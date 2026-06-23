from __future__ import annotations

from dataclasses import dataclass

from app.schemas.evaluation import AdaptabilityReview, LogicIssue, LogicReview, SpeechReview

DEFAULT_SCORE_WEIGHTS = {
    "logic": 0.6,
    "speech": 0.2,
    "adaptability": 0.2,
}

SCORE_CAP_BY_CODE = {
    "ALIGN-01": 40,
    "NO_DECISION": 55,
    "ASSUMPTION_AS_FACT": 50,
    "SINGLE_OPTION": 60,
    "LEVEL-01": 50,
    "GENERIC_FRAMEWORK": 60,
}


@dataclass(frozen=True)
class ScoreResult:
    logic_score: int
    speech_score: int
    adaptability_score: int
    final_score: int
    applied_caps: list[str]


def calculate_logic_score(review: LogicReview, verified_issues: list[LogicIssue]) -> int:
    if review.dimension_scores:
        values = [_clamp_score(value) for value in review.dimension_scores.values()]
        base_score = round(sum(values) / len(values))
    else:
        base_score = 100
    penalty = sum(issue.severity * 4 for issue in verified_issues)
    return _clamp_score(base_score - penalty)


def apply_score_rules(
    *,
    logic_review: LogicReview,
    speech_review: SpeechReview,
    adaptability_review: AdaptabilityReview,
    verified_issues: list[LogicIssue],
) -> ScoreResult:
    logic_score = calculate_logic_score(logic_review, verified_issues)
    speech_score = _clamp_score(speech_review.score)
    adaptability_score = _clamp_score(adaptability_review.score)
    weighted = round(
        logic_score * DEFAULT_SCORE_WEIGHTS["logic"]
        + speech_score * DEFAULT_SCORE_WEIGHTS["speech"]
        + adaptability_score * DEFAULT_SCORE_WEIGHTS["adaptability"]
    )
    applied_caps: list[str] = []
    capped = weighted
    for issue in verified_issues:
        cap = SCORE_CAP_BY_CODE.get(issue.code)
        if cap is not None and capped > cap:
            capped = cap
            applied_caps.append(issue.code)
    return ScoreResult(
        logic_score=logic_score,
        speech_score=speech_score,
        adaptability_score=adaptability_score,
        final_score=_clamp_score(capped),
        applied_caps=applied_caps,
    )


def _clamp_score(value: int | float) -> int:
    return max(0, min(100, round(value)))
