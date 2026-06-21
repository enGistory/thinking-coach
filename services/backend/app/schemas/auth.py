from __future__ import annotations

from datetime import datetime
from re import fullmatch
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("nickname")
    @classmethod
    def strip_nickname(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("nickname must not be empty")
        return stripped


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class AcceptInvitationRequest(LoginRequest):
    code: str = Field(min_length=16, max_length=256)


class CreateInvitationRequest(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=30)


class CreateInvitationResponse(BaseModel):
    id: UUID
    code: str
    expires_at: datetime


class TimeRange(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def validate_hhmm(cls, value: str) -> str:
        if fullmatch(r"\d{2}:\d{2}", value) is None:
            raise ValueError("time must use HH:MM")
        hour, minute = (int(part) for part in value.split(":", 1))
        if hour > 23 or minute > 59:
            raise ValueError("time must use HH:MM")
        return value

    @model_validator(mode="after")
    def validate_non_empty_range(self) -> TimeRange:
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class WeeklyWindow(TimeRange):
    days: list[int] = Field(min_length=1, max_length=7)

    @field_validator("days")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("days must be between 0 and 6")
        if len(set(value)) != len(value):
            raise ValueError("days must be unique")
        return value


class TrainingPolicyPayload(BaseModel):
    windows: list[WeeklyWindow] = Field(min_length=1, max_length=14)
    quiet_hours: list[TimeRange] = Field(default_factory=list, max_length=7)
    daily_max: int = Field(ge=1, le=10)
    retention_days: int = Field(ge=1, le=365)
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class TrainingPolicyResponse(TrainingPolicyPayload):
    user_id: UUID


class FailedJobResponse(BaseModel):
    id: UUID
    job_type: str
    status: str
    retry_count: int
    locked_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
