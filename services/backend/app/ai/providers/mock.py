from __future__ import annotations

import hashlib
from collections.abc import Mapping
from time import perf_counter

from pydantic import BaseModel

from app.ai.providers.contracts import (
    EmbeddingRequest,
    EmbeddingResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    ProviderCallMetadata,
    ProviderUsage,
    STTRequest,
    STTResponse,
    Transcript,
    TranscriptSegment,
    TTSRequest,
    TTSResponse,
    WordTimestamp,
)


def _elapsed_ms(start: float) -> int:
    return max(0, round((perf_counter() - start) * 1000))


class MockLLMProvider:
    def __init__(self, payload: Mapping[str, object] | None = None) -> None:
        self.payload = dict(payload or {"ok": True, "message": "mock structured response"})

    async def generate_structured(
        self,
        request: LLMStructuredRequest,
        response_model: type[BaseModel],
    ) -> LLMStructuredResponse:
        start = perf_counter()
        parsed = response_model.model_validate(self.payload)
        return LLMStructuredResponse(
            output=parsed,
            raw_json=dict(self.payload),
            metadata=ProviderCallMetadata(
                provider="mock",
                model=f"mock-{request.model_slot}",
                request_id="mock-llm-request",
                latency_ms=_elapsed_ms(start),
                usage=ProviderUsage(
                    input_characters=sum(len(message.content) for message in request.messages),
                    output_characters=len(parsed.model_dump_json()),
                ),
                structured_ok=True,
            ),
        )


class MockSTTProvider:
    async def transcribe(self, request: STTRequest) -> STTResponse:
        start = perf_counter()
        transcript = Transcript(
            text="mock transcript",
            language=request.language_hints[0] if request.language_hints else "zh",
            segments=[
                TranscriptSegment(
                    text="mock transcript",
                    start_seconds=0.0,
                    end_seconds=1.0,
                    words=[
                        WordTimestamp(text="mock", start_seconds=0.0, end_seconds=0.5),
                        WordTimestamp(text="transcript", start_seconds=0.5, end_seconds=1.0),
                    ],
                )
            ],
        )
        return STTResponse(
            transcript=transcript,
            metadata=ProviderCallMetadata(
                provider="mock",
                model="mock-asr",
                request_id="mock-stt-request",
                latency_ms=_elapsed_ms(start),
                usage=ProviderUsage(audio_duration_seconds=1.0),
                structured_ok=True,
            ),
        )


class MockTTSProvider:
    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        start = perf_counter()
        audio = f"mock-audio:{request.text}".encode()
        return TTSResponse(
            audio=audio,
            mime_type="audio/mpeg",
            metadata=ProviderCallMetadata(
                provider="mock",
                model="mock-tts",
                request_id="mock-tts-request",
                latency_ms=_elapsed_ms(start),
                usage=ProviderUsage(
                    input_characters=len(request.text),
                    output_characters=len(audio),
                ),
                structured_ok=True,
            ),
        )


class MockEmbeddingProvider:
    def __init__(self, dimensions: int = 8) -> None:
        self.dimensions = dimensions

    async def embed_texts(self, request: EmbeddingRequest) -> EmbeddingResponse:
        start = perf_counter()
        dimensions = request.dimensions or self.dimensions
        vectors = [self._vector_for_text(text, dimensions) for text in request.texts]
        return EmbeddingResponse(
            vectors=vectors,
            metadata=ProviderCallMetadata(
                provider="mock",
                model="mock-embedding",
                request_id="mock-embedding-request",
                latency_ms=_elapsed_ms(start),
                usage=ProviderUsage(input_characters=sum(len(text) for text in request.texts)),
                structured_ok=True,
            ),
        )

    @staticmethod
    def _vector_for_text(text: str, dimensions: int) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[index % len(digest)] / 255 for index in range(dimensions)]
