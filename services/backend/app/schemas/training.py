from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
