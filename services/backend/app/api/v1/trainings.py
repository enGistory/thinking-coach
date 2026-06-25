from __future__ import annotations

from datetime import UTC, datetime, timedelta
from random import Random
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.ai.providers.factory import create_provider_bundle
from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db.models import AppUser, SourceBundle, TrainingSession, VoiceAttempt
from app.db.session import get_session, get_sessionmaker
from app.graphs.voice_training import (
    DEV_QUESTION_TEXT,
    FINAL_PROMPT_TEXT,
    VoiceTrainingDeps,
    load_voice_training_state,
)
from app.repositories.jobs import (
    AIJobRepository,
    graph_resume_idempotency_key,
)
from app.repositories.source_questions import SourceQuestionRepository
from app.repositories.training_policy import TrainingPolicyRepository
from app.repositories.trainings import TrainingRepository
from app.repositories.transcripts import (
    TranscriptBundle,
    TranscriptCorrectionRejected,
    TranscriptRepository,
)
from app.schemas.defects import AppealRequest, AppealResponse
from app.schemas.source_question import (
    DuplicateComplaintRequest,
    DuplicateComplaintResponse,
    ProvenanceClaimResponse,
    ProvenanceMappingResponse,
    ProvenanceSourceResponse,
    SourceLevel,
    SourceSummaryResponse,
    SupportStatus,
    TrainingProvenanceResponse,
)
from app.schemas.training import (
    AttemptTranscriptResponse,
    AudioUploadResponse,
    CreateAttemptRequest,
    ResumeTrainingRequest,
    ResumeTrainingResponse,
    TrainingAwaitingInputResponse,
    TrainingSessionResponse,
    TrainingStateResponse,
    TranscriptCorrectionRequest,
    TranscriptSegmentResponse,
    TranscriptWordResponse,
    VoiceAttemptResponse,
)
from app.services.audio_storage import (
    AudioStorageError,
    resolve_stored_audio_path,
    save_audio_upload,
)
from app.services.defects import DefectMemoryError, DefectMemoryService
from app.services.push import PyWebPushSender
from app.services.question_duplicates import DuplicateQuestionError, DuplicateQuestionService
from app.services.random_strike import RandomStrikeError, RandomStrikeService

router = APIRouter(prefix="/api/v1", tags=["trainings"])

WAITING_ATTEMPT_SLOTS = {
    "ACCEPTED": ("FIRST", 1),
    "QUESTION_EXPOSED": ("FIRST", 1),
    "WAIT_FIRST_AUDIO": ("FIRST", 1),
    "WAIT_FOLLOWUP_AUDIO": ("FOLLOWUP", 1),
    "WAIT_FINAL_AUDIO": ("FINAL", 1),
}
PROCESSING_STAGE_BY_ATTEMPT_STAGE = {
    "FIRST": "PROCESS_FIRST",
    "FOLLOWUP": "PROCESS_FOLLOWUP",
    "FINAL": "EVALUATING",
}


@router.get("/trainings/current", response_model=TrainingSessionResponse)
async def get_current_training_session(
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingSessionResponse:
    training_session = await TrainingRepository(session).current_visible_session(
        current_user.id,
        now=datetime.now(UTC),
    )
    if training_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NO_CURRENT_TRAINING"},
        )
    return _training_session_response(training_session)


@router.post("/trainings/{session_id}/accept", response_model=TrainingSessionResponse)
async def accept_training(
    session_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingSessionResponse:
    training_session = await TrainingRepository(session).get_owned_session_for_update(
        session_id=session_id,
        user_id=current_user.id,
    )
    if training_session is None:
        raise _not_found()
    settings = get_settings()
    try:
        await RandomStrikeService(
            session=session,
            settings=settings,
            push_sender=PyWebPushSender(settings),
        ).accept(training_session=training_session, now=datetime.now(UTC))
    except RandomStrikeError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code},
        ) from exc
    await session.commit()
    return _training_session_response(training_session)


@router.post("/trainings/{session_id}/defer", response_model=TrainingSessionResponse)
async def defer_training(
    session_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingSessionResponse:
    training_session = await TrainingRepository(session).get_owned_session_for_update(
        session_id=session_id,
        user_id=current_user.id,
    )
    if training_session is None:
        raise _not_found()
    settings = get_settings()
    try:
        await RandomStrikeService(
            session=session,
            settings=settings,
            push_sender=PyWebPushSender(settings),
        ).defer(
            training_session=training_session,
            now=datetime.now(UTC),
            rng=Random(f"defer:{training_session.id}:{training_session.deferred_count}"),
        )
    except RandomStrikeError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code},
        ) from exc
    await session.commit()
    return _training_session_response(training_session)


@router.post("/trainings/{session_id}/abandon", response_model=TrainingSessionResponse)
async def abandon_training(
    session_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingSessionResponse:
    training_session = await TrainingRepository(session).get_owned_session_for_update(
        session_id=session_id,
        user_id=current_user.id,
    )
    if training_session is None:
        raise _not_found()
    settings = get_settings()
    try:
        await RandomStrikeService(
            session=session,
            settings=settings,
            push_sender=PyWebPushSender(settings),
        ).abandon(training_session=training_session)
    except RandomStrikeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code},
        ) from exc
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
    _ensure_attempt_matches_session_stage(training_session, payload)

    attempt = await repository.get_or_create_attempt(
        training_session=training_session,
        stage=payload.stage,
        round_number=payload.round,
    )
    await session.commit()
    return _attempt_response(attempt)


@router.get("/trainings/{session_id}/state", response_model=TrainingStateResponse)
async def get_training_state(
    session_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingStateResponse:
    training_session = await TrainingRepository(session).get_owned_session(
        session_id=session_id,
        user_id=current_user.id,
    )
    if training_session is None:
        raise _not_found()

    graph_state: dict[str, object] = {}
    if training_session.stage in {"WAIT_FOLLOWUP_AUDIO", "WAIT_FINAL_AUDIO"}:
        graph_state = dict(
            await load_voice_training_state(
                deps=_voice_training_deps(get_settings()),
                thread_id=training_session.thread_id,
            )
        )
    return await _training_state_response(session, training_session, graph_state)


@router.get(
    "/trainings/{session_id}/provenance",
    response_model=TrainingProvenanceResponse,
)
async def get_training_provenance(
    session_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingProvenanceResponse:
    provenance = await SourceQuestionRepository(session).get_owned_provenance(
        session_id=session_id,
        user_id=current_user.id,
    )
    if provenance is None:
        raise _not_found()
    return TrainingProvenanceResponse(
        session_id=provenance.training_session.id,
        question_id=provenance.question.id,
        prompt=provenance.question.prompt,
        source_summary=_source_summary_from_bundle(provenance.source_bundle),
        sources=[
            ProvenanceSourceResponse(
                id=source.id,
                title=source.title,
                publisher=source.publisher,
                url=source.url,
                level=cast(SourceLevel, source.level),
                published_at=source.published_at,
                accessed_at=source.accessed_at,
                snapshot_hash=source.snapshot_hash,
                claims=[
                    ProvenanceClaimResponse(
                        id=claim.id,
                        claim_text=claim.claim_text,
                        locator=claim.locator,
                        excerpt=claim.excerpt,
                        support_status=cast(SupportStatus, claim.support_status),
                    )
                    for claim in provenance.claims_by_source.get(source.id, [])
                ],
            )
            for source in provenance.sources
        ],
        mappings=[
            ProvenanceMappingResponse(
                sentence_index=mapping.sentence_index,
                sentence_text=mapping.sentence_text,
                claim_ids=[mapping.claim_id],
            )
            for mapping in provenance.mappings
        ],
        hypothetical_assumptions=provenance.question.hypothetical_assumptions_json,
    )


@router.post(
    "/trainings/{session_id}/resume",
    response_model=ResumeTrainingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_training(
    session_id: UUID,
    payload: ResumeTrainingRequest,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResumeTrainingResponse:
    repository = TrainingRepository(session)
    training_session = await repository.get_owned_session_for_update(
        session_id=session_id,
        user_id=current_user.id,
    )
    if training_session is None:
        raise _not_found()

    attempt = await repository.get_owned_attempt(
        attempt_id=payload.attempt_id,
        user_id=current_user.id,
    )
    if attempt is None or attempt.session_id != training_session.id:
        raise _not_found()
    if attempt.upload_status != "UPLOADED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attempt audio must be uploaded before resume",
        )
    if attempt.stage != payload.stage or attempt.round != payload.round:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume payload does not match attempt slot",
        )

    idempotency_key = graph_resume_idempotency_key(
        session_id=training_session.id,
        attempt_id=attempt.id,
        stage=payload.stage,
        round_number=payload.round,
    )
    job_repo = AIJobRepository(session)
    job = await job_repo.get_by_idempotency_key(idempotency_key)
    if job is None:
        _ensure_resume_matches_session_stage(training_session, payload)
        training_session.stage = PROCESSING_STAGE_BY_ATTEMPT_STAGE[payload.stage]
        job = await job_repo.enqueue_graph_resume(
            session_id=training_session.id,
            attempt_id=attempt.id,
            stage=payload.stage,
            round_number=payload.round,
        )

    await session.commit()
    return ResumeTrainingResponse(job_id=job.id, session_stage=training_session.stage)


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
            await _ensure_pending_transcript(session, attempt)
            await session.commit()
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
    await _ensure_pending_transcript(session, attempt)
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


@router.get("/attempts/{attempt_id}/transcript", response_model=AttemptTranscriptResponse)
async def get_attempt_transcript(
    attempt_id: UUID,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttemptTranscriptResponse:
    bundle = await TranscriptRepository(session).get_owned_bundle(
        attempt_id=attempt_id,
        user_id=current_user.id,
    )
    if bundle is None:
        raise _not_found()
    return _transcript_response(bundle)


@router.patch(
    "/attempts/{attempt_id}/transcript-correction",
    response_model=AttemptTranscriptResponse,
)
async def correct_attempt_transcript(
    attempt_id: UUID,
    payload: TranscriptCorrectionRequest,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttemptTranscriptResponse:
    try:
        bundle = await TranscriptRepository(session).apply_segment_correction(
            attempt_id=attempt_id,
            segment_id=payload.segment_id,
            user_id=current_user.id,
            corrected_text=payload.corrected_text,
            reason=payload.reason,
        )
    except TranscriptCorrectionRejected as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc
    if bundle is None:
        raise _not_found()
    await session.commit()
    return _transcript_response(bundle)


@router.post(
    "/trainings/{session_id}/appeals",
    response_model=AppealResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_training_appeal(
    session_id: UUID,
    payload: AppealRequest,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AppealResponse:
    try:
        appeal = await DefectMemoryService(session=session).create_appeal(
            user_id=current_user.id,
            session_id=session_id,
            appeal_type=payload.type,
            reason=payload.reason,
            issue_id=payload.issue_id,
            defect_code=payload.defect_code,
        )
    except DefectMemoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.code,
        ) from exc
    await session.commit()
    return AppealResponse(
        id=appeal.id,
        session_id=appeal.session_id,
        issue_id=appeal.issue_id,
        defect_code=appeal.defect_code,
        type=appeal.type,
        status=appeal.status,
        reason=appeal.reason,
        resolution=appeal.resolution,
        created_at=appeal.created_at,
    )


@router.post(
    "/trainings/{session_id}/duplicate-complaints",
    response_model=DuplicateComplaintResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_duplicate_complaint(
    session_id: UUID,
    payload: DuplicateComplaintRequest,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DuplicateComplaintResponse:
    try:
        result = await DuplicateQuestionService(session=session).create_complaint(
            user_id=current_user.id,
            session_id=session_id,
            reason=payload.reason,
            duplicate_type=payload.duplicate_type,
            similar_question_id=payload.similar_question_id,
        )
    except DuplicateQuestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.code,
        ) from exc
    await session.commit()
    return DuplicateComplaintResponse(
        id=result.complaint.id,
        session_id=result.complaint.session_id,
        question_id=result.complaint.question_id,
        template_family=result.complaint.template_family,
        status="ACCEPTED",
        replacement_job_id=result.replacement_job.id,
        created_at=result.complaint.created_at,
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


async def _ensure_pending_transcript(session: AsyncSession, attempt: VoiceAttempt) -> None:
    await TranscriptRepository(session).ensure_pending(attempt.id)


def _ensure_attempt_matches_session_stage(
    training_session: TrainingSession,
    payload: CreateAttemptRequest,
) -> None:
    expected = WAITING_ATTEMPT_SLOTS.get(training_session.stage)
    if expected != (payload.stage, payload.round):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attempt slot is not open for the current session stage",
        )


def _ensure_resume_matches_session_stage(
    training_session: TrainingSession,
    payload: ResumeTrainingRequest,
) -> None:
    expected = WAITING_ATTEMPT_SLOTS.get(training_session.stage)
    if expected != (payload.stage, payload.round):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume slot is not open for the current session stage",
        )


def _voice_training_deps(settings: Settings) -> VoiceTrainingDeps:
    bundle = create_provider_bundle(settings)
    return VoiceTrainingDeps(
        settings=settings,
        sessionmaker=get_sessionmaker(),
        llm_provider=bundle.llm,
        stt_provider=bundle.stt,
    )


async def _training_state_response(
    session: AsyncSession,
    training_session: TrainingSession,
    graph_state: dict[str, object],
) -> TrainingStateResponse:
    return TrainingStateResponse(
        id=training_session.id,
        thread_id=training_session.thread_id,
        stage=training_session.stage,
        awaiting=await _awaiting_input_response(session, training_session, graph_state),
        current_attempt=await _current_attempt_response(session, training_session),
        source_summary=await _visible_source_summary_response(session, training_session),
        created_at=training_session.created_at,
        updated_at=training_session.updated_at,
        completed_at=training_session.completed_at,
    )


async def _question_text(session: AsyncSession, question_id: UUID | None) -> str | None:
    if question_id is None:
        return None
    question = await SourceQuestionRepository(session).get_question(question_id)
    return question.prompt if question is not None else None


async def _source_summary_response(
    session: AsyncSession,
    question_id: UUID | None,
) -> SourceSummaryResponse | None:
    if question_id is None:
        return None
    bundle = await SourceQuestionRepository(session).get_source_bundle_for_question(question_id)
    return _source_summary_from_bundle(bundle) if bundle is not None else None


async def _visible_source_summary_response(
    session: AsyncSession,
    training_session: TrainingSession,
) -> SourceSummaryResponse | None:
    if training_session.stage in {"SCHEDULED", "NOTIFIED", "EXPIRED"}:
        return None
    return await _source_summary_response(session, training_session.question_id)


def _source_summary_from_bundle(bundle: SourceBundle) -> SourceSummaryResponse:
    return SourceSummaryResponse(
        source_count=bundle.source_count,
        highest_source_level=cast(SourceLevel | None, bundle.highest_source_level),
        credential=bundle.credential,
    )


async def _awaiting_input_response(
    session: AsyncSession,
    training_session: TrainingSession,
    graph_state: dict[str, object],
) -> TrainingAwaitingInputResponse | None:
    session_stage = training_session.stage
    if session_stage in {"ACCEPTED", "QUESTION_EXPOSED", "WAIT_FIRST_AUDIO"}:
        question_text = await _question_text(session, training_session.question_id)
        return TrainingAwaitingInputResponse(
            type="FIRST_ANSWER",
            stage="FIRST",
            round=1,
            text=question_text or DEV_QUESTION_TEXT,
        )
    if session_stage == "WAIT_FOLLOWUP_AUDIO":
        followup_text = graph_state.get("followup_text")
        return TrainingAwaitingInputResponse(
            type="FOLLOWUP_QUESTION",
            stage="FOLLOWUP",
            round=1,
            text=(
                followup_text
                if isinstance(followup_text, str) and followup_text
                else "请补充你刚才判断中最关键的依据、未知和取舍。"
            ),
        )
    if session_stage == "WAIT_FINAL_AUDIO":
        final_text = graph_state.get("final_prompt_text")
        return TrainingAwaitingInputResponse(
            type="FINAL_ANSWER",
            stage="FINAL",
            round=1,
            text=final_text if isinstance(final_text, str) and final_text else FINAL_PROMPT_TEXT,
        )
    return None


async def _current_attempt_response(
    session: AsyncSession,
    training_session: TrainingSession,
) -> VoiceAttemptResponse | None:
    expected = WAITING_ATTEMPT_SLOTS.get(training_session.stage)
    if expected is None:
        return None
    stage, round_number = expected
    attempt = await TrainingRepository(session).get_attempt_by_slot(
        session_id=training_session.id,
        stage=stage,
        round_number=round_number,
    )
    if attempt is None:
        return None
    return _attempt_response(attempt)


def _training_session_response(training_session: TrainingSession) -> TrainingSessionResponse:
    return TrainingSessionResponse(
        id=training_session.id,
        thread_id=training_session.thread_id,
        stage=training_session.stage,
        scheduled_at=training_session.scheduled_at,
        notification_expires_at=training_session.notification_expires_at,
        accepted_at=training_session.accepted_at,
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


def _transcript_response(bundle: TranscriptBundle) -> AttemptTranscriptResponse:
    return AttemptTranscriptResponse(
        attempt_id=bundle.transcript.attempt_id,
        status=bundle.transcript.status,
        raw_text=bundle.transcript.raw_text,
        corrected_text=bundle.transcript.corrected_text,
        language=bundle.transcript.language,
        error_code=bundle.transcript.error_code,
        metrics=bundle.transcript.metrics_json,
        segments=[
            TranscriptSegmentResponse(
                id=segment.id,
                segment_index=segment.segment_index,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                raw_text=segment.raw_text,
                corrected_text=segment.corrected_text,
                words=[_word_response(word) for word in segment.words_json],
            )
            for segment in bundle.segments
        ],
    )


def _word_response(word: dict[str, object]) -> TranscriptWordResponse:
    text = word.get("text")
    start_ms = word.get("start_ms")
    end_ms = word.get("end_ms")
    confidence = word.get("confidence")
    return TranscriptWordResponse(
        text=text if isinstance(text, str) else "",
        start_ms=start_ms if isinstance(start_ms, int) else 0,
        end_ms=end_ms if isinstance(end_ms, int) else 0,
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Training resource not found",
    )
