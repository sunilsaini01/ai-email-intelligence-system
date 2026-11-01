"""
The database-backed inputs RoutingService.route() needs but cannot fetch
itself (it is synchronous and DB-free, shared by the /routing/predict
endpoint and the Orchestrator):

  - sender_negative_history (FR-17/FR-32): how many negative emails this
    sender sent in the trailing window;
  - department_thresholds (FR-41): the organization's learned auto-route
    thresholds;
  - disabled_categories (FR-23): categories the organization switched off.

Both call sites load these the same way through `load_routing_context`,
so the two intake paths can never disagree about them.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.routing.priority_adjustment import SENDER_HISTORY_WINDOW_DAYS
from app.services.category_taxonomy import disabled_categories
from app.services.organization_settings_service import get_org_settings

NEGATIVE_SENTIMENTS = ("Negative", "Very Negative")


async def count_sender_negative_history(
    session: AsyncSession, organization_id: str, sender_email: str, before: datetime | None = None
) -> int:
    sender = (sender_email or "").strip().lower()
    if not sender:
        return 0
    now = datetime.now(UTC)
    query = select(func.count()).select_from(SentimentPredictionLog).where(
        SentimentPredictionLog.organization_id == organization_id,
        SentimentPredictionLog.sender_email == sender,
        SentimentPredictionLog.predicted_sentiment.in_(NEGATIVE_SENTIMENTS),
        SentimentPredictionLog.created_at >= now - timedelta(days=SENDER_HISTORY_WINDOW_DAYS),
    )
    if before is not None:
        query = query.where(SentimentPredictionLog.created_at < before)
    return (await session.execute(query)).scalar_one()


async def load_routing_context(
    session: AsyncSession, organization_id: str, sender_email: str, before: datetime | None = None
) -> tuple[dict, dict]:
    """Returns (route_kwargs, org_settings). `before` excludes the email
    currently being processed from its own sender history."""
    org_settings = await get_org_settings(session, organization_id)
    route_kwargs = {
        "sender_negative_history": await count_sender_negative_history(
            session, organization_id, sender_email, before=before
        ),
        "department_thresholds": dict(org_settings["routing_thresholds"] or {}),
        "disabled_categories": disabled_categories(org_settings["category_taxonomy"]),
    }
    return route_kwargs, org_settings
