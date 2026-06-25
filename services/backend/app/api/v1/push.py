from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.dependencies import get_current_user
from app.core.config import ConfigurationError, get_settings
from app.db.models import AppUser
from app.db.session import get_session
from app.repositories.push import PushSubscriptionRepository
from app.schemas.push import (
    PushPublicKeyResponse,
    PushSubscriptionRequest,
    PushSubscriptionResponse,
)

router = APIRouter(prefix="/api/v1/push", tags=["push"])


@router.get("/public-key", response_model=PushPublicKeyResponse)
async def get_push_public_key() -> PushPublicKeyResponse:
    settings = get_settings()
    try:
        settings.validate_push()
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code},
        ) from exc
    return PushPublicKeyResponse(public_key=settings.web_push_vapid_public_key)


@router.post(
    "/subscriptions",
    response_model=PushSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_push_subscription(
    payload: PushSubscriptionRequest,
    current_user: Annotated[AppUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    user_agent: Annotated[str | None, Header(alias="user-agent")] = None,
) -> PushSubscriptionResponse:
    subscription = await PushSubscriptionRepository(session).upsert_subscription(
        user_id=current_user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=payload.user_agent or user_agent or "",
    )
    await session.commit()
    return PushSubscriptionResponse(
        id=subscription.id,
        endpoint=subscription.endpoint,
        active=subscription.active,
        created_at=subscription.created_at,
    )
