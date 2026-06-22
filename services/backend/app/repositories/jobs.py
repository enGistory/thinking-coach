from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIJob

TRANSCRIBE_ATTEMPT_JOB = "TRANSCRIBE_ATTEMPT"
TRANSCRIBE_JOB_LEASE_SECONDS = 30 * 60
TRANSCRIBE_MAX_RETRIES = 2


class AIJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_transcribe_attempt(self, attempt_id: UUID) -> None:
        statement = (
            insert(AIJob)
            .values(
                job_type=TRANSCRIBE_ATTEMPT_JOB,
                payload={"attempt_id": str(attempt_id)},
                status="PENDING",
                idempotency_key=f"transcribe_attempt:{attempt_id}",
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(statement)

    async def claim_next(self, job_type: str) -> AIJob | None:
        lease_expires_before = datetime.now(UTC) - timedelta(seconds=TRANSCRIBE_JOB_LEASE_SECONDS)
        result = await self._session.execute(
            select(AIJob)
            .where(
                AIJob.job_type == job_type,
                or_(
                    AIJob.status == "PENDING",
                    and_(AIJob.status == "RUNNING", AIJob.locked_at < lease_expires_before),
                ),
            )
            .order_by(AIJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        job.status = "RUNNING"
        job.locked_at = datetime.now(UTC)
        await self._session.flush()
        return job

    async def get_by_id(self, job_id: UUID) -> AIJob | None:
        result = await self._session.execute(select(AIJob).where(AIJob.id == job_id))
        return result.scalar_one_or_none()

    async def mark_succeeded(self, job: AIJob) -> None:
        job.status = "SUCCEEDED"
        job.error_code = None
        await self._session.flush()

    async def mark_retryable_failure(self, job: AIJob, error_code: str) -> None:
        job.error_code = error_code
        job.locked_at = None
        if job.retry_count < TRANSCRIBE_MAX_RETRIES:
            job.retry_count += 1
            job.status = "PENDING"
        else:
            job.status = "FAILED"
        await self._session.flush()

    async def list_failed(self, limit: int) -> list[AIJob]:
        result = await self._session.execute(
            select(AIJob)
            .where(AIJob.status == "FAILED")
            .order_by(AIJob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
