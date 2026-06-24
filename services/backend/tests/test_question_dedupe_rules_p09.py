from __future__ import annotations

import json
from pathlib import Path

from app.domain.question_dedupe import (
    DIRECT_REJECT_SIMILARITY,
    HistoricalQuestion,
    answer_skeleton_hash,
    cosine_similarity,
    most_similar_questions,
    normalized_question_hash,
    required_structure_changes,
    structure_comparison,
)


def test_p09_golden_hash_cases_match_expected_skin_rejection() -> None:
    fixture_path = Path(__file__).parent / "golden_cases" / "p09_dedupe_cases.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert {case["id"] for case in cases} == {
        "digit_parameter_skin_rejected",
        "role_synonym_skin_rejected",
        "far_scenario_allowed",
    }
    for case in cases:
        assert (
            normalized_question_hash(case["left"]) == normalized_question_hash(case["right"])
        ) is case["same_hash"], case["id"]


def test_embedding_similarity_uses_exact_cosine_threshold() -> None:
    history = HistoricalQuestion(
        question_id="history-1",
        prompt="history",
        normalized_hash="hash",
        template_family="family-a",
        target_defects=("ALIGN-01",),
        structural_json={},
        source_event_id=None,
        prompt_embedding=[1.0, 0.0, 0.0],
        summary_embedding=[0.0, 1.0, 0.0],
        decision_embedding=[0.0, 0.0, 1.0],
        answer_skeleton_hash=None,
    )

    matches = most_similar_questions(
        prompt_embedding=[0.93, 0.0, 0.0],
        summary_embedding=[0.0, 0.2, 0.0],
        decision_embedding=[0.0, 0.0, 0.2],
        histories=[history],
    )

    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert matches[0].similarity >= DIRECT_REJECT_SIMILARITY
    assert matches[0].channel == "prompt"


def test_structure_change_requirement_is_four_or_six_dimensions() -> None:
    history = HistoricalQuestion(
        question_id="history-1",
        prompt="history",
        normalized_hash="hash",
        template_family="family-a",
        target_defects=("ALIGN-01",),
        structural_json={
            "domain": "project",
            "role": "manager",
            "conflict": "scope_vs_speed",
            "constraint": "budget",
            "time_span": "quarter",
            "type": "decision",
            "decision_object": "launch",
        },
        source_event_id=None,
        prompt_embedding=None,
        summary_embedding=None,
        decision_embedding=None,
        answer_skeleton_hash="old-skeleton",
    )

    comparison = structure_comparison(
        candidate_structural={
            "domain": "sales",
            "role": "leader",
            "conflict": "quality_vs_speed",
            "constraint": "headcount",
            "time_span": "quarter",
            "type": "decision",
            "decision_object": "launch",
        },
        candidate_answer_skeleton_hash="new-skeleton",
        history=history,
        high_priority=False,
    )
    high_priority = structure_comparison(
        candidate_structural={
            "domain": "sales",
            "role": "leader",
            "conflict": "quality_vs_speed",
            "constraint": "headcount",
            "time_span": "quarter",
            "type": "decision",
            "decision_object": "launch",
        },
        candidate_answer_skeleton_hash="new-skeleton",
        history=history,
        high_priority=True,
    )

    assert required_structure_changes(high_priority=False) == 4
    assert required_structure_changes(high_priority=True) == 6
    assert len(comparison.changed_dimensions) == 5
    assert len(comparison.changed_dimensions) >= comparison.required_changes
    assert len(high_priority.changed_dimensions) < high_priority.required_changes


def test_answer_skeleton_hash_is_stable_for_same_expected_elements() -> None:
    assert answer_skeleton_hash(
        expected_reasoning=["区分事实和假设"],
        expected_elements=["结论", "证据"],
        fatal_omissions=["答非所问"],
    ) == answer_skeleton_hash(
        expected_reasoning=[" 区分事实和假设 "],
        expected_elements=["结论", "证据"],
        fatal_omissions=["答非所问"],
    )
