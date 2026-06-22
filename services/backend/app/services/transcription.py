from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.contracts import (
    STTProvider,
    STTRequest,
    STTResponse,
)
from app.ai.providers.contracts import (
    TranscriptSegment as ProviderTranscriptSegment,
)
from app.core.config import Settings
from app.db.models import AttemptTranscript, TrainingSession, VoiceAttempt
from app.domain.speech_metrics import SpeechMetricSegment, calculate_speech_metrics
from app.repositories.trainings import TrainingRepository
from app.repositories.transcripts import TranscriptRepository, TranscriptSegmentWrite
from app.services.audio_access import (
    AudioAccessError,
    TranscriptionAudioAccess,
    build_transcription_audio_access,
    cleanup_transcription_audio_access,
)

logger = logging.getLogger(__name__)


class TranscriptionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AttemptContext:
    attempt: VoiceAttempt
    training_session: TrainingSession


class TranscriptionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        stt_provider: STTProvider,
    ) -> None:
        self._session = session
        self._settings = settings
        self._stt_provider = stt_provider

    async def transcribe_attempt(
        self,
        attempt_id: UUID,
        *,
        mark_failed_on_error: bool = True,
    ) -> AttemptTranscript:
        context = await self._attempt_context(attempt_id)
        attempt = context.attempt
        if attempt.upload_status != "UPLOADED" or attempt.audio_path is None:
            raise TranscriptionError("AUDIO_NOT_UPLOADED", "Attempt audio has not been uploaded")

        transcript_repo = TranscriptRepository(self._session)
        running = await transcript_repo.mark_running(attempt.id)
        await self._session.commit()
        if running.status == "SUCCEEDED":
            return running

        audio_access: TranscriptionAudioAccess | None = None
        try:
            audio_access = await build_transcription_audio_access(
                settings=self._settings,
                attempt=attempt,
                user_id=context.training_session.user_id,
            )
            response = await self._stt_provider.transcribe(STTRequest(audio_url=audio_access.url))
            stored = await transcript_repo.upsert_success(
                attempt_id=attempt.id,
                raw_text=_transcript_text(response),
                corrected_text=_transcript_text(response),
                language=response.transcript.language,
                provider=response.metadata.provider,
                model=response.metadata.model,
                request_id=response.metadata.request_id,
                latency_ms=response.metadata.latency_ms,
                metrics_json=_metrics_for_response(attempt, response),
                segments=_segment_writes(response.transcript.segments),
            )
            await self._session.commit()
            return stored
        except Exception as exc:
            await self._session.rollback()
            if mark_failed_on_error:
                await transcript_repo.mark_failed(attempt.id, _error_code(exc))
                await self._session.commit()
            raise
        finally:
            if audio_access is not None:
                await self._cleanup_audio_access(audio_access)

    async def _cleanup_audio_access(self, audio_access: TranscriptionAudioAccess) -> None:
        try:
            await cleanup_transcription_audio_access(
                settings=self._settings,
                access=audio_access,
            )
        except AudioAccessError as exc:
            logger.warning(
                "transcription audio cleanup failed",
                extra={"error_code": exc.code},
            )

    async def _attempt_context(self, attempt_id: UUID) -> AttemptContext:
        result = await TrainingRepository(self._session).get_attempt_with_session(attempt_id)
        if result is None:
            raise TranscriptionError("ATTEMPT_NOT_FOUND", "Attempt was not found")
        attempt, training_session = result
        return AttemptContext(attempt=attempt, training_session=training_session)


def _transcript_text(response: STTResponse) -> str:
    if response.transcript.text.strip():
        return response.transcript.text.strip()
    return "".join(segment.text for segment in response.transcript.segments).strip()


def _metrics_for_response(
    attempt: VoiceAttempt,
    response: STTResponse,
) -> dict[str, object]:
    audio_duration_ms = attempt.duration_ms
    if audio_duration_ms is None and response.metadata.usage.audio_duration_seconds is not None:
        audio_duration_ms = round(response.metadata.usage.audio_duration_seconds * 1000)
    metrics = calculate_speech_metrics(
        audio_duration_ms=audio_duration_ms,
        segments=[
            SpeechMetricSegment(
                start_ms=_seconds_to_ms(segment.start_seconds),
                end_ms=_seconds_to_ms(segment.end_seconds),
                text=segment.text,
            )
            for segment in response.transcript.segments
        ],
    )
    return dict(metrics)


def _segment_writes(
    segments: list[ProviderTranscriptSegment],
) -> list[TranscriptSegmentWrite]:
    return [
        TranscriptSegmentWrite(
            segment_index=index,
            start_ms=_seconds_to_ms(segment.start_seconds),
            end_ms=_seconds_to_ms(segment.end_seconds),
            raw_text=segment.text,
            corrected_text=segment.text,
            words_json=[
                {
                    "text": word.text,
                    "start_ms": _seconds_to_ms(word.start_seconds),
                    "end_ms": _seconds_to_ms(word.end_seconds),
                    "confidence": word.confidence,
                }
                for word in segment.words
            ],
        )
        for index, segment in enumerate(segments)
    ]


def _seconds_to_ms(value: float) -> int:
    return max(0, round(value * 1000))


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    return code if isinstance(code, str) and code else exc.__class__.__name__.upper()
