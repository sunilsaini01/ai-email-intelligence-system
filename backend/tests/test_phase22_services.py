"""
DB-backed tests for the Phase 22 services, against in-memory SQLite (same
fixture shape as tests/test_feedback_event_repository.py): organization
settings, FR-41 threshold recompute, FR-42 assignment, FR-18
notifications + webhook, FR-17 sender history, GDPR erasure/retention,
the SLA sweep, weekly reports (FR-56), the retraining runner (FR-61) and
drift (FR-72).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 -- registers every table on Base.metadata
from app.database.repositories.retraining_trigger_repository import RetrainingTriggerRepository
from app.database.session import Base
from app.mlops import retraining_runner
from app.models.email_record import EmailRecord
from app.models.feedback_event import ACTION_CONFIRM, ACTION_CORRECTION, FeedbackEvent
from app.models.generated_report import GeneratedReport
from app.models.notification import (
    KIND_CRITICAL_EMAIL,
    KIND_SLA_AT_RISK,
    KIND_SLA_BREACHED,
    WEBHOOK_DELIVERED,
    WEBHOOK_NOT_CONFIGURED,
    Notification,
)
from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.reply_draft import ReplyDraft
from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.models.user import ROLE_ADMIN, ROLE_AGENT, User
from app.services import notification_service, privacy_service, scheduled_jobs
from app.services.assignment_service import assign_agent
from app.services.drift_service import compute_drift
from app.services.notification_service import notify, notify_critical_email
from app.services.organization_settings_service import get_org_settings, update_org_settings
from app.services.routing_context import count_sender_negative_history, load_routing_context
from app.services.routing_feedback_service import recompute_routing_thresholds

ORG = "default"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _email(subject="Order missing", body="Where is my order?", sender="cust@example.com", **kw) -> EmailRecord:
    return EmailRecord(
        organization_id=kw.pop("organization_id", ORG),
        content_hash=uuid.uuid4().hex,
        subject=subject,
        body=body,
        sender_email=sender,
        **kw,
    )


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


# --- settings ------------------------------------------------------------------


async def test_settings_merge_defaults_and_ignore_unknown_keys(session):
    assert (await get_org_settings(session, ORG))["assignment_strategy"] == "round_robin"
    updated = await update_org_settings(session, ORG, {"assignment_strategy": "skills", "bogus": 1})
    assert updated["assignment_strategy"] == "skills"
    assert "bogus" not in updated
    assert (await get_org_settings(session, ORG))["notify_on_critical"] is True


# --- FR-41 --------------------------------------------------------------------


async def test_routing_feedback_recompute_writes_thresholds(session):
    for i in range(12):
        corrected = i < 6
        session.add(
            FeedbackEvent(
                module="routing",
                organization_id=ORG,
                action=ACTION_CORRECTION if corrected else ACTION_CONFIRM,
                original_value={"department": "Sales", "action": "auto_route"},
                corrected_value={"department": "Support" if corrected else "Sales"},
            )
        )
    await session.commit()

    thresholds = await recompute_routing_thresholds(session, ORG)
    assert thresholds["Sales"] > 0.55
    assert (await get_org_settings(session, ORG))["routing_thresholds"] == thresholds
    route_kwargs, _ = await load_routing_context(session, ORG, "")
    assert route_kwargs["department_thresholds"] == thresholds


# --- FR-42 --------------------------------------------------------------------


async def test_assign_agent_only_considers_active_agents_in_department(session):
    eligible = User(email="a@x.com", hashed_password="x", organization_id=ORG, role=ROLE_AGENT, department="Billing")
    session.add_all(
        [
            eligible,
            User(email="b@x.com", hashed_password="x", organization_id=ORG, role=ROLE_AGENT, department="Sales"),
            User(email="c@x.com", hashed_password="x", organization_id=ORG, role=ROLE_AGENT, department="Billing",
                 is_active=False),
            User(email="d@x.com", hashed_password="x", organization_id=ORG, role=ROLE_ADMIN, department="Billing"),
        ]
    )
    await session.commit()

    agent = await assign_agent(session, ORG, "Billing", "round_robin")
    assert agent is not None and agent.email == "a@x.com"
    assert agent.last_assigned_at is not None
    assert await assign_agent(session, ORG, None, "round_robin") is None
    assert await assign_agent(session, ORG, "Billing", "none") is None


# --- FR-18 --------------------------------------------------------------------


async def test_critical_notification_in_app_only_without_webhook(session):
    email_id = uuid.uuid4()
    n = await notify_critical_email(session, ORG, email_id, "Server down", "IT")
    assert n.kind == KIND_CRITICAL_EMAIL and n.webhook_status == WEBHOOK_NOT_CONFIGURED
    # Same email again -> deduplicated.
    assert await notify_critical_email(session, ORG, email_id, "Server down", "IT") is None


async def test_critical_notification_posts_webhook_without_email_body(session, monkeypatch):
    await update_org_settings(session, ORG, {"notification_webhook_url": "https://hooks.example.com/x"})
    sent = {}

    async def fake_deliver(url, payload):
        sent.update(url=url, payload=payload)
        return WEBHOOK_DELIVERED

    monkeypatch.setattr(notification_service, "_deliver_webhook", fake_deliver)
    monkeypatch.setattr(notification_service, "safe_subject", lambda s: "[anon]")
    n = await notify_critical_email(session, ORG, uuid.uuid4(), "Refund for John", "Billing")
    assert n.webhook_status == WEBHOOK_DELIVERED
    assert sent["url"] == "https://hooks.example.com/x"
    assert sent["payload"]["subject"] == "[anon]"
    assert "body" not in sent["payload"]


async def test_critical_notifications_can_be_switched_off(session):
    await update_org_settings(session, ORG, {"notify_on_critical": False})
    assert await notify_critical_email(session, ORG, uuid.uuid4(), "x", "IT") is None


# --- FR-17 sender history ------------------------------------------------------


async def test_sender_negative_history_counts_only_recent_negative_rows_before_cutoff(session):
    now = datetime.now(UTC)

    def row(label, age_days, sender="Cust@Example.com"):
        return SentimentPredictionLog(
            organization_id=ORG, subject="", body="b", predicted_sentiment=label, confidence=0.9,
            model_version="t", processing_ms=1, sender_email=sender.lower(), created_at=now - timedelta(days=age_days),
        )

    session.add_all([row("Negative", 1), row("Very Negative", 2), row("Positive", 1), row("Negative", 60),
                     row("Negative", 1, sender="other@example.com")])
    await session.commit()
    assert await count_sender_negative_history(session, ORG, "CUST@example.com") == 2
    assert await count_sender_negative_history(session, ORG, "cust@example.com", before=now - timedelta(days=1, hours=12)) == 1
    assert await count_sender_negative_history(session, ORG, "") == 0


# --- GDPR -----------------------------------------------------------------------


async def test_erase_data_subject_removes_linked_rows_only(session, tmp_path, monkeypatch):
    monkeypatch.setattr(privacy_service, "_delete_vectors", lambda records: len(records))
    target = _email(sender="Leaving@Example.com")
    keep = _email(subject="Other", body="Unrelated", sender="stay@example.com")
    session.add_all([target, keep])
    await session.commit()
    session.add_all(
        [
            PriorityPredictionLog(organization_id=ORG, subject=target.subject, body=target.body, predicted_priority="High",
                                  confidence=0.9, model_version="t", processing_ms=1),
            PriorityPredictionLog(organization_id=ORG, subject=keep.subject, body=keep.body, predicted_priority="Low",
                                  confidence=0.9, model_version="t", processing_ms=1),
            SentimentPredictionLog(organization_id=ORG, subject="different", body="different", predicted_sentiment="Negative",
                                   confidence=0.9, model_version="t", processing_ms=1, sender_email="leaving@example.com"),
            ReplyDraft(organization_id=ORG, source_email_id=target.id, source_subject="", source_body="x",
                       generation_policy="NORMAL_REPLY"),
            Notification(organization_id=ORG, kind=KIND_CRITICAL_EMAIL, title="t", email_id=target.id),
        ]
    )
    await session.commit()
    (tmp_path / "spam_feedback.jsonl").write_text(
        json.dumps({"subject": target.subject, "body": target.body}) + "\n" + json.dumps({"subject": "a", "body": "b"}) + "\n",
        encoding="utf-8",
    )

    counts = await privacy_service.erase_data_subject(session, ORG, "leaving@example.com", artifact_dir=tmp_path)

    assert counts["emails"] == 1 and counts["vectors"] == 1
    assert counts["priority_prediction_logs"] == 1
    assert counts["sentiment_prediction_logs"] == 1
    assert counts["reply_drafts"] == 1 and counts["notifications"] == 1
    assert counts["feedback_file_lines"] == 1
    assert await _count(session, EmailRecord) == 1
    assert await _count(session, PriorityPredictionLog) == 1
    assert (tmp_path / "spam_feedback.jsonl").read_text(encoding="utf-8").count("\n") == 1


async def test_retention_purge_deletes_only_expired_rows(session, monkeypatch):
    monkeypatch.setattr(privacy_service, "_delete_vectors", lambda records: len(records))
    old = datetime.now(UTC) - timedelta(days=400)
    session.add_all([_email(created_at=old), _email()])
    await session.commit()
    counts = await privacy_service.purge_expired_data(session, ORG, retention_days=365)
    assert counts["emails"] == 1
    assert await _count(session, EmailRecord) == 1


# --- SLA sweep / reports ---------------------------------------------------------


async def test_sla_sweep_notifies_at_risk_and_breached_once(session):
    now = datetime.now(UTC)
    session.add_all(
        [
            _email(subject="ok", priority="Low", received_at=now),
            _email(subject="risk", priority="Critical", received_at=now - timedelta(hours=1.6)),
            _email(subject="late", priority="Critical", received_at=now - timedelta(hours=3)),
            _email(subject="done", priority="Critical", received_at=now - timedelta(hours=3), resolution_status="RESOLVED"),
        ]
    )
    await session.commit()

    totals = await scheduled_jobs.sla_sweep(session)
    assert totals == {"within_sla": 1, "at_risk": 1, "breached": 1}
    kinds = sorted((await session.execute(select(Notification.kind))).scalars())
    assert kinds == sorted([KIND_SLA_AT_RISK, KIND_SLA_BREACHED])
    await scheduled_jobs.sla_sweep(session)
    assert await _count(session, Notification) == 2


async def test_weekly_reports_generated_once_per_week_on_report_day(session):
    monday = datetime(2026, 10, 26, 9, tzinfo=UTC)
    assert await scheduled_jobs.generate_weekly_reports(session, now=monday) == 1
    assert await scheduled_jobs.generate_weekly_reports(session, now=monday + timedelta(hours=1)) == 0
    formats = sorted((await session.execute(select(GeneratedReport.report_format))).scalars())
    assert formats == ["csv", "pdf"]
    assert await scheduled_jobs.generate_weekly_reports(session, now=monday + timedelta(days=1)) == 0


def test_previous_week_bounds():
    start, end = scheduled_jobs.previous_week_bounds(datetime(2026, 10, 28, 15, tzinfo=UTC))
    assert start == datetime(2026, 10, 19, tzinfo=UTC) and end == datetime(2026, 10, 26, tzinfo=UTC)


# --- FR-61 retraining -------------------------------------------------------------


async def test_retraining_runner_executes_and_records_result(session, monkeypatch):
    monkeypatch.setattr(retraining_runner, "_run_training_script", lambda module: (True, "registered candidate v7"))
    repo = RetrainingTriggerRepository(session)
    await repo.create(module="priority", feedback_count_at_trigger=50, threshold_used=50)
    await repo.create(module="sentiment", feedback_count_at_trigger=50, threshold_used=50)

    assert await scheduled_jobs.run_retraining(session) == 2
    triggers = {t.module: t for t in await repo.list_recent()}
    assert triggers["priority"].status == "COMPLETED"
    assert "registered candidate v7" in triggers["priority"].result_message
    assert triggers["priority"].consumed is True
    assert triggers["sentiment"].status == "NOT_APPLICABLE"
    assert await repo.has_open_trigger("priority") is False


async def test_failed_retraining_is_recorded(session, monkeypatch):
    monkeypatch.setattr(retraining_runner, "_run_training_script", lambda module: (False, "Traceback: boom"))
    await RetrainingTriggerRepository(session).create(module="spam", feedback_count_at_trigger=1, threshold_used=1)
    assert await retraining_runner.run_next_trigger(session) == "FAILED"


# --- FR-72 drift ---------------------------------------------------------------------


async def test_compute_drift_flags_shifted_priority_distribution(session):
    now = datetime.now(UTC)

    def row(label, age_days):
        return PriorityPredictionLog(organization_id=ORG, subject="", body="b", predicted_priority=label,
                                     confidence=0.9, model_version="t", processing_ms=1,
                                     created_at=now - timedelta(days=age_days))

    session.add_all([row("Low", 10) for _ in range(40)] + [row("Critical", 1) for _ in range(40)])
    await session.commit()
    drift = {d.module: d for d in await compute_drift(session, ORG)}
    assert drift["priority"].prediction_status == "significant"
    assert drift["spam"].prediction_status == "insufficient_data"


async def test_notify_dedup_is_per_organization(session):
    assert await notify(session, "org-a", kind="x", title="t", dedup_key="k", send_webhook=False) is not None
    assert await notify(session, "org-b", kind="x", title="t", dedup_key="k", send_webhook=False) is not None
    assert await notify(session, "org-a", kind="x", title="t", dedup_key="k", send_webhook=False) is None
