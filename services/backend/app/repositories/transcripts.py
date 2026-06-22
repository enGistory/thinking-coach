from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AttemptTranscript,
    TrainingSession,
    TranscriptCorrection,
    TranscriptSegment,
    VoiceAttempt,
)


@dataclass(frozen=True)
class TranscriptSegmentWrite:
    segment_index: int
    start_ms: int
    end_ms: int
    raw_text: str
    corrected_text: str
    words_json: list[dict[str, object]]


@dataclass(frozen=True)
class TranscriptBundle:
    transcript: AttemptTranscript
    segments: list[TranscriptSegment]


class TranscriptCorrectionRejected(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_pending(self, attempt_id: UUID) -> AttemptTranscript:
        await self._session.execute(
            insert(AttemptTranscript)
            .values(attempt_id=attempt_id, status="PENDING", raw_text="", corrected_text="")
            .on_conflict_do_nothing(index_elements=["attempt_id"])
        )
        transcript = await self._get_by_attempt_id(attempt_id)
        if transcript is None:
            raise RuntimeError("attempt transcript upsert did not return a row")
        return transcript

    async def mark_running(self, attempt_id: UUID) -> AttemptTranscript:
        transcript = await self.ensure_pending(attempt_id)
        if transcript.status != "SUCCEEDED":
            transcript.status = "RUNNING"
            transcript.error_code = None
        await self._session.flush()
        return transcript

    async def mark_pending(
        self,
        attempt_id: UUID,
        error_code: str | None = None,
    ) -> AttemptTranscript:
        transcript = await self.ensure_pending(attempt_id)
        if transcript.status != "SUCCEEDED":
            transcript.status = "PENDING"
            transcript.error_code = error_code
        await self._session.flush()
        return transcript

    async def mark_failed(self, attempt_id: UUID, error_code: str) -> AttemptTranscript:
        transcript = await self.ensure_pending(attempt_id)
        if transcript.status != "SUCCEEDED":
            transcript.status = "FAILED"
            transcript.error_code = error_code
        await self._session.flush()
        return transcript

    async def upsert_success(
        self,
        *,
        attempt_id: UUID,
        raw_text: str,
        corrected_text: str,
        language: str | None,
        provider: str,
        model: str,
        request_id: str | None,
        latency_ms: int,
        metrics_json: dict[str, object],
        segments: list[TranscriptSegmentWrite],
    ) -> AttemptTranscript:
        transcript = await self.ensure_pending(attempt_id)
        if transcript.status == "SUCCEEDED":
            return transcript

        await self._session.execute(
            delete(TranscriptSegment).where(TranscriptSegment.attempt_id == attempt_id)
        )
        transcript.status = "SUCCEEDED"
        transcript.raw_text = raw_text
        transcript.corrected_text = corrected_text
        transcript.language = language
        transcript.provider = provider
        transcript.model = model
        transcript.request_id = request_id
        transcript.latency_ms = latency_ms
        transcript.error_code = None
        transcript.metrics_json = metrics_json
        transcript.completed_at = datetime.now(UTC)
        self._session.add_all(
            [
                TranscriptSegment(
                    attempt_id=attempt_id,
                    segment_index=segment.segment_index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    raw_text=segment.raw_text,
                    corrected_text=segment.corrected_text,
                    words_json=segment.words_json,
                    source="asr",
                )
                for segment in segments
            ]
        )
        await self._session.flush()
        return transcript

    async def get_owned_bundle(self, *, attempt_id: UUID, user_id: UUID) -> TranscriptBundle | None:
        transcript = await self._get_owned_transcript(attempt_id=attempt_id, user_id=user_id)
        if transcript is None:
            return None
        return TranscriptBundle(
            transcript=transcript,
            segments=await self._segments_for_attempt(attempt_id),
        )

    async def apply_segment_correction(
        self,
        *,
        attempt_id: UUID,
        segment_id: UUID,
        user_id: UUID,
        corrected_text: str,
        reason: str,
    ) -> TranscriptBundle | None:
        segment = await self._get_owned_segment_for_update(
            attempt_id=attempt_id,
            segment_id=segment_id,
            user_id=user_id,
        )
        if segment is None:
            return None

        _validate_correction_size(
            raw_text=segment.raw_text,
            corrected_text=corrected_text,
        )
        self._session.add(
            TranscriptCorrection(
                attempt_id=attempt_id,
                segment_id=segment_id,
                user_id=user_id,
                raw_text=segment.raw_text,
                previous_corrected_text=segment.corrected_text,
                corrected_text=corrected_text,
                reason=reason,
            )
        )
        segment.corrected_text = corrected_text
        await self._session.flush()

        transcript = await self._get_owned_transcript_for_update(
            attempt_id=attempt_id,
            user_id=user_id,
        )
        if transcript is None:
            return None
        segments = await self._segments_for_attempt(attempt_id)
        transcript.corrected_text = "".join(item.corrected_text for item in segments)
        await self._session.flush()
        return TranscriptBundle(transcript=transcript, segments=segments)

    async def _get_by_attempt_id(self, attempt_id: UUID) -> AttemptTranscript | None:
        result = await self._session.execute(
            select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def _get_owned_transcript(
        self,
        *,
        attempt_id: UUID,
        user_id: UUID,
    ) -> AttemptTranscript | None:
        result = await self._session.execute(
            select(AttemptTranscript)
            .join(VoiceAttempt, AttemptTranscript.attempt_id == VoiceAttempt.id)
            .join(TrainingSession, VoiceAttempt.session_id == TrainingSession.id)
            .where(AttemptTranscript.attempt_id == attempt_id, TrainingSession.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_owned_transcript_for_update(
        self,
        *,
        attempt_id: UUID,
        user_id: UUID,
    ) -> AttemptTranscript | None:
        result = await self._session.execute(
            select(AttemptTranscript)
            .join(VoiceAttempt, AttemptTranscript.attempt_id == VoiceAttempt.id)
            .join(TrainingSession, VoiceAttempt.session_id == TrainingSession.id)
            .where(AttemptTranscript.attempt_id == attempt_id, TrainingSession.user_id == user_id)
            .with_for_update(of=AttemptTranscript)
        )
        return result.scalar_one_or_none()

    async def _get_owned_segment_for_update(
        self,
        *,
        attempt_id: UUID,
        segment_id: UUID,
        user_id: UUID,
    ) -> TranscriptSegment | None:
        result = await self._session.execute(
            select(TranscriptSegment)
            .join(VoiceAttempt, TranscriptSegment.attempt_id == VoiceAttempt.id)
            .join(TrainingSession, VoiceAttempt.session_id == TrainingSession.id)
            .where(
                TranscriptSegment.id == segment_id,
                TranscriptSegment.attempt_id == attempt_id,
                TrainingSession.user_id == user_id,
            )
            .with_for_update(of=TranscriptSegment)
        )
        return result.scalar_one_or_none()

    async def _segments_for_attempt(self, attempt_id: UUID) -> list[TranscriptSegment]:
        result = await self._session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.attempt_id == attempt_id)
            .order_by(TranscriptSegment.segment_index)
        )
        return list(result.scalars().all())


def _validate_correction_size(*, raw_text: str, corrected_text: str) -> None:
    original = _normalize_for_correction(raw_text)
    corrected = _normalize_for_correction(corrected_text)
    if not original:
        raise TranscriptCorrectionRejected("TRANSCRIPT_CORRECTION_EMPTY_BASE")
    if not corrected:
        raise TranscriptCorrectionRejected("TRANSCRIPT_CORRECTION_EMPTY")

    max_length = max(len(original) * 2, len(original) + 20)
    if len(corrected) > max_length:
        raise TranscriptCorrectionRejected("TRANSCRIPT_CORRECTION_TOO_LARGE")

    max_distance = max(3, round(len(original) * 0.6))
    if _levenshtein_distance(original, corrected) > max_distance:
        raise TranscriptCorrectionRejected("TRANSCRIPT_CORRECTION_TOO_LARGE")


def _normalize_for_correction(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or _is_cjk(char))


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
