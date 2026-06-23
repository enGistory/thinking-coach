from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.providers.contracts import (
    LLMStructuredRequest,
    LLMStructuredResponse,
    ProviderCallMetadata,
    ProviderUsage,
)
from app.ai.providers.factory import ProviderBundle
from app.ai.providers.mock import MockEmbeddingProvider, MockSTTProvider, MockTTSProvider
from app.db.base import Base
from app.db.models import (
    AIJob,
    AppUser,
    AttemptTranscript,
    EvaluationIssue,
    EvaluationReport,
    ModelRun,
    TrainingSession,
    TranscriptSegment,
    VoiceAttempt,
)
from app.repositories.jobs import EVALUATE_SESSION_JOB, AIJobRepository
from app.services.evaluation import EvaluationService
from app.workers import main as worker_module

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_DATABASE_SYNC_URL = os.getenv("TEST_DATABASE_SYNC_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None or TEST_DATABASE_SYNC_URL is None,
    reason="TEST_DATABASE_URL and TEST_DATABASE_SYNC_URL are required for P06 evaluation tests",
)


@pytest.fixture
async def db_maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert TEST_DATABASE_URL is not None
    assert TEST_DATABASE_SYNC_URL is not None
    _assert_test_database(TEST_DATABASE_URL)
    _assert_test_database(TEST_DATABASE_SYNC_URL)
    _reset_schema(TEST_DATABASE_SYNC_URL)
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def test_evaluation_service_persists_report_issues_and_model_runs(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    session_id, user_id = await _seed_evaluation_session(db_maker)
    llm = QueueLLMProvider(
        _answer_structure_payload(),
        _logic_review_payload(quote="first answer missed the core"),
    )
    async with db_maker() as session:
        job = await AIJobRepository(session).enqueue_evaluate_session(
            session_id=session_id,
            user_id=user_id,
        )
        report = await EvaluationService(session=session, llm_provider=llm).evaluate_session(
            session_id=session_id,
            user_id=user_id,
            job_id=job.id,
        )
        await session.commit()

    async with db_maker() as session:
        stored_report = await session.get(EvaluationReport, report.id)
        stored_session = await session.get(TrainingSession, session_id)
        issue_count = await session.scalar(
            select(func.count())
            .select_from(EvaluationIssue)
            .where(EvaluationIssue.report_id == report.id)
        )
        model_runs = list(
            (
                await session.execute(
                    select(ModelRun)
                    .where(ModelRun.report_id == report.id)
                    .order_by(ModelRun.created_at)
                )
            ).scalars()
        )

    assert stored_report is not None
    assert stored_report.status == "COMPLETED"
    assert stored_report.final_score == 40
    assert stored_session is not None
    assert stored_session.stage == "COMPLETED"
    assert issue_count == 1
    assert [run.prompt_name for run in model_runs] == ["answer_structure", "logic_review"]
    assert {run.job_id for run in model_runs} == {job.id}


async def test_evaluation_rejects_issue_without_transcript_quote(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    session_id, user_id = await _seed_evaluation_session(db_maker)
    llm = QueueLLMProvider(
        _answer_structure_payload(),
        _logic_review_payload(quote="this quote is absent"),
    )
    async with db_maker() as session:
        report = await EvaluationService(session=session, llm_provider=llm).evaluate_session(
            session_id=session_id,
            user_id=user_id,
        )
        await session.commit()

    async with db_maker() as session:
        stored_report = await session.get(EvaluationReport, report.id)
        issue_count = await session.scalar(
            select(func.count())
            .select_from(EvaluationIssue)
            .where(EvaluationIssue.report_id == report.id)
        )

    assert stored_report is not None
    assert stored_report.status == "COMPLETED"
    assert issue_count == 0
    rejected = stored_report.details_json["rejected_issues"]
    assert isinstance(rejected, list)
    assert rejected[0]["quote_match"] is False


async def test_evaluation_allows_same_evidence_in_different_attempts(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    repeated_quote = "same flawed sentence"
    session_id, user_id = await _seed_evaluation_session(
        db_maker,
        stage_texts={
            "FIRST": repeated_quote,
            "FOLLOWUP": "followup adds one evidence point",
            "FINAL": repeated_quote,
        },
    )
    llm = QueueLLMProvider(
        _answer_structure_payload(),
        _logic_review_payload_with_issues(
            [
                _logic_issue_payload(quote=repeated_quote, attempt_stage="FIRST"),
                _logic_issue_payload(quote=repeated_quote, attempt_stage="FINAL"),
            ]
        ),
    )
    async with db_maker() as session:
        report = await EvaluationService(session=session, llm_provider=llm).evaluate_session(
            session_id=session_id,
            user_id=user_id,
        )
        await session.commit()

    async with db_maker() as session:
        issues = list(
            (
                await session.execute(
                    select(EvaluationIssue)
                    .where(EvaluationIssue.report_id == report.id)
                    .order_by(EvaluationIssue.attempt_id)
                )
            ).scalars()
        )

    assert len(issues) == 2
    assert {issue.quote for issue in issues} == {repeated_quote}
    assert {issue.start_ms for issue in issues} == {0}
    assert {issue.end_ms for issue in issues} == {1000}
    assert len({issue.attempt_id for issue in issues}) == 2


async def test_evaluation_adaptability_score_recognizes_chinese_final_markers(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    session_id, user_id = await _seed_evaluation_session(
        db_maker,
        stage_texts={
            "FIRST": "先判断延期原因",
            "FOLLOWUP": "补充一个依据",
            "FINAL": "最终回答会说明依据、未知、取舍和下一步行动",
        },
    )
    llm = QueueLLMProvider(
        _answer_structure_payload(), _logic_review_payload(quote="先判断延期原因")
    )
    async with db_maker() as session:
        report = await EvaluationService(session=session, llm_provider=llm).evaluate_session(
            session_id=session_id,
            user_id=user_id,
        )
        await session.commit()

    assert report.adaptability_score == 100
    assert report.details_json["adaptability_review"]["notes"][-1] == (
        "final answer mentions evidence, unknowns, tradeoffs or next steps"
    )


async def test_evaluation_worker_processes_evaluate_session_job(
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, user_id = await _seed_evaluation_session(db_maker)
    async with db_maker() as session:
        job = await AIJobRepository(session).enqueue_evaluate_session(
            session_id=session_id,
            user_id=user_id,
        )
        await session.commit()

    monkeypatch.setattr(worker_module, "get_sessionmaker", lambda: db_maker)
    bundle = ProviderBundle(
        llm=QueueLLMProvider(
            _answer_structure_payload(),
            _logic_review_payload(quote="first answer missed the core"),
        ),
        stt=MockSTTProvider(),
        tts=MockTTSProvider(),
        embedding=MockEmbeddingProvider(),
    )

    assert await worker_module.run_evaluation_job_once(bundle=bundle) is True

    async with db_maker() as session:
        stored_job = await session.get(AIJob, job.id)
        stored_session = await session.get(TrainingSession, session_id)
        model_run_count = await session.scalar(
            select(func.count()).select_from(ModelRun).where(ModelRun.job_id == job.id)
        )

    assert stored_job is not None
    assert stored_job.job_type == EVALUATE_SESSION_JOB
    assert stored_job.status == "SUCCEEDED"
    assert stored_session is not None
    assert stored_session.stage == "COMPLETED"
    assert model_run_count == 2


class QueueLLMProvider:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = list(payloads)
        self.requests: list[LLMStructuredRequest] = []

    async def generate_structured(
        self,
        request: LLMStructuredRequest,
        response_model: type[BaseModel],
    ) -> LLMStructuredResponse:
        self.requests.append(request)
        payload = self.payloads.pop(0)
        parsed = response_model.model_validate(payload)
        return LLMStructuredResponse(
            output=parsed,
            raw_json=payload,
            metadata=ProviderCallMetadata(
                provider="mock",
                model=f"mock-{request.model_slot}",
                request_id=f"request-{len(self.requests)}",
                latency_ms=1,
                usage=ProviderUsage(
                    input_characters=sum(len(message.content) for message in request.messages),
                    output_characters=len(parsed.model_dump_json()),
                ),
                structured_ok=True,
            ),
        )


async def _seed_evaluation_session(
    maker: async_sessionmaker[AsyncSession],
    *,
    stage_texts: dict[str, str] | None = None,
) -> tuple[UUID, UUID]:
    async with maker() as session:
        user = AppUser(
            nickname=f"user-{uuid4()}",
            password_hash="fake-password-hash",
            role="USER",
            status="ACTIVE",
        )
        session.add(user)
        await session.flush()
        training_session = TrainingSession(
            user_id=user.id,
            thread_id=f"thread-{uuid4()}",
            stage="EVALUATING",
        )
        session.add(training_session)
        await session.flush()
        for stage, text in (stage_texts or _stage_texts()).items():
            attempt = VoiceAttempt(
                session_id=training_session.id,
                stage=stage,
                round=1,
                upload_status="UPLOADED",
            )
            session.add(attempt)
            await session.flush()
            session.add(
                AttemptTranscript(
                    attempt_id=attempt.id,
                    status="SUCCEEDED",
                    raw_text=text,
                    corrected_text=text,
                    metrics_json={
                        "first_conclusion_ms": 300,
                        "speech_rate_cpm": 160,
                        "long_pauses": [],
                        "filler_phrases": [],
                    },
                )
            )
            session.add(
                TranscriptSegment(
                    attempt_id=attempt.id,
                    segment_index=0,
                    start_ms=0,
                    end_ms=1200,
                    raw_text=text,
                    corrected_text=text,
                    words_json=[],
                )
            )
        await session.commit()
        return training_session.id, user.id


def _stage_texts() -> dict[str, str]:
    return {
        "FIRST": "first answer missed the core",
        "FOLLOWUP": "followup adds one evidence point",
        "FINAL": "final answer mentions evidence, unknown, tradeoff and next action",
    }


def _answer_structure_payload() -> dict[str, object]:
    return {
        "direct_answer": "The answer needs more alignment.",
        "facts_used": ["one evidence point"],
        "assumptions": ["delay cause"],
        "unknowns": ["business goal"],
        "stakeholders": ["team", "business owner"],
        "options": ["clarify goal"],
        "tradeoffs": ["speed versus confidence"],
        "risks": ["wrong diagnosis"],
        "actions": ["confirm goal"],
    }


def _logic_review_payload(*, quote: str, attempt_stage: str = "FIRST") -> dict[str, object]:
    return _logic_review_payload_with_issues(
        [_logic_issue_payload(quote=quote, attempt_stage=attempt_stage)]
    )


def _logic_review_payload_with_issues(issues: list[dict[str, object]]) -> dict[str, object]:
    return {
        "dimension_scores": {"alignment": 95, "structure": 90},
        "issues": issues,
        "strengths": ["mentions a judgement"],
        "score_caps": [],
        "followup_strategy": "ask for evidence",
    }


def _logic_issue_payload(*, quote: str, attempt_stage: str = "FIRST") -> dict[str, object]:
    return {
        "code": "ALIGN-01",
        "category": "logic",
        "attempt_stage": attempt_stage,
        "severity": 5,
        "confidence": "high",
        "quote": quote,
        "start_ms": 0,
        "end_ms": 1000,
        "explanation": "The answer does not address the core judgement.",
        "missing_information": ["goal"],
        "correction_rule": "State the core judgement before evidence.",
    }


def _reset_schema(database_url: str) -> None:
    engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.execute(text("GRANT ALL ON SCHEMA public TO public"))
    finally:
        engine.dispose()


def _assert_test_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(f"Refusing to reset non-test database: {database_name}")
