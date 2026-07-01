from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.dependencies import require_admin
from app.db.models import Appeal, AppUser
from app.db.session import get_session
from app.repositories.jobs import AIJobRepository
from app.schemas.auth import FailedJobResponse
from app.schemas.defects import AdminAppealResponse, AppealReviewRequest
from app.services.defects import DefectMemoryError, DefectMemoryService

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


@router.get("/appeals", response_model=list[AdminAppealResponse])
async def list_appeals(
    current_admin: Annotated[AppUser, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AdminAppealResponse]:
    appeals = await DefectMemoryService(session=session).list_admin_appeals(limit=limit)
    return [_admin_appeal_response(appeal) for appeal in appeals]


@router.post("/appeals/{appeal_id}/review", response_model=AdminAppealResponse)
async def review_appeal(
    appeal_id: UUID,
    payload: AppealReviewRequest,
    current_admin: Annotated[AppUser, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminAppealResponse:
    result = await session.execute(select(Appeal).where(Appeal.id == appeal_id))
    existing = result.scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="APPEAL_NOT_FOUND")
    try:
        appeal = await DefectMemoryService(session=session).review_appeal(
            appeal_id=existing.id,
            user_id=existing.user_id,
            accepted=payload.accepted,
            resolution=payload.resolution,
        )
    except DefectMemoryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code) from exc
    await session.commit()
    return _admin_appeal_response(appeal)


def _admin_appeal_response(appeal: Appeal) -> AdminAppealResponse:
    return AdminAppealResponse(
        id=appeal.id,
        user_id=appeal.user_id,
        session_id=appeal.session_id,
        issue_id=appeal.issue_id,
        defect_code=appeal.defect_code,
        type=appeal.type,
        target=appeal.target_json,
        status=appeal.status,
        reason=appeal.reason,
        resolution=appeal.resolution,
        created_at=appeal.created_at,
        reviewed_at=appeal.reviewed_at,
    )
