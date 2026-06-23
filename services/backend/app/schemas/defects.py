from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

AppealType = Literal["evaluation", "defect_classification"]
AppealStatus = Literal["OPEN", "REVIEWED_ACCEPTED", "REVIEWED_REJECTED"]
DefectProfileState = Literal[
    "observed",
    "confirmed",
    "high-priority",
    "improving",
    "stable-improved",
]


class DefectProfileResponse(BaseModel):
    code: str
    name: str
    description: str
    state: DefectProfileState
    severity: int
    frequency: int
    recurrence: int
    priority: int
    confidence: int
    active_occurrence_count: int
    suspended_occurrence_count: int
    scenario_count: int
    last_seen_at: datetime | None


class DefectOccurrenceResponse(BaseModel):
    id: UUID
    session_id: UUID
    issue_id: UUID
    status: str
    attempt_stage: str
    scenario_key: str
    severity: int
    confidence: str
    quote: str
    start_ms: int
    end_ms: int
    explanation: str
    missing_information: list[str]
    correction_rule: str
    similarity_reasons: list[str]
    created_at: datetime


class AppealRequest(BaseModel):
    type: AppealType
    reason: str = Field(min_length=1, max_length=2000)
    issue_id: UUID | None = None
    defect_code: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_target(self) -> AppealRequest:
        if self.issue_id is None and self.defect_code is None:
            raise ValueError("issue_id or defect_code is required")
        return self

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped

    @field_validator("defect_code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().upper()
        return stripped or None


class AppealResponse(BaseModel):
    id: UUID
    session_id: UUID
    issue_id: UUID | None
    defect_code: str | None
    type: AppealType
    status: AppealStatus
    reason: str
    resolution: str | None
    created_at: datetime
