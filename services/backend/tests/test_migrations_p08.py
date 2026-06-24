from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

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


def test_p08_migration_upgrade_downgrade_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_DATABASE_SYNC_URL is not None
    _assert_test_database(TEST_DATABASE_SYNC_URL)
    _reset_schema(TEST_DATABASE_SYNC_URL)

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    monkeypatch.setenv("DATABASE_SYNC_URL", TEST_DATABASE_SYNC_URL)
    get_settings.cache_clear()
    command.upgrade(config, "0006_defect_memory")
    legacy_session_id = _seed_legacy_question_session(TEST_DATABASE_SYNC_URL)

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "source_bundle")
    assert _has_table(TEST_DATABASE_SYNC_URL, "question")
    assert _has_table(TEST_DATABASE_SYNC_URL, "question_claim_map")
    assert _training_session_question_id(TEST_DATABASE_SYNC_URL, legacy_session_id) is None
    assert _unique_constraint_columns(
        TEST_DATABASE_SYNC_URL,
        "question_rubric",
        "uq_question_rubric_question_version",
    ) == ["question_id", "version"]
    assert _foreign_key_target(
        TEST_DATABASE_SYNC_URL,
        "training_session",
        "fk_training_session_question_id_question",
    ) == ("question", ["question_id"], ["id"])

    command.downgrade(config, "0006_defect_memory")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "question")
    assert not _has_table(TEST_DATABASE_SYNC_URL, "source_bundle")
    assert _has_table(TEST_DATABASE_SYNC_URL, "question_rubric")

    command.upgrade(config, "head")
    assert _has_table(TEST_DATABASE_SYNC_URL, "source_claim")
    assert _foreign_key_target(
        TEST_DATABASE_SYNC_URL,
        "question_rubric",
        "fk_question_rubric_question_id_question",
    ) == ("question", ["question_id"], ["id"])
    get_settings.cache_clear()


def _has_table(database_url: str, table_name: str) -> bool:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            return table_name in inspector.get_table_names()
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


def _foreign_key_target(
    database_url: str,
    table_name: str,
    constraint_name: str,
) -> tuple[str, list[str], list[str]]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            for constraint in inspector.get_foreign_keys(table_name):
                if constraint["name"] == constraint_name:
                    return (
                        str(constraint["referred_table"]),
                        list(constraint["constrained_columns"]),
                        list(constraint["referred_columns"]),
                    )
    finally:
        engine.dispose()
    raise AssertionError(f"Foreign key not found: {constraint_name}")


def _seed_legacy_question_session(database_url: str) -> UUID:
    user_id = uuid4()
    session_id = uuid4()
    question_id = uuid4()
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO app_user (id, nickname, password_hash, role, status) "
                    "VALUES (:id, :nickname, :password_hash, 'USER', 'ACTIVE')"
                ),
                {
                    "id": user_id,
                    "nickname": f"legacy-{user_id.hex[:8]}",
                    "password_hash": "fake-password-hash",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO training_session "
                    "(id, user_id, question_id, thread_id, stage) "
                    "VALUES (:id, :user_id, :question_id, :thread_id, 'COMPLETED')"
                ),
                {
                    "id": session_id,
                    "user_id": user_id,
                    "question_id": question_id,
                    "thread_id": f"legacy-{session_id.hex[:8]}",
                },
            )
    finally:
        engine.dispose()
    return session_id


def _training_session_question_id(database_url: str, session_id: UUID) -> UUID | None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            value = connection.execute(
                text("SELECT question_id FROM training_session WHERE id = :id"),
                {"id": session_id},
            ).scalar_one()
            return value if isinstance(value, UUID) else None
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
