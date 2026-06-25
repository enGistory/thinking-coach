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


def test_p10_migration_upgrade_downgrade_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_DATABASE_SYNC_URL is not None
    _assert_test_database(TEST_DATABASE_SYNC_URL)
    _reset_schema(TEST_DATABASE_SYNC_URL)

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    monkeypatch.setenv("DATABASE_SYNC_URL", TEST_DATABASE_SYNC_URL)
    get_settings.cache_clear()
    command.upgrade(config, "0008_never_repeat")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "push_subscription")
    assert "notified_at" not in _column_names(TEST_DATABASE_SYNC_URL, "training_session")

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "push_subscription")
    assert _unique_constraint_columns(
        TEST_DATABASE_SYNC_URL,
        "push_subscription",
        "uq_push_subscription_endpoint",
    ) == ["endpoint"]
    assert _index_columns(
        TEST_DATABASE_SYNC_URL,
        "push_subscription",
        "ix_push_subscription_user_active",
    ) == ["user_id", "active"]
    assert {
        "notified_at",
        "notification_expires_at",
        "accepted_at",
        "delivery_decision_json",
        "deferred_count",
        "push_status",
        "push_error_code",
    }.issubset(_column_names(TEST_DATABASE_SYNC_URL, "training_session"))
    assert _index_columns(
        TEST_DATABASE_SYNC_URL,
        "training_session",
        "ix_training_session_stage_scheduled",
    ) == ["stage", "scheduled_at"]
    active_index = _index(
        TEST_DATABASE_SYNC_URL,
        "training_session",
        "uq_training_session_user_active",
    )
    assert active_index["unique"] is True
    assert active_index["column_names"] == ["user_id"]
    active_index_definition = _index_definition(
        TEST_DATABASE_SYNC_URL,
        "training_session",
        "uq_training_session_user_active",
    )
    assert "UNIQUE INDEX" in active_index_definition
    assert "WHERE" in active_index_definition
    assert "FAILED_RETRYABLE" in active_index_definition
    assert _index_columns(
        TEST_DATABASE_SYNC_URL,
        "training_session",
        "ix_training_session_notification_expires",
    ) == ["stage", "notification_expires_at"]

    command.downgrade(config, "0008_never_repeat")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "push_subscription")
    assert "notified_at" not in _column_names(TEST_DATABASE_SYNC_URL, "training_session")

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "push_subscription")
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


def _index_columns(
    database_url: str,
    table_name: str,
    index_name: str,
) -> list[str]:
    return list(_index(database_url, table_name, index_name)["column_names"])


def _index(
    database_url: str,
    table_name: str,
    index_name: str,
) -> dict[str, object]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            for index in inspector.get_indexes(table_name):
                if index["name"] == index_name:
                    return dict(index)
    finally:
        engine.dispose()
    raise AssertionError(f"Index not found: {index_name}")


def _index_definition(
    database_url: str,
    table_name: str,
    index_name: str,
) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' "
                    "AND tablename = :table_name "
                    "AND indexname = :index_name"
                ),
                {"table_name": table_name, "index_name": index_name},
            )
            indexdef = result.scalar_one_or_none()
            if indexdef is None:
                raise AssertionError(f"Index definition not found: {index_name}")
            return str(indexdef)
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
