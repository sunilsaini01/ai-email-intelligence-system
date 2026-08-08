"""
Integration tests for the intent detection endpoint (Module 7 / Phase 7B).

Hits the real trained artifact (artifacts/intent_baseline.joblib), skipped
if it doesn't exist -- same reasoning as test_category_endpoint.py, since
(unlike Sentiment) this module DOES have an artifact dependency.
"""

from pathlib import Path

import pytest

from app.services.intent_service import _DEFAULT_ARTIFACT_DIR, get_intent_service


def _model_available() -> bool:
    return (Path(_DEFAULT_ARTIFACT_DIR) / "intent_baseline.joblib").exists()


pytestmark = pytest.mark.skipif(
    not _model_available(),
    reason="intent_baseline.joblib not found — run scripts/train_intent_model.py first",
)


@pytest.fixture(autouse=True)
def _clear_service_cache():
    get_intent_service.cache_clear()
    yield
    get_intent_service.cache_clear()


VALID_LABELS = {
    "Complaint", "Inquiry", "Request", "Feedback", "Escalation",
    "Order", "Cancel", "Refund", "Schedule",
}


def test_predict_returns_a_structurally_valid_response(client):
    response = client.post(
        "/api/v1/intent/predict",
        json={
            "subject": "Cancel my subscription",
            "body": "Please cancel my subscription and refund order #45821 for John Smith, $120 on August 14th, 2026.",
        },
    )
    assert response.status_code == 200

    body = response.json()
    for intent in body["intents"]:
        assert intent["intent"] in VALID_LABELS
        assert 0.0 <= intent["confidence"] <= 1.0
    assert set(body["all_scores"].keys()) == VALID_LABELS
    assert body["entities"]["order_ids"] == ["45821"]
    assert "John Smith" in body["entities"]["person_names"]
    assert body["model_version"]
    assert body["processing_ms"] >= 0


def test_predict_can_return_zero_intents(client):
    response = client.post(
        "/api/v1/intent/predict",
        json={"subject": "FYI", "body": "The meeting notes from yesterday are attached."},
    )
    assert response.status_code == 200
    assert isinstance(response.json()["intents"], list)


def test_predict_requires_body(client):
    response = client.post("/api/v1/intent/predict", json={"subject": "no body field"})
    assert response.status_code == 422


def test_intent_feedback_is_logged(client, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_intent_feedback_logger

    client.app.dependency_overrides[get_intent_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="intent"
    )
    try:
        response = client.post(
            "/api/v1/intent/feedback",
            json={
                "subject": "Test",
                "body": "Test body",
                "predicted_label": ["Cancel"],
                "corrected_label": ["Cancel", "Refund"],
                "comment": "Also asked for a refund",
            },
        )
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "logged"
        assert body["feedback_id"]

        logged = (tmp_path / "intent_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del client.app.dependency_overrides[get_intent_feedback_logger]
