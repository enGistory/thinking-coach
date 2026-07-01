from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.defects import AppealStatus, AppealType
from app.schemas.source_question import SourceSummaryResponse


class ReportIssueResponse(BaseModel):
    id: UUID
    attempt_id: UUID
    attempt_stage: str
    transcript_segment_id: UUID | None
    category: str
    code: str
    severity: int
    confidence: str
    quote: str
    start_ms: int
    end_ms: int
    explanation: str
    missing_information: list[str]
    correction_rule: str


class SimilarDefectResponse(BaseModel):
    id: UUID
    session_id: UUID
    issue_id: UUID
    defect_code: str
    quote: str
    start_ms: int
    end_ms: int
    created_at: datetime


class TrainingAppealStatusResponse(BaseModel):
    id: UUID
    type: AppealType | str
    status: AppealStatus | str
    target: dict[str, object]
    reason: str
    resolution: str | None
    created_at: datetime


class TrainingReportResponse(BaseModel):
    session_id: UUID
    report_id: UUID
    stage: str
    evaluated_at: datetime
    rubric_version: str
    total_score: float
    logic_score: float
    expression_score: float
    adaptability_score: float
    confidence: str
    summary: str
    source_summary: SourceSummaryResponse | None
    issues: list[ReportIssueResponse]
    similar_defects: list[SimilarDefectResponse]
    appeals: list[TrainingAppealStatusResponse]


class WeeklyReportResponse(BaseModel):
    id: UUID
    week_start: date
    week_end: date
    metrics: dict[str, object]
    summary: str
    created_at: datetime
    updated_at: datetime
