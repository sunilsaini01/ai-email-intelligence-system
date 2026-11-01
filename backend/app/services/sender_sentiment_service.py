"""
Per-sender sentiment trends (FR-32: "System shall track sentiment trends
per sender over time (for proactive escalation)").

Built from sentiment_prediction_logs.sender_email (recorded by both the
/sentiment/predict endpoint and the Kafka sentiment agent). The five FR-29
labels are mapped onto an ordinal -2..+2 scale so they can be averaged;
"trend" compares the sender's last RECENT_DAYS against everything earlier
in the window. A sender is an escalation candidate when their recent
sentiment is clearly negative or clearly worsening with repeated negative
emails -- the same signal the priority adjustment uses
(app/routing/priority_adjustment.py), surfaced here for a manager to act
on before it becomes a complaint.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.routing.priority_adjustment import SENDER_NEGATIVE_HISTORY_THRESHOLD

SENTIMENT_SCORES = {"Very Negative": -2, "Negative": -1, "Neutral": 0, "Positive": 1, "Very Positive": 2}

WINDOW_DAYS = 90
RECENT_DAYS = 14
DECLINE_DELTA = -0.5
NEGATIVE_AVERAGE = -1.0
MIN_EMAILS = 2


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def summarize_sender(sender: str, rows: list[tuple[datetime, str]], now: datetime) -> dict:
    """`rows` are (created_at, sentiment label) for one sender."""
    recent_cutoff = now - timedelta(days=RECENT_DAYS)
    scores = [(_as_utc(at), SENTIMENT_SCORES[label]) for at, label in rows if label in SENTIMENT_SCORES]
    recent = [s for at, s in scores if at >= recent_cutoff]
    earlier = [s for at, s in scores if at < recent_cutoff]

    average = sum(s for _, s in scores) / len(scores)
    recent_average = sum(recent) / len(recent) if recent else average
    if earlier and recent:
        delta = recent_average - sum(earlier) / len(earlier)
        trend = "declining" if delta <= DECLINE_DELTA else "improving" if delta >= -DECLINE_DELTA else "stable"
    else:
        trend = "stable"
    negative_count = sum(1 for _, s in scores if s < 0)

    by_day: dict[str, list[int]] = defaultdict(list)
    for at, s in scores:
        by_day[at.strftime("%Y-%m-%d")].append(s)

    return {
        "sender_email": sender,
        "email_count": len(scores),
        "negative_count": negative_count,
        "average_score": round(average, 3),
        "recent_average_score": round(recent_average, 3),
        "trend": trend,
        "escalation_candidate": recent_average <= NEGATIVE_AVERAGE
        or (trend == "declining" and negative_count >= SENDER_NEGATIVE_HISTORY_THRESHOLD),
        "points": [
            {"date": day, "average_score": round(sum(v) / len(v), 3), "count": len(v)}
            for day, v in sorted(by_day.items())
        ],
    }


async def get_sender_trends(
    session: AsyncSession, organization_id: str, sender_email: str | None = None, limit: int = 50
) -> list[dict]:
    now = datetime.now(UTC)
    query = select(
        SentimentPredictionLog.sender_email,
        SentimentPredictionLog.created_at,
        SentimentPredictionLog.predicted_sentiment,
    ).where(
        SentimentPredictionLog.organization_id == organization_id,
        SentimentPredictionLog.sender_email.is_not(None),
        SentimentPredictionLog.created_at >= now - timedelta(days=WINDOW_DAYS),
    )
    if sender_email:
        query = query.where(SentimentPredictionLog.sender_email == sender_email.strip().lower())

    grouped: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for sender, created_at, label in (await session.execute(query)).all():
        grouped[sender].append((created_at, label))

    minimum = 1 if sender_email else MIN_EMAILS
    summaries = [summarize_sender(s, rows, now) for s, rows in grouped.items() if len(rows) >= minimum]
    summaries.sort(key=lambda s: (not s["escalation_candidate"], s["recent_average_score"]))
    return summaries[:limit]
