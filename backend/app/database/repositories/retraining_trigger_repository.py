"""
Repository for the FR-61 retraining-threshold trigger audit log.
"""

from datetime import UTC, datetime

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

    async def create(
        self,
        module: str,
        feedback_count_at_trigger: int,
        threshold_used: int,
        source: str = "feedback_threshold",
        requested_by_user_id: str | None = None,
    ) -> RetrainingTrigger:
        record = RetrainingTrigger(
            module=module,
            feedback_count_at_trigger=feedback_count_at_trigger,
            threshold_used=threshold_used,
            source=source,
            requested_by_user_id=requested_by_user_id,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def has_open_trigger(self, module: str) -> bool:
        """A PENDING or RUNNING trigger already exists for this module --
        used to refuse a duplicate manual request."""
        result = await self.session.execute(
            select(RetrainingTrigger.id)
            .where(RetrainingTrigger.module == module, RetrainingTrigger.status.in_(("PENDING", "RUNNING")))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def claim_next_pending(self) -> RetrainingTrigger | None:
        """Oldest PENDING trigger -> RUNNING. Single agents process (see
        k8s/agents-deployment.yaml's replica count), so no row lock."""
        result = await self.session.execute(
            select(RetrainingTrigger)
            .where(RetrainingTrigger.status == "PENDING")
            .order_by(RetrainingTrigger.triggered_at)
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        record.status = "RUNNING"
        record.consumed = True
        record.started_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def finish(self, record: RetrainingTrigger, status: str, message: str) -> RetrainingTrigger:
        record.status = status
        record.result_message = message
        record.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_recent(self, limit: int = 50) -> list[RetrainingTrigger]:
        result = await self.session.execute(
            select(RetrainingTrigger).order_by(RetrainingTrigger.triggered_at.desc()).limit(limit)
        )
        return list(result.scalars())
