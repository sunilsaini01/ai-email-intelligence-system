"""
Integration tests for the sentiment analysis endpoint (Module 6 / Phase 7A).

No skip-if-missing-artifact guard, unlike priority/category's endpoint
tests -- VaderSentimentPredictor has no artifact dependency (see
app/services/sentiment_service.py's module docstring), so there is no
"hasn't been trained yet" state that could make this endpoint unavailable.
"""

from app.services.sentiment_service import get_sentiment_service

VALID_LABELS = {"Very Negative", "Negative", "Neutral", "Positive", "Very Positive"}


def _clear_cache():
    get_sentiment_service.cache_clear()


def test_predict_returns_valid_sentiment_label(client):
    _clear_cache()
    response = client.post(
        "/api/v1/sentiment/predict",
        json={
            "subject": "Thank you",
            "body": "This worked perfectly, really appreciate the quick turnaround!",
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["sentiment"] in VALID_LABELS
    assert 0.0 <= body["confidence"] <= 1.0
    assert set(body["probabilities"].keys()) == VALID_LABELS
    assert abs(sum(body["probabilities"].values()) - 1.0) < 1e-3
    assert body["model_version"]
    assert body["processing_ms"] >= 0


def test_predict_requires_body(client):
    response = client.post("/api/v1/sentiment/predict", json={"subject": "no body field"})
    assert response.status_code == 422


def test_predict_accepts_empty_subject(client):
    _clear_cache()
    response = client.post("/api/v1/sentiment/predict", json={"body": "Please see attached."})
    assert response.status_code == 200
    assert response.json()["sentiment"] in VALID_LABELS


def test_sentiment_feedback_is_logged(client, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_sentiment_feedback_logger

    client.app.dependency_overrides[get_sentiment_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="sentiment"
    )
    try:
        response = client.post(
            "/api/v1/sentiment/feedback",
            json={
                "subject": "Test",
                "body": "Test body",
                "predicted_label": "Neutral",
                "corrected_label": "Negative",
                "comment": "This was actually a complaint",
            },
        )
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "logged"
        assert body["feedback_id"]

        logged = (tmp_path / "sentiment_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del client.app.dependency_overrides[get_sentiment_feedback_logger]
