from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.core.config import get_settings
from app.db.session import get_session
from app.schemas.privacy import DeletionStatusRequest, DeletionStatusResponse
from app.services.privacy import PrivacyService

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])


@router.post("/deletion-status", response_model=DeletionStatusResponse)
async def get_deletion_status(
    payload: DeletionStatusRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeletionStatusResponse:
    result = await PrivacyService(session=session, settings=get_settings()).deletion_status(
        request_id=payload.request_id,
        proof_code=payload.proof_code,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DELETION_REQUEST_NOT_FOUND",
        )
    return result
