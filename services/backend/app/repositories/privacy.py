from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AIJob,
    Appeal,
    AppUser,
    AttemptTranscript,
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


@dataclass(frozen=True)
class TrainingDeletionTarget:
    training_session: TrainingSession
    attempts: list[VoiceAttempt]
    transcript_count: int
    segment_count: int
    correction_count: int
    defect_occurrence_count: int
    defect_evidence_count: int
    question_rubric_count: int
    report_count: int
    issue_count: int
    appeal_count: int
    duplicate_complaint_count: int


@dataclass(frozen=True)
class AccountDeletionTarget:
    user: AppUser | None
    sessions: list[TrainingSession]
    attempts: list[VoiceAttempt]
    audio_paths: list[str]


class PrivacyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_training_deletion_target(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> TrainingDeletionTarget | None:
        result = await self._session.execute(
            select(TrainingSession).where(
                TrainingSession.id == session_id,
                TrainingSession.user_id == user_id,
            )
        )
        training_session = result.scalar_one_or_none()
        if training_session is None:
            return None
        attempts = await self._attempts_for_sessions([training_session.id])
        attempt_ids = [attempt.id for attempt in attempts]
        return TrainingDeletionTarget(
            training_session=training_session,
            attempts=attempts,
            transcript_count=await self._attempt_transcript_count(attempt_ids),
            segment_count=await self._segment_count(attempt_ids),
            correction_count=await self._correction_count(attempt_ids),
            defect_occurrence_count=await self._defect_occurrence_count([training_session.id]),
            defect_evidence_count=await self._defect_evidence_count([training_session.id]),
            question_rubric_count=await self._question_rubric_count_for_training(
                session_id=training_session.id,
                question_id=training_session.question_id,
            ),
            report_count=await self._report_count([training_session.id]),
            issue_count=await self._issue_count([training_session.id]),
            appeal_count=await self._appeal_count([training_session.id]),
            duplicate_complaint_count=await self._duplicate_complaint_count([training_session.id]),
        )

    async def collect_account_deletion_target(self, *, user_id: UUID) -> AccountDeletionTarget:
        user = await self._session.get(AppUser, user_id)
        sessions = await self._sessions_for_user(user_id)
        session_ids = [training_session.id for training_session in sessions]
        attempts = await self._attempts_for_sessions(session_ids)
        audio_paths = [attempt.audio_path for attempt in attempts if attempt.audio_path is not None]
        return AccountDeletionTarget(
            user=user,
            sessions=sessions,
            attempts=attempts,
            audio_paths=audio_paths,
        )

    async def delete_training_target(self, target: TrainingDeletionTarget) -> dict[str, int]:
        training_session = target.training_session
        question_id = training_session.question_id
        thread_id = training_session.thread_id
        attempt_ids = [attempt.id for attempt in target.attempts]
        ai_job_count, model_run_count = await self.delete_ai_jobs_for_training(
            session_id=training_session.id,
            attempt_ids=attempt_ids,
        )
        checkpoint_count = await self.delete_checkpoints([thread_id])
        await self._session.delete(training_session)
        await self._session.flush()
        orphan_question_counts = await self._delete_orphan_question(question_id)
        return {
            "sessions": 1,
            "attempts": len(target.attempts),
            "transcripts": target.transcript_count,
            "transcript_segments": target.segment_count,
            "transcript_corrections": target.correction_count,
            "defect_occurrences": target.defect_occurrence_count,
            "defect_evidence": target.defect_evidence_count,
            "reports": target.report_count,
            "issues": target.issue_count,
            "appeals": target.appeal_count,
            "duplicate_complaints": target.duplicate_complaint_count,
            "ai_jobs": ai_job_count,
            "model_runs": model_run_count,
            "checkpoint_rows": checkpoint_count,
            "question_rubrics": target.question_rubric_count,
            **orphan_question_counts,
        }

    async def delete_account_target(self, target: AccountDeletionTarget) -> dict[str, int]:
        session_ids = [training_session.id for training_session in target.sessions]
        attempt_ids = [attempt.id for attempt in target.attempts]
        thread_ids = [training_session.thread_id for training_session in target.sessions]
        transcript_count = await self._attempt_transcript_count(attempt_ids)
        segment_count = await self._segment_count(attempt_ids)
        correction_count = await self._correction_count(attempt_ids)
        defect_occurrence_count = await self._defect_occurrence_count(session_ids)
        defect_evidence_count = await self._defect_evidence_count(session_ids)
        report_count = await self._report_count(session_ids)
        issue_count = await self._issue_count(session_ids)
        appeal_count = await self._appeal_count(session_ids)
        duplicate_complaint_count = await self._duplicate_complaint_count(session_ids)
        user_scoped_counts = (
            await self._account_user_scoped_counts(target.user.id)
            if target.user is not None
            else {}
        )
        ai_job_count, model_run_count = await self.delete_ai_jobs_for_user_scope(
            user_id=target.user.id if target.user is not None else None,
            session_ids=session_ids,
            attempt_ids=attempt_ids,
        )
        checkpoint_count = await self.delete_checkpoints(thread_ids)
        user_count = 0
        if target.user is not None:
            await self._session.delete(target.user)
            user_count = 1
        await self._session.flush()
        return {
            "users": user_count,
            "sessions": len(target.sessions),
            "attempts": len(target.attempts),
            "audio_file_references": len(target.audio_paths),
            "transcripts": transcript_count,
            "transcript_segments": segment_count,
            "transcript_corrections": correction_count,
            "defect_occurrences": defect_occurrence_count,
            "defect_evidence": defect_evidence_count,
            "reports": report_count,
            "issues": issue_count,
            "appeals": appeal_count,
            "duplicate_complaints": duplicate_complaint_count,
            "ai_jobs": ai_job_count,
            "model_runs": model_run_count,
            "checkpoint_rows": checkpoint_count,
            **user_scoped_counts,
        }

    async def create_deletion_request(
        self,
        *,
        user_id: UUID,
        user_id_hash: str,
        proof_hash: str,
    ) -> PrivacyDeletionRequest:
        request = PrivacyDeletionRequest(
            user_id_snapshot=user_id,
            user_id_hash=user_id_hash,
            proof_hash=proof_hash,
            status="QUEUED",
            counts_json={},
        )
        self._session.add(request)
        await self._session.flush()
        return request

    async def get_deletion_request(self, request_id: UUID) -> PrivacyDeletionRequest | None:
        result = await self._session.execute(
            select(PrivacyDeletionRequest).where(PrivacyDeletionRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def mark_request_running(self, request: PrivacyDeletionRequest) -> None:
        request.status = "RUNNING"
        request.error_code = None
        request.started_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_request_succeeded(
        self,
        request: PrivacyDeletionRequest,
        counts: Mapping[str, object],
    ) -> None:
        request.status = "SUCCEEDED"
        request.counts_json = dict(counts)
        request.error_code = None
        request.completed_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_request_failed(
        self,
        request: PrivacyDeletionRequest,
        error_code: str,
    ) -> None:
        request.status = "FAILED"
        request.error_code = error_code
        request.completed_at = datetime.now(UTC)
        await self._session.flush()

    async def create_audit_event(
        self,
        *,
        user_id_snapshot: UUID | None,
        event_type: str,
        target_type: str,
        target_id: str | None,
        request_id: UUID | None,
        status: str,
        counts: Mapping[str, object] | None = None,
        error_code: str | None = None,
    ) -> PrivacyAuditEvent:
        event = PrivacyAuditEvent(
            user_id_snapshot=user_id_snapshot,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            status=status,
            counts_json=dict(counts or {}),
            error_code=error_code,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def anonymize_completed_deletion_request(
        self,
        request: PrivacyDeletionRequest,
    ) -> None:
        raw_user_id = request.user_id_snapshot
        request.user_id_snapshot = None
        audit_result = await self._session.execute(
            select(PrivacyAuditEvent).where(PrivacyAuditEvent.request_id == request.id)
        )
        for event in audit_result.scalars().all():
            event.user_id_snapshot = None
            if raw_user_id is not None and event.target_id == str(raw_user_id):
                event.target_id = request.user_id_hash
        await self._session.flush()

    async def delete_checkpoints(self, thread_ids: list[str]) -> int:
        if not thread_ids or not await self._checkpoint_table_exists():
            return 0
        deleted = 0
        for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            for thread_id in thread_ids:
                result = await self._session.execute(
                    text(f"DELETE FROM {table_name} WHERE thread_id = :thread_id"),
                    {"thread_id": thread_id},
                )
                deleted += cast(CursorResult[Any], result).rowcount or 0
        return deleted

    async def delete_ai_jobs_for_training(
        self,
        *,
        session_id: UUID,
        attempt_ids: list[UUID],
    ) -> tuple[int, int]:
        conditions = [AIJob.payload["session_id"].as_string() == str(session_id)]
        if attempt_ids:
            conditions.append(
                AIJob.payload["attempt_id"].as_string().in_([str(item) for item in attempt_ids])
            )
        return await self._delete_ai_jobs_and_model_runs(conditions)

    async def delete_ai_jobs_for_user_scope(
        self,
        *,
        user_id: UUID | None,
        session_ids: list[UUID],
        attempt_ids: list[UUID],
    ) -> tuple[int, int]:
        conditions = []
        if user_id is not None:
            conditions.append(AIJob.payload["user_id"].as_string() == str(user_id))
        if session_ids:
            conditions.append(
                AIJob.payload["session_id"].as_string().in_([str(item) for item in session_ids])
            )
        if attempt_ids:
            conditions.append(
                AIJob.payload["attempt_id"].as_string().in_([str(item) for item in attempt_ids])
            )
        if not conditions:
            return 0, 0
        return await self._delete_ai_jobs_and_model_runs(conditions)

    async def _delete_ai_jobs_and_model_runs(self, conditions: list[Any]) -> tuple[int, int]:
        result = await self._session.execute(select(AIJob.id).where(or_(*conditions)))
        job_ids = list(result.scalars().all())
        if not job_ids:
            return 0, 0
        model_run_result = await self._session.execute(
            delete(ModelRun).where(ModelRun.job_id.in_(job_ids))
        )
        ai_job_result = await self._session.execute(delete(AIJob).where(AIJob.id.in_(job_ids)))
        return (
            cast(CursorResult[Any], ai_job_result).rowcount or 0,
            cast(CursorResult[Any], model_run_result).rowcount or 0,
        )

    async def _delete_orphan_question(self, question_id: UUID | None) -> dict[str, int]:
        empty_counts = {
            "questions": 0,
            "question_claim_maps": 0,
            "question_fingerprints": 0,
            "source_bundles": 0,
            "question_sources": 0,
            "source_claims": 0,
        }
        if question_id is None:
            return empty_counts
        reference_count = await self._question_reference_count(question_id)
        if reference_count > 0:
            return empty_counts
        question = await self._session.get(Question, question_id)
        if question is None:
            return empty_counts
        source_bundle_id = question.source_bundle_id
        counts = {
            **empty_counts,
            "questions": 1,
            "question_claim_maps": await self._question_claim_map_count(question_id),
            "question_fingerprints": await self._question_fingerprint_count(question_id),
            "question_sources": await self._question_source_count(source_bundle_id),
            "source_claims": await self._source_claim_count(source_bundle_id),
        }
        await self._session.delete(question)
        await self._session.flush()
        bundle_reference_count = await self._source_bundle_question_count(source_bundle_id)
        if bundle_reference_count == 0:
            source_bundle = await self._session.get(SourceBundle, source_bundle_id)
            if source_bundle is not None:
                await self._session.delete(source_bundle)
                counts["source_bundles"] = 1
        await self._session.flush()
        return counts

    async def _sessions_for_user(self, user_id: UUID) -> list[TrainingSession]:
        result = await self._session.execute(
            select(TrainingSession)
            .where(TrainingSession.user_id == user_id)
            .order_by(TrainingSession.created_at)
        )
        return list(result.scalars().all())

    async def _attempts_for_sessions(self, session_ids: list[UUID]) -> list[VoiceAttempt]:
        if not session_ids:
            return []
        result = await self._session.execute(
            select(VoiceAttempt)
            .where(VoiceAttempt.session_id.in_(session_ids))
            .order_by(VoiceAttempt.created_at)
        )
        return list(result.scalars().all())

    async def _attempt_transcript_count(self, attempt_ids: list[UUID]) -> int:
        if not attempt_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(AttemptTranscript)
            .where(AttemptTranscript.attempt_id.in_(attempt_ids))
        )
        return int(result.scalar_one())

    async def _segment_count(self, attempt_ids: list[UUID]) -> int:
        if not attempt_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.attempt_id.in_(attempt_ids))
        )
        return int(result.scalar_one())

    async def _correction_count(self, attempt_ids: list[UUID]) -> int:
        if not attempt_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(TranscriptCorrection)
            .where(TranscriptCorrection.attempt_id.in_(attempt_ids))
        )
        return int(result.scalar_one())

    async def _defect_occurrence_count(self, session_ids: list[UUID]) -> int:
        if not session_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(DefectOccurrence)
            .where(DefectOccurrence.session_id.in_(session_ids))
        )
        return int(result.scalar_one())

    async def _defect_evidence_count(self, session_ids: list[UUID]) -> int:
        if not session_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(DefectEvidence)
            .join(DefectOccurrence, DefectOccurrence.id == DefectEvidence.occurrence_id)
            .where(DefectOccurrence.session_id.in_(session_ids))
        )
        return int(result.scalar_one())

    async def _account_user_scoped_counts(self, user_id: UUID) -> dict[str, int]:
        return {
            "refresh_tokens": await self._user_row_count(RefreshToken, user_id),
            "training_policies": await self._user_row_count(UserTrainingPolicy, user_id),
            "push_subscriptions": await self._user_row_count(PushSubscription, user_id),
            "source_bundles": await self._user_row_count(SourceBundle, user_id),
            "question_sources": await self._question_source_count_for_user(user_id),
            "source_claims": await self._source_claim_count_for_user(user_id),
            "questions": await self._user_row_count(Question, user_id),
            "question_claim_maps": await self._question_claim_map_count_for_user(user_id),
            "question_fingerprints": await self._question_fingerprint_count_for_user(user_id),
            "question_rubrics": await self._question_rubric_count_for_user(user_id),
            "question_dedupe_checks": await self._user_row_count(QuestionDedupeCheck, user_id),
            "question_template_denylists": await self._user_row_count(
                QuestionTemplateDenylist,
                user_id,
            ),
            "defect_profiles": await self._user_row_count(DefectProfile, user_id),
            "weekly_reports": await self._user_row_count(WeeklyReport, user_id),
        }

    async def _user_row_count(self, model: Any, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
        return int(result.scalar_one())

    async def _question_source_count_for_user(self, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(QuestionSource)
            .join(SourceBundle, SourceBundle.id == QuestionSource.source_bundle_id)
            .where(SourceBundle.user_id == user_id)
        )
        return int(result.scalar_one())

    async def _source_claim_count_for_user(self, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(SourceClaim)
            .join(QuestionSource, QuestionSource.id == SourceClaim.source_id)
            .join(SourceBundle, SourceBundle.id == QuestionSource.source_bundle_id)
            .where(SourceBundle.user_id == user_id)
        )
        return int(result.scalar_one())

    async def _question_claim_map_count_for_user(self, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(QuestionClaimMap)
            .join(Question, Question.id == QuestionClaimMap.question_id)
            .where(Question.user_id == user_id)
        )
        return int(result.scalar_one())

    async def _question_fingerprint_count_for_user(self, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(QuestionFingerprint)
            .join(Question, Question.id == QuestionFingerprint.question_id)
            .where(Question.user_id == user_id)
        )
        return int(result.scalar_one())

    async def _question_rubric_count_for_user(self, user_id: UUID) -> int:
        user_question_ids = select(Question.id).where(Question.user_id == user_id)
        user_session_ids = select(TrainingSession.id).where(TrainingSession.user_id == user_id)
        result = await self._session.execute(
            select(func.count(func.distinct(QuestionRubric.id)))
            .select_from(QuestionRubric)
            .where(
                or_(
                    QuestionRubric.question_id.in_(user_question_ids),
                    QuestionRubric.training_session_id.in_(user_session_ids),
                )
            )
        )
        return int(result.scalar_one())

    async def _question_rubric_count_for_training(
        self,
        *,
        session_id: UUID,
        question_id: UUID | None,
    ) -> int:
        conditions = [QuestionRubric.training_session_id == session_id]
        if question_id is not None and await self._question_reference_count(question_id) <= 1:
            conditions.append(QuestionRubric.question_id == question_id)
        result = await self._session.execute(
            select(func.count(func.distinct(QuestionRubric.id))).where(or_(*conditions))
        )
        return int(result.scalar_one())

    async def _question_claim_map_count(self, question_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(QuestionClaimMap)
            .where(QuestionClaimMap.question_id == question_id)
        )
        return int(result.scalar_one())

    async def _question_fingerprint_count(self, question_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(QuestionFingerprint)
            .where(QuestionFingerprint.question_id == question_id)
        )
        return int(result.scalar_one())

    async def _question_source_count(self, source_bundle_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(QuestionSource)
            .where(QuestionSource.source_bundle_id == source_bundle_id)
        )
        return int(result.scalar_one())

    async def _source_claim_count(self, source_bundle_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(SourceClaim)
            .join(QuestionSource, QuestionSource.id == SourceClaim.source_id)
            .where(QuestionSource.source_bundle_id == source_bundle_id)
        )
        return int(result.scalar_one())

    async def _report_count(self, session_ids: list[UUID]) -> int:
        if not session_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(EvaluationReport)
            .where(EvaluationReport.session_id.in_(session_ids))
        )
        return int(result.scalar_one())

    async def _issue_count(self, session_ids: list[UUID]) -> int:
        if not session_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(EvaluationIssue)
            .join(EvaluationReport, EvaluationReport.id == EvaluationIssue.report_id)
            .where(EvaluationReport.session_id.in_(session_ids))
        )
        return int(result.scalar_one())

    async def _appeal_count(self, session_ids: list[UUID]) -> int:
        if not session_ids:
            return 0
        result = await self._session.execute(
            select(func.count()).select_from(Appeal).where(Appeal.session_id.in_(session_ids))
        )
        return int(result.scalar_one())

    async def _duplicate_complaint_count(self, session_ids: list[UUID]) -> int:
        if not session_ids:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(QuestionDuplicateComplaint)
            .where(QuestionDuplicateComplaint.session_id.in_(session_ids))
        )
        return int(result.scalar_one())

    async def _question_reference_count(self, question_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(TrainingSession)
            .where(TrainingSession.question_id == question_id)
        )
        return int(result.scalar_one())

    async def _source_bundle_question_count(self, source_bundle_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Question)
            .where(Question.source_bundle_id == source_bundle_id)
        )
        return int(result.scalar_one())

    async def _checkpoint_table_exists(self) -> bool:
        result = await self._session.execute(text("SELECT to_regclass('public.checkpoints')"))
        return result.scalar_one() is not None
