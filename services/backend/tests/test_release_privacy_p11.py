from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
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
    AIJob,
    Appeal,
    AppUser,
    AttemptTranscript,
    DefectDefinition,
    DefectEvidence,
    DefectOccurrence,
    DefectProfile,
    EvaluationIssue,
    EvaluationReport,
    ModelRun,
    PrivacyAuditEvent,
    PrivacyDeletionRequest,
    PushSubscription,
    Question,
    QuestionClaimMap,
    QuestionDedupeCheck,
    QuestionDuplicateComplaint,
    QuestionFingerprint,
    QuestionRubric,
    QuestionSource,
    QuestionTemplateDenylist,
    RefreshToken,
    SourceBundle,
    SourceClaim,
    TrainingSession,
    TranscriptCorrection,
    TranscriptSegment,
    UserTrainingPolicy,
    VoiceAttempt,
    WeeklyReport,
)
from app.db.session import get_session
from app.main import create_app
from app.repositories.auth import RefreshTokenRepository
from app.repositories.jobs import DELETE_ACCOUNT_JOB
from app.services.defects import DefectMemoryError, DefectMemoryService
from app.services.privacy import PrivacyService
from app.services.reports import ReportService
from tests.helpers_source_questions import seed_exposed_training_session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_DATABASE_SYNC_URL = os.getenv("TEST_DATABASE_SYNC_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None or TEST_DATABASE_SYNC_URL is None,
    reason="TEST_DATABASE_URL and TEST_DATABASE_SYNC_URL are required for P11 privacy tests",
)


@dataclass(frozen=True)
class SeededTraining:
    user_id: UUID
    session_id: UUID
    thread_id: str
    question_id: UUID
    source_bundle_id: UUID
    attempt_id: UUID
    transcript_id: UUID
    segment_id: UUID
    correction_id: UUID
    report_id: UUID
    issue_id: UUID
    occurrence_id: UUID
    audio_relative_path: str


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

    def test_settings() -> Settings:
        return settings

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with db_maker() as session:
            yield session

    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", test_settings)
    monkeypatch.setattr("app.api.dependencies.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.me.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.privacy.get_settings", test_settings)
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


async def test_delete_training_removes_audio_checkpoint_and_business_rows(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    async with db_maker() as session:
        user = await _create_user(session, "training-delete")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        session.add(
            Appeal(
                user_id=user.id,
                session_id=seeded.session_id,
                issue_id=seeded.issue_id,
                defect_code="ALIGN-01",
                type="evaluation",
                target_json={"issue_id": str(seeded.issue_id)},
                reason="Evaluation dispute that should be deleted with the session.",
                status="OPEN",
            )
        )
        session.add(
            QuestionDuplicateComplaint(
                user_id=user.id,
                session_id=seeded.session_id,
                question_id=seeded.question_id,
                duplicate_type="semantic",
                template_family="test-p08",
                reason="Duplicate complaint that should be deleted with the session.",
                status="ACCEPTED",
            )
        )
        await _insert_checkpoint_rows(session, seeded.thread_id)
        await _add_user_scoped_model_run(
            session,
            user_id=user.id,
            session_id=seeded.session_id,
            attempt_id=seeded.attempt_id,
        )
        await session.commit()

    audio_path = tmp_path / seeded.audio_relative_path
    assert audio_path.exists()

    async with db_maker() as session:
        response = await PrivacyService(session=session, settings=settings).delete_training(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )
        await session.commit()

    assert response.deleted is True
    assert response.counts["sessions"] == 1
    assert response.counts["attempts"] == 1
    assert response.counts["transcripts"] == 1
    assert response.counts["transcript_segments"] == 1
    assert response.counts["transcript_corrections"] == 1
    assert response.counts["defect_occurrences"] == 1
    assert response.counts["defect_evidence"] == 1
    assert response.counts["reports"] == 1
    assert response.counts["issues"] == 1
    assert response.counts["appeals"] == 1
    assert response.counts["duplicate_complaints"] == 1
    assert response.counts["ai_jobs"] == 1
    assert response.counts["model_runs"] == 1
    assert response.counts["checkpoint_rows"] == 3
    assert response.counts["questions"] == 1
    assert response.counts["source_bundles"] == 1
    assert response.counts["question_sources"] == 1
    assert response.counts["source_claims"] == 1
    assert response.counts["question_claim_maps"] == 1
    assert response.counts["question_fingerprints"] == 1
    assert response.counts["question_rubrics"] == 2
    assert response.counts["audio_file_references"] == 1
    assert response.counts["audio_files"] == 1
    assert not audio_path.exists()

    async with db_maker() as session:
        assert await session.get(TrainingSession, seeded.session_id) is None
        assert await session.get(VoiceAttempt, seeded.attempt_id) is None
        assert await session.get(AttemptTranscript, seeded.transcript_id) is None
        assert await session.get(TranscriptSegment, seeded.segment_id) is None
        assert await session.get(TranscriptCorrection, seeded.correction_id) is None
        assert await session.get(EvaluationReport, seeded.report_id) is None
        assert await session.get(EvaluationIssue, seeded.issue_id) is None
        assert await session.get(DefectOccurrence, seeded.occurrence_id) is None
        assert await _row_count(session, DefectEvidence) == 0
        assert await _row_count(session, Appeal) == 0
        assert await _row_count(session, QuestionDuplicateComplaint) == 0
        assert await session.get(Question, seeded.question_id) is None
        assert await session.get(SourceBundle, seeded.source_bundle_id) is None
        assert await _row_count(session, QuestionSource) == 0
        assert await _row_count(session, SourceClaim) == 0
        assert await _row_count(session, QuestionClaimMap) == 0
        assert await _row_count(session, QuestionFingerprint) == 0
        assert await _row_count(session, QuestionRubric) == 0
        assert await _row_count(session, AIJob) == 0
        assert await _row_count(session, ModelRun) == 0
        assert await _checkpoint_row_count(session) == 0
        audit = await _audit_event(session, "DELETE_TRAINING")
        assert audit is not None
        assert audit.status == "SUCCEEDED"
        assert audit.counts_json["sessions"] == 1
        assert audit.counts_json["audio_file_references"] == 1
        assert audit.counts_json["audio_files"] == 1


async def test_release_delete_training_distinguishes_missing_audio_file(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    async with db_maker() as session:
        user = await _create_user(session, "delete-training-missing-audio")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        await session.commit()

    audio_path = tmp_path / seeded.audio_relative_path
    audio_path.unlink()

    async with db_maker() as session:
        response = await PrivacyService(session=session, settings=settings).delete_training(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )
        await session.commit()

    assert response.counts["audio_file_references"] == 1
    assert response.counts["audio_files"] == 0

    async with db_maker() as session:
        assert await session.get(TrainingSession, seeded.session_id) is None
        assert await session.get(VoiceAttempt, seeded.attempt_id) is None


async def test_release_delete_training_continues_when_audio_reference_escapes_root(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside-audio"
    outside_dir.mkdir()
    outside_file = outside_dir / "escaped.webm"
    outside_file.write_bytes(b"do-not-delete")
    invalid_relative_path = f"../{outside_dir.name}/{outside_file.name}"
    async with db_maker() as session:
        user = await _create_user(session, "delete-training-invalid-audio")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        attempt = await session.get(VoiceAttempt, seeded.attempt_id)
        assert attempt is not None
        attempt.audio_path = invalid_relative_path
        await session.commit()

    original_audio = tmp_path / seeded.audio_relative_path
    original_audio.unlink()

    async with db_maker() as session:
        response = await PrivacyService(session=session, settings=settings).delete_training(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )
        await session.commit()

    assert response.counts["audio_file_references"] == 1
    assert response.counts["audio_files"] == 0
    assert response.counts["audio_file_invalid_references"] == 1
    assert response.counts["audio_file_non_file_references"] == 0
    assert outside_file.exists()

    async with db_maker() as session:
        assert await session.get(TrainingSession, seeded.session_id) is None
        assert await session.get(VoiceAttempt, seeded.attempt_id) is None
        audit = await _audit_event(session, "DELETE_TRAINING")
        assert audit is not None
        assert audit.counts_json["audio_file_invalid_references"] == 1

    outside_file.unlink()
    outside_dir.rmdir()


async def test_release_delete_training_counts_non_file_audio_reference(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    non_file_relative_path = "non-file-audio-reference"
    non_file_path = tmp_path / non_file_relative_path
    non_file_path.mkdir()
    async with db_maker() as session:
        user = await _create_user(session, "delete-training-non-file-audio")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        attempt = await session.get(VoiceAttempt, seeded.attempt_id)
        assert attempt is not None
        attempt.audio_path = non_file_relative_path
        await session.commit()

    original_audio = tmp_path / seeded.audio_relative_path
    original_audio.unlink()

    async with db_maker() as session:
        response = await PrivacyService(session=session, settings=settings).delete_training(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )
        await session.commit()

    assert response.counts["audio_file_references"] == 1
    assert response.counts["audio_files"] == 0
    assert response.counts["audio_file_invalid_references"] == 0
    assert response.counts["audio_file_non_file_references"] == 1
    assert non_file_path.exists()

    async with db_maker() as session:
        assert await session.get(TrainingSession, seeded.session_id) is None
        assert await session.get(VoiceAttempt, seeded.attempt_id) is None
        audit = await _audit_event(session, "DELETE_TRAINING")
        assert audit is not None
        assert audit.counts_json["audio_file_non_file_references"] == 1

    non_file_path.rmdir()


async def test_account_deletion_disables_login_scope_then_removes_user_data(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _test_settings(tmp_path)
    async with db_maker() as session:
        user = await _create_user(session, "account-delete")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        session.add(
            Appeal(
                user_id=user.id,
                session_id=seeded.session_id,
                issue_id=seeded.issue_id,
                defect_code="ALIGN-01",
                type="evaluation",
                target_json={"issue_id": str(seeded.issue_id)},
                reason="Account deletion appeal cleanup.",
                status="OPEN",
            )
        )
        session.add(
            QuestionDuplicateComplaint(
                user_id=user.id,
                session_id=seeded.session_id,
                question_id=seeded.question_id,
                duplicate_type="semantic",
                template_family="test-p08",
                reason="Account deletion duplicate cleanup.",
                status="ACCEPTED",
            )
        )
        session.add(
            UserTrainingPolicy(
                user_id=user.id,
                windows=[{"start": "09:00", "end": "18:00"}],
                quiet_hours=[],
                daily_max=1,
                retention_days=30,
                timezone="Asia/Shanghai",
            )
        )
        session.add(
            PushSubscription(
                user_id=user.id,
                endpoint=f"https://push.example.test/{user.id}",
                p256dh="test-p256dh",
                auth="test-auth",
                user_agent="pytest",
                active=True,
            )
        )
        session.add(
            QuestionDedupeCheck(
                user_id=user.id,
                source_bundle_id=seeded.source_bundle_id,
                question_id=seeded.question_id,
                candidate_hash="a" * 64,
                normalized_hash="b" * 64,
                template_family="privacy-proof",
                source_event_id="privacy-proof-event",
                decision="PASS",
                input_summary_json={"source": "privacy-test"},
                decision_json={"accepted": True},
            )
        )
        session.add(
            QuestionTemplateDenylist(
                user_id=user.id,
                template_family="privacy-proof",
                trigger_question_id=seeded.question_id,
                reason="Privacy deletion proof fixture.",
            )
        )
        session.add(
            WeeklyReport(
                user_id=user.id,
                week_start=date(2026, 6, 15),
                week_end=date(2026, 6, 21),
                metrics_json={"completed_session_count": 1},
                summary="Privacy deletion proof weekly report.",
            )
        )
        await RefreshTokenRepository(session).create_token(
            user_id=user.id,
            token_hash="refresh-token-hash",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        session.add(
            AIJob(
                job_type="GRAPH_RESUME",
                payload={
                    "user_id": str(user.id),
                    "session_id": str(seeded.session_id),
                    "attempt_id": str(seeded.attempt_id),
                },
                status="PENDING",
            )
        )
        await _add_user_scoped_model_run(
            session,
            user_id=user.id,
            session_id=seeded.session_id,
            attempt_id=seeded.attempt_id,
        )
        await _add_user_only_prepare_model_run(session, user_id=user.id)
        await _insert_checkpoint_rows(session, seeded.thread_id)
        await session.flush()
        response = await PrivacyService(
            session=session, settings=settings
        ).request_account_deletion(user=user)
        await session.commit()

    expected_proof_hash = hashlib.sha256(f"proof:{response.proof_code}".encode()).hexdigest()
    wrong_proof_hash = hashlib.sha256(b"proof:wrong-proof-code").hexdigest()
    compare_calls: list[tuple[str, str]] = []

    def fake_compare_digest(left: str, right: str) -> bool:
        compare_calls.append((left, right))
        return left == right

    monkeypatch.setattr("app.services.privacy.secrets.compare_digest", fake_compare_digest)

    audio_path = tmp_path / seeded.audio_relative_path
    assert audio_path.exists()

    async with db_maker() as session:
        disabled_user = await session.get(AppUser, seeded.user_id)
        assert disabled_user is not None
        assert disabled_user.status == "DISABLED"
        token = (await session.execute(select(RefreshToken))).scalar_one()
        assert token.revoked_at is not None
        queued_status = await PrivacyService(session=session, settings=settings).deletion_status(
            request_id=response.request_id,
            proof_code=response.proof_code,
        )
        assert queued_status is not None
        assert queued_status.status == "QUEUED"
        assert compare_calls == [(expected_proof_hash, expected_proof_hash)]
        delete_job = (
            await session.execute(select(AIJob).where(AIJob.job_type == DELETE_ACCOUNT_JOB))
        ).scalar_one()
        assert delete_job.payload == {"request_id": str(response.request_id)}

    async with db_maker() as session:
        counts = await PrivacyService(session=session, settings=settings).process_account_deletion(
            request_id=response.request_id,
        )
        await session.commit()

    assert counts["users"] == 1
    assert counts["sessions"] == 1
    assert counts["attempts"] == 1
    assert counts["transcripts"] == 1
    assert counts["transcript_segments"] == 1
    assert counts["transcript_corrections"] == 1
    assert counts["defect_occurrences"] == 1
    assert counts["defect_evidence"] == 1
    assert counts["reports"] == 1
    assert counts["issues"] == 1
    assert counts["appeals"] == 1
    assert counts["duplicate_complaints"] == 1
    assert counts["refresh_tokens"] == 1
    assert counts["training_policies"] == 1
    assert counts["push_subscriptions"] == 1
    assert counts["source_bundles"] == 1
    assert counts["question_sources"] == 1
    assert counts["source_claims"] == 1
    assert counts["questions"] == 1
    assert counts["question_claim_maps"] == 1
    assert counts["question_fingerprints"] == 1
    assert counts["question_rubrics"] == 2
    assert counts["question_dedupe_checks"] == 1
    assert counts["question_template_denylists"] == 1
    assert counts["defect_profiles"] == 1
    assert counts["weekly_reports"] == 1
    assert counts["ai_jobs"] == 3
    assert counts["model_runs"] == 2
    assert counts["checkpoint_rows"] == 3
    assert counts["audio_file_references"] == 1
    assert counts["audio_files"] == 1
    assert not audio_path.exists()

    async with db_maker() as session:
        assert await session.get(AppUser, seeded.user_id) is None
        assert await session.get(TrainingSession, seeded.session_id) is None
        assert await session.get(VoiceAttempt, seeded.attempt_id) is None
        assert await session.get(AttemptTranscript, seeded.transcript_id) is None
        assert await session.get(TranscriptCorrection, seeded.correction_id) is None
        assert await session.get(EvaluationReport, seeded.report_id) is None
        assert await session.get(DefectOccurrence, seeded.occurrence_id) is None
        assert await _row_count(session, DefectEvidence) == 0
        assert await _row_count(session, DefectProfile) == 0
        assert await _row_count(session, Appeal) == 0
        assert await _row_count(session, QuestionDuplicateComplaint) == 0
        assert await session.get(Question, seeded.question_id) is None
        assert await session.get(SourceBundle, seeded.source_bundle_id) is None
        assert await _row_count(session, RefreshToken) == 0
        assert await _row_count(session, UserTrainingPolicy) == 0
        assert await _row_count(session, PushSubscription) == 0
        assert await _row_count(session, WeeklyReport) == 0
        assert await _row_count(session, QuestionSource) == 0
        assert await _row_count(session, SourceClaim) == 0
        assert await _row_count(session, QuestionClaimMap) == 0
        assert await _row_count(session, QuestionFingerprint) == 0
        assert await _row_count(session, QuestionRubric) == 0
        assert await _row_count(session, QuestionDedupeCheck) == 0
        assert await _row_count(session, QuestionTemplateDenylist) == 0
        assert await _row_count(session, ModelRun) == 0
        assert await _checkpoint_row_count(session) == 0
        deletion_request = await session.get(PrivacyDeletionRequest, response.request_id)
        assert deletion_request is not None
        assert deletion_request.status == "SUCCEEDED"
        assert deletion_request.user_id_snapshot is None
        assert deletion_request.counts_json["users"] == 1
        assert deletion_request.counts_json["audio_file_references"] == 1
        assert deletion_request.counts_json["audio_files"] == 1
        user_id_hash = hashlib.sha256(f"user:{seeded.user_id}".encode()).hexdigest()
        assert deletion_request.user_id_hash == user_id_hash
        remaining_job = (await session.execute(select(AIJob))).scalar_one()
        assert remaining_job.job_type == DELETE_ACCOUNT_JOB
        assert remaining_job.payload == {"request_id": str(response.request_id)}

        succeeded_status = await PrivacyService(session=session, settings=settings).deletion_status(
            request_id=response.request_id,
            proof_code=response.proof_code,
        )
        assert succeeded_status is not None
        assert succeeded_status.status == "SUCCEEDED"
        assert succeeded_status.counts["users"] == 1
        assert succeeded_status.counts["ai_jobs"] == 3
        assert succeeded_status.counts["model_runs"] == 2
        assert succeeded_status.counts["transcript_corrections"] == 1
        assert succeeded_status.counts["defect_occurrences"] == 1
        assert succeeded_status.counts["push_subscriptions"] == 1
        assert succeeded_status.counts["question_fingerprints"] == 1
        assert succeeded_status.counts["weekly_reports"] == 1
        assert succeeded_status.counts["appeals"] == 1
        assert succeeded_status.counts["duplicate_complaints"] == 1
        assert succeeded_status.counts["audio_file_references"] == 1
        assert succeeded_status.counts["audio_files"] == 1
        wrong_proof = await PrivacyService(session=session, settings=settings).deletion_status(
            request_id=response.request_id,
            proof_code="wrong-proof-code",
        )
        assert wrong_proof is None
        assert compare_calls == [
            (expected_proof_hash, expected_proof_hash),
            (expected_proof_hash, expected_proof_hash),
            (expected_proof_hash, wrong_proof_hash),
        ]
        audit_events = (
            (
                await session.execute(
                    select(PrivacyAuditEvent).where(
                        PrivacyAuditEvent.request_id == response.request_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_events) == 2
        assert all(event.user_id_snapshot is None for event in audit_events)
        assert all(event.target_id != str(seeded.user_id) for event in audit_events)
        assert {event.target_id for event in audit_events} == {user_id_hash}


async def test_account_deletion_success_cannot_be_downgraded_to_failed(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    async with db_maker() as session:
        user = await _create_user(session, "account-delete-success-sticky")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        response = await PrivacyService(
            session=session, settings=settings
        ).request_account_deletion(user=user)
        await session.commit()

    async with db_maker() as session:
        await PrivacyService(session=session, settings=settings).process_account_deletion(
            request_id=response.request_id,
        )
        await session.commit()

    async with db_maker() as session:
        service = PrivacyService(session=session, settings=settings)
        await service.mark_deletion_failed(
            request_id=response.request_id,
            error_code="JOB_MARK_SUCCEEDED_FAILED",
        )
        await session.commit()

    async with db_maker() as session:
        deletion_request = await session.get(PrivacyDeletionRequest, response.request_id)
        assert deletion_request is not None
        assert deletion_request.status == "SUCCEEDED"
        assert deletion_request.error_code is None
        assert deletion_request.user_id_snapshot is None
        succeeded_status = await PrivacyService(session=session, settings=settings).deletion_status(
            request_id=response.request_id,
            proof_code=response.proof_code,
        )
        assert succeeded_status is not None
        assert succeeded_status.status == "SUCCEEDED"
        events = (
            (
                await session.execute(
                    select(PrivacyAuditEvent).where(
                        PrivacyAuditEvent.request_id == response.request_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(event.status for event in events) == ["QUEUED", "SUCCEEDED"]
        assert await session.get(AppUser, seeded.user_id) is None


async def test_account_deletion_failed_error_code_is_redacted_for_audit(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    async with db_maker() as session:
        user = await _create_user(session, "account-delete-failed-redaction")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        response = await PrivacyService(
            session=session, settings=settings
        ).request_account_deletion(user=user)
        await session.commit()

    refresh_token = "refresh-token-value-that-must-not-persist"
    signed_url = "https://private.example.com/audio.wav?X-Amz-Signature=secret-signature"
    api_key = "sk-delete-secret-value-that-must-not-persist"
    unsafe_error_code = (
        f"delete failed proof={response.proof_code} token={refresh_token} "
        f"audio={seeded.audio_relative_path} url={signed_url} key={api_key}"
    )

    async with db_maker() as session:
        await PrivacyService(session=session, settings=settings).mark_deletion_failed(
            request_id=response.request_id,
            error_code=unsafe_error_code,
        )
        await session.commit()

    async with db_maker() as session:
        deletion_request = await session.get(PrivacyDeletionRequest, response.request_id)
        assert deletion_request is not None
        assert deletion_request.status == "FAILED"
        assert deletion_request.error_code == "DELETION_FAILED"
        audit = await _audit_event(session, "COMPLETE_ACCOUNT_DELETION")
        assert audit is not None
        assert audit.status == "FAILED"
        assert audit.error_code == "DELETION_FAILED"

        persisted_error_material = json.dumps(
            {
                "request_error_code": deletion_request.error_code,
                "audit_error_code": audit.error_code,
                "audit_counts": audit.counts_json,
                "audit_error": audit.error_code,
            },
            ensure_ascii=False,
        )
        for sensitive_value in (
            response.proof_code,
            refresh_token,
            seeded.audio_relative_path,
            signed_url,
            "secret-signature",
            api_key,
        ):
            assert sensitive_value not in persisted_error_material


async def test_account_deletion_continues_when_audio_reference_escapes_root(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    outside_dir = tmp_path.parent / f"{tmp_path.name}-account-outside-audio"
    outside_dir.mkdir()
    outside_file = outside_dir / "escaped.webm"
    outside_file.write_bytes(b"do-not-delete")
    invalid_relative_path = f"../{outside_dir.name}/{outside_file.name}"
    async with db_maker() as session:
        user = await _create_user(session, "account-delete-invalid-audio")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        attempt = await session.get(VoiceAttempt, seeded.attempt_id)
        assert attempt is not None
        attempt.audio_path = invalid_relative_path
        response = await PrivacyService(
            session=session, settings=settings
        ).request_account_deletion(user=user)
        await session.commit()

    original_audio = tmp_path / seeded.audio_relative_path
    original_audio.unlink()

    async with db_maker() as session:
        counts = await PrivacyService(session=session, settings=settings).process_account_deletion(
            request_id=response.request_id,
        )
        await session.commit()

    assert counts["users"] == 1
    assert counts["audio_file_references"] == 1
    assert counts["audio_files"] == 0
    assert counts["audio_file_invalid_references"] == 1
    assert counts["audio_file_non_file_references"] == 0
    assert outside_file.exists()

    async with db_maker() as session:
        assert await session.get(AppUser, seeded.user_id) is None
        assert await session.get(TrainingSession, seeded.session_id) is None
        deletion_request = await session.get(PrivacyDeletionRequest, response.request_id)
        assert deletion_request is not None
        assert deletion_request.status == "SUCCEEDED"
        assert deletion_request.counts_json["audio_file_invalid_references"] == 1

    outside_file.unlink()
    outside_dir.rmdir()


async def test_release_http_report_export_and_training_delete_are_user_scoped(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with db_maker() as session:
        user = await _create_user(session, "api-release-owner")
        other_user = await _create_user(session, "api-release-other")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        other_session = await seed_exposed_training_session(session, user_id=other_user.id)
        session.add(
            PrivacyAuditEvent(
                user_id_snapshot=user.id,
                event_type="EXPORT_TEST_AUDIT",
                target_type="training_session",
                target_id=str(seeded.session_id),
                status="SUCCEEDED",
                counts_json={"sessions": 1},
            )
        )
        await session.commit()

    owner_headers = _auth_headers(seeded.user_id)
    other_headers = _auth_headers(other_user.id)

    report = await client.get(
        f"/api/v1/trainings/{seeded.session_id}/report",
        headers=owner_headers,
    )
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["report_id"] == str(seeded.report_id)
    assert report_payload["issues"][0]["quote"] == "I skipped the decision."
    assert report_payload["source_summary"]["source_count"] == 1

    forbidden_report = await client.get(
        f"/api/v1/trainings/{seeded.session_id}/report",
        headers=other_headers,
    )
    assert forbidden_report.status_code == 404

    exported = await client.get("/api/v1/me/export", headers=owner_headers)
    assert exported.status_code == 200
    export_payload = exported.json()
    export_text = json.dumps(export_payload, ensure_ascii=False, sort_keys=True)
    assert export_payload["sessions"][0]["id"] == str(seeded.session_id)
    assert export_payload["sessions"][0]["sources"][0]["source_bundle_id"] == str(
        seeded.source_bundle_id
    )
    assert export_payload["sessions"][0]["attempts"][0]["corrections"][0]["id"] == str(
        seeded.correction_id
    )
    assert (
        export_payload["sessions"][0]["attempts"][0]["corrections"][0]["corrected_text"]
        == "I skipped the decision today."
    )
    assert export_payload["privacy_audit_events"][0]["event_type"] == "EXPORT_TEST_AUDIT"
    assert str(other_session.id) not in export_text
    assert seeded.audio_relative_path not in export_text
    assert "audio_path" not in export_text
    assert "Signature=" not in export_text

    forbidden_delete = await client.delete(
        f"/api/v1/me/trainings/{seeded.session_id}",
        headers=other_headers,
    )
    assert forbidden_delete.status_code == 404

    deleted = await client.delete(
        f"/api/v1/me/trainings/{seeded.session_id}",
        headers=owner_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["counts"]["sessions"] == 1
    assert deleted.json()["counts"]["audio_file_references"] == 1
    assert deleted.json()["counts"]["audio_files"] == 1

    report_after_delete = await client.get(
        f"/api/v1/trainings/{seeded.session_id}/report",
        headers=owner_headers,
    )
    assert report_after_delete.status_code == 404


async def test_release_http_account_delete_status_does_not_require_bearer(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    async with db_maker() as session:
        user = await _create_user(session, "api-account-delete")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        await session.commit()

    requested = await client.delete("/api/v1/me", headers=_auth_headers(seeded.user_id))
    assert requested.status_code == 200
    request_payload = requested.json()

    queued_status = await client.post(
        "/api/v1/privacy/deletion-status",
        json={
            "request_id": request_payload["request_id"],
            "proof_code": request_payload["proof_code"],
        },
    )
    assert queued_status.status_code == 200
    assert queued_status.json()["status"] == "QUEUED"

    wrong_proof = await client.post(
        "/api/v1/privacy/deletion-status",
        json={
            "request_id": request_payload["request_id"],
            "proof_code": "wrong-proof-code",
        },
    )
    assert wrong_proof.status_code == 404

    async with db_maker() as session:
        counts = await PrivacyService(session=session, settings=settings).process_account_deletion(
            request_id=UUID(request_payload["request_id"]),
        )
        await session.commit()

    assert counts["users"] == 1
    assert counts["sessions"] == 1
    assert counts["audio_file_references"] == 1
    assert counts["audio_files"] == 1

    completed_status = await client.post(
        "/api/v1/privacy/deletion-status",
        json={
            "request_id": request_payload["request_id"],
            "proof_code": request_payload["proof_code"],
        },
    )
    assert completed_status.status_code == 200
    assert completed_status.json()["status"] == "SUCCEEDED"
    assert completed_status.json()["counts"]["users"] == 1
    assert completed_status.json()["counts"]["audio_file_references"] == 1
    assert completed_status.json()["counts"]["audio_files"] == 1

    export_after_delete = await client.get(
        "/api/v1/me/export",
        headers=_auth_headers(seeded.user_id),
    )
    assert export_after_delete.status_code == 401


async def test_release_http_admin_cannot_request_self_account_deletion(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_maker() as session:
        admin = await _create_user(session, "api-delete-admin", role="ADMIN")
        await session.commit()

    response = await client.delete("/api/v1/me", headers=_auth_headers(admin.id, role="ADMIN"))

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "ADMIN_ACCOUNT_DELETE_FORBIDDEN"

    async with db_maker() as session:
        persisted_admin = await session.get(AppUser, admin.id)
        deletion_request_count = await _row_count(session, PrivacyDeletionRequest)
        delete_job_count = (
            await session.execute(
                select(func.count()).select_from(AIJob).where(AIJob.job_type == DELETE_ACCOUNT_JOB)
            )
        ).scalar_one()

    assert persisted_admin is not None
    assert persisted_admin.status == "ACTIVE"
    assert deletion_request_count == 0
    assert delete_job_count == 0


async def test_release_http_admin_appeal_queue_and_review(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with db_maker() as session:
        user = await _create_user(session, "api-appeal-owner")
        admin = await _create_user(session, "api-appeal-admin", role="ADMIN")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        await session.commit()

    user_headers = _auth_headers(seeded.user_id)
    admin_headers = _auth_headers(admin.id, role="ADMIN")

    created = await client.post(
        f"/api/v1/trainings/{seeded.session_id}/appeals",
        headers=user_headers,
        json={
            "type": "transcript",
            "reason": "The transcript segment does not match my audio.",
            "attempt_id": str(seeded.attempt_id),
        },
    )
    assert created.status_code == 201
    appeal_id = created.json()["id"]

    forbidden_queue = await client.get("/api/v1/admin/appeals", headers=user_headers)
    assert forbidden_queue.status_code == 403

    queue = await client.get("/api/v1/admin/appeals", headers=admin_headers)
    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [appeal_id]
    assert queue.json()[0]["user_id"] == str(seeded.user_id)
    assert queue.json()[0]["target"]["attempt_id"] == str(seeded.attempt_id)

    reviewed = await client.post(
        f"/api/v1/admin/appeals/{appeal_id}/review",
        headers=admin_headers,
        json={
            "accepted": True,
            "resolution": "Transcript dispute accepted.",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "REVIEWED_ACCEPTED"
    assert reviewed.json()["reviewed_at"] is not None

    queue_after_review = await client.get("/api/v1/admin/appeals", headers=admin_headers)
    assert queue_after_review.status_code == 200
    assert queue_after_review.json() == []

    async with db_maker() as session:
        report = await session.get(EvaluationReport, seeded.report_id)
        occurrence = await session.get(DefectOccurrence, seeded.occurrence_id)

    assert report is not None
    assert report.status == "INVALID"
    assert report.error_code == "TRANSCRIPT_APPEAL_ACCEPTED"
    assert occurrence is not None
    assert occurrence.status == "EXCLUDED"


async def test_release_http_weekly_reports_and_unified_appeals_are_user_scoped(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    completed_at = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    async with db_maker() as session:
        user = await _create_user(session, "api-weekly-owner")
        other_user = await _create_user(session, "api-weekly-other")
        seeded = await _seed_completed_training(
            session,
            user_id=user.id,
            audio_root=tmp_path,
            completed_at=completed_at,
        )
        await ReportService(session=session).generate_previous_week_for_user(
            user_id=user.id,
            now=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
            timezone_name="Asia/Shanghai",
        )
        session.add(
            QuestionDuplicateComplaint(
                user_id=user.id,
                session_id=seeded.session_id,
                question_id=seeded.question_id,
                duplicate_type="semantic",
                template_family="test-p08",
                reason="This question repeats an earlier answer skeleton.",
                status="ACCEPTED",
            )
        )
        await session.commit()

    owner_headers = _auth_headers(seeded.user_id)
    other_headers = _auth_headers(other_user.id)

    weekly = await client.get("/api/v1/me/weekly-reports", headers=owner_headers)
    assert weekly.status_code == 200
    weekly_payload = weekly.json()
    assert len(weekly_payload) == 1
    assert weekly_payload[0]["week_start"] == "2026-06-15"
    assert weekly_payload[0]["week_end"] == "2026-06-21"
    assert weekly_payload[0]["metrics"]["completed_session_count"] == 1

    other_weekly = await client.get("/api/v1/me/weekly-reports", headers=other_headers)
    assert other_weekly.status_code == 200
    assert other_weekly.json() == []

    ordinary_appeal = await client.post(
        f"/api/v1/trainings/{seeded.session_id}/appeals",
        headers=owner_headers,
        json={
            "type": "evaluation",
            "reason": "The evaluation missed my stated decision.",
            "issue_id": str(seeded.issue_id),
        },
    )
    assert ordinary_appeal.status_code == 201

    appeals = await client.get(
        f"/api/v1/trainings/{seeded.session_id}/appeals",
        headers=owner_headers,
    )
    assert appeals.status_code == 200
    appeal_payload = appeals.json()
    assert {item["type"] for item in appeal_payload} == {"evaluation", "duplicate_question"}
    duplicate_item = next(item for item in appeal_payload if item["type"] == "duplicate_question")
    assert duplicate_item["status"] == "ACCEPTED"
    assert duplicate_item["target"]["duplicate_type"] == "semantic"
    assert duplicate_item["resolution"] == "DUPLICATE_QUESTION_ACCEPTED"

    forbidden_appeals = await client.get(
        f"/api/v1/trainings/{seeded.session_id}/appeals",
        headers=other_headers,
    )
    assert forbidden_appeals.status_code == 404


async def test_personal_export_includes_sources_and_audit_without_private_audio_or_model_data(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = _test_settings(tmp_path)
    async with db_maker() as session:
        user = await _create_user(session, "export-user")
        other_user = await _create_user(session, "export-other")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        other_session = await seed_exposed_training_session(
            session,
            user_id=other_user.id,
        )
        await _add_user_scoped_model_run(
            session,
            user_id=user.id,
            session_id=seeded.session_id,
            attempt_id=seeded.attempt_id,
        )
        session.add(
            PrivacyAuditEvent(
                user_id_snapshot=user.id,
                event_type="EXPORT_TEST_AUDIT",
                target_type="training_session",
                target_id=str(seeded.session_id),
                status="SUCCEEDED",
                counts_json={"sessions": 1},
            )
        )
        await session.commit()

    async with db_maker() as session:
        user = await session.get(AppUser, seeded.user_id)
        assert user is not None
        exported = await PrivacyService(
            session=session,
            settings=settings,
        ).export_personal_data(user=user)

    payload = exported.model_dump(mode="json")
    payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert payload["user"]["nickname"] == "export-user"
    assert [item["id"] for item in payload["sessions"]] == [str(seeded.session_id)]
    assert payload["sessions"][0]["sources"][0]["source_bundle_id"] == str(seeded.source_bundle_id)
    assert payload["sessions"][0]["attempts"][0]["corrections"][0]["id"] == str(
        seeded.correction_id
    )
    exported_source = payload["sessions"][0]["sources"][0]["sources"][0]
    assert exported_source["title"] == "Test official source"
    assert exported_source["claims"][0]["support_status"] == "VERIFIED"
    assert payload["privacy_audit_events"][0]["event_type"] == "EXPORT_TEST_AUDIT"
    assert payload["privacy_audit_events"][0]["target_id"] == str(seeded.session_id)

    assert str(other_session.id) not in payload_text
    assert str(other_user.id) not in payload_text
    assert seeded.audio_relative_path not in payload_text
    assert "fake-audio" not in payload_text
    assert "audio_path" not in payload_text
    assert "Signature=" not in payload_text
    assert "private_training_summary" not in payload_text
    assert "delete me" not in payload_text


async def test_report_weekly_and_source_appeal_invalidation(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    completed_at = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    async with db_maker() as session:
        user = await _create_user(session, "report-source-appeal")
        other_user = await _create_user(session, "report-other")
        seeded = await _seed_completed_training(
            session,
            user_id=user.id,
            audio_root=tmp_path,
            completed_at=completed_at,
        )
        await session.commit()

    async with db_maker() as session:
        report_service = ReportService(session=session)
        report = await report_service.training_report(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )
        weekly = await report_service.generate_previous_week_for_user(
            user_id=seeded.user_id,
            now=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
            timezone_name="Asia/Shanghai",
        )
        weekly_again = await report_service.generate_previous_week_for_user(
            user_id=seeded.user_id,
            now=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
            timezone_name="Asia/Shanghai",
        )
        other_report = await report_service.training_report(
            user_id=other_user.id,
            session_id=seeded.session_id,
        )
        other_weeklies = await report_service.weekly_reports(user_id=other_user.id)
        await session.commit()

    assert report is not None
    assert report.report_id == seeded.report_id
    assert report.source_summary is not None
    assert report.source_summary.source_count == 1
    assert [issue.id for issue in report.issues] == [seeded.issue_id]
    assert weekly.metrics_json["completed_session_count"] == 1
    assert weekly.week_start.isoformat() == "2026-06-15"
    assert weekly.week_end.isoformat() == "2026-06-21"
    assert weekly_again.id == weekly.id
    assert other_report is None
    assert other_weeklies == []

    async with db_maker() as session:
        source = (
            await session.execute(
                select(QuestionSource).where(
                    QuestionSource.source_bundle_id == seeded.source_bundle_id
                )
            )
        ).scalar_one()
        claim = (
            await session.execute(select(SourceClaim).where(SourceClaim.source_id == source.id))
        ).scalar_one()
        service = DefectMemoryService(session=session)
        appeal = await service.create_appeal(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
            appeal_type="source",
            reason="The cited source does not support this question.",
            issue_id=None,
            defect_code=None,
            target_json={"claim_id": str(claim.id)},
        )
        reviewed = await service.review_appeal(
            appeal_id=appeal.id,
            user_id=seeded.user_id,
            accepted=True,
            resolution="Source dispute accepted.",
        )
        await session.commit()

    assert reviewed.status == "REVIEWED_ACCEPTED"

    async with db_maker() as session:
        invalidated = await session.get(EvaluationReport, seeded.report_id)
        occurrence = await session.get(DefectOccurrence, seeded.occurrence_id)
        profile = (
            await session.execute(
                select(DefectProfile).where(
                    DefectProfile.user_id == seeded.user_id,
                    DefectProfile.defect_code == "ALIGN-01",
                )
            )
        ).scalar_one()
        report_after_appeal = await ReportService(session=session).training_report(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )

    assert invalidated is not None
    assert invalidated.status == "INVALID"
    assert invalidated.error_code == "SOURCE_APPEAL_ACCEPTED"
    assert occurrence is not None
    assert occurrence.status == "EXCLUDED"
    assert profile.active_occurrence_count == 0
    assert profile.suspended_occurrence_count == 0
    assert report_after_appeal is None


async def test_report_source_summary_requires_owned_question(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with db_maker() as session:
        user = await _create_user(session, "report-owned-question")
        other_user = await _create_user(session, "report-other-question")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        other_session = await seed_exposed_training_session(session, user_id=other_user.id)
        training_session = await session.get(TrainingSession, seeded.session_id)
        assert training_session is not None
        training_session.question_id = other_session.question_id
        await session.commit()

    async with db_maker() as session:
        report = await ReportService(session=session).training_report(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )

    assert report is not None
    assert report.report_id == seeded.report_id
    assert report.source_summary is None


async def test_source_appeal_rejects_cross_user_question_reference(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with db_maker() as session:
        user = await _create_user(session, "source-appeal-owned-question")
        other_user = await _create_user(session, "source-appeal-other-question")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        other_session = await seed_exposed_training_session(session, user_id=other_user.id)
        assert other_session.question_id is not None
        other_question = await session.get(Question, other_session.question_id)
        assert other_question is not None
        other_source = (
            await session.execute(
                select(QuestionSource).where(
                    QuestionSource.source_bundle_id == other_question.source_bundle_id
                )
            )
        ).scalar_one()
        training_session = await session.get(TrainingSession, seeded.session_id)
        assert training_session is not None
        training_session.question_id = other_session.question_id
        await session.commit()

    async with db_maker() as session:
        with pytest.raises(DefectMemoryError) as exc_info:
            await DefectMemoryService(session=session).create_appeal(
                user_id=seeded.user_id,
                session_id=seeded.session_id,
                appeal_type="source",
                reason="This should not validate another user's source.",
                issue_id=None,
                defect_code=None,
                target_json={"source_id": str(other_source.id)},
            )
        await session.commit()

    assert exc_info.value.code == "DEFECT_APPEAL_TARGET_NOT_FOUND"

    async with db_maker() as session:
        assert await _row_count(session, Appeal) == 0


async def test_transcript_appeal_acceptance_invalidates_report_and_admin_queue(
    db_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with db_maker() as session:
        user = await _create_user(session, "transcript-appeal")
        seeded = await _seed_completed_training(session, user_id=user.id, audio_root=tmp_path)
        service = DefectMemoryService(session=session)
        appeal = await service.create_appeal(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
            appeal_type="transcript",
            reason="The transcript segment does not match my audio.",
            issue_id=None,
            defect_code=None,
            target_json={
                "attempt_id": str(seeded.attempt_id),
                "segment_id": str(seeded.segment_id),
            },
        )
        open_appeals = await service.list_admin_appeals(limit=10)
        reviewed = await service.review_appeal(
            appeal_id=appeal.id,
            user_id=seeded.user_id,
            accepted=True,
            resolution="Transcript dispute accepted.",
        )
        reviewed_appeals = await service.list_admin_appeals(limit=10)
        await session.commit()

    assert [item.id for item in open_appeals] == [appeal.id]
    assert reviewed.status == "REVIEWED_ACCEPTED"
    assert reviewed_appeals == []

    async with db_maker() as session:
        invalidated = await session.get(EvaluationReport, seeded.report_id)
        occurrence = await session.get(DefectOccurrence, seeded.occurrence_id)
        report_after_appeal = await ReportService(session=session).training_report(
            user_id=seeded.user_id,
            session_id=seeded.session_id,
        )

    assert invalidated is not None
    assert invalidated.status == "INVALID"
    assert invalidated.error_code == "TRANSCRIPT_APPEAL_ACCEPTED"
    assert occurrence is not None
    assert occurrence.status == "EXCLUDED"
    assert report_after_appeal is None


async def _create_user(session: AsyncSession, nickname: str, role: str = "USER") -> AppUser:
    user = AppUser(
        nickname=nickname,
        password_hash="fake-password-hash",
        role=role,
        status="ACTIVE",
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_completed_training(
    session: AsyncSession,
    *,
    user_id: UUID,
    audio_root: Path,
    completed_at: datetime | None = None,
) -> SeededTraining:
    now = completed_at or datetime.now(UTC)
    training_session = await seed_exposed_training_session(session, user_id=user_id)
    training_session.stage = "COMPLETED"
    training_session.completed_at = now
    question_id = training_session.question_id
    assert question_id is not None
    question = await session.get(Question, question_id)
    assert question is not None
    session.add(
        QuestionRubric(
            training_session_id=training_session.id,
            question_id=None,
            version="session-rubric",
            dimensions_json={"logic": 70, "adaptability": 30},
            expected_elements_json=["结论", "追问应变"],
            fatal_omissions_json=["没有回答追问"],
            content_hash="session-rubric-" + training_session.id.hex,
        )
    )
    await session.flush()

    audio_relative_path = f"{user_id}/{training_session.id}/{uuid4()}.webm"
    audio_path = audio_root / audio_relative_path
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"fake-audio")

    attempt = VoiceAttempt(
        session_id=training_session.id,
        stage="FIRST",
        round=1,
        audio_path=audio_relative_path,
        mime_type="audio/webm",
        duration_ms=1200,
        size_bytes=10,
        checksum_sha256="0" * 64,
        upload_status="UPLOADED",
        uploaded_at=now,
        retention_at=now + timedelta(days=30),
    )
    session.add(attempt)
    await session.flush()

    transcript = AttemptTranscript(
        attempt_id=attempt.id,
        status="SUCCEEDED",
        raw_text="I skipped the decision.",
        corrected_text="I skipped the decision.",
        language="zh",
        metrics_json={"speech_rate_cpm": 160},
        completed_at=now,
    )
    session.add(transcript)
    segment = TranscriptSegment(
        attempt_id=attempt.id,
        segment_index=0,
        start_ms=0,
        end_ms=1200,
        raw_text="I skipped the decision.",
        corrected_text="I skipped the decision.",
        words_json=[],
    )
    session.add(segment)
    await session.flush()
    correction = TranscriptCorrection(
        attempt_id=attempt.id,
        segment_id=segment.id,
        user_id=user_id,
        raw_text="I skipped the decision.",
        previous_corrected_text="I skipped the decision.",
        corrected_text="I skipped the decision today.",
        reason="STT missed one word.",
    )
    session.add(correction)
    await session.flush()

    report = EvaluationReport(
        session_id=training_session.id,
        status="COMPLETED",
        details_json={"rubric_version": "test"},
        logic_score=55,
        speech_score=80,
        adaptability_score=70,
        final_score=55,
        completed_at=now,
    )
    session.add(report)
    await session.flush()
    issue = EvaluationIssue(
        report_id=report.id,
        attempt_id=attempt.id,
        transcript_segment_id=segment.id,
        category="logic",
        code="ALIGN-01",
        severity=4,
        confidence="high",
        quote="I skipped the decision.",
        start_ms=0,
        end_ms=1200,
        explanation="The answer did not state the core decision.",
        missing_information=["decision"],
        correction_rule="State the decision before supporting evidence.",
        verification_json={"evidence_valid": True},
    )
    session.add(issue)
    session.add(
        DefectDefinition(
            code="ALIGN-01",
            name="Alignment gap",
            description="Answer misses the core decision.",
            detection_rule="Evidence-backed evaluation issue.",
            score_cap=70,
        )
    )
    await session.flush()
    occurrence = DefectOccurrence(
        user_id=user_id,
        session_id=training_session.id,
        issue_id=issue.id,
        defect_code="ALIGN-01",
        source_issue_code=issue.code,
        category=issue.category,
        scenario_key="test-scenario",
        attempt_stage=attempt.stage,
        severity=issue.severity,
        confidence=issue.confidence,
        status="ACTIVE",
        confirmed=False,
    )
    session.add(occurrence)
    await session.flush()
    session.add(
        DefectEvidence(
            occurrence_id=occurrence.id,
            issue_id=issue.id,
            attempt_id=attempt.id,
            transcript_segment_id=segment.id,
            quote=issue.quote,
            start_ms=issue.start_ms,
            end_ms=issue.end_ms,
            explanation=issue.explanation,
            missing_information=issue.missing_information,
            correction_rule=issue.correction_rule,
            verification_json=issue.verification_json,
        )
    )
    session.add(
        DefectProfile(
            user_id=user_id,
            defect_code="ALIGN-01",
            state="observed",
            severity=4,
            frequency=1,
            recurrence=1,
            priority=10,
            confidence=90,
            active_occurrence_count=1,
            scenario_count=1,
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    await session.flush()
    return SeededTraining(
        user_id=user_id,
        session_id=training_session.id,
        thread_id=training_session.thread_id,
        question_id=question_id,
        source_bundle_id=question.source_bundle_id,
        attempt_id=attempt.id,
        transcript_id=transcript.id,
        segment_id=segment.id,
        correction_id=correction.id,
        report_id=report.id,
        issue_id=issue.id,
        occurrence_id=occurrence.id,
        audio_relative_path=audio_relative_path,
    )


async def _insert_checkpoint_rows(session: AsyncSession, thread_id: str) -> None:
    for table_name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        await session.execute(text(f"CREATE TABLE {table_name} (thread_id text NOT NULL)"))
        await session.execute(
            text(f"INSERT INTO {table_name} (thread_id) VALUES (:thread_id)"),
            {"thread_id": thread_id},
        )


async def _add_user_scoped_model_run(
    session: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID,
    attempt_id: UUID,
) -> None:
    job = AIJob(
        job_type="PREPARE_QUESTIONS",
        payload={
            "user_id": str(user_id),
            "session_id": str(session_id),
            "attempt_id": str(attempt_id),
        },
        status="PENDING",
    )
    session.add(job)
    await session.flush()
    session.add(
        ModelRun(
            job_id=job.id,
            report_id=None,
            prompt_name="question_generation",
            prompt_version="test",
            provider="mock",
            model="mock-question",
            request_id="mock-request",
            latency_ms=1,
            input_tokens=None,
            output_tokens=None,
            input_characters=42,
            output_characters=7,
            structured_ok=True,
            error_code=None,
            input_summary_json={"session_id": str(session_id)},
            output_json={"private_training_summary": "delete me"},
        )
    )
    await session.flush()


async def _add_user_only_prepare_model_run(session: AsyncSession, *, user_id: UUID) -> None:
    job = AIJob(
        job_type="PREPARE_QUESTIONS",
        payload={"user_id": str(user_id)},
        status="PENDING",
    )
    session.add(job)
    await session.flush()
    session.add(
        ModelRun(
            job_id=job.id,
            report_id=None,
            prompt_name="question_generation",
            prompt_version="test",
            provider="mock",
            model="mock-question",
            request_id="mock-user-only-request",
            latency_ms=1,
            input_tokens=None,
            output_tokens=None,
            input_characters=24,
            output_characters=5,
            structured_ok=True,
            error_code=None,
            input_summary_json={"user_id": str(user_id)},
            output_json={"private_user_summary": "delete me"},
        )
    )
    await session.flush()


async def _checkpoint_row_count(session: AsyncSession) -> int:
    total = 0
    for table_name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        total += int(
            (await session.execute(text(f"SELECT count(*) FROM {table_name}"))).scalar_one()
        )
    return total


async def _row_count(session: AsyncSession, model: type[object]) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _audit_event(session: AsyncSession, event_type: str) -> PrivacyAuditEvent | None:
    result = await session.execute(
        select(PrivacyAuditEvent).where(PrivacyAuditEvent.event_type == event_type)
    )
    return result.scalar_one_or_none()


def _auth_headers(user_id: UUID, role: str = "USER") -> dict[str, str]:
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
    )
    return {"Authorization": f"Bearer {create_access_token(user_id, role, settings)}"}


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        audio_root=tmp_path,
        audio_retention_days=30,
        tz="Asia/Shanghai",
    )


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
