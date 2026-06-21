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
from app.repositories.training_policy import TrainingPolicyRepository
from app.schemas.auth import TrainingPolicyPayload, TrainingPolicyResponse

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


def _policy_response(policy: UserTrainingPolicy) -> TrainingPolicyResponse:
    return TrainingPolicyResponse(
        user_id=policy.user_id,
        windows=policy.windows,
        quiet_hours=policy.quiet_hours,
        daily_max=policy.daily_max,
        retention_days=policy.retention_days,
        timezone=policy.timezone,
    )
