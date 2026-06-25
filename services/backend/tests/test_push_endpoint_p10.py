from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from pywebpush import Vapid01

from app.core.config import Settings
from app.db.models import PushSubscription
from app.domain.push import is_fake_ip_dns_address, validate_push_endpoint
from app.schemas.push import PushSubscriptionRequest
from app.services.push import PyWebPushSender


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://push.example/subscription/1",
        "https://localhost/subscription/1",
        "https://push.local/subscription/1",
        "https://127.0.0.1/subscription/1",
        "https://10.0.0.2/subscription/1",
        "https://[::1]/subscription/1",
        "https://user:pass@push.example/subscription/1",
        "https://push.example:8443/subscription/1",
    ],
)
def test_push_subscription_request_rejects_unsafe_endpoint(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        PushSubscriptionRequest(
            endpoint=endpoint,
            keys={"p256dh": "p256dh-key", "auth": "auth-key"},
        )


def test_validate_push_endpoint_accepts_https_public_hostname() -> None:
    assert (
        validate_push_endpoint(" https://push.example/subscription/1 ")
        == "https://push.example/subscription/1"
    )


def test_fake_ip_dns_address_detection_is_limited_to_benchmark_range() -> None:
    assert is_fake_ip_dns_address("198.18.6.15") is True
    assert is_fake_ip_dns_address("127.0.0.1") is False
    assert is_fake_ip_dns_address("10.0.0.2") is False
    assert is_fake_ip_dns_address("93.184.216.34") is False


@pytest.mark.asyncio
async def test_pywebpush_sender_blocks_invalid_stored_endpoint(tmp_path: Path) -> None:
    sender = PyWebPushSender(_test_settings(tmp_path))
    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://127.0.0.1/subscription/1",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is False
    assert result.error_code == "WEB_PUSH_ENDPOINT_BLOCKED"
    assert result.deactivate is True


@pytest.mark.asyncio
async def test_pywebpush_sender_blocks_endpoint_resolving_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    def fail_webpush(*args: object, **kwargs: object) -> None:
        raise AssertionError("webpush must not be called for private DNS results")

    monkeypatch.setattr("app.services.push.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.services.push.webpush", fail_webpush)
    sender = PyWebPushSender(_test_settings(tmp_path))

    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://push.example/subscription/1",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is False
    assert result.error_code == "WEB_PUSH_ENDPOINT_BLOCKED"
    assert result.deactivate is True


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["198.18.6.15", "127.0.0.1"])
async def test_pywebpush_sender_blocks_endpoint_resolving_to_blocked_ip_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    address: str,
) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    def fail_webpush(*args: object, **kwargs: object) -> None:
        raise AssertionError("webpush must not be called for blocked DNS results")

    monkeypatch.setattr("app.services.push.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.services.push.webpush", fail_webpush)
    sender = PyWebPushSender(_test_settings(tmp_path))

    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://fcm.googleapis.com/fcm/send/test",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is False
    assert result.error_code == "WEB_PUSH_ENDPOINT_BLOCKED"
    assert result.deactivate is True


@pytest.mark.asyncio
async def test_pywebpush_sender_allows_configured_fake_ip_dns_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.6.15", 443))]

    def fake_webpush(*args: object, **kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr("app.services.push.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.services.push.webpush", fake_webpush)
    sender = PyWebPushSender(
        _test_settings(tmp_path, web_push_allow_fake_ip_hosts="FCM.GOOGLEAPIS.COM")
    )

    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://fcm.googleapis.com/fcm/send/test",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is True
    assert calls[0]["subscription_info"] == {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test",
        "keys": {
            "p256dh": "p256dh-key",
            "auth": "auth-key",
        },
    }


@pytest.mark.asyncio
async def test_pywebpush_sender_still_blocks_non_fake_private_ip_for_allowlisted_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    def fail_webpush(*args: object, **kwargs: object) -> None:
        raise AssertionError("webpush must not be called for non-fake private DNS results")

    monkeypatch.setattr("app.services.push.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.services.push.webpush", fail_webpush)
    sender = PyWebPushSender(
        _test_settings(tmp_path, web_push_allow_fake_ip_hosts="fcm.googleapis.com")
    )

    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://fcm.googleapis.com/fcm/send/test",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is False
    assert result.error_code == "WEB_PUSH_ENDPOINT_BLOCKED"
    assert result.deactivate is True


@pytest.mark.asyncio
async def test_pywebpush_sender_uses_public_resolved_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def fake_webpush(*args: object, **kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr("app.services.push.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.services.push.webpush", fake_webpush)
    sender = PyWebPushSender(_test_settings(tmp_path))

    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://push.example/subscription/1",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is True
    assert calls[0]["subscription_info"] == {
        "endpoint": "https://push.example/subscription/1",
        "keys": {
            "p256dh": "p256dh-key",
            "auth": "auth-key",
        },
    }
    assert calls[0]["vapid_private_key"] == "test-vapid-private"


@pytest.mark.asyncio
async def test_pywebpush_sender_converts_pem_vapid_private_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    vapid = Vapid01()
    vapid.generate_keys()

    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def fake_webpush(*args: object, **kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr("app.services.push.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.services.push.webpush", fake_webpush)
    sender = PyWebPushSender(
        _test_settings(
            tmp_path,
            web_push_vapid_private_key=SecretStr(vapid.private_pem().decode("utf-8")),
        )
    )

    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://push.example/subscription/1",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is True
    assert isinstance(calls[0]["vapid_private_key"], Vapid01)


@pytest.mark.asyncio
async def test_pywebpush_sender_fails_closed_when_pywebpush_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def fail_webpush(*args: object, **kwargs: object) -> None:
        raise ValueError("invalid vapid key")

    monkeypatch.setattr("app.services.push.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.services.push.webpush", fail_webpush)
    sender = PyWebPushSender(_test_settings(tmp_path))

    result = await sender.send(
        subscription=PushSubscription(
            endpoint="https://push.example/subscription/1",
            p256dh="p256dh-key",
            auth="auth-key",
            user_agent="test",
        ),
        payload={"title": "突击审核已到达"},
    )

    assert result.delivered is False
    assert result.error_code == "WEB_PUSH_FAILED"
    assert result.deactivate is False


def _test_settings(
    tmp_path: Path,
    *,
    web_push_vapid_private_key: SecretStr | None = None,
    web_push_allow_fake_ip_hosts: str = "",
) -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="mock",
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
        web_push_vapid_public_key="test-vapid-public",
        web_push_vapid_private_key=web_push_vapid_private_key or SecretStr("test-vapid-private"),
        web_push_allow_fake_ip_hosts=web_push_allow_fake_ip_hosts,
        audio_root=tmp_path,
    )
