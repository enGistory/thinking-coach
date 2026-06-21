from __future__ import annotations

from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.dependencies import require_admin
from app.core.config import get_settings
from app.core.security import hash_password, hash_secret
from app.db.models import AppUser
from app.db.session import get_session
from app.domain.training_policy import default_training_policy
from app.repositories.auth import UserRepository
from app.repositories.invitations import InvitationRepository
from app.repositories.training_policy import TrainingPolicyRepository
from app.schemas.auth import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    CreateInvitationResponse,
    TokenPair,
)
from app.services.auth_tokens import issue_token_pair

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])
admin_router = APIRouter(prefix="/api/v1/admin/invitations", tags=["admin"])


@router.post("/accept", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    now = datetime.now(UTC)
    invitation_repository = InvitationRepository(session)
    invitation = await invitation_repository.get_usable_by_hash(hash_secret(payload.code), now)
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation code",
        )

    settings = get_settings()
    user_repository = UserRepository(session)
    if await user_repository.get_by_nickname(payload.nickname) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nickname already exists",
        )

    try:
        user = await user_repository.create_user(
            nickname=payload.nickname,
            password_hash=hash_password(payload.password),
            role=invitation.role,
        )
        await TrainingPolicyRepository(session).create_for_user(
            user_id=user.id,
            policy=default_training_policy(settings.tz, settings.audio_retention_days),
        )
        invitation_repository.mark_used(invitation, user.id, now)
        issued = await issue_token_pair(session, user, settings)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nickname already exists",
        ) from exc

    return TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
    )


@admin_router.post("", response_model=CreateInvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: CreateInvitationRequest,
    current_admin: Annotated[AppUser, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CreateInvitationResponse:
    code = token_urlsafe(24)
    expires_at = datetime.now(UTC) + timedelta(days=payload.expires_in_days)
    invitation = await InvitationRepository(session).create_invitation(
        code_hash=hash_secret(code),
        created_by_user_id=current_admin.id,
        expires_at=expires_at,
    )
    await session.commit()
    return CreateInvitationResponse(id=invitation.id, code=code, expires_at=invitation.expires_at)
