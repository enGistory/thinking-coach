from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

LONG_PAUSE_THRESHOLD_MS = 700
FILLER_PHRASES = (
    "嗯",
    "呃",
    "然后",
    "就是",
    "那个",
    "这个",
    "其实",
    "对吧",
    "是吧",
    "啊",
)
CONCLUSION_MARKERS = ("我认为", "我的结论", "结论", "核心是", "所以", "因此")


class LongPauseMetric(TypedDict):
    start_ms: int
    end_ms: int
    duration_ms: int


class PhraseCountMetric(TypedDict):
    phrase: str
    count: int


class RepeatedPhraseMetric(TypedDict):
    text: str
    count: int


class SpeechMetrics(TypedDict):
    audio_duration_ms: int | None
    effective_speech_ms: int
    speech_ratio: float | None
    long_pauses: list[LongPauseMetric]
    filler_phrases: list[PhraseCountMetric]
    speech_rate_cpm: float | None
    repeated_phrases: list[RepeatedPhraseMetric]
    first_conclusion_ms: int | None
    total_text_chars: int
    segment_count: int


@dataclass(frozen=True)
class SpeechMetricSegment:
    start_ms: int
    end_ms: int
    text: str


def calculate_speech_metrics(
    *,
    audio_duration_ms: int | None,
    segments: list[SpeechMetricSegment],
) -> SpeechMetrics:
    ordered_segments = sorted(segments, key=lambda segment: (segment.start_ms, segment.end_ms))
    effective_speech_ms = _effective_speech_ms(ordered_segments)
    total_chars = sum(_count_text_chars(segment.text) for segment in ordered_segments)
    speech_rate = (
        round(total_chars / (effective_speech_ms / 60_000), 2)
        if effective_speech_ms > 0 and total_chars > 0
        else None
    )
    return SpeechMetrics(
        audio_duration_ms=audio_duration_ms,
        effective_speech_ms=effective_speech_ms,
        speech_ratio=(
            round(effective_speech_ms / audio_duration_ms, 4)
            if audio_duration_ms and audio_duration_ms > 0
            else None
        ),
        long_pauses=_long_pauses(ordered_segments),
        filler_phrases=_filler_counts(ordered_segments),
        speech_rate_cpm=speech_rate,
        repeated_phrases=_repeated_phrases(ordered_segments),
        first_conclusion_ms=_first_conclusion_ms(ordered_segments),
        total_text_chars=total_chars,
        segment_count=len(ordered_segments),
    )


def _effective_speech_ms(segments: list[SpeechMetricSegment]) -> int:
    intervals = [
        (segment.start_ms, segment.end_ms)
        for segment in segments
        if segment.end_ms > segment.start_ms
    ]
    if not intervals:
        return 0

    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in sorted(intervals):
        if not merged or start_ms > merged[-1][1]:
            merged.append((start_ms, end_ms))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end_ms))
    return sum(end_ms - start_ms for start_ms, end_ms in merged)


def _long_pauses(segments: list[SpeechMetricSegment]) -> list[LongPauseMetric]:
    pauses: list[LongPauseMetric] = []
    previous_end: int | None = None
    for segment in segments:
        if segment.end_ms <= segment.start_ms:
            continue
        if previous_end is not None and segment.start_ms - previous_end >= LONG_PAUSE_THRESHOLD_MS:
            pauses.append(
                LongPauseMetric(
                    start_ms=previous_end,
                    end_ms=segment.start_ms,
                    duration_ms=segment.start_ms - previous_end,
                )
            )
        previous_end = max(previous_end or segment.end_ms, segment.end_ms)
    return pauses


def _filler_counts(segments: list[SpeechMetricSegment]) -> list[PhraseCountMetric]:
    text = "".join(segment.text for segment in segments)
    counts = [
        PhraseCountMetric(phrase=phrase, count=text.count(phrase))
        for phrase in FILLER_PHRASES
        if text.count(phrase) > 0
    ]
    return sorted(counts, key=lambda item: (-item["count"], item["phrase"]))


def _repeated_phrases(segments: list[SpeechMetricSegment]) -> list[RepeatedPhraseMetric]:
    counts: dict[str, int] = {}
    for segment in segments:
        normalized = _normalize_text(segment.text)
        for size in range(2, 7):
            index = 0
            while index + size * 2 <= len(normalized):
                phrase = normalized[index : index + size]
                if phrase == normalized[index + size : index + size * 2]:
                    counts[phrase] = counts.get(phrase, 0) + 1
                    index += size * 2
                else:
                    index += 1
    repeated = [
        RepeatedPhraseMetric(text=text, count=count)
        for text, count in counts.items()
        if _count_text_chars(text) >= 2
    ]
    return sorted(repeated, key=lambda item: (-item["count"], item["text"]))


def _first_conclusion_ms(segments: list[SpeechMetricSegment]) -> int | None:
    for segment in segments:
        if any(marker in segment.text for marker in CONCLUSION_MARKERS):
            return segment.start_ms
    return None


def _count_text_chars(text: str) -> int:
    return sum(1 for char in text if char.isalnum() or _is_cjk(char))


def _normalize_text(text: str) -> str:
    return "".join(char for char in text if char.isalnum() or _is_cjk(char))


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"
