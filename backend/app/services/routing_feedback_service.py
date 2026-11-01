"""
Recomputes an organization's learned routing thresholds (FR-41) from its
routing feedback -- see app/routing/feedback_weights.py for the policy.

Counted per PREDICTED department over the trailing window:
  - a CORRECTION whose corrected department differs from the predicted one
    is a routing error;
  - a CORRECTION that only changed the action (same department), or a
    CONFIRM from the review queue, is a reviewed-and-correct decision.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback_event import ACTION_CONFIRM, ACTION_CORRECTION, FeedbackEvent
from app.routing.feedback_weights import (
    FEEDBACK_WINDOW_DAYS,
    DepartmentFeedback,
    compute_department_thresholds,
)
from app.services.organization_settings_service import update_org_settings

logger = logging.getLogger("app.routing.feedback")


def _department(value) -> str | None:
    if isinstance(value, dict):
        return value.get("department")
    return value if isinstance(value, str) else None


async def collect_department_feedback(session: AsyncSession, organization_id: str) -> dict[str, DepartmentFeedback]:
    since = datetime.now(UTC) - timedelta(days=FEEDBACK_WINDOW_DAYS)
    rows = (
        await session.execute(
            select(FeedbackEvent.action, FeedbackEvent.original_value, FeedbackEvent.corrected_value).where(
                FeedbackEvent.module == "routing",
                FeedbackEvent.organization_id == organization_id,
                FeedbackEvent.action.in_((ACTION_CORRECTION, ACTION_CONFIRM)),
                FeedbackEvent.created_at >= since,
            )
        )
    ).all()

    reviewed: dict[str, int] = {}
    corrected: dict[str, int] = {}
    for action, original, correction in rows:
        predicted = _department(original)
        if predicted is None:
            continue
        reviewed[predicted] = reviewed.get(predicted, 0) + 1
        if action == ACTION_CORRECTION and _department(correction) not in (None, predicted):
            corrected[predicted] = corrected.get(predicted, 0) + 1

    return {d: DepartmentFeedback(reviewed=n, corrected=corrected.get(d, 0)) for d, n in reviewed.items()}


async def recompute_routing_thresholds(session: AsyncSession, organization_id: str) -> dict[str, float]:
    stats = await collect_department_feedback(session, organization_id)
    thresholds = compute_department_thresholds(stats)
    await update_org_settings(session, organization_id, {"routing_thresholds": thresholds})
    logger.info(
        "routing_thresholds_recomputed",
        extra={"organization_id": organization_id, "thresholds": thresholds},
    )
    return thresholds
