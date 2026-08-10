"""
Tests for the dashboard analytics/query layer (Module 11 / Phase 11) --
the SLA calculation, review-queue ranking/exclusion, correction-rate
formula, and the "no observations yet, not 0%" nullability contract are
the highest-risk pieces (docs/architecture_dashboard.md), so this file
verifies each directly against real seeded rows in an in-memory SQLite
engine, not mocks.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base
from app.models.email_record import EmailRecord
from app.models.feedback_event import ACTION_CONFIRM, ACTION_CORRECTION, FeedbackEvent
from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.spam_prediction_log import SpamPredictionLog
from app.services import dashboard_service


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _wide_range() -> dashboard_service.DateRange:
    now = datetime.now(UTC)
    return dashboard_service.DateRange(start=now - timedelta(days=365), end=now + timedelta(days=1))


# --- resolve_date_range -------------------------------------------------

def test_resolve_date_range_today_starts_at_midnight_utc():
    r = dashboard_service.resolve_date_range("today", None, None)
    assert r.start.hour == 0 and r.start.minute == 0


def test_resolve_date_range_custom_requires_start_and_end():
    with pytest.raises(ValueError):
        dashboard_service.resolve_date_range("custom", None, None)


def test_resolve_date_range_custom_rejects_end_before_start():
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        dashboard_service.resolve_date_range("custom", now, now - timedelta(days=1))


def test_resolve_date_range_custom_normalizes_naive_datetimes_to_utc():
    """Adversarial-review finding: a naive datetime (no UTC offset -- what
    an HTML datetime-local input produces) must be treated as UTC
    explicitly, not left to accidentally work only because the DB
    session's timezone happens to be UTC."""
    naive_start = datetime(2026, 1, 1, 0, 0, 0)
    naive_end = datetime(2026, 1, 2, 0, 0, 0)
    assert naive_start.tzinfo is None

    result = dashboard_service.resolve_date_range("custom", naive_start, naive_end)
    assert result.start.tzinfo is not None
    assert result.start.utcoffset() == timedelta(0)
    assert result.end.tzinfo is not None


# --- evidence badges ------------------------------------------------------

def test_evidence_badge_spam_is_real_validated():
    badge = dashboard_service.evidence_badge("spam")
    assert badge["status"] == "REAL_VALIDATED"


def test_evidence_badge_priority_is_synthetic():
    badge = dashboard_service.evidence_badge("priority")
    assert badge["status"] == "SYNTHETIC"


def test_evidence_badge_unknown_module_defaults_to_provisional():
    badge = dashboard_service.evidence_badge("not_a_real_module")
    assert badge["status"] == "PROVISIONAL"


# --- SLA -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sla_excludes_emails_with_no_priority(session):
    session.add(EmailRecord(body="x", content_hash="a" * 64, received_at=datetime.now(UTC)))
    await session.commit()

    result = await dashboard_service.get_sla(session, "default", _wide_range())
    assert result["excluded_no_priority"] == 1
    assert all(b["within_sla"] == b["at_risk"] == b["breached"] == 0 for b in result["buckets"])


@pytest.mark.asyncio
async def test_sla_breached_when_elapsed_exceeds_target(session):
    settings = dashboard_service.get_settings()
    long_ago = datetime.now(UTC) - timedelta(hours=settings.SLA_CRITICAL_HOURS + 1)
    session.add(EmailRecord(body="x", content_hash="b" * 64, received_at=long_ago, priority="Critical"))
    await session.commit()

    result = await dashboard_service.get_sla(session, "default", _wide_range())
    critical = next(b for b in result["buckets"] if b["priority"] == "Critical")
    assert critical["breached"] == 1


@pytest.mark.asyncio
async def test_sla_within_sla_for_a_freshly_received_email(session):
    session.add(EmailRecord(body="x", content_hash="c" * 64, received_at=datetime.now(UTC), priority="Low"))
    await session.commit()

    result = await dashboard_service.get_sla(session, "default", _wide_range())
    low = next(b for b in result["buckets"] if b["priority"] == "Low")
    assert low["within_sla"] == 1


@pytest.mark.asyncio
async def test_sla_uses_resolved_at_not_now_for_a_resolved_email(session):
    """A ticket resolved quickly, long ago, must NOT be counted as
    currently breached just because `now` has since moved far past
    received_at -- resolved_at is the correct end-point, not `now`."""
    settings = dashboard_service.get_settings()
    received = datetime.now(UTC) - timedelta(days=30)
    resolved = received + timedelta(minutes=5)  # resolved fast
    session.add(
        EmailRecord(
            body="x", content_hash="d" * 64, received_at=received, resolved_at=resolved,
            priority="Critical", resolution_status="RESOLVED",
        )
    )
    await session.commit()

    result = await dashboard_service.get_sla(session, "default", _wide_range())
    critical = next(b for b in result["buckets"] if b["priority"] == "Critical")
    assert critical["within_sla"] == 1
    assert critical["breached"] == 0


# --- Correction rate ---------------------------------------------------

@pytest.mark.asyncio
async def test_correction_rate_is_none_with_zero_reviews(session):
    rate, reviewed, corrected = await dashboard_service._correction_rate_for_module(
        session, "spam", "default", _wide_range()
    )
    assert rate is None
    assert reviewed == 0


@pytest.mark.asyncio
async def test_correction_rate_formula_uses_reviewed_not_all_predictions(session):
    # Two predictions logged, but only one ever reviewed (one CORRECTION).
    session.add(SpamPredictionLog(body="a", is_spam=False, status="clear", spam_score=0.1, confidence=0.9, threshold_used=0.06, model_version="v1", processing_ms=1.0))
    session.add(SpamPredictionLog(body="b", is_spam=False, status="clear", spam_score=0.1, confidence=0.9, threshold_used=0.06, model_version="v1", processing_ms=1.0))
    session.add(FeedbackEvent(module="spam", action=ACTION_CORRECTION, organization_id="default"))
    await session.commit()

    rate, reviewed, corrected = await dashboard_service._correction_rate_for_module(
        session, "spam", "default", _wide_range()
    )
    # NOT corrected / all_predictions (which would be 1/2 = 0.5 coincidentally
    # here) -- verify against the actual denominator semantics instead.
    assert reviewed == 1  # only the one CORRECTION event, no CONFIRM yet
    assert rate == 1.0


@pytest.mark.asyncio
async def test_correction_rate_confirm_lowers_the_rate(session):
    session.add(FeedbackEvent(module="priority", action=ACTION_CORRECTION, organization_id="default"))
    session.add(FeedbackEvent(module="priority", action=ACTION_CONFIRM, organization_id="default"))
    session.add(FeedbackEvent(module="priority", action=ACTION_CONFIRM, organization_id="default"))
    await session.commit()

    rate, reviewed, corrected = await dashboard_service._correction_rate_for_module(
        session, "priority", "default", _wide_range()
    )
    assert reviewed == 3
    assert corrected == 1
    assert rate == pytest.approx(1 / 3)


# --- Review queue --------------------------------------------------------

@pytest.mark.asyncio
async def test_review_queue_excludes_high_confidence_predictions(session):
    session.add(SpamPredictionLog(body="a", is_spam=False, status="clear", spam_score=0.1, confidence=0.95, threshold_used=0.06, model_version="v1", processing_ms=1.0))
    await session.commit()

    result = await dashboard_service.get_review_queue(session, "default")
    assert result["items"] == []


@pytest.mark.asyncio
async def test_review_queue_includes_low_confidence_predictions(session):
    session.add(SpamPredictionLog(body="a", is_spam=False, status="clear", spam_score=0.1, confidence=0.3, threshold_used=0.06, model_version="v1", processing_ms=1.0))
    await session.commit()

    result = await dashboard_service.get_review_queue(session, "default")
    assert len(result["items"]) == 1
    assert result["items"][0]["module"] == "spam"


@pytest.mark.asyncio
async def test_review_queue_excludes_already_reviewed_items(session):
    row = SpamPredictionLog(body="a", is_spam=False, status="clear", spam_score=0.1, confidence=0.3, threshold_used=0.06, model_version="v1", processing_ms=1.0)
    session.add(row)
    await session.commit()
    await session.refresh(row)

    session.add(FeedbackEvent(module="spam", action=ACTION_CONFIRM, organization_id="default", prediction_id=row.id))
    await session.commit()

    result = await dashboard_service.get_review_queue(session, "default")
    assert result["items"] == []


@pytest.mark.asyncio
async def test_review_queue_ranks_critical_priority_above_low_priority(session):
    session.add(PriorityPredictionLog(body="a", predicted_priority="Critical", confidence=0.1, model_version="v1", processing_ms=1.0))
    session.add(PriorityPredictionLog(body="b", predicted_priority="Low", confidence=0.1, model_version="v1", processing_ms=1.0))
    await session.commit()

    result = await dashboard_service.get_review_queue(session, "default")
    assert result["items"][0]["predicted_value"] == "Critical"
    assert result["items"][0]["urgency_score"] > result["items"][1]["urgency_score"]


@pytest.mark.asyncio
async def test_review_queue_multilabel_confidence_uses_minimum_across_labels(session):
    from app.models.category_prediction_log import CategoryPredictionLog

    session.add(
        CategoryPredictionLog(
            body="a", predicted_categories=["Billing", "Legal"],
            confidences={"Billing": 0.9, "Legal": 0.2}, model_version="v1", processing_ms=1.0,
        )
    )
    await session.commit()

    result = await dashboard_service.get_review_queue(session, "default")
    # Multi-label threshold default is 0.5 -- min(0.9, 0.2)=0.2 qualifies.
    assert len(result["items"]) == 1
    assert result["items"][0]["confidence"] == 0.2


# --- Overview zero-observation nullability -------------------------------

@pytest.mark.asyncio
async def test_overview_correction_rate_is_null_not_zero_with_no_feedback(session):
    result = await dashboard_service.get_overview(session, "default", _wide_range())
    assert result["feedback_correction_rate"] is None
    assert result["reviewed_feedback_count"] == 0


@pytest.mark.asyncio
async def test_overview_auto_reply_acceptance_rate_is_null_not_zero_with_no_reviews(session):
    result = await dashboard_service.get_overview(session, "default", _wide_range())
    assert result["auto_reply_acceptance_rate"] is None
    assert result["auto_reply_reviewed_count"] == 0
