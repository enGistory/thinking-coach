from __future__ import annotations

from dataclasses import dataclass

from app.ai.providers.aliyun import (
    AliyunCosyVoiceProvider,
    AliyunEmbeddingProvider,
    AliyunFunASRProvider,
    AliyunQwenProvider,
)
from app.ai.providers.contracts import EmbeddingProvider, LLMProvider, STTProvider, TTSProvider
from app.ai.providers.mock import (
    MockEmbeddingProvider,
    MockLLMProvider,
    MockSTTProvider,
    MockTTSProvider,
)
from app.core.config import Settings


@dataclass(frozen=True)
class ProviderBundle:
    llm: LLMProvider
    stt: STTProvider
    tts: TTSProvider
    embedding: EmbeddingProvider


def create_provider_bundle(settings: Settings) -> ProviderBundle:
    settings.validate_ai()
    if settings.ai_provider_mode_normalized == "mock":
        return ProviderBundle(
            llm=MockLLMProvider(),
            stt=MockSTTProvider(),
            tts=MockTTSProvider(),
            embedding=MockEmbeddingProvider(dimensions=settings.aliyun_embedding_dimensions),
        )
    return ProviderBundle(
        llm=AliyunQwenProvider(settings),
        stt=AliyunFunASRProvider(settings),
        tts=AliyunCosyVoiceProvider(settings),
        embedding=AliyunEmbeddingProvider(settings),
    )
