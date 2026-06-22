from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
import respx
from pydantic import BaseModel, SecretStr

from app.ai.providers import aliyun as aliyun_module
from app.ai.providers.aliyun import (
    AliyunCosyVoiceProvider,
    AliyunEmbeddingProvider,
    AliyunFunASRProvider,
    AliyunQwenProvider,
)
from app.ai.providers.contracts import (
    ChatMessage,
    EmbeddingRequest,
    LLMStructuredRequest,
    ProviderError,
    STTRequest,
    TTSRequest,
)
from app.core.config import Settings


class SmokeSchema(BaseModel):
    ok: bool
    message: str


def aliyun_settings() -> Settings:
    return Settings(
        _env_file=None,
        ai_provider_mode="aliyun",
        dashscope_api_key=SecretStr("sk-test-secret"),
        dashscope_base_url="https://dashscope.test/compatible-mode/v1",
        dashscope_http_base_url="https://dashscope.test/api/v1",
        dashscope_websocket_base_url="wss://dashscope.test/api-ws/v1/inference",
        qwen_dialog_model="qwen-dialog-test",
        qwen_question_model="qwen-question-test",
        qwen_review_model="qwen-review-test",
        qwen_verify_model="qwen-verify-test",
        qwen_fallback_model="qwen-fallback-test",
        aliyun_asr_model="fun-asr-test",
        aliyun_tts_model="cosyvoice-test",
        aliyun_tts_voice="voice-test",
        aliyun_embedding_model="embedding-test",
        aliyun_embedding_dimensions=16,
    )


@respx.mock
async def test_qwen_provider_uses_json_mode_and_validates_schema() -> None:
    route = respx.post("https://dashscope.test/compatible-mode/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen-dialog-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"ok": true, "message": "done"}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )
    )

    response = await AliyunQwenProvider(aliyun_settings()).generate_structured(
        LLMStructuredRequest(
            model_slot="dialog",
            prompt_version="test-v1",
            messages=[ChatMessage(role="user", content="return json")],
        ),
        SmokeSchema,
    )

    request_payload = json.loads(route.calls[0].request.content)
    assert request_payload["model"] == "qwen-dialog-test"
    assert request_payload["response_format"] == {"type": "json_object"}
    assert "sk-test-secret" not in route.calls[0].request.content.decode()
    assert cast(SmokeSchema, response.output).ok is True
    assert response.metadata.request_id == "chatcmpl-test"
    assert response.metadata.usage.total_tokens == 5


@respx.mock
async def test_embedding_provider_returns_ordered_vectors() -> None:
    respx.post("https://dashscope.test/compatible-mode/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "embedding-response",
                "object": "list",
                "model": "embedding-test",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
                    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
                ],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )
    )

    response = await AliyunEmbeddingProvider(aliyun_settings()).embed_texts(
        EmbeddingRequest(texts=["a", "b"], dimensions=2),
    )

    assert response.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert response.metadata.model == "embedding-test"


async def test_fun_asr_provider_downloads_and_parses_transcript(monkeypatch) -> None:
    class FakeWaitResponse:
        def __init__(self) -> None:
            self.output = {"results": [{"transcription_url": "https://signed.example/result.json"}]}
            self.request_id = "asr-request"

    provider = AliyunFunASRProvider(aliyun_settings())

    def fake_submit_and_wait(request: STTRequest) -> FakeWaitResponse:
        assert request.audio_url == "https://signed.example/audio.webm"
        return FakeWaitResponse()

    async def fake_download_json(url: str) -> dict[str, object]:
        assert url == "https://signed.example/result.json"
        return {
            "transcripts": [
                {
                    "text": "你好",
                    "language": "zh",
                    "sentences": [
                        {
                            "text": "你好",
                            "begin_time": 0,
                            "end_time": 1000,
                            "words": [
                                {"text": "你", "begin_time": 0, "end_time": 500},
                                {"text": "好", "begin_time": 500, "end_time": 1000},
                            ],
                        }
                    ],
                }
            ],
            "properties": {"audio_duration": 1000},
        }

    monkeypatch.setattr(provider, "_submit_and_wait", fake_submit_and_wait)
    monkeypatch.setattr(provider, "_download_json", fake_download_json)

    response = await provider.transcribe(STTRequest(audio_url="https://signed.example/audio.webm"))

    assert response.transcript.text == "你好"
    assert response.transcript.segments[0].end_seconds == 1.0
    assert response.metadata.request_id == "asr-request"
    assert response.metadata.usage.audio_duration_seconds == 1.0


def test_fun_asr_provider_preserves_dashscope_submit_error(monkeypatch) -> None:
    class FakeTranscription:
        @staticmethod
        def async_call(**kwargs: object) -> object:
            assert kwargs["file_urls"] == ["https://signed.example/audio.webm?Signature=secret"]
            return SimpleNamespace(
                status_code=401,
                code="InvalidApiKey",
                message="Invalid API-key provided.",
                request_id="asr-401",
            )

    fake_dashscope = SimpleNamespace()
    fake_asr_module = SimpleNamespace(Transcription=FakeTranscription)

    def fake_import_module(name: str) -> object:
        if name == "dashscope":
            return fake_dashscope
        if name == "dashscope.audio.asr":
            return fake_asr_module
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(aliyun_module.importlib, "import_module", fake_import_module)
    provider = AliyunFunASRProvider(aliyun_settings())

    with pytest.raises(ProviderError) as exc_info:
        provider._submit_and_wait(
            STTRequest(audio_url="https://signed.example/audio.webm?Signature=secret")
        )

    assert exc_info.value.error_code == "ASR_INVALID_API_KEY"
    assert exc_info.value.request_id == "asr-401"
    assert "signed.example" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


@respx.mock
async def test_fun_asr_provider_redacts_signed_result_url_on_download_error() -> None:
    signed_url = "https://signed.example/result.json?Signature=secret-token"
    respx.get(signed_url).mock(return_value=httpx.Response(403, text="expired"))

    provider = AliyunFunASRProvider(aliyun_settings())

    with pytest.raises(ProviderError) as exc_info:
        await provider._download_json(signed_url)

    assert exc_info.value.error_code == "ASR_RESULT_DOWNLOAD_FAILED"
    assert exc_info.value.__cause__ is None
    assert "signed.example" not in str(exc_info.value)
    assert "secret-token" not in str(exc_info.value)


async def test_cosyvoice_provider_wraps_audio_bytes(monkeypatch) -> None:
    provider = AliyunCosyVoiceProvider(aliyun_settings())

    def fake_synthesize_sync(request: TTSRequest) -> tuple[bytes, str]:
        assert request.text == "hello"
        return b"audio-bytes", "tts-request"

    monkeypatch.setattr(provider, "_synthesize_sync", fake_synthesize_sync)

    response = await provider.synthesize(TTSRequest(text="hello"))

    assert response.audio == b"audio-bytes"
    assert response.metadata.request_id == "tts-request"
    assert response.metadata.usage.input_characters == 5


def test_cosyvoice_provider_passes_dashscope_audio_format(monkeypatch) -> None:
    class FakeFormat:
        sample_rate = 24000

    fake_mp3_format = FakeFormat()

    class FakeAudioFormat:
        MP3_24000HZ_MONO_256KBPS = fake_mp3_format
        WAV_24000HZ_MONO_16BIT = FakeFormat()

    class FakeSpeechSynthesizer:
        def __init__(self, *, model: str, voice: str, format: object) -> None:
            assert model == "cosyvoice-test"
            assert voice == "voice-test"
            assert format is fake_mp3_format

        def call(self, text: str) -> bytes:
            assert text == "hello"
            return b"audio-bytes"

        def get_last_request_id(self) -> str:
            return "tts-request"

    fake_dashscope = SimpleNamespace()
    fake_tts_module = SimpleNamespace(
        AudioFormat=FakeAudioFormat,
        SpeechSynthesizer=FakeSpeechSynthesizer,
    )

    def fake_import_module(name: str) -> object:
        if name == "dashscope":
            return fake_dashscope
        if name == "dashscope.audio.tts_v2":
            return fake_tts_module
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(aliyun_module.importlib, "import_module", fake_import_module)

    audio, request_id = AliyunCosyVoiceProvider(aliyun_settings())._synthesize_sync(
        TTSRequest(text="hello", audio_format="mp3"),
    )

    assert audio == b"audio-bytes"
    assert request_id == "tts-request"
