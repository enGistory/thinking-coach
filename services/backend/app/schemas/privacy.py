from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PersonalDataExportResponse(BaseModel):
    generated_at: datetime
    user: dict[str, object]
    training_policy: dict[str, object] | None
    sessions: list[dict[str, object]]
    defect_profiles: list[dict[str, object]]
    weekly_reports: list[dict[str, object]]
    appeals: list[dict[str, object]]
    duplicate_complaints: list[dict[str, object]]
    privacy_audit_events: list[dict[str, object]]


class TrainingDeletionResponse(BaseModel):
    session_id: UUID
    deleted: bool
    counts: dict[str, int]


class AccountDeletionResponse(BaseModel):
    request_id: UUID
    proof_code: str
    status: Literal["QUEUED"]


class DeletionStatusRequest(BaseModel):
    request_id: UUID
    proof_code: str = Field(min_length=8, max_length=128)

    @field_validator("proof_code")
    @classmethod
    def strip_proof_code(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("proof_code must not be blank")
        return stripped


class DeletionStatusResponse(BaseModel):
    request_id: UUID
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    counts: dict[str, object]
    error_code: str | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
