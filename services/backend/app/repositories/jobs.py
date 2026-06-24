from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIJob

GRAPH_RESUME_JOB = "GRAPH_RESUME"
TRANSCRIBE_ATTEMPT_JOB = "TRANSCRIBE_ATTEMPT"
EVALUATE_SESSION_JOB = "EVALUATE_SESSION"
PREPARE_QUESTIONS_JOB = "PREPARE_QUESTIONS"
AI_JOB_LEASE_SECONDS = 30 * 60
AI_JOB_MAX_RETRIES = 2
TRANSCRIBE_JOB_LEASE_SECONDS = AI_JOB_LEASE_SECONDS
TRANSCRIBE_MAX_RETRIES = AI_JOB_MAX_RETRIES


def graph_resume_idempotency_key(
    *,
    session_id: UUID,
    attempt_id: UUID,
    stage: str,
    round_number: int,
) -> str:
    return f"graph_resume:{session_id}:{stage.lower()}:{round_number}:{attempt_id}"


def evaluation_idempotency_key(session_id: UUID) -> str:
    return f"evaluate_session:{session_id}"


def prepare_questions_idempotency_key(user_id: UUID) -> str:
    return f"prepare_questions:{user_id}"


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

    async def enqueue_graph_resume(
        self,
        *,
        session_id: UUID,
        attempt_id: UUID,
        stage: str,
        round_number: int,
    ) -> AIJob:
        idempotency_key = graph_resume_idempotency_key(
            session_id=session_id,
            attempt_id=attempt_id,
            stage=stage,
            round_number=round_number,
        )
        statement = (
            insert(AIJob)
            .values(
                job_type=GRAPH_RESUME_JOB,
                payload={
                    "session_id": str(session_id),
                    "attempt_id": str(attempt_id),
                    "stage": stage,
                    "round": round_number,
                },
                status="PENDING",
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(statement)
        job = await self.get_by_idempotency_key(idempotency_key)
        if job is None:
            raise RuntimeError("graph resume job upsert did not return a row")
        return job

    async def enqueue_evaluate_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> AIJob:
        idempotency_key = evaluation_idempotency_key(session_id)
        statement = (
            insert(AIJob)
            .values(
                job_type=EVALUATE_SESSION_JOB,
                payload={"session_id": str(session_id), "user_id": str(user_id)},
                status="PENDING",
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(statement)
        job = await self.get_by_idempotency_key(idempotency_key)
        if job is None:
            raise RuntimeError("evaluation job upsert did not return a row")
        return job

    async def enqueue_prepare_questions(self, *, user_id: UUID) -> AIJob:
        idempotency_key = prepare_questions_idempotency_key(user_id)
        await self._insert_prepare_questions_job(
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        job = await self.get_by_idempotency_key(idempotency_key)
        if job is None:
            raise RuntimeError("question preparation job upsert did not return a row")
        if job.status in {"PENDING", "RUNNING"}:
            return job
        job.idempotency_key = f"{idempotency_key}:archived:{job.id}"
        await self._session.flush()
        await self._insert_prepare_questions_job(
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        new_job = await self.get_by_idempotency_key(idempotency_key)
        if new_job is None:
            raise RuntimeError("question preparation job upsert did not return a row")
        return new_job

    async def _insert_prepare_questions_job(self, *, user_id: UUID, idempotency_key: str) -> None:
        statement = (
            insert(AIJob)
            .values(
                job_type=PREPARE_QUESTIONS_JOB,
                payload={"user_id": str(user_id)},
                status="PENDING",
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(statement)

    async def claim_next(self, job_type: str) -> AIJob | None:
        lease_expires_before = datetime.now(UTC) - timedelta(seconds=AI_JOB_LEASE_SECONDS)
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

    async def get_by_idempotency_key(self, idempotency_key: str) -> AIJob | None:
        result = await self._session.execute(
            select(AIJob).where(AIJob.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def mark_succeeded(self, job: AIJob) -> None:
        job.status = "SUCCEEDED"
        job.error_code = None
        await self._session.flush()

    async def mark_retryable_failure(self, job: AIJob, error_code: str) -> None:
        job.error_code = error_code
        job.locked_at = None
        if job.retry_count < AI_JOB_MAX_RETRIES:
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
