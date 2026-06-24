from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from collections.abc import Iterable, Mapping, Sequence
from urllib.parse import urljoin, urlparse

import httpcore
import httpx
import pymupdf
import trafilatura

from app.ai.providers.contracts import (
    ContentFetchRequest,
    ContentFetchResponse,
    ProviderError,
    SearchRequest,
    SearchResult,
)
from app.core.config import Settings

BOCHA_PROVIDER_NAME = "bocha"
MAX_SOURCE_REDIRECTS = 5
MAX_SOURCE_BYTES = 10 * 1024 * 1024
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class BochaSearchProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def search(self, request: SearchRequest) -> Sequence[SearchResult]:
        if self.settings.bocha_api_key is None:
            raise ProviderError(
                "SEARCH_CONFIG_MISSING",
                "BOCHA_API_KEY is not configured",
                provider=BOCHA_PROVIDER_NAME,
            )
        try:
            response = await self._client_or_create().post(
                self.settings.bocha_search_endpoint,
                headers={
                    "Authorization": (f"Bearer {self.settings.bocha_api_key.get_secret_value()}"),
                    "Content-Type": "application/json",
                },
                json={
                    "query": request.query,
                    "summary": True,
                    "freshness": self.settings.bocha_freshness,
                    "count": self.settings.bocha_search_count,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"SEARCH_HTTP_{exc.response.status_code}",
                "Bocha search request failed",
                provider=BOCHA_PROVIDER_NAME,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "SEARCH_PROVIDER_ERROR",
                "Bocha search response was not usable",
                provider=BOCHA_PROVIDER_NAME,
            ) from exc
        return _bocha_results(payload)

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.llm_timeout_seconds,
                trust_env=False,
            )
        return self._client


class HttpContentFetcher:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def fetch(self, request: ContentFetchRequest) -> ContentFetchResponse:
        url = request.url
        raw: bytes | None = None
        final_url = ""
        content_type = ""
        charset_encoding: str | None = None
        try:
            for _ in range(MAX_SOURCE_REDIRECTS + 1):
                await _validate_public_source_url(url)
                async with self._client_or_create().stream(
                    "GET",
                    url,
                    follow_redirects=False,
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ProviderError(
                                "SOURCE_REDIRECT_INVALID",
                                "source redirect did not include a location",
                                provider="http",
                            )
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    content_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    )
                    charset_encoding = response.charset_encoding
                    raw = await _read_limited_response(response)
                    final_url = str(response.url)
                    break
            else:
                raise ProviderError(
                    "SOURCE_REDIRECT_TOO_DEEP",
                    "source URL redirected too many times",
                    provider="http",
                )
        except httpx.HTTPError as exc:
            raise ProviderError(
                "SOURCE_FETCH_FAILED",
                "source URL could not be fetched",
                provider="http",
            ) from exc
        if raw is None:
            raise RuntimeError("source fetch loop exited without content")
        if "pdf" in content_type or request.url.lower().split("?", 1)[0].endswith(".pdf"):
            text = _extract_pdf_text(raw)
            locator_prefix = "page"
            normalized_type = "application/pdf"
        else:
            html = raw.decode(charset_encoding or "utf-8", errors="replace")
            extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
            text = (extracted or "").strip()
            locator_prefix = "paragraph"
            normalized_type = content_type or "text/html"
        if not text:
            raise ProviderError(
                "SOURCE_TEXT_EMPTY",
                "source content extraction returned no text",
                provider="http",
            )
        return ContentFetchResponse(
            url=final_url,
            content_type=normalized_type,
            text=text,
            snapshot_hash=hashlib.sha256(raw).hexdigest(),
            locator_prefix=locator_prefix,
        )

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=_public_source_transport(),
                timeout=self.settings.llm_timeout_seconds,
                trust_env=False,
                headers={"User-Agent": f"{self.settings.app_name}/source-fetcher"},
            )
        return self._client


def _bocha_results(payload: object) -> list[SearchResult]:
    if not isinstance(payload, Mapping):
        raise ProviderError(
            "SEARCH_OUTPUT_INVALID",
            "Bocha search payload was not an object",
            provider=BOCHA_PROVIDER_NAME,
        )
    data = payload.get("data")
    search_payload: Mapping[object, object] = data if isinstance(data, Mapping) else payload
    web_pages = search_payload.get("webPages")
    values = web_pages.get("value") if isinstance(web_pages, Mapping) else None
    if not isinstance(values, Sequence):
        return []
    results: list[SearchResult] = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        url = _string_value(item.get("url"))
        title = _string_value(item.get("name"))
        if not url or not title:
            continue
        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=_string_value(item.get("summary")) or _string_value(item.get("snippet")),
                source=_string_value(item.get("siteName")) or None,
                published_at=_string_value(item.get("datePublished")) or None,
            )
        )
    return results


class _PublicSourceNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, delegate: httpcore.AsyncNetworkBackend) -> None:
        self._delegate = delegate

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore protocol keyword.
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await _public_host_addresses(host, port)
        last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for address in addresses:
            try:
                return await self._delegate.connect_tcp(
                    str(address),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("validated source host did not include any addresses")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore protocol keyword.
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._delegate.connect_unix_socket(
            path,
            timeout=timeout,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


def _public_source_transport() -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    pool = transport._pool
    delegate = pool._network_backend
    pool._network_backend = _PublicSourceNetworkBackend(delegate)
    return transport


async def _read_limited_response(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = 0
        if declared_size > MAX_SOURCE_BYTES:
            raise ProviderError(
                "SOURCE_CONTENT_TOO_LARGE",
                "source content exceeded the maximum allowed size",
                provider="http",
            )

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_SOURCE_BYTES:
            raise ProviderError(
                "SOURCE_CONTENT_TOO_LARGE",
                "source content exceeded the maximum allowed size",
                provider="http",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_pdf_text(raw: bytes) -> str:
    try:
        with pymupdf.open(stream=raw, filetype="pdf") as document:  # type: ignore[no-untyped-call]
            pages = [page.get_text("text").strip() for page in document]
    except Exception as exc:
        raise ProviderError(
            "SOURCE_PDF_PARSE_FAILED",
            "PDF source could not be parsed",
            provider="pymupdf",
        ) from exc
    return "\n\n".join(page for page in pages if page)


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


async def _validate_public_source_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ProviderError(
            "SOURCE_URL_BLOCKED",
            "source URL scheme is not allowed",
            provider="http",
        )
    if parsed.username or parsed.password:
        raise ProviderError(
            "SOURCE_URL_BLOCKED",
            "source URL credentials are not allowed",
            provider="http",
        )
    host = parsed.hostname
    if host is None:
        raise ProviderError(
            "SOURCE_URL_BLOCKED",
            "source URL host is missing",
            provider="http",
        )
    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith((".localhost", ".local")):
        raise ProviderError(
            "SOURCE_URL_BLOCKED",
            "source URL host is not public",
            provider="http",
        )
    await _public_host_addresses(
        normalized_host,
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


async def _public_host_addresses(host: str, port: int) -> list[IPAddress]:
    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith((".localhost", ".local")):
        raise ProviderError(
            "SOURCE_URL_BLOCKED",
            "source URL host is not public",
            provider="http",
        )
    addresses = _literal_ip_addresses(normalized_host)
    if addresses is None:
        addresses = await _resolve_host_addresses(normalized_host, port)
    for address in addresses:
        _raise_if_blocked_address(address)
    return addresses


def _literal_ip_addresses(host: str) -> list[IPAddress] | None:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        return None


async def _resolve_host_addresses(host: str, port: int) -> list[IPAddress]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ProviderError(
            "SOURCE_DNS_FAILED",
            "source URL host could not be resolved",
            provider="http",
        ) from exc
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos if info[4]]
    if not addresses:
        raise ProviderError(
            "SOURCE_DNS_FAILED",
            "source URL host could not be resolved",
            provider="http",
        )
    return addresses


def _raise_if_blocked_address(address: IPAddress) -> None:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ProviderError(
            "SOURCE_URL_BLOCKED",
            "source URL host is not public",
            provider="http",
        )
