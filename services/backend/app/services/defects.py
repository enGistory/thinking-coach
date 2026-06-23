from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appeal
from app.repositories.defects import DefectMemoryRepository


class DefectMemoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DefectMemoryService:
    def __init__(self, *, session: AsyncSession) -> None:
        self._repository = DefectMemoryRepository(session)

    async def sync_report(self, *, report_id: UUID, user_id: UUID) -> list[str]:
        return await self._repository.sync_completed_report(report_id=report_id, user_id=user_id)

    async def create_appeal(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        appeal_type: str,
        reason: str,
        issue_id: UUID | None,
        defect_code: str | None,
    ) -> Appeal:
        appeal = await self._repository.create_appeal(
            user_id=user_id,
            session_id=session_id,
            appeal_type=appeal_type,
            reason=reason,
            issue_id=issue_id,
            defect_code=defect_code,
        )
        if appeal is None:
            raise DefectMemoryError("DEFECT_APPEAL_TARGET_NOT_FOUND")
        return appeal

    async def review_appeal(
        self,
        *,
        appeal_id: UUID,
        user_id: UUID,
        accepted: bool,
        resolution: str,
    ) -> Appeal:
        appeal = await self._repository.review_appeal(
            appeal_id=appeal_id,
            user_id=user_id,
            accepted=accepted,
            resolution=resolution,
        )
        if appeal is None:
            raise DefectMemoryError("DEFECT_APPEAL_NOT_FOUND")
        return appeal
