"""
Orchestrates a feedback_events write plus the FR-61 retraining-threshold
check (Module 11 / Phase 11).

Why this isn't just two inline repository calls in each endpoint: the
threshold-crossing check needs to run identically after every CORRECTION
write, from 7 different `*/feedback` endpoints plus the Review Queue's
correction path -- one shared function, not seven copies of the same
"count since last trigger, compare to threshold, maybe insert a trigger
row" logic.

Both the feedback write and the retraining check are best-effort from the
CALLING endpoint's point of view -- same stance every existing
`*/feedback` endpoint already takes toward its own JSONL write (never
fails the request), applied consistently to this ADDITIONAL write. The
caller wraps this in its own try/except, same as the existing pattern.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.repositories.feedback_event_repository import FeedbackEventRepository
from app.database.repositories.retraining_trigger_repository import RetrainingTriggerRepository
from app.models.feedback_event import ACTION_CORRECTION, FeedbackEvent
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

logger = logging.getLogger("app.dashboard.feedback")


async def record_feedback_event(
    db: AsyncSession,
    module: str,
    action: str,
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    prediction_id=None,
    original_value=None,
    corrected_value=None,
    confidence: float | None = None,
    reviewer_id: str | None = None,
    reason: str | None = None,
) -> FeedbackEvent:
    """Writes one feedback_events row, and, for a CORRECTION, checks
    whether this crosses the module's retraining threshold (FR-61)."""
    repository = FeedbackEventRepository(db)
    event = await repository.create(
        module=module,
        action=action,
        organization_id=organization_id,
        prediction_id=prediction_id,
        original_value=original_value,
        corrected_value=corrected_value,
        confidence=confidence,
        reviewer_id=reviewer_id,
        reason=reason,
    )

    if action == ACTION_CORRECTION:
        await _check_retraining_threshold(db, module)

    return event


async def _check_retraining_threshold(db: AsyncSession, module: str) -> None:
    settings = get_settings()
    threshold = settings.RETRAINING_FEEDBACK_THRESHOLD

    trigger_repo = RetrainingTriggerRepository(db)
    feedback_repo = FeedbackEventRepository(db)

    latest = await trigger_repo.get_latest(module)
    since = latest.triggered_at if latest is not None else None
    count = await feedback_repo.count_corrections_since(module, since)

    if count >= threshold:
        await trigger_repo.create(module=module, feedback_count_at_trigger=count, threshold_used=threshold)
        # Deliberately just an audit log + a DB row -- FR-61's ENTIRE scope
        # this phase. No retraining executes. See
        # docs/architecture_dashboard.md "Retraining trigger".
        logger.info(
            "retraining_requested",
            extra={"module": module, "feedback_count_at_trigger": count, "threshold_used": threshold},
        )
