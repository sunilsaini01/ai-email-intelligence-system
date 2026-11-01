"""
Database side of drift monitoring -- see app/mlops/drift.py for the
statistics and their limits. Used by GET /dashboard/drift (on demand) and
by the agents process's periodic drift check (app/services/scheduled_jobs.py),
which also exports the result as Prometheus gauges for the alert rules in
monitoring/prometheus/alert_rules.yml.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mlops.drift import BASELINE_WINDOW_DAYS, CURRENT_WINDOW_DAYS, ModuleDrift, evaluate_module
from app.models.category_prediction_log import CategoryPredictionLog
from app.models.intent_prediction_log import IntentPredictionLog
from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.models.spam_prediction_log import SpamPredictionLog
from app.services import dashboard_service

# module -> (model, label column, is_multi_label)
_SOURCES = {
    "spam": (SpamPredictionLog, SpamPredictionLog.is_spam, False),
    "priority": (PriorityPredictionLog, PriorityPredictionLog.predicted_priority, False),
    "category": (CategoryPredictionLog, CategoryPredictionLog.predicted_categories, True),
    "sentiment": (SentimentPredictionLog, SentimentPredictionLog.predicted_sentiment, False),
    "intent": (IntentPredictionLog, IntentPredictionLog.predicted_intents, True),
}

DRIFT_MODULES = tuple(_SOURCES)


def _label(module: str, value) -> str:
    if module == "spam":
        return "spam" if value else "ham"
    return str(value)


async def _label_counts(
    session: AsyncSession, module: str, organization_id: str, start: datetime, end: datetime
) -> Counter:
    model, column, multi_label = _SOURCES[module]
    rows = await session.execute(
        select(column).where(
            model.organization_id == organization_id,
            model.created_at >= start,
            model.created_at < end,
        )
    )
    counts: Counter = Counter()
    for (value,) in rows.all():
        if multi_label:
            counts.update(str(v) for v in (value or []))
        elif value is not None:
            counts[_label(module, value)] += 1
    return counts


async def compute_drift(session: AsyncSession, organization_id: str, now: datetime | None = None) -> list[ModuleDrift]:
    now = now or datetime.now(UTC)
    current_start = now - timedelta(days=CURRENT_WINDOW_DAYS)
    baseline_start = current_start - timedelta(days=BASELINE_WINDOW_DAYS)

    results = []
    for module in DRIFT_MODULES:
        baseline = await _label_counts(session, module, organization_id, baseline_start, current_start)
        current = await _label_counts(session, module, organization_id, current_start, now)
        _, base_reviewed, base_corrected = await dashboard_service.correction_rate_for_module(
            session, module, organization_id, dashboard_service.DateRange(start=baseline_start, end=current_start)
        )
        _, curr_reviewed, curr_corrected = await dashboard_service.correction_rate_for_module(
            session, module, organization_id, dashboard_service.DateRange(start=current_start, end=now)
        )
        results.append(
            evaluate_module(
                module,
                baseline,
                current,
                baseline_feedback=(base_reviewed, base_corrected),
                current_feedback=(curr_reviewed, curr_corrected),
            )
        )
    return results
