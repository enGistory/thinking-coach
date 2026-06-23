from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.defects import (
    ProfileOccurrence,
    calculate_profile_stats,
    normalize_defect_code,
    occurrence_status_for_confidence,
)


def test_defect_code_aliases_map_p06_short_codes_to_spec_codes() -> None:
    assert normalize_defect_code("NO_DECISION") == "STRUCT-01"
    assert normalize_defect_code("ASSUMPTION_AS_FACT") == "INFO-01"
    assert normalize_defect_code("SINGLE_OPTION") == "DEC-01"
    assert normalize_defect_code("GENERIC_FRAMEWORK") == "STRUCT-04"
    assert normalize_defect_code("ALIGN-01") == "ALIGN-01"
    assert normalize_defect_code("UNKNOWN") is None


def test_low_confidence_occurrence_stays_pending() -> None:
    assert occurrence_status_for_confidence("low") == "PENDING"
    assert occurrence_status_for_confidence("medium") == "ACTIVE"
    assert occurrence_status_for_confidence("high") == "ACTIVE"


def test_profile_waits_for_three_occurrences_across_two_scenarios() -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    stats = calculate_profile_stats(
        [
            _occurrence(now, scenario_key="question:a", attempt_stage="FIRST"),
            _occurrence(
                now + timedelta(minutes=1),
                scenario_key="question:b",
                attempt_stage="FIRST",
            ),
        ]
    )

    assert stats.state == "observed"
    assert stats.confirmed is False
    assert stats.active_occurrence_count == 2
    assert stats.scenario_count == 2


def test_profile_confirms_after_three_occurrences_two_scenarios_and_two_first_answers() -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    stats = calculate_profile_stats(
        [
            _occurrence(now, scenario_key="question:a", attempt_stage="FIRST", severity=3),
            _occurrence(
                now + timedelta(minutes=1),
                scenario_key="question:b",
                attempt_stage="FIRST",
                severity=3,
            ),
            _occurrence(
                now + timedelta(minutes=2),
                scenario_key="question:b",
                attempt_stage="FINAL",
                severity=3,
            ),
        ]
    )

    assert stats.state == "confirmed"
    assert stats.confirmed is True
    assert stats.frequency == 3


def test_high_severity_confirmed_profile_becomes_high_priority() -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    stats = calculate_profile_stats(
        [
            _occurrence(now, scenario_key="question:a", attempt_stage="FIRST", severity=5),
            _occurrence(
                now + timedelta(minutes=1),
                scenario_key="question:b",
                attempt_stage="FIRST",
                severity=4,
            ),
            _occurrence(
                now + timedelta(minutes=2),
                scenario_key="question:b",
                attempt_stage="FINAL",
                severity=4,
            ),
        ]
    )

    assert stats.state == "high-priority"
    assert stats.priority > 0


def test_recurrence_after_improvement_returns_to_high_priority() -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    stats = calculate_profile_stats(
        [_occurrence(now, scenario_key="question:a", attempt_stage="FIRST")],
        previous_state="stable-improved",
    )

    assert stats.state == "high-priority"
    assert stats.recurrence == 1


def test_recurrence_high_priority_survives_repeated_rebuild() -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    first = calculate_profile_stats(
        [_occurrence(now, scenario_key="question:a", attempt_stage="FIRST")],
        previous_state="stable-improved",
    )
    second = calculate_profile_stats(
        [_occurrence(now, scenario_key="question:a", attempt_stage="FIRST")],
        previous_state=first.state,
        previous_recurrence=first.recurrence,
    )

    assert first.state == "high-priority"
    assert second.state == "high-priority"
    assert second.recurrence == 1


def test_profile_preserves_improvement_states_without_active_occurrences() -> None:
    assert calculate_profile_stats([], previous_state="improving").state == "improving"
    assert calculate_profile_stats([], previous_state="stable-improved").state == "stable-improved"


def _occurrence(
    created_at: datetime,
    *,
    scenario_key: str,
    attempt_stage: str,
    severity: int = 3,
) -> ProfileOccurrence:
    return ProfileOccurrence(
        severity=severity,
        confidence="high",
        scenario_key=scenario_key,
        attempt_stage=attempt_stage,
        status="ACTIVE",
        created_at=created_at,
    )
