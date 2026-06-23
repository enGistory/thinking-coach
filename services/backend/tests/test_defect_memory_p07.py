from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.db.models import (
    Appeal,
    AppUser,
    DefectEvidence,
    DefectOccurrence,
    DefectProfile,
    EvaluationIssue,
    EvaluationReport,
    TrainingSession,
    VoiceAttempt,
)
from app.db.session import get_session
from app.main import create_app
from app.repositories.defects import DefectMemoryRepository
from app.services.defects import DefectMemoryService

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_DATABASE_SYNC_URL = os.getenv("TEST_DATABASE_SYNC_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None or TEST_DATABASE_SYNC_URL is None,
    reason="TEST_DATABASE_URL and TEST_DATABASE_SYNC_URL are required for P07 tests",
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
    tmp_path,
) -> AsyncIterator[AsyncClient]:
    def test_settings() -> Settings:
        return Settings(
            _env_file=None,
            ai_provider_mode="mock",
            jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
            audio_root=tmp_path,
            audio_retention_days=30,
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


async def test_sync_report_is_idempotent(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "user-one")
    _, report_id, _ = await _seed_report(db_maker, user_id=user_id)

    async with db_maker() as session:
        service = DefectMemoryService(session=session)
        assert await service.sync_report(report_id=report_id, user_id=user_id) == ["ALIGN-01"]
        assert await service.sync_report(report_id=report_id, user_id=user_id) == ["ALIGN-01"]
        await session.commit()

    async with db_maker() as session:
        occurrence_count = await session.scalar(select(func.count()).select_from(DefectOccurrence))
        evidence_count = await session.scalar(select(func.count()).select_from(DefectEvidence))
        profile = await _profile(session, user_id, "ALIGN-01")

    assert occurrence_count == 1
    assert evidence_count == 1
    assert profile is not None
    assert profile.state == "observed"
    assert profile.active_occurrence_count == 1


async def test_low_confidence_issue_creates_pending_occurrence_without_profile_weight(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "user-low")
    _, report_id, _ = await _seed_report(db_maker, user_id=user_id, confidence="low")

    async with db_maker() as session:
        await DefectMemoryService(session=session).sync_report(report_id=report_id, user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        occurrence = (
            await session.execute(
                select(DefectOccurrence).where(DefectOccurrence.user_id == user_id)
            )
        ).scalar_one()
        profile = await _profile(session, user_id, "ALIGN-01")

    assert occurrence.status == "PENDING"
    assert profile is not None
    assert profile.active_occurrence_count == 0
    assert profile.priority == 0


async def test_sync_report_ignores_issue_attempt_from_another_session(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "user-mismatched-attempt")
    async with db_maker() as session:
        report_session = TrainingSession(
            user_id=user_id,
            thread_id=f"thread-{uuid4()}",
            stage="COMPLETED",
        )
        other_session = TrainingSession(
            user_id=user_id,
            thread_id=f"thread-{uuid4()}",
            stage="COMPLETED",
        )
        session.add_all([report_session, other_session])
        await session.flush()
        other_attempt = VoiceAttempt(
            session_id=other_session.id,
            stage="FIRST",
            round=1,
            upload_status="UPLOADED",
        )
        session.add(other_attempt)
        await session.flush()
        report = EvaluationReport(
            session_id=report_session.id,
            status="COMPLETED",
            details_json={},
            logic_score=60,
            speech_score=80,
            adaptability_score=70,
            final_score=60,
        )
        session.add(report)
        await session.flush()
        session.add(
            EvaluationIssue(
                report_id=report.id,
                attempt_id=other_attempt.id,
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
        )
        await session.commit()
        report_id = report.id

    async with db_maker() as session:
        affected = await DefectMemoryService(session=session).sync_report(
            report_id=report_id,
            user_id=user_id,
        )
        await session.commit()

    async with db_maker() as session:
        occurrence_count = await session.scalar(select(func.count()).select_from(DefectOccurrence))

    assert affected == []
    assert occurrence_count == 0


async def test_profile_confirms_only_after_three_occurrences_across_two_scenarios(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "user-confirmed")
    first_question = uuid4()
    second_question = uuid4()
    reports = [
        (
            await _seed_report(
                db_maker,
                user_id=user_id,
                question_id=first_question,
                severity=3,
                stage="FIRST",
                quote="first scenario missed the decision",
            )
        )[1],
        (
            await _seed_report(
                db_maker,
                user_id=user_id,
                question_id=second_question,
                severity=3,
                stage="FIRST",
                quote="second scenario missed the decision",
            )
        )[1],
        (
            await _seed_report(
                db_maker,
                user_id=user_id,
                question_id=second_question,
                severity=3,
                stage="FINAL",
                quote="final answer still missed the decision",
            )
        )[1],
    ]

    async with db_maker() as session:
        service = DefectMemoryService(session=session)
        for report_id in reports:
            await service.sync_report(report_id=report_id, user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        profile = await _profile(session, user_id, "ALIGN-01")
        confirmed_count = await session.scalar(
            select(func.count())
            .select_from(DefectOccurrence)
            .where(
                DefectOccurrence.user_id == user_id,
                DefectOccurrence.defect_code == "ALIGN-01",
                DefectOccurrence.confirmed.is_(True),
            )
        )

    assert profile is not None
    assert profile.state == "confirmed"
    assert profile.scenario_count == 2
    assert profile.active_occurrence_count == 3
    assert confirmed_count == 3


async def test_recurrence_high_priority_is_idempotent_when_report_resyncs(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "user-recurrence-idempotent")
    _, report_id, _ = await _seed_report(
        db_maker,
        user_id=user_id,
        question_id=uuid4(),
        severity=3,
        stage="FIRST",
        quote="recurrent issue after stable improvement",
    )

    async with db_maker() as session:
        await DefectMemoryRepository(session).ensure_definitions()
        session.add(
            DefectProfile(
                user_id=user_id,
                defect_code="ALIGN-01",
                state="stable-improved",
                severity=0,
                frequency=0,
                recurrence=0,
                priority=0,
                confidence=0,
                active_occurrence_count=0,
                suspended_occurrence_count=0,
                scenario_count=0,
            )
        )
        service = DefectMemoryService(session=session)
        await service.sync_report(report_id=report_id, user_id=user_id)
        await service.sync_report(report_id=report_id, user_id=user_id)
        await session.commit()

    async with db_maker() as session:
        profile = await _profile(session, user_id, "ALIGN-01")

    assert profile is not None
    assert profile.state == "high-priority"
    assert profile.recurrence == 1
    assert profile.active_occurrence_count == 1


async def test_appeal_suspends_occurrence_until_review(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "user-appeal")
    session_id, report_id, issue_id = await _seed_report(db_maker, user_id=user_id)

    async with db_maker() as session:
        service = DefectMemoryService(session=session)
        await service.sync_report(report_id=report_id, user_id=user_id)
        appeal = await service.create_appeal(
            user_id=user_id,
            session_id=session_id,
            appeal_type="evaluation",
            reason="这条评审误解了我的表达",
            issue_id=issue_id,
            defect_code=None,
        )
        await session.commit()
        appeal_id = appeal.id

    async with db_maker() as session:
        occurrence = (
            await session.execute(
                select(DefectOccurrence).where(DefectOccurrence.issue_id == issue_id)
            )
        ).scalar_one()
        profile = await _profile(session, user_id, "ALIGN-01")

    assert occurrence.status == "SUSPENDED"
    assert occurrence.previous_status == "ACTIVE"
    assert profile is not None
    assert profile.active_occurrence_count == 0
    assert profile.suspended_occurrence_count == 1

    async with db_maker() as session:
        await DefectMemoryService(session=session).review_appeal(
            appeal_id=appeal_id,
            user_id=user_id,
            accepted=False,
            resolution="复核后维持原评审",
        )
        await session.commit()

    async with db_maker() as session:
        occurrence = (
            await session.execute(
                select(DefectOccurrence).where(DefectOccurrence.issue_id == issue_id)
            )
        ).scalar_one()
        profile = await _profile(session, user_id, "ALIGN-01")

    assert occurrence.status == "ACTIVE"
    assert profile is not None
    assert profile.active_occurrence_count == 1


async def test_accepted_appeal_excludes_occurrence_from_profile(
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, "user-accepted-appeal")
    session_id, report_id, issue_id = await _seed_report(db_maker, user_id=user_id)

    async with db_maker() as session:
        service = DefectMemoryService(session=session)
        await service.sync_report(report_id=report_id, user_id=user_id)
        appeal = await service.create_appeal(
            user_id=user_id,
            session_id=session_id,
            appeal_type="defect_classification",
            reason="这个问题不属于该缺陷",
            issue_id=issue_id,
            defect_code="ALIGN-01",
        )
        await service.review_appeal(
            appeal_id=appeal.id,
            user_id=user_id,
            accepted=True,
            resolution="复核通过, 排除该缺陷累计",
        )
        await session.commit()

    async with db_maker() as session:
        occurrence = (
            await session.execute(
                select(DefectOccurrence).where(DefectOccurrence.issue_id == issue_id)
            )
        ).scalar_one()
        profile = await _profile(session, user_id, "ALIGN-01")

    assert occurrence.status == "EXCLUDED"
    assert occurrence.previous_status is None
    assert profile is not None
    assert profile.active_occurrence_count == 0
    assert profile.suspended_occurrence_count == 0

    async with db_maker() as session:
        service = DefectMemoryService(session=session)
        reviewed = await service.review_appeal(
            appeal_id=appeal.id,
            user_id=user_id,
            accepted=False,
            resolution="二次复核不应翻转结果",
        )
        await session.commit()

    async with db_maker() as session:
        occurrence = (
            await session.execute(
                select(DefectOccurrence).where(DefectOccurrence.issue_id == issue_id)
            )
        ).scalar_one()

    assert reviewed.status == "REVIEWED_ACCEPTED"
    assert occurrence.status == "EXCLUDED"


async def test_defect_api_is_user_scoped_and_appeal_excludes_profile_weight(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    first_user = await _create_user(db_maker, "api-first")
    second_user = await _create_user(db_maker, "api-second")
    first_session, first_report, first_issue = await _seed_report(
        db_maker,
        user_id=first_user,
        quote="first user missed the core decision",
    )
    _, second_report, _ = await _seed_report(
        db_maker,
        user_id=second_user,
        quote="second user missed the core decision",
    )
    async with db_maker() as session:
        service = DefectMemoryService(session=session)
        await service.sync_report(report_id=first_report, user_id=first_user)
        await service.sync_report(report_id=second_report, user_id=second_user)
        await session.commit()

    first_headers = _auth_headers(first_user)
    second_headers = _auth_headers(second_user)

    profiles = await client.get("/api/v1/me/defects", headers=first_headers)
    assert profiles.status_code == 200
    assert [item["code"] for item in profiles.json()] == ["ALIGN-01"]

    occurrences = await client.get(
        "/api/v1/me/defects/ALIGN-01/occurrences",
        headers=first_headers,
    )
    assert occurrences.status_code == 200
    assert occurrences.json()[0]["quote"] == "first user missed the core decision"
    assert "same_defect_code" in occurrences.json()[0]["similarity_reasons"]

    forbidden_appeal = await client.post(
        f"/api/v1/trainings/{first_session}/appeals",
        headers=second_headers,
        json={
            "type": "evaluation",
            "reason": "不应能申诉他人的 session",
            "issue_id": str(first_issue),
        },
    )
    assert forbidden_appeal.status_code == 404

    empty_target_appeal = await client.post(
        f"/api/v1/trainings/{first_session}/appeals",
        headers=first_headers,
        json={
            "type": "evaluation",
            "reason": "缺少具体申诉目标",
        },
    )
    assert empty_target_appeal.status_code == 422

    mismatched_target_appeal = await client.post(
        f"/api/v1/trainings/{first_session}/appeals",
        headers=first_headers,
        json={
            "type": "defect_classification",
            "reason": "该 issue 不属于这个缺陷分类",
            "issue_id": str(first_issue),
            "defect_code": "STRUCT-01",
        },
    )
    assert mismatched_target_appeal.status_code == 404
    async with db_maker() as session:
        appeal_count = await session.scalar(select(func.count()).select_from(Appeal))
    assert appeal_count == 0

    appeal = await client.post(
        f"/api/v1/trainings/{first_session}/appeals",
        headers=first_headers,
        json={
            "type": "evaluation",
            "reason": "这条评审误解了我的表达",
            "issue_id": str(first_issue),
        },
    )
    assert appeal.status_code == 201
    assert appeal.json()["status"] == "OPEN"

    updated_profiles = await client.get("/api/v1/me/defects", headers=first_headers)
    assert updated_profiles.status_code == 200
    assert updated_profiles.json()[0]["active_occurrence_count"] == 0
    assert updated_profiles.json()[0]["suspended_occurrence_count"] == 1


async def _create_user(
    maker: async_sessionmaker[AsyncSession],
    nickname: str,
) -> UUID:
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


async def _seed_report(
    maker: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    code: str = "ALIGN-01",
    severity: int = 4,
    confidence: str = "high",
    question_id: UUID | None = None,
    stage: str = "FIRST",
    quote: str = "answer missed the core",
) -> tuple[UUID, UUID, UUID]:
    async with maker() as session:
        training_session = TrainingSession(
            user_id=user_id,
            question_id=question_id,
            thread_id=f"thread-{uuid4()}",
            stage="COMPLETED",
        )
        session.add(training_session)
        await session.flush()
        attempt = VoiceAttempt(
            session_id=training_session.id,
            stage=stage,
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
            code=code,
            severity=severity,
            confidence=confidence,
            quote=quote,
            start_ms=0,
            end_ms=1000,
            explanation="The answer does not address the decision.",
            missing_information=["goal"],
            correction_rule="State the core decision first.",
            verification_json={"evidence_valid": True},
        )
        session.add(issue)
        await session.commit()
        return training_session.id, report.id, issue.id


async def _profile(
    session: AsyncSession,
    user_id: UUID,
    defect_code: str,
) -> DefectProfile | None:
    return (
        await session.execute(
            select(DefectProfile).where(
                DefectProfile.user_id == user_id,
                DefectProfile.defect_code == defect_code,
            )
        )
    ).scalar_one_or_none()


def _auth_headers(user_id: UUID) -> dict[str, str]:
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
    )
    return {"Authorization": f"Bearer {create_access_token(user_id, 'USER', settings)}"}


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
