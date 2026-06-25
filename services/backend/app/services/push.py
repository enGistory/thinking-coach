from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from pywebpush import Vapid01, WebPushException, webpush

from app.core.config import Settings
from app.db.models import PushSubscription
from app.domain.push import (
    is_blocked_push_ip_address,
    is_fake_ip_dns_address,
    validate_push_endpoint,
)


@dataclass(frozen=True)
class PushDeliveryResult:
    delivered: bool
    error_code: str | None = None
    deactivate: bool = False


class WebPushSender(Protocol):
    async def send(
        self,
        *,
        subscription: PushSubscription,
        payload: dict[str, object],
    ) -> PushDeliveryResult: ...


class PyWebPushSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(
        self,
        *,
        subscription: PushSubscription,
        payload: dict[str, object],
    ) -> PushDeliveryResult:
        try:
            endpoint = validate_push_endpoint(subscription.endpoint)
        except ValueError:
            return PushDeliveryResult(
                delivered=False,
                error_code="WEB_PUSH_ENDPOINT_BLOCKED",
                deactivate=True,
            )
        resolution_result = await _validate_resolved_endpoint_addresses(
            endpoint,
            allowed_fake_ip_hosts=self._settings.web_push_fake_ip_host_allowlist,
        )
        if resolution_result is not None:
            return resolution_result
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=_vapid_private_key_for_pywebpush(self._settings),
                vapid_claims={"sub": self._settings.app_base_url},
            )
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            deactivate = status_code in {404, 410}
            return PushDeliveryResult(
                delivered=False,
                error_code=f"WEB_PUSH_{status_code or 'FAILED'}",
                deactivate=deactivate,
            )
        except Exception:
            return PushDeliveryResult(
                delivered=False,
                error_code="WEB_PUSH_FAILED",
                deactivate=False,
            )
        return PushDeliveryResult(delivered=True)


def strike_notification_payload(*, session_id: str, web_base_url: str) -> dict[str, object]:
    return {
        "title": "突击审核已到达",
        "body": "预计用时约 3 分钟",
        "tag": f"strike:{session_id}",
        "url": f"{web_base_url.rstrip('/')}/?session={session_id}",
        "session_id": session_id,
    }


async def _validate_resolved_endpoint_addresses(
    endpoint: str,
    *,
    allowed_fake_ip_hosts: set[str] | None = None,
) -> PushDeliveryResult | None:
    parsed = urlparse(endpoint)
    host = parsed.hostname
    if host is None:
        return PushDeliveryResult(
            delivered=False,
            error_code="WEB_PUSH_ENDPOINT_BLOCKED",
            deactivate=True,
        )
    try:
        port = parsed.port or 443
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return PushDeliveryResult(
            delivered=False,
            error_code="WEB_PUSH_ENDPOINT_RESOLUTION_FAILED",
            deactivate=False,
        )
    addresses = {str(info[4][0]) for info in infos if info[4]}
    if not addresses:
        return PushDeliveryResult(
            delivered=False,
            error_code="WEB_PUSH_ENDPOINT_RESOLUTION_FAILED",
            deactivate=False,
        )
    blocked_addresses = {address for address in addresses if is_blocked_push_ip_address(address)}
    if blocked_addresses:
        normalized_host = host.lower().rstrip(".")
        allowed_hosts = allowed_fake_ip_hosts or set()
        if normalized_host in allowed_hosts and all(
            is_fake_ip_dns_address(address) for address in blocked_addresses
        ):
            return None
        return PushDeliveryResult(
            delivered=False,
            error_code="WEB_PUSH_ENDPOINT_BLOCKED",
            deactivate=True,
        )
    return None


def _vapid_private_key_for_pywebpush(settings: Settings) -> object:
    if settings.web_push_vapid_private_key is None:
        return ""
    value = settings.web_push_vapid_private_key.get_secret_value().strip()
    if value.startswith("-----BEGIN"):
        return Vapid01.from_pem(value.encode("utf-8"))
    return value
