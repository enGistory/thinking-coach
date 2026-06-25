from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import UploadFile
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1 import trainings as trainings_api
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.db.models import VoiceAttempt
from app.db.session import get_session
from app.main import create_app
from app.repositories.auth import UserRepository
from app.services.audio_storage import (
    StoredAudio,
)
from app.services.audio_storage import (
    save_audio_upload as real_save_audio_upload,
)
from tests.helpers_source_questions import seed_exposed_training_session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="TEST_DATABASE_URL is required for P03 audio slice tests",
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
    tmp_path: Path,
) -> AsyncIterator[AsyncClient]:
    def test_settings() -> Settings:
        return Settings(
            _env_file=None,
            ai_provider_mode="mock",
            jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
            audio_root=tmp_path,
            audio_retention_days=30,
            max_audio_seconds=180,
            max_audio_mb=1,
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
    monkeypatch.setattr("app.api.v1.trainings.get_settings", test_settings)

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


async def test_attempt_upload_is_idempotent_and_private(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    first_user_id = await _create_user(
        db_maker,
        nickname="first",
        password="first-password",
        role="USER",
    )
    await _create_user(db_maker, nickname="second", password="second-password", role="USER")
    first_tokens = await _login(client, "first", "first-password")
    second_tokens = await _login(client, "second", "second-password")

    async with db_maker() as session:
        training_session = await seed_exposed_training_session(session, user_id=first_user_id)
        session_id = str(training_session.id)
        await session.commit()

    first_attempt = await client.post(
        f"/api/v1/trainings/{session_id}/attempts",
        headers=_auth_headers(first_tokens),
        json={"stage": "FIRST", "round": 1},
    )
    assert first_attempt.status_code == 201
    repeated_attempt = await client.post(
        f"/api/v1/trainings/{session_id}/attempts",
        headers=_auth_headers(first_tokens),
        json={"stage": "FIRST", "round": 1},
    )
    assert repeated_attempt.status_code == 201
    assert repeated_attempt.json()["id"] == first_attempt.json()["id"]
    attempt_id = first_attempt.json()["id"]

    audio_bytes = b"fake-webm-audio"
    checksum = hashlib.sha256(audio_bytes).hexdigest()
    uploaded = await _upload_audio(
        client,
        access_token=first_tokens,
        attempt_id=attempt_id,
        audio_bytes=audio_bytes,
        checksum=checksum,
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["upload_status"] == "UPLOADED"
    assert uploaded.json()["checksum_sha256"] == checksum

    same_upload = await _upload_audio(
        client,
        access_token=first_tokens,
        attempt_id=attempt_id,
        audio_bytes=audio_bytes,
        checksum=checksum,
    )
    assert same_upload.status_code == 200

    overwrite = await _upload_audio(
        client,
        access_token=first_tokens,
        attempt_id=attempt_id,
        audio_bytes=b"different-audio",
        checksum=hashlib.sha256(b"different-audio").hexdigest(),
    )
    assert overwrite.status_code == 409

    playback = await client.get(
        f"/api/v1/attempts/{attempt_id}/audio",
        headers=_auth_headers(first_tokens),
    )
    assert playback.status_code == 200
    assert playback.headers["cache-control"] == "no-store"
    assert playback.content == audio_bytes
    assert "http://" not in uploaded.text
    assert "https://" not in uploaded.text

    other_user_playback = await client.get(
        f"/api/v1/attempts/{attempt_id}/audio",
        headers=_auth_headers(second_tokens),
    )
    assert other_user_playback.status_code == 404


async def test_concurrent_upload_cannot_overwrite_first_answer(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _create_user(db_maker, nickname="race", password="race-password", role="USER")
    access_token = await _login(client, "race", "race-password")
    async with db_maker() as session:
        training_session = await seed_exposed_training_session(session, user_id=user_id)
        session_id = str(training_session.id)
        await session.commit()

    attempt = await client.post(
        f"/api/v1/trainings/{session_id}/attempts",
        headers=_auth_headers(access_token),
        json={"stage": "FIRST", "round": 1},
    )
    attempt_id = attempt.json()["id"]

    first_entered_save = asyncio.Event()
    release_first_save = asyncio.Event()
    save_calls = 0

    async def delayed_save_audio_upload(
        *,
        audio_root: Path,
        upload: UploadFile,
        user_id: UUID,
        session_id: UUID,
        attempt_id: UUID,
        expected_checksum: str,
        max_bytes: int,
    ) -> StoredAudio:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            first_entered_save.set()
            await release_first_save.wait()
        return await real_save_audio_upload(
            audio_root=audio_root,
            upload=upload,
            user_id=user_id,
            session_id=session_id,
            attempt_id=attempt_id,
            expected_checksum=expected_checksum,
            max_bytes=max_bytes,
        )

    monkeypatch.setattr(trainings_api, "save_audio_upload", delayed_save_audio_upload)

    first_audio = b"first-webm-audio"
    second_audio = b"second-webm-audio"
    first_task = asyncio.create_task(
        _upload_audio(
            client,
            access_token=access_token,
            attempt_id=attempt_id,
            audio_bytes=first_audio,
            checksum=hashlib.sha256(first_audio).hexdigest(),
        )
    )
    await asyncio.wait_for(first_entered_save.wait(), timeout=2)
    second_task = asyncio.create_task(
        _upload_audio(
            client,
            access_token=access_token,
            attempt_id=attempt_id,
            audio_bytes=second_audio,
            checksum=hashlib.sha256(second_audio).hexdigest(),
        )
    )
    await asyncio.sleep(0.05)
    release_first_save.set()

    first_response, second_response = await asyncio.gather(first_task, second_task)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert save_calls == 1
    playback = await client.get(
        f"/api/v1/attempts/{attempt_id}/audio",
        headers=_auth_headers(access_token),
    )
    assert playback.content == first_audio


async def test_upload_validation_does_not_consume_attempt(
    client: AsyncClient,
    db_maker: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _create_user(db_maker, nickname="user", password="user-password", role="USER")
    access_token = await _login(client, "user", "user-password")
    async with db_maker() as session:
        training_session = await seed_exposed_training_session(session, user_id=user_id)
        session_id = str(training_session.id)
        await session.commit()

    attempt = await client.post(
        f"/api/v1/trainings/{session_id}/attempts",
        headers=_auth_headers(access_token),
        json={"stage": "FIRST", "round": 1},
    )
    attempt_id = attempt.json()["id"]

    response = await client.put(
        f"/api/v1/attempts/{attempt_id}/audio",
        headers=_auth_headers(access_token),
        data={"duration_ms": "1000", "checksum_sha256": hashlib.sha256(b"nope").hexdigest()},
        files={"audio": ("answer.txt", b"nope", "text/plain")},
    )

    assert response.status_code == 400
    async with db_maker() as session:
        result = await session.execute(
            select(VoiceAttempt).where(VoiceAttempt.id == UUID(attempt_id))
        )
        stored_attempt = result.scalar_one()
        assert stored_attempt.upload_status == "PENDING"
        assert stored_attempt.audio_path is None


async def _create_user(
    maker: async_sessionmaker[AsyncSession],
    *,
    nickname: str,
    password: str,
    role: str,
) -> UUID:
    async with maker() as session:
        user = await UserRepository(session).create_user(
            nickname=nickname,
            password_hash=hash_password(password),
            role=role,
        )
        await session.commit()
        return user.id


async def _login(client: AsyncClient, nickname: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"nickname": nickname, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


async def _upload_audio(
    client: AsyncClient,
    *,
    access_token: str,
    attempt_id: str,
    audio_bytes: bytes,
    checksum: str,
) -> Response:
    return await client.put(
        f"/api/v1/attempts/{attempt_id}/audio",
        headers=_auth_headers(access_token),
        data={"duration_ms": "1200", "checksum_sha256": checksum},
        files={"audio": ("answer.webm", audio_bytes, "audio/webm")},
    )


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _assert_test_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(f"Refusing to reset non-test database: {database_name}")
