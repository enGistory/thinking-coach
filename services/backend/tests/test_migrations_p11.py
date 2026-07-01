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


def test_p11_migration_upgrade_downgrade_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_DATABASE_SYNC_URL is not None
    _assert_test_database(TEST_DATABASE_SYNC_URL)
    _reset_schema(TEST_DATABASE_SYNC_URL)

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    monkeypatch.setenv("DATABASE_SYNC_URL", TEST_DATABASE_SYNC_URL)
    get_settings.cache_clear()
    command.upgrade(config, "0009_random_strike")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "weekly_report")
    assert "target_json" not in _column_names(TEST_DATABASE_SYNC_URL, "appeal")

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "weekly_report")
    assert _has_table(TEST_DATABASE_SYNC_URL, "privacy_deletion_request")
    assert _has_table(TEST_DATABASE_SYNC_URL, "privacy_audit_event")
    assert "target_json" in _column_names(TEST_DATABASE_SYNC_URL, "appeal")
    assert _unique_constraint_columns(
        TEST_DATABASE_SYNC_URL,
        "weekly_report",
        "uq_weekly_report_user_week",
    ) == ["user_id", "week_start"]
    appeal_type = _check_constraint_definition(
        TEST_DATABASE_SYNC_URL,
        "appeal",
        "ck_appeal_type",
    )
    assert "transcript" in appeal_type
    assert "source" in appeal_type

    command.downgrade(config, "0009_random_strike")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "weekly_report")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "privacy_deletion_request")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "privacy_audit_event")
    assert "target_json" not in _column_names(TEST_DATABASE_SYNC_URL, "appeal")
    old_appeal_type = _check_constraint_definition(
        TEST_DATABASE_SYNC_URL,
        "appeal",
        "ck_appeal_type",
    )
    assert "transcript" not in old_appeal_type
    assert "source" not in old_appeal_type

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "weekly_report")
    get_settings.cache_clear()


def _has_table(database_url: str, table_name: str) -> bool:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            return table_name in inspector.get_table_names()
    finally:
        engine.dispose()


def _column_names(database_url: str, table_name: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            return {str(column["name"]) for column in inspector.get_columns(table_name)}
    finally:
        engine.dispose()


def _unique_constraint_columns(
    database_url: str,
    table_name: str,
    constraint_name: str,
) -> list[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            for constraint in inspector.get_unique_constraints(table_name):
                if constraint["name"] == constraint_name:
                    return list(constraint["column_names"])
    finally:
        engine.dispose()
    raise AssertionError(f"Unique constraint not found: {constraint_name}")


def _check_constraint_definition(
    database_url: str,
    table_name: str,
    constraint_name: str,
) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) "
                    "FROM pg_constraint "
                    "WHERE conrelid = to_regclass(:table_name) "
                    "AND conname = :constraint_name"
                ),
                {"table_name": table_name, "constraint_name": constraint_name},
            )
            constraint = result.scalar_one_or_none()
            if constraint is None:
                raise AssertionError(f"Check constraint not found: {constraint_name}")
            return str(constraint)
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
