from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

SourceLevel = Literal["S", "A", "B", "C"]
SupportStatus = Literal["VERIFIED", "CONFLICTED", "UNSUPPORTED"]


class SearchDirectionPlan(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=5)


class ClaimDraft(BaseModel):
    ref: str = Field(min_length=1, max_length=64)
    claim_text: str = Field(min_length=1, max_length=1000)
    evidence_locator: str = Field(min_length=1, max_length=256)
    evidence_excerpt: str = Field(min_length=1, max_length=1000)


class ClaimExtractionResult(BaseModel):
    claims: list[ClaimDraft] = Field(default_factory=list, max_length=20)


class ClaimVerificationItem(BaseModel):
    ref: str = Field(min_length=1, max_length=64)
    support_status: SupportStatus
    reason: str = Field(min_length=1, max_length=1000)


class ClaimVerificationResult(BaseModel):
    claims: list[ClaimVerificationItem] = Field(default_factory=list)


class QuestionFactMapping(BaseModel):
    sentence_index: int = Field(ge=0)
    sentence_text: str = Field(min_length=1, max_length=1000)
    claim_ids: list[UUID] = Field(min_length=1)


class QuestionCandidate(BaseModel):
    prompt: str = Field(min_length=20, max_length=2000)
    type: str = Field(min_length=1, max_length=64)
    target_defects: list[str] = Field(min_length=1, max_length=8)
    claim_ids: list[UUID] = Field(min_length=1)
    fact_mappings: list[QuestionFactMapping] = Field(min_length=1)
    fingerprint: dict[str, object] = Field(default_factory=dict)
    expected_reasoning: list[str] = Field(default_factory=list)
    prohibited_inferences: list[str] = Field(default_factory=list)
    hypothetical_assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_fact_claims_are_declared(self) -> QuestionCandidate:
        declared = set(self.claim_ids)
        for mapping in self.fact_mappings:
            if not set(mapping.claim_ids).issubset(declared):
                raise ValueError("fact_mappings must reference declared claim_ids")
        return self


class QuestionGenerationResult(BaseModel):
    candidates: list[QuestionCandidate] = Field(min_length=1, max_length=12)


class RubricGenerationResult(BaseModel):
    dimensions: dict[str, int] = Field(min_length=1)
    expected_elements: list[str] = Field(min_length=1)
    fatal_omissions: list[str] = Field(default_factory=list)


class SourceSummaryResponse(BaseModel):
    source_count: int
    highest_source_level: SourceLevel | None
    credential: str


class ProvenanceClaimResponse(BaseModel):
    id: UUID
    claim_text: str
    locator: str
    excerpt: str
    support_status: SupportStatus


class ProvenanceSourceResponse(BaseModel):
    id: UUID
    title: str
    publisher: str
    url: str
    level: SourceLevel
    published_at: datetime | None
    accessed_at: datetime
    snapshot_hash: str
    claims: list[ProvenanceClaimResponse]


class ProvenanceMappingResponse(BaseModel):
    sentence_index: int
    sentence_text: str
    claim_ids: list[UUID]


class TrainingProvenanceResponse(BaseModel):
    session_id: UUID
    question_id: UUID
    prompt: str
    source_summary: SourceSummaryResponse
    sources: list[ProvenanceSourceResponse]
    mappings: list[ProvenanceMappingResponse]
    hypothetical_assumptions: list[str]
