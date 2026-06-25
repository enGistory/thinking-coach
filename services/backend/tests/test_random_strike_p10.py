from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import (
    AppUser,
    DefectOccurrence,
    EvaluationReport,
    PushSubscription,
    Question,
    TrainingSession,
    VoiceAttempt,
)
from app.db.session import get_session
from app.main import create_app
from app.repositories.auth import UserRepository
from app.repositories.training_policy import TrainingPolicyRepository
from app.repositories.trainings import TrainingRepository
from app.services.push import PushDeliveryResult
from app.services.random_strike import RandomStrikeService
from tests.helpers_source_questions import seed_ready_question

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="TEST_DATABASE_URL is required for P10 random strike tests",
)


class FakePushSender:
    def __init__(self, result: PushDeliveryResult | None = None) -> None:
        self.result = result or PushDeliveryResult(delivered=True)
        self.payloads: list[dict[str, object]] = []

    async def send(
        self,
        *,
        subscription: PushSubscription,
        payload: dict[str, object],
    ) -> PushDeliveryResult:
        self.payloads.append(payload)
        return self.result


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
    monkeypatch.setattr("app.api.v1.push.get_settings", lambda: settings)
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


async def test_push_subscription_and_accept_hide_question_until_accept(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "p10-user")
    token = _token(user_id)
    now = datetime.now(UTC)
    session_id = await _seed_notified_session(db_maker, user_id=user_id, now=now)

    public_key = await client.get("/api/v1/push/public-key")
    subscription = await client.post(
        "/api/v1/push/subscriptions",
        headers=_auth_headers(token),
        json={
            "endpoint": "https://push.example/subscription/1",
            "keys": {"p256dh": "p256dh-key", "auth": "auth-key"},
        },
    )
    current = await client.get("/api/v1/trainings/current", headers=_auth_headers(token))
    hidden_state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(token),
    )
    accepted = await client.post(
        f"/api/v1/trainings/{session_id}/accept",
        headers=_auth_headers(token),
    )
    exposed_state = await client.get(
        f"/api/v1/trainings/{session_id}/state",
        headers=_auth_headers(token),
    )

    assert public_key.status_code == 200
    assert public_key.json()["public_key"] == "test-vapid-public"
    assert subscription.status_code == 201
    assert current.status_code == 200
    assert current.json()["stage"] == "NOTIFIED"
    assert hidden_state.status_code == 200
    assert hidden_state.json()["awaiting"] is None
    assert hidden_state.json()["source_summary"] is None
    assert accepted.status_code == 200
    assert accepted.json()["stage"] == "WAIT_FIRST_AUDIO"
    assert exposed_state.json()["awaiting"]["type"] == "FIRST_ANSWER"
    assert exposed_state.json()["source_summary"]["source_count"] == 1

    async with db_maker() as session:
        training = await session.get(TrainingSession, session_id)
        assert training is not None
        assert training.exposed_at is not None
        question = await session.get(Question, training.question_id)
        assert question is not None
        assert question.status == "EXPOSED"
        assert question.exposed_count == 1


async def test_current_does_not_return_expired_notification(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "p10-expired-current")
    token = _token(user_id)
    expired_at = datetime.now(UTC) - timedelta(minutes=10)
    await _seed_notified_session(db_maker, user_id=user_id, now=expired_at)

    current = await client.get("/api/v1/trainings/current", headers=_auth_headers(token))

    assert current.status_code == 404
    assert current.json()["error"]["code"] == "NO_CURRENT_TRAINING"


async def test_scheduler_sends_neutral_notification_and_expired_failure_does_not_score(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user_id = await _create_user(db_maker, "p10-scheduler")
    now = datetime(2026, 6, 24, 2, 0, tzinfo=UTC)
    fake_sender = FakePushSender()

    async with db_maker() as session:
        await seed_ready_question(session, user_id=user_id)
        session.add(
            PushSubscription(
                user_id=user_id,
                endpoint="https://push.example/subscription/2",
                p256dh="p256dh-key",
                auth="auth-key",
                user_agent="test",
                active=True,
            )
        )
        await session.commit()

    async with db_maker() as session:
        user = await session.get(AppUser, user_id)
        assert user is not None
        service = RandomStrikeService(
            session=session,
            settings=_test_settings(tmp_path),
            push_sender=fake_sender,
        )
        result = await service.schedule_for_user(
            user=user,
            now=now,
            rng=Random(3),
        )
        assert result.session is not None
        result.session.scheduled_at = now
        await session.commit()

    async with db_maker() as session:
        service = RandomStrikeService(
            session=session,
            settings=_test_settings(tmp_path),
            push_sender=fake_sender,
        )
        sent = await service.send_due_notifications(now=now)
        await session.commit()

    assert sent == 1
    assert fake_sender.payloads
    payload_text = json.dumps(fake_sender.payloads[0], ensure_ascii=False)
    assert "突击审核已到达" in payload_text
    assert "ALIGN-01" not in payload_text

    failing_user_id = await _create_user(db_maker, "p10-no-push")
    failed_session_id = await _seed_scheduled_session(
        db_maker,
        user_id=failing_user_id,
        now=now,
    )
    async with db_maker() as session:
        service = RandomStrikeService(
            session=session,
            settings=_test_settings(tmp_path),
            push_sender=FakePushSender(),
        )
        await service.send_due_notifications(now=now)
        await session.commit()

    async with db_maker() as session:
        failed = await session.get(TrainingSession, failed_session_id)
        attempt_count = await session.scalar(select(func.count()).select_from(VoiceAttempt))
        report_count = await session.scalar(select(func.count()).select_from(EvaluationReport))
        occurrence_count = await session.scalar(select(func.count()).select_from(DefectOccurrence))

    assert failed is not None
    assert failed.stage == "EXPIRED"
    assert failed.push_error_code == "NO_ACTIVE_PUSH_SUBSCRIPTION"
    assert attempt_count == 0
    assert report_count == 0
    assert occurrence_count == 0


async def test_defer_does_not_expose_and_abandon_keeps_question_retired(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "p10-defer")
    token = _token(user_id)
    now = datetime.now(UTC)
    defer_session_id = await _seed_notified_session(db_maker, user_id=user_id, now=now)

    deferred = await client.post(
        f"/api/v1/trainings/{defer_session_id}/defer",
        headers=_auth_headers(token),
    )

    assert deferred.status_code == 200
    assert deferred.json()["stage"] == "SCHEDULED"

    async with db_maker() as session:
        deferred_session = await session.get(TrainingSession, defer_session_id)
        assert deferred_session is not None
        assert deferred_session.exposed_at is None

    accept_user_id = await _create_user(db_maker, "p10-abandon")
    accept_token = _token(accept_user_id)
    accept_session_id = await _seed_notified_session(
        db_maker,
        user_id=accept_user_id,
        now=now,
    )
    accepted = await client.post(
        f"/api/v1/trainings/{accept_session_id}/accept",
        headers=_auth_headers(accept_token),
    )
    abandoned = await client.post(
        f"/api/v1/trainings/{accept_session_id}/abandon",
        headers=_auth_headers(accept_token),
    )

    assert accepted.status_code == 200
    assert abandoned.status_code == 200
    assert abandoned.json()["stage"] == "ABANDONED"

    async with db_maker() as session:
        training = await session.get(TrainingSession, accept_session_id)
        assert training is not None
        question = await session.get(Question, training.question_id)
        assert question is not None
        assert question.status == "EXPOSED"
        assert question.exposed_count == 1


async def _create_user(maker: async_sessionmaker[AsyncSession], nickname: str) -> UUID:
    async with maker() as session:
        user = await UserRepository(session).create_user(
            nickname=nickname,
            password_hash="fake-password-hash",
            role="USER",
        )
        await TrainingPolicyRepository(session).create_for_user(
            user_id=user.id,
            policy={
                "windows": [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "09:00", "end": "21:00"}],
                "quiet_hours": [{"start": "22:00", "end": "08:00"}],
                "daily_max": 2,
                "retention_days": 30,
                "timezone": "Asia/Shanghai",
            },
        )
        await session.commit()
        return user.id


async def _seed_notified_session(
    maker: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    now: datetime,
) -> UUID:
    async with maker() as session:
        question = await seed_ready_question(session, user_id=user_id)
        training_session = TrainingSession(
            id=uuid4(),
            user_id=user_id,
            question_id=question.id,
            thread_id=f"p10-{uuid4()}",
            stage="NOTIFIED",
            scheduled_at=now,
            notified_at=now,
            notification_expires_at=now + timedelta(minutes=5),
            push_status="SUCCEEDED",
        )
        session.add(training_session)
        await session.commit()
        return training_session.id


async def _seed_scheduled_session(
    maker: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    now: datetime,
) -> UUID:
    async with maker() as session:
        question = await seed_ready_question(session, user_id=user_id)
        training_session = await TrainingRepository(session).create_scheduled_session(
            user_id=user_id,
            question_id=question.id,
            scheduled_at=now,
            delivery_decision={"reason": "test"},
        )
        await session.commit()
        return training_session.id


def _token(user_id: UUID) -> str:
    return create_access_token(user_id, "USER", _test_settings(Path(".")))


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        web_push_vapid_public_key="test-vapid-public",
        web_push_vapid_private_key=SecretStr("test-vapid-private"),
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
