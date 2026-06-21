from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.v1 import health as health_module
from app.core.config import Settings, get_settings
from app.main import create_app


def test_health_returns_all_p00_checks(monkeypatch, tmp_path: Path) -> None:
    async def database_ok() -> None:
        return None

    def test_settings() -> Settings:
        return Settings(
            _env_file=None,
            audio_root=tmp_path,
            database_url="postgresql+asyncpg://example",
        )

    monkeypatch.setattr(health_module, "check_database", database_ok)
    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", test_settings)
    monkeypatch.setattr(health_module, "get_settings", test_settings)

    client = TestClient(create_app())
    response = client.get("/api/v1/health", headers={"X-Request-ID": "req-test"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test"
    body = response.json()
    assert body["status"] == "ok"
    assert body["request_id"] == "req-test"
    assert set(body["checks"]) == {"app", "database", "audio_root"}
    assert body["checks"]["database"]["ok"] is True


def test_health_degrades_when_audio_root_is_missing(monkeypatch, tmp_path: Path) -> None:
    async def database_ok() -> None:
        return None

    missing_audio_root = tmp_path / "missing"

    def test_settings() -> Settings:
        return Settings(
            _env_file=None,
            audio_root=missing_audio_root,
            database_url="postgresql+asyncpg://example",
        )

    monkeypatch.setattr(health_module, "check_database", database_ok)
    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", test_settings)
    monkeypatch.setattr(health_module, "get_settings", test_settings)

    client = TestClient(create_app())
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["audio_root"]["ok"] is False


def test_unhandled_errors_keep_request_id_header() -> None:
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    app = create_app()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom", headers={"X-Request-ID": "req-error"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-error"
    assert response.json()["error"]["request_id"] == "req-error"


def test_framework_http_errors_use_unified_error_envelope() -> None:
    client = TestClient(create_app())

    response = client.get("/missing", headers={"X-Request-ID": "req-missing"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req-missing"
    body = response.json()
    assert body["error"]["code"] == "HTTP_ERROR"
    assert body["error"]["message"] == "Not Found"
    assert body["error"]["request_id"] == "req-missing"


def test_framework_http_errors_preserve_protocol_headers() -> None:
    client = TestClient(create_app())

    response = client.post("/api/v1/health", headers={"X-Request-ID": "req-method"})

    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.headers["X-Request-ID"] == "req-method"
    assert response.json()["error"]["code"] == "HTTP_ERROR"


def test_validation_errors_do_not_echo_raw_inputs() -> None:
    class LoginRequest(BaseModel):
        password: int

    router = APIRouter()

    @router.post("/login")
    def login(payload: LoginRequest) -> dict[str, bool]:
        return {"ok": bool(payload)}

    app = create_app()
    app.include_router(router)
    client = TestClient(app)

    response = client.post("/login", json={"password": "supersecret"})

    assert response.status_code == 422
    body_text = response.text
    assert "supersecret" not in body_text
    assert response.json()["error"]["message"] == "Request validation failed"
