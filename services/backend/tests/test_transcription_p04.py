from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.providers.contracts import ProviderError, STTRequest, STTResponse
from app.ai.providers.mock import MockSTTProvider
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db import models as _models
from app.db.base import Base
from app.db.models import (
    AIJob,
    AttemptTranscript,
    TrainingSession,
    TranscriptCorrection,
    TranscriptSegment,
    VoiceAttempt,
)
from app.db.session import get_session
from app.main import create_app
from app.repositories.auth import UserRepository
from app.repositories.jobs import (
    TRANSCRIBE_ATTEMPT_JOB,
    TRANSCRIBE_JOB_LEASE_SECONDS,
    AIJobRepository,
)
from app.services import transcription as transcription_module
from app.services.audio_access import AudioAccessError, TranscriptionAudioAccess
from app.services.transcription import TranscriptionService
from app.workers import main as worker_module

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="TEST_DATABASE_URL is required for P04 transcription tests",
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
    def test_settings() -> Settings:
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

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with db_maker() as session:
            yield session

    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", test_settings)
    monkeypatch.setattr("app.api.dependencies.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.auth.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.invitations.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.me.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.trainings.get_settings", test_settings)

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


async def test_upload_creates_pending_transcript_without_transcription_job(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="first", password="first-password", role="USER")
    access_token = await _login(client, "first", "first-password")
    current = await client.post("/api/v1/trainings/current", headers=_auth_headers(access_token))
    session_id = current.json()["id"]
    attempt = await client.post(
        f"/api/v1/trainings/{session_id}/attempts",
        headers=_auth_headers(access_token),
        json={"stage": "FIRST", "round": 1},
    )
    attempt_id = attempt.json()["id"]
    audio_bytes = b"fake-webm-audio"
    upload = await client.put(
        f"/api/v1/attempts/{attempt_id}/audio",
        headers=_auth_headers(access_token),
        data={
            "duration_ms": "1200",
            "checksum_sha256": hashlib.sha256(audio_bytes).hexdigest(),
        },
        files={"audio": ("answer.webm", audio_bytes, "audio/webm")},
    )

    assert upload.status_code == 200
    transcript = await client.get(
        f"/api/v1/attempts/{attempt_id}/transcript",
        headers=_auth_headers(access_token),
    )
    assert transcript.status_code == 200
    assert transcript.json()["status"] == "PENDING"
    assert "mock://attempt" not in transcript.text

    async with db_maker() as session:
        job_count = await session.scalar(
            select(func.count()).select_from(AIJob).where(AIJob.job_type == TRANSCRIBE_ATTEMPT_JOB)
        )
        assert job_count == 0


async def test_transcription_retry_does_not_duplicate_segments(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id, attempt_id = await _create_uploaded_attempt(db_maker)
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
    )

    async with db_maker() as session:
        service = TranscriptionService(
            session=session,
            settings=settings,
            stt_provider=MockSTTProvider(),
        )
        await service.transcribe_attempt(attempt_id)
        await service.transcribe_attempt(attempt_id)

    async with db_maker() as session:
        segment_count = await session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.attempt_id == attempt_id)
        )
        transcript = (
            await session.execute(
                select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
            )
        ).scalar_one()

    assert user_id is not None
    assert segment_count == 1
    assert transcript.status == "SUCCEEDED"
    assert transcript.metrics_json is not None
    assert transcript.metrics_json["segment_count"] == 1


async def test_failed_transcription_retry_writes_segments_once(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, attempt_id = await _create_uploaded_attempt(
        db_maker,
        nickname="retry-speaker",
        thread_id="thread-transcription-retry",
    )
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
    )
    provider = FailingOnceSTTProvider()

    async with db_maker() as session:
        service = TranscriptionService(session=session, settings=settings, stt_provider=provider)
        with pytest.raises(ProviderError):
            await service.transcribe_attempt(attempt_id)
        await service.transcribe_attempt(attempt_id)

    async with db_maker() as session:
        segment_count = await session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.attempt_id == attempt_id)
        )
        transcript = (
            await session.execute(
                select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
            )
        ).scalar_one()

    assert segment_count == 1
    assert transcript.status == "SUCCEEDED"
    assert provider.calls == 2


async def test_worker_retry_keeps_transcript_non_terminal_until_retry_succeeds(
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, attempt_id = await _create_uploaded_attempt(
        db_maker,
        nickname="worker-retry-speaker",
        thread_id="thread-worker-transcription-retry",
    )
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
    )
    provider = FailingOnceSTTProvider()
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_module, "get_sessionmaker", lambda: db_maker)

    async with db_maker() as session:
        await AIJobRepository(session).enqueue_transcribe_attempt(attempt_id)
        await session.commit()

    assert await worker_module.run_transcription_job_once(stt_provider=provider) is True
    async with db_maker() as session:
        job = (
            await session.execute(select(AIJob).where(AIJob.job_type == TRANSCRIBE_ATTEMPT_JOB))
        ).scalar_one()
        transcript = (
            await session.execute(
                select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
            )
        ).scalar_one()

    assert job.status == "PENDING"
    assert job.retry_count == 1
    assert transcript.status == "PENDING"
    assert transcript.error_code == "ASR_TIMEOUT"

    assert await worker_module.run_transcription_job_once(stt_provider=provider) is True
    async with db_maker() as session:
        job = (
            await session.execute(select(AIJob).where(AIJob.job_type == TRANSCRIBE_ATTEMPT_JOB))
        ).scalar_one()
        transcript = (
            await session.execute(
                select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
            )
        ).scalar_one()
        segment_count = await session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.attempt_id == attempt_id)
        )

    assert job.status == "SUCCEEDED"
    assert transcript.status == "SUCCEEDED"
    assert segment_count == 1
    assert provider.calls == 2


async def test_transcription_cleans_temporary_audio_after_success(
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, attempt_id = await _create_uploaded_attempt(
        db_maker,
        nickname="cleanup-success",
        thread_id="thread-cleanup-success",
    )
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
    )
    access = TranscriptionAudioAccess(
        url="https://oss.example/asr-temp/audio.webm?signature=redacted",
        object_name="asr-temp/test/audio.webm",
    )
    cleaned: list[TranscriptionAudioAccess] = []

    async def fake_build_transcription_audio_access(**_: object) -> TranscriptionAudioAccess:
        return access

    async def fake_cleanup_transcription_audio_access(
        *,
        settings: Settings,
        access: TranscriptionAudioAccess,
    ) -> None:
        cleaned.append(access)

    monkeypatch.setattr(
        transcription_module,
        "build_transcription_audio_access",
        fake_build_transcription_audio_access,
    )
    monkeypatch.setattr(
        transcription_module,
        "cleanup_transcription_audio_access",
        fake_cleanup_transcription_audio_access,
    )

    async with db_maker() as session:
        service = TranscriptionService(
            session=session,
            settings=settings,
            stt_provider=AssertingUrlSTTProvider(access.url),
        )
        transcript = await service.transcribe_attempt(attempt_id)

    assert transcript.status == "SUCCEEDED"
    assert cleaned == [access]


async def test_transcription_cleans_temporary_audio_after_provider_failure(
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, attempt_id = await _create_uploaded_attempt(
        db_maker,
        nickname="cleanup-failure",
        thread_id="thread-cleanup-failure",
    )
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
    )
    access = TranscriptionAudioAccess(
        url="https://oss.example/asr-temp/audio.webm?signature=redacted",
        object_name="asr-temp/test/audio.webm",
    )
    cleaned: list[TranscriptionAudioAccess] = []

    async def fake_build_transcription_audio_access(**_: object) -> TranscriptionAudioAccess:
        return access

    async def fake_cleanup_transcription_audio_access(
        *,
        settings: Settings,
        access: TranscriptionAudioAccess,
    ) -> None:
        cleaned.append(access)

    monkeypatch.setattr(
        transcription_module,
        "build_transcription_audio_access",
        fake_build_transcription_audio_access,
    )
    monkeypatch.setattr(
        transcription_module,
        "cleanup_transcription_audio_access",
        fake_cleanup_transcription_audio_access,
    )

    async with db_maker() as session:
        service = TranscriptionService(
            session=session,
            settings=settings,
            stt_provider=AlwaysFailingSTTProvider(),
        )
        with pytest.raises(ProviderError):
            await service.transcribe_attempt(attempt_id)

    async with db_maker() as session:
        transcript = (
            await session.execute(
                select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
            )
        ).scalar_one()

    assert cleaned == [access]
    assert transcript.status == "FAILED"
    assert transcript.error_code == "ASR_TIMEOUT"


async def test_transcription_cleanup_failure_does_not_hide_success(
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, attempt_id = await _create_uploaded_attempt(
        db_maker,
        nickname="cleanup-error-success",
        thread_id="thread-cleanup-error-success",
    )
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
    )
    access = TranscriptionAudioAccess(
        url="https://oss.example/asr-temp/audio.webm?signature=redacted",
        object_name="asr-temp/test/audio.webm",
    )

    async def fake_build_transcription_audio_access(**_: object) -> TranscriptionAudioAccess:
        return access

    async def fake_cleanup_transcription_audio_access(
        *,
        settings: Settings,
        access: TranscriptionAudioAccess,
    ) -> None:
        raise AudioAccessError(
            "OSS_CLEANUP_FAILED",
            "Failed to clean up private audio object for ASR",
        )

    monkeypatch.setattr(
        transcription_module,
        "build_transcription_audio_access",
        fake_build_transcription_audio_access,
    )
    monkeypatch.setattr(
        transcription_module,
        "cleanup_transcription_audio_access",
        fake_cleanup_transcription_audio_access,
    )

    async with db_maker() as session:
        service = TranscriptionService(
            session=session,
            settings=settings,
            stt_provider=AssertingUrlSTTProvider(access.url),
        )
        with caplog.at_level(logging.WARNING):
            transcript = await service.transcribe_attempt(attempt_id)

    assert transcript.status == "SUCCEEDED"
    assert any(
        record.__dict__.get("error_code") == "OSS_CLEANUP_FAILED" for record in caplog.records
    )


async def test_unexpected_transcription_error_marks_transcript_failed(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _, attempt_id = await _create_uploaded_attempt(
        db_maker,
        nickname="unexpected-failure",
        thread_id="thread-unexpected-transcription-failure",
    )
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
    )

    async with db_maker() as session:
        service = TranscriptionService(
            session=session,
            settings=settings,
            stt_provider=UnexpectedFailingSTTProvider(),
        )
        with pytest.raises(RuntimeError, match="unexpected parser failure"):
            await service.transcribe_attempt(attempt_id)

    async with db_maker() as session:
        transcript = (
            await session.execute(
                select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
            )
        ).scalar_one()

    assert transcript.status == "FAILED"
    assert transcript.error_code == "RUNTIMEERROR"


async def test_transcript_correction_is_private_and_preserves_raw_text(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="first", password="first-password", role="USER")
    await _create_user(db_maker, nickname="second", password="second-password", role="USER")
    first_token = await _login(client, "first", "first-password")
    second_token = await _login(client, "second", "second-password")
    user_id, attempt_id = await _create_transcribed_attempt(db_maker, nickname="first")
    segment_id = await _segment_id_for_attempt(db_maker, attempt_id)

    forbidden = await client.get(
        f"/api/v1/attempts/{attempt_id}/transcript",
        headers=_auth_headers(second_token),
    )
    assert forbidden.status_code == 404

    corrected = await client.patch(
        f"/api/v1/attempts/{attempt_id}/transcript-correction",
        headers=_auth_headers(first_token),
        json={
            "segment_id": str(segment_id),
            "corrected_text": "正确文本",
            "reason": "STT 把专有名词识别错了",
        },
    )

    assert corrected.status_code == 200
    body = corrected.json()
    assert body["raw_text"] == "错误文本"
    assert body["corrected_text"] == "正确文本"
    assert body["segments"][0]["raw_text"] == "错误文本"
    assert body["segments"][0]["corrected_text"] == "正确文本"

    async with db_maker() as session:
        correction = (
            await session.execute(
                select(TranscriptCorrection).where(TranscriptCorrection.user_id == user_id)
            )
        ).scalar_one()
    assert correction.raw_text == "错误文本"
    assert correction.previous_corrected_text == "错误文本"
    assert correction.corrected_text == "正确文本"


async def test_transcript_correction_rejects_answer_rewrite(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="first", password="first-password", role="USER")
    first_token = await _login(client, "first", "first-password")
    _, attempt_id = await _create_transcribed_attempt(db_maker, nickname="first")
    segment_id = await _segment_id_for_attempt(db_maker, attempt_id)

    rewritten = await client.patch(
        f"/api/v1/attempts/{attempt_id}/transcript-correction",
        headers=_auth_headers(first_token),
        json={
            "segment_id": str(segment_id),
            "corrected_text": "我的最终答案是先暂停项目然后重新制定完整的组织调整方案",
            "reason": "想补充一下刚才没说完的内容",
        },
    )

    assert rewritten.status_code == 400
    assert rewritten.json()["error"]["message"] == "TRANSCRIPT_CORRECTION_TOO_LARGE"
    async with db_maker() as session:
        segment = (
            await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.attempt_id == attempt_id)
            )
        ).scalar_one()
        correction_count = await session.scalar(
            select(func.count())
            .select_from(TranscriptCorrection)
            .where(TranscriptCorrection.attempt_id == attempt_id)
        )

    assert segment.corrected_text == "错误文本"
    assert correction_count == 0


async def test_claim_next_reclaims_expired_running_transcription_job(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_maker() as session:
        stale = AIJob(
            job_type=TRANSCRIBE_ATTEMPT_JOB,
            payload={"attempt_id": str(UUID(int=1))},
            status="RUNNING",
            locked_at=datetime.now(UTC) - timedelta(seconds=TRANSCRIBE_JOB_LEASE_SECONDS + 1),
            idempotency_key="transcribe_attempt:stale",
        )
        session.add(stale)
        await session.commit()
        stale_id = stale.id

    async with db_maker() as session:
        claimed = await AIJobRepository(session).claim_next(TRANSCRIBE_ATTEMPT_JOB)

    assert claimed is not None
    assert claimed.id == stale_id
    assert claimed.status == "RUNNING"


async def _create_user(
    maker: async_sessionmaker[AsyncSession],
    *,
    nickname: str,
    password: str,
    role: str,
) -> UUID:
    async with maker() as session:
        user = await UserRepository(session).create_user(
            nickname=nickname,
            password_hash=hash_password(password),
            role=role,
        )
        await session.commit()
        return user.id


async def _create_uploaded_attempt(
    maker: async_sessionmaker[AsyncSession],
    *,
    nickname: str = "speaker",
    thread_id: str = "thread-transcription",
) -> tuple[UUID, UUID]:
    user_id = await _create_user(
        maker,
        nickname=nickname,
        password="speaker-password",
        role="USER",
    )
    async with maker() as session:
        training_session = TrainingSession(user_id=user_id, thread_id=thread_id)
        session.add(training_session)
        await session.flush()
        attempt = VoiceAttempt(
            session_id=training_session.id,
            stage="FIRST",
            round=1,
            audio_path="speaker/session/attempt.webm",
            mime_type="audio/webm",
            duration_ms=1200,
            size_bytes=10,
            checksum_sha256="a" * 64,
            upload_status="UPLOADED",
        )
        session.add(attempt)
        await session.commit()
        return user_id, attempt.id


async def _create_transcribed_attempt(
    maker: async_sessionmaker[AsyncSession],
    *,
    nickname: str,
) -> tuple[UUID, UUID]:
    async with maker() as session:
        user = (
            await session.execute(
                select(_models.AppUser).where(_models.AppUser.nickname == nickname)
            )
        ).scalar_one()
        training_session = TrainingSession(user_id=user.id, thread_id="thread-correction")
        session.add(training_session)
        await session.flush()
        attempt = VoiceAttempt(
            session_id=training_session.id,
            stage="FIRST",
            round=1,
            audio_path="speaker/session/attempt.webm",
            mime_type="audio/webm",
            duration_ms=1200,
            size_bytes=10,
            checksum_sha256="b" * 64,
            upload_status="UPLOADED",
        )
        session.add(attempt)
        await session.flush()
        session.add(
            AttemptTranscript(
                attempt_id=attempt.id,
                status="SUCCEEDED",
                raw_text="错误文本",
                corrected_text="错误文本",
                metrics_json={"segment_count": 1},
            )
        )
        session.add(
            TranscriptSegment(
                attempt_id=attempt.id,
                segment_index=0,
                start_ms=0,
                end_ms=1000,
                raw_text="错误文本",
                corrected_text="错误文本",
                words_json=[{"text": "错误文本", "start_ms": 0, "end_ms": 1000}],
            )
        )
        await session.commit()
        return user.id, attempt.id


async def _segment_id_for_attempt(
    maker: async_sessionmaker[AsyncSession],
    attempt_id: UUID,
) -> UUID:
    async with maker() as session:
        segment = (
            await session.execute(
                select(TranscriptSegment).where(TranscriptSegment.attempt_id == attempt_id)
            )
        ).scalar_one()
        return segment.id


async def _login(client: AsyncClient, nickname: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"nickname": nickname, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _assert_test_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(f"Refusing to reset non-test database: {database_name}")


class FailingOnceSTTProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._mock = MockSTTProvider()

    async def transcribe(self, request: STTRequest) -> STTResponse:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("ASR_TIMEOUT", "temporary ASR failure", provider="mock")
        return await self._mock.transcribe(request)


class AssertingUrlSTTProvider:
    def __init__(self, expected_audio_url: str) -> None:
        self.expected_audio_url = expected_audio_url
        self._mock = MockSTTProvider()

    async def transcribe(self, request: STTRequest) -> STTResponse:
        assert request.audio_url == self.expected_audio_url
        return await self._mock.transcribe(request)


class AlwaysFailingSTTProvider:
    async def transcribe(self, request: STTRequest) -> STTResponse:
        raise ProviderError("ASR_TIMEOUT", "temporary ASR failure", provider="mock")


class UnexpectedFailingSTTProvider:
    async def transcribe(self, request: STTRequest) -> STTResponse:
        raise RuntimeError("unexpected parser failure")
