from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token, generate_refresh_token, hash_secret
from app.db.models import AppUser, RefreshToken
from app.repositories.auth import RefreshTokenRepository


@dataclass(frozen=True)
class IssuedTokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


async def issue_token_pair(
    session: AsyncSession,
    user: AppUser,
    settings: Settings,
) -> IssuedTokenPair:
    refresh_token = generate_refresh_token()
    await RefreshTokenRepository(session).create_token(
        user_id=user.id,
        token_hash=hash_secret(refresh_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_days),
    )
    return IssuedTokenPair(
        access_token=create_access_token(user.id, user.role, settings),
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_minutes * 60,
    )


def refresh_token_is_owned_by_user(token: RefreshToken, user: AppUser) -> bool:
    return token.user_id == user.id
