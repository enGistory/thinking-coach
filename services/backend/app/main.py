from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.invitations import admin_router as admin_invitations_router
from app.api.v1.invitations import router as invitations_router
from app.api.v1.me import router as me_router
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.request_id import request_id_middleware
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_ai()
    settings.validate_auth()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="Thinking Coach API", version="1.0.0", lifespan=lifespan)
    app.middleware("http")(request_id_middleware)
    install_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(invitations_router)
    app.include_router(me_router)
    app.include_router(admin_router)
    app.include_router(admin_invitations_router)
    return app


app = create_app()
