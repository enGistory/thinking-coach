from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.providers.aliyun import (
    AliyunCosyVoiceProvider,
    AliyunEmbeddingProvider,
    AliyunFunASRProvider,
    AliyunQwenProvider,
)
from app.ai.providers.contracts import (
    ContentFetcher,
    EmbeddingProvider,
    LLMProvider,
    SearchProvider,
    STTProvider,
    TTSProvider,
)
from app.ai.providers.mock import (
    MockContentFetcher,
    MockEmbeddingProvider,
    MockLLMProvider,
    MockSearchProvider,
    MockSTTProvider,
    MockTTSProvider,
)
from app.ai.providers.search import BochaSearchProvider, HttpContentFetcher
from app.core.config import Settings


@dataclass(frozen=True)
class ProviderBundle:
    llm: LLMProvider
    stt: STTProvider
    tts: TTSProvider
    embedding: EmbeddingProvider
    search: SearchProvider = field(default_factory=MockSearchProvider)
    content_fetcher: ContentFetcher = field(default_factory=MockContentFetcher)


def create_provider_bundle(settings: Settings) -> ProviderBundle:
    settings.validate_ai()
    if settings.ai_provider_mode_normalized == "mock":
        return ProviderBundle(
            llm=MockLLMProvider(),
            stt=MockSTTProvider(),
            tts=MockTTSProvider(),
            embedding=MockEmbeddingProvider(dimensions=settings.aliyun_embedding_dimensions),
            search=MockSearchProvider(),
            content_fetcher=MockContentFetcher(),
        )
    settings.validate_search()
    return ProviderBundle(
        llm=AliyunQwenProvider(settings),
        stt=AliyunFunASRProvider(settings),
        tts=AliyunCosyVoiceProvider(settings),
        embedding=AliyunEmbeddingProvider(settings),
        search=(
            MockSearchProvider()
            if settings.search_provider_normalized == "mock"
            else BochaSearchProvider(settings)
        ),
        content_fetcher=HttpContentFetcher(settings),
    )
