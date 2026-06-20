from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.health import router as health_router
from app.core.errors import install_exception_handlers
from app.core.request_id import request_id_middleware
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="Thinking Coach API", version="1.0.0", lifespan=lifespan)
    app.middleware("http")(request_id_middleware)
    install_exception_handlers(app)
    app.include_router(health_router)
    return app


app = create_app()
