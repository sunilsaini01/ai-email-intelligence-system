"""
Repository for the FR-61 retraining-threshold trigger audit log.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.retraining_trigger import RetrainingTrigger


class RetrainingTriggerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest(self, module: str) -> RetrainingTrigger | None:
        result = await self.session.execute(
            select(RetrainingTrigger)
            .where(RetrainingTrigger.module == module)
            .order_by(RetrainingTrigger.triggered_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, module: str, feedback_count_at_trigger: int, threshold_used: int) -> RetrainingTrigger:
        record = RetrainingTrigger(
            module=module,
            feedback_count_at_trigger=feedback_count_at_trigger,
            threshold_used=threshold_used,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record
