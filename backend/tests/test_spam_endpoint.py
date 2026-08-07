"""
Integration tests for the spam classification endpoint (Module 2 / Phase 3).

These hit the real trained model artifact (artifacts/spam_baseline.joblib),
not a mock — the whole point is verifying the endpoint actually classifies
correctly, not just that it wires request/response shapes together.
"""

from pathlib import Path

import pytest

from app.services.feedback_service import FeedbackLogger, get_feedback_logger
from app.services.spam_service import _DEFAULT_ARTIFACT_DIR, get_spam_service


def _model_available() -> bool:
    return (Path(_DEFAULT_ARTIFACT_DIR) / "spam_baseline.joblib").exists()


pytestmark = pytest.mark.skipif(
    not _model_available(),
    reason="spam_baseline.joblib not found — run scripts/train_spam_model.py first",
)


@pytest.fixture(autouse=True)
def _clear_service_cache():
    get_spam_service.cache_clear()
    yield
    get_spam_service.cache_clear()


def test_predict_flags_obvious_spam(client):
    response = client.post(
        "/api/v1/spam/predict",
        json={
            "subject": "URGENT: You have won a free prize!!!",
            "body": "Click here now to claim your free iPhone. Limited time offer, act now!",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["is_spam"] is True
    assert body["status"] == "quarantined"
    assert 0.0 <= body["spam_score"] <= 1.0


def test_predict_clears_obvious_ham(client):
    response = client.post(
        "/api/v1/spam/predict",
        json={
            "subject": "Re: Q3 budget review",
            "body": (
                "Hi Sarah, thanks for sending over the spreadsheet yesterday. I went "
                "through the numbers with the finance team this morning and everything "
                "looks correct on our end. Can we schedule a call next Tuesday to "
                "finalize the department allocations before the board meeting?"
            ),
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["is_spam"] is False
    assert body["status"] == "clear"


def test_predict_requires_body(client):
    response = client.post("/api/v1/spam/predict", json={"subject": "no body field"})
    assert response.status_code == 422


def test_feedback_is_logged(client, tmp_path):
    # Without this override, FeedbackLogger's default writes to the real
    # artifacts/spam_feedback.jsonl — every test run was appending a row to a
    # file that gets committed to the repo. tmp_path isolates it the same way
    # test_spam_prediction_log.py isolates the DB write with an in-memory
    # SQLite session, instead of hitting a real dependency.
    client.app.dependency_overrides[get_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path)
    )
    try:
        response = client.post(
            "/api/v1/spam/feedback",
            json={
                "subject": "Test",
                "body": "Test body",
                "predicted_label": "ham",
                "corrected_label": "spam",
                "comment": "test correction",
            },
        )
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "logged"
        assert body["feedback_id"]

        logged = (tmp_path / "spam_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del client.app.dependency_overrides[get_feedback_logger]
