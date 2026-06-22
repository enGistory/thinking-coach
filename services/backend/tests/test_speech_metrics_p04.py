from __future__ import annotations

from app.domain.speech_metrics import SpeechMetricSegment, calculate_speech_metrics


def test_speech_metrics_calculates_pauses_fillers_rate_and_conclusion_time() -> None:
    metrics = calculate_speech_metrics(
        audio_duration_ms=10_000,
        segments=[
            SpeechMetricSegment(start_ms=0, end_ms=1000, text="嗯,我认为核心是先定位问题"),
            SpeechMetricSegment(start_ms=2200, end_ms=3600, text="然后然后明确责任"),
            SpeechMetricSegment(start_ms=3900, end_ms=5000, text="风险风险需要复盘"),
        ],
    )

    assert metrics["audio_duration_ms"] == 10_000
    assert metrics["effective_speech_ms"] == 3500
    assert metrics["segment_count"] == 3
    assert metrics["first_conclusion_ms"] == 0
    assert metrics["long_pauses"] == [{"start_ms": 1000, "end_ms": 2200, "duration_ms": 1200}]
    assert {"phrase": "然后", "count": 2} in metrics["filler_phrases"]
    assert metrics["speech_rate_cpm"] is not None
    assert {"text": "风险", "count": 1} in metrics["repeated_phrases"]


def test_speech_metrics_merges_overlapping_segments_for_effective_speech() -> None:
    metrics = calculate_speech_metrics(
        audio_duration_ms=3000,
        segments=[
            SpeechMetricSegment(start_ms=0, end_ms=1200, text="第一段"),
            SpeechMetricSegment(start_ms=1000, end_ms=2000, text="重叠段"),
        ],
    )

    assert metrics["effective_speech_ms"] == 2000
    assert metrics["long_pauses"] == []


def test_speech_metrics_handles_empty_transcript() -> None:
    metrics = calculate_speech_metrics(audio_duration_ms=None, segments=[])

    assert metrics["effective_speech_ms"] == 0
    assert metrics["speech_rate_cpm"] is None
    assert metrics["first_conclusion_ms"] is None
    assert metrics["filler_phrases"] == []
