from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from time import perf_counter

from pydantic import BaseModel

from app.ai.providers.contracts import (
    ContentFetchRequest,
    ContentFetchResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    LLMStructuredRequest,
    LLMStructuredResponse,
    ProviderCallMetadata,
    ProviderUsage,
    SearchRequest,
    SearchResult,
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
        self.payload = dict(payload) if payload is not None else None

    async def generate_structured(
        self,
        request: LLMStructuredRequest,
        response_model: type[BaseModel],
    ) -> LLMStructuredResponse:
        start = perf_counter()
        payload = self.payload or _mock_payload_for_schema(response_model, request)
        parsed = response_model.model_validate(payload)
        return LLMStructuredResponse(
            output=parsed,
            raw_json=dict(payload),
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


class MockSearchProvider:
    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.results = (
            [
                SearchResult(
                    title="官方项目复盘",
                    url="https://example.edu/official-report/source-a",
                    snippet="项目复盘摘要",
                    source="Example 官方研究报告",
                    published_at="2026-01-01T00:00:00+08:00",
                )
            ]
            if results is None
            else results
        )
        self.requests: list[SearchRequest] = []

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        self.requests.append(request)
        return list(self.results)


class MockContentFetcher:
    def __init__(self, pages: Mapping[str, str] | None = None) -> None:
        self.pages = dict(
            {
                "https://example.edu/official-report/source-a": (
                    "官方项目复盘显示,团队在需求频繁变化后没有更新成功标准。"
                    "复盘还指出,技术方案评审缺少备选方案。"
                )
            }
            if pages is None
            else pages
        )
        self.requests: list[ContentFetchRequest] = []

    async def fetch(self, request: ContentFetchRequest) -> ContentFetchResponse:
        self.requests.append(request)
        text = self.pages.get(request.url, "")
        return ContentFetchResponse(
            url=request.url,
            content_type="text/html",
            text=text,
            snapshot_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            title="mock source",
        )


def _mock_payload_for_schema(
    response_model: type[BaseModel],
    request: LLMStructuredRequest,
) -> dict[str, object]:
    name = response_model.__name__
    if name == "SearchDirectionPlan":
        return {"queries": ["项目延期 官方复盘 成功标准 备选方案"]}
    if name == "ClaimExtractionResult":
        return {
            "claims": [
                {
                    "ref": "c1",
                    "claim_text": "团队在需求频繁变化后没有更新成功标准。",
                    "evidence_locator": "paragraph 1",
                    "evidence_excerpt": "团队在需求频繁变化后没有更新成功标准",
                },
                {
                    "ref": "c2",
                    "claim_text": "技术方案评审缺少备选方案。",
                    "evidence_locator": "paragraph 1",
                    "evidence_excerpt": "技术方案评审缺少备选方案",
                },
            ]
        }
    if name == "ClaimVerificationResult":
        return {
            "claims": [
                {"ref": "c1", "support_status": "VERIFIED", "reason": "excerpt matches"},
                {"ref": "c2", "support_status": "VERIFIED", "reason": "excerpt matches"},
            ]
        }
    if name == "QuestionGenerationResult":
        claim_ids = _uuids_from_messages(request.messages)
        first_claim = claim_ids[0] if claim_ids else "00000000-0000-0000-0000-000000000000"
        scenarios = [
            "资源调配",
            "验收口径",
            "上线节奏",
            "供应商选择",
            "预算调整",
            "质量门禁",
            "客户沟通",
            "风险应对",
        ]
        return {
            "candidates": [
                {
                    "prompt": (
                        f"候选题: 项目延期后,{scenario}材料显示团队没有更新成功标准。"
                        "你需要向负责人说明当前判断、证据缺口、取舍和下一步。"
                    ),
                    "type": "decision",
                    "target_defects": ["ALIGN-01", "INFO-01"],
                    "claim_ids": [first_claim],
                    "fact_mappings": [
                        {
                            "sentence_index": 0,
                            "sentence_text": "材料显示团队没有更新成功标准。",
                            "claim_ids": [first_claim],
                        }
                    ],
                    "fingerprint": {
                        "domain": f"project-{chr(97 + index)}",
                        "role": f"manager-{chr(97 + index)}",
                        "conflict": f"tradeoff-{chr(97 + index)}",
                        "constraint": f"constraint-{chr(97 + index)}",
                        "time_span": f"phase-{chr(97 + index)}",
                        "decision_object": scenario,
                        "reasoning_skeleton": f"skeleton-{chr(97 + index)}",
                        "template_family": f"mock-p08-{index}",
                    },
                    "expected_reasoning": ["区分事实、假设和未知"],
                    "prohibited_inferences": ["不得补充来源未支持的因果"],
                    "hypothetical_assumptions": [],
                }
                for index, scenario in enumerate(scenarios)
            ]
        }
    if name == "RubricGenerationResult":
        return {
            "dimensions": {
                "alignment": 20,
                "structure": 15,
                "evidence": 20,
                "tradeoffs": 15,
                "risk_action": 15,
                "audience_fit": 15,
            },
            "expected_elements": ["结论", "事实", "假设", "未知", "取舍", "下一步"],
            "fatal_omissions": ["答非所问", "把假设当事实"],
        }
    if name == "DedupeAdjudicationResult":
        return {
            "is_duplicate": False,
            "duplicate_type": "other",
            "reusable_answer_skeleton": False,
            "reason": "mock adjudication passes the candidate",
        }
    return {"ok": True, "message": "mock structured response"}


def _uuids_from_messages(messages: Sequence[object]) -> list[str]:
    text = "\n".join(getattr(message, "content", "") for message in messages)
    return re.findall(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        text,
    )
