from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.providers.contracts import (
    ContentFetchRequest,
    ContentFetchResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    ProviderCallMetadata,
    ProviderUsage,
    SearchResult,
)
from app.ai.providers.mock import (
    MockContentFetcher,
    MockEmbeddingProvider,
    MockLLMProvider,
    MockSearchProvider,
)
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.models import (
    AIJob,
    Question,
    QuestionClaimMap,
    QuestionRubric,
    QuestionSource,
    SourceBundle,
    SourceClaim,
    TrainingSession,
)
from app.db.session import get_session
from app.main import create_app
from app.repositories.auth import UserRepository
from app.repositories.jobs import PREPARE_QUESTIONS_JOB, AIJobRepository
from app.services.source_questions import SourceQuestionService
from tests.helpers_source_questions import seed_exposed_training_session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="TEST_DATABASE_URL is required for P08 source question tests",
)


class RedirectingMockContentFetcher(MockContentFetcher):
    def __init__(self, final_url: str) -> None:
        super().__init__()
        self.final_url = final_url
        self.source_text = next(iter(self.pages.values()))

    async def fetch(self, request: ContentFetchRequest) -> ContentFetchResponse:
        self.requests.append(request)
        return ContentFetchResponse(
            url=self.final_url,
            content_type="text/html",
            text=self.source_text,
            snapshot_hash=hashlib.sha256(self.source_text.encode("utf-8")).hexdigest(),
            title="mock source",
        )


class ShiftingSearchDirectionsLLMProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.search_direction_calls = 0

    async def generate_structured(
        self,
        request: LLMStructuredRequest,
        response_model: type[BaseModel],
    ) -> LLMStructuredResponse:
        if response_model.__name__ != "SearchDirectionPlan":
            return await super().generate_structured(request, response_model)

        self.search_direction_calls += 1
        payload: dict[str, object] = {
            "queries": [f"retry-sensitive-query-{self.search_direction_calls}"]
        }
        parsed = response_model.model_validate(payload)
        return LLMStructuredResponse(
            output=parsed,
            raw_json=payload,
            metadata=ProviderCallMetadata(
                provider="mock",
                model=request.model_slot,
                request_id=f"search-plan-{self.search_direction_calls}",
                latency_ms=0,
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
    _assert_test_database(TEST_DATABASE_URL)
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
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


async def test_prepare_questions_generates_ready_inventory(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id = await _create_user(db_maker, nickname="inventory")

    async with db_maker() as session:
        service = SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=MockLLMProvider(),
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(),
            content_fetcher=MockContentFetcher(),
        )
        ready = await service.prepare_questions_for_user(user_id=user_id)
        second_run = await service.prepare_questions_for_user(user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        question_count = await session.scalar(select(func.count()).select_from(Question))
        mapping_count = await session.scalar(select(func.count()).select_from(QuestionClaimMap))
        rubric_count = await session.scalar(select(func.count()).select_from(QuestionRubric))

    assert len(ready) == 8
    assert len(second_run) == 8
    assert question_count == 8
    assert mapping_count == 8
    assert rubric_count == 8


async def test_prepare_questions_retry_reuses_job_bundle_when_search_directions_change(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id = await _create_user(db_maker, nickname="prepare-retry")
    job_id = await _create_prepare_questions_job(db_maker, user_id=user_id)
    llm_provider = ShiftingSearchDirectionsLLMProvider()

    async with db_maker() as session:
        service = SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=llm_provider,
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(),
            content_fetcher=MockContentFetcher(),
        )
        ready = await service.prepare_questions_for_user(user_id=user_id, job_id=job_id)
        await session.commit()

    async with db_maker() as session:
        service = SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=llm_provider,
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(),
            content_fetcher=MockContentFetcher(),
        )
        second_ready = await service.prepare_questions_for_user(user_id=user_id, job_id=job_id)
        await session.commit()

    async with db_maker() as session:
        bundle_count = await session.scalar(select(func.count()).select_from(SourceBundle))
        source_count = await session.scalar(select(func.count()).select_from(QuestionSource))
        claim_count = await session.scalar(select(func.count()).select_from(SourceClaim))
        question_count = await session.scalar(select(func.count()).select_from(Question))

    assert len(ready) == 8
    assert len(second_ready) == 8
    assert llm_provider.search_direction_calls == 1
    assert bundle_count == 1
    assert source_count == 1
    assert claim_count == 2
    assert question_count == 8


async def test_prepare_questions_fails_closed_without_sources(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id = await _create_user(db_maker, nickname="no-source")

    async with db_maker() as session:
        service = SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=MockLLMProvider(),
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(results=[]),
            content_fetcher=MockContentFetcher(),
        )
        ready = await service.prepare_questions_for_user(user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        question_count = await session.scalar(select(func.count()).select_from(Question))

    assert ready == []
    assert question_count == 0


async def test_prepare_questions_rates_final_fetched_url(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id = await _create_user(db_maker, nickname="final-url-level")

    async with db_maker() as session:
        service = SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=MockLLMProvider(),
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(
                results=[
                    SearchResult(
                        title="University mirror report",
                        url="https://example.edu/redirect",
                        snippet="redirects to final source",
                        source="Example University",
                    )
                ]
            ),
            content_fetcher=RedirectingMockContentFetcher("https://ordinary.example.com/report"),
        )
        ready = await service.prepare_questions_for_user(user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        source = (await session.execute(select(QuestionSource))).scalar_one()
        question_count = await session.scalar(select(func.count()).select_from(Question))

    assert ready == []
    assert source.url == "https://ordinary.example.com/report"
    assert source.level == "B"
    assert question_count == 0


async def test_prepare_questions_dedupes_repeated_final_fetched_url(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id = await _create_user(db_maker, nickname="final-url-dedupe")

    async with db_maker() as session:
        service = SourceQuestionService(
            session=session,
            settings=_test_settings(tmp_path),
            llm_provider=MockLLMProvider(),
            embedding_provider=MockEmbeddingProvider(),
            search_provider=MockSearchProvider(
                results=[
                    SearchResult(
                        title="First redirect",
                        url="https://first.example/redirect",
                        snippet="first redirect",
                        source="First Source",
                    ),
                    SearchResult(
                        title="Second redirect",
                        url="https://second.example/redirect",
                        snippet="second redirect",
                        source="Second Source",
                    ),
                ]
            ),
            content_fetcher=RedirectingMockContentFetcher("https://example.edu/final-report"),
        )
        ready = await service.prepare_questions_for_user(user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        source_count = await session.scalar(select(func.count()).select_from(QuestionSource))
        claim_count = await session.scalar(select(func.count()).select_from(SourceClaim))
        question_count = await session.scalar(select(func.count()).select_from(Question))

    assert len(ready) == 8
    assert source_count == 1
    assert claim_count == 2
    assert question_count == 8


async def test_current_without_visible_session_does_not_enqueue_prepare_job(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="waiting")
    token = await _login(client, "waiting")

    response = await client.get("/api/v1/trainings/current", headers=_auth_headers(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_CURRENT_TRAINING"
    async with db_maker() as session:
        job_count = await session.scalar(
            select(func.count()).select_from(AIJob).where(AIJob.job_type == PREPARE_QUESTIONS_JOB)
        )
    assert job_count == 0


async def test_prepare_question_enqueue_reuses_active_but_starts_new_after_terminal(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, nickname="prepare-again")

    async with db_maker() as session:
        repo = AIJobRepository(session)
        first = await repo.enqueue_prepare_questions(user_id=user_id)
        second = await repo.enqueue_prepare_questions(user_id=user_id)
        assert second.id == first.id

        first.status = "SUCCEEDED"
        third = await repo.enqueue_prepare_questions(user_id=user_id)
        await session.commit()

        assert third.id != first.id
        assert third.status == "PENDING"

    async with db_maker() as session:
        job_count = await session.scalar(
            select(func.count()).select_from(AIJob).where(AIJob.job_type == PREPARE_QUESTIONS_JOB)
        )
    assert job_count == 2


async def test_state_hides_sources_until_completed_and_then_returns_provenance(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, nickname="provenance")
    token = await _login(client, "provenance")
    async with db_maker() as session:
        training_session = await seed_exposed_training_session(session, user_id=user_id)
        session_id = str(training_session.id)
        await session.commit()

    state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(token),
    )
    before_completed = await client.get(
        f"/api/v1/trainings/{session_id}/provenance",
        headers=_auth_headers(token),
    )

    assert state.status_code == 200
    assert state.json()["source_summary"]["source_count"] == 1
    assert "sources" not in state.json()
    assert before_completed.status_code == 404

    async with db_maker() as session:
        training = await session.get(TrainingSession, UUID(session_id))
        assert training is not None
        training.stage = "COMPLETED"
        await session.commit()

    provenance = await client.get(
        f"/api/v1/trainings/{session_id}/provenance",
        headers=_auth_headers(token),
    )

    assert provenance.status_code == 200
    body = provenance.json()
    assert body["source_summary"]["source_count"] == 1
    assert body["sources"][0]["claims"][0]["support_status"] == "VERIFIED"
    assert body["mappings"][0]["claim_ids"]


async def test_provenance_rejects_other_users_completed_session(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    owner_id = await _create_user(db_maker, nickname="source-owner")
    await _create_user(db_maker, nickname="source-intruder")
    intruder_token = await _login(client, "source-intruder")
    async with db_maker() as session:
        training_session = await seed_exposed_training_session(session, user_id=owner_id)
        session_id = str(training_session.id)
        await session.commit()

    async with db_maker() as session:
        training = await session.get(TrainingSession, UUID(session_id))
        assert training is not None
        training.stage = "COMPLETED"
        await session.commit()

    response = await client.get(
        f"/api/v1/trainings/{session_id}/provenance",
        headers=_auth_headers(intruder_token),
    )

    assert response.status_code == 404


async def _create_user(
    maker: async_sessionmaker[AsyncSession],
    *,
    nickname: str,
) -> UUID:
    async with maker() as session:
        user = await UserRepository(session).create_user(
            nickname=nickname,
            password_hash=hash_password("test-password"),
            role="USER",
        )
        await session.commit()
        return user.id


async def _create_prepare_questions_job(
    maker: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
) -> UUID:
    async with maker() as session:
        job = await AIJobRepository(session).enqueue_prepare_questions(user_id=user_id)
        await session.commit()
        return job.id


async def _login(client: AsyncClient, nickname: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"nickname": nickname, "password": "test-password"},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


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


def _assert_test_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(f"Refusing to reset non-test database: {database_name}")
