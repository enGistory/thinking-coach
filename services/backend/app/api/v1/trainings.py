from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db.models import AppUser, TrainingSession, VoiceAttempt
from app.db.session import get_session
from app.repositories.training_policy import TrainingPolicyRepository
from app.repositories.trainings import TrainingRepository
from app.schemas.training import (
    AudioUploadResponse,
    CreateAttemptRequest,
    TrainingSessionResponse,
    VoiceAttemptResponse,
)
from app.services.audio_storage import (
    AudioStorageError,
    resolve_stored_audio_path,
    save_audio_upload,
)

router = APIRouter(prefix="/api/v1", tags=["trainings"])


@router.post("/trainings/current", response_model=TrainingSessionResponse)
async def create_current_training_session(
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingSessionResponse:
    training_session = await TrainingRepository(session).get_or_create_current_audio_session(
        current_user.id
    )
    await session.commit()
    return _training_session_response(training_session)


@router.post(
    "/trainings/{session_id}/attempts",
    response_model=VoiceAttemptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_attempt(
    session_id: UUID,
    payload: CreateAttemptRequest,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoiceAttemptResponse:
    repository = TrainingRepository(session)
    training_session = await repository.get_owned_session(
        session_id=session_id,
        user_id=current_user.id,
    )
    if training_session is None:
        raise _not_found()

    attempt = await repository.get_or_create_attempt(
        training_session=training_session,
        stage=payload.stage,
        round_number=payload.round,
    )
    await session.commit()
    return _attempt_response(attempt)


@router.put("/attempts/{attempt_id}/audio", response_model=AudioUploadResponse)
async def upload_attempt_audio(
    attempt_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    duration_ms: Annotated[int, Form(gt=0)],
    checksum_sha256: Annotated[str, Form(pattern=r"^[0-9a-f]{64}$")],
    audio: Annotated[UploadFile, File()],
) -> AudioUploadResponse:
    settings = get_settings()
    attempt = await _get_owned_attempt_for_update(session, attempt_id, current_user.id)
    if attempt.upload_status == "UPLOADED":
        if attempt.checksum_sha256 == checksum_sha256:
            return _audio_upload_response(attempt)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uploaded audio cannot be overwritten",
        )

    if duration_ms > settings.max_audio_seconds * 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio duration exceeds the configured limit",
        )

    max_bytes = settings.max_audio_mb * 1024 * 1024
    try:
        stored = await save_audio_upload(
            audio_root=settings.audio_root_resolved,
            upload=audio,
            user_id=current_user.id,
            session_id=attempt.session_id,
            attempt_id=attempt.id,
            expected_checksum=checksum_sha256,
            max_bytes=max_bytes,
        )
    except AudioStorageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc

    attempt.audio_path = stored.relative_path
    attempt.mime_type = stored.mime_type
    attempt.duration_ms = duration_ms
    attempt.size_bytes = stored.size_bytes
    attempt.checksum_sha256 = stored.checksum_sha256
    attempt.upload_status = "UPLOADED"
    attempt.retention_at = datetime.now(UTC) + timedelta(
        days=await _retention_days(session, current_user.id, settings)
    )
    attempt.uploaded_at = datetime.now(UTC)
    await session.commit()
    return _audio_upload_response(attempt)


@router.get("/attempts/{attempt_id}/audio")
async def get_attempt_audio(
    attempt_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    settings = get_settings()
    attempt = await _get_owned_attempt(session, attempt_id, current_user.id)
    if attempt.upload_status != "UPLOADED" or attempt.audio_path is None:
        raise _not_found()

    try:
        audio_path = resolve_stored_audio_path(settings.audio_root_resolved, attempt.audio_path)
    except AudioStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.code,
        ) from exc
    if not audio_path.exists() or not audio_path.is_file():
        raise _not_found()

    return FileResponse(
        audio_path,
        media_type=attempt.mime_type or "application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


async def _get_owned_attempt_for_update(
    session: AsyncSession,
    attempt_id: UUID,
    user_id: UUID,
) -> VoiceAttempt:
    attempt = await TrainingRepository(session).get_owned_attempt_for_update(
        attempt_id=attempt_id,
        user_id=user_id,
    )
    if attempt is None:
        raise _not_found()
    return attempt


async def _get_owned_attempt(
    session: AsyncSession,
    attempt_id: UUID,
    user_id: UUID,
) -> VoiceAttempt:
    attempt = await TrainingRepository(session).get_owned_attempt(
        attempt_id=attempt_id,
        user_id=user_id,
    )
    if attempt is None:
        raise _not_found()
    return attempt


async def _retention_days(session: AsyncSession, user_id: UUID, settings: Settings) -> int:
    policy = await TrainingPolicyRepository(session).get_for_user(user_id)
    if policy is None:
        return settings.audio_retention_days
    return policy.retention_days


def _training_session_response(training_session: TrainingSession) -> TrainingSessionResponse:
    return TrainingSessionResponse(
        id=training_session.id,
        thread_id=training_session.thread_id,
        stage=training_session.stage,
        created_at=training_session.created_at,
    )


def _attempt_response(attempt: VoiceAttempt) -> VoiceAttemptResponse:
    return VoiceAttemptResponse(
        id=attempt.id,
        session_id=attempt.session_id,
        stage=attempt.stage,
        round=attempt.round,
        upload_status=attempt.upload_status,
        mime_type=attempt.mime_type,
        duration_ms=attempt.duration_ms,
        size_bytes=attempt.size_bytes,
        checksum_sha256=attempt.checksum_sha256,
        uploaded_at=attempt.uploaded_at,
    )


def _audio_upload_response(attempt: VoiceAttempt) -> AudioUploadResponse:
    return AudioUploadResponse(
        id=attempt.id,
        session_id=attempt.session_id,
        stage=attempt.stage,
        round=attempt.round,
        upload_status=attempt.upload_status,
        mime_type=attempt.mime_type,
        duration_ms=attempt.duration_ms,
        size_bytes=attempt.size_bytes,
        checksum_sha256=attempt.checksum_sha256,
        uploaded_at=attempt.uploaded_at,
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Training resource not found",
    )
