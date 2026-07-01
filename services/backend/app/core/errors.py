from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import REQUEST_ID_HEADER, get_request_id

_SENSITIVE_ERROR_DETAIL_KEY_PARTS = (
    "apikey",
    "accesskey",
    "authorization",
    "audio",
    "bocha",
    "cookie",
    "dashscope",
    "jwt",
    "password",
    "proof",
    "secret",
    "signature",
    "signedurl",
    "token",
    "vapid",
)


def error_payload(code: str, message: str, request: Request) -> dict[str, dict[str, object]]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(request),
        }
    }


def error_headers(request: Request, headers: Mapping[str, str] | None = None) -> dict[str, str]:
    merged = dict(headers or {})
    merged[REQUEST_ID_HEADER] = get_request_id(request)
    return merged


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        payload = _http_error_payload(request, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
            headers=error_headers(request, exc.headers),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_payload("VALIDATION_ERROR", "Request validation failed", request),
            headers=error_headers(request),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload("INTERNAL_ERROR", "Internal server error", request),
            headers=error_headers(request),
        )


def _http_error_payload(request: Request, detail: object) -> dict[str, dict[str, object]]:
    if isinstance(detail, Mapping):
        code = detail.get("code")
        message = detail.get("message") or code or "Request failed"
        payload = error_payload(
            str(code) if code else "HTTP_ERROR",
            str(message),
            request,
        )
        for key, value in detail.items():
            if (
                key not in {"code", "message"}
                and _is_safe_error_detail_key(str(key))
                and isinstance(value, str | int | float | bool)
            ):
                payload["error"][str(key)] = value
        return payload
    message = str(detail) if detail else "Request failed"
    return error_payload("HTTP_ERROR", message, request)


def _is_safe_error_detail_key(key: str) -> bool:
    normalized = "".join(char for char in key.lower() if char.isalnum())
    return not any(part in normalized for part in _SENSITIVE_ERROR_DETAIL_KEY_PARTS)
