from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Question, TrainingSession, VoiceAttempt

TERMINAL_SESSION_STAGES = ("COMPLETED", "EXPIRED", "ABANDONED", "INVALID", "FAILED_RETRYABLE")
VISIBLE_CURRENT_SESSION_STAGES = (
    "ACCEPTED",
    "QUESTION_EXPOSED",
    "WAIT_FIRST_AUDIO",
    "PROCESS_FIRST",
    "WAIT_FOLLOWUP_AUDIO",
    "PROCESS_FOLLOWUP",
    "WAIT_FINAL_AUDIO",
    "EVALUATING",
)


class TrainingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_active_audio_session(self, user_id: UUID) -> TrainingSession | None:
        return await self._latest_active_audio_session(user_id)

    async def current_visible_session(
        self,
        user_id: UUID,
        *,
        now: datetime,
    ) -> TrainingSession | None:
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                or_(
                    and_(
                        TrainingSession.stage == "NOTIFIED",
                        TrainingSession.notification_expires_at.is_not(None),
                        TrainingSession.notification_expires_at > now,
                    ),
                    TrainingSession.stage.in_(VISIBLE_CURRENT_SESSION_STAGES),
                ),
            )
            .order_by(TrainingSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_scheduled_session(
        self,
        *,
        user_id: UUID,
        question_id: UUID,
        scheduled_at: datetime,
        delivery_decision: dict[str, object],
    ) -> TrainingSession:
        latest = await self._latest_active_audio_session(user_id)
        if latest is not None:
            return latest

        session_id = uuid4()
        training_session = TrainingSession(
            id=session_id,
            user_id=user_id,
            question_id=question_id,
            thread_id=str(session_id),
            stage="SCHEDULED",
            scheduled_at=scheduled_at,
            delivery_decision_json=delivery_decision,
            push_status="PENDING",
        )
        self._session.add(training_session)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            existing_after_race = await self._latest_active_audio_session(user_id)
            if existing_after_race is None:
                raise
            return existing_after_race
        else:
            return training_session

    async def create_audio_session_for_question(
        self,
        *,
        user_id: UUID,
        question_id: UUID,
    ) -> TrainingSession:
        latest = await self._latest_active_audio_session(user_id)
        if latest is not None:
            return latest

        session_id = uuid4()
        training_session = TrainingSession(
            id=session_id,
            user_id=user_id,
            question_id=question_id,
            thread_id=str(session_id),
            stage="WAIT_FIRST_AUDIO",
        )
        self._session.add(training_session)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            existing_after_race = await self._latest_active_audio_session(user_id)
            if existing_after_race is None:
                raise
            return existing_after_race
        else:
            return training_session

    async def list_due_scheduled(
        self,
        *,
        now: datetime,
        limit: int = 50,
    ) -> list[TrainingSession]:
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.stage == "SCHEDULED",
                TrainingSession.scheduled_at <= now,
            )
            .order_by(TrainingSession.scheduled_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_expired_notified(
        self,
        *,
        now: datetime,
        limit: int = 50,
    ) -> list[TrainingSession]:
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.stage == "NOTIFIED",
                TrainingSession.notification_expires_at.is_not(None),
                TrainingSession.notification_expires_at <= now,
            )
            .order_by(TrainingSession.notification_expires_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_notified(
        self,
        training_session: TrainingSession,
        *,
        notified_at: datetime,
        expires_at: datetime,
    ) -> None:
        training_session.stage = "NOTIFIED"
        training_session.notified_at = notified_at
        training_session.notification_expires_at = expires_at
        training_session.push_status = "SUCCEEDED"
        training_session.push_error_code = None
        await self._session.flush()

    async def mark_notification_failed(
        self,
        training_session: TrainingSession,
        *,
        error_code: str,
    ) -> None:
        training_session.stage = "EXPIRED"
        training_session.push_status = "FAILED"
        training_session.push_error_code = error_code
        await self._session.flush()

    async def expire_notified(
        self,
        training_session: TrainingSession,
        *,
        error_code: str = "NOTIFICATION_EXPIRED",
    ) -> None:
        training_session.stage = "EXPIRED"
        training_session.push_status = "EXPIRED"
        training_session.push_error_code = error_code
        await self._session.flush()

    async def accept_notified(
        self,
        training_session: TrainingSession,
        *,
        accepted_at: datetime,
    ) -> None:
        training_session.stage = "WAIT_FIRST_AUDIO"
        training_session.accepted_at = accepted_at
        training_session.exposed_at = accepted_at
        await self._session.flush()

    async def defer_notified(
        self,
        training_session: TrainingSession,
        *,
        scheduled_at: datetime,
    ) -> None:
        training_session.stage = "SCHEDULED"
        training_session.scheduled_at = scheduled_at
        training_session.notified_at = None
        training_session.notification_expires_at = None
        training_session.deferred_count += 1
        training_session.push_status = "PENDING"
        training_session.push_error_code = None
        await self._session.flush()

    async def abandon_exposed(
        self,
        training_session: TrainingSession,
    ) -> None:
        training_session.stage = "ABANDONED"
        await self._session.flush()

    async def count_for_local_day(
        self,
        *,
        user_id: UUID,
        day_start_utc: datetime,
        day_end_utc: datetime,
    ) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.scheduled_at >= day_start_utc,
                TrainingSession.scheduled_at < day_end_utc,
                TrainingSession.stage != "INVALID",
            )
        )
        return int(result.scalar_one())

    async def recent_completed_defect_groups(
        self,
        *,
        user_id: UUID,
        limit: int = 2,
    ) -> list[tuple[str, ...]]:
        result = await self._session.execute(
            select(Question.target_defects)
            .select_from(TrainingSession)
            .join(Question, TrainingSession.question_id == Question.id)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.question_id.is_not(None),
                TrainingSession.stage.in_(("COMPLETED", "ABANDONED")),
            )
            .order_by(
                TrainingSession.completed_at.desc().nullslast(),
                TrainingSession.exposed_at.desc().nullslast(),
                TrainingSession.created_at.desc(),
            )
            .limit(limit)
        )
        return [tuple(str(code) for code in defects) for defects in result.scalars().all()]

    async def get_owned_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> TrainingSession | None:
        result = await self._session.execute(
            select(TrainingSession).where(
                TrainingSession.id == session_id,
                TrainingSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_owned_session_for_update(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> TrainingSession | None:
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.id == session_id,
                TrainingSession.user_id == user_id,
            )
            .with_for_update(of=TrainingSession)
        )
        return result.scalar_one_or_none()

    async def get_or_create_attempt(
        self,
        *,
        training_session: TrainingSession,
        stage: str,
        round_number: int,
    ) -> VoiceAttempt:
        existing = await self._get_attempt_by_slot(
            training_session.id,
            stage=stage,
            round_number=round_number,
        )
        if existing is not None:
            return existing

        attempt = VoiceAttempt(
            session_id=training_session.id,
            stage=stage,
            round=round_number,
            upload_status="PENDING",
        )
        self._session.add(attempt)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            existing_after_race = await self._get_attempt_by_slot(
                training_session.id,
                stage=stage,
                round_number=round_number,
            )
            if existing_after_race is None:
                raise
            return existing_after_race
        else:
            return attempt

    async def get_owned_attempt_for_update(
        self,
        *,
        attempt_id: UUID,
        user_id: UUID,
    ) -> VoiceAttempt | None:
        result = await self._session.execute(
            select(VoiceAttempt)
            .join(TrainingSession, VoiceAttempt.session_id == TrainingSession.id)
            .where(
                VoiceAttempt.id == attempt_id,
                TrainingSession.user_id == user_id,
            )
            .with_for_update(of=VoiceAttempt)
        )
        return result.scalar_one_or_none()

    async def get_owned_attempt(
        self,
        *,
        attempt_id: UUID,
        user_id: UUID,
    ) -> VoiceAttempt | None:
        result = await self._session.execute(
            select(VoiceAttempt)
            .join(TrainingSession, VoiceAttempt.session_id == TrainingSession.id)
            .where(
                VoiceAttempt.id == attempt_id,
                TrainingSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_attempt_with_session(
        self,
        attempt_id: UUID,
    ) -> tuple[VoiceAttempt, TrainingSession] | None:
        result = await self._session.execute(
            select(VoiceAttempt, TrainingSession)
            .join(TrainingSession, VoiceAttempt.session_id == TrainingSession.id)
            .where(VoiceAttempt.id == attempt_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    async def get_attempt_by_slot(
        self,
        *,
        session_id: UUID,
        stage: str,
        round_number: int,
    ) -> VoiceAttempt | None:
        return await self._get_attempt_by_slot(
            session_id,
            stage=stage,
            round_number=round_number,
        )

    async def _latest_active_audio_session(self, user_id: UUID) -> TrainingSession | None:
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.stage.not_in(TERMINAL_SESSION_STAGES),
            )
            .order_by(TrainingSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_attempt_by_slot(
        self,
        session_id: UUID,
        *,
        stage: str,
        round_number: int,
    ) -> VoiceAttempt | None:
        result = await self._session.execute(
            select(VoiceAttempt).where(
                VoiceAttempt.session_id == session_id,
                VoiceAttempt.stage == stage,
                VoiceAttempt.round == round_number,
            )
        )
        return result.scalar_one_or_none()
