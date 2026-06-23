from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

AttemptStage = Literal["FIRST", "FOLLOWUP", "FINAL"]
ConfidenceLevel = Literal["low", "medium", "high"]
IssueCategory = Literal["logic", "speech", "adaptability"]


class AnswerStructure(BaseModel):
    direct_answer: str = ""
    facts_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class LogicIssue(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    category: IssueCategory = "logic"
    attempt_stage: AttemptStage = "FIRST"
    severity: int = Field(ge=1, le=5)
    confidence: ConfidenceLevel
    quote: str = Field(min_length=1, max_length=1000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=2000)
    missing_information: list[str] = Field(default_factory=list)
    correction_rule: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_time_range(self) -> LogicIssue:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class LogicReview(BaseModel):
    dimension_scores: dict[str, int] = Field(default_factory=dict)
    issues: list[LogicIssue] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    score_caps: list[str] = Field(default_factory=list)
    followup_strategy: str | None = None


class EvidenceVerification(BaseModel):
    issue_code: str
    evidence_valid: bool
    quote_match: bool
    timestamp_valid: bool
    correction: str | None = None


class SpeechReview(BaseModel):
    score: int = Field(ge=0, le=100)
    metrics: dict[str, object] = Field(default_factory=dict)
    issues: list[LogicIssue] = Field(default_factory=list)


class AdaptabilityReview(BaseModel):
    score: int = Field(ge=0, le=100)
    issues: list[LogicIssue] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    logic_score: int = Field(ge=0, le=100)
    speech_score: int = Field(ge=0, le=100)
    adaptability_score: int = Field(ge=0, le=100)
    final_score: int = Field(ge=0, le=100)
    verified_issues: list[LogicIssue] = Field(default_factory=list)
    rejected_issues: list[EvidenceVerification] = Field(default_factory=list)
    applied_caps: list[str] = Field(default_factory=list)
