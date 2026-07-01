from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appeal,
    DefectEvidence,
    DefectOccurrence,
    DefectProfile,
    EvaluationIssue,
    EvaluationReport,
    Question,
    QuestionDuplicateComplaint,
    SourceBundle,
    TrainingSession,
    VoiceAttempt,
    WeeklyReport,
)
from app.domain.defects import normalize_defect_code


@dataclass(frozen=True)
class ReportIssueRow:
    issue: EvaluationIssue
    attempt: VoiceAttempt


@dataclass(frozen=True)
class SimilarDefectRow:
    occurrence: DefectOccurrence
    evidence: DefectEvidence


@dataclass(frozen=True)
class TrainingReportBundle:
    training_session: TrainingSession
    report: EvaluationReport
    source_bundle: SourceBundle | None
    issues: list[ReportIssueRow]
    similar_defects: list[SimilarDefectRow]
    appeals: list[Appeal]
    duplicate_complaints: list[QuestionDuplicateComplaint]


@dataclass(frozen=True)
class CompletedReportRow:
    training_session: TrainingSession
    report: EvaluationReport


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_training_report(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> TrainingReportBundle | None:
        result = await self._session.execute(
            select(TrainingSession, EvaluationReport)
            .join(EvaluationReport, EvaluationReport.session_id == TrainingSession.id)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.id == session_id,
                EvaluationReport.status == "COMPLETED",
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        training_session, report = row
        issues = await self._report_issues(report.id, training_session.id)
        return TrainingReportBundle(
            training_session=training_session,
            report=report,
            source_bundle=await self._source_bundle(
                user_id=user_id,
                question_id=training_session.question_id,
            ),
            issues=issues,
            similar_defects=await self._similar_defects(
                user_id=user_id,
                session_id=training_session.id,
                issues=[item.issue for item in issues],
            ),
            appeals=await self._session_appeals(user_id=user_id, session_id=session_id),
            duplicate_complaints=await self._duplicate_complaints(
                user_id=user_id,
                session_id=session_id,
            ),
        )

    async def list_weekly_reports(self, *, user_id: UUID, limit: int = 12) -> list[WeeklyReport]:
        result = await self._session.execute(
            select(WeeklyReport)
            .where(WeeklyReport.user_id == user_id)
            .order_by(WeeklyReport.week_start.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_completed_reports_for_week(
        self,
        *,
        user_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> list[CompletedReportRow]:
        result = await self._session.execute(
            select(TrainingSession, EvaluationReport)
            .join(EvaluationReport, EvaluationReport.session_id == TrainingSession.id)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.completed_at >= start_at,
                TrainingSession.completed_at < end_at,
                EvaluationReport.status == "COMPLETED",
            )
            .order_by(TrainingSession.completed_at)
        )
        return [
            CompletedReportRow(training_session=training_session, report=report)
            for training_session, report in result.all()
        ]

    async def list_profiles(self, *, user_id: UUID) -> list[DefectProfile]:
        result = await self._session.execute(
            select(DefectProfile)
            .where(DefectProfile.user_id == user_id)
            .order_by(DefectProfile.priority.desc(), DefectProfile.defect_code)
        )
        return list(result.scalars().all())

    async def upsert_weekly_report(
        self,
        *,
        user_id: UUID,
        week_start: date,
        week_end: date,
        metrics: dict[str, object],
        summary: str,
    ) -> WeeklyReport:
        await self._session.execute(
            insert(WeeklyReport)
            .values(
                user_id=user_id,
                week_start=week_start,
                week_end=week_end,
                metrics_json=metrics,
                summary=summary,
            )
            .on_conflict_do_update(
                constraint="uq_weekly_report_user_week",
                set_={
                    "week_end": week_end,
                    "metrics_json": metrics,
                    "summary": summary,
                },
            )
        )
        result = await self._session.execute(
            select(WeeklyReport).where(
                WeeklyReport.user_id == user_id,
                WeeklyReport.week_start == week_start,
            )
        )
        return result.scalar_one()

    async def _report_issues(
        self,
        report_id: UUID,
        session_id: UUID,
    ) -> list[ReportIssueRow]:
        result = await self._session.execute(
            select(EvaluationIssue, VoiceAttempt)
            .join(
                VoiceAttempt,
                and_(
                    VoiceAttempt.id == EvaluationIssue.attempt_id,
                    VoiceAttempt.session_id == session_id,
                ),
            )
            .where(EvaluationIssue.report_id == report_id)
            .order_by(EvaluationIssue.created_at, EvaluationIssue.id)
        )
        return [ReportIssueRow(issue=issue, attempt=attempt) for issue, attempt in result.all()]

    async def _source_bundle(
        self,
        *,
        user_id: UUID,
        question_id: UUID | None,
    ) -> SourceBundle | None:
        if question_id is None:
            return None
        result = await self._session.execute(
            select(SourceBundle)
            .join(Question, Question.source_bundle_id == SourceBundle.id)
            .where(
                Question.id == question_id,
                Question.user_id == user_id,
                SourceBundle.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _similar_defects(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        issues: list[EvaluationIssue],
    ) -> list[SimilarDefectRow]:
        codes = sorted(
            {code for issue in issues if (code := normalize_defect_code(issue.code)) is not None}
        )
        if not codes:
            return []
        result = await self._session.execute(
            select(DefectOccurrence, DefectEvidence)
            .join(DefectEvidence, DefectEvidence.occurrence_id == DefectOccurrence.id)
            .where(
                DefectOccurrence.user_id == user_id,
                DefectOccurrence.session_id != session_id,
                DefectOccurrence.defect_code.in_(codes),
                DefectOccurrence.status.in_(["ACTIVE", "SUSPENDED"]),
            )
            .order_by(DefectOccurrence.created_at.desc())
            .limit(5)
        )
        return [
            SimilarDefectRow(occurrence=occurrence, evidence=evidence)
            for occurrence, evidence in result.all()
        ]

    async def _session_appeals(self, *, user_id: UUID, session_id: UUID) -> list[Appeal]:
        result = await self._session.execute(
            select(Appeal)
            .where(Appeal.user_id == user_id, Appeal.session_id == session_id)
            .order_by(Appeal.created_at.desc(), Appeal.id.desc())
        )
        return list(result.scalars().all())

    async def _duplicate_complaints(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> list[QuestionDuplicateComplaint]:
        result = await self._session.execute(
            select(QuestionDuplicateComplaint)
            .where(
                QuestionDuplicateComplaint.user_id == user_id,
                QuestionDuplicateComplaint.session_id == session_id,
            )
            .order_by(QuestionDuplicateComplaint.created_at.desc())
        )
        return list(result.scalars().all())
