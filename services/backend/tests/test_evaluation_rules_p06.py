from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.domain.evidence import EvidenceSegment, verify_issue_evidence
from app.domain.scoring import apply_score_rules
from app.schemas.evaluation import (
    AdaptabilityReview,
    AnswerStructure,
    LogicIssue,
    LogicReview,
    SpeechReview,
)


def test_p06_golden_case_fixture_is_well_formed() -> None:
    fixture_path = Path(__file__).parent / "golden_cases" / "p06_evaluation_cases.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert cases[0]["id"] == "p06-logic-evidence-cap"
    assert cases[0]["expected_issue"]["code"] == "ALIGN-01"
    assert cases[0]["expected_cap"] == 40


def test_evidence_verifier_accepts_quote_with_valid_timestamp() -> None:
    issue = _issue(quote="先确认业务目标", start_ms=1000, end_ms=2000)
    segment = EvidenceSegment(
        id=uuid4(),
        attempt_id=uuid4(),
        stage="FIRST",
        start_ms=500,
        end_ms=2500,
        corrected_text="我认为应该先确认业务目标, 再比较方案。",
    )

    result = verify_issue_evidence(issue, [segment])

    assert result.verification.evidence_valid is True
    assert result.verification.quote_match is True
    assert result.verification.timestamp_valid is True
    assert result.segment_id == segment.id


def test_evidence_verifier_rejects_missing_quote_or_invalid_timestamp() -> None:
    segment = EvidenceSegment(
        id=uuid4(),
        attempt_id=uuid4(),
        stage="FIRST",
        start_ms=500,
        end_ms=2500,
        corrected_text="我认为应该先确认业务目标。",
    )
    wrong_quote = _issue(quote="数据库拆三张表", start_ms=1000, end_ms=2000)
    wrong_time = _issue(quote="确认业务目标", start_ms=2600, end_ms=3000)

    quote_result = verify_issue_evidence(wrong_quote, [segment])
    time_result = verify_issue_evidence(wrong_time, [segment])

    assert quote_result.verification.evidence_valid is False
    assert quote_result.verification.quote_match is False
    assert quote_result.verification.timestamp_valid is True
    assert time_result.verification.evidence_valid is False
    assert time_result.verification.quote_match is True
    assert time_result.verification.timestamp_valid is False


def test_evidence_verifier_rejects_quote_from_different_timestamp_segment() -> None:
    quote_segment = EvidenceSegment(
        id=uuid4(),
        attempt_id=uuid4(),
        stage="FIRST",
        start_ms=0,
        end_ms=1000,
        corrected_text="先确认业务目标。",
    )
    cited_segment = EvidenceSegment(
        id=uuid4(),
        attempt_id=quote_segment.attempt_id,
        stage="FIRST",
        start_ms=1000,
        end_ms=2000,
        corrected_text="再比较方案。",
    )
    issue = _issue(quote="先确认业务目标", start_ms=1200, end_ms=1600)

    result = verify_issue_evidence(issue, [quote_segment, cited_segment])

    assert result.verification.evidence_valid is False
    assert result.verification.quote_match is False
    assert result.verification.timestamp_valid is True
    assert result.segment_id is None


def test_evidence_verifier_accepts_quote_spanning_adjacent_segments() -> None:
    attempt_id = uuid4()
    first_segment = EvidenceSegment(
        id=uuid4(),
        attempt_id=attempt_id,
        stage="FIRST",
        start_ms=0,
        end_ms=1000,
        corrected_text="我认为应该先确认业务",
    )
    second_segment = EvidenceSegment(
        id=uuid4(),
        attempt_id=attempt_id,
        stage="FIRST",
        start_ms=1000,
        end_ms=2000,
        corrected_text="目标, 再比较方案。",
    )
    issue = _issue(quote="业务目标", start_ms=900, end_ms=1100)

    result = verify_issue_evidence(issue, [first_segment, second_segment])

    assert result.verification.evidence_valid is True
    assert result.verification.quote_match is True
    assert result.verification.timestamp_valid is True
    assert result.segment_id == first_segment.id


def test_score_caps_are_deterministic_and_scores_remain_independent() -> None:
    issue = _issue(code="ALIGN-01", quote="没有回答核心问题", severity=5)
    result = apply_score_rules(
        logic_review=LogicReview(
            dimension_scores={"alignment": 95, "structure": 90},
            issues=[issue],
        ),
        speech_review=SpeechReview(score=96),
        adaptability_review=AdaptabilityReview(score=88),
        verified_issues=[issue],
    )

    assert result.logic_score == 72
    assert result.speech_score == 96
    assert result.adaptability_score == 88
    assert result.final_score == 40
    assert result.applied_caps == ["ALIGN-01"]


def test_answer_structure_prompt_uses_schema_field_names() -> None:
    prompt_path = (
        Path(__file__).resolve().parents[3] / "prompts" / "answer_structure" / "v1.0.0.user.md"
    )
    prompt = prompt_path.read_text(encoding="utf-8")

    for field_name in AnswerStructure.model_fields:
        assert f"- {field_name} " in prompt
    for stale_field_name in (
        "main_claims",
        "evidence_used",
        "uncertainties",
        "action_items",
        "summary",
    ):
        assert stale_field_name not in prompt


def _issue(
    *,
    code: str = "ALIGN-01",
    quote: str,
    start_ms: int = 1000,
    end_ms: int = 2000,
    severity: int = 3,
) -> LogicIssue:
    return LogicIssue(
        code=code,
        severity=severity,
        confidence="high",
        quote=quote,
        start_ms=start_ms,
        end_ms=end_ms,
        explanation="回答没有覆盖题目核心。",
        missing_information=["目标"],
        correction_rule="先回答核心问题, 再补充依据。",
    )
