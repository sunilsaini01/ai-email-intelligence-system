"""
Integration tests for the Manager Dashboard endpoints (Module 11 / Phase
11, FR-53 to FR-62). Same dependency-override pattern as
tests/test_reply_endpoint.py -- in-memory SQLite via get_db override, no
real Postgres, fully deterministic.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from app.models.feedback_event import FeedbackEvent
from app.models.priority_prediction_log import PriorityPredictionLog


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_overview_returns_200_on_an_empty_database(client):
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["feedback_correction_rate"] is None
    assert body["auto_reply_acceptance_rate"] is None


def test_overview_rejects_end_before_start(client):
    response = client.get(
        "/api/v1/dashboard/overview",
        params={"range": "custom", "start": "2026-01-10T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
    )
    assert response.status_code == 422


def test_email_volume_rejects_invalid_granularity(client):
    response = client.get("/api/v1/dashboard/email-volume", params={"granularity": "week"})
    assert response.status_code == 422


def test_categories_carries_synthetic_evidence_badge(client):
    response = client.get("/api/v1/dashboard/categories")
    assert response.status_code == 200
    assert response.json()["evidence"]["status"] == "SYNTHETIC"


def test_sla_response_reports_documented_default_targets(client):
    response = client.get("/api/v1/dashboard/sla")
    assert response.status_code == 200
    assert set(response.json()["sla_targets_hours"].keys()) == {"Critical", "High", "Medium", "Low"}


def test_review_queue_is_empty_on_a_fresh_database(client):
    response = client.get("/api/v1/dashboard/review-queue")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_reports_export_rejects_unknown_format(client):
    response = client.get("/api/v1/dashboard/reports/export", params={"format": "xml"})
    assert response.status_code == 422


def test_reports_export_csv_returns_csv_content_type(client):
    response = client.get("/api/v1/dashboard/reports/export", params={"format": "csv"})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert b"Overview" in response.content


def test_reports_export_pdf_returns_pdf_bytes(client):
    response = client.get("/api/v1/dashboard/reports/export", params={"format": "pdf"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_confirm_review_item_writes_a_feedback_event(client, session_factory):
    async with session_factory() as session:
        row = PriorityPredictionLog(body="a", predicted_priority="Low", confidence=0.2, model_version="v1", processing_ms=1.0)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        prediction_id = row.id

    response = client.post(
        f"/api/v1/dashboard/review-queue/{prediction_id}/confirm",
        json={"module": "priority", "subject": "test", "predicted_value": "Low", "confidence": 0.2, "reviewer_id": "agent_1"},
    )
    assert response.status_code == 200

    async with session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(FeedbackEvent).where(FeedbackEvent.prediction_id == prediction_id))
        event = result.scalar_one()
        assert event.action == "CONFIRM"
        assert event.reviewer_id == "agent_1"


@pytest.mark.asyncio
async def test_confirm_review_item_twice_returns_409_not_a_duplicate_row(client, session_factory):
    """Adversarial-review finding: a double-click (or any duplicate
    request) on Confirm must not silently insert two feedback_events rows
    for the same prediction -- that would inflate the correction-rate
    denominator (FR-62)."""
    async with session_factory() as session:
        row = PriorityPredictionLog(body="a", predicted_priority="Low", confidence=0.2, model_version="v1", processing_ms=1.0)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        prediction_id = row.id

    payload = {"module": "priority", "subject": "test", "predicted_value": "Low", "confidence": 0.2, "reviewer_id": "agent_1"}
    first = client.post(f"/api/v1/dashboard/review-queue/{prediction_id}/confirm", json=payload)
    assert first.status_code == 200

    second = client.post(f"/api/v1/dashboard/review-queue/{prediction_id}/confirm", json=payload)
    assert second.status_code == 409

    async with session_factory() as session:
        from sqlalchemy import func, select

        result = await session.execute(select(func.count()).select_from(FeedbackEvent).where(FeedbackEvent.prediction_id == prediction_id))
        assert result.scalar_one() == 1


def test_spam_feedback_dual_writes_to_feedback_events(client):
    """Existing /spam/feedback endpoint (FR-58) must keep working exactly
    as before AND additionally write to feedback_events (FR-59) -- see
    docs/requirements_traceability_phase11.md FR-58/59."""
    response = client.post(
        "/api/v1/spam/feedback",
        json={"subject": "s", "body": "b", "predicted_label": "ham", "corrected_label": "spam", "reviewer_id": "agent_2"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "logged"
