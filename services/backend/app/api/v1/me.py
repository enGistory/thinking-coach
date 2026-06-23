from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import AppUser, UserTrainingPolicy
from app.db.session import get_session
from app.domain.training_policy import default_training_policy
from app.repositories.defects import DefectMemoryRepository, DefectOccurrenceRow, DefectProfileRow
from app.repositories.training_policy import TrainingPolicyRepository
from app.schemas.auth import TrainingPolicyPayload, TrainingPolicyResponse
from app.schemas.defects import DefectOccurrenceResponse, DefectProfileResponse

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("/training-policy", response_model=TrainingPolicyResponse)
async def get_training_policy(
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingPolicyResponse:
    repository = TrainingPolicyRepository(session)
    policy = await repository.get_for_user(current_user.id)
    if policy is None:
        settings = get_settings()
        policy = await repository.create_for_user(
            user_id=current_user.id,
            policy=default_training_policy(settings.tz, settings.audio_retention_days),
        )
        await session.commit()
    return _policy_response(policy)


@router.put("/training-policy", response_model=TrainingPolicyResponse)
async def update_training_policy(
    payload: TrainingPolicyPayload,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingPolicyResponse:
    updated = await TrainingPolicyRepository(session).update_for_user(
        user_id=current_user.id,
        policy=payload.model_dump(mode="json"),
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training policy not found",
        )
    await session.commit()
    return _policy_response(updated)


@router.get("/defects", response_model=list[DefectProfileResponse])
async def list_defect_profiles(
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DefectProfileResponse]:
    rows = await DefectMemoryRepository(session).list_profiles(current_user.id)
    return [_profile_response(row) for row in rows]


@router.get("/defects/{defect_code}/occurrences", response_model=list[DefectOccurrenceResponse])
async def list_defect_occurrences(
    defect_code: str,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DefectOccurrenceResponse]:
    rows = await DefectMemoryRepository(session).list_occurrences(
        user_id=current_user.id,
        defect_code=defect_code,
    )
    return [_occurrence_response(row) for row in rows]


def _policy_response(policy: UserTrainingPolicy) -> TrainingPolicyResponse:
    return TrainingPolicyResponse(
        user_id=policy.user_id,
        windows=policy.windows,
        quiet_hours=policy.quiet_hours,
        daily_max=policy.daily_max,
        retention_days=policy.retention_days,
        timezone=policy.timezone,
    )


def _profile_response(row: DefectProfileRow) -> DefectProfileResponse:
    return DefectProfileResponse(
        code=row.definition.code,
        name=row.definition.name,
        description=row.definition.description,
        state=row.profile.state,
        severity=row.profile.severity,
        frequency=row.profile.frequency,
        recurrence=row.profile.recurrence,
        priority=row.profile.priority,
        confidence=row.profile.confidence,
        active_occurrence_count=row.profile.active_occurrence_count,
        suspended_occurrence_count=row.profile.suspended_occurrence_count,
        scenario_count=row.profile.scenario_count,
        last_seen_at=row.profile.last_seen_at,
    )


def _occurrence_response(row: DefectOccurrenceRow) -> DefectOccurrenceResponse:
    return DefectOccurrenceResponse(
        id=row.occurrence.id,
        session_id=row.occurrence.session_id,
        issue_id=row.occurrence.issue_id,
        status=row.occurrence.status,
        attempt_stage=row.occurrence.attempt_stage,
        scenario_key=row.occurrence.scenario_key,
        severity=row.occurrence.severity,
        confidence=row.occurrence.confidence,
        quote=row.evidence.quote,
        start_ms=row.evidence.start_ms,
        end_ms=row.evidence.end_ms,
        explanation=row.evidence.explanation,
        missing_information=row.evidence.missing_information,
        correction_rule=row.evidence.correction_rule,
        similarity_reasons=row.similarity_reasons,
        created_at=row.occurrence.created_at,
    )
