from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.request_id import get_request_id
from app.db.session import check_database

router = APIRouter(prefix="/api/v1", tags=["health"])


class HealthCheck(BaseModel):
    ok: bool
    message: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    request_id: str
    checks: dict[str, HealthCheck]


def check_app() -> HealthCheck:
    settings = get_settings()
    if settings.app_name:
        return HealthCheck(ok=True, message=settings.app_name)
    return HealthCheck(ok=False, message="APP_NAME is empty")


async def check_database_health() -> HealthCheck:
    try:
        await check_database()
    except Exception as exc:
        return HealthCheck(ok=False, message=exc.__class__.__name__)
    return HealthCheck(ok=True, message="database reachable")


def check_audio_root(path: Path) -> HealthCheck:
    if not path.exists():
        return HealthCheck(ok=False, message=f"{path} does not exist")
    if not path.is_dir():
        return HealthCheck(ok=False, message=f"{path} is not a directory")
    if not os.access(path, os.R_OK | os.W_OK):
        return HealthCheck(ok=False, message=f"{path} is not readable and writable")
    return HealthCheck(ok=True, message=str(path))


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    checks = {
        "app": check_app(),
        "database": await check_database_health(),
        "audio_root": check_audio_root(settings.audio_root_resolved),
    }
    status_value: Literal["ok", "degraded"]
    if all(item.ok for item in checks.values()):
        status_value = "ok"
    else:
        status_value = "degraded"
    return HealthResponse(
        status=status_value,
        request_id=get_request_id(request),
        checks=checks,
    )
