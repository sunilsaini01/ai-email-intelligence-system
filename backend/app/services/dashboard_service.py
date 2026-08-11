"""
Analytics/query layer for the Manager Dashboard (Module 11 / Phase 11,
FR-53 to FR-62).

Every dashboard API endpoint calls through here, never issuing its own
raw query -- the "operational tables -> analytics/query layer ->
aggregated dashboard APIs" principle docs/architecture_dashboard.md
commits to. This module owns: the evidence-badge mapping, the SLA
calculation, the review-queue ranking, and the correction-rate formula --
the four places this phase is most at risk of accidentally presenting
misleading numbers, kept in ONE place rather than duplicated per
endpoint.

Aggregation is done in Python after a scoped SELECT, not via
dialect-specific SQL (e.g. Postgres's `date_trunc`) -- this codebase's DB
tests run against SQLite (aiosqlite), and every existing repository is
deliberately dialect-portable (see email_repository.py's own docstring).
At this project's actual data volume (no real production traffic exists
yet -- see PHASE_11_AUDIT_REPORT.md), fetching timestamps for a date
range and bucketing them in Python is simple, correct, and portable; it
is NOT how this should be done once real volume exists -- see
docs/dashboard_performance.md for the disclosed scaling limit.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.repositories.feedback_event_repository import FeedbackEventRepository
from app.database.repositories.retraining_trigger_repository import RetrainingTriggerRepository
from app.models.category_prediction_log import CategoryPredictionLog
from app.models.email_record import EmailRecord
from app.models.feedback_event import (
    ACTION_ACCEPT,
    ACTION_CONFIRM,
    ACTION_CORRECTION,
    ACTION_REJECT,
    FeedbackEvent,
)
from app.models.intent_prediction_log import IntentPredictionLog
from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.reply_draft import STATUS_APPROVED, STATUS_EDITED, STATUS_REJECTED, ReplyDraft
from app.models.routing_decision_log import RoutingDecisionLog
from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.models.spam_prediction_log import SpamPredictionLog

# Correction-rate generalization (docs/architecture_dashboard.md "Correction
# rate"): a "correction-like" action means the reviewer changed something;
# a "confirm-like" action means the reviewer looked and left it as-is.
# RELEVANCE (retrieval's/auto-reply's usefulness judgments) is neither --
# excluded from this formula entirely, not forced into it.
_CORRECTION_LIKE = {ACTION_CORRECTION, ACTION_REJECT}
_CONFIRM_LIKE = {ACTION_CONFIRM, ACTION_ACCEPT}

# docs/architecture_dashboard.md "Model evidence policy" -- a documented
# project fact (README's own evidence table), not a per-request
# computation.
EVIDENCE_MAP: dict[str, tuple[str, str]] = {
    "spam": ("REAL_VALIDATED", "Real SpamAssassin-domain evidence (99.44% recall / 91.33% precision). Does not transfer to ordinary business email outside that domain (Phase 8 finding)."),
    "priority": ("SYNTHETIC", "Trained on heuristically-labelled synthetic data (Enron text, fabricated labels) -- not PRD-compliant."),
    "category": ("SYNTHETIC", "Trained on heuristically-labelled synthetic data -- not PRD-compliant."),
    "intent": ("SYNTHETIC", "Trained on heuristically-labelled synthetic data -- not PRD-compliant. Escalation/Refund classes additionally shown unreliable, not just unvalidated."),
    "summarization": ("OFF_DOMAIN", "Real, human-written reference summaries, but news domain, not email."),
    "sentiment": ("UNVALIDATED", "Zero-shot VADER lexicon scorer -- never trained or fit to any dataset, no ground truth exists to measure it against."),
    "routing": ("PROVISIONAL", "Composition layer over the other five modules -- inherits every upstream caveat, no routing-outcome ground truth exists."),
    "retrieval": ("PROVISIONAL", "Unsupervised embedding fitting (no fabricated labels), but no retrieval-relevance ground truth exists either."),
    "auto_reply": ("PROVISIONAL", "Third-party LLM (Groq/Llama-3.3-70b) this project does not train or validate. No real Human Acceptance Rate observations exist yet."),
}

_OFFLINE_REFERENCE: dict[str, str | None] = {
    "spam": "99.44% recall / 91.33% precision (SpamAssassin/SMS Spam/Amazon Reviews, real evaluation domain)",
    "priority": None,
    "category": None,
    "intent": None,
    "summarization": "ROUGE vs. BBC News Summary (off-domain) -- see docs/model_cards/email_summarization.md",
    "sentiment": None,
    "routing": None,
    "retrieval": None,
    "auto_reply": None,
}

_SINGLE_LABEL_MODULES = ("spam", "priority", "sentiment", "routing")
_MULTI_LABEL_MODULES = ("category", "intent")
_CORRECTABLE_MODULES = ("spam", "priority", "category", "sentiment", "intent", "routing", "summarization", "auto_reply")

_PRIORITY_WEIGHT = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
_QUEUE_SCAN_CAP = 500  # per module -- see get_review_queue's docstring

# module -> (ORM class, confidence column, prediction "value" column, timestamp column)
_MODULE_TABLES = {
    "spam": (SpamPredictionLog, "confidence", "is_spam"),
    "priority": (PriorityPredictionLog, "confidence", "predicted_priority"),
    "category": (CategoryPredictionLog, "confidences", "predicted_categories"),
    "sentiment": (SentimentPredictionLog, "confidence", "predicted_sentiment"),
    "intent": (IntentPredictionLog, "confidences", "predicted_intents"),
    "routing": (RoutingDecisionLog, "confidence", "department"),
}


@dataclass
class DateRange:
    start: datetime
    end: datetime


def resolve_date_range(range_name: str | None, start: datetime | None, end: datetime | None) -> DateRange:
    """FR-55. `range_name` is one of today|week|month|custom; custom
    requires start/end. All boundaries are UTC -- see
    docs/architecture_dashboard.md "Timezone Policy": filtering is always
    server-side UTC, display-side conversion is a frontend concern only.

    Adversarial-review finding (Stage 17): a naive `start`/`end` (no UTC
    offset -- exactly what an HTML `datetime-local` input produces, which
    is what this project's own DateRangePicker uses) previously worked
    ONLY because asyncpg/Postgres happens to interpret a naive timestamp
    against the session's timezone, which happens to be UTC by default in
    this project's docker-compose -- accidental correctness, not
    guaranteed. Normalized explicitly here instead of relying on that."""
    now = datetime.now(UTC)
    if range_name == "custom":
        if start is None or end is None:
            raise ValueError("range=custom requires both start and end.")
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end < start:
            raise ValueError("end must not be before start.")
        return DateRange(start=start, end=end)
    if range_name == "week":
        return DateRange(start=now - timedelta(days=7), end=now)
    if range_name == "month":
        return DateRange(start=now - timedelta(days=30), end=now)
    # default: today
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return DateRange(start=today_start, end=now)


def evidence_badge(module: str) -> dict:
    status, note = EVIDENCE_MAP.get(module, ("PROVISIONAL", "No evidence classification recorded for this module."))
    return {"status": status, "note": note}


def _bucket_key(dt: datetime, granularity: str) -> str:
    if granularity == "hour":
        return dt.strftime("%Y-%m-%dT%H:00")
    return dt.strftime("%Y-%m-%d")


async def get_email_volume(db: AsyncSession, organization_id: str, date_range: DateRange, granularity: str = "day") -> dict:
    """Volume is sourced from `spam_prediction_logs`, NOT `emails` --
    Phase 9's indexing is not auto-wired (a disclosed, pre-existing gap),
    so `emails` undercounts real traffic. Spam is the most defensible
    single proxy since every other module also logs independently and no
    table is a true "one row per request" source of truth today -- see
    PHASE_11_AUDIT_REPORT.md finding F1."""
    result = await db.execute(
        select(SpamPredictionLog.created_at).where(
            SpamPredictionLog.organization_id == organization_id,
            SpamPredictionLog.created_at >= date_range.start,
            SpamPredictionLog.created_at <= date_range.end,
        )
    )
    timestamps = [row[0] for row in result.all()]
    buckets: Counter[str] = Counter(_bucket_key(ts, granularity) for ts in timestamps)
    points = [{"bucket": k, "count": v} for k, v in sorted(buckets.items())]
    return {
        "granularity": granularity,
        "points": points,
        "total": len(timestamps),
        "note": "Sourced from spam_prediction_logs as the traffic proxy (see docstring) -- not a true per-request count.",
    }


async def get_category_distribution(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    result = await db.execute(
        select(CategoryPredictionLog.predicted_categories).where(
            CategoryPredictionLog.organization_id == organization_id,
            CategoryPredictionLog.created_at >= date_range.start,
            CategoryPredictionLog.created_at <= date_range.end,
        )
    )
    counter: Counter[str] = Counter()
    for row in result.all():
        counter.update(row[0] or [])
    counts = [{"category": k, "count": v} for k, v in sorted(counter.items(), key=lambda kv: -kv[1])]
    return {"counts": counts, "evidence": evidence_badge("category")}


async def get_sentiment_trend(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    result = await db.execute(
        select(SentimentPredictionLog.created_at, SentimentPredictionLog.predicted_sentiment).where(
            SentimentPredictionLog.organization_id == organization_id,
            SentimentPredictionLog.created_at >= date_range.start,
            SentimentPredictionLog.created_at <= date_range.end,
        )
    )
    counter: Counter[tuple[str, str]] = Counter()
    for created_at, sentiment in result.all():
        counter[(_bucket_key(created_at, "day"), sentiment)] += 1
    points = [{"bucket": b, "sentiment": s, "count": c} for (b, s), c in sorted(counter.items())]
    return {"points": points, "evidence": evidence_badge("sentiment")}


async def get_priority_distribution(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    result = await db.execute(
        select(PriorityPredictionLog.predicted_priority).where(
            PriorityPredictionLog.organization_id == organization_id,
            PriorityPredictionLog.created_at >= date_range.start,
            PriorityPredictionLog.created_at <= date_range.end,
        )
    )
    counter: Counter[str] = Counter(row[0] for row in result.all())
    counts = [{"priority": k, "count": v} for k, v in sorted(counter.items(), key=lambda kv: -kv[1])]
    return {"counts": counts, "evidence": evidence_badge("priority")}


async def get_sla(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    """FR-53's SLA dashboard. Computed entirely from `emails` (priority +
    received_at + resolved_at/resolution_status) -- see
    docs/architecture_dashboard.md "emails.priority" for why no join to
    any prediction table is needed. SLA targets are documented development
    defaults (Settings), not real business values -- the PRD names none."""
    settings = get_settings()
    targets = {
        "Critical": settings.SLA_CRITICAL_HOURS,
        "High": settings.SLA_HIGH_HOURS,
        "Medium": settings.SLA_MEDIUM_HOURS,
        "Low": settings.SLA_LOW_HOURS,
    }
    result = await db.execute(
        select(EmailRecord.priority, EmailRecord.received_at, EmailRecord.resolved_at).where(
            EmailRecord.organization_id == organization_id,
            EmailRecord.is_deleted == False,  # noqa: E712
            EmailRecord.received_at >= date_range.start,
            EmailRecord.received_at <= date_range.end,
        )
    )
    now = datetime.now(UTC)
    buckets: dict[str, dict[str, int]] = {p: {"within_sla": 0, "at_risk": 0, "breached": 0} for p in targets}
    excluded = 0

    for priority, received_at, resolved_at in result.all():
        if priority is None or priority not in targets:
            excluded += 1
            continue
        target_hours = targets[priority]
        at_risk_hours = target_hours * settings.SLA_AT_RISK_FRACTION
        end_point = resolved_at if resolved_at is not None else now
        # SQLite (used in this project's DB tests, aiosqlite) has no real
        # timezone-aware column type -- DateTime(timezone=True) round-trips
        # as a NAIVE datetime there even though it's tz-aware in production
        # Postgres. Normalize defensively (assume UTC, this codebase's only
        # timezone -- every writer already uses datetime.now(UTC)) rather
        # than letting the subtraction crash on a dialect this table is
        # actually tested against.
        end_point = end_point if end_point.tzinfo is not None else end_point.replace(tzinfo=UTC)
        received_at = received_at if received_at.tzinfo is not None else received_at.replace(tzinfo=UTC)
        elapsed_hours = (end_point - received_at).total_seconds() / 3600.0

        if elapsed_hours >= target_hours:
            buckets[priority]["breached"] += 1
        elif elapsed_hours >= at_risk_hours:
            buckets[priority]["at_risk"] += 1
        else:
            buckets[priority]["within_sla"] += 1

    bucket_list = [{"priority": p, **counts} for p, counts in buckets.items()]
    return {
        "buckets": bucket_list,
        "excluded_no_priority": excluded,
        "sla_targets_hours": targets,
        "note": "Development-default SLA targets, not real business values (PRD names none). "
        "Only emails with a non-NULL priority (set at /retrieval/index time) are included in the tiered breakdown.",
    }


async def get_agent_workload(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    """FR-53's agent-workload view -- a PROXY, not a real user/assignment
    system: `reply_drafts.reviewer_id` is caller-supplied and
    unauthenticated (see docs/dashboard_security.md)."""
    result = await db.execute(
        select(ReplyDraft.reviewer_id, ReplyDraft.status, ReplyDraft.created_at, ReplyDraft.reviewed_at).where(
            ReplyDraft.organization_id == organization_id,
            ReplyDraft.created_at >= date_range.start,
            ReplyDraft.created_at <= date_range.end,
            ReplyDraft.reviewer_id.is_not(None),
        )
    )
    by_agent: dict[str, dict] = defaultdict(lambda: {"assigned": 0, "pending": 0, "resolved": 0, "durations": []})
    resolved_statuses = {STATUS_APPROVED, STATUS_EDITED, STATUS_REJECTED}
    for reviewer_id, status, created_at, reviewed_at in result.all():
        entry = by_agent[reviewer_id]
        entry["assigned"] += 1
        if status in resolved_statuses:
            entry["resolved"] += 1
            if reviewed_at is not None:
                entry["durations"].append((reviewed_at - created_at).total_seconds() / 60.0)
        else:
            entry["pending"] += 1

    agents = [
        {
            "reviewer_id": reviewer_id,
            "assigned": entry["assigned"],
            "pending": entry["pending"],
            "resolved": entry["resolved"],
            "avg_resolution_minutes": (sum(entry["durations"]) / len(entry["durations"])) if entry["durations"] else None,
        }
        for reviewer_id, entry in sorted(by_agent.items())
    ]
    return {"agents": agents, "note": "reviewer_id is caller-supplied and unauthenticated -- a workload PROXY, not a real user/assignment system."}


async def _correction_rate_for_module(db: AsyncSession, module: str, organization_id: str, date_range: DateRange) -> tuple[float | None, int, int]:
    result = await db.execute(
        select(FeedbackEvent.action).where(
            FeedbackEvent.module == module,
            FeedbackEvent.organization_id == organization_id,
            FeedbackEvent.created_at >= date_range.start,
            FeedbackEvent.created_at <= date_range.end,
        )
    )
    actions = [row[0] for row in result.all()]
    corrected = sum(1 for a in actions if a in _CORRECTION_LIKE)
    confirmed = sum(1 for a in actions if a in _CONFIRM_LIKE)
    reviewed = corrected + confirmed
    rate = (corrected / reviewed) if reviewed > 0 else None
    return rate, reviewed, corrected


async def get_model_quality(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    trigger_repo = RetrainingTriggerRepository(db)
    modules_out = []
    for module in (*_CORRECTABLE_MODULES, "retrieval"):
        rate, reviewed, corrected = await _correction_rate_for_module(db, module, organization_id, date_range)
        latest_trigger = await trigger_repo.get_latest(module)
        modules_out.append(
            {
                "module": module,
                "evidence": evidence_badge(module),
                "offline_reference_metric": _OFFLINE_REFERENCE.get(module),
                "correction_rate": rate,
                "reviewed_count": reviewed,
                "corrected_count": corrected,
                "retraining_threshold_reached": latest_trigger is not None and not latest_trigger.consumed,
            }
        )
    return {"modules": modules_out}


async def get_review_queue(db: AsyncSession, organization_id: str, limit: int = 100) -> dict:
    """FR-60. Ranking: docs/architecture_dashboard.md "Review Queue
    ranking" -- urgency = (1 - confidence) * priority_weight, where
    priority_weight only applies within the priority module's own items
    (no cross-table join exists to give other modules a priority
    signal -- see PHASE_11_AUDIT_REPORT.md)."""
    settings = get_settings()
    feedback_repo = FeedbackEventRepository(db)
    items: list[dict] = []

    for module, (model_cls, confidence_attr, value_attr) in _MODULE_TABLES.items():
        threshold = (
            settings.LOW_CONFIDENCE_THRESHOLD_MULTI_LABEL
            if module in _MULTI_LABEL_MODULES
            else settings.LOW_CONFIDENCE_THRESHOLD_SINGLE_LABEL
        )
        reviewed_ids = await feedback_repo.get_reviewed_prediction_ids(module, organization_id)

        # Adversarial-review finding (Stage 17): unbounded per-module scan
        # -- capped to the most recent _QUEUE_SCAN_CAP rows per module so
        # this doesn't degrade into a full-table scan as data grows. A
        # genuinely correct "globally most urgent" ranking across ALL
        # history would need the SQL-side aggregation this phase's Python-
        # side approach deliberately avoids for portability (see module
        # docstring) -- disclosed tradeoff, not silently unbounded either.
        result = await db.execute(
            select(model_cls)
            .where(model_cls.organization_id == organization_id)
            .order_by(model_cls.created_at.desc())
            .limit(_QUEUE_SCAN_CAP)
        )
        for row in result.scalars().all():
            if row.id in reviewed_ids:
                continue

            raw_confidence = getattr(row, confidence_attr)
            if isinstance(raw_confidence, dict):
                if not raw_confidence:
                    continue
                confidence = min(raw_confidence.values())
            else:
                confidence = raw_confidence

            if confidence is None or confidence >= threshold:
                continue

            predicted_value = getattr(row, value_attr)
            priority_weight = 1
            if module == "priority" and predicted_value in _PRIORITY_WEIGHT:
                priority_weight = _PRIORITY_WEIGHT[predicted_value]

            urgency = (1 - confidence) * priority_weight
            items.append(
                {
                    "prediction_id": str(row.id),
                    "module": module,
                    "subject": row.subject,
                    "confidence": confidence,
                    "predicted_value": predicted_value,
                    "urgency_score": round(urgency, 4),
                    "created_at": row.created_at,
                    "evidence": evidence_badge(module),
                }
            )

    items.sort(key=lambda i: -i["urgency_score"])
    return {
        "items": items[:limit],
        "note": "Priority-based urgency boosting currently applies only to Priority-module review items "
        "(no email_id link exists to give other modules a priority signal -- see PHASE_11_AUDIT_REPORT.md). "
        "Summarization has no confidence concept and is not included.",
    }


class AlreadyReviewedError(Exception):
    """Raised when a prediction_id already has a feedback_events row for
    this module -- adversarial-review finding (Stage 17): without this
    guard, a double-click (or any duplicate request) on the Review
    Queue's Confirm button races and inserts two CONFIRM rows for the
    same prediction, inflating FR-62's correction-rate denominator."""


async def confirm_review_item(
    db: AsyncSession,
    module: str,
    prediction_id: uuid.UUID,
    organization_id: str,
    subject: str,
    predicted_value,
    confidence: float | None,
    reviewer_id: str | None,
):
    from app.services.feedback_event_service import record_feedback_event

    feedback_repo = FeedbackEventRepository(db)
    already_reviewed = await feedback_repo.get_reviewed_prediction_ids(module, organization_id)
    if prediction_id in already_reviewed:
        raise AlreadyReviewedError(f"{module}:{prediction_id} was already reviewed.")

    return await record_feedback_event(
        db,
        module=module,
        action=ACTION_CONFIRM,
        organization_id=organization_id,
        prediction_id=prediction_id,
        original_value=predicted_value,
        corrected_value=predicted_value,
        confidence=confidence,
        reviewer_id=reviewer_id,
        reason=f"Confirmed correct via Review Queue (subject: {subject[:80]!r})" if subject else "Confirmed correct via Review Queue.",
    )


async def get_overview(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    volume = await get_email_volume(db, organization_id, date_range, granularity="day")
    days = max((date_range.end - date_range.start).total_seconds() / 86400.0, 1e-9)

    spam_result = await db.execute(
        select(SpamPredictionLog.is_spam).where(
            SpamPredictionLog.organization_id == organization_id,
            SpamPredictionLog.created_at >= date_range.start,
            SpamPredictionLog.created_at <= date_range.end,
        )
    )
    spam_flags = [row[0] for row in spam_result.all()]
    spam_rate = (sum(spam_flags) / len(spam_flags)) if spam_flags else None

    priority_result = await db.execute(
        select(PriorityPredictionLog.predicted_priority).where(
            PriorityPredictionLog.organization_id == organization_id,
            PriorityPredictionLog.created_at >= date_range.start,
            PriorityPredictionLog.created_at <= date_range.end,
        )
    )
    high_critical = sum(1 for row in priority_result.all() if row[0] in ("Critical", "High"))

    sla = await get_sla(db, organization_id, date_range)
    sla_breach_count = sum(b["breached"] for b in sla["buckets"])

    queue = await get_review_queue(db, organization_id, limit=10_000)
    pending_human_reviews = len(queue["items"])

    feedback_result = await db.execute(
        select(FeedbackEvent.action).where(
            FeedbackEvent.organization_id == organization_id,
            FeedbackEvent.created_at >= date_range.start,
            FeedbackEvent.created_at <= date_range.end,
        )
    )
    fb_actions = [row[0] for row in feedback_result.all()]
    fb_corrected = sum(1 for a in fb_actions if a in _CORRECTION_LIKE)
    fb_confirmed = sum(1 for a in fb_actions if a in _CONFIRM_LIKE)
    fb_reviewed = fb_corrected + fb_confirmed
    correction_rate = (fb_corrected / fb_reviewed) if fb_reviewed > 0 else None

    reply_result = await db.execute(
        select(ReplyDraft.status).where(
            ReplyDraft.organization_id == organization_id,
            ReplyDraft.created_at >= date_range.start,
            ReplyDraft.created_at <= date_range.end,
            ReplyDraft.status.in_([STATUS_APPROVED, STATUS_EDITED, STATUS_REJECTED]),
        )
    )
    reply_statuses = [row[0] for row in reply_result.all()]
    accepted = sum(1 for s in reply_statuses if s in (STATUS_APPROVED, STATUS_EDITED))
    acceptance_rate = (accepted / len(reply_statuses)) if reply_statuses else None

    return {
        "total_emails_proxy": volume["total"],
        "emails_per_day_avg": round(volume["total"] / days, 2),
        "spam_rate": spam_rate,
        "high_critical_priority_count": high_critical,
        "sla_breach_count": sla_breach_count,
        "pending_human_reviews": pending_human_reviews,
        "feedback_correction_rate": correction_rate,
        "reviewed_feedback_count": fb_reviewed,
        "auto_reply_acceptance_rate": acceptance_rate,
        "auto_reply_reviewed_count": len(reply_statuses),
        "date_range_start": date_range.start,
        "date_range_end": date_range.end,
        "note": "total_emails_proxy is sourced from spam_prediction_logs, not `emails` (see get_email_volume). "
        "correction_rate and acceptance_rate are null (not 0%) when reviewed_count is 0 -- zero observations is not "
        "the same as a 0% rate.",
    }
