from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.core.config import get_settings
from app.core.security import hash_secret, verify_password
from app.db.session import get_session
from app.repositories.auth import RefreshTokenRepository, UserRepository
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenPair
from app.services.auth_tokens import issue_token_pair

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    user = await UserRepository(session).get_by_nickname(payload.nickname)
    if (
        user is None
        or user.status != "ACTIVE"
        or not verify_password(payload.password, user.password_hash)
    ):
        raise _invalid_credentials()

    issued = await issue_token_pair(session, user, get_settings())
    await session.commit()
    return TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenPair:
    now = datetime.now(UTC)
    token_repository = RefreshTokenRepository(session)
    refresh_token = await token_repository.get_valid_by_hash(
        hash_secret(payload.refresh_token),
        now,
    )
    if refresh_token is None:
        raise _invalid_credentials()

    user = await UserRepository(session).get_active_by_id(refresh_token.user_id)
    if user is None:
        token_repository.revoke(refresh_token, now)
        await session.commit()
        raise _invalid_credentials()

    token_repository.revoke(refresh_token, now)
    issued = await issue_token_pair(session, user, get_settings())
    await session.commit()
    return TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await RefreshTokenRepository(session).revoke_by_hash(
        hash_secret(payload.refresh_token),
        datetime.now(UTC),
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
