"""
Integration tests for the summarization endpoint (Module 5 / Phase 6).
Uses the `client` fixture (tests/conftest.py) — unlike spam/priority/
category, no skipif-on-missing-artifact guard is needed here (see
app/api/v1/endpoints/summarization.py's docstring: nothing needs to be
pre-trained for the extractive default path).
"""


def _long_body(word_count: int = 250) -> str:
    return ". ".join(f"This is filler sentence number {i} in a long email" for i in range(word_count // 8)) + "."


def test_predict_short_email_is_returned_unsummarized(client):
    response = client.post(
        "/api/v1/summarization/predict",
        json={"body": "Are we still on for lunch tomorrow?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["skipped_short_input"] is True
    assert body["summary"] == "Are we still on for lunch tomorrow?"


def test_predict_long_email_is_summarized_extractively_by_default(client):
    response = client.post(
        "/api/v1/summarization/predict",
        json={"subject": "Budget review", "body": _long_body(300)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["skipped_short_input"] is False
    assert body["summary_type"] == "extractive"
    assert body["model_version"] == "textrank-tfidf-v1"
    assert body["processing_ms"] >= 0
    assert set(body["preserved_entities"].keys()) == {"dates", "monetary_amounts", "names"}


def test_predict_accepts_thread_messages(client):
    response = client.post(
        "/api/v1/summarization/predict",
        json={
            "messages": [
                {"body": _long_body(200), "received_at": "2026-01-01T00:00:00Z"},
                {"body": "One more thing - please also check the vendor invoice.", "received_at": "2026-01-02T00:00:00Z"},
            ]
        },
    )
    assert response.status_code == 200


def test_predict_rejects_both_body_and_messages(client):
    response = client.post(
        "/api/v1/summarization/predict",
        json={"body": "some text", "messages": [{"body": "other text"}]},
    )
    assert response.status_code == 422


def test_predict_rejects_neither_body_nor_messages(client):
    response = client.post("/api/v1/summarization/predict", json={"subject": "empty request"})
    assert response.status_code == 422


def test_predict_rejects_invalid_summary_type(client):
    response = client.post(
        "/api/v1/summarization/predict",
        json={"body": _long_body(300), "summary_type": "not_a_real_type"},
    )
    assert response.status_code == 422


def test_feedback_is_logged(client, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_summarization_feedback_logger

    client.app.dependency_overrides[get_summarization_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="summarization"
    )
    try:
        response = client.post(
            "/api/v1/summarization/feedback",
            json={
                "original_text": "the original long email text",
                "generated_summary": "a generated summary",
                "accepted": False,
                "corrected_summary": "a better summary",
                "quality_score": 2,
                "reason": "missed the deadline mentioned in the email",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "logged"
        assert body["feedback_id"]

        logged = (tmp_path / "summarization_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del client.app.dependency_overrides[get_summarization_feedback_logger]


def test_feedback_quality_score_out_of_range_is_rejected(client):
    response = client.post(
        "/api/v1/summarization/feedback",
        json={
            "original_text": "text",
            "generated_summary": "summary",
            "accepted": True,
            "quality_score": 10,  # out of the 1-5 range
        },
    )
    assert response.status_code == 422
