"""
Unit tests for RoutingService (Module 8 / Phase 8), mirroring
test_intent_service.py's fake-backend style -- fakes here duck-type the
upstream SERVICES (SpamService.classify, CategoryService.classify, etc.),
not their Predictors, since RoutingService composes services, not raw
inference.
"""

from app.services.routing_service import RoutingService, get_routing_service


def _spam(is_spam=False, confidence=0.02, spam_score=None):
    # `spam_score` defaults to `confidence` for existing callers that don't
    # care about the distinction -- but the two are genuinely DIFFERENT
    # fields on the real SpamService response (confidence = argmax-label
    # confidence, spam_score = spam-class probability), and Fix #1's
    # regression test below constructs them as deliberately different values.
    if spam_score is None:
        spam_score = confidence
    return {
        "is_spam": is_spam,
        "status": "quarantined" if is_spam else "clear",
        "confidence": confidence,
        "spam_score": spam_score,
        "threshold_used": 0.06,
        "model_version": "svm-test",
        "processing_ms": 1.0,
    }


def _category(top="Support", top_conf=0.8, all_scores=None):
    if all_scores is None:
        # `top`'s score must actually be the highest -- hardcoding "Support"
        # here regardless of `top` was a real bug (found via
        # test_routing_prediction_log.py failing with department=="Support"
        # for a fake explicitly configured with top="Billing").
        all_scores = dict.fromkeys(
            ["Support", "Sales", "Billing", "Legal", "HR", "IT", "Marketing", "General"], 0.02
        )
        all_scores[top] = top_conf
    return {
        "categories": [{"category": top, "confidence": top_conf}],
        "all_scores": all_scores,
        "model_version": "svm-category-test",
        "processing_ms": 1.0,
    }


def _intent(intents=()):
    return {
        "intents": [{"intent": i, "confidence": 0.8} for i in intents],
        "all_scores": {},
        "entities": {"order_ids": [], "dates": [], "monetary_amounts": [], "person_names": [], "product_names": []},
        "model_version": "logreg-intent-test",
        "processing_ms": 1.0,
    }


def _sentiment(label="Neutral"):
    return {
        "sentiment": label,
        "confidence": 0.7,
        "probabilities": {},
        "model_version": "vader-test",
        "processing_ms": 0.5,
    }


def _priority(label="Medium"):
    return {
        "priority": label,
        "confidence": 0.6,
        "probabilities": {},
        "model_version": "logreg-priority-test",
        "processing_ms": 1.0,
    }


class _FakeService:
    """Generic duck-typed fake -- constructed with the method name it must
    expose (classify/analyze) and either a fixed return value or a callable
    that raises, so failure-isolation tests don't need a second fake class."""

    def __init__(self, method_name, result_or_raiser):
        self.calls = 0
        self._result_or_raiser = result_or_raiser
        setattr(self, method_name, self._call)

    def _call(self, *args, **kwargs):
        self.calls += 1
        if callable(self._result_or_raiser) and not isinstance(self._result_or_raiser, dict):
            return self._result_or_raiser()
        return self._result_or_raiser


def _make_routing_service(
    spam=None, category=None, intent=None, sentiment=None, priority=None
):
    return RoutingService(
        spam_service=_FakeService("classify", spam or _spam()),
        category_service=_FakeService("classify", category or _category()),
        intent_service=_FakeService("analyze", intent or _intent()),
        sentiment_service=_FakeService("analyze", sentiment or _sentiment()),
        priority_service=_FakeService("classify", priority or _priority()),
    )


def test_route_auto_routes_a_non_high_impact_department():
    service = _make_routing_service(category=_category(top="Support", top_conf=0.85))
    result = service.route(subject="Bug", body="Something is broken and not working.")

    assert result["department"] == "Support"
    assert result["action"] == "auto_route"
    assert result["requires_human_review"] is False
    assert result["upstream_failures"] == []
    assert result["supporting_signals"]["sentiment"]["reliability"] == "unvalidated"
    assert result["supporting_signals"]["category"]["reliability"] == "provisional_synthetic"
    assert result["supporting_signals"]["spam"]["reliability"] == "validated"


def test_route_quarantines_spam_and_skips_the_other_four_services():
    spam_fake = _FakeService("classify", _spam(is_spam=True, confidence=0.95))
    category_fake = _FakeService("classify", _category())
    intent_fake = _FakeService("analyze", _intent())
    sentiment_fake = _FakeService("analyze", _sentiment())
    priority_fake = _FakeService("classify", _priority())

    service = RoutingService(
        spam_service=spam_fake,
        category_service=category_fake,
        intent_service=intent_fake,
        sentiment_service=sentiment_fake,
        priority_service=priority_fake,
    )
    result = service.route(subject="WIN A FREE PRIZE", body="Click now!!!")

    assert result["action"] == "quarantine"
    assert result["department"] is None
    assert category_fake.calls == 0
    assert intent_fake.calls == 0
    assert sentiment_fake.calls == 0
    assert priority_fake.calls == 0


def test_route_quarantine_confidence_uses_spam_score_not_argmax_confidence():
    """Regression test for the Phase 8 engineering review's Critical Finding
    #1: SpamService's `confidence` field is the argmax-label confidence --
    often the HAM-label confidence, since the real 0.06 threshold routinely
    classifies is_spam=True while the argmax label is still "ham" (e.g. a
    real spam_score of 0.1859 pairs with a real confidence of 0.8141, per
    the review's live verification). Routing must report `spam_score` (the
    actual spam-class probability that drove the decision), never
    `confidence`. This test fails against the pre-fix implementation
    (which used `confidence` and would assert 0.82 == 0.18)."""
    service = _make_routing_service(spam=_spam(is_spam=True, confidence=0.82, spam_score=0.18))
    result = service.route(subject="Pricing", body="Can you send me a quote?")

    assert result["action"] == "quarantine"
    assert result["confidence"] == 0.18
    assert result["confidence"] != 0.82
    assert result["supporting_signals"]["spam"]["confidence"] == 0.18


def test_route_isolates_a_failing_category_service_without_crashing():
    def _raise():
        raise RuntimeError("artifact missing")

    service = _make_routing_service(category=_raise)
    result = service.route(subject="Refund please", body="invoice invoice charge please refund me")

    assert "category" in result["upstream_failures"]
    # No crash, and never department-less unless quarantine (RULE 10).
    assert result["department"] is not None


def test_route_never_raises_even_when_every_upstream_service_fails():
    def _raise():
        raise RuntimeError("boom")

    service = _make_routing_service(
        spam=_raise, category=_raise, intent=_raise, sentiment=_raise, priority=_raise
    )
    result = service.route(subject="", body="")

    assert set(result["upstream_failures"]) == {"spam", "category", "intent", "sentiment", "priority"}
    assert result["department"] == "General"
    assert result["action"] == "fallback"
    assert result["requires_human_review"] is True


def test_route_isolates_a_failing_keyword_matcher(monkeypatch):
    """Regression test for Fix #4: RoutingService's OWN keyword-matching call
    (not an upstream service) must degrade the same safe way as the five
    services -- recorded in upstream_failures, never a crashed request."""
    import app.services.routing_service as routing_service_module

    def _raise(text):
        raise RuntimeError("keyword matcher exploded")

    monkeypatch.setattr(routing_service_module, "top_department_by_keywords", _raise)

    service = _make_routing_service()
    result = service.route(subject="Test", body="Some ordinary content")

    assert "keywords" in result["upstream_failures"]
    assert result["department"] is not None  # never crashes, still returns a decision


def test_route_isolates_a_failing_sender_domain_classifier(monkeypatch):
    """Regression test for Fix #4: sender-domain classification is
    RoutingService's own code, not an upstream service -- must still degrade
    to a safe default ("unknown") rather than crashing the request."""
    import app.services.routing_service as routing_service_module

    def _raise(sender_email):
        raise RuntimeError("sender domain classifier exploded")

    monkeypatch.setattr(routing_service_module, "classify_sender_domain", _raise)

    service = _make_routing_service()
    result = service.route(subject="Test", body="Some ordinary content", sender_email="a@b.com")

    assert "sender_domain" in result["upstream_failures"]
    assert result["supporting_signals"]["sender_domain"]["type"] == "unknown"
    assert result["department"] is not None


def test_route_intent_unavailable_does_not_synthesize_escalation_behavior():
    """Regression test for Fix #6: if Intent is unavailable, intents=() must
    NOT be treated as though Escalation could still fire just because
    Priority/Sentiment happen to look corroborating -- the Escalation/Refund
    safety policy only ever activates from an ACTUAL Intent='Escalation'
    label, never inferred from other signals alone. Routing must remain
    deterministic and other valid signals must still behave per the existing
    rules (Critical priority at high confidence does not itself force
    review)."""

    def _raise():
        raise RuntimeError("intent artifact missing")

    service = _make_routing_service(
        intent=_raise,
        priority=_priority(label="Critical"),
        sentiment=_sentiment(label="Very Negative"),
        category=_category(top="Support", top_conf=0.9),
    )
    result = service.route(subject="Help", body="This is urgent, please help.")

    assert "intent" in result["upstream_failures"]
    assert "R-ESCALATION-CORROBORATED" not in result["matched_rules"]
    assert result["department"] == "Support"  # unaffected, still routed normally
    assert result["action"] == "auto_route"
    assert result["requires_human_review"] is False


def test_route_model_versions_are_none_for_unavailable_signals():
    def _raise():
        raise RuntimeError("boom")

    service = _make_routing_service(intent=_raise)
    result = service.route(subject="Hi", body="just checking in")

    assert result["model_versions"]["intent"] is None
    assert result["model_versions"]["spam"] is not None


def test_route_includes_routing_and_keyword_matcher_versions():
    service = _make_routing_service()
    result = service.route(subject="Hi", body="just checking in")

    assert result["routing_rules_version"] == "routing_rules_v1"
    assert result["keyword_matcher_version"] == "routing_keywords_v1"


def test_get_routing_service_returns_a_singleton():
    get_routing_service.cache_clear()
    try:
        a = get_routing_service()
        b = get_routing_service()
        assert a is b
    finally:
        get_routing_service.cache_clear()
