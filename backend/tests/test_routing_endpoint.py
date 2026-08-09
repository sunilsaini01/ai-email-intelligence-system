"""
Integration tests for the routing endpoint (Module 8 / Phase 8).

Hits the real trained artifacts for spam/priority/category/intent (routing
itself has none of its own), skipped if any of the four is missing -- same
reasoning as test_intent_endpoint.py/test_category_endpoint.py.

Deliberately avoids asserting a specific department/action for any given
input text -- the four upstream classifiers' actual behavior on a crafted
example isn't something this test should hard-code (that would make it an
undocumented pin on model behavior, not a routing-contract test). Instead
these assert the response's STRUCTURE and INVARIANTS (RULE 10 never drops an
email; quarantine implies no department; every department is in the known
taxonomy).
"""

from pathlib import Path

import pytest

from app.routing.department_taxonomy import DEPARTMENTS
from app.services.category_service import _DEFAULT_ARTIFACT_DIR as CATEGORY_DIR
from app.services.intent_service import _DEFAULT_ARTIFACT_DIR as INTENT_DIR
from app.services.priority_service import _DEFAULT_ARTIFACT_DIR as PRIORITY_DIR
from app.services.routing_service import get_routing_service
from app.services.spam_service import _DEFAULT_ARTIFACT_DIR as SPAM_DIR

_REQUIRED_ARTIFACTS = [
    (SPAM_DIR, "spam_baseline.joblib"),
    (PRIORITY_DIR, "priority_baseline.joblib"),
    (CATEGORY_DIR, "category_baseline.joblib"),
    (INTENT_DIR, "intent_baseline.joblib"),
]


def _all_artifacts_available() -> bool:
    return all((Path(d) / f).exists() for d, f in _REQUIRED_ARTIFACTS)


pytestmark = pytest.mark.skipif(
    not _all_artifacts_available(),
    reason="One or more of spam/priority/category/intent artifacts not found -- "
    "run the corresponding scripts/train_*.py first",
)


@pytest.fixture(autouse=True)
def _clear_service_cache():
    get_routing_service.cache_clear()
    yield
    get_routing_service.cache_clear()


VALID_ACTIONS = {"auto_route", "human_review", "quarantine", "fallback"}


def test_predict_returns_a_structurally_valid_response(client):
    response = client.post(
        "/api/v1/routing/predict",
        json={
            "subject": "Refund request",
            "body": "Please cancel my subscription and refund order #45821 for John Smith, $120.",
            "sender_email": "customer@example.com",
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["action"] in VALID_ACTIONS
    assert body["department"] in (*DEPARTMENTS, None)
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["requires_human_review"], bool)
    assert isinstance(body["matched_rules"], list) and body["matched_rules"]
    assert body["routing_rules_version"] == "routing_rules_v1"
    assert body["keyword_matcher_version"] == "routing_keywords_v1"
    assert body["processing_ms"] >= 0


def test_quarantine_action_implies_no_department(client):
    response = client.post(
        "/api/v1/routing/predict",
        json={
            "subject": "WIN A FREE PRIZE NOW",
            "body": "CLICK HERE to claim your free lottery winnings!!! Limited time offer, act now!",
        },
    )
    assert response.status_code == 200
    body = response.json()

    if body["action"] == "quarantine":
        assert body["department"] is None
    else:
        assert body["department"] is not None


def test_predict_never_drops_an_empty_email(client):
    """An empty email is a completely valid outcome, not a special case to
    special-case away. Notably, the REAL trained spam model (threshold 0.06,
    calibrated for FR-11's >99% recall) classifies empty text as spam --
    verified directly: SpamService().classify("", "") returns is_spam=True.
    That's a real, disclosed characteristic of an aggressively recall-tuned
    classifier on a degenerate input, not a routing bug -- and quarantine
    IS the safe, defined outcome here (RULE 10 never DROPS an email; it
    doesn't guarantee every email gets a department). See
    docs/error_analysis_routing.md."""
    response = client.post("/api/v1/routing/predict", json={"subject": "", "body": ""})
    assert response.status_code == 200
    body = response.json()

    assert body["action"] in {"auto_route", "human_review", "quarantine", "fallback"}
    if body["action"] == "quarantine":
        assert body["department"] is None
    else:
        assert body["department"] is not None
    assert body["matched_rules"]  # a decision was made and is explainable either way


def test_predict_requires_body(client):
    response = client.post("/api/v1/routing/predict", json={"subject": "no body field"})
    assert response.status_code == 422


def test_predict_supporting_signals_expose_reliability_labels(client):
    response = client.post(
        "/api/v1/routing/predict",
        json={"subject": "Question", "body": "Do you support SSO integration?"},
    )
    body = response.json()
    signals = body["supporting_signals"]
    assert signals["sentiment"]["reliability"] == "unvalidated"
    assert signals["category"]["reliability"] == "provisional_synthetic"
    assert signals["spam"]["reliability"] == "validated"


def test_routing_feedback_is_logged(client, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_routing_feedback_logger

    client.app.dependency_overrides[get_routing_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="routing"
    )
    try:
        response = client.post(
            "/api/v1/routing/feedback",
            json={
                "subject": "Test",
                "body": "Test body",
                "predicted_department": "Support",
                "corrected_department": "IT",
                "predicted_action": "auto_route",
                "corrected_action": "auto_route",
                "comment": "Wrong department",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "logged"
        assert body["feedback_id"]

        logged = (tmp_path / "routing_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del client.app.dependency_overrides[get_routing_feedback_logger]
