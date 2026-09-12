"""
Bridges RoutingOverrideRepository (ORM rows) to app/routing/overrides.py's
pure evaluator (Phase 21). Kept as its own thin module rather than folded
into RoutingService itself: RoutingService.route() is a synchronous, DB-free
composition function called via a threadpool from BOTH the synchronous API
endpoint and the async Orchestrator (app/agents/orchestrator.py) -- giving
it an async DB dependency would break that shared, already-tested contract
for both callers. This function is the async step each caller runs
separately, right after route() returns, before persisting or acting on
the decision.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.routing_override_repository import RoutingOverrideRepository
from app.models.routing_override import RoutingOverride
from app.routing.overrides import OverrideCondition, OverrideRule, apply_overrides

logger = logging.getLogger("app.routing")


def _to_override_rule(record: RoutingOverride) -> OverrideRule:
    return OverrideRule(
        id=str(record.id),
        name=record.name,
        conditions=tuple(
            OverrideCondition(field=c["field"], operator=c["operator"], value=c["value"]) for c in record.conditions
        ),
        override_department=record.override_department,
        override_action=record.override_action,
        override_requires_human_review=record.override_requires_human_review,
    )


async def apply_organization_overrides(
    db: AsyncSession, organization_id: str, decision: dict, subject: str, body: str, sender_email: str
) -> dict:
    """Never raises -- same "route() never raises, always returns a
    decision" contract app/services/routing_service.py's own module
    docstring establishes (RULE 10), extended to this later pass. A DB
    hiccup fetching overrides is exactly the kind of transient failure
    that must degrade to "no overrides applied this call," not crash the
    whole routing decision -- the base engine's own decision is always a
    perfectly usable fallback, same as any other per-signal failure this
    codebase already isolates (see RoutingService._safe_call)."""
    try:
        active = await RoutingOverrideRepository(db).list_active_for_organization(organization_id)
    except Exception:
        logger.warning("routing_overrides_fetch_failed", exc_info=True, extra={"organization_id": organization_id})
        return decision
    if not active:
        return decision  # skip building OverrideRule objects entirely for the common "no overrides configured" case
    rules = [_to_override_rule(record) for record in active]
    return apply_overrides(decision, subject, body, sender_email, rules)
