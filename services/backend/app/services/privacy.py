from __future__ import annotations

import hashlib
import re
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    Appeal,
    AppUser,
    AttemptTranscript,
    DefectProfile,
    EvaluationIssue,
    EvaluationReport,
    PrivacyAuditEvent,
    Question,
    QuestionDuplicateComplaint,
    QuestionSource,
    SourceBundle,
    SourceClaim,
    TrainingSession,
    TranscriptCorrection,
    TranscriptSegment,
    UserTrainingPolicy,
    VoiceAttempt,
    WeeklyReport,
)
from app.repositories.auth import RefreshTokenRepository
from app.repositories.jobs import AIJobRepository
from app.repositories.privacy import PrivacyRepository
from app.schemas.privacy import (
    AccountDeletionResponse,
    DeletionStatusResponse,
    PersonalDataExportResponse,
    TrainingDeletionResponse,
)
from app.services.audio_storage import AudioStorageError, resolve_stored_audio_path

_SAFE_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class PrivacyError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PrivacyService:
    def __init__(self, *, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._repository = PrivacyRepository(session)

    async def export_personal_data(self, *, user: AppUser) -> PersonalDataExportResponse:
        policy = await self._policy(user.id)
        sessions = await self._sessions_export(user.id)
        return PersonalDataExportResponse(
            generated_at=datetime.now(UTC),
            user=_json_dict(
                {
                    "id": user.id,
                    "nickname": user.nickname,
                    "role": user.role,
                    "status": user.status,
                    "created_at": user.created_at,
                }
            ),
            training_policy=(_json_dict(_policy_export(policy)) if policy is not None else None),
            sessions=sessions,
            defect_profiles=await self._defect_profiles_export(user.id),
            weekly_reports=await self._weekly_reports_export(user.id),
            appeals=await self._appeals_export(user.id),
            duplicate_complaints=await self._duplicate_complaints_export(user.id),
            privacy_audit_events=await self._privacy_audit_events_export(user.id),
        )

    async def delete_training(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> TrainingDeletionResponse:
        target = await self._repository.get_training_deletion_target(
            user_id=user_id,
            session_id=session_id,
        )
        if target is None:
            raise PrivacyError("TRAINING_NOT_FOUND")
        audio_paths = [
            attempt.audio_path for attempt in target.attempts if attempt.audio_path is not None
        ]
        audio_deletion = _delete_audio_files(
            self._settings.audio_root_resolved,
            audio_paths,
        )
        counts = await self._repository.delete_training_target(target)
        counts["audio_file_references"] = len(audio_paths)
        _record_audio_deletion_counts(counts, audio_deletion)
        await self._repository.create_audit_event(
            user_id_snapshot=user_id,
            event_type="DELETE_TRAINING",
            target_type="training_session",
            target_id=str(session_id),
            request_id=None,
            status="SUCCEEDED",
            counts=counts,
        )
        return TrainingDeletionResponse(session_id=session_id, deleted=True, counts=counts)

    async def request_account_deletion(self, *, user: AppUser) -> AccountDeletionResponse:
        if user.role != "USER":
            raise PrivacyError("ADMIN_ACCOUNT_DELETE_FORBIDDEN")
        proof_code = secrets.token_urlsafe(24)
        request = await self._repository.create_deletion_request(
            user_id=user.id,
            user_id_hash=_hash(f"user:{user.id}"),
            proof_hash=_hash(f"proof:{proof_code}"),
        )
        user.status = "DISABLED"
        await RefreshTokenRepository(self._session).revoke_all_for_user(user.id, datetime.now(UTC))
        await AIJobRepository(self._session).enqueue_delete_account(request_id=request.id)
        await self._repository.create_audit_event(
            user_id_snapshot=user.id,
            event_type="REQUEST_ACCOUNT_DELETION",
            target_type="app_user",
            target_id=str(user.id),
            request_id=request.id,
            status="QUEUED",
        )
        return AccountDeletionResponse(
            request_id=request.id,
            proof_code=proof_code,
            status="QUEUED",
        )

    async def deletion_status(
        self,
        *,
        request_id: UUID,
        proof_code: str,
    ) -> DeletionStatusResponse | None:
        request = await self._repository.get_deletion_request(request_id)
        expected_hash = _hash(f"proof:{proof_code}")
        if request is None or not secrets.compare_digest(request.proof_hash, expected_hash):
            return None
        return DeletionStatusResponse(
            request_id=request.id,
            status=request.status,
            counts=request.counts_json,
            error_code=request.error_code,
            requested_at=request.requested_at,
            started_at=request.started_at,
            completed_at=request.completed_at,
        )

    async def process_account_deletion(self, *, request_id: UUID) -> dict[str, int]:
        request = await self._repository.get_deletion_request(request_id)
        if request is None:
            raise PrivacyError("DELETION_REQUEST_NOT_FOUND")
        if request.status == "SUCCEEDED":
            return {
                key: int(value)
                for key, value in request.counts_json.items()
                if isinstance(value, int)
            }
        user_id_snapshot = request.user_id_snapshot
        if user_id_snapshot is None:
            raise PrivacyError("DELETION_REQUEST_ANONYMIZED")
        await self._repository.mark_request_running(request)
        target = await self._repository.collect_account_deletion_target(
            user_id=user_id_snapshot,
        )
        audio_deletion = _delete_audio_files(self._settings.audio_root_resolved, target.audio_paths)
        counts = await self._repository.delete_account_target(target)
        counts["audio_file_references"] = len(target.audio_paths)
        _record_audio_deletion_counts(counts, audio_deletion)
        await self._repository.mark_request_succeeded(request, counts)
        await self._repository.create_audit_event(
            user_id_snapshot=None,
            event_type="COMPLETE_ACCOUNT_DELETION",
            target_type="app_user",
            target_id=request.user_id_hash,
            request_id=request.id,
            status="SUCCEEDED",
            counts=counts,
        )
        await self._repository.anonymize_completed_deletion_request(request)
        return counts

    async def mark_deletion_failed(self, *, request_id: UUID, error_code: str) -> None:
        request = await self._repository.get_deletion_request(request_id)
        if request is None:
            return
        if request.status == "SUCCEEDED":
            return
        safe_error_code = _safe_error_code(error_code)
        await self._repository.mark_request_failed(request, safe_error_code)
        await self._repository.create_audit_event(
            user_id_snapshot=request.user_id_snapshot,
            event_type="COMPLETE_ACCOUNT_DELETION",
            target_type="app_user",
            target_id=(
                str(request.user_id_snapshot)
                if request.user_id_snapshot is not None
                else request.user_id_hash
            ),
            request_id=request.id,
            status="FAILED",
            error_code=safe_error_code,
        )

    async def _policy(self, user_id: UUID) -> UserTrainingPolicy | None:
        result = await self._session.execute(
            select(UserTrainingPolicy).where(UserTrainingPolicy.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def _sessions_export(self, user_id: UUID) -> list[dict[str, object]]:
        session_result = await self._session.execute(
            select(TrainingSession)
            .where(TrainingSession.user_id == user_id)
            .order_by(TrainingSession.created_at)
        )
        sessions = list(session_result.scalars().all())
        if not sessions:
            return []
        attempts_by_session = await self._attempts_by_session([item.id for item in sessions])
        reports_by_session = await self._reports_by_session([item.id for item in sessions])
        sources_by_question = await self._sources_by_question(
            user_id=user_id,
            question_ids=[item.question_id for item in sessions if item.question_id is not None],
        )
        return [
            _json_dict(
                {
                    "id": item.id,
                    "thread_id": item.thread_id,
                    "stage": item.stage,
                    "scheduled_at": item.scheduled_at,
                    "completed_at": item.completed_at,
                    "question_id": item.question_id,
                    "attempts": attempts_by_session[item.id],
                    "report": reports_by_session.get(item.id),
                    "sources": sources_by_question.get(item.question_id, []),
                }
            )
            for item in sessions
        ]

    async def _attempts_by_session(
        self,
        session_ids: list[UUID],
    ) -> dict[UUID, list[dict[str, object]]]:
        result = await self._session.execute(
            select(VoiceAttempt)
            .where(VoiceAttempt.session_id.in_(session_ids))
            .order_by(VoiceAttempt.created_at)
        )
        attempts = list(result.scalars().all())
        transcripts = await self._transcripts_by_attempt([item.id for item in attempts])
        corrections = await self._corrections_by_attempt([item.id for item in attempts])
        grouped: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for attempt in attempts:
            grouped[attempt.session_id].append(
                {
                    "id": attempt.id,
                    "stage": attempt.stage,
                    "round": attempt.round,
                    "upload_status": attempt.upload_status,
                    "mime_type": attempt.mime_type,
                    "duration_ms": attempt.duration_ms,
                    "size_bytes": attempt.size_bytes,
                    "checksum_sha256": attempt.checksum_sha256,
                    "uploaded_at": attempt.uploaded_at,
                    "transcript": transcripts.get(attempt.id),
                    "corrections": corrections[attempt.id],
                }
            )
        return grouped

    async def _transcripts_by_attempt(
        self,
        attempt_ids: list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        if not attempt_ids:
            return {}
        transcript_result = await self._session.execute(
            select(AttemptTranscript).where(AttemptTranscript.attempt_id.in_(attempt_ids))
        )
        transcripts = list(transcript_result.scalars().all())
        segment_result = await self._session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.attempt_id.in_(attempt_ids))
            .order_by(TranscriptSegment.segment_index)
        )
        grouped_segments: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for segment in segment_result.scalars().all():
            grouped_segments[segment.attempt_id].append(
                {
                    "id": segment.id,
                    "segment_index": segment.segment_index,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "raw_text": segment.raw_text,
                    "corrected_text": segment.corrected_text,
                }
            )
        return {
            transcript.attempt_id: {
                "id": transcript.id,
                "status": transcript.status,
                "raw_text": transcript.raw_text,
                "corrected_text": transcript.corrected_text,
                "language": transcript.language,
                "metrics": transcript.metrics_json,
                "segments": grouped_segments[transcript.attempt_id],
            }
            for transcript in transcripts
        }

    async def _corrections_by_attempt(
        self,
        attempt_ids: list[UUID],
    ) -> dict[UUID, list[dict[str, object]]]:
        grouped: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        if not attempt_ids:
            return grouped
        result = await self._session.execute(
            select(TranscriptCorrection)
            .where(TranscriptCorrection.attempt_id.in_(attempt_ids))
            .order_by(TranscriptCorrection.created_at, TranscriptCorrection.id)
        )
        for correction in result.scalars().all():
            grouped[correction.attempt_id].append(
                {
                    "id": correction.id,
                    "segment_id": correction.segment_id,
                    "raw_text": correction.raw_text,
                    "previous_corrected_text": correction.previous_corrected_text,
                    "corrected_text": correction.corrected_text,
                    "reason": correction.reason,
                    "created_at": correction.created_at,
                }
            )
        return grouped

    async def _reports_by_session(
        self,
        session_ids: list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        result = await self._session.execute(
            select(EvaluationReport).where(EvaluationReport.session_id.in_(session_ids))
        )
        reports = list(result.scalars().all())
        issues_by_report = await self._issues_by_report([item.id for item in reports])
        return {
            report.session_id: {
                "id": report.id,
                "status": report.status,
                "logic_score": report.logic_score,
                "speech_score": report.speech_score,
                "adaptability_score": report.adaptability_score,
                "final_score": report.final_score,
                "error_code": report.error_code,
                "completed_at": report.completed_at,
                "issues": issues_by_report[report.id],
            }
            for report in reports
        }

    async def _issues_by_report(
        self,
        report_ids: list[UUID],
    ) -> dict[UUID, list[dict[str, object]]]:
        grouped: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        if not report_ids:
            return grouped
        result = await self._session.execute(
            select(EvaluationIssue)
            .where(EvaluationIssue.report_id.in_(report_ids))
            .order_by(EvaluationIssue.created_at)
        )
        for issue in result.scalars().all():
            grouped[issue.report_id].append(
                {
                    "id": issue.id,
                    "attempt_id": issue.attempt_id,
                    "transcript_segment_id": issue.transcript_segment_id,
                    "category": issue.category,
                    "code": issue.code,
                    "severity": issue.severity,
                    "confidence": issue.confidence,
                    "quote": issue.quote,
                    "start_ms": issue.start_ms,
                    "end_ms": issue.end_ms,
                    "explanation": issue.explanation,
                    "missing_information": issue.missing_information,
                    "correction_rule": issue.correction_rule,
                }
            )
        return grouped

    async def _sources_by_question(
        self,
        *,
        user_id: UUID,
        question_ids: list[UUID],
    ) -> dict[UUID | None, list[dict[str, object]]]:
        if not question_ids:
            return {}
        bundle_result = await self._session.execute(
            select(Question.id, SourceBundle)
            .join(SourceBundle, SourceBundle.id == Question.source_bundle_id)
            .where(
                Question.id.in_(question_ids),
                Question.user_id == user_id,
                SourceBundle.user_id == user_id,
            )
        )
        bundle_by_question: dict[UUID, SourceBundle] = {
            question_id: bundle for question_id, bundle in bundle_result.all()
        }
        if not bundle_by_question:
            return {}
        bundle_ids = [bundle.id for bundle in bundle_by_question.values()]
        source_result = await self._session.execute(
            select(QuestionSource)
            .where(QuestionSource.source_bundle_id.in_(bundle_ids))
            .order_by(QuestionSource.created_at, QuestionSource.id)
        )
        sources = list(source_result.scalars().all())
        claims_by_source = await self._claims_by_source([item.id for item in sources])
        sources_by_bundle: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for source in sources:
            sources_by_bundle[source.source_bundle_id].append(
                {
                    "id": source.id,
                    "title": source.title,
                    "publisher": source.publisher,
                    "url": source.url,
                    "level": source.level,
                    "content_type": source.content_type,
                    "published_at": source.published_at,
                    "accessed_at": source.accessed_at,
                    "snapshot_hash": source.snapshot_hash,
                    "fetch_status": source.fetch_status,
                    "claims": claims_by_source[source.id],
                }
            )
        return {
            question_id: [
                {
                    "source_bundle_id": bundle.id,
                    "status": bundle.status,
                    "source_count": bundle.source_count,
                    "highest_source_level": bundle.highest_source_level,
                    "credential": bundle.credential,
                    "sources": sources_by_bundle[bundle.id],
                }
            ]
            for question_id, bundle in bundle_by_question.items()
        }

    async def _claims_by_source(
        self,
        source_ids: list[UUID],
    ) -> dict[UUID, list[dict[str, object]]]:
        grouped: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        if not source_ids:
            return grouped
        result = await self._session.execute(
            select(SourceClaim)
            .where(SourceClaim.source_id.in_(source_ids))
            .order_by(SourceClaim.created_at, SourceClaim.id)
        )
        for claim in result.scalars().all():
            grouped[claim.source_id].append(
                {
                    "id": claim.id,
                    "claim_text": claim.claim_text,
                    "locator": claim.locator,
                    "excerpt": claim.excerpt,
                    "support_status": claim.support_status,
                    "valid_until": claim.valid_until,
                }
            )
        return grouped

    async def _defect_profiles_export(self, user_id: UUID) -> list[dict[str, object]]:
        result = await self._session.execute(
            select(DefectProfile)
            .where(DefectProfile.user_id == user_id)
            .order_by(DefectProfile.priority.desc(), DefectProfile.defect_code)
        )
        return [
            _json_dict(
                {
                    "defect_code": item.defect_code,
                    "state": item.state,
                    "priority": item.priority,
                    "active_occurrence_count": item.active_occurrence_count,
                    "suspended_occurrence_count": item.suspended_occurrence_count,
                    "last_seen_at": item.last_seen_at,
                }
            )
            for item in result.scalars().all()
        ]

    async def _weekly_reports_export(self, user_id: UUID) -> list[dict[str, object]]:
        result = await self._session.execute(
            select(WeeklyReport)
            .where(WeeklyReport.user_id == user_id)
            .order_by(WeeklyReport.week_start.desc())
        )
        return [
            _json_dict(
                {
                    "id": item.id,
                    "week_start": item.week_start,
                    "week_end": item.week_end,
                    "metrics": item.metrics_json,
                    "summary": item.summary,
                    "created_at": item.created_at,
                }
            )
            for item in result.scalars().all()
        ]

    async def _appeals_export(self, user_id: UUID) -> list[dict[str, object]]:
        result = await self._session.execute(
            select(Appeal).where(Appeal.user_id == user_id).order_by(Appeal.created_at.desc())
        )
        return [
            _json_dict(
                {
                    "id": item.id,
                    "session_id": item.session_id,
                    "type": item.type,
                    "target": item.target_json,
                    "status": item.status,
                    "reason": item.reason,
                    "resolution": item.resolution,
                    "created_at": item.created_at,
                }
            )
            for item in result.scalars().all()
        ]

    async def _duplicate_complaints_export(self, user_id: UUID) -> list[dict[str, object]]:
        result = await self._session.execute(
            select(QuestionDuplicateComplaint)
            .where(QuestionDuplicateComplaint.user_id == user_id)
            .order_by(QuestionDuplicateComplaint.created_at.desc())
        )
        return [
            _json_dict(
                {
                    "id": item.id,
                    "session_id": item.session_id,
                    "question_id": item.question_id,
                    "similar_question_id": item.similar_question_id,
                    "duplicate_type": item.duplicate_type,
                    "template_family": item.template_family,
                    "reason": item.reason,
                    "status": item.status,
                    "created_at": item.created_at,
                }
            )
            for item in result.scalars().all()
        ]

    async def _privacy_audit_events_export(self, user_id: UUID) -> list[dict[str, object]]:
        result = await self._session.execute(
            select(PrivacyAuditEvent)
            .where(PrivacyAuditEvent.user_id_snapshot == user_id)
            .order_by(PrivacyAuditEvent.created_at.desc(), PrivacyAuditEvent.id.desc())
        )
        return [
            _json_dict(
                {
                    "id": item.id,
                    "event_type": item.event_type,
                    "target_type": item.target_type,
                    "target_id": item.target_id,
                    "request_id": item.request_id,
                    "status": item.status,
                    "counts": item.counts_json,
                    "error_code": item.error_code,
                    "created_at": item.created_at,
                }
            )
            for item in result.scalars().all()
        ]


def _policy_export(policy: UserTrainingPolicy) -> dict[str, object]:
    return {
        "windows": policy.windows,
        "quiet_hours": policy.quiet_hours,
        "daily_max": policy.daily_max,
        "retention_days": policy.retention_days,
        "timezone": policy.timezone,
    }


@dataclass(frozen=True)
class AudioDeletionCounts:
    deleted_files: int
    invalid_references: int
    non_file_references: int


def _delete_audio_files(audio_root: Path, relative_paths: list[str]) -> AudioDeletionCounts:
    deleted = 0
    invalid_references = 0
    non_file_references = 0
    for relative_path in relative_paths:
        try:
            audio_path = resolve_stored_audio_path(audio_root, relative_path)
        except AudioStorageError:
            invalid_references += 1
            continue
        if not audio_path.exists():
            continue
        if not audio_path.is_file():
            non_file_references += 1
            continue
        audio_path.unlink()
        deleted += 1
    return AudioDeletionCounts(
        deleted_files=deleted,
        invalid_references=invalid_references,
        non_file_references=non_file_references,
    )


def _record_audio_deletion_counts(
    counts: dict[str, int],
    audio_deletion: AudioDeletionCounts,
) -> None:
    counts["audio_files"] = audio_deletion.deleted_files
    counts["audio_file_invalid_references"] = audio_deletion.invalid_references
    counts["audio_file_non_file_references"] = audio_deletion.non_file_references


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_error_code(error_code: str) -> str:
    if _SAFE_ERROR_CODE_RE.fullmatch(error_code):
        return error_code
    return "DELETION_FAILED"


def _json_dict(value: dict[str, object]) -> dict[str, object]:
    converted = _jsonify(value)
    if not isinstance(converted, dict):
        raise TypeError("expected dict after JSON conversion")
    return converted


def _jsonify(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
