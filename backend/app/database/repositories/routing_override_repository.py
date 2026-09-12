"""Repository for routing_overrides (Phase 21)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.routing_override import RoutingOverride


class RoutingOverrideRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> RoutingOverride:
        record = RoutingOverride(**fields)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_id(self, organization_id: str, override_id: uuid.UUID) -> RoutingOverride | None:
        result = await self.session.execute(
            select(RoutingOverride).where(
                RoutingOverride.organization_id == organization_id,
                RoutingOverride.id == override_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: str) -> list[RoutingOverride]:
        """Every override for this org, active or not -- what the admin
        management screen shows."""
        result = await self.session.execute(
            select(RoutingOverride)
            .where(RoutingOverride.organization_id == organization_id)
            .order_by(RoutingOverride.priority_order.asc())
        )
        return list(result.scalars().all())

    async def list_active_for_organization(self, organization_id: str) -> list[RoutingOverride]:
        """Only what app/routing/overrides.py's evaluator actually needs --
        ordered by priority_order ascending, the exact order it evaluates
        them in (first match wins)."""
        result = await self.session.execute(
            select(RoutingOverride)
            .where(RoutingOverride.organization_id == organization_id, RoutingOverride.is_active.is_(True))
            .order_by(RoutingOverride.priority_order.asc())
        )
        return list(result.scalars().all())

    async def update(self, override: RoutingOverride, **fields) -> RoutingOverride:
        for key, value in fields.items():
            setattr(override, key, value)
        await self.session.commit()
        await self.session.refresh(override)
        return override

    async def delete(self, override: RoutingOverride) -> None:
        # Hard delete, unlike MailboxConnection/EmailRecord's soft-delete:
        # this is a pure configuration row, not a domain record with
        # history worth preserving after removal -- a fired override is
        # already captured as a plain-text "OVERRIDE:{id}:{name}" entry in
        # routing_decision_logs.matched_rules at decision time, so deleting
        # the row here doesn't erase anything from the audit trail.
        await self.session.delete(override)
        await self.session.commit()
