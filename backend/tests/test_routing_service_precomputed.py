"""
Regression tests for RoutingService's Phase 12 addition: `precomputed_*`
kwargs on `route()`, which let the Orchestrator (app/agents/orchestrator.py)
reuse this class's existing rule/composition logic with results the Kafka
agents already produced, WITHOUT re-running the five ML calls a second
time. Existing callers (the pre-Phase-12 `/routing/predict` endpoint, and
every test in test_routing_service.py) pass none of these and are
unaffected -- verified by that whole file still passing unchanged.
"""

from app.services.routing_service import RoutingService


class _FakeService:
    def __init__(self, method_name, result):
        self.calls = 0
        self._result = result
        setattr(self, method_name, self._call)

    def _call(self, *args, **kwargs):
        self.calls += 1
        return self._result


def _spam(is_spam=False):
    return {
        "is_spam": is_spam,
        "status": "quarantined" if is_spam else "clear",
        "confidence": 0.9 if is_spam else 0.02,
        "spam_score": 0.9 if is_spam else 0.02,
        "threshold_used": 0.06,
        "model_version": "svm-test",
        "processing_ms": 1.0,
    }


def _category(top="Support", top_conf=0.85):
    all_scores = dict.fromkeys(["Support", "Sales", "Billing"], 0.02)
    all_scores[top] = top_conf
    return {
        "categories": [{"category": top, "confidence": top_conf}],
        "all_scores": all_scores,
        "model_version": "svm-category-test",
        "processing_ms": 1.0,
    }


def _intent():
    return {
        "intents": [],
        "all_scores": {},
        "entities": {},
        "model_version": "logreg-intent-test",
        "processing_ms": 1.0,
    }


def _sentiment(label="Neutral"):
    return {"sentiment": label, "confidence": 0.7, "probabilities": {}, "model_version": "vader-test", "processing_ms": 0.5}


def _priority(label="Medium"):
    return {"priority": label, "confidence": 0.6, "probabilities": {}, "model_version": "logreg-priority-test", "processing_ms": 1.0}


def _make_service():
    """Every underlying service is a fake that would fail the test loudly
    (via .calls tracking) if RoutingService ever fell back to calling it --
    the point of these tests is that precomputed results are used AS-IS."""
    return RoutingService(
        spam_service=_FakeService("classify", _spam()),
        category_service=_FakeService("classify", _category()),
        intent_service=_FakeService("analyze", _intent()),
        sentiment_service=_FakeService("analyze", _sentiment()),
        priority_service=_FakeService("classify", _priority()),
    )


def test_precomputed_results_are_used_without_calling_the_underlying_services():
    service = _make_service()
    result = service.route(
        subject="Bug report",
        body="Something is broken",
        precomputed_spam=_spam(is_spam=False),
        precomputed_category=_category(top="Billing", top_conf=0.9),
        precomputed_intent=_intent(),
        precomputed_sentiment=_sentiment(),
        precomputed_priority=_priority(),
    )

    assert service._spam_service.calls == 0
    assert service._category_service.calls == 0
    assert service._intent_service.calls == 0
    assert service._sentiment_service.calls == 0
    assert service._priority_service.calls == 0
    assert result["department"] == "Billing"
    assert result["upstream_failures"] == []


def test_precomputed_none_is_recorded_as_unavailable_not_fetched():
    service = _make_service()
    result = service.route(
        subject="Bug report",
        body="Something is broken",
        precomputed_spam=_spam(is_spam=False),
        precomputed_category=None,  # agent failed/didn't report -- Orchestrator's explicit signal
        precomputed_intent=_intent(),
        precomputed_sentiment=_sentiment(),
        precomputed_priority=_priority(),
    )

    assert service._category_service.calls == 0  # never fetched, not even attempted
    assert "category" in result["upstream_failures"]


def test_spam_gate_still_applies_when_spam_result_is_precomputed():
    service = _make_service()
    result = service.route(
        subject="WIN A PRIZE",
        body="Click now",
        precomputed_spam=_spam(is_spam=True),
        # category/intent/sentiment/priority deliberately left unset
        # (_NOT_PROVIDED) -- the gate must prevent them from EVER being
        # fetched, precomputed or not.
    )

    assert result["action"] == "quarantine"
    assert service._category_service.calls == 0
    assert service._intent_service.calls == 0
    assert service._sentiment_service.calls == 0
    assert service._priority_service.calls == 0


def test_mixing_precomputed_and_normal_fetch_is_allowed():
    """The Orchestrator always supplies all five; this test documents that
    a PARTIAL supply (e.g. a future caller) still falls back correctly for
    whatever it omits, since `route()` treats each signal independently."""
    service = _make_service()
    result = service.route(
        subject="Bug report",
        body="Something is broken",
        precomputed_spam=_spam(is_spam=False),
        # category/intent/sentiment/priority NOT supplied -> fetched normally
    )

    assert service._category_service.calls == 1
    assert service._intent_service.calls == 1
    assert service._sentiment_service.calls == 1
    assert service._priority_service.calls == 1
    assert result["department"] == "Support"
