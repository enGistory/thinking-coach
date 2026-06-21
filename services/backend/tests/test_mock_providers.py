from __future__ import annotations

from pydantic import BaseModel

from app.ai.providers.contracts import (
    ChatMessage,
    EmbeddingRequest,
    LLMStructuredRequest,
    STTRequest,
    TTSRequest,
)
from app.ai.providers.mock import (
    MockEmbeddingProvider,
    MockLLMProvider,
    MockSTTProvider,
    MockTTSProvider,
)


class MockSchema(BaseModel):
    ok: bool
    message: str


async def test_mock_llm_returns_validated_pydantic_output() -> None:
    response = await MockLLMProvider().generate_structured(
        LLMStructuredRequest(
            model_slot="dialog",
            prompt_version="test-v1",
            messages=[ChatMessage(role="user", content="return json")],
        ),
        MockSchema,
    )

    assert isinstance(response.output, MockSchema)
    assert response.output.ok is True
    assert response.metadata.provider == "mock"
    assert response.metadata.structured_ok is True


async def test_mock_stt_returns_timestamped_transcript() -> None:
    response = await MockSTTProvider().transcribe(STTRequest(audio_url="mock://audio"))

    assert response.transcript.text == "mock transcript"
    assert response.transcript.segments[0].start_seconds == 0.0
    assert response.transcript.segments[0].words[0].text == "mock"


async def test_mock_tts_returns_audio_bytes() -> None:
    response = await MockTTSProvider().synthesize(TTSRequest(text="hello"))

    assert response.audio
    assert response.mime_type == "audio/mpeg"
    assert response.metadata.usage.input_characters == 5


async def test_mock_embedding_returns_deterministic_dimensions() -> None:
    provider = MockEmbeddingProvider(dimensions=4)

    response = await provider.embed_texts(EmbeddingRequest(texts=["same", "same"]))

    assert len(response.vectors) == 2
    assert len(response.vectors[0]) == 4
    assert response.vectors[0] == response.vectors[1]
