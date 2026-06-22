from __future__ import annotations

import asyncio
from uuid import UUID

from app.ai.providers.contracts import STTProvider
from app.ai.providers.factory import create_provider_bundle
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.repositories.jobs import TRANSCRIBE_ATTEMPT_JOB, AIJobRepository
from app.repositories.transcripts import TranscriptRepository
from app.services.transcription import TranscriptionService

POLL_SECONDS = 1.0


async def run_worker() -> None:
    settings = get_settings()
    settings.validate_ai()
    bundle = create_provider_bundle(settings)
    while True:
        processed = await run_transcription_job_once(stt_provider=bundle.stt)
        if not processed:
            await asyncio.sleep(POLL_SECONDS)


async def run_transcription_job_once(*, stt_provider: STTProvider) -> bool:
    settings = get_settings()
    maker = get_sessionmaker()
    attempt_id: UUID | None = None
    async with maker() as session:
        job_repo = AIJobRepository(session)
        job = await job_repo.claim_next(TRANSCRIBE_ATTEMPT_JOB)
        if job is None:
            await session.rollback()
            return False
        job_id = job.id
        payload = job.payload
        await session.commit()

    try:
        attempt_id = _attempt_id_from_payload(payload)
        async with maker() as session:
            await TranscriptionService(
                session=session,
                settings=settings,
                stt_provider=stt_provider,
            ).transcribe_attempt(attempt_id, mark_failed_on_error=False)
        async with maker() as session:
            job_repo = AIJobRepository(session)
            job = await job_repo.get_by_id(job_id)
            if job is not None:
                await job_repo.mark_succeeded(job)
            await session.commit()
    except Exception as exc:
        async with maker() as session:
            job_repo = AIJobRepository(session)
            job = await job_repo.get_by_id(job_id)
            if job is not None:
                error_code = _error_code(exc)
                await job_repo.mark_retryable_failure(job, error_code)
                if attempt_id is not None:
                    transcript_repo = TranscriptRepository(session)
                    if job.status == "FAILED":
                        await transcript_repo.mark_failed(attempt_id, error_code)
                    else:
                        await transcript_repo.mark_pending(attempt_id, error_code)
            await session.commit()
    return True


def _attempt_id_from_payload(payload: dict[str, object]) -> UUID:
    value = payload.get("attempt_id")
    if not isinstance(value, str):
        raise ValueError("TRANSCRIBE_ATTEMPT payload is missing attempt_id")
    return UUID(value)


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    return code if isinstance(code, str) and code else exc.__class__.__name__.upper()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
