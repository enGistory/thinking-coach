from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from statistics import mean
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppUser, DefectProfile, SourceBundle, WeeklyReport
from app.repositories.auth import UserRepository
from app.repositories.reports import CompletedReportRow, ReportRepository, TrainingReportBundle
from app.repositories.training_policy import TrainingPolicyRepository
from app.schemas.reports import (
    ReportIssueResponse,
    SimilarDefectResponse,
    TrainingAppealStatusResponse,
    TrainingReportResponse,
    WeeklyReportResponse,
)
from app.schemas.source_question import SourceLevel, SourceSummaryResponse


class ReportService:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session
        self._repository = ReportRepository(session)

    async def training_report(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> TrainingReportResponse | None:
        bundle = await self._repository.get_training_report(user_id=user_id, session_id=session_id)
        if bundle is None:
            return None
        return _training_report_response(bundle)

    async def weekly_reports(self, *, user_id: UUID, limit: int = 12) -> list[WeeklyReportResponse]:
        reports = await self._repository.list_weekly_reports(user_id=user_id, limit=limit)
        return [_weekly_report_response(report) for report in reports]

    async def generate_previous_week_for_user(
        self,
        *,
        user_id: UUID,
        now: datetime,
        timezone_name: str | None = None,
    ) -> WeeklyReport:
        zone = _safe_zone(timezone_name or "Asia/Shanghai")
        week_start, week_end, start_at, end_at = _previous_week_window(now, zone)
        completed = await self._repository.list_completed_reports_for_week(
            user_id=user_id,
            start_at=start_at,
            end_at=end_at,
        )
        profiles = await self._repository.list_profiles(user_id=user_id)
        metrics = _weekly_metrics(completed, profiles)
        summary = _weekly_summary(metrics)
        return await self._repository.upsert_weekly_report(
            user_id=user_id,
            week_start=week_start,
            week_end=week_end,
            metrics=metrics,
            summary=summary,
        )

    async def generate_previous_week_for_all_active_users(
        self,
        *,
        now: datetime,
    ) -> list[WeeklyReport]:
        users = await UserRepository(self._session).list_active_users()
        reports: list[WeeklyReport] = []
        for user in users:
            reports.append(await self.generate_previous_week_for_active_user(user=user, now=now))
        return reports

    async def generate_previous_week_for_active_user(
        self,
        *,
        user: AppUser,
        now: datetime,
    ) -> WeeklyReport:
        policy = await TrainingPolicyRepository(self._session).get_for_user(user.id)
        return await self.generate_previous_week_for_user(
            user_id=user.id,
            now=now,
            timezone_name=policy.timezone if policy is not None else None,
        )


def _training_report_response(bundle: TrainingReportBundle) -> TrainingReportResponse:
    report = bundle.report
    return TrainingReportResponse(
        session_id=bundle.training_session.id,
        report_id=report.id,
        stage=bundle.training_session.stage,
        evaluated_at=report.completed_at or report.updated_at,
        rubric_version=_rubric_version(report.details_json),
        total_score=float(report.final_score or 0),
        logic_score=float(report.logic_score or 0),
        expression_score=float(report.speech_score or 0),
        adaptability_score=float(report.adaptability_score or 0),
        confidence=_report_confidence(bundle),
        summary=_report_summary(bundle),
        source_summary=_source_summary(bundle.source_bundle),
        issues=[
            ReportIssueResponse(
                id=row.issue.id,
                attempt_id=row.issue.attempt_id,
                attempt_stage=row.attempt.stage,
                transcript_segment_id=row.issue.transcript_segment_id,
                category=row.issue.category,
                code=row.issue.code,
                severity=row.issue.severity,
                confidence=row.issue.confidence,
                quote=row.issue.quote,
                start_ms=row.issue.start_ms,
                end_ms=row.issue.end_ms,
                explanation=row.issue.explanation,
                missing_information=row.issue.missing_information,
                correction_rule=row.issue.correction_rule,
            )
            for row in bundle.issues
        ],
        similar_defects=[
            SimilarDefectResponse(
                id=row.occurrence.id,
                session_id=row.occurrence.session_id,
                issue_id=row.occurrence.issue_id,
                defect_code=row.occurrence.defect_code,
                quote=row.evidence.quote,
                start_ms=row.evidence.start_ms,
                end_ms=row.evidence.end_ms,
                created_at=row.occurrence.created_at,
            )
            for row in bundle.similar_defects
        ],
        appeals=[
            TrainingAppealStatusResponse(
                id=appeal.id,
                type=appeal.type,
                status=appeal.status,
                target=appeal.target_json,
                reason=appeal.reason,
                resolution=appeal.resolution,
                created_at=appeal.created_at,
            )
            for appeal in bundle.appeals
        ]
        + [
            TrainingAppealStatusResponse(
                id=complaint.id,
                type="duplicate_question",
                status=complaint.status,
                target={
                    "question_id": str(complaint.question_id),
                    "similar_question_id": (
                        str(complaint.similar_question_id)
                        if complaint.similar_question_id is not None
                        else None
                    ),
                    "duplicate_type": complaint.duplicate_type,
                },
                reason=complaint.reason,
                resolution="DUPLICATE_QUESTION_ACCEPTED",
                created_at=complaint.created_at,
            )
            for complaint in bundle.duplicate_complaints
        ],
    )


def _weekly_report_response(report: WeeklyReport) -> WeeklyReportResponse:
    return WeeklyReportResponse(
        id=report.id,
        week_start=report.week_start,
        week_end=report.week_end,
        metrics=report.metrics_json,
        summary=report.summary,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _source_summary(bundle: SourceBundle | None) -> SourceSummaryResponse | None:
    if bundle is None:
        return None
    return SourceSummaryResponse(
        source_count=bundle.source_count,
        highest_source_level=cast(SourceLevel | None, bundle.highest_source_level),
        credential=bundle.credential,
    )


def _rubric_version(details: dict[str, object]) -> str:
    value = details.get("rubric_version")
    return value if isinstance(value, str) and value else "default"


def _report_confidence(bundle: TrainingReportBundle) -> str:
    if not bundle.issues:
        return "medium"
    if any(row.issue.confidence == "low" for row in bundle.issues):
        return "low"
    if all(row.issue.confidence == "high" for row in bundle.issues):
        return "high"
    return "medium"


def _report_summary(bundle: TrainingReportBundle) -> str:
    final_score = bundle.report.final_score or 0
    issue_count = len(bundle.issues)
    return f"Final score {final_score}; evidence issues {issue_count}."


def _weekly_metrics(
    completed: list[CompletedReportRow],
    profiles: list[DefectProfile],
) -> dict[str, object]:
    final_scores = [
        row.report.final_score for row in completed if row.report.final_score is not None
    ]
    logic_scores = [
        row.report.logic_score for row in completed if row.report.logic_score is not None
    ]
    speech_scores = [
        row.report.speech_score for row in completed if row.report.speech_score is not None
    ]
    adaptability_scores = [
        row.report.adaptability_score
        for row in completed
        if row.report.adaptability_score is not None
    ]
    top_defects = [
        {
            "code": profile.defect_code,
            "state": profile.state,
            "priority": profile.priority,
            "active_occurrence_count": profile.active_occurrence_count,
        }
        for profile in profiles[:5]
    ]
    return {
        "completed_session_count": len(completed),
        "average_final_score": _average(final_scores),
        "average_logic_score": _average(logic_scores),
        "average_speech_score": _average(speech_scores),
        "average_adaptability_score": _average(adaptability_scores),
        "score_delta": _score_delta(final_scores),
        "speech_metric_averages": _speech_metric_averages(completed),
        "top_defects": top_defects,
    }


def _weekly_summary(metrics: dict[str, object]) -> str:
    count = _int_metric(metrics, "completed_session_count")
    if count == 0:
        return "No completed training this week; defect profile unchanged."
    average = metrics.get("average_final_score")
    top_defects = metrics.get("top_defects")
    defect_text = "暂无高优先缺陷"
    if isinstance(top_defects, list) and top_defects:
        first = top_defects[0]
        if isinstance(first, dict):
            defect_text = str(first.get("code") or "unnamed_defect")
    return f"Completed sessions {count}; average score {average}; top focus {defect_text}."


def _int_metric(metrics: dict[str, object], key: str) -> int:
    value = metrics.get(key)
    return value if isinstance(value, int) else 0


def _average(values: list[int]) -> float | None:
    if not values:
        return None
    return round(float(mean(values)), 2)


def _score_delta(values: list[int]) -> int | None:
    if len(values) < 2:
        return None
    return values[-1] - values[0]


def _speech_metric_averages(completed: list[CompletedReportRow]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for row in completed:
        speech_review = row.report.details_json.get("speech_review")
        if not isinstance(speech_review, dict):
            continue
        metrics = speech_review.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                buckets.setdefault(key, []).append(float(value))
    return {key: round(float(mean(values)), 2) for key, values in buckets.items() if values}


def _previous_week_window(
    now: datetime,
    zone: ZoneInfo,
) -> tuple[date, date, datetime, datetime]:
    aware_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    local_now = aware_now.astimezone(zone)
    this_week_start = local_now.date() - timedelta(days=local_now.weekday())
    week_start = this_week_start - timedelta(days=7)
    week_end = this_week_start - timedelta(days=1)
    start_at = datetime.combine(week_start, time.min, tzinfo=zone).astimezone(UTC)
    end_at = datetime.combine(this_week_start, time.min, tzinfo=zone).astimezone(UTC)
    return week_start, week_end, start_at, end_at


def _safe_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")
