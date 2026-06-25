from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from random import Random
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.random_strike import (
    DefectSignal,
    QuestionCandidate,
    can_schedule_strike,
    choose_strike_question,
    random_scheduled_at,
    should_enqueue_inventory_job,
)


@dataclass(frozen=True)
class Policy:
    windows: list[dict[str, object]]
    quiet_hours: list[dict[str, object]]
    daily_max: int
    timezone: str


def test_random_schedule_respects_window_and_quiet_hours() -> None:
    policy = Policy(
        windows=[{"days": [2], "start": "09:00", "end": "12:00"}],
        quiet_hours=[{"start": "10:00", "end": "11:00"}],
        daily_max=1,
        timezone="Asia/Shanghai",
    )

    scheduled = random_scheduled_at(
        policy=policy,
        now=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        rng=Random(7),
    )

    assert scheduled is not None
    shanghai = scheduled.astimezone(ZoneInfo("Asia/Shanghai"))
    assert shanghai.weekday() == 2
    assert shanghai.hour in {9, 11}


def test_inventory_threshold_and_daily_max_gate_scheduling() -> None:
    assert should_enqueue_inventory_job(2) is True
    assert should_enqueue_inventory_job(3) is False
    assert can_schedule_strike(ready_count=1, daily_count=0, daily_max=1) is True
    assert can_schedule_strike(ready_count=0, daily_count=0, daily_max=1) is False
    assert can_schedule_strike(ready_count=1, daily_count=1, daily_max=1) is False


def test_repeated_defect_forces_different_candidate_when_available() -> None:
    repeated = QuestionCandidate(
        id=uuid4(),
        target_defects=("ALIGN-01",),
        ready_at=None,
    )
    breaker = QuestionCandidate(
        id=uuid4(),
        target_defects=("STRUCT-01",),
        ready_at=None,
    )

    decision = choose_strike_question(
        candidates=[repeated, breaker],
        defect_signals=[
            DefectSignal("ALIGN-01", "high-priority", 90, None),
            DefectSignal("STRUCT-01", "observed", 10, None),
        ],
        recent_defect_groups=[("ALIGN-01",), ("ALIGN-01",)],
        now=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        rng=Random(1),
    )

    assert decision is not None
    assert decision.question_id == breaker.id
    assert decision.reason == "fatigue break after repeated defect"
