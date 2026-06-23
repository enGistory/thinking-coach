from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.providers.factory import ProviderBundle
from app.ai.providers.mock import (
    MockEmbeddingProvider,
    MockLLMProvider,
    MockSTTProvider,
    MockTTSProvider,
)
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.models import AIJob, AttemptTranscript, TrainingSession, VoiceAttempt
from app.db.session import get_session
from app.main import create_app
from app.repositories.auth import UserRepository
from app.repositories.jobs import GRAPH_RESUME_JOB
from app.workers import main as worker_module

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_DATABASE_SYNC_URL = os.getenv("TEST_DATABASE_SYNC_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None or TEST_DATABASE_SYNC_URL is None,
    reason="TEST_DATABASE_URL and TEST_DATABASE_SYNC_URL are required for P05 graph tests",
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
    monkeypatch.setattr("app.api.v1.trainings.get_sessionmaker", lambda: db_maker)

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


async def test_voice_training_graph_completes_three_attempts(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    _patch_worker(monkeypatch, db_maker, settings)
    bundle = _provider_bundle("请说明你判断中最缺的证据是什么。")
    await _create_user(db_maker, nickname="first", password="first-password", role="USER")
    token = await _login(client, "first", "first-password")

    current = await client.post("/api/v1/trainings/current", headers=_auth_headers(token))
    assert current.status_code == 200
    session_id = current.json()["id"]

    first_state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(token),
    )
    assert first_state.status_code == 200
    assert first_state.json()["stage"] == "WAIT_FIRST_AUDIO"
    assert first_state.json()["awaiting"]["stage"] == "FIRST"

    first_attempt_id = await _record_and_resume(
        client,
        token=token,
        session_id=session_id,
        stage="FIRST",
        round_number=1,
        audio_bytes=b"first-answer",
    )
    assert await worker_module.run_graph_resume_job_once(bundle=bundle) is True

    followup_state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(token),
    )
    assert followup_state.status_code == 200
    assert followup_state.json()["stage"] == "WAIT_FOLLOWUP_AUDIO"
    assert followup_state.json()["awaiting"]["stage"] == "FOLLOWUP"
    assert followup_state.json()["awaiting"]["text"] == "请说明你判断中最缺的证据是什么。"

    await _record_and_resume(
        client,
        token=token,
        session_id=session_id,
        stage="FOLLOWUP",
        round_number=1,
        audio_bytes=b"followup-answer",
    )
    assert await worker_module.run_graph_resume_job_once(bundle=bundle) is True

    final_state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(token),
    )
    assert final_state.status_code == 200
    assert final_state.json()["stage"] == "WAIT_FINAL_AUDIO"
    assert final_state.json()["awaiting"]["stage"] == "FINAL"

    await _record_and_resume(
        client,
        token=token,
        session_id=session_id,
        stage="FINAL",
        round_number=1,
        audio_bytes=b"final-answer",
    )
    assert await worker_module.run_graph_resume_job_once(bundle=bundle) is True

    async with db_maker() as session:
        stored_session = await session.get(TrainingSession, UUID(session_id))
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(VoiceAttempt)
            .where(VoiceAttempt.session_id == UUID(session_id))
        )

    assert first_attempt_id is not None
    assert stored_session is not None
    assert stored_session.stage == "COMPLETED"
    assert stored_session.completed_at is not None
    assert attempt_count == 3


async def test_repeated_resume_reuses_graph_job(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="repeat", password="repeat-password", role="USER")
    token = await _login(client, "repeat", "repeat-password")
    current = await client.post("/api/v1/trainings/current", headers=_auth_headers(token))
    session_id = current.json()["id"]
    attempt = await _create_attempt(client, token, session_id, "FIRST", 1)
    upload = await _upload_audio(client, token, attempt["id"], b"same-first-answer")
    assert upload.status_code == 200

    first_resume = await client.post(
        f"/api/v1/trainings/{session_id}/resume",
        headers=_auth_headers(token),
        json={"stage": "FIRST", "round": 1, "attempt_id": attempt["id"]},
    )
    repeated_resume = await client.post(
        f"/api/v1/trainings/{session_id}/resume",
        headers=_auth_headers(token),
        json={"stage": "FIRST", "round": 1, "attempt_id": attempt["id"]},
    )

    assert first_resume.status_code == 202
    assert repeated_resume.status_code == 202
    assert repeated_resume.json()["job_id"] == first_resume.json()["job_id"]
    async with db_maker() as session:
        job_count = await session.scalar(
            select(func.count()).select_from(AIJob).where(AIJob.job_type == GRAPH_RESUME_JOB)
        )
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(VoiceAttempt)
            .where(VoiceAttempt.session_id == UUID(session_id))
        )

    assert job_count == 1
    assert attempt_count == 1


async def test_graph_resume_job_replay_after_checkpoint_advance_is_succeeded(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    _patch_worker(monkeypatch, db_maker, settings)
    bundle = _provider_bundle("follow-up after replay")
    await _create_user(db_maker, nickname="replay", password="replay-password", role="USER")
    token = await _login(client, "replay", "replay-password")
    current = await client.post("/api/v1/trainings/current", headers=_auth_headers(token))
    session_id = current.json()["id"]
    attempt = await _create_attempt(client, token, session_id, "FIRST", 1)
    upload = await _upload_audio(client, token, attempt["id"], b"first-answer")
    assert upload.status_code == 200
    resume = await client.post(
        f"/api/v1/trainings/{session_id}/resume",
        headers=_auth_headers(token),
        json={"stage": "FIRST", "round": 1, "attempt_id": attempt["id"]},
    )
    assert resume.status_code == 202
    job_id = UUID(resume.json()["job_id"])

    assert await worker_module.run_graph_resume_job_once(bundle=bundle) is True
    async with db_maker() as session:
        replay_job = await session.get(AIJob, job_id)
        assert replay_job is not None
        replay_job.status = "PENDING"
        replay_job.error_code = None
        replay_job.locked_at = None
        await session.commit()

    assert await worker_module.run_graph_resume_job_once(bundle=bundle) is True
    async with db_maker() as session:
        stored_session = await session.get(TrainingSession, UUID(session_id))
        replay_job = await session.get(AIJob, job_id)

    assert stored_session is not None
    assert stored_session.stage == "WAIT_FOLLOWUP_AUDIO"
    assert replay_job is not None
    assert replay_job.status == "SUCCEEDED"
    assert replay_job.error_code is None


async def test_graph_resume_job_replays_when_session_stage_advanced_before_checkpoint(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    _patch_worker(monkeypatch, db_maker, settings)
    bundle = _provider_bundle("checkpoint repaired follow-up")
    await _create_user(
        db_maker, nickname="stage-ahead", password="stage-ahead-password", role="USER"
    )
    token = await _login(client, "stage-ahead", "stage-ahead-password")
    current = await client.post("/api/v1/trainings/current", headers=_auth_headers(token))
    session_id = current.json()["id"]
    attempt = await _create_attempt(client, token, session_id, "FIRST", 1)
    upload = await _upload_audio(client, token, attempt["id"], b"first-answer")
    assert upload.status_code == 200
    resume = await client.post(
        f"/api/v1/trainings/{session_id}/resume",
        headers=_auth_headers(token),
        json={"stage": "FIRST", "round": 1, "attempt_id": attempt["id"]},
    )
    assert resume.status_code == 202
    job_id = UUID(resume.json()["job_id"])

    async with db_maker() as session:
        stored_session = await session.get(TrainingSession, UUID(session_id))
        assert stored_session is not None
        stored_session.stage = "WAIT_FOLLOWUP_AUDIO"
        await session.commit()

    assert await worker_module.run_graph_resume_job_once(bundle=bundle) is True
    followup_state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(token),
    )

    assert followup_state.status_code == 200
    assert followup_state.json()["stage"] == "WAIT_FOLLOWUP_AUDIO"
    assert followup_state.json()["awaiting"]["text"] == "checkpoint repaired follow-up"
    async with db_maker() as session:
        job = await session.get(AIJob, job_id)
        transcript = (
            await session.execute(
                select(AttemptTranscript).where(
                    AttemptTranscript.attempt_id == UUID(str(attempt["id"]))
                )
            )
        ).scalar_one()

    assert job is not None
    assert job.status == "SUCCEEDED"
    assert transcript.status == "SUCCEEDED"


async def test_failed_retryable_session_does_not_block_new_current_session(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="failed", password="failed-password", role="USER")
    token = await _login(client, "failed", "failed-password")
    first_current = await client.post("/api/v1/trainings/current", headers=_auth_headers(token))
    assert first_current.status_code == 200
    failed_session_id = first_current.json()["id"]

    async with db_maker() as session:
        failed_session = await session.get(TrainingSession, UUID(failed_session_id))
        assert failed_session is not None
        failed_session.stage = "FAILED_RETRYABLE"
        await session.commit()

    next_current = await client.post("/api/v1/trainings/current", headers=_auth_headers(token))

    assert next_current.status_code == 200
    assert next_current.json()["id"] != failed_session_id
    assert next_current.json()["stage"] == "WAIT_FIRST_AUDIO"


async def test_training_state_and_resume_are_private(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="owner", password="owner-password", role="USER")
    await _create_user(db_maker, nickname="other", password="other-password", role="USER")
    owner_token = await _login(client, "owner", "owner-password")
    other_token = await _login(client, "other", "other-password")
    current = await client.post("/api/v1/trainings/current", headers=_auth_headers(owner_token))
    session_id = current.json()["id"]
    attempt = await _create_attempt(client, owner_token, session_id, "FIRST", 1)
    await _upload_audio(client, owner_token, attempt["id"], b"private-answer")

    forbidden_state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(other_token),
    )
    forbidden_resume = await client.post(
        f"/api/v1/trainings/{session_id}/resume",
        headers=_auth_headers(other_token),
        json={"stage": "FIRST", "round": 1, "attempt_id": attempt["id"]},
    )

    assert forbidden_state.status_code == 404
    assert forbidden_resume.status_code == 404


async def _record_and_resume(
    client: AsyncClient,
    *,
    token: str,
    session_id: str,
    stage: str,
    round_number: int,
    audio_bytes: bytes,
) -> str:
    attempt = await _create_attempt(client, token, session_id, stage, round_number)
    upload = await _upload_audio(client, token, attempt["id"], audio_bytes)
    assert upload.status_code == 200
    resume = await client.post(
        f"/api/v1/trainings/{session_id}/resume",
        headers=_auth_headers(token),
        json={"stage": stage, "round": round_number, "attempt_id": attempt["id"]},
    )
    assert resume.status_code == 202
    return str(attempt["id"])


async def _create_attempt(
    client: AsyncClient,
    token: str,
    session_id: str,
    stage: str,
    round_number: int,
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/trainings/{session_id}/attempts",
        headers=_auth_headers(token),
        json={"stage": stage, "round": round_number},
    )
    assert response.status_code == 201
    return dict(response.json())


async def _upload_audio(
    client: AsyncClient,
    token: str,
    attempt_id: str,
    audio_bytes: bytes,
) -> Response:
    return await client.put(
        f"/api/v1/attempts/{attempt_id}/audio",
        headers=_auth_headers(token),
        data={
            "duration_ms": "1200",
            "checksum_sha256": hashlib.sha256(audio_bytes).hexdigest(),
        },
        files={"audio": ("answer.webm", audio_bytes, "audio/webm")},
    )


async def _create_user(
    maker: async_sessionmaker[AsyncSession],
    *,
    nickname: str,
    password: str,
    role: str,
) -> None:
    async with maker() as session:
        await UserRepository(session).create_user(
            nickname=nickname,
            password_hash=hash_password(password),
            role=role,
        )
        await session.commit()


async def _login(client: AsyncClient, nickname: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"nickname": nickname, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _test_settings(tmp_path: Path) -> Settings:
    assert TEST_DATABASE_URL is not None
    assert TEST_DATABASE_SYNC_URL is not None
    return Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        database_url=TEST_DATABASE_URL,
        database_sync_url=TEST_DATABASE_SYNC_URL,
        audio_root=tmp_path,
        audio_retention_days=30,
        max_audio_seconds=180,
        max_audio_mb=1,
        tz="Asia/Shanghai",
    )


def _provider_bundle(followup_text: str) -> ProviderBundle:
    return ProviderBundle(
        llm=MockLLMProvider({"ok": True, "message": followup_text}),
        stt=MockSTTProvider(),
        tts=MockTTSProvider(),
        embedding=MockEmbeddingProvider(),
    )


def _patch_worker(
    monkeypatch: pytest.MonkeyPatch,
    db_maker: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_module, "get_sessionmaker", lambda: db_maker)


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
