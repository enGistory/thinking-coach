from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence

from pydantic import BaseModel

from app.ai.providers.contracts import (
    ChatMessage,
    EmbeddingRequest,
    LLMStructuredRequest,
    STTRequest,
    TTSRequest,
)
from app.ai.providers.factory import create_provider_bundle
from app.core.config import ConfigurationError, Settings, get_settings


class SmokeLLMOutput(BaseModel):
    ok: bool
    message: str


async def run_smoke(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    bundle = create_provider_bundle(settings)
    if args.task == "llm":
        llm_response = await bundle.llm.generate_structured(
            LLMStructuredRequest(
                model_slot="dialog",
                prompt_version="smoke-v1",
                messages=[
                    ChatMessage(
                        role="user",
                        content='Return JSON only: {"ok": true, "message": "smoke ok"}',
                    )
                ],
            ),
            SmokeLLMOutput,
        )
        return {
            "task": "llm",
            "ok": llm_response.output.model_dump()["ok"],
            "message_length": len(str(llm_response.output.model_dump()["message"])),
            "metadata": llm_response.metadata.model_dump(),
        }

    if args.task == "embedding":
        embedding_response = await bundle.embedding.embed_texts(
            EmbeddingRequest(texts=["smoke embedding"], dimensions=args.dimensions),
        )
        return {
            "task": "embedding",
            "vector_count": len(embedding_response.vectors),
            "vector_dimensions": (
                len(embedding_response.vectors[0]) if embedding_response.vectors else 0
            ),
            "metadata": embedding_response.metadata.model_dump(),
        }

    if args.task == "tts":
        tts_response = await bundle.tts.synthesize(
            TTSRequest(text="This is a TTS smoke test."),
        )
        return {
            "task": "tts",
            "audio_bytes": len(tts_response.audio),
            "mime_type": tts_response.mime_type,
            "metadata": tts_response.metadata.model_dump(),
        }

    if args.task == "asr":
        audio_url = args.audio_url
        if not audio_url and settings.ai_provider_mode_normalized == "mock":
            audio_url = "mock://audio"
        if not audio_url:
            raise ConfigurationError(
                "ASR_AUDIO_URL_REQUIRED",
                "ASR smoke test requires --audio-url in aliyun mode",
            )
        stt_response = await bundle.stt.transcribe(STTRequest(audio_url=audio_url))
        first_segment = (
            stt_response.transcript.segments[0] if stt_response.transcript.segments else None
        )
        return {
            "task": "asr",
            "text_length": len(stt_response.transcript.text),
            "segment_count": len(stt_response.transcript.segments),
            "first_segment_start": first_segment.start_seconds if first_segment else None,
            "first_segment_end": first_segment.end_seconds if first_segment else None,
            "metadata": stt_response.metadata.model_dump(),
        }

    raise AssertionError(f"unsupported task: {args.task}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a redacted AI provider smoke test.")
    parser.add_argument("--provider", choices=["aliyun"], default="aliyun")
    parser.add_argument("--task", choices=["llm", "embedding", "tts", "asr"], required=True)
    parser.add_argument("--audio-url", default="", help="Short-lived URL for ASR smoke tests.")
    parser.add_argument("--dimensions", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    settings.validate_ai()
    result = asyncio.run(run_smoke(args, settings))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
