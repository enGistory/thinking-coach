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


def test_p09_migration_upgrade_downgrade_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_DATABASE_SYNC_URL is not None
    _assert_test_database(TEST_DATABASE_SYNC_URL)
    _reset_schema(TEST_DATABASE_SYNC_URL)

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    monkeypatch.setenv("DATABASE_SYNC_URL", TEST_DATABASE_SYNC_URL)
    get_settings.cache_clear()
    command.upgrade(config, "0007_source_question")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "question_dedupe_check")
    assert "prompt_embedding" not in _column_names(TEST_DATABASE_SYNC_URL, "question_fingerprint")
    assert _has_unique_constraint(
        TEST_DATABASE_SYNC_URL,
        "question_fingerprint",
        "uq_question_fingerprint_normalized_hash",
    )

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "question_dedupe_check")
    assert _has_table(TEST_DATABASE_SYNC_URL, "question_template_denylist")
    assert _has_table(TEST_DATABASE_SYNC_URL, "question_duplicate_complaint")
    assert {
        "prompt_embedding",
        "summary_embedding",
        "decision_embedding",
        "answer_skeleton_hash",
        "dedupe_decision_json",
    }.issubset(_column_names(TEST_DATABASE_SYNC_URL, "question_fingerprint"))
    assert not _has_unique_constraint(
        TEST_DATABASE_SYNC_URL,
        "question_fingerprint",
        "uq_question_fingerprint_normalized_hash",
    )
    assert _unique_constraint_columns(
        TEST_DATABASE_SYNC_URL,
        "question_template_denylist",
        "uq_question_template_deny_user_family",
    ) == ["user_id", "template_family"]
    assert _unique_constraint_columns(
        TEST_DATABASE_SYNC_URL,
        "question_duplicate_complaint",
        "uq_question_duplicate_complaint_session",
    ) == ["user_id", "session_id"]

    command.downgrade(config, "0007_source_question")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "question_dedupe_check")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "question_template_denylist")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "question_duplicate_complaint")
    assert "prompt_embedding" not in _column_names(TEST_DATABASE_SYNC_URL, "question_fingerprint")
    assert _has_unique_constraint(
        TEST_DATABASE_SYNC_URL,
        "question_fingerprint",
        "uq_question_fingerprint_normalized_hash",
    )

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "question_duplicate_complaint")
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


def _has_unique_constraint(
    database_url: str,
    table_name: str,
    constraint_name: str,
) -> bool:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            return any(
                constraint["name"] == constraint_name
                for constraint in inspector.get_unique_constraints(table_name)
            )
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
