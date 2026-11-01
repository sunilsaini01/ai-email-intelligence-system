"""
Pure-logic tests for the Phase 22 PRD gap closure: emotion detection
(FR-30), priority adjustment (FR-31/FR-17), learned routing thresholds
(FR-41), category taxonomy (FR-23), agent selection (FR-42), drift
statistics (FR-72), sender trends (FR-32), linear explanations (SS6.5),
feedback-to-training rows (FR-61) and the rate limiter (SS13.1).
"""

import json
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MultiLabelBinarizer

from app.inference.explainability import explain_linear, explain_prediction
from app.middleware.rate_limit import RateLimitMiddleware
from app.mlops import feedback_training_data
from app.mlops.drift import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_SIGNIFICANT,
    STATUS_STABLE,
    evaluate_module,
    population_stability_index,
)
from app.models.user import User
from app.nlp.emotion_detector import detect_emotions
from app.routing.feedback_weights import (
    MIN_SAMPLES,
    THRESHOLD_CAP,
    THRESHOLD_FLOOR,
    DepartmentFeedback,
    compute_department_thresholds,
)
from app.routing.priority_adjustment import SENDER_NEGATIVE_HISTORY_THRESHOLD, adjust_priority
from app.routing.rules import CATEGORY_AUTO_ROUTE_THRESHOLD, RoutingSignals, resolve_routing
from app.services.assignment_service import choose_agent
from app.services.category_taxonomy import (
    apply_display_taxonomy,
    disabled_categories,
    filter_disabled,
)
from app.services.routing_service import RoutingService
from app.services.sender_sentiment_service import summarize_sender

# --- FR-30 emotion -----------------------------------------------------


def test_anger_detected_from_cues_and_shouting():
    result = detect_emotions("This is UNACCEPTABLE and RIDICULOUS!! I am furious.", compound=-0.8)
    assert result.primary_emotion == "Anger"


def test_confusion_detected():
    result = detect_emotions("I'm confused, can you explain how does the billing work??")
    assert result.primary_emotion == "Confusion"


def test_satisfaction_suppressed_on_negative_text():
    """'thanks for nothing' must not read as Satisfaction."""
    result = detect_emotions("Thanks for nothing, still not fixed again", compound=-0.6)
    assert result.primary_emotion != "Satisfaction"


def test_neutral_text_has_no_primary_emotion():
    result = detect_emotions("Please find the attached quarterly report.", compound=0.0)
    assert result.primary_emotion is None
    assert result.ranked() == []


# --- FR-31 / FR-17 priority adjustment ----------------------------------


def test_very_negative_sentiment_raises_priority_up_to_critical():
    adj = adjust_priority("High", "Very Negative", is_spam=False)
    assert adj.adjusted_priority == "Critical"
    assert adj.changed and adj.reasons


def test_negative_sentiment_is_capped_at_high():
    assert adjust_priority("Medium", "Negative", is_spam=False).adjusted_priority == "High"
    assert adjust_priority("High", "Negative", is_spam=False).adjusted_priority == "High"


def test_spam_is_never_adjusted():
    assert adjust_priority("Low", "Very Negative", is_spam=True).adjusted_priority == "Low"


def test_sender_history_adds_one_level_capped_at_high():
    adj = adjust_priority("Low", "Neutral", is_spam=False, sender_negative_count=SENDER_NEGATIVE_HISTORY_THRESHOLD)
    assert adj.adjusted_priority == "Medium"
    below = adjust_priority("Low", "Neutral", is_spam=False, sender_negative_count=SENDER_NEGATIVE_HISTORY_THRESHOLD - 1)
    assert not below.changed


def test_unknown_priority_passes_through():
    assert adjust_priority(None, "Very Negative", is_spam=False).adjusted_priority is None


def test_routing_service_applies_priority_adjustment_from_precomputed_signals():
    result = RoutingService().route(
        "Order still missing",
        "This is the third time I am writing.",
        "customer@example.com",
        precomputed_spam={"is_spam": False, "spam_score": 0.01, "model_version": "t", "processing_ms": 1},
        precomputed_category={
            "categories": [{"category": "Support", "confidence": 0.9}],
            "all_scores": {"Support": 0.9, "Sales": 0.1},
            "model_version": "t",
            "processing_ms": 1,
        },
        precomputed_intent={"intents": [], "model_version": "t", "processing_ms": 1},
        precomputed_sentiment={"sentiment": "Negative", "model_version": "t", "processing_ms": 1},
        precomputed_priority={"priority": "Low", "model_version": "t", "processing_ms": 1},
        sender_negative_history=SENDER_NEGATIVE_HISTORY_THRESHOLD,
    )
    adj = result["priority_adjustment"]
    # Low -> Medium (sentiment) -> High (sender history).
    assert adj["model_priority"] == "Low"
    assert adj["adjusted_priority"] == "High"
    assert len(adj["reasons"]) == 2
    assert result["supporting_signals"]["priority"]["label"] == "High"
    assert result["supporting_signals"]["priority"]["model_label"] == "Low"


# --- FR-41 learned thresholds ------------------------------------------


def test_no_threshold_until_enough_samples():
    assert compute_department_thresholds({"Sales": DepartmentFeedback(reviewed=MIN_SAMPLES - 1, corrected=9)}) == {}


def test_high_correction_rate_raises_threshold_and_is_capped():
    thresholds = compute_department_thresholds({"Sales": DepartmentFeedback(reviewed=20, corrected=20)})
    assert CATEGORY_AUTO_ROUTE_THRESHOLD < thresholds["Sales"] <= THRESHOLD_CAP


def test_zero_corrections_relax_threshold_but_not_below_floor():
    thresholds = compute_department_thresholds({"IT": DepartmentFeedback(reviewed=50, corrected=0)})
    assert THRESHOLD_FLOOR <= thresholds["IT"] < CATEGORY_AUTO_ROUTE_THRESHOLD


def test_learned_threshold_changes_routing_decision_and_is_audited():
    signals = RoutingSignals(is_spam=False, category="Sales", category_confidence=0.6, category_second="Support",
                             category_second_confidence=0.1)
    assert resolve_routing(signals).action == "auto_route"
    decision = resolve_routing(signals, department_thresholds={"Sales": 0.7})
    assert decision.action == "human_review"
    assert "R-FEEDBACK-ADJUSTED-THRESHOLD" in decision.matched_rules


# --- FR-23 taxonomy ------------------------------------------------------

_CATEGORY_RESULT = {
    "categories": [{"category": "Marketing", "confidence": 0.8}],
    "all_scores": {"Marketing": 0.8, "Sales": 0.3, "General": 0.2},
    "model_version": "t",
    "processing_ms": 1,
}


def test_disabled_categories_never_include_general():
    assert disabled_categories({"General": {"enabled": False}, "Marketing": {"enabled": False}}) == frozenset({"Marketing"})


def test_filter_disabled_falls_back_to_general():
    filtered = filter_disabled(_CATEGORY_RESULT, frozenset({"Marketing"}))
    assert [c["category"] for c in filtered["categories"]] == ["General"]
    assert "Marketing" not in filtered["all_scores"]


def test_display_taxonomy_renames_but_keeps_model_label():
    shown = apply_display_taxonomy(_CATEGORY_RESULT, {"Marketing": {"display_name": "Brand & PR", "enabled": True}})
    assert shown["categories"][0] == {"category": "Brand & PR", "confidence": 0.8, "label": "Marketing"}
    assert "Brand & PR" in shown["all_scores"]


# --- FR-42 agent selection -----------------------------------------------


def _user(name, skills=(), last=None):
    return User(id=uuid.uuid4(), email=f"{name}@x.com", hashed_password="x", skills=list(skills), last_assigned_at=last)


def test_round_robin_picks_least_recently_assigned():
    now = datetime.now(UTC)
    a, b, c = _user("a", last=now), _user("b", last=None), _user("c", last=now - timedelta(hours=1))
    assert choose_agent([a, b, c], "round_robin", set()) is b


def test_skills_strategy_prefers_overlap_then_round_robin():
    now = datetime.now(UTC)
    generalist = _user("g", last=None)
    refunds_old = _user("r1", skills=["Refund"], last=now - timedelta(hours=2))
    refunds_new = _user("r2", skills=["refund"], last=now)
    assert choose_agent([generalist, refunds_old, refunds_new], "skills", {"Refund"}) is refunds_old


def test_skills_strategy_falls_back_when_nobody_matches():
    g = _user("g", last=None)
    assert choose_agent([g], "skills", {"Legal"}) is g


def test_strategy_none_assigns_nobody():
    assert choose_agent([_user("a")], "none", set()) is None


# --- FR-72 drift -----------------------------------------------------------


def test_psi_zero_for_identical_distributions():
    assert population_stability_index(Counter(a=50, b=50), Counter(a=50, b=50)) == 0.0


def test_significant_prediction_drift():
    drift = evaluate_module("priority", Counter(Low=90, High=10), Counter(Low=10, High=90))
    assert drift.prediction_status == STATUS_SIGNIFICANT and drift.alert


def test_insufficient_data_is_not_an_alert():
    drift = evaluate_module("priority", Counter(Low=3), Counter(High=3))
    assert drift.prediction_status == STATUS_INSUFFICIENT_DATA and not drift.alert


def test_correction_rate_rise_is_performance_drift():
    drift = evaluate_module(
        "spam", Counter(spam=50, ham=50), Counter(spam=50, ham=50),
        baseline_feedback=(100, 5), current_feedback=(100, 20),
    )
    assert drift.prediction_status == STATUS_STABLE
    assert drift.performance_drift and drift.alert


# --- FR-32 sender trends ----------------------------------------------------


def test_declining_sender_is_escalation_candidate():
    now = datetime.now(UTC)
    rows = [(now - timedelta(days=40), "Positive"), (now - timedelta(days=30), "Neutral")]
    rows += [(now - timedelta(days=d), "Very Negative") for d in (1, 2, 3)]
    summary = summarize_sender("a@b.com", rows, now)
    assert summary["trend"] == "declining"
    assert summary["escalation_candidate"]
    assert summary["negative_count"] == 3


def test_steady_positive_sender_is_not_flagged():
    now = datetime.now(UTC)
    summary = summarize_sender("a@b.com", [(now - timedelta(days=d), "Positive") for d in (1, 20, 40)], now)
    assert summary["trend"] == "stable" and not summary["escalation_candidate"]


# --- SS6.5 explanations -------------------------------------------------------

_TEXTS = ["free prize click now", "win free money", "meeting notes attached", "project status update"] * 5
_LABELS = [1, 1, 0, 0] * 5


class _SpamLikePipeline:
    """Shape of MLPipeline: `.pipeline` is an sklearn Pipeline(tfidf, classifier)."""

    def __init__(self):
        self.pipeline = Pipeline(
            [("tfidf", TfidfVectorizer()), ("classifier", CalibratedClassifierCV(LogisticRegression(), cv=2))]
        ).fit(_TEXTS, _LABELS)


class _SpamLikePredictor:
    def __init__(self):
        self.pipeline = _SpamLikePipeline()


def test_binary_explanation_points_toward_the_target_class():
    pipeline = _SpamLikePipeline()
    spam_words = {e["feature"]: e for e in explain_linear(pipeline, "free prize meeting", 1)}
    assert spam_words["word:free"]["effect"] == "supports"
    assert spam_words["word:meeting"]["effect"] == "opposes"
    ham_view = {e["feature"]: e for e in explain_linear(pipeline, "free prize meeting", 0)}
    assert ham_view["word:free"]["effect"] == "opposes"


def test_string_label_matches_integer_classes():
    """Regression: "1" vs np.int64(1) once flipped every sign."""
    explanation = explain_prediction(_SpamLikePredictor(), "free prize", "1")
    assert explanation["by_label"]["1"][0]["effect"] == "supports"


class _MultiLabelPipeline:
    """Shape of IntentMLPipeline: _vectorize + OneVsRest classifier + mlb."""

    def __init__(self):
        self.tfidf = TfidfVectorizer().fit(_TEXTS)
        self.mlb = MultiLabelBinarizer().fit([["Refund"], ["Inquiry"]])
        y = self.mlb.transform([["Refund"] if lbl else ["Inquiry"] for lbl in _LABELS])
        self.classifier = OneVsRestClassifier(CalibratedClassifierCV(LogisticRegression(), cv=2)).fit(
            self.tfidf.transform(_TEXTS), y
        )
        self.classes_ = self.mlb.classes_

    def _vectorize(self, texts, fit=False):
        return self.tfidf.transform(texts)


def test_one_vs_rest_explanation_per_label():
    explanation = explain_linear(_MultiLabelPipeline(), "win free money", "Refund", top_k=3)
    assert explanation and all(e["feature"].startswith("word:") for e in explanation)
    assert explanation[0]["effect"] == "supports"


def test_explain_prediction_returns_none_for_non_linear_predictors():
    assert explain_prediction(object(), "text", "x") is None


# --- FR-61 feedback rows -----------------------------------------------------


def test_feedback_rows_dedupe_validate_and_require_opt_in(tmp_path, monkeypatch):
    lines = [
        {"subject": "s", "body": "first", "corrected_label": "Low", "created_at": "2026-01-01T00:00:00+00:00"},
        {"subject": "s", "body": "first", "corrected_label": "High", "created_at": "2026-01-02T00:00:00+00:00"},
        {"subject": "s2", "body": "bad label", "corrected_label": "Urgentish"},
        {"subject": "s3", "body": "", "corrected_label": "Low"},
    ]
    (tmp_path / "priority_feedback.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")

    corrections = feedback_training_data.load_feedback_corrections("priority", tmp_path)
    assert [(c["body"], c["label"]) for c in corrections] == [("first", "High")]

    import pandas as pd

    base = pd.DataFrame([{"subject_raw": "x", "body_text_raw": "y", "priority_label": "Low"}])
    monkeypatch.delenv(feedback_training_data.INCLUDE_FEEDBACK_ENV, raising=False)
    assert feedback_training_data.augment_training_frame(base, "priority", tmp_path)[1] == 0
    monkeypatch.setenv(feedback_training_data.INCLUDE_FEEDBACK_ENV, "1")
    augmented, added = feedback_training_data.augment_training_frame(base, "priority", tmp_path)
    assert added == 1 and len(augmented) == 2


def test_multilabel_feedback_filters_unknown_labels(tmp_path):
    (tmp_path / "category_feedback.jsonl").write_text(
        json.dumps({"subject": "", "body": "b", "corrected_label": ["Billing", "Nonsense"]}), encoding="utf-8"
    )
    assert feedback_training_data.load_feedback_corrections("category", tmp_path)[0]["label"] == ["Billing"]


# --- SS13.1 rate limiting ---------------------------------------------------


def _scope(path="/api/v1/spam/predict", ip="10.0.0.1"):
    return {"type": "http", "path": path, "headers": [], "client": (ip, 1234)}


async def _call(middleware, scope):
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_rate_limit_rejects_after_limit_with_problem_details():
    middleware = RateLimitMiddleware(_ok_app, limit_per_minute=2)
    assert (await _call(middleware, _scope()))[0]["status"] == 200
    assert (await _call(middleware, _scope()))[0]["status"] == 200
    rejected = await _call(middleware, _scope())
    assert rejected[0]["status"] == 429
    assert json.loads(rejected[1]["body"])["status"] == 429
    # Separate caller, separate bucket.
    assert (await _call(middleware, _scope(ip="10.0.0.2")))[0]["status"] == 200


async def test_health_probes_are_never_limited():
    middleware = RateLimitMiddleware(_ok_app, limit_per_minute=1)
    for _ in range(3):
        assert (await _call(middleware, _scope(path="/api/v1/health")))[0]["status"] == 200
