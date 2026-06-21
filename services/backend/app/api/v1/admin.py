from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.db.models import AppUser
from app.db.session import get_session
from app.repositories.jobs import AIJobRepository
from app.schemas.auth import FailedJobResponse

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/jobs/failed", response_model=list[FailedJobResponse])
async def list_failed_jobs(
    current_admin: Annotated[AppUser, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[FailedJobResponse]:
    jobs = await AIJobRepository(session).list_failed(limit)
    return [
        FailedJobResponse(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            retry_count=job.retry_count,
            locked_at=job.locked_at,
            error_code=job.error_code,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        for job in jobs
    ]
