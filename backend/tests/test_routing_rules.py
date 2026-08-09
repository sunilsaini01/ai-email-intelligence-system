"""
Unit tests for the pure routing rule engine (Module 8 / Phase 8).

Deliberately constructs RoutingSignals directly -- no service, no HTTP, no
DB -- so precedence, tie-breaking, and the unreliable-Intent policy are
tested in isolation from the five upstream ML services, per the Phase 8
brief's explicit ask for unit tests of "individual routing rules... tie-
breaking... unreliable Intent handling."
"""

from app.routing.rules import (
    ACTION_AUTO_ROUTE,
    ACTION_FALLBACK,
    ACTION_HUMAN_REVIEW,
    ACTION_QUARANTINE,
    RULE_REGISTRY,
    RoutingSignals,
    resolve_routing,
)


def test_spam_gate_quarantines_and_ignores_every_other_signal():
    signals = RoutingSignals(
        is_spam=True,
        spam_confidence=0.97,
        category="Billing",
        category_confidence=0.99,
        intents=("Refund", "Escalation"),
        priority="Critical",
        sentiment="Very Negative",
    )
    decision = resolve_routing(signals)

    assert decision.action == ACTION_QUARANTINE
    assert decision.department is None
    assert decision.requires_human_review is False
    assert decision.matched_rules == ("R-SPAM-GATE",)
    assert decision.confidence == 0.97


def test_high_confidence_category_auto_routes_a_non_high_impact_department():
    signals = RoutingSignals(
        is_spam=False,
        category="Support",
        category_confidence=0.80,
        category_second="IT",
        category_second_confidence=0.15,
    )
    decision = resolve_routing(signals)

    assert decision.action == ACTION_AUTO_ROUTE
    assert decision.department == "Support"
    assert decision.confidence == 0.80
    assert decision.requires_human_review is False
    assert "R-CATEGORY-AUTO-ROUTE" in decision.matched_rules


def test_low_confidence_category_routes_to_human_review_as_a_candidate():
    signals = RoutingSignals(
        is_spam=False, category="IT", category_confidence=0.40, category_second_confidence=0.10
    )
    decision = resolve_routing(signals)

    assert decision.action == ACTION_HUMAN_REVIEW
    assert decision.department == "IT"  # surfaced as a candidate, not discarded
    assert decision.requires_human_review is True
    assert "R-CATEGORY-LOW-CONFIDENCE" in decision.matched_rules


def test_tied_top_two_categories_trigger_human_review():
    signals = RoutingSignals(
        is_spam=False,
        category="Sales",
        category_confidence=0.60,
        category_second="Marketing",
        category_second_confidence=0.58,  # margin 0.02 < CATEGORY_TIE_MARGIN (0.05)
    )
    decision = resolve_routing(signals)

    assert decision.action == ACTION_HUMAN_REVIEW
    assert "R-CATEGORY-TIE" in decision.matched_rules


def test_category_unavailable_with_clear_keyword_winner_falls_back_but_never_auto_routes():
    signals = RoutingSignals(
        is_spam=False,
        category=None,
        category_confidence=None,
        keyword_top="Billing",
        keyword_votes={"Billing": 3, "IT": 1},
        unavailable_signals=("category",),
    )
    decision = resolve_routing(signals)

    assert decision.department == "Billing"
    assert decision.action == ACTION_HUMAN_REVIEW  # never AUTO_ROUTE on keywords alone
    assert decision.confidence == 3 / 4
    assert "R-CATEGORY-UNAVAILABLE-KEYWORD-FALLBACK" in decision.matched_rules


def test_category_unavailable_with_insufficient_keyword_votes_falls_to_general():
    signals = RoutingSignals(
        is_spam=False,
        category=None,
        keyword_top="Sales",
        keyword_votes={"Sales": 1},  # below KEYWORD_FALLBACK_MIN_VOTES (2)
        unavailable_signals=("category",),
    )
    decision = resolve_routing(signals)

    assert decision.department == "General"
    assert decision.action == ACTION_FALLBACK
    assert decision.confidence == 0.0
    assert decision.requires_human_review is True
    assert "R-NO-EVIDENCE-FALLBACK" in decision.matched_rules


def test_no_category_and_no_keyword_evidence_never_drops_the_email():
    signals = RoutingSignals(is_spam=False)
    decision = resolve_routing(signals)

    assert decision.department == "General"
    assert decision.action == ACTION_FALLBACK
    assert decision.requires_human_review is True


def test_high_impact_department_requires_review_even_at_high_confidence():
    signals = RoutingSignals(
        is_spam=False,
        category="HR",
        category_confidence=0.95,
        category_second_confidence=0.02,
    )
    decision = resolve_routing(signals)

    assert decision.action == ACTION_AUTO_ROUTE  # still the routing suggestion
    assert decision.department == "HR"
    assert decision.requires_human_review is True  # but mandatory review
    assert "R-HIGH-IMPACT-DEPARTMENT-REVIEW" in decision.matched_rules


def test_high_impact_rule_is_recorded_even_when_review_already_required_by_another_rule():
    """Regression test for Fix #5: R-HIGH-IMPACT-DEPARTMENT-REVIEW must
    appear in matched_rules whenever the department is HIGH_IMPACT, even if
    a DIFFERENT rule (here, R-CATEGORY-LOW-CONFIDENCE) already set
    requires_human_review=True first. Pre-fix, the `and not requires_review`
    guard suppressed this rule from ever being recorded in exactly this
    scenario, under-reporting the audit trail."""
    signals = RoutingSignals(
        is_spam=False,
        category="HR",
        category_confidence=0.30,  # below auto-route threshold -> low-confidence fires first
        category_second_confidence=0.10,
    )
    decision = resolve_routing(signals)

    assert decision.requires_human_review is True
    assert "R-CATEGORY-LOW-CONFIDENCE" in decision.matched_rules
    assert "R-HIGH-IMPACT-DEPARTMENT-REVIEW" in decision.matched_rules  # would have been absent pre-fix


def test_external_sender_with_high_impact_department_adds_review_rule():
    signals = RoutingSignals(
        is_spam=False,
        category="Billing",
        category_confidence=0.90,
        category_second_confidence=0.02,
        sender_domain_type="external",
    )
    decision = resolve_routing(signals)

    assert decision.department == "Billing"
    assert decision.requires_human_review is True
    assert "R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW" in decision.matched_rules
    assert "external sender" in decision.reason.lower()


def test_internal_sender_does_not_trigger_external_sender_rule():
    signals = RoutingSignals(
        is_spam=False,
        category="Billing",
        category_confidence=0.90,
        category_second_confidence=0.02,
        sender_domain_type="internal",
    )
    decision = resolve_routing(signals)

    assert "R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW" not in decision.matched_rules
    # Billing is still HIGH_IMPACT regardless of sender domain -- review is
    # still required, just not attributed to the sender-domain rule.
    assert decision.requires_human_review is True


def test_external_sender_does_not_independently_select_a_department():
    # Support is not HIGH_IMPACT -- external sender must have NO effect here,
    # since most legitimate Support senders are external by nature.
    signals = RoutingSignals(
        is_spam=False,
        category="Support",
        category_confidence=0.90,
        category_second_confidence=0.02,
        sender_domain_type="external",
    )
    decision = resolve_routing(signals)

    assert decision.department == "Support"
    assert decision.requires_human_review is False
    assert "R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW" not in decision.matched_rules


def test_sender_domain_has_no_effect_when_department_is_not_high_impact():
    """Existing routing behavior is unchanged by sender domain whenever the
    department isn't HIGH_IMPACT -- 'unknown' and 'external' must produce
    identical decisions for a non-HIGH_IMPACT department."""
    base_kwargs = dict(
        is_spam=False, category="IT", category_confidence=0.90, category_second_confidence=0.02
    )
    d_unknown = resolve_routing(RoutingSignals(**base_kwargs, sender_domain_type="unknown"))
    d_external = resolve_routing(RoutingSignals(**base_kwargs, sender_domain_type="external"))

    assert d_unknown.department == d_external.department == "IT"
    assert d_unknown.requires_human_review == d_external.requires_human_review is False
    assert d_unknown.matched_rules == d_external.matched_rules


def test_uncorroborated_escalation_intent_has_no_effect():
    signals = RoutingSignals(
        is_spam=False,
        category="Support",
        category_confidence=0.90,
        category_second_confidence=0.02,
        intents=("Escalation",),
        priority=None,
        sentiment=None,
    )
    decision = resolve_routing(signals)

    assert decision.requires_human_review is False
    assert "R-ESCALATION-CORROBORATED" not in decision.matched_rules


def test_escalation_corroborated_by_critical_priority_flags_review():
    signals = RoutingSignals(
        is_spam=False,
        category="Support",
        category_confidence=0.90,
        category_second_confidence=0.02,
        intents=("Escalation",),
        priority="Critical",
    )
    decision = resolve_routing(signals)

    assert decision.department == "Support"  # Escalation never changes the department
    assert decision.requires_human_review is True
    assert "R-ESCALATION-CORROBORATED" in decision.matched_rules


def test_escalation_corroborated_by_negative_sentiment_flags_review():
    signals = RoutingSignals(
        is_spam=False,
        category="Support",
        category_confidence=0.90,
        category_second_confidence=0.02,
        intents=("Escalation",),
        sentiment="Very Negative",
    )
    decision = resolve_routing(signals)

    assert decision.requires_human_review is True
    assert "R-ESCALATION-CORROBORATED" in decision.matched_rules


def test_refund_intent_mismatch_flags_review_without_changing_department():
    signals = RoutingSignals(
        is_spam=False,
        category="Support",
        category_confidence=0.90,
        category_second_confidence=0.02,
        intents=("Refund",),
    )
    decision = resolve_routing(signals)

    assert decision.department == "Support"  # Refund never redirects the department alone
    assert decision.requires_human_review is True
    assert "R-REFUND-CATEGORY-MISMATCH" in decision.matched_rules


def test_refund_intent_corroborates_billing():
    signals = RoutingSignals(
        is_spam=False,
        category="Billing",
        category_confidence=0.90,
        category_second_confidence=0.02,
        intents=("Refund",),
    )
    decision = resolve_routing(signals)

    assert decision.department == "Billing"
    assert "R-REFUND-BILLING-CORROBORATED" in decision.matched_rules
    assert "R-REFUND-CATEGORY-MISMATCH" not in decision.matched_rules


def test_critical_priority_below_confidence_floor_downgrades_to_review():
    signals = RoutingSignals(
        is_spam=False,
        category="IT",
        category_confidence=0.60,  # >= auto-route threshold (0.55) but < critical floor (0.75)
        category_second_confidence=0.05,
        priority="Critical",
    )
    decision = resolve_routing(signals)

    assert decision.action == ACTION_AUTO_ROUTE  # still the suggestion
    assert decision.requires_human_review is True  # but flagged
    assert "R-CRITICAL-PRIORITY-CONFIDENCE-CHECK" in decision.matched_rules


def test_critical_priority_above_confidence_floor_does_not_require_extra_review():
    signals = RoutingSignals(
        is_spam=False,
        category="IT",
        category_confidence=0.90,
        category_second_confidence=0.02,
        priority="Critical",
    )
    decision = resolve_routing(signals)

    assert decision.requires_human_review is False
    assert "R-CRITICAL-PRIORITY-CONFIDENCE-CHECK" not in decision.matched_rules


def test_borderline_confidence_with_negative_sentiment_flags_review():
    signals = RoutingSignals(
        is_spam=False,
        category="Marketing",
        category_confidence=0.60,  # within BORDERLINE_SENTIMENT_MARGIN of the 0.55 threshold
        category_second_confidence=0.05,
        sentiment="Negative",
    )
    decision = resolve_routing(signals)

    assert decision.requires_human_review is True
    assert "R-BORDERLINE-CONFIDENCE-NEGATIVE-SENTIMENT" in decision.matched_rules


def test_negative_sentiment_well_above_threshold_has_no_borderline_effect():
    signals = RoutingSignals(
        is_spam=False,
        category="Marketing",
        category_confidence=0.95,
        category_second_confidence=0.02,
        sentiment="Very Negative",
    )
    decision = resolve_routing(signals)

    assert decision.requires_human_review is False
    assert "R-BORDERLINE-CONFIDENCE-NEGATIVE-SENTIMENT" not in decision.matched_rules


def test_every_matched_rule_id_is_registered():
    scenarios = [
        RoutingSignals(is_spam=True, spam_confidence=0.9),
        RoutingSignals(is_spam=False, category="HR", category_confidence=0.95, category_second_confidence=0.01, intents=("Escalation", "Refund"), priority="Critical", sentiment="Very Negative"),
        RoutingSignals(is_spam=False, category=None, keyword_top="Billing", keyword_votes={"Billing": 5}),
        RoutingSignals(is_spam=False),
    ]
    for signals in scenarios:
        decision = resolve_routing(signals)
        for rule_id in decision.matched_rules:
            assert rule_id in RULE_REGISTRY, f"{rule_id} fired but is not documented in RULE_REGISTRY"


def test_action_is_never_department_none_unless_quarantine():
    scenarios = [
        RoutingSignals(is_spam=False, category="Support", category_confidence=0.9, category_second_confidence=0.02),
        RoutingSignals(is_spam=False, category="IT", category_confidence=0.3, category_second_confidence=0.1),
        RoutingSignals(is_spam=False),
    ]
    for signals in scenarios:
        decision = resolve_routing(signals)
        if decision.action != ACTION_QUARANTINE:
            assert decision.department is not None
