from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PushSubscription


class PushSubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_subscription(
        self,
        *,
        user_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str,
    ) -> PushSubscription:
        await self._session.execute(
            insert(PushSubscription)
            .values(
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
                active=True,
                last_error_code=None,
            )
            .on_conflict_do_update(
                index_elements=["endpoint"],
                set_={
                    "user_id": user_id,
                    "p256dh": p256dh,
                    "auth": auth,
                    "user_agent": user_agent,
                    "active": True,
                    "last_error_code": None,
                },
            )
        )
        result = await self._session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        subscription = result.scalar_one_or_none()
        if subscription is None:
            raise RuntimeError("push subscription upsert did not return a row")
        return subscription

    async def list_active_for_user(self, user_id: UUID) -> list[PushSubscription]:
        result = await self._session.execute(
            select(PushSubscription)
            .where(
                PushSubscription.user_id == user_id,
                PushSubscription.active.is_(True),
            )
            .order_by(PushSubscription.created_at)
        )
        return list(result.scalars().all())

    async def mark_inactive(
        self,
        subscription: PushSubscription,
        *,
        error_code: str,
    ) -> None:
        subscription.active = False
        subscription.last_error_code = error_code
        await self._session.flush()
