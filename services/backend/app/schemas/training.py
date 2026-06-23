from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic.functional_validators import field_validator

AttemptStage = Literal["FIRST", "FOLLOWUP", "FINAL"]


class TrainingSessionResponse(BaseModel):
    id: UUID
    thread_id: str
    stage: str
    created_at: datetime


class CreateAttemptRequest(BaseModel):
    stage: AttemptStage
    round: int = Field(ge=1, le=3)


class VoiceAttemptResponse(BaseModel):
    id: UUID
    session_id: UUID
    stage: AttemptStage
    round: int
    upload_status: str
    mime_type: str | None
    duration_ms: int | None
    size_bytes: int | None
    checksum_sha256: str | None
    uploaded_at: datetime | None


class AudioUploadResponse(VoiceAttemptResponse):
    pass


class TrainingAwaitingInputResponse(BaseModel):
    type: str
    stage: AttemptStage
    round: int
    text: str


class TrainingStateResponse(BaseModel):
    id: UUID
    thread_id: str
    stage: str
    awaiting: TrainingAwaitingInputResponse | None
    current_attempt: VoiceAttemptResponse | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ResumeTrainingRequest(BaseModel):
    stage: AttemptStage
    round: int = Field(ge=1, le=3)
    attempt_id: UUID


class ResumeTrainingResponse(BaseModel):
    job_id: UUID
    session_stage: str


class TranscriptWordResponse(BaseModel):
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None


class TranscriptSegmentResponse(BaseModel):
    id: UUID
    segment_index: int
    start_ms: int
    end_ms: int
    raw_text: str
    corrected_text: str
    words: list[TranscriptWordResponse]


class AttemptTranscriptResponse(BaseModel):
    attempt_id: UUID
    status: str
    raw_text: str
    corrected_text: str
    language: str | None
    error_code: str | None
    metrics: dict[str, object] | None
    segments: list[TranscriptSegmentResponse]


class TranscriptCorrectionRequest(BaseModel):
    segment_id: UUID
    corrected_text: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("corrected_text", "reason")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped
