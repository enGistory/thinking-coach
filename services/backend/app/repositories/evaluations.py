from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.contracts import ProviderCallMetadata
from app.db.models import (
    AttemptTranscript,
    EvaluationIssue,
    EvaluationReport,
    ModelRun,
    PromptVersion,
    QuestionRubric,
    TrainingSession,
    TranscriptSegment,
    VoiceAttempt,
)
from app.schemas.evaluation import EvidenceVerification, LogicIssue


@dataclass(frozen=True)
class EvaluationAttemptBundle:
    attempt: VoiceAttempt
    transcript: AttemptTranscript
    segments: list[TranscriptSegment]


@dataclass(frozen=True)
class EvaluationContext:
    training_session: TrainingSession
    attempts: dict[str, EvaluationAttemptBundle]


@dataclass(frozen=True)
class IssueWrite:
    issue: LogicIssue
    verification: EvidenceVerification
    attempt_id: UUID
    segment_id: UUID | None


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_context(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> EvaluationContext | None:
        session_result = await self._session.execute(
            select(TrainingSession).where(
                TrainingSession.id == session_id,
                TrainingSession.user_id == user_id,
            )
        )
        training_session = session_result.scalar_one_or_none()
        if training_session is None:
            return None
        attempts_result = await self._session.execute(
            select(VoiceAttempt)
            .where(VoiceAttempt.session_id == session_id)
            .order_by(VoiceAttempt.stage, VoiceAttempt.round)
        )
        attempts: dict[str, EvaluationAttemptBundle] = {}
        for attempt in attempts_result.scalars().all():
            transcript = await self._transcript_for_attempt(attempt.id)
            if transcript is None:
                continue
            segments = await self._segments_for_attempt(attempt.id)
            attempts[attempt.stage] = EvaluationAttemptBundle(
                attempt=attempt,
                transcript=transcript,
                segments=segments,
            )
        return EvaluationContext(training_session=training_session, attempts=attempts)

    async def ensure_question_rubric(
        self,
        *,
        training_session_id: UUID,
        version: str,
        dimensions_json: dict[str, object],
        expected_elements_json: list[str],
        fatal_omissions_json: list[str],
        content_hash: str,
    ) -> QuestionRubric:
        await self._session.execute(
            insert(QuestionRubric)
            .values(
                training_session_id=training_session_id,
                version=version,
                dimensions_json=dimensions_json,
                expected_elements_json=expected_elements_json,
                fatal_omissions_json=fatal_omissions_json,
                content_hash=content_hash,
            )
            .on_conflict_do_nothing(
                index_elements=["training_session_id", "version"],
            )
        )
        result = await self._session.execute(
            select(QuestionRubric).where(
                QuestionRubric.training_session_id == training_session_id,
                QuestionRubric.version == version,
            )
        )
        rubric = result.scalar_one_or_none()
        if rubric is None:
            raise RuntimeError("question rubric upsert did not return a row")
        return rubric

    async def ensure_prompt_version(
        self,
        *,
        name: str,
        version: str,
        content_hash: str,
        schema_version: str,
    ) -> PromptVersion:
        await self._session.execute(
            insert(PromptVersion)
            .values(
                name=name,
                version=version,
                content_hash=content_hash,
                schema_version=schema_version,
                active=True,
            )
            .on_conflict_do_nothing(index_elements=["name", "version"])
        )
        result = await self._session.execute(
            select(PromptVersion).where(
                PromptVersion.name == name,
                PromptVersion.version == version,
            )
        )
        prompt_version = result.scalar_one_or_none()
        if prompt_version is None:
            raise RuntimeError("prompt version upsert did not return a row")
        return prompt_version

    async def get_report_by_session(self, session_id: UUID) -> EvaluationReport | None:
        result = await self._session.execute(
            select(EvaluationReport).where(EvaluationReport.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def start_report(
        self,
        *,
        session_id: UUID,
        rubric_id: UUID,
    ) -> EvaluationReport:
        await self._session.execute(
            insert(EvaluationReport)
            .values(
                session_id=session_id,
                rubric_id=rubric_id,
                status="PENDING",
                details_json={},
            )
            .on_conflict_do_nothing(index_elements=["session_id"])
        )
        report = await self.get_report_by_session(session_id)
        if report is None:
            raise RuntimeError("evaluation report upsert did not return a row")
        if report.status == "COMPLETED":
            return report
        await self._session.execute(
            delete(EvaluationIssue).where(EvaluationIssue.report_id == report.id)
        )
        report.rubric_id = rubric_id
        report.status = "RUNNING"
        report.error_code = None
        report.completed_at = None
        await self._session.flush()
        return report

    async def complete_report(
        self,
        *,
        report: EvaluationReport,
        logic_score: int,
        speech_score: int,
        adaptability_score: int,
        final_score: int,
        details_json: dict[str, object],
        issues: list[IssueWrite],
    ) -> EvaluationReport:
        await self._session.execute(
            delete(EvaluationIssue).where(EvaluationIssue.report_id == report.id)
        )
        report.logic_score = logic_score
        report.speech_score = speech_score
        report.adaptability_score = adaptability_score
        report.final_score = final_score
        report.details_json = details_json
        report.status = "COMPLETED"
        report.error_code = None
        report.completed_at = datetime.now(UTC)
        self._session.add_all(
            [
                EvaluationIssue(
                    report_id=report.id,
                    attempt_id=item.attempt_id,
                    transcript_segment_id=item.segment_id,
                    category=item.issue.category,
                    code=item.issue.code,
                    severity=item.issue.severity,
                    confidence=item.issue.confidence,
                    quote=item.issue.quote,
                    start_ms=item.issue.start_ms,
                    end_ms=item.issue.end_ms,
                    explanation=item.issue.explanation,
                    missing_information=item.issue.missing_information,
                    correction_rule=item.issue.correction_rule,
                    verification_json=item.verification.model_dump(mode="json"),
                )
                for item in issues
            ]
        )
        await self._session.flush()
        return report

    async def mark_report_invalid(self, report: EvaluationReport, error_code: str) -> None:
        report.status = "INVALID"
        report.error_code = error_code
        report.completed_at = datetime.now(UTC)
        await self._session.flush()

    async def record_model_run(
        self,
        *,
        report_id: UUID,
        job_id: UUID | None,
        prompt_name: str,
        prompt_version: str,
        metadata: ProviderCallMetadata,
        input_summary_json: dict[str, object],
        output_json: dict[str, object],
    ) -> ModelRun:
        model_run = ModelRun(
            report_id=report_id,
            job_id=job_id,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            provider=metadata.provider,
            model=metadata.model,
            request_id=metadata.request_id,
            latency_ms=metadata.latency_ms,
            input_tokens=metadata.usage.input_tokens,
            output_tokens=metadata.usage.output_tokens,
            input_characters=metadata.usage.input_characters,
            output_characters=metadata.usage.output_characters,
            structured_ok=metadata.structured_ok,
            error_code=metadata.error_code,
            input_summary_json=input_summary_json,
            output_json=output_json,
        )
        self._session.add(model_run)
        await self._session.flush()
        return model_run

    async def _transcript_for_attempt(self, attempt_id: UUID) -> AttemptTranscript | None:
        result = await self._session.execute(
            select(AttemptTranscript).where(AttemptTranscript.attempt_id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def _segments_for_attempt(self, attempt_id: UUID) -> list[TranscriptSegment]:
        result = await self._session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.attempt_id == attempt_id)
            .order_by(TranscriptSegment.segment_index)
        )
        return list(result.scalars().all())
