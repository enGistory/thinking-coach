from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppUser, RefreshToken


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(
        self,
        *,
        nickname: str,
        password_hash: str,
        role: str,
        status: str = "ACTIVE",
    ) -> AppUser:
        user = AppUser(
            nickname=nickname,
            password_hash=password_hash,
            role=role,
            status=status,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_by_nickname(self, nickname: str) -> AppUser | None:
        result = await self._session.execute(select(AppUser).where(AppUser.nickname == nickname))
        return result.scalar_one_or_none()

    async def get_active_by_id(self, user_id: UUID) -> AppUser | None:
        result = await self._session.execute(
            select(AppUser).where(AppUser.id == user_id, AppUser.status == "ACTIVE")
        )
        return result.scalar_one_or_none()

    async def list_active_users(self) -> list[AppUser]:
        result = await self._session.execute(
            select(AppUser)
            .where(AppUser.status == "ACTIVE", AppUser.role == "USER")
            .order_by(AppUser.created_at)
        )
        return list(result.scalars().all())

    async def has_admin(self) -> bool:
        result = await self._session.execute(
            select(AppUser.id).where(AppUser.role == "ADMIN").limit(1)
        )
        return result.scalar_one_or_none() is not None


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_valid_by_hash(self, token_hash: str, now: datetime) -> RefreshToken | None:
        statement = (
            select(RefreshToken)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .with_for_update()
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def revoke_by_hash(self, token_hash: str, now: datetime) -> None:
        result = await self._session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
        )
        token = result.scalar_one_or_none()
        if token is not None:
            token.revoked_at = now

    def revoke(self, token: RefreshToken, now: datetime) -> None:
        token.revoked_at = now
