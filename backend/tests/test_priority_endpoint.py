"""
Integration tests for the priority classification endpoint (Module 3 / Phase 4).

Hits the real trained artifact (artifacts/priority_baseline.joblib), same
reasoning as test_spam_endpoint.py — verifies the endpoint actually
classifies, not just that request/response shapes wire together.

IMPORTANT: this model is trained on data/processed/priority_synthetic_v1
(see docs/data_audit_priority.md) — these tests confirm the pipeline
produces a valid, structurally correct response, NOT that the prediction is
"right" in a real-world sense. There is no ground truth to assert against
for that claim yet.
"""

from pathlib import Path

import pytest

from app.services.priority_service import _DEFAULT_ARTIFACT_DIR, get_priority_service


def _model_available() -> bool:
    return (Path(_DEFAULT_ARTIFACT_DIR) / "priority_baseline.joblib").exists()


pytestmark = pytest.mark.skipif(
    not _model_available(),
    reason="priority_baseline.joblib not found — run scripts/train_priority_model.py first",
)


@pytest.fixture(autouse=True)
def _clear_service_cache():
    get_priority_service.cache_clear()
    yield
    get_priority_service.cache_clear()


VALID_LABELS = {"Critical", "High", "Medium", "Low"}


def test_predict_returns_valid_priority_label(client):
    response = client.post(
        "/api/v1/priority/predict",
        json={
            "subject": "Quick question about the meeting",
            "body": "Hi, can we move our sync to 4pm tomorrow? Thanks!",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["priority"] in VALID_LABELS
    assert 0.0 <= body["confidence"] <= 1.0
    assert set(body["probabilities"].keys()) == VALID_LABELS
    # Each probability is independently rounded to 4dp before being returned
    # (see PriorityPredictor), so a 4-class sum can be off by a few 1e-4 —
    # 1e-6 would be asserting a precision the API never promised.
    assert abs(sum(body["probabilities"].values()) - 1.0) < 1e-3
    assert body["model_version"]
    assert body["processing_ms"] >= 0


def test_predict_accepts_optional_metadata(client):
    response = client.post(
        "/api/v1/priority/predict",
        json={
            "subject": "URGENT: production outage, please escalate",
            "body": "We are seeing a full outage affecting all customers, please escalate immediately.",
            "sender_email": "ops@example.com",
            "received_at": "2026-08-08T03:00:00Z",
            "recipient_to": ["support@example.com"],
            "has_attachments": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] in VALID_LABELS


def test_predict_requires_body(client):
    response = client.post("/api/v1/priority/predict", json={"subject": "no body field"})
    assert response.status_code == 422


def test_priority_feedback_is_logged(client, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_priority_feedback_logger

    client.app.dependency_overrides[get_priority_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="priority"
    )
    try:
        response = client.post(
            "/api/v1/priority/feedback",
            json={
                "subject": "Test",
                "body": "Test body",
                "predicted_label": "Low",
                "corrected_label": "Critical",
                "comment": "This was actually urgent",
            },
        )
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "logged"
        assert body["feedback_id"]

        logged = (tmp_path / "priority_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del client.app.dependency_overrides[get_priority_feedback_logger]
