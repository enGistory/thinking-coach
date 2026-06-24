from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, Field, HttpUrl

ModelSlot = Literal["dialog", "question", "review", "verify", "fallback"]
ChatRole = Literal["system", "user", "assistant"]


class ProviderUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    input_characters: int | None = None
    output_characters: int | None = None
    audio_duration_seconds: float | None = None


class ProviderCallMetadata(BaseModel):
    provider: str
    model: str
    request_id: str | None = None
    latency_ms: int
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    structured_ok: bool
    error_code: str | None = None


class ProviderError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        provider: str,
        request_id: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.provider = provider
        self.request_id = request_id
        super().__init__(f"{error_code}: {message}")


class ChatMessage(BaseModel):
    role: ChatRole
    content: str


class LLMStructuredRequest(BaseModel):
    model_slot: ModelSlot
    messages: list[ChatMessage]
    prompt_version: str
    temperature: float | None = None


class LLMStructuredResponse(BaseModel):
    output: BaseModel
    raw_json: dict[str, object]
    metadata: ProviderCallMetadata


class WordTimestamp(BaseModel):
    text: str
    start_seconds: float
    end_seconds: float
    confidence: float | None = None


class TranscriptSegment(BaseModel):
    text: str
    start_seconds: float
    end_seconds: float
    words: list[WordTimestamp] = Field(default_factory=list)


class Transcript(BaseModel):
    text: str
    language: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)


class STTRequest(BaseModel):
    audio_url: str
    language_hints: list[str] = Field(default_factory=lambda: ["zh"])
    diarization_enabled: bool = False


class STTResponse(BaseModel):
    transcript: Transcript
    metadata: ProviderCallMetadata


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None
    audio_format: Literal["mp3", "wav"] = "mp3"


class TTSResponse(BaseModel):
    audio: bytes
    mime_type: str
    metadata: ProviderCallMetadata


class EmbeddingRequest(BaseModel):
    texts: list[str]
    dimensions: int | None = None


class EmbeddingResponse(BaseModel):
    vectors: list[list[float]]
    metadata: ProviderCallMetadata


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str
    source: str | None = None
    published_at: str | None = None


class SearchRequest(BaseModel):
    query: str
    domains: list[str] = Field(default_factory=list)
    recency_days: int | None = None


class ContentFetchRequest(BaseModel):
    url: str


class ContentFetchResponse(BaseModel):
    url: str
    content_type: str
    text: str
    snapshot_hash: str
    title: str | None = None
    locator_prefix: str = "paragraph"


class LLMProvider(Protocol):
    async def generate_structured(
        self,
        request: LLMStructuredRequest,
        response_model: type[BaseModel],
    ) -> LLMStructuredResponse:
        """Return a Pydantic-validated structured LLM response."""


class STTProvider(Protocol):
    async def transcribe(self, request: STTRequest) -> STTResponse:
        """Transcribe one private audio object through a provider boundary."""


class TTSProvider(Protocol):
    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """Synthesize speech bytes for a question or follow-up."""


class EmbeddingProvider(Protocol):
    async def embed_texts(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Embed text values for similarity search."""


class SearchProvider(Protocol):
    async def search(self, request: SearchRequest) -> Sequence[SearchResult]:
        """Search is defined here but implemented in the later source task."""


class ContentFetcher(Protocol):
    async def fetch(self, request: ContentFetchRequest) -> ContentFetchResponse:
        """Fetch and extract evidence text from a public source URL."""
