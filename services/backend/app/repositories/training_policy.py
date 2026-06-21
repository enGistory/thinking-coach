from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserTrainingPolicy


class TrainingPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_for_user(
        self,
        *,
        user_id: UUID,
        policy: dict[str, object],
    ) -> UserTrainingPolicy:
        training_policy = UserTrainingPolicy(
            user_id=user_id,
            windows=cast(list[dict[str, object]], policy["windows"]),
            quiet_hours=cast(list[dict[str, object]], policy["quiet_hours"]),
            daily_max=cast(int, policy["daily_max"]),
            retention_days=cast(int, policy["retention_days"]),
            timezone=cast(str, policy["timezone"]),
        )
        self._session.add(training_policy)
        await self._session.flush()
        return training_policy

    async def get_for_user(self, user_id: UUID) -> UserTrainingPolicy | None:
        result = await self._session.execute(
            select(UserTrainingPolicy).where(UserTrainingPolicy.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_for_user(
        self,
        *,
        user_id: UUID,
        policy: dict[str, object],
    ) -> UserTrainingPolicy | None:
        training_policy = await self.get_for_user(user_id)
        if training_policy is None:
            return None
        training_policy.windows = cast(list[dict[str, object]], policy["windows"])
        training_policy.quiet_hours = cast(list[dict[str, object]], policy["quiet_hours"])
        training_policy.daily_max = cast(int, policy["daily_max"])
        training_policy.retention_days = cast(int, policy["retention_days"])
        training_policy.timezone = cast(str, policy["timezone"])
        await self._session.flush()
        return training_policy
