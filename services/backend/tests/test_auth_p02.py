from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.db.models import AIJob
from app.db.session import get_session
from app.main import create_app
from app.repositories.auth import UserRepository

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="TEST_DATABASE_URL is required for P02 database isolation tests",
)


@pytest.fixture
async def db_maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert TEST_DATABASE_URL is not None
    _assert_test_database(TEST_DATABASE_URL)
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest.fixture
async def client(
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> AsyncIterator[AsyncClient]:
    def test_settings() -> Settings:
        return Settings(
            _env_file=None,
            ai_provider_mode="mock",
            jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
            audio_root=tmp_path,
            audio_retention_days=30,
            tz="Asia/Shanghai",
        )

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with db_maker() as session:
            yield session

    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", test_settings)
    monkeypatch.setattr("app.api.dependencies.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.auth.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.invitations.get_settings", test_settings)
    monkeypatch.setattr("app.api.v1.me.get_settings", test_settings)

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


async def test_invitation_auth_refresh_logout_and_policy_isolation(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="admin", password="admin-password", role="ADMIN")

    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"nickname": "admin", "password": "admin-password"},
    )
    assert admin_login.status_code == 200
    admin_access = admin_login.json()["access_token"]

    invitation = await client.post(
        "/api/v1/admin/invitations",
        headers=_auth_headers(admin_access),
        json={"expires_in_days": 7},
    )
    assert invitation.status_code == 201
    invitation_code = invitation.json()["code"]

    first_user = await client.post(
        "/api/v1/invitations/accept",
        json={"code": invitation_code, "nickname": "first", "password": "first-password"},
    )
    assert first_user.status_code == 201
    first_tokens = first_user.json()

    reused_code = await client.post(
        "/api/v1/invitations/accept",
        json={"code": invitation_code, "nickname": "again", "password": "again-password"},
    )
    assert reused_code.status_code == 400

    user_admin_attempt = await client.post(
        "/api/v1/admin/invitations",
        headers=_auth_headers(first_tokens["access_token"]),
        json={"expires_in_days": 7},
    )
    assert user_admin_attempt.status_code == 403

    updated_policy = {
        "windows": [{"days": [1, 3, 5], "start": "10:00", "end": "17:30"}],
        "quiet_hours": [{"start": "22:30", "end": "07:30"}],
        "daily_max": 4,
        "retention_days": 45,
        "timezone": "Asia/Shanghai",
    }
    update_response = await client.put(
        "/api/v1/me/training-policy",
        headers=_auth_headers(first_tokens["access_token"]),
        json=updated_policy,
    )
    assert update_response.status_code == 200
    assert update_response.json()["daily_max"] == 4

    second_invitation = await client.post(
        "/api/v1/admin/invitations",
        headers=_auth_headers(admin_access),
        json={"expires_in_days": 7},
    )
    assert second_invitation.status_code == 201
    second_user = await client.post(
        "/api/v1/invitations/accept",
        json={
            "code": second_invitation.json()["code"],
            "nickname": "second",
            "password": "second-password",
        },
    )
    assert second_user.status_code == 201
    second_policy = await client.get(
        "/api/v1/me/training-policy",
        headers=_auth_headers(second_user.json()["access_token"]),
    )
    assert second_policy.status_code == 200
    assert second_policy.json()["daily_max"] == 2
    assert second_policy.json()["retention_days"] == 30

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    old_refresh_reuse = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_tokens["refresh_token"]},
    )
    assert old_refresh_reuse.status_code == 401

    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refreshed.json()["refresh_token"]},
    )
    assert logout.status_code == 204
    after_logout = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refreshed.json()["refresh_token"]},
    )
    assert after_logout.status_code == 401


async def test_disabled_user_cannot_login(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(
        db_maker,
        nickname="disabled",
        password="disabled-password",
        role="USER",
        status="DISABLED",
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"nickname": "disabled", "password": "disabled-password"},
    )

    assert response.status_code == 401


async def test_admin_failed_jobs_are_desensitized(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _create_user(db_maker, nickname="admin", password="admin-password", role="ADMIN")
    await _create_user(db_maker, nickname="user", password="user-password", role="USER")
    async with db_maker() as session:
        session.add(
            AIJob(
                job_type="GRAPH_RESUME",
                payload={"raw_answer": "sensitive-answer"},
                status="FAILED",
                retry_count=2,
                error_code="MODEL_TIMEOUT",
            )
        )
        await session.commit()

    user_login = await client.post(
        "/api/v1/auth/login",
        json={"nickname": "user", "password": "user-password"},
    )
    assert user_login.status_code == 200
    user_jobs = await client.get(
        "/api/v1/admin/jobs/failed",
        headers=_auth_headers(user_login.json()["access_token"]),
    )
    assert user_jobs.status_code == 403

    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"nickname": "admin", "password": "admin-password"},
    )
    assert admin_login.status_code == 200
    admin_jobs = await client.get(
        "/api/v1/admin/jobs/failed",
        headers=_auth_headers(admin_login.json()["access_token"]),
    )
    assert admin_jobs.status_code == 200
    assert admin_jobs.json()[0]["error_code"] == "MODEL_TIMEOUT"
    assert "raw_answer" not in admin_jobs.text
    assert "sensitive-answer" not in admin_jobs.text


async def _create_user(
    maker: async_sessionmaker[AsyncSession],
    *,
    nickname: str,
    password: str,
    role: str,
    status: str = "ACTIVE",
) -> None:
    async with maker() as session:
        await UserRepository(session).create_user(
            nickname=nickname,
            password_hash=hash_password(password),
            role=role,
            status=status,
        )
        await session.commit()


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _assert_test_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(f"Refusing to reset non-test database: {database_name}")
