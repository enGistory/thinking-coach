from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Invitation


class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_invitation(
        self,
        *,
        code_hash: str,
        created_by_user_id: UUID,
        expires_at: datetime,
        role: str = "USER",
    ) -> Invitation:
        invitation = Invitation(
            code_hash=code_hash,
            created_by_user_id=created_by_user_id,
            expires_at=expires_at,
            role=role,
        )
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def get_usable_by_hash(self, code_hash: str, now: datetime) -> Invitation | None:
        statement = (
            select(Invitation)
            .where(
                Invitation.code_hash == code_hash,
                Invitation.used_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now,
            )
            .with_for_update()
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def mark_used(self, invitation: Invitation, user_id: UUID, now: datetime) -> None:
        invitation.used_by_user_id = user_id
        invitation.used_at = now
