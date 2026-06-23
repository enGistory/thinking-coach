from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.contracts import ChatMessage, LLMProvider, LLMStructuredRequest
from app.db.models import EvaluationReport
from app.domain.evidence import EvidenceSegment, verify_issue_evidence
from app.domain.scoring import apply_score_rules
from app.repositories.evaluations import EvaluationAttemptBundle, EvaluationRepository, IssueWrite
from app.schemas.evaluation import (
    AdaptabilityReview,
    AnswerStructure,
    EvidenceVerification,
    LogicReview,
    SpeechReview,
)

PROMPT_VERSION = "v1.0.0"
SCHEMA_VERSION = "p06-evaluation-v1"
RUBRIC_VERSION = "p06-dev-rubric-v1"
DEFAULT_RUBRIC_DIMENSIONS = {
    "alignment": 20,
    "structure": 15,
    "evidence": 15,
    "causal_counterfactual": 10,
    "stakeholders": 10,
    "tradeoffs": 15,
    "risk_action": 10,
    "audience_fit": 5,
}
DEFAULT_EXPECTED_ELEMENTS = [
    "goal",
    "evidence",
    "unknowns",
    "options",
    "tradeoffs",
    "next_action",
]
DEFAULT_FATAL_OMISSIONS = [
    "missed_question_core",
    "no_clear_conclusion",
    "assumption_as_fact",
]
ADAPTABILITY_FINAL_MARKERS = (
    "unknown",
    "evidence",
    "tradeoff",
    "next",
    "未知",
    "依据",
    "证据",
    "取舍",
    "下一步",
)
_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class EvaluationPrompt:
    name: str
    version: str
    system: str
    user: str


class EvaluationError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


class EvaluationService:
    def __init__(self, *, session: AsyncSession, llm_provider: LLMProvider) -> None:
        self._session = session
        self._llm_provider = llm_provider

    async def evaluate_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        job_id: UUID | None = None,
    ) -> EvaluationReport:
        repo = EvaluationRepository(self._session)
        context = await repo.get_context(session_id=session_id, user_id=user_id)
        if context is None:
            raise EvaluationError("EVALUATION_SESSION_NOT_FOUND", "training session not found")
        existing = await repo.get_report_by_session(session_id)
        if existing is not None and existing.status == "COMPLETED":
            return existing

        _ensure_ready_for_evaluation(context.attempts)
        rubric = await repo.ensure_question_rubric(
            training_session_id=session_id,
            version=RUBRIC_VERSION,
            dimensions_json=dict(DEFAULT_RUBRIC_DIMENSIONS),
            expected_elements_json=list(DEFAULT_EXPECTED_ELEMENTS),
            fatal_omissions_json=list(DEFAULT_FATAL_OMISSIONS),
            content_hash=_rubric_hash(),
        )
        report = await repo.start_report(session_id=session_id, rubric_id=rubric.id)
        answer_structure = await self._extract_answer_structure(
            repo,
            report,
            context.attempts,
            job_id,
        )
        logic_review = await self._review_logic(
            repo,
            report,
            context.attempts,
            answer_structure,
            job_id,
        )
        speech_review = _review_speech(context.attempts)
        adaptability_review = _review_adaptability(context.attempts)
        issue_writes, rejected = _verify_issues(logic_review, context.attempts)
        scores = apply_score_rules(
            logic_review=logic_review,
            speech_review=speech_review,
            adaptability_review=adaptability_review,
            verified_issues=[item.issue for item in issue_writes],
        )
        completed = await repo.complete_report(
            report=report,
            logic_score=scores.logic_score,
            speech_score=scores.speech_score,
            adaptability_score=scores.adaptability_score,
            final_score=scores.final_score,
            details_json={
                "answer_structure": answer_structure.model_dump(mode="json"),
                "speech_review": speech_review.model_dump(mode="json"),
                "adaptability_review": adaptability_review.model_dump(mode="json"),
                "rejected_issues": [item.model_dump(mode="json") for item in rejected],
                "applied_caps": scores.applied_caps,
            },
            issues=issue_writes,
        )
        context.training_session.stage = "COMPLETED"
        context.training_session.completed_at = datetime.now(UTC)
        await self._session.flush()
        return completed

    async def _extract_answer_structure(
        self,
        repo: EvaluationRepository,
        report: EvaluationReport,
        attempts: dict[str, EvaluationAttemptBundle],
        job_id: UUID | None,
    ) -> AnswerStructure:
        prompt = _load_prompt("answer_structure")
        await _ensure_prompt(repo, prompt)
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="review",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(transcript=_combined_transcript(attempts)),
                    ),
                ],
                temperature=0.0,
            ),
            AnswerStructure,
        )
        await repo.record_model_run(
            report_id=report.id,
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json=_input_summary(attempts),
            output_json=response.raw_json,
        )
        return cast(AnswerStructure, response.output)

    async def _review_logic(
        self,
        repo: EvaluationRepository,
        report: EvaluationReport,
        attempts: dict[str, EvaluationAttemptBundle],
        answer_structure: AnswerStructure,
        job_id: UUID | None,
    ) -> LogicReview:
        prompt = _load_prompt("logic_review")
        await _ensure_prompt(repo, prompt)
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="review",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(
                            rubric=json.dumps(DEFAULT_RUBRIC_DIMENSIONS, ensure_ascii=False),
                            answer_structure=answer_structure.model_dump_json(),
                            transcript=_combined_transcript(attempts),
                        ),
                    ),
                ],
                temperature=0.0,
            ),
            LogicReview,
        )
        await repo.record_model_run(
            report_id=report.id,
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json=_input_summary(attempts),
            output_json=response.raw_json,
        )
        return cast(LogicReview, response.output)


async def _ensure_prompt(repo: EvaluationRepository, prompt: EvaluationPrompt) -> None:
    await repo.ensure_prompt_version(
        name=prompt.name,
        version=prompt.version,
        content_hash=_hash_text(prompt.system + "\n" + prompt.user),
        schema_version=SCHEMA_VERSION,
    )


def _ensure_ready_for_evaluation(attempts: dict[str, EvaluationAttemptBundle]) -> None:
    for stage in ("FIRST", "FOLLOWUP", "FINAL"):
        bundle = attempts.get(stage)
        if bundle is None or bundle.transcript.status != "SUCCEEDED":
            raise EvaluationError("EVALUATION_INPUT_INCOMPLETE", f"{stage} transcript is missing")
        if not bundle.segments:
            raise EvaluationError(
                "EVALUATION_INPUT_INCOMPLETE",
                f"{stage} transcript has no segments",
            )


def _verify_issues(
    logic_review: LogicReview,
    attempts: dict[str, EvaluationAttemptBundle],
) -> tuple[list[IssueWrite], list[EvidenceVerification]]:
    segments = _evidence_segments(attempts)
    verified: list[IssueWrite] = []
    rejected: list[EvidenceVerification] = []
    for issue in logic_review.issues:
        evidence = verify_issue_evidence(issue, segments)
        attempt_bundle = attempts.get(issue.attempt_stage)
        if evidence.verification.evidence_valid and attempt_bundle is not None:
            verified.append(
                IssueWrite(
                    issue=issue,
                    verification=evidence.verification,
                    attempt_id=attempt_bundle.attempt.id,
                    segment_id=evidence.segment_id,
                )
            )
        else:
            rejected.append(evidence.verification)
    return verified, rejected


def _review_speech(attempts: dict[str, EvaluationAttemptBundle]) -> SpeechReview:
    scores: list[int] = []
    metrics_by_stage: dict[str, object] = {}
    for stage, bundle in attempts.items():
        metrics = bundle.transcript.metrics_json or {}
        metrics_by_stage[stage] = metrics
        scores.append(_speech_score(metrics))
    return SpeechReview(
        score=round(sum(scores) / len(scores)) if scores else 0,
        metrics=metrics_by_stage,
    )


def _review_adaptability(attempts: dict[str, EvaluationAttemptBundle]) -> AdaptabilityReview:
    first = _text_for_stage(attempts, "FIRST")
    followup = _text_for_stage(attempts, "FOLLOWUP")
    final = _text_for_stage(attempts, "FINAL")
    score = 70
    notes: list[str] = []
    if followup and _normalized(followup) != _normalized(first):
        score += 10
        notes.append("followup answer changed from first answer")
    if final and _normalized(final) != _normalized(first):
        score += 10
        notes.append("final answer incorporated later response")
    if _mentions_adaptability_marker(final):
        score += 10
        notes.append("final answer mentions evidence, unknowns, tradeoffs or next steps")
    return AdaptabilityReview(score=min(score, 100), notes=notes)


def _speech_score(metrics: dict[str, object]) -> int:
    score = 100
    long_pauses = metrics.get("long_pauses")
    if isinstance(long_pauses, list):
        score -= len(long_pauses) * 3
    fillers = metrics.get("filler_phrases")
    if isinstance(fillers, list):
        for item in fillers:
            if isinstance(item, dict) and isinstance(item.get("count"), int):
                score -= int(item["count"]) * 2
    if metrics.get("first_conclusion_ms") is None:
        score -= 10
    speech_rate = metrics.get("speech_rate_cpm")
    if isinstance(speech_rate, int | float) and (speech_rate < 80 or speech_rate > 280):
        score -= 10
    return max(0, min(100, score))


def _evidence_segments(attempts: dict[str, EvaluationAttemptBundle]) -> list[EvidenceSegment]:
    result: list[EvidenceSegment] = []
    for stage, bundle in attempts.items():
        for segment in bundle.segments:
            result.append(
                EvidenceSegment(
                    id=segment.id,
                    attempt_id=bundle.attempt.id,
                    stage=stage,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    corrected_text=segment.corrected_text,
                )
            )
    return result


def _combined_transcript(attempts: dict[str, EvaluationAttemptBundle]) -> str:
    parts: list[str] = []
    for stage in ("FIRST", "FOLLOWUP", "FINAL"):
        parts.append(f"[{stage}]\n{_text_for_stage(attempts, stage)}")
    return "\n\n".join(parts)


def _text_for_stage(attempts: dict[str, EvaluationAttemptBundle], stage: str) -> str:
    bundle = attempts.get(stage)
    if bundle is None:
        return ""
    corrected = bundle.transcript.corrected_text or ""
    raw = bundle.transcript.raw_text or ""
    return str(corrected or raw)


def _input_summary(attempts: dict[str, EvaluationAttemptBundle]) -> dict[str, object]:
    return {
        "stages": {
            stage: {
                "text_chars": len(_text_for_stage(attempts, stage)),
                "segment_count": len(bundle.segments),
            }
            for stage, bundle in attempts.items()
        }
    }


def _load_prompt(name: str) -> EvaluationPrompt:
    prompt_dir = _REPO_ROOT / "prompts" / name
    return EvaluationPrompt(
        name=name,
        version=PROMPT_VERSION,
        system=(prompt_dir / f"{PROMPT_VERSION}.system.md").read_text(encoding="utf-8"),
        user=(prompt_dir / f"{PROMPT_VERSION}.user.md").read_text(encoding="utf-8"),
    )


def _rubric_hash() -> str:
    payload = json.dumps(
        {
            "dimensions": DEFAULT_RUBRIC_DIMENSIONS,
            "expected": DEFAULT_EXPECTED_ELEMENTS,
            "fatal": DEFAULT_FATAL_OMISSIONS,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return _hash_text(payload)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized(value: str) -> str:
    return "".join(char for char in value if not char.isspace())


def _mentions_adaptability_marker(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in ADAPTABILITY_FINAL_MARKERS)
