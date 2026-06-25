from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from random import Random
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AppUser, PushSubscription, TrainingSession, UserTrainingPolicy
from app.domain.random_strike import (
    MAX_DEFER_COUNT,
    DefectSignal,
    QuestionCandidate,
    can_schedule_strike,
    choose_strike_question,
    random_scheduled_at,
    should_enqueue_inventory_job,
)
from app.repositories.auth import UserRepository
from app.repositories.defects import DefectMemoryRepository
from app.repositories.jobs import AIJobRepository
from app.repositories.push import PushSubscriptionRepository
from app.repositories.source_questions import SourceQuestionRepository
from app.repositories.training_policy import TrainingPolicyRepository
from app.repositories.trainings import TrainingRepository
from app.services.push import (
    PushDeliveryResult,
    WebPushSender,
    strike_notification_payload,
)


class RandomStrikeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ScheduledStrikeResult:
    session: TrainingSession | None
    inventory_job_enqueued: bool


class RandomStrikeService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        push_sender: WebPushSender,
    ) -> None:
        self._session = session
        self._settings = settings
        self._push_sender = push_sender
        self._training_repo = TrainingRepository(session)
        self._source_repo = SourceQuestionRepository(session)
        self._job_repo = AIJobRepository(session)
        self._push_repo = PushSubscriptionRepository(session)

    async def schedule_for_all_users(
        self,
        *,
        now: datetime,
        rng: Random,
    ) -> list[ScheduledStrikeResult]:
        users = await UserRepository(self._session).list_active_users()
        results: list[ScheduledStrikeResult] = []
        for user in users:
            results.append(await self.schedule_for_user(user=user, now=now, rng=rng))
        return results

    async def schedule_for_user(
        self,
        *,
        user: AppUser,
        now: datetime,
        rng: Random,
    ) -> ScheduledStrikeResult:
        if await self._training_repo.latest_active_audio_session(user.id) is not None:
            return ScheduledStrikeResult(session=None, inventory_job_enqueued=False)

        policy = await TrainingPolicyRepository(self._session).get_for_user(user.id)
        if policy is None:
            return ScheduledStrikeResult(session=None, inventory_job_enqueued=False)

        ready_count = await self._source_repo.ready_question_count_for_user(user.id)
        inventory_enqueued = False
        if should_enqueue_inventory_job(ready_count):
            await self._job_repo.enqueue_prepare_questions(user_id=user.id)
            inventory_enqueued = True

        daily_count = await self._daily_count(user_id=user.id, policy=policy, now=now)
        if not can_schedule_strike(
            ready_count=ready_count,
            daily_count=daily_count,
            daily_max=policy.daily_max,
        ):
            return ScheduledStrikeResult(session=None, inventory_job_enqueued=inventory_enqueued)

        scheduled_at = random_scheduled_at(policy=policy, now=now, rng=rng)
        if scheduled_at is None:
            return ScheduledStrikeResult(session=None, inventory_job_enqueued=inventory_enqueued)

        candidates = [
            QuestionCandidate(
                id=question.id,
                target_defects=tuple(str(code) for code in question.target_defects),
                ready_at=question.ready_at,
            )
            for question in await self._source_repo.list_ready_questions_for_user(user.id)
        ]
        profiles = [
            DefectSignal(
                code=row.profile.defect_code,
                state=row.profile.state,
                priority=row.profile.priority,
                last_seen_at=row.profile.last_seen_at,
            )
            for row in await DefectMemoryRepository(self._session).list_profiles(user.id)
        ]
        recent_groups = await self._training_repo.recent_completed_defect_groups(user_id=user.id)
        decision = choose_strike_question(
            candidates=candidates,
            defect_signals=profiles,
            recent_defect_groups=recent_groups,
            now=now,
            rng=rng,
        )
        if decision is None:
            return ScheduledStrikeResult(session=None, inventory_job_enqueued=inventory_enqueued)

        training_session = await self._training_repo.create_scheduled_session(
            user_id=user.id,
            question_id=decision.question_id,
            scheduled_at=scheduled_at,
            delivery_decision={
                **decision.as_json(),
                "scheduled_at": scheduled_at.isoformat(),
                "ready_count": ready_count,
                "daily_count": daily_count,
            },
        )
        return ScheduledStrikeResult(
            session=training_session,
            inventory_job_enqueued=inventory_enqueued,
        )

    async def send_due_notifications(self, *, now: datetime) -> int:
        due_sessions = await self._training_repo.list_due_scheduled(now=now)
        sent_count = 0
        for training_session in due_sessions:
            subscriptions = await self._push_repo.list_active_for_user(training_session.user_id)
            if not subscriptions:
                await self._training_repo.mark_notification_failed(
                    training_session,
                    error_code="NO_ACTIVE_PUSH_SUBSCRIPTION",
                )
                continue
            result = await self._send_to_any_subscription(
                training_session=training_session,
                subscriptions=subscriptions,
            )
            if result.delivered:
                expires_at = now + timedelta(minutes=self._settings.strike_notification_ttl_minutes)
                await self._training_repo.mark_notified(
                    training_session,
                    notified_at=now,
                    expires_at=expires_at,
                )
                sent_count += 1
            else:
                await self._training_repo.mark_notification_failed(
                    training_session,
                    error_code=result.error_code or "WEB_PUSH_FAILED",
                )
        return sent_count

    async def expire_notifications(self, *, now: datetime) -> int:
        expired = await self._training_repo.list_expired_notified(now=now)
        for training_session in expired:
            await self._training_repo.expire_notified(training_session)
        return len(expired)

    async def accept(self, *, training_session: TrainingSession, now: datetime) -> None:
        if training_session.stage != "NOTIFIED":
            raise RandomStrikeError("TRAINING_NOT_ACCEPTABLE")
        if (
            training_session.notification_expires_at is None
            or training_session.notification_expires_at <= now
        ):
            await self._training_repo.expire_notified(training_session)
            raise RandomStrikeError("TRAINING_NOTIFICATION_EXPIRED")
        if training_session.question_id is None:
            raise RandomStrikeError("TRAINING_QUESTION_MISSING")
        question = await self._source_repo.get_question(training_session.question_id)
        if question is None or question.status != "READY" or question.exposed_count != 0:
            training_session.stage = "INVALID"
            raise RandomStrikeError("TRAINING_QUESTION_NOT_READY")
        await self._training_repo.accept_notified(training_session, accepted_at=now)
        await self._source_repo.mark_question_exposed(question)

    async def defer(self, *, training_session: TrainingSession, now: datetime, rng: Random) -> None:
        if training_session.stage != "NOTIFIED":
            raise RandomStrikeError("TRAINING_NOT_DEFERABLE")
        if training_session.deferred_count >= MAX_DEFER_COUNT:
            raise RandomStrikeError("TRAINING_DEFER_LIMIT_REACHED")
        if (
            training_session.notification_expires_at is None
            or training_session.notification_expires_at <= now
        ):
            await self._training_repo.expire_notified(training_session)
            raise RandomStrikeError("TRAINING_NOTIFICATION_EXPIRED")
        policy = await TrainingPolicyRepository(self._session).get_for_user(
            training_session.user_id
        )
        if policy is None:
            raise RandomStrikeError("TRAINING_POLICY_MISSING")
        scheduled_at = random_scheduled_at(policy=policy, now=now + timedelta(minutes=1), rng=rng)
        if scheduled_at is None:
            raise RandomStrikeError("TRAINING_NO_ALLOWED_WINDOW")
        await self._training_repo.defer_notified(training_session, scheduled_at=scheduled_at)

    async def abandon(self, *, training_session: TrainingSession) -> None:
        if training_session.stage not in {
            "WAIT_FIRST_AUDIO",
            "WAIT_FOLLOWUP_AUDIO",
            "WAIT_FINAL_AUDIO",
        }:
            raise RandomStrikeError("TRAINING_NOT_ABANDONABLE")
        await self._training_repo.abandon_exposed(training_session)

    async def _send_to_any_subscription(
        self,
        *,
        training_session: TrainingSession,
        subscriptions: list[PushSubscription],
    ) -> PushDeliveryResult:
        payload = strike_notification_payload(
            session_id=str(training_session.id),
            web_base_url=self._settings.web_base_url,
        )
        last_error = "WEB_PUSH_FAILED"
        for subscription in subscriptions:
            result = await self._push_sender.send(subscription=subscription, payload=payload)
            if result.delivered:
                return result
            last_error = result.error_code or last_error
            if result.deactivate:
                await self._push_repo.mark_inactive(subscription, error_code=last_error)
        return PushDeliveryResult(delivered=False, error_code=last_error)

    async def _daily_count(
        self,
        *,
        user_id: UUID,
        policy: UserTrainingPolicy,
        now: datetime,
    ) -> int:
        timezone = ZoneInfo(policy.timezone)
        local_now = now.astimezone(timezone)
        day_start = datetime.combine(local_now.date(), time.min, tzinfo=timezone).astimezone(UTC)
        day_end = datetime.combine(
            local_now.date() + timedelta(days=1),
            time.min,
            tzinfo=timezone,
        ).astimezone(UTC)
        return await self._training_repo.count_for_local_day(
            user_id=user_id,
            day_start_utc=day_start,
            day_end_utc=day_end,
        )
