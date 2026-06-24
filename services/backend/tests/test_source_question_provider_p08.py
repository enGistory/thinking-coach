from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterable

import httpcore
import httpx
import pytest
import respx
from pydantic import SecretStr

from app.ai.providers.contracts import ContentFetchRequest, ProviderError, SearchRequest
from app.ai.providers.search import (
    MAX_SOURCE_BYTES,
    BochaSearchProvider,
    HttpContentFetcher,
    _PublicSourceNetworkBackend,
)
from app.core.config import Settings


async def public_dns_result(host: str, port: int) -> list[ipaddress.IPv4Address]:
    return [ipaddress.ip_address("93.184.216.34")]


class RecordingNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.connected_host: str | None = None

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore protocol keyword.
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.connected_host = host
        return DummyNetworkStream()

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore protocol keyword.
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AssertionError("source fetcher should not use unix sockets")

    async def sleep(self, seconds: float) -> None:
        return None


class DummyNetworkStream(httpcore.AsyncNetworkStream):
    async def read(
        self,
        max_bytes: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore protocol keyword.
    ) -> bytes:
        return b""

    async def write(
        self,
        buffer: bytes,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore protocol keyword.
    ) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def start_tls(
        self,
        ssl_context: object,
        server_hostname: str | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore protocol keyword.
    ) -> httpcore.AsyncNetworkStream:
        return self


def search_settings() -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="mock",
        bocha_api_key=SecretStr("bocha-test-secret"),
        bocha_search_endpoint="https://bocha.test/v1/web-search",
        bocha_search_count=3,
        bocha_freshness="oneYear",
        llm_timeout_seconds=5,
    )


async def test_public_source_network_backend_connects_to_validated_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ai.providers.search._resolve_host_addresses", public_dns_result)
    delegate = RecordingNetworkBackend()

    await _PublicSourceNetworkBackend(delegate).connect_tcp("source.example", 443)

    assert delegate.connected_host == "93.184.216.34"


async def test_public_source_network_backend_blocks_rebound_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def private_dns_result(host: str, port: int) -> list[ipaddress.IPv4Address]:
        return [ipaddress.ip_address("10.0.0.5")]

    monkeypatch.setattr("app.ai.providers.search._resolve_host_addresses", private_dns_result)
    delegate = RecordingNetworkBackend()

    with pytest.raises(ProviderError) as exc_info:
        await _PublicSourceNetworkBackend(delegate).connect_tcp("source.example", 443)

    assert exc_info.value.error_code == "SOURCE_URL_BLOCKED"
    assert delegate.connected_host is None


@respx.mock
async def test_bocha_search_provider_maps_web_pages() -> None:
    route = respx.post("https://bocha.test/v1/web-search").mock(
        return_value=httpx.Response(
            200,
            json={
                "webPages": {
                    "value": [
                        {
                            "name": "官方报告",
                            "url": "https://source.example/report",
                            "summary": "报告摘要",
                            "siteName": "Example 官方",
                            "datePublished": "2026-01-01T00:00:00Z",
                        }
                    ]
                }
            },
        )
    )

    results = await BochaSearchProvider(search_settings()).search(
        SearchRequest(query="项目延期 官方报告")
    )

    request_payload = route.calls[0].request.read().decode()
    assert route.calls[0].request.headers["authorization"] == "Bearer bocha-test-secret"
    assert "项目延期 官方报告" in request_payload
    assert results[0].title == "官方报告"
    assert str(results[0].url) == "https://source.example/report"
    assert results[0].source == "Example 官方"


@respx.mock
async def test_bocha_search_provider_maps_wrapped_web_pages() -> None:
    respx.post("https://bocha.test/v1/web-search").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "_type": "SearchResponse",
                    "webPages": {
                        "value": [
                            {
                                "name": "真实包装层报告",
                                "url": "https://wrapped.example/report",
                                "snippet": "包装层摘要",
                                "siteName": "Wrapped Source",
                                "datePublished": "2026-06-01T00:00:00+08:00",
                            }
                        ]
                    },
                },
                "log_id": "test-log-id",
                "msg": None,
            },
        )
    )

    results = await BochaSearchProvider(search_settings()).search(
        SearchRequest(query="阿里巴巴 ESG 报告")
    )

    assert len(results) == 1
    assert results[0].title == "真实包装层报告"
    assert str(results[0].url) == "https://wrapped.example/report"
    assert results[0].snippet == "包装层摘要"
    assert results[0].source == "Wrapped Source"


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SEARCH_TESTS") != "1" or not os.getenv("BOCHA_API_KEY"),
    reason="RUN_LIVE_SEARCH_TESTS=1 and BOCHA_API_KEY are required for live Bocha smoke",
)
async def test_live_bocha_search_provider_smoke() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        bocha_api_key=SecretStr(os.environ["BOCHA_API_KEY"]),
        bocha_search_endpoint=os.getenv(
            "BOCHA_SEARCH_ENDPOINT",
            "https://api.bochaai.com/v1/web-search",
        ),
        bocha_search_count=2,
        bocha_freshness=os.getenv("BOCHA_FRESHNESS", "oneYear"),
        llm_timeout_seconds=20,
    )
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        results = await BochaSearchProvider(settings, client=client).search(
            SearchRequest(query="China GDP 2025 official statistics")
        )

    assert results
    assert all(str(result.url).startswith(("http://", "https://")) for result in results)


@respx.mock
async def test_bocha_search_provider_wraps_http_errors() -> None:
    respx.post("https://bocha.test/v1/web-search").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )

    with pytest.raises(ProviderError) as exc_info:
        await BochaSearchProvider(search_settings()).search(SearchRequest(query="x"))

    assert exc_info.value.error_code == "SEARCH_HTTP_429"
    assert "bocha-test-secret" not in str(exc_info.value)


@respx.mock
async def test_http_content_fetcher_extracts_html_text_and_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ai.providers.search._resolve_host_addresses", public_dns_result)
    html = """
    <html><body><article>
    <h1>官方项目复盘</h1>
    <p>官方项目复盘显示团队没有更新成功标准。</p>
    </article></body></html>
    """
    respx.get("https://source.example/article").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
        )
    )

    fetched = await HttpContentFetcher(search_settings()).fetch(
        ContentFetchRequest(url="https://source.example/article")
    )

    assert "团队没有更新成功标准" in fetched.text
    assert fetched.content_type == "text/html"
    assert len(fetched.snapshot_hash) == 64


@respx.mock
async def test_http_content_fetcher_rejects_declared_oversized_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ai.providers.search._resolve_host_addresses", public_dns_result)
    respx.get("https://source.example/large").mock(
        return_value=httpx.Response(
            200,
            headers={
                "content-type": "text/html; charset=utf-8",
                "content-length": str(MAX_SOURCE_BYTES + 1),
            },
            content=b"",
        )
    )

    with pytest.raises(ProviderError) as exc_info:
        await HttpContentFetcher(search_settings()).fetch(
            ContentFetchRequest(url="https://source.example/large")
        )

    assert exc_info.value.error_code == "SOURCE_CONTENT_TOO_LARGE"


@respx.mock
async def test_http_content_fetcher_rejects_streamed_oversized_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ai.providers.search._resolve_host_addresses", public_dns_result)
    monkeypatch.setattr("app.ai.providers.search.MAX_SOURCE_BYTES", 16)
    respx.get("https://source.example/large-stream").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"x" * 17,
        )
    )

    with pytest.raises(ProviderError) as exc_info:
        await HttpContentFetcher(search_settings()).fetch(
            ContentFetchRequest(url="https://source.example/large-stream")
        )

    assert exc_info.value.error_code == "SOURCE_CONTENT_TOO_LARGE"


async def test_http_content_fetcher_blocks_private_source_urls() -> None:
    with pytest.raises(ProviderError) as exc_info:
        await HttpContentFetcher(search_settings()).fetch(
            ContentFetchRequest(url="http://127.0.0.1/admin")
        )

    assert exc_info.value.error_code == "SOURCE_URL_BLOCKED"


async def test_http_content_fetcher_blocks_domains_resolving_to_private_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def private_dns_result(host: str, port: int) -> list[ipaddress.IPv4Address]:
        return [ipaddress.ip_address("10.0.0.5")]

    monkeypatch.setattr("app.ai.providers.search._resolve_host_addresses", private_dns_result)

    with pytest.raises(ProviderError) as exc_info:
        await HttpContentFetcher(search_settings()).fetch(
            ContentFetchRequest(url="https://source.example/article")
        )

    assert exc_info.value.error_code == "SOURCE_URL_BLOCKED"


@respx.mock
async def test_http_content_fetcher_blocks_redirect_to_private_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ai.providers.search._resolve_host_addresses", public_dns_result)
    respx.get("https://source.example/redirect").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/admin"},
        )
    )

    with pytest.raises(ProviderError) as exc_info:
        await HttpContentFetcher(search_settings()).fetch(
            ContentFetchRequest(url="https://source.example/redirect")
        )

    assert exc_info.value.error_code == "SOURCE_URL_BLOCKED"
