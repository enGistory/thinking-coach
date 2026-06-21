from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import ConfigurationError, Settings

_ACCESS_TOKEN_TYPE = "access"
_JWT_ALGORITHM = "HS256"
_password_hash = PasswordHash.recommended()


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    role: str


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return bool(_password_hash.verify(password, password_hash))


def generate_refresh_token() -> str:
    from secrets import token_urlsafe

    return token_urlsafe(48)


def hash_secret(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def create_access_token(user_id: UUID, role: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.jwt_access_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "token_type": _ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(settings), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    try:
        payload = jwt.decode(token, _jwt_secret(settings), algorithms=[_JWT_ALGORITHM])
    except InvalidTokenError as exc:
        raise TokenError("Invalid access token") from exc

    if payload.get("token_type") != _ACCESS_TOKEN_TYPE:
        raise TokenError("Invalid token type")
    subject = payload.get("sub")
    role = payload.get("role")
    if not isinstance(subject, str) or not isinstance(role, str):
        raise TokenError("Invalid token claims")
    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise TokenError("Invalid token subject") from exc
    return AccessTokenClaims(user_id=user_id, role=role)


def _jwt_secret(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise ConfigurationError("JWT_SECRET_MISSING", "JWT_SECRET must be configured")
    secret = settings.jwt_secret.get_secret_value().strip()
    if not secret:
        raise ConfigurationError("JWT_SECRET_MISSING", "JWT_SECRET must be configured")
    return secret
