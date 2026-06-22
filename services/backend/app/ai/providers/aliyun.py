from __future__ import annotations

import asyncio
import importlib
import json
import re
from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any, cast

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from app.ai.providers.contracts import (
    EmbeddingRequest,
    EmbeddingResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    ModelSlot,
    ProviderCallMetadata,
    ProviderError,
    ProviderUsage,
    STTRequest,
    STTResponse,
    Transcript,
    TranscriptSegment,
    TTSRequest,
    TTSResponse,
    WordTimestamp,
)
from app.core.config import Settings

ALIYUN_PROVIDER_NAME = "aliyun"


def _elapsed_ms(start: float) -> int:
    return max(0, round((perf_counter() - start) * 1000))


def _secret_value(settings: Settings) -> str:
    if settings.dashscope_api_key is None:
        raise ProviderError(
            "AI_CONFIG_MISSING",
            "DASHSCOPE_API_KEY is not configured",
            provider=ALIYUN_PROVIDER_NAME,
        )
    return settings.dashscope_api_key.get_secret_value()


def _usage_from_openai(value: object) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=cast(int | None, getattr(value, "prompt_tokens", None)),
        output_tokens=cast(int | None, getattr(value, "completion_tokens", None)),
        total_tokens=cast(int | None, getattr(value, "total_tokens", None)),
    )


class AliyunQwenProvider:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self._client = client

    async def generate_structured(
        self,
        request: LLMStructuredRequest,
        response_model: type[BaseModel],
    ) -> LLMStructuredResponse:
        start = perf_counter()
        model = self._model_for_slot(request.model_slot)
        try:
            response = await self._client_or_create().chat.completions.create(
                model=model,
                messages=cast(Any, [message.model_dump() for message in request.messages]),
                temperature=self._temperature_for_request(request),
                response_format=cast(Any, {"type": "json_object"}),
                extra_body={"enable_thinking": self._thinking_for_slot(request.model_slot)},
            )
            content = self._content_to_text(response.choices[0].message.content)
            raw_json = self._load_json_object(content)
            parsed = response_model.model_validate(raw_json)
        except ValidationError as exc:
            raise ProviderError(
                "AI_OUTPUT_SCHEMA_INVALID",
                "Qwen response did not match the requested Pydantic schema",
                provider=ALIYUN_PROVIDER_NAME,
            ) from exc
        except (json.JSONDecodeError, IndexError, AttributeError, TypeError) as exc:
            raise ProviderError(
                "AI_OUTPUT_INVALID",
                "Qwen response was not valid structured JSON",
                provider=ALIYUN_PROVIDER_NAME,
            ) from exc
        except OpenAIError as exc:
            raise self._provider_error_from_openai(exc) from exc

        return LLMStructuredResponse(
            output=parsed,
            raw_json=raw_json,
            metadata=ProviderCallMetadata(
                provider=ALIYUN_PROVIDER_NAME,
                model=model,
                request_id=response.id,
                latency_ms=_elapsed_ms(start),
                usage=_usage_from_openai(response.usage),
                structured_ok=True,
            ),
        )

    def _client_or_create(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=_secret_value(self.settings),
                base_url=self.settings.dashscope_base_url,
                http_client=httpx.AsyncClient(
                    timeout=self.settings.llm_timeout_seconds,
                    trust_env=False,
                ),
                timeout=self.settings.llm_timeout_seconds,
                max_retries=self.settings.llm_max_retries,
            )
        return self._client

    def _model_for_slot(self, slot: ModelSlot) -> str:
        mapping: dict[ModelSlot, str] = {
            "dialog": self.settings.qwen_dialog_model,
            "question": self.settings.qwen_question_model,
            "review": self.settings.qwen_review_model,
            "verify": self.settings.qwen_verify_model,
            "fallback": self.settings.qwen_fallback_model,
        }
        return mapping[slot]

    def _temperature_for_request(self, request: LLMStructuredRequest) -> float:
        if request.temperature is not None:
            return request.temperature
        if request.model_slot == "question":
            return self.settings.llm_temperature_question
        if request.model_slot == "review":
            return self.settings.llm_temperature_review
        return self.settings.llm_temperature_dialog

    def _thinking_for_slot(self, slot: ModelSlot) -> bool:
        if slot == "dialog":
            return self.settings.qwen_enable_thinking_dialog
        if slot == "question":
            return self.settings.qwen_enable_thinking_question
        if slot in {"review", "verify"}:
            return self.settings.qwen_enable_thinking_review
        return False

    @staticmethod
    def _content_to_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, Sequence):
            parts: list[str] = []
            for item in content:
                if isinstance(item, Mapping):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "".join(parts)
        raise TypeError("response content is not textual")

    @staticmethod
    def _load_json_object(content: str) -> dict[str, object]:
        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            raise TypeError("structured output must be a JSON object")
        return cast(dict[str, object], loaded)

    @staticmethod
    def _provider_error_from_openai(exc: OpenAIError) -> ProviderError:
        request_id = cast(str | None, getattr(exc, "request_id", None))
        if isinstance(exc, APITimeoutError):
            code = "AI_TIMEOUT"
        elif isinstance(exc, APIConnectionError):
            code = "AI_CONNECTION_ERROR"
        elif isinstance(exc, APIStatusError):
            code = f"AI_HTTP_{exc.status_code}"
        else:
            code = "AI_PROVIDER_ERROR"
        return ProviderError(
            code,
            exc.__class__.__name__,
            provider=ALIYUN_PROVIDER_NAME,
            request_id=request_id,
        )


class AliyunEmbeddingProvider:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self._client = client

    async def embed_texts(self, request: EmbeddingRequest) -> EmbeddingResponse:
        start = perf_counter()
        dimensions = request.dimensions or self.settings.aliyun_embedding_dimensions
        try:
            response = await self._client_or_create().embeddings.create(
                model=self.settings.aliyun_embedding_model,
                input=request.texts,
                dimensions=dimensions,
                encoding_format="float",
            )
        except OpenAIError as exc:
            raise AliyunQwenProvider._provider_error_from_openai(exc) from exc

        vectors = [
            list(item.embedding) for item in sorted(response.data, key=lambda value: value.index)
        ]
        return EmbeddingResponse(
            vectors=vectors,
            metadata=ProviderCallMetadata(
                provider=ALIYUN_PROVIDER_NAME,
                model=self.settings.aliyun_embedding_model,
                request_id=cast(str | None, getattr(response, "id", None)),
                latency_ms=_elapsed_ms(start),
                usage=_usage_from_openai(response.usage),
                structured_ok=True,
            ),
        )

    def _client_or_create(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=_secret_value(self.settings),
                base_url=self.settings.dashscope_base_url,
                http_client=httpx.AsyncClient(
                    timeout=self.settings.llm_timeout_seconds,
                    trust_env=False,
                ),
                timeout=self.settings.llm_timeout_seconds,
                max_retries=self.settings.llm_max_retries,
            )
        return self._client


class AliyunFunASRProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def transcribe(self, request: STTRequest) -> STTResponse:
        start = perf_counter()
        wait_response = await asyncio.to_thread(self._submit_and_wait, request)
        output = _mapping_from_object(getattr(wait_response, "output", wait_response))
        transcription_url = self._transcription_url_from_output(output)
        payload = await self._download_json(transcription_url)
        transcript = _parse_asr_transcript(payload)
        return STTResponse(
            transcript=transcript,
            metadata=ProviderCallMetadata(
                provider=ALIYUN_PROVIDER_NAME,
                model=self.settings.aliyun_asr_model,
                request_id=_request_id_from_response(wait_response),
                latency_ms=_elapsed_ms(start),
                usage=ProviderUsage(audio_duration_seconds=_audio_duration_from_payload(payload)),
                structured_ok=True,
            ),
        )

    def _submit_and_wait(self, request: STTRequest) -> object:
        _configure_dashscope(self.settings)
        asr_module = cast(Any, importlib.import_module("dashscope.audio.asr"))
        transcription_cls = asr_module.Transcription
        kwargs: dict[str, object] = {
            "model": self.settings.aliyun_asr_model,
            "file_urls": [request.audio_url],
        }
        if request.language_hints:
            kwargs["language_hints"] = request.language_hints
        kwargs["diarization_enabled"] = request.diarization_enabled
        task_response = transcription_cls.async_call(**kwargs)
        if _status_code_from_response(task_response) >= 400:
            raise _provider_error_from_dashscope_response(
                task_response,
                fallback_code="ASR_SUBMIT_FAILED",
                fallback_message="fun-asr task submission failed",
            )
        task_output = _mapping_from_object(getattr(task_response, "output", task_response))
        task_id = task_output.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError(
                "ASR_TASK_ID_MISSING",
                "fun-asr did not return a task id",
                provider=ALIYUN_PROVIDER_NAME,
                request_id=_request_id_from_response(task_response),
            )
        wait_response = transcription_cls.wait(task=task_id)
        if _status_code_from_response(wait_response) >= 400:
            raise _provider_error_from_dashscope_response(
                wait_response,
                fallback_code="ASR_WAIT_FAILED",
                fallback_message="fun-asr task wait failed",
            )
        return wait_response

    async def _download_json(self, url: str) -> Mapping[str, object]:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.llm_timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            raise ProviderError(
                "ASR_RESULT_DOWNLOAD_FAILED",
                "failed to download fun-asr transcription result",
                provider=ALIYUN_PROVIDER_NAME,
            ) from None
        if not isinstance(payload, Mapping):
            raise ProviderError(
                "ASR_RESULT_INVALID",
                "fun-asr transcription result is not a JSON object",
                provider=ALIYUN_PROVIDER_NAME,
            )
        return cast(Mapping[str, object], payload)

    @staticmethod
    def _transcription_url_from_output(output: Mapping[str, object]) -> str:
        direct = output.get("transcription_url")
        if isinstance(direct, str) and direct:
            return direct
        results = output.get("results")
        if isinstance(results, Sequence):
            for result in results:
                if isinstance(result, Mapping):
                    url = result.get("transcription_url")
                    if isinstance(url, str) and url:
                        return url
        raise ProviderError(
            "ASR_RESULT_URL_MISSING",
            "fun-asr did not return a transcription result URL",
            provider=ALIYUN_PROVIDER_NAME,
        )


class AliyunCosyVoiceProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        start = perf_counter()
        audio, request_id = await asyncio.to_thread(self._synthesize_sync, request)
        return TTSResponse(
            audio=audio,
            mime_type="audio/mpeg" if request.audio_format == "mp3" else "audio/wav",
            metadata=ProviderCallMetadata(
                provider=ALIYUN_PROVIDER_NAME,
                model=self.settings.aliyun_tts_model,
                request_id=request_id,
                latency_ms=_elapsed_ms(start),
                usage=ProviderUsage(
                    input_characters=len(request.text),
                    output_characters=len(audio),
                ),
                structured_ok=True,
            ),
        )

    def _synthesize_sync(self, request: TTSRequest) -> tuple[bytes, str | None]:
        _configure_dashscope(self.settings)
        tts_module = cast(Any, importlib.import_module("dashscope.audio.tts_v2"))
        synthesizer_cls = tts_module.SpeechSynthesizer
        synthesizer = synthesizer_cls(
            model=self.settings.aliyun_tts_model,
            voice=request.voice or self.settings.aliyun_tts_voice,
            format=_dashscope_audio_format(tts_module, request.audio_format),
        )
        audio = synthesizer.call(request.text)
        if not isinstance(audio, bytes | bytearray):
            raise ProviderError(
                "TTS_OUTPUT_INVALID",
                "CosyVoice did not return audio bytes",
                provider=ALIYUN_PROVIDER_NAME,
            )
        request_id_getter = getattr(synthesizer, "get_last_request_id", None)
        request_id = request_id_getter() if callable(request_id_getter) else None
        return bytes(audio), cast(str | None, request_id)


def _configure_dashscope(settings: Settings) -> None:
    dashscope_module = cast(Any, importlib.import_module("dashscope"))
    dashscope_module.api_key = _secret_value(settings)
    dashscope_module.base_http_api_url = settings.dashscope_http_base_url
    dashscope_module.base_websocket_api_url = settings.dashscope_websocket_base_url


def _dashscope_audio_format(tts_module: Any, audio_format: str) -> object:
    if audio_format == "mp3":
        return tts_module.AudioFormat.MP3_24000HZ_MONO_256KBPS
    if audio_format == "wav":
        return tts_module.AudioFormat.WAV_24000HZ_MONO_16BIT
    raise ProviderError(
        "TTS_FORMAT_UNSUPPORTED",
        "unsupported CosyVoice audio format",
        provider=ALIYUN_PROVIDER_NAME,
    )


def _mapping_from_object(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return cast(Mapping[str, object], dumped)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        if isinstance(dumped, Mapping):
            return cast(Mapping[str, object], dumped)
    data = getattr(value, "__dict__", None)
    if isinstance(data, Mapping):
        return cast(Mapping[str, object], data)
    raise ProviderError(
        "AI_PROVIDER_RESPONSE_INVALID",
        "provider response is not mapping-like",
        provider=ALIYUN_PROVIDER_NAME,
    )


def _status_code_from_response(value: object) -> int:
    status_code = getattr(value, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return 200


def _request_id_from_response(value: object) -> str | None:
    request_id = getattr(value, "request_id", None)
    if isinstance(request_id, str):
        return request_id
    request_id = getattr(value, "id", None)
    if isinstance(request_id, str):
        return request_id
    return None


def _provider_error_from_dashscope_response(
    value: object,
    *,
    fallback_code: str,
    fallback_message: str,
) -> ProviderError:
    upstream_code = _string_value(getattr(value, "code", None))
    if upstream_code:
        error_code = f"ASR_{_provider_error_suffix(upstream_code)}"
        message = f"{fallback_message}: {upstream_code}"
    else:
        status_code = _status_code_from_response(value)
        error_code = f"ASR_HTTP_{status_code}" if status_code >= 400 else fallback_code
        message = fallback_message
    return ProviderError(
        error_code,
        message,
        provider=ALIYUN_PROVIDER_NAME,
        request_id=_request_id_from_response(value),
    )


def _provider_error_suffix(value: str) -> str:
    with_word_boundaries = re.sub(r"(?<!^)(?=[A-Z])", "_", value.strip())
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", with_word_boundaries).strip("_").upper()
    return normalized or "PROVIDER_ERROR"


def _parse_asr_transcript(payload: Mapping[str, object]) -> Transcript:
    transcript_items = payload.get("transcripts")
    if isinstance(transcript_items, Sequence):
        transcript_sources = [item for item in transcript_items if isinstance(item, Mapping)]
    else:
        transcript_sources = [payload]

    all_segments: list[TranscriptSegment] = []
    all_text: list[str] = []
    language: str | None = None

    for source in transcript_sources:
        text = _string_value(source.get("text"))
        if text:
            all_text.append(text)
        language = language or _string_value(source.get("language"))
        sentences = source.get("sentences")
        if isinstance(sentences, Sequence):
            all_segments.extend(_parse_segments(sentences))

    if not all_segments and all_text:
        all_segments.append(
            TranscriptSegment(
                text=" ".join(all_text),
                start_seconds=0.0,
                end_seconds=_audio_duration_from_payload(payload) or 0.0,
            )
        )
    return Transcript(text=" ".join(all_text).strip(), language=language, segments=all_segments)


def _parse_segments(sentences: Sequence[object]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for sentence in sentences:
        if not isinstance(sentence, Mapping):
            continue
        text = _string_value(sentence.get("text")) or _string_value(sentence.get("sentence"))
        if not text:
            continue
        words_value = sentence.get("words")
        words = _parse_words(words_value if isinstance(words_value, Sequence) else [])
        segments.append(
            TranscriptSegment(
                text=text,
                start_seconds=_timestamp_seconds(
                    sentence.get("begin_time")
                    or sentence.get("start_time")
                    or sentence.get("start")
                    or 0
                ),
                end_seconds=_timestamp_seconds(
                    sentence.get("end_time") or sentence.get("end") or sentence.get("stop") or 0
                ),
                words=words,
            )
        )
    return segments


def _parse_words(words: Sequence[object]) -> list[WordTimestamp]:
    result: list[WordTimestamp] = []
    for word in words:
        if not isinstance(word, Mapping):
            continue
        text = _string_value(word.get("text")) or _string_value(word.get("word"))
        if not text:
            continue
        confidence_value = word.get("confidence")
        result.append(
            WordTimestamp(
                text=text,
                start_seconds=_timestamp_seconds(
                    word.get("begin_time") or word.get("start_time") or word.get("start") or 0
                ),
                end_seconds=_timestamp_seconds(
                    word.get("end_time") or word.get("end") or word.get("stop") or 0
                ),
                confidence=(
                    float(confidence_value) if isinstance(confidence_value, int | float) else None
                ),
            )
        )
    return result


def _audio_duration_from_payload(payload: Mapping[str, object]) -> float | None:
    properties = payload.get("properties")
    if isinstance(properties, Mapping):
        for key in ("audio_duration", "original_duration", "duration"):
            duration = properties.get(key)
            if isinstance(duration, int | float):
                return _timestamp_seconds(duration)
    duration = payload.get("duration")
    if isinstance(duration, int | float):
        return _timestamp_seconds(duration)
    return None


def _timestamp_seconds(value: object) -> float:
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric / 1000 if numeric > 100 else numeric
    return 0.0


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""
