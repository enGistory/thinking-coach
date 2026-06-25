from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from random import Random
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

READY_INVENTORY_TARGET = 7
READY_INVENTORY_LOW_WATERMARK = 3
MAX_DEFER_COUNT = 1
RECENT_REPEAT_LIMIT = 2

QUOTA_WEIGHTS = {
    "known_defect": 0.55,
    "migration": 0.25,
    "potential_defect": 0.10,
    "blind_spot": 0.10,
}


class PolicyLike(Protocol):
    windows: list[dict[str, object]]
    quiet_hours: list[dict[str, object]]
    daily_max: int
    timezone: str


@dataclass(frozen=True)
class QuestionCandidate:
    id: UUID
    target_defects: tuple[str, ...]
    ready_at: datetime | None


@dataclass(frozen=True)
class DefectSignal:
    code: str
    state: str
    priority: int
    last_seen_at: datetime | None


@dataclass(frozen=True)
class StrikeDecision:
    question_id: UUID
    target_defects: tuple[str, ...]
    quota_bucket: str
    score: float
    fatigue_penalty: float
    repeated_defect: str | None
    reason: str

    def as_json(self) -> dict[str, object]:
        return {
            "question_id": str(self.question_id),
            "target_defects": list(self.target_defects),
            "quota_bucket": self.quota_bucket,
            "quota_weights": QUOTA_WEIGHTS,
            "score": round(self.score, 4),
            "fatigue_penalty": round(self.fatigue_penalty, 4),
            "repeated_defect": self.repeated_defect,
            "reason": self.reason,
        }


def should_enqueue_inventory_job(ready_count: int) -> bool:
    return ready_count < READY_INVENTORY_LOW_WATERMARK


def can_schedule_strike(*, ready_count: int, daily_count: int, daily_max: int) -> bool:
    return ready_count > 0 and daily_count < daily_max


def random_scheduled_at(
    *,
    policy: PolicyLike,
    now: datetime,
    rng: Random,
) -> datetime | None:
    timezone = ZoneInfo(policy.timezone)
    local_now = _as_aware_utc(now).astimezone(timezone)
    intervals = _allowed_intervals(policy, local_now)
    future_intervals = [
        (max(start, local_now), end)
        for start, end in intervals
        if end > local_now and (end - max(start, local_now)).total_seconds() >= 60
    ]
    if not future_intervals:
        return None
    total_seconds = sum(int((end - start).total_seconds()) for start, end in future_intervals)
    offset = rng.randrange(max(total_seconds, 1))
    for start, end in future_intervals:
        span = int((end - start).total_seconds())
        if offset < span:
            return (start + timedelta(seconds=offset)).astimezone(UTC)
        offset -= span
    return future_intervals[-1][0].astimezone(UTC)


def choose_strike_question(
    *,
    candidates: list[QuestionCandidate],
    defect_signals: list[DefectSignal],
    recent_defect_groups: list[tuple[str, ...]],
    now: datetime,
    rng: Random,
) -> StrikeDecision | None:
    if not candidates:
        return None
    repeated_defect = _repeated_recent_defect(recent_defect_groups)
    filtered = [
        candidate
        for candidate in candidates
        if repeated_defect is None or repeated_defect not in candidate.target_defects
    ]
    effective_candidates = filtered or candidates
    scored = [
        _score_candidate(
            candidate,
            defect_signals=defect_signals,
            repeated_defect=repeated_defect,
            fatigue_applies=(
                repeated_defect is not None
                and repeated_defect in candidate.target_defects
                and not filtered
            ),
            now=now,
        )
        for candidate in effective_candidates
    ]
    top_score = max(decision.score for decision in scored)
    top = [decision for decision in scored if decision.score == top_score]
    return top[rng.randrange(len(top))]


def _score_candidate(
    candidate: QuestionCandidate,
    *,
    defect_signals: list[DefectSignal],
    repeated_defect: str | None,
    fatigue_applies: bool,
    now: datetime,
) -> StrikeDecision:
    signals_by_code = {signal.code: signal for signal in defect_signals}
    matching = [
        signals_by_code[code] for code in candidate.target_defects if code in signals_by_code
    ]
    quota_bucket = _quota_bucket(matching, has_profiles=bool(defect_signals))
    priority = max((signal.priority for signal in matching), default=0)
    days_since_test = max(
        (
            (_as_aware_utc(now) - _as_aware_utc(signal.last_seen_at)).days
            for signal in matching
            if signal.last_seen_at is not None
        ),
        default=0,
    )
    fatigue_penalty = 0.15 if fatigue_applies else 0.0
    score = (
        QUOTA_WEIGHTS[quota_bucket]
        + priority / 100.0
        + min(days_since_test, 30) * 0.01
        - fatigue_penalty
    )
    reason = "profile priority and quota"
    if repeated_defect is not None and repeated_defect not in candidate.target_defects:
        reason = "fatigue break after repeated defect"
        score += 0.5
    elif not matching:
        reason = "blind spot quota"
    return StrikeDecision(
        question_id=candidate.id,
        target_defects=candidate.target_defects,
        quota_bucket=quota_bucket,
        score=score,
        fatigue_penalty=fatigue_penalty,
        repeated_defect=repeated_defect,
        reason=reason,
    )


def _quota_bucket(matching: list[DefectSignal], *, has_profiles: bool) -> str:
    if any(signal.state in {"high-priority", "confirmed"} for signal in matching):
        return "known_defect"
    if any(signal.state in {"improving", "stable-improved"} for signal in matching):
        return "migration"
    if matching:
        return "potential_defect"
    if has_profiles:
        return "blind_spot"
    return "blind_spot"


def _repeated_recent_defect(recent_defect_groups: list[tuple[str, ...]]) -> str | None:
    if len(recent_defect_groups) < RECENT_REPEAT_LIMIT:
        return None
    recent = recent_defect_groups[:RECENT_REPEAT_LIMIT]
    common = set(recent[0])
    for group in recent[1:]:
        common &= set(group)
    return sorted(common)[0] if common else None


def _allowed_intervals(
    policy: PolicyLike,
    local_now: datetime,
) -> list[tuple[datetime, datetime]]:
    base_date = local_now.date()
    intervals: list[tuple[datetime, datetime]] = []
    for offset in range(-1, 8):
        current_date = base_date + timedelta(days=offset)
        for window in policy.windows:
            days = window.get("days")
            if not isinstance(days, list) or current_date.weekday() not in days:
                continue
            start = _parse_hhmm(str(window.get("start", "")))
            end = _parse_hhmm(str(window.get("end", "")))
            intervals.append(_range_for_date(current_date, start, end, local_now.tzinfo))

    quiet_intervals: list[tuple[datetime, datetime]] = []
    for offset in range(-1, 9):
        current_date = base_date + timedelta(days=offset)
        for quiet in policy.quiet_hours:
            start = _parse_hhmm(str(quiet.get("start", "")))
            end = _parse_hhmm(str(quiet.get("end", "")))
            quiet_intervals.append(_range_for_date(current_date, start, end, local_now.tzinfo))

    available = intervals
    for quiet_start, quiet_end in quiet_intervals:
        available = _subtract_interval(available, quiet_start, quiet_end)
    return sorted(available, key=lambda item: item[0])


def _range_for_date(
    current_date: date,
    start: time,
    end: time,
    tzinfo: tzinfo | None,
) -> tuple[datetime, datetime]:
    start_at = datetime.combine(current_date, start, tzinfo=tzinfo)
    end_date = current_date if end > start else current_date + timedelta(days=1)
    end_at = datetime.combine(end_date, end, tzinfo=tzinfo)
    return start_at, end_at


def _subtract_interval(
    intervals: list[tuple[datetime, datetime]],
    block_start: datetime,
    block_end: datetime,
) -> list[tuple[datetime, datetime]]:
    result: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if block_end <= start or block_start >= end:
            result.append((start, end))
            continue
        if block_start > start:
            result.append((start, block_start))
        if block_end < end:
            result.append((block_end, end))
    return result


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
