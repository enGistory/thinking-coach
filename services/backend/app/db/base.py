from __future__ import annotations

from sqlalchemy import DDL, event
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


vector_extension = DDL("CREATE EXTENSION IF NOT EXISTS vector")  # type: ignore[no-untyped-call]

event.listen(
    Base.metadata,
    "before_create",
    vector_extension.execute_if(dialect="postgresql"),
)
