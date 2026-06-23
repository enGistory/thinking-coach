from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appeal,
    DefectDefinition,
    DefectEvidence,
    DefectOccurrence,
    DefectProfile,
    EvaluationIssue,
    EvaluationReport,
    TrainingSession,
    VoiceAttempt,
)
from app.domain.defects import (
    SPEC_DEFECT_DEFINITIONS,
    ConfidenceLevel,
    OccurrenceStatus,
    ProfileOccurrence,
    calculate_profile_stats,
    normalize_defect_code,
    occurrence_status_for_confidence,
)


@dataclass(frozen=True)
class ReportIssueBundle:
    training_session: TrainingSession
    report: EvaluationReport
    issue: EvaluationIssue
    attempt: VoiceAttempt


@dataclass(frozen=True)
class DefectProfileRow:
    profile: DefectProfile
    definition: DefectDefinition


@dataclass(frozen=True)
class DefectOccurrenceRow:
    occurrence: DefectOccurrence
    evidence: DefectEvidence
    similarity_reasons: list[str]


class DefectMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_definitions(self) -> None:
        for definition in SPEC_DEFECT_DEFINITIONS:
            await self._session.execute(
                insert(DefectDefinition)
                .values(
                    code=definition.code,
                    name=definition.name,
                    description=definition.description,
                    detection_rule=definition.detection_rule,
                    score_cap=definition.score_cap,
                )
                .on_conflict_do_nothing(index_elements=["code"])
            )

    async def sync_completed_report(
        self,
        *,
        report_id: UUID,
        user_id: UUID,
    ) -> list[str]:
        await self.ensure_definitions()
        affected_codes: set[str] = set()
        for bundle in await self._report_issues(report_id=report_id, user_id=user_id):
            defect_code = normalize_defect_code(bundle.issue.code)
            if defect_code is None:
                continue
            occurrence = await self._ensure_occurrence(bundle, defect_code)
            await self._ensure_evidence(occurrence, bundle.issue)
            affected_codes.add(defect_code)
        for defect_code in sorted(affected_codes):
            await self.rebuild_profile(user_id=user_id, defect_code=defect_code)
        return sorted(affected_codes)

    async def rebuild_profile(self, *, user_id: UUID, defect_code: str) -> DefectProfile:
        occurrences = await self._occurrences_for_profile(user_id=user_id, defect_code=defect_code)
        existing = await self._profile(user_id=user_id, defect_code=defect_code)
        stats = calculate_profile_stats(
            [
                ProfileOccurrence(
                    severity=occurrence.severity,
                    confidence=cast(ConfidenceLevel, occurrence.confidence),
                    scenario_key=occurrence.scenario_key,
                    attempt_stage=occurrence.attempt_stage,
                    status=cast(OccurrenceStatus, occurrence.status),
                    created_at=occurrence.created_at,
                )
                for occurrence in occurrences
            ],
            previous_state=existing.state if existing is not None else None,
            previous_recurrence=existing.recurrence if existing is not None else 0,
        )
        for occurrence in occurrences:
            occurrence.confirmed = stats.confirmed and occurrence.status == "ACTIVE"

        if existing is None:
            existing = DefectProfile(user_id=user_id, defect_code=defect_code, state=stats.state)
            self._session.add(existing)
        existing.state = stats.state
        existing.severity = stats.severity
        existing.frequency = stats.frequency
        existing.recurrence = stats.recurrence
        existing.priority = stats.priority
        existing.confidence = stats.confidence
        existing.active_occurrence_count = stats.active_occurrence_count
        existing.suspended_occurrence_count = stats.suspended_occurrence_count
        existing.scenario_count = stats.scenario_count
        existing.first_seen_at = stats.first_seen_at
        existing.last_seen_at = stats.last_seen_at
        await self._session.flush()
        return existing

    async def list_profiles(self, user_id: UUID) -> list[DefectProfileRow]:
        result = await self._session.execute(
            select(DefectProfile, DefectDefinition)
            .join(DefectDefinition, DefectProfile.defect_code == DefectDefinition.code)
            .where(DefectProfile.user_id == user_id)
            .order_by(DefectProfile.priority.desc(), DefectProfile.defect_code)
        )
        return [
            DefectProfileRow(profile=profile, definition=definition)
            for profile, definition in result.all()
        ]

    async def list_occurrences(
        self,
        *,
        user_id: UUID,
        defect_code: str,
    ) -> list[DefectOccurrenceRow]:
        normalized = normalize_defect_code(defect_code)
        if normalized is None:
            return []
        result = await self._session.execute(
            select(DefectOccurrence, DefectEvidence)
            .join(DefectEvidence, DefectEvidence.occurrence_id == DefectOccurrence.id)
            .where(
                DefectOccurrence.user_id == user_id,
                DefectOccurrence.defect_code == normalized,
            )
            .order_by(DefectOccurrence.created_at.desc())
        )
        rows = [(occurrence, evidence) for occurrence, evidence in result.all()]
        return [
            DefectOccurrenceRow(
                occurrence=occurrence,
                evidence=evidence,
                similarity_reasons=_similarity_reasons(occurrence, evidence, rows),
            )
            for occurrence, evidence in rows
        ]

    async def create_appeal(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        appeal_type: str,
        reason: str,
        issue_id: UUID | None,
        defect_code: str | None,
    ) -> Appeal | None:
        training_session = await self._owned_session(user_id=user_id, session_id=session_id)
        if training_session is None:
            return None

        normalized_code: str | None = None
        if defect_code is not None:
            normalized_code = normalize_defect_code(defect_code)
            if normalized_code is None:
                return None

        if issue_id is not None:
            issue = await self._owned_issue(
                user_id=user_id,
                session_id=training_session.id,
                issue_id=issue_id,
            )
            if issue is None:
                return None

        appealable_occurrences = await self._appealable_occurrences(
            user_id=user_id,
            session_id=training_session.id,
            issue_id=issue_id,
            defect_code=normalized_code,
        )
        if not appealable_occurrences:
            return None

        appeal = Appeal(
            user_id=user_id,
            session_id=training_session.id,
            issue_id=issue_id,
            defect_code=normalized_code,
            type=appeal_type,
            reason=reason,
            status="OPEN",
        )
        self._session.add(appeal)
        await self._session.flush()

        affected_codes: set[str] = set()
        for occurrence in appealable_occurrences:
            occurrence.previous_status = occurrence.status
            occurrence.status = "SUSPENDED"
            occurrence.suspending_appeal_id = appeal.id
            affected_codes.add(occurrence.defect_code)
        for code in sorted(affected_codes):
            await self.rebuild_profile(user_id=user_id, defect_code=code)
        await self._session.flush()
        return appeal

    async def review_appeal(
        self,
        *,
        appeal_id: UUID,
        user_id: UUID,
        accepted: bool,
        resolution: str,
    ) -> Appeal | None:
        appeal_result = await self._session.execute(
            select(Appeal).where(Appeal.id == appeal_id, Appeal.user_id == user_id)
        )
        appeal = appeal_result.scalar_one_or_none()
        if appeal is None:
            return None
        if appeal.status != "OPEN":
            return appeal

        affected = await self._occurrences_for_appeal(appeal.id)
        affected_codes = {occurrence.defect_code for occurrence in affected}
        for occurrence in affected:
            if accepted:
                occurrence.status = "EXCLUDED"
            else:
                occurrence.status = occurrence.previous_status or "ACTIVE"
                occurrence.suspending_appeal_id = None
            occurrence.previous_status = None
        appeal.status = "REVIEWED_ACCEPTED" if accepted else "REVIEWED_REJECTED"
        appeal.resolution = resolution
        appeal.reviewed_at = datetime.now(UTC)
        for code in sorted(affected_codes):
            await self.rebuild_profile(user_id=user_id, defect_code=code)
        await self._session.flush()
        return appeal

    async def _report_issues(self, *, report_id: UUID, user_id: UUID) -> list[ReportIssueBundle]:
        result = await self._session.execute(
            select(TrainingSession, EvaluationReport, EvaluationIssue, VoiceAttempt)
            .join(EvaluationReport, EvaluationReport.session_id == TrainingSession.id)
            .join(EvaluationIssue, EvaluationIssue.report_id == EvaluationReport.id)
            .join(
                VoiceAttempt,
                and_(
                    VoiceAttempt.id == EvaluationIssue.attempt_id,
                    VoiceAttempt.session_id == TrainingSession.id,
                ),
            )
            .where(
                TrainingSession.user_id == user_id,
                EvaluationReport.id == report_id,
                EvaluationReport.status == "COMPLETED",
            )
            .order_by(EvaluationIssue.created_at, EvaluationIssue.id)
        )
        return [
            ReportIssueBundle(
                training_session=training_session,
                report=report,
                issue=issue,
                attempt=attempt,
            )
            for training_session, report, issue, attempt in result.all()
        ]

    async def _ensure_occurrence(
        self,
        bundle: ReportIssueBundle,
        defect_code: str,
    ) -> DefectOccurrence:
        result = await self._session.execute(
            select(DefectOccurrence).where(
                DefectOccurrence.session_id == bundle.training_session.id,
                DefectOccurrence.issue_id == bundle.issue.id,
                DefectOccurrence.defect_code == defect_code,
            )
        )
        occurrence = result.scalar_one_or_none()
        status = occurrence_status_for_confidence(cast(ConfidenceLevel, bundle.issue.confidence))
        if occurrence is None:
            occurrence = DefectOccurrence(
                user_id=bundle.training_session.user_id,
                session_id=bundle.training_session.id,
                issue_id=bundle.issue.id,
                defect_code=defect_code,
                source_issue_code=bundle.issue.code,
                category=bundle.issue.category,
                scenario_key=_scenario_key(bundle.training_session),
                attempt_stage=bundle.attempt.stage,
                severity=bundle.issue.severity,
                confidence=bundle.issue.confidence,
                status=status,
                confirmed=False,
            )
            self._session.add(occurrence)
        elif occurrence.status not in {"SUSPENDED", "EXCLUDED"}:
            occurrence.source_issue_code = bundle.issue.code
            occurrence.category = bundle.issue.category
            occurrence.scenario_key = _scenario_key(bundle.training_session)
            occurrence.attempt_stage = bundle.attempt.stage
            occurrence.severity = bundle.issue.severity
            occurrence.confidence = bundle.issue.confidence
            occurrence.status = status
        await self._session.flush()
        return occurrence

    async def _ensure_evidence(
        self,
        occurrence: DefectOccurrence,
        issue: EvaluationIssue,
    ) -> DefectEvidence:
        result = await self._session.execute(
            select(DefectEvidence).where(DefectEvidence.occurrence_id == occurrence.id)
        )
        evidence = result.scalar_one_or_none()
        if evidence is None:
            evidence = DefectEvidence(occurrence_id=occurrence.id, issue_id=issue.id)
            self._session.add(evidence)
        evidence.issue_id = issue.id
        evidence.attempt_id = issue.attempt_id
        evidence.transcript_segment_id = issue.transcript_segment_id
        evidence.quote = issue.quote
        evidence.start_ms = issue.start_ms
        evidence.end_ms = issue.end_ms
        evidence.explanation = issue.explanation
        evidence.missing_information = issue.missing_information
        evidence.correction_rule = issue.correction_rule
        evidence.verification_json = issue.verification_json
        await self._session.flush()
        return evidence

    async def _profile(self, *, user_id: UUID, defect_code: str) -> DefectProfile | None:
        result = await self._session.execute(
            select(DefectProfile).where(
                DefectProfile.user_id == user_id,
                DefectProfile.defect_code == defect_code,
            )
        )
        return result.scalar_one_or_none()

    async def _occurrences_for_profile(
        self,
        *,
        user_id: UUID,
        defect_code: str,
    ) -> list[DefectOccurrence]:
        result = await self._session.execute(
            select(DefectOccurrence)
            .where(
                DefectOccurrence.user_id == user_id,
                DefectOccurrence.defect_code == defect_code,
                DefectOccurrence.status.in_(["ACTIVE", "SUSPENDED"]),
            )
            .order_by(DefectOccurrence.created_at)
        )
        return list(result.scalars().all())

    async def _owned_session(self, *, user_id: UUID, session_id: UUID) -> TrainingSession | None:
        result = await self._session.execute(
            select(TrainingSession).where(
                TrainingSession.id == session_id,
                TrainingSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _owned_issue(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        issue_id: UUID,
    ) -> EvaluationIssue | None:
        result = await self._session.execute(
            select(EvaluationIssue)
            .join(EvaluationReport, EvaluationIssue.report_id == EvaluationReport.id)
            .join(TrainingSession, EvaluationReport.session_id == TrainingSession.id)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.id == session_id,
                EvaluationIssue.id == issue_id,
            )
        )
        return result.scalar_one_or_none()

    async def _appealable_occurrences(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        issue_id: UUID | None,
        defect_code: str | None,
    ) -> list[DefectOccurrence]:
        statement = select(DefectOccurrence).where(
            DefectOccurrence.user_id == user_id,
            DefectOccurrence.session_id == session_id,
            DefectOccurrence.status.in_(["ACTIVE", "PENDING"]),
        )
        if issue_id is not None:
            statement = statement.where(DefectOccurrence.issue_id == issue_id)
        if defect_code is not None:
            statement = statement.where(DefectOccurrence.defect_code == defect_code)
        result = await self._session.execute(statement.order_by(DefectOccurrence.created_at))
        return list(result.scalars().all())

    async def _occurrences_for_appeal(self, appeal_id: UUID) -> list[DefectOccurrence]:
        result = await self._session.execute(
            select(DefectOccurrence)
            .where(DefectOccurrence.suspending_appeal_id == appeal_id)
            .order_by(DefectOccurrence.created_at)
        )
        return list(result.scalars().all())


def _scenario_key(training_session: TrainingSession) -> str:
    if training_session.question_id is not None:
        return f"question:{training_session.question_id}"
    return "unscoped"


def _similarity_reasons(
    occurrence: DefectOccurrence,
    evidence: DefectEvidence,
    rows: list[tuple[DefectOccurrence, DefectEvidence]],
) -> list[str]:
    reasons: set[str] = set()
    for other, other_evidence in rows:
        if other.id == occurrence.id:
            continue
        reasons.add("same_defect_code")
        if other.scenario_key == occurrence.scenario_key and occurrence.scenario_key != "unscoped":
            reasons.add("same_scenario")
        if other_evidence.correction_rule == evidence.correction_rule:
            reasons.add("same_correction_rule")
        if set(other_evidence.missing_information) & set(evidence.missing_information):
            reasons.add("overlapping_missing_information")
    if not reasons:
        reasons.add("same_defect_code")
    return sorted(reasons)
