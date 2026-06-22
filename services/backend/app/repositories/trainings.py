from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TrainingSession, VoiceAttempt


class TrainingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_current_audio_session(self, user_id: UUID) -> TrainingSession:
        latest = await self._latest_waiting_first_audio_session(user_id)
        if latest is not None and not await self._has_uploaded_first_attempt(latest.id):
            return latest

        session_id = uuid4()
        training_session = TrainingSession(
            id=session_id,
            user_id=user_id,
            thread_id=str(session_id),
            stage="WAIT_FIRST_AUDIO",
        )
        self._session.add(training_session)
        await self._session.flush()
        return training_session

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

    async def _latest_waiting_first_audio_session(self, user_id: UUID) -> TrainingSession | None:
        result = await self._session.execute(
            select(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.stage == "WAIT_FIRST_AUDIO",
                TrainingSession.question_id.is_(None),
            )
            .order_by(TrainingSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _has_uploaded_first_attempt(self, session_id: UUID) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    VoiceAttempt.session_id == session_id,
                    VoiceAttempt.stage == "FIRST",
                    VoiceAttempt.round == 1,
                    VoiceAttempt.upload_status == "UPLOADED",
                )
            )
        )
        return bool(result.scalar_one())

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
