from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.contracts import STTProvider
from app.ai.providers.factory import ProviderBundle, create_provider_bundle
from app.core.config import get_settings
from app.db.models import TrainingSession
from app.db.session import get_sessionmaker
from app.graphs.voice_training import (
    VoiceTrainingDeps,
    load_voice_training_state,
    resume_voice_training,
)
from app.repositories.jobs import GRAPH_RESUME_JOB, TRANSCRIBE_ATTEMPT_JOB, AIJobRepository
from app.repositories.transcripts import TranscriptRepository
from app.services.transcription import TranscriptionService

POLL_SECONDS = 1.0
ADVANCED_SESSION_STAGES_BY_RESUME_STAGE = {
    "FIRST": {
        "PROCESS_FOLLOWUP",
        "WAIT_FOLLOWUP_AUDIO",
        "WAIT_FINAL_AUDIO",
        "EVALUATING",
        "COMPLETED",
    },
    "FOLLOWUP": {"EVALUATING", "WAIT_FINAL_AUDIO", "COMPLETED"},
    "FINAL": {"COMPLETED"},
}
ADVANCED_GRAPH_STAGES_BY_RESUME_STAGE = {
    "FIRST": {
        "PROCESS_FOLLOWUP",
        "WAIT_FOLLOWUP_AUDIO",
        "WAIT_FINAL_AUDIO",
        "EVALUATING",
        "COMPLETED",
    },
    "FOLLOWUP": {"EVALUATING", "WAIT_FINAL_AUDIO", "COMPLETED"},
    "FINAL": {"COMPLETED"},
}


async def run_worker() -> None:
    settings = get_settings()
    settings.validate_ai()
    bundle = create_provider_bundle(settings)
    while True:
        processed = await run_graph_resume_job_once(bundle=bundle)
        if not processed:
            processed = await run_transcription_job_once(stt_provider=bundle.stt)
        if not processed:
            await asyncio.sleep(POLL_SECONDS)


async def run_graph_resume_job_once(*, bundle: ProviderBundle) -> bool:
    settings = get_settings()
    maker = get_sessionmaker()
    async with maker() as session:
        job_repo = AIJobRepository(session)
        job = await job_repo.claim_next(GRAPH_RESUME_JOB)
        if job is None:
            await session.rollback()
            return False
        job_id = job.id
        payload = job.payload
        await session.commit()

    session_id: UUID | None = None
    try:
        session_id = _uuid_from_payload(payload, "session_id")
        attempt_id = _uuid_from_payload(payload, "attempt_id")
        stage = _str_from_payload(payload, "stage")
        round_number = _int_from_payload(payload, "round")
        training_session = await _training_session_for_graph(session_id)
        deps = VoiceTrainingDeps(
            settings=settings,
            sessionmaker=maker,
            llm_provider=bundle.llm,
            stt_provider=bundle.stt,
        )
        if await _graph_resume_already_applied(
            deps=deps,
            training_session=training_session,
            resume_stage=stage,
        ):
            await _mark_job_succeeded(job_id)
            return True
        await resume_voice_training(
            deps=deps,
            training_session=training_session,
            attempt_id=attempt_id,
            stage=stage,
            round_number=round_number,
        )
        await _mark_job_succeeded(job_id)
    except Exception as exc:
        async with maker() as session:
            job_repo = AIJobRepository(session)
            job = await job_repo.get_by_id(job_id)
            if job is not None:
                error_code = _error_code(exc)
                await job_repo.mark_retryable_failure(job, error_code)
                if job.status == "FAILED" and session_id is not None:
                    await _mark_session_failed_retryable(session, session_id)
            await session.commit()
    return True


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
    return _uuid_from_payload(payload, "attempt_id")


def _uuid_from_payload(payload: dict[str, object], key: str) -> UUID:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"job payload is missing {key}")
    return UUID(value)


def _str_from_payload(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"job payload is missing {key}")
    return value


def _int_from_payload(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"job payload is missing {key}")
    return value


async def _training_session_for_graph(session_id: UUID) -> TrainingSession:
    maker = get_sessionmaker()
    async with maker() as session:
        result = await session.get(TrainingSession, session_id)
        if result is None:
            raise ValueError("GRAPH_RESUME payload references a missing session")
        return result


async def _mark_session_failed_retryable(session: AsyncSession, session_id: UUID) -> None:
    training_session = await session.get(TrainingSession, session_id)
    if training_session is not None and training_session.stage != "COMPLETED":
        training_session.stage = "FAILED_RETRYABLE"


async def _mark_job_succeeded(job_id: UUID) -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        job_repo = AIJobRepository(session)
        job = await job_repo.get_by_id(job_id)
        if job is not None:
            await job_repo.mark_succeeded(job)
        await session.commit()


async def _graph_resume_already_applied(
    *,
    deps: VoiceTrainingDeps,
    training_session: TrainingSession,
    resume_stage: str,
) -> bool:
    if training_session.stage not in ADVANCED_SESSION_STAGES_BY_RESUME_STAGE.get(
        resume_stage, set()
    ):
        return False
    graph_state = await load_voice_training_state(
        deps=deps,
        thread_id=training_session.thread_id,
    )
    graph_stage = graph_state.get("current_stage")
    if not isinstance(graph_stage, str):
        return False
    return graph_stage in ADVANCED_GRAPH_STAGES_BY_RESUME_STAGE.get(resume_stage, set())


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    return code if isinstance(code, str) and code else exc.__class__.__name__.upper()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
