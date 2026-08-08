"""
Integration tests for the categorization endpoint (Module 4 / Phase 5).

Hits the real trained artifact (artifacts/category_baseline.joblib), same
reasoning as test_priority_endpoint.py — verifies the endpoint actually
classifies, not just that request/response shapes wire together.

IMPORTANT: this model is trained on data/processed/category_synthetic_v1
(see docs/data_audit_categorization.md) — these tests confirm the pipeline
produces a valid, structurally correct multi-label response, NOT that the
prediction is "right" in a real-world sense. There is no ground truth to
assert against for that claim yet.
"""

from pathlib import Path

import pytest

from app.feature_engineering.category_keywords import CATEGORY_LABELS
from app.services.category_service import _DEFAULT_ARTIFACT_DIR, get_category_service


def _model_available() -> bool:
    return (Path(_DEFAULT_ARTIFACT_DIR) / "category_baseline.joblib").exists()


pytestmark = pytest.mark.skipif(
    not _model_available(),
    reason="category_baseline.joblib not found — run scripts/train_category_model.py first",
)


@pytest.fixture(autouse=True)
def _clear_service_cache():
    get_category_service.cache_clear()
    yield
    get_category_service.cache_clear()


VALID_LABELS = set(CATEGORY_LABELS)


def test_predict_returns_valid_multilabel_response(client):
    response = client.post(
        "/api/v1/categorization/predict",
        json={
            "subject": "Please review the legal terms of the invoice before payment",
            "body": "Attached is the invoice, please have legal review the terms before we process payment.",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert isinstance(body["categories"], list)
    for entry in body["categories"]:
        assert entry["category"] in VALID_LABELS
        assert 0.0 <= entry["confidence"] <= 1.0

    assert set(body["all_scores"].keys()) == VALID_LABELS
    assert all(0.0 <= v <= 1.0 for v in body["all_scores"].values())
    assert body["model_version"]
    assert body["processing_ms"] >= 0


def test_predict_never_returns_zero_categories(client):
    """CategoryService's General-fallback safety net (see its module
    docstring) — the API contract is that `categories` is never empty, even
    if every binary classifier abstains."""
    response = client.post(
        "/api/v1/categorization/predict",
        json={"subject": "", "body": "."},
    )
    assert response.status_code == 200
    assert len(response.json()["categories"]) >= 1


def test_predict_accepts_optional_metadata(client):
    response = client.post(
        "/api/v1/categorization/predict",
        json={
            "subject": "VPN access request",
            "body": "I need VPN access provisioned for the new laptop before Monday.",
            "sender_email": "employee@example.com",
            "received_at": "2026-08-08T03:00:00Z",
            "recipient_to": ["it@example.com"],
            "has_attachments": False,
        },
    )
    assert response.status_code == 200
    assert len(response.json()["categories"]) >= 1


def test_predict_requires_body(client):
    response = client.post("/api/v1/categorization/predict", json={"subject": "no body field"})
    assert response.status_code == 422


def test_category_feedback_is_logged(client, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_category_feedback_logger

    client.app.dependency_overrides[get_category_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="category"
    )
    try:
        response = client.post(
            "/api/v1/categorization/feedback",
            json={
                "subject": "Test",
                "body": "Test body",
                "predicted_categories": ["General"],
                "corrected_categories": ["HR", "IT"],
                "comment": "Onboarding email, not General",
            },
        )
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "logged"
        assert body["feedback_id"]

        logged = (tmp_path / "category_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del client.app.dependency_overrides[get_category_feedback_logger]
