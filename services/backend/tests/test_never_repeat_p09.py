from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.providers.contracts import (
    ChatMessage,
    LLMStructuredRequest,
    LLMStructuredResponse,
    ProviderCallMetadata,
    ProviderUsage,
)
from app.ai.providers.mock import MockContentFetcher, MockEmbeddingProvider, MockSearchProvider
from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import (
    AIJob,
    AppUser,
    DefectOccurrence,
    DefectProfile,
    EvaluationIssue,
    EvaluationReport,
    Question,
    QuestionDedupeCheck,
    QuestionDuplicateComplaint,
    QuestionFingerprint,
    QuestionTemplateDenylist,
    TrainingSession,
    VoiceAttempt,
)
from app.db.session import get_session
from app.domain.question_dedupe import normalized_question_hash
from app.main import create_app
from app.repositories.defects import DefectMemoryRepository
from app.repositories.jobs import PREPARE_QUESTIONS_JOB
from app.services.source_questions import SourceQuestionService
from tests.helpers_source_questions import seed_ready_question

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_DATABASE_SYNC_URL = os.getenv("TEST_DATABASE_SYNC_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None or TEST_DATABASE_SYNC_URL is None,
    reason="TEST_DATABASE_URL and TEST_DATABASE_SYNC_URL are required for P09 tests",
)


class SingleDuplicateCandidateLLMProvider:
    async def generate_structured(
        self,
        request: LLMStructuredRequest,
        response_model: type[BaseModel],
    ) -> LLMStructuredResponse:
        name = response_model.__name__
        if name == "SearchDirectionPlan":
            payload: dict[str, object] = {
                "queries": ["project delay official review success criteria"]
            }
        elif name == "ClaimExtractionResult":
            payload = {
                "claims": [
                    {
                        "ref": "c1",
                        "claim_text": (
                            "The team did not update success criteria after scope changed."
                        ),
                        "evidence_locator": "paragraph 1",
                        "evidence_excerpt": "did not update success criteria",
                    }
                ]
            }
        elif name == "ClaimVerificationResult":
            payload = {
                "claims": [{"ref": "c1", "support_status": "VERIFIED", "reason": "excerpt matches"}]
            }
        elif name == "QuestionGenerationResult":
            claim_id = _first_uuid_from_messages(request.messages)
            payload = {
                "candidates": [
                    {
                        "prompt": "Project delay with 200 budget: how explain tradeoff?",
                        "type": "decision",
                        "target_defects": ["ALIGN-01"],
                        "claim_ids": [claim_id],
                        "fact_mappings": [
                            {
                                "sentence_index": 0,
                                "sentence_text": "The source says success criteria were stale.",
                                "claim_ids": [claim_id],
                            }
                        ],
                        "fingerprint": {
                            "domain": "project",
                            "role": "manager",
                            "conflict": "scope_vs_speed",
                            "decision_object": "budget",
                            "template_family": "duplicate-budget",
                        },
                        "expected_reasoning": ["state conclusion, evidence, and tradeoff"],
                        "prohibited_inferences": [],
                        "hypothetical_assumptions": [],
                    }
                ]
            }
        elif name == "RubricGenerationResult":
            payload = {
                "dimensions": {"alignment": 50, "evidence": 50},
                "expected_elements": ["conclusion", "evidence", "tradeoff"],
                "fatal_omissions": ["does not answer the decision"],
            }
        else:
            payload = {
                "is_duplicate": False,
                "duplicate_type": "other",
                "reusable_answer_skeleton": False,
                "reason": "not duplicate",
            }
        parsed = response_model.model_validate(payload)
        return LLMStructuredResponse(
            output=parsed,
            raw_json=payload,
            metadata=ProviderCallMetadata(
                provider="mock",
                model=f"mock-{request.model_slot}",
                request_id=f"mock-{name}",
                latency_ms=1,
                usage=ProviderUsage(
                    input_characters=sum(len(message.content) for message in request.messages),
                    output_characters=len(parsed.model_dump_json()),
                ),
                structured_ok=True,
            ),
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


@pytest.fixture
async def client(
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[AsyncClient]:
    settings = _test_settings(tmp_path)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with db_maker() as session:
            yield session

    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.dependencies.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.invitations.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.me.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.v1.trainings.get_settings", lambda: settings)

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


async def test_prepare_questions_rejects_known_parameter_skin_and_records_audit(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id = await _create_user(db_maker, "p09-dedupe")
    async with db_maker() as session:
        historical = await seed_ready_question(
            session,
            user_id=user_id,
            prompt="Project delay with 100 budget: how explain tradeoff?",
        )
        fingerprint = (
            await session.execute(
                select(QuestionFingerprint).where(QuestionFingerprint.question_id == historical.id)
            )
        ).scalar_one()
        fingerprint.normalized_hash = normalized_question_hash(historical.prompt)
        await session.commit()

    async with db_maker() as session:
        ready = await SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=SingleDuplicateCandidateLLMProvider(),
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(),
            content_fetcher=MockContentFetcher(
                pages={
                    "https://example.edu/official-report/source-a": (
                        "The team did not update success criteria after scope changed."
                    )
                }
            ),
        ).prepare_questions_for_user(user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        dedupe_check = (await session.execute(select(QuestionDedupeCheck))).scalar_one()
        question_count = await session.scalar(select(func.count()).select_from(Question))

    assert ready == []
    assert question_count == 1
    assert dedupe_check.decision == "REJECT"
    assert dedupe_check.rejection_level == "L1_NORMALIZED_HASH"
    assert dedupe_check.matched_question_ids_json == [str(historical.id)]


async def test_prepare_questions_does_not_dedupe_against_other_users_history(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    owner_id = await _create_user(db_maker, "p09-owner-history")
    other_id = await _create_user(db_maker, "p09-other-history")
    async with db_maker() as session:
        historical = await seed_ready_question(
            session,
            user_id=other_id,
            prompt="Project delay with 100 budget: how explain tradeoff?",
        )
        fingerprint = (
            await session.execute(
                select(QuestionFingerprint).where(QuestionFingerprint.question_id == historical.id)
            )
        ).scalar_one()
        fingerprint.normalized_hash = normalized_question_hash(historical.prompt)
        await session.commit()

    async with db_maker() as session:
        ready = await SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=SingleDuplicateCandidateLLMProvider(),
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(),
            content_fetcher=MockContentFetcher(
                pages={
                    "https://example.edu/official-report/source-a": (
                        "The team did not update success criteria after scope changed."
                    )
                }
            ),
        ).prepare_questions_for_user(user_id=owner_id)
        await session.commit()

    async with db_maker() as session:
        owner_questions = list(
            (await session.execute(select(Question).where(Question.user_id == owner_id))).scalars()
        )
        dedupe_check = (
            await session.execute(
                select(QuestionDedupeCheck).where(QuestionDedupeCheck.user_id == owner_id)
            )
        ).scalar_one()

    assert len(ready) == 1
    assert len(owner_questions) == 1
    assert dedupe_check.decision == "PASS"
    assert dedupe_check.matched_question_ids_json == []


async def test_duplicate_complaint_invalidates_scoring_and_denies_template_family(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _create_user(db_maker, "duplicate-owner")
    intruder_id = await _create_user(db_maker, "duplicate-intruder")
    session_id, question_id = await _seed_completed_question_session(db_maker, user_id=owner_id)
    async with db_maker() as session:
        intruder_question = await seed_ready_question(session, user_id=intruder_id)
        await session.commit()

    forbidden = await client.post(
        f"/api/v1/trainings/{session_id}/duplicate-complaints",
        headers=_auth_headers(intruder_id),
        json={"reason": "same structure", "duplicate_type": "structure"},
    )
    assert forbidden.status_code == 404

    cross_user_similar = await client.post(
        f"/api/v1/trainings/{session_id}/duplicate-complaints",
        headers=_auth_headers(owner_id),
        json={
            "reason": "same structure",
            "duplicate_type": "structure",
            "similar_question_id": str(intruder_question.id),
        },
    )
    assert cross_user_similar.status_code == 404

    response = await client.post(
        f"/api/v1/trainings/{session_id}/duplicate-complaints",
        headers=_auth_headers(owner_id),
        json={"reason": "same answer skeleton", "duplicate_type": "answer_skeleton"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["question_id"] == str(question_id)
    assert body["template_family"] == "test-p08"

    async with db_maker() as session:
        question = await session.get(Question, question_id)
        report = (
            await session.execute(
                select(EvaluationReport).where(EvaluationReport.session_id == session_id)
            )
        ).scalar_one()
        occurrence = (
            await session.execute(
                select(DefectOccurrence).where(DefectOccurrence.session_id == session_id)
            )
        ).scalar_one()
        profile = (
            await session.execute(select(DefectProfile).where(DefectProfile.user_id == owner_id))
        ).scalar_one()
        deny_count = await session.scalar(
            select(func.count()).select_from(QuestionTemplateDenylist)
        )
        complaint_count = await session.scalar(
            select(func.count()).select_from(QuestionDuplicateComplaint)
        )
        job_count = await session.scalar(
            select(func.count()).select_from(AIJob).where(AIJob.job_type == PREPARE_QUESTIONS_JOB)
        )

    assert question is not None
    assert question.status == "INVALID"
    assert report.status == "INVALID"
    assert report.final_score is None
    assert occurrence.status == "EXCLUDED"
    assert profile.active_occurrence_count == 0
    assert deny_count == 1
    assert complaint_count == 1
    assert job_count == 1

    async with db_maker() as session:
        replacement_job = await session.get(AIJob, UUID(body["replacement_job_id"]))
        assert replacement_job is not None
        replacement_job.status = "SUCCEEDED"
        await session.commit()

    repeat = await client.post(
        f"/api/v1/trainings/{session_id}/duplicate-complaints",
        headers=_auth_headers(owner_id),
        json={"reason": "same answer skeleton", "duplicate_type": "answer_skeleton"},
    )

    assert repeat.status_code == 201
    assert repeat.json()["id"] == body["id"]
    assert repeat.json()["replacement_job_id"] == body["replacement_job_id"]

    async with db_maker() as session:
        repeated_job_count = await session.scalar(
            select(func.count()).select_from(AIJob).where(AIJob.job_type == PREPARE_QUESTIONS_JOB)
        )
        repeated_complaint_count = await session.scalar(
            select(func.count()).select_from(QuestionDuplicateComplaint)
        )

    assert repeated_job_count == 1
    assert repeated_complaint_count == 1


async def _create_user(maker: async_sessionmaker[AsyncSession], nickname: str) -> UUID:
    async with maker() as session:
        user = AppUser(
            nickname=nickname,
            password_hash="fake-password-hash",
            role="USER",
            status="ACTIVE",
        )
        session.add(user)
        await session.commit()
        return user.id


async def _seed_completed_question_session(
    maker: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
) -> tuple[UUID, UUID]:
    async with maker() as session:
        question = await seed_ready_question(session, user_id=user_id)
        training_session = TrainingSession(
            user_id=user_id,
            question_id=question.id,
            thread_id=f"thread-{uuid4()}",
            stage="COMPLETED",
        )
        session.add(training_session)
        await session.flush()
        attempt = VoiceAttempt(
            session_id=training_session.id,
            stage="FIRST",
            round=1,
            upload_status="UPLOADED",
        )
        session.add(attempt)
        await session.flush()
        report = EvaluationReport(
            session_id=training_session.id,
            status="COMPLETED",
            details_json={},
            logic_score=60,
            speech_score=80,
            adaptability_score=70,
            final_score=60,
        )
        session.add(report)
        await session.flush()
        issue = EvaluationIssue(
            report_id=report.id,
            attempt_id=attempt.id,
            category="logic",
            code="ALIGN-01",
            severity=4,
            confidence="high",
            quote="answer missed the core",
            start_ms=0,
            end_ms=1000,
            explanation="The answer does not address the decision.",
            missing_information=["goal"],
            correction_rule="State the core decision first.",
            verification_json={"evidence_valid": True},
        )
        session.add(issue)
        await session.flush()
        await DefectMemoryRepository(session).ensure_definitions()
        await session.commit()
        report_id = report.id
        session_id = training_session.id
        question_id = question.id
    async with maker() as session:
        await DefectMemoryRepository(session).sync_completed_report(
            report_id=report_id,
            user_id=user_id,
        )
        await session.commit()
    return session_id, question_id


def _auth_headers(user_id: UUID) -> dict[str, str]:
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
    )
    return {"Authorization": f"Bearer {create_access_token(user_id, 'USER', settings)}"}


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
        audio_retention_days=30,
        max_audio_seconds=180,
        max_audio_mb=1,
        tz="Asia/Shanghai",
    )


def _first_uuid_from_messages(messages: list[ChatMessage]) -> str:
    text = "\n".join(message.content for message in messages)
    match = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        text,
    )
    assert match is not None
    return match.group(0)


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
