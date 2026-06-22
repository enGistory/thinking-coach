from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import get_settings

TEST_DATABASE_SYNC_URL = os.getenv("TEST_DATABASE_SYNC_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_SYNC_URL is None,
    reason="TEST_DATABASE_SYNC_URL is required for Alembic migration tests",
)


def test_p03_migration_upgrade_downgrade_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_DATABASE_SYNC_URL is not None
    _assert_test_database(TEST_DATABASE_SYNC_URL)
    _reset_schema(TEST_DATABASE_SYNC_URL)

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    monkeypatch.setenv("DATABASE_SYNC_URL", TEST_DATABASE_SYNC_URL)
    get_settings.cache_clear()
    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "training_session")
    assert _has_table(TEST_DATABASE_SYNC_URL, "voice_attempt")

    command.downgrade(config, "0002_database_auth")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "training_session")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "voice_attempt")

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "training_session")
    assert _has_table(TEST_DATABASE_SYNC_URL, "voice_attempt")
    get_settings.cache_clear()


def _has_table(database_url: str, table_name: str) -> bool:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            return table_name in inspector.get_table_names()
    finally:
        engine.dispose()


def _reset_schema(database_url: str) -> None:
    engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.execute(text("GRANT ALL ON SCHEMA public TO public"))
    finally:
        engine.dispose()


def _assert_test_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(f"Refusing to reset non-test database: {database_name}")
