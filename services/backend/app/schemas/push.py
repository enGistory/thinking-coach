from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.push import validate_push_endpoint


class PushPublicKeyResponse(BaseModel):
    public_key: str


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=4096)
    auth: str = Field(min_length=1, max_length=4096)


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=4096)
    keys: PushSubscriptionKeys
    user_agent: str = Field(default="", max_length=512)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return validate_push_endpoint(value)


class PushSubscriptionResponse(BaseModel):
    id: UUID
    endpoint: str
    active: bool
    created_at: datetime
