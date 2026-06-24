from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DEDUP_VECTOR_DIMENSIONS = 1024
DIRECT_REJECT_SIMILARITY = 0.92
LLM_REVIEW_MIN_SIMILARITY = 0.82
DEFAULT_REQUIRED_STRUCTURE_CHANGES = 4
HIGH_PRIORITY_REQUIRED_STRUCTURE_CHANGES = 6

STRUCTURE_DIMENSIONS = (
    "domain",
    "role",
    "conflict",
    "constraint",
    "time_span",
    "type",
    "decision_object",
    "reasoning_skeleton",
    "answer_skeleton",
    "rubric",
)

ROLE_SYNONYMS = {
    "\u8001\u677f": "leader",
    "\u4e0a\u7ea7": "leader",
    "\u9886\u5bfc": "leader",
    "\u8d1f\u8d23\u4eba": "leader",
    "\u5ba2\u6237": "customer",
    "\u7532\u65b9": "customer",
    "\u7528\u6237": "customer",
    "\u4e0b\u5c5e": "report",
    "\u56e2\u961f\u6210\u5458": "report",
    "\u540c\u4e8b": "colleague",
    "\u534f\u4f5c\u65b9": "colleague",
}
CHINESE_SURNAMES = (
    "\u5f20\u738b\u674e\u8d75\u5218\u9648\u6768\u9ec4\u5468\u5434"
    "\u5f90\u5b59\u80e1\u6731\u9ad8\u6797\u4f55\u90ed\u9a6c\u7f57"
    "\u6881\u5b8b\u90d1\u8c22\u97e9\u5510\u51af\u4e8e\u8463\u8427"
)
ENTITY_PATTERNS = (
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b",
    f"[{CHINESE_SURNAMES}][\u4e00-\u9fff]{{1,2}}",
    r"[A-Z]\s*(?:\u516c\u53f8|\u56e2\u961f|\u90e8\u95e8|\u9879\u76ee|\u4ea7\u54c1)",
)


@dataclass(frozen=True)
class HistoricalQuestion:
    question_id: str
    prompt: str
    normalized_hash: str
    template_family: str
    target_defects: tuple[str, ...]
    structural_json: Mapping[str, object]
    source_event_id: str | None
    prompt_embedding: Sequence[float] | None
    summary_embedding: Sequence[float] | None
    decision_embedding: Sequence[float] | None
    answer_skeleton_hash: str | None


@dataclass(frozen=True)
class SimilarQuestion:
    question_id: str
    similarity: float
    channel: str
    template_family: str


@dataclass(frozen=True)
class StructureComparison:
    question_id: str
    changed_dimensions: tuple[str, ...]
    required_changes: int


def normalize_dedupe_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[0-9]+(?:\.[0-9]+)?", "#", normalized)
    for pattern in ENTITY_PATTERNS:
        normalized = re.sub(pattern, "@entity", normalized)
    normalized = normalized.lower()
    for source, target in ROLE_SYNONYMS.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)
    return normalized


def normalized_question_hash(prompt: str) -> str:
    return hash_text(normalize_dedupe_text(prompt))


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def answer_skeleton_hash(
    *,
    expected_reasoning: Sequence[str],
    expected_elements: Sequence[str],
    fatal_omissions: Sequence[str],
) -> str:
    payload = {
        "expected_elements": [normalize_dedupe_text(item) for item in expected_elements],
        "expected_reasoning": [normalize_dedupe_text(item) for item in expected_reasoning],
        "fatal_omissions": [normalize_dedupe_text(item) for item in fatal_omissions],
    }
    return hash_text(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def embedding_texts(
    *,
    prompt: str,
    structural_json: Mapping[str, object],
    expected_reasoning: Sequence[str],
) -> tuple[str, str, str]:
    decision_object = _string_value(structural_json.get("decision_object"))
    summary_parts = [
        _string_value(structural_json.get("domain")),
        _string_value(structural_json.get("role")),
        _string_value(structural_json.get("conflict")),
        _string_value(structural_json.get("constraint")),
        decision_object,
        " ".join(expected_reasoning),
    ]
    return (
        prompt,
        " ".join(part for part in summary_parts if part),
        decision_object or prompt,
    )


def most_similar_questions(
    *,
    prompt_embedding: Sequence[float],
    summary_embedding: Sequence[float],
    decision_embedding: Sequence[float],
    histories: Sequence[HistoricalQuestion],
    limit: int = 10,
) -> list[SimilarQuestion]:
    matches: list[SimilarQuestion] = []
    for history in histories:
        channel_scores = [
            ("prompt", cosine_similarity(prompt_embedding, history.prompt_embedding)),
            ("summary", cosine_similarity(summary_embedding, history.summary_embedding)),
            ("decision", cosine_similarity(decision_embedding, history.decision_embedding)),
        ]
        channel, similarity = max(channel_scores, key=lambda item: item[1])
        if similarity > 0:
            matches.append(
                SimilarQuestion(
                    question_id=history.question_id,
                    similarity=similarity,
                    channel=channel,
                    template_family=history.template_family,
                )
            )
    return sorted(matches, key=lambda item: item.similarity, reverse=True)[:limit]


def cosine_similarity(left: Sequence[float], right: Sequence[float] | None) -> float:
    if right is None or not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def structure_comparison(
    *,
    candidate_structural: Mapping[str, object],
    candidate_answer_skeleton_hash: str,
    history: HistoricalQuestion,
    high_priority: bool,
) -> StructureComparison:
    candidate = dict(candidate_structural)
    candidate["answer_skeleton"] = candidate_answer_skeleton_hash
    historical = dict(history.structural_json)
    historical["answer_skeleton"] = history.answer_skeleton_hash or ""
    changed = tuple(
        dimension
        for dimension in STRUCTURE_DIMENSIONS
        if _normalized_structure_value(candidate.get(dimension))
        and _normalized_structure_value(historical.get(dimension))
        and _normalized_structure_value(candidate.get(dimension))
        != _normalized_structure_value(historical.get(dimension))
    )
    return StructureComparison(
        question_id=history.question_id,
        changed_dimensions=changed,
        required_changes=required_structure_changes(high_priority=high_priority),
    )


def required_structure_changes(*, high_priority: bool) -> int:
    if high_priority:
        return HIGH_PRIORITY_REQUIRED_STRUCTURE_CHANGES
    return DEFAULT_REQUIRED_STRUCTURE_CHANGES


def overlaps_target_defect(left: Sequence[str], right: Sequence[str]) -> bool:
    return bool(set(left) & set(right))


def _normalized_structure_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return normalize_dedupe_text(value)
    if isinstance(value, list | tuple | set):
        return normalize_dedupe_text(" ".join(str(item) for item in value))
    if isinstance(value, Mapping):
        return normalize_dedupe_text(json.dumps(value, ensure_ascii=True, sort_keys=True))
    return normalize_dedupe_text(str(value))


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
