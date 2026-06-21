from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIJob


class AIJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_failed(self, limit: int) -> list[AIJob]:
        result = await self._session.execute(
            select(AIJob)
            .where(AIJob.status == "FAILED")
            .order_by(AIJob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
