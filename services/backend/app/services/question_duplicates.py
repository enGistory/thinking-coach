from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIJob, QuestionDuplicateComplaint
from app.repositories.defects import DefectMemoryRepository
from app.repositories.jobs import AIJobRepository
from app.repositories.source_questions import SourceQuestionRepository


class DuplicateQuestionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DuplicateComplaintResult:
    complaint: QuestionDuplicateComplaint
    replacement_job: AIJob


class DuplicateQuestionService:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session
        self._source_repo = SourceQuestionRepository(session)
        self._defect_repo = DefectMemoryRepository(session)
        self._job_repo = AIJobRepository(session)

    async def create_complaint(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        reason: str,
        duplicate_type: str,
        similar_question_id: UUID | None,
    ) -> DuplicateComplaintResult:
        target = await self._source_repo.get_duplicate_complaint_target(
            user_id=user_id,
            session_id=session_id,
        )
        if target is None:
            raise DuplicateQuestionError("DUPLICATE_COMPLAINT_TARGET_NOT_FOUND")
        if similar_question_id is not None:
            similar = await self._source_repo.get_question(similar_question_id, user_id=user_id)
            if similar is None:
                raise DuplicateQuestionError("DUPLICATE_SIMILAR_QUESTION_NOT_FOUND")
        if target.existing_complaint is not None:
            replacement_job = await self._job_repo.get_prepare_questions_job(user_id=user_id)
            if replacement_job is None:
                replacement_job = await self._job_repo.enqueue_prepare_questions(user_id=user_id)
            return DuplicateComplaintResult(
                complaint=target.existing_complaint,
                replacement_job=replacement_job,
            )

        await self._source_repo.ensure_template_denylist(
            user_id=user_id,
            template_family=target.fingerprint.template_family,
            trigger_question_id=target.question.id,
            reason=reason,
        )
        complaint = await self._source_repo.create_duplicate_complaint(
            user_id=user_id,
            session_id=target.training_session.id,
            question_id=target.question.id,
            similar_question_id=similar_question_id,
            duplicate_type=duplicate_type,
            template_family=target.fingerprint.template_family,
            reason=reason,
        )
        await self._source_repo.invalidate_question(target.question.id)
        await self._source_repo.invalidate_report_scores_for_session(target.training_session.id)
        await self._defect_repo.exclude_session_occurrences(
            user_id=user_id,
            session_id=target.training_session.id,
        )
        replacement_job = await self._job_repo.enqueue_prepare_questions(user_id=user_id)
        return DuplicateComplaintResult(complaint=complaint, replacement_job=replacement_job)
