"""
API tests for the Phase 22 endpoints: admin settings/taxonomy/users/GDPR,
notifications, model operations, dashboard sender trends and generated
reports -- including the agent < manager < admin RBAC gates (PRD SS6.4).
Same in-memory SQLite + get_db override pattern as
tests/test_routing_override_endpoints.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.auth_dependency import has_role_at_least
from app.core.security import create_access_token, decode_access_token
from app.database.session import Base, get_db
from app.main import create_app
from app.models.generated_report import GeneratedReport
from app.models.notification import Notification
from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.models.user import ROLE_ADMIN, ROLE_AGENT, ROLE_MANAGER, User
from tests.conftest import (
    TEST_ADMIN_USER_ID,
    override_admin_auth,
    override_auth,
    override_manager_auth,
)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    await engine.dispose()


def _client(session_factory, auth) -> TestClient:
    async def override_get_db():
        async with session_factory() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_db] = override_get_db
    auth(application)
    return TestClient(application)


@pytest.fixture
def agent_client(session_factory):
    return _client(session_factory, override_auth)


@pytest.fixture
def manager_client(session_factory):
    return _client(session_factory, override_manager_auth)


@pytest.fixture
def admin_client(session_factory):
    return _client(session_factory, override_admin_auth)


# --- RBAC / RS256 ---------------------------------------------------------------


def test_role_hierarchy():
    agent, manager, admin = (User(role=r) for r in (ROLE_AGENT, ROLE_MANAGER, ROLE_ADMIN))
    assert has_role_at_least(admin, ROLE_MANAGER) and has_role_at_least(manager, ROLE_MANAGER)
    assert not has_role_at_least(agent, ROLE_MANAGER)
    assert not has_role_at_least(User(role="member"), ROLE_AGENT)


def test_access_tokens_are_rs256_signed():
    import jwt

    token = create_access_token(subject=str(uuid.uuid4()), organization_id="o", role=ROLE_AGENT)
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    assert decode_access_token(token)["org"] == "o"


def test_settings_read_requires_manager_and_write_requires_admin(agent_client, manager_client, admin_client):
    assert agent_client.get("/api/v1/admin/settings").status_code == 403
    assert manager_client.get("/api/v1/admin/settings").status_code == 200
    assert manager_client.put("/api/v1/admin/settings", json={"notify_on_critical": False}).status_code == 403

    response = admin_client.put(
        "/api/v1/admin/settings",
        json={"notification_webhook_url": "https://hooks.example.com/abc", "assignment_strategy": "skills",
              "data_retention_days": 365},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notification_webhook_url"] == "https://hooks.example.com/abc"
    assert body["assignment_strategy"] == "skills"
    assert body["data_retention_days"] == 365

    cleared = admin_client.put("/api/v1/admin/settings", json={"clear_webhook": True}).json()
    assert cleared["notification_webhook_url"] is None
    assert cleared["assignment_strategy"] == "skills"


def test_settings_reject_bad_values(admin_client):
    assert admin_client.put("/api/v1/admin/settings", json={"assignment_strategy": "random"}).status_code == 422
    assert admin_client.put("/api/v1/admin/settings", json={"notification_webhook_url": "not a url"}).status_code == 422


# --- FR-23 taxonomy -----------------------------------------------------------


def test_category_taxonomy_rename_and_disable(agent_client, admin_client):
    labels = {c["label"] for c in agent_client.get("/api/v1/admin/category-taxonomy").json()["categories"]}
    assert "General" in labels and "Marketing" in labels

    update = {"categories": [{"label": "Marketing", "enabled": False}, {"label": "Support", "display_name": "Customer Care"}]}
    assert agent_client.put("/api/v1/admin/category-taxonomy", json=update).status_code == 403
    body = admin_client.put("/api/v1/admin/category-taxonomy", json=update).json()
    by_label = {c["label"]: c for c in body["categories"]}
    assert by_label["Marketing"]["enabled"] is False
    assert by_label["Support"]["display_name"] == "Customer Care"


def test_category_taxonomy_rejects_unknown_labels_and_disabling_general(admin_client):
    assert admin_client.put("/api/v1/admin/category-taxonomy",
                            json={"categories": [{"label": "Shipping"}]}).status_code == 422
    assert admin_client.put("/api/v1/admin/category-taxonomy",
                            json={"categories": [{"label": "General", "enabled": False}]}).status_code == 422


# --- users ------------------------------------------------------------------------


async def test_admin_manages_users_but_cannot_demote_self(admin_client, session_factory):
    async with session_factory() as s:
        agent = User(email="agent@x.com", hashed_password="x", organization_id="default", role=ROLE_AGENT)
        s.add_all([agent, User(id=TEST_ADMIN_USER_ID, email="adm@x.com", hashed_password="x",
                               organization_id="default", role=ROLE_ADMIN)])
        await s.commit()
        agent_id = agent.id

    assert len(admin_client.get("/api/v1/admin/users").json()["users"]) == 2
    updated = admin_client.patch(
        f"/api/v1/admin/users/{agent_id}", json={"role": "manager", "department": "Billing", "skills": ["Refund", " "]}
    ).json()
    assert updated["role"] == "manager" and updated["department"] == "Billing" and updated["skills"] == ["Refund"]

    assert admin_client.patch(f"/api/v1/admin/users/{agent_id}", json={"role": "owner"}).status_code == 422
    assert admin_client.patch(f"/api/v1/admin/users/{TEST_ADMIN_USER_ID}", json={"role": "agent"}).status_code == 409
    assert admin_client.patch(f"/api/v1/admin/users/{uuid.uuid4()}", json={"role": "agent"}).status_code == 404


def test_user_listing_is_admin_only(manager_client):
    assert manager_client.get("/api/v1/admin/users").status_code == 403


# --- GDPR ---------------------------------------------------------------------------


def test_erasure_requires_admin_and_confirmation(manager_client, admin_client, monkeypatch):
    payload = {"sender_email": "gone@example.com", "confirm": True}
    assert manager_client.post("/api/v1/admin/privacy/erase", json=payload).status_code == 403
    assert admin_client.post("/api/v1/admin/privacy/erase", json={**payload, "confirm": False}).status_code == 422

    async def fake_erase(db, organization_id, sender_email):
        return {"emails": 0}

    monkeypatch.setattr("app.api.v1.endpoints.admin.erase_data_subject", fake_erase)
    response = admin_client.post("/api/v1/admin/privacy/erase", json=payload)
    assert response.status_code == 200 and response.json()["deleted"] == {"emails": 0}


# --- notifications --------------------------------------------------------------------


async def test_notifications_list_and_mark_read(agent_client, session_factory):
    async with session_factory() as s:
        s.add_all([Notification(organization_id="default", kind="critical_email", title="A"),
                   Notification(organization_id="other-org", kind="critical_email", title="B")])
        await s.commit()

    listing = agent_client.get("/api/v1/notifications").json()
    assert [n["title"] for n in listing["notifications"]] == ["A"]
    assert listing["unread_count"] == 1
    assert agent_client.post("/api/v1/notifications/read", json={}).json()["updated"] == 1
    assert agent_client.get("/api/v1/notifications?unread_only=true").json()["notifications"] == []


# --- model operations ---------------------------------------------------------------------


def test_manual_retrain_queues_once_and_rejects_non_trainable(manager_client, admin_client):
    assert manager_client.post("/api/v1/models/retrain", json={"module": "spam"}).status_code == 403
    queued = admin_client.post("/api/v1/models/retrain", json={"module": "spam"})
    assert queued.status_code == 202 and queued.json()["status"] == "PENDING" and queued.json()["source"] == "manual"
    assert admin_client.post("/api/v1/models/retrain", json={"module": "spam"}).status_code == 409
    assert admin_client.post("/api/v1/models/retrain", json={"module": "sentiment"}).status_code == 422
    assert [t["module"] for t in manager_client.get("/api/v1/models/retraining").json()["triggers"]] == ["spam"]


def test_drift_endpoint_is_manager_only(agent_client, manager_client):
    assert agent_client.get("/api/v1/models/drift").status_code == 403
    body = manager_client.get("/api/v1/models/drift").json()
    assert {m["module"] for m in body["modules"]} == {"spam", "priority", "category", "sentiment", "intent"}


# --- dashboard additions --------------------------------------------------------------------


async def test_generated_reports_list_and_download(manager_client, agent_client, session_factory):
    start = datetime(2026, 10, 19, tzinfo=UTC)
    async with session_factory() as s:
        report = GeneratedReport(organization_id="default", period_start=start, period_end=start + timedelta(days=7),
                                 report_format="csv", content=b"a,b\n1,2\n")
        s.add(report)
        await s.commit()
        report_id = report.id

    assert agent_client.get("/api/v1/dashboard/reports/generated").status_code == 403
    listing = manager_client.get("/api/v1/dashboard/reports/generated").json()["reports"]
    assert listing[0]["size_bytes"] == 8
    download = manager_client.get(f"/api/v1/dashboard/reports/generated/{report_id}")
    assert download.status_code == 200 and download.content == b"a,b\n1,2\n"
    assert manager_client.get(f"/api/v1/dashboard/reports/generated/{uuid.uuid4()}").status_code == 404


def test_report_export_requires_manager(agent_client):
    assert agent_client.get("/api/v1/dashboard/reports/export?format=csv&range=week").status_code == 403


async def test_sender_sentiment_trends(agent_client, session_factory):
    now = datetime.now(UTC)
    async with session_factory() as s:
        for days, label in ((1, "Very Negative"), (2, "Very Negative"), (3, "Negative")):
            s.add(SentimentPredictionLog(organization_id="default", subject="", body="b", predicted_sentiment=label,
                                         confidence=0.9, model_version="t", processing_ms=1,
                                         sender_email="angry@example.com", created_at=now - timedelta(days=days)))
        await s.commit()

    senders = agent_client.get("/api/v1/dashboard/sentiment/senders").json()["senders"]
    assert senders[0]["sender_email"] == "angry@example.com"
    assert senders[0]["escalation_candidate"] is True
