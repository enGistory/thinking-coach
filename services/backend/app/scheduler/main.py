from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from random import Random

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.push import PyWebPushSender
from app.services.random_strike import RandomStrikeService
from app.services.reports import ReportService

SCHEDULER_CHECK_SECONDS = 60
SCHEDULER_DAILY_SECONDS = 24 * 60 * 60
SCHEDULER_WEEKLY_SECONDS = 7 * 24 * 60 * 60


async def run_schedule_generation_once(
    *,
    now: datetime | None = None,
    rng: Random | None = None,
) -> int:
    settings = get_settings()
    maker = get_sessionmaker()
    async with maker() as session:
        results = await RandomStrikeService(
            session=session,
            settings=settings,
            push_sender=PyWebPushSender(settings),
        ).schedule_for_all_users(
            now=now or datetime.now(UTC),
            rng=rng or Random(),
        )
        await session.commit()
        return sum(1 for result in results if result.session is not None)


async def run_due_notifications_once(*, now: datetime | None = None) -> int:
    settings = get_settings()
    settings.validate_push()
    effective_now = now or datetime.now(UTC)
    maker = get_sessionmaker()
    async with maker() as session:
        service = RandomStrikeService(
            session=session,
            settings=settings,
            push_sender=PyWebPushSender(settings),
        )
        expired_count = await service.expire_notifications(now=effective_now)
        sent_count = await service.send_due_notifications(now=effective_now)
        await session.commit()
        return expired_count + sent_count


async def run_weekly_reports_once(*, now: datetime | None = None) -> int:
    maker = get_sessionmaker()
    async with maker() as session:
        reports = await ReportService(session=session).generate_previous_week_for_all_active_users(
            now=now or datetime.now(UTC),
        )
        await session.commit()
        return len(reports)


async def _scheduler_tick() -> None:
    await run_due_notifications_once()


async def _scheduler_daily() -> None:
    await run_schedule_generation_once()


async def _scheduler_weekly() -> None:
    await run_weekly_reports_once()


async def run_scheduler() -> None:
    settings = get_settings()
    settings.validate_ai()
    settings.validate_push()
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(_scheduler_tick, "interval", seconds=SCHEDULER_CHECK_SECONDS)
    scheduler.add_job(_scheduler_daily, "interval", seconds=SCHEDULER_DAILY_SECONDS)
    scheduler.add_job(_scheduler_weekly, "interval", seconds=SCHEDULER_WEEKLY_SECONDS)
    scheduler.start()
    await _scheduler_daily()
    await _scheduler_weekly()
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
