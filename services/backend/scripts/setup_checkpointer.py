from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver

from app.core.config import get_settings


def _psycopg_conninfo(database_url: str) -> str:
    return (
        database_url.replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )


def main() -> None:
    settings = get_settings()
    conninfo = _psycopg_conninfo(settings.database_sync_url)
    with PostgresSaver.from_conn_string(conninfo) as checkpointer:
        checkpointer.setup()


if __name__ == "__main__":
    main()
