from __future__ import annotations

from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

_FAKE_IP_DNS_NETWORK = ip_network("198.18.0.0/15")


def validate_push_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValueError("WEB_PUSH_ENDPOINT_INVALID_SCHEME")
    if parsed.username or parsed.password:
        raise ValueError("WEB_PUSH_ENDPOINT_USERINFO_FORBIDDEN")
    try:
        host = parsed.hostname
    except ValueError as exc:
        raise ValueError("WEB_PUSH_ENDPOINT_INVALID_HOST") from exc
    if host is None or not host.strip():
        raise ValueError("WEB_PUSH_ENDPOINT_INVALID_HOST")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("WEB_PUSH_ENDPOINT_INVALID_PORT") from exc
    if port not in {None, 443}:
        raise ValueError("WEB_PUSH_ENDPOINT_PORT_FORBIDDEN")

    normalized_host = host.lower().rstrip(".")
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError("WEB_PUSH_ENDPOINT_LOCAL_HOST_FORBIDDEN")
    if normalized_host.endswith(".local"):
        raise ValueError("WEB_PUSH_ENDPOINT_LOCAL_HOST_FORBIDDEN")

    try:
        parsed_ip = ip_address(normalized_host)
    except ValueError:
        return value

    if is_blocked_push_ip_address(str(parsed_ip)):
        raise ValueError("WEB_PUSH_ENDPOINT_PRIVATE_IP_FORBIDDEN")
    return value


def is_blocked_push_ip_address(address: str) -> bool:
    parsed_ip = ip_address(address)
    return (
        parsed_ip.is_private
        or parsed_ip.is_loopback
        or parsed_ip.is_link_local
        or parsed_ip.is_multicast
        or parsed_ip.is_reserved
        or parsed_ip.is_unspecified
    )


def is_fake_ip_dns_address(address: str) -> bool:
    return ip_address(address) in _FAKE_IP_DNS_NETWORK
