"""
Unit tests for app/routing/overrides.py (Phase 21) -- pure, DB-free, same
"signals in, decision out" testability as test_routing_rules.py already
established for the base engine.
"""

from app.routing.overrides import OverrideCondition, OverrideRule, apply_overrides

BASE_DECISION = {
    "department": "Support",
    "action": "auto_route",
    "confidence": 0.8,
    "requires_human_review": False,
    "reason": "Category 'Support' auto-routed.",
    "matched_rules": ["R-CATEGORY-AUTO-ROUTE"],
    "supporting_signals": {
        "spam": {"is_spam": False, "confidence": 0.01},
        "category": {"top": "Support", "confidence": 0.8},
        "intent": {"labels": ["Inquiry"]},
        "sentiment": {"label": "Neutral"},
        "priority": {"label": "Medium"},
        "sender_domain": {"type": "external"},
    },
}


def _rule(**kwargs) -> OverrideRule:
    defaults = dict(
        id="r1",
        name="test rule",
        conditions=(),
        override_department=None,
        override_action=None,
        override_requires_human_review=None,
    )
    defaults.update(kwargs)
    return OverrideRule(**defaults)


def test_no_overrides_returns_the_original_decision_unchanged():
    result = apply_overrides(BASE_DECISION, "subject", "body", "a@b.com", [])
    assert result is BASE_DECISION


def test_no_matching_override_returns_the_original_decision_unchanged():
    rule = _rule(conditions=(OverrideCondition("category", "eq", "Billing"),), override_department="Billing")
    result = apply_overrides(BASE_DECISION, "subject", "body", "a@b.com", [rule])
    assert result == BASE_DECISION


def test_matching_override_changes_department_and_appends_a_matched_rule():
    rule = _rule(
        id="abc123",
        name="Route Support to Sales",
        conditions=(OverrideCondition("category", "eq", "Support"),),
        override_department="Sales",
    )
    result = apply_overrides(BASE_DECISION, "subject", "body", "a@b.com", [rule])

    assert result["department"] == "Sales"
    assert "OVERRIDE:abc123:Route Support to Sales" in result["matched_rules"]
    assert "Route Support to Sales" in result["reason"]
    # Original untouched -- apply_overrides must never mutate its input.
    assert BASE_DECISION["department"] == "Support"


def test_override_can_set_action_and_requires_human_review_independently():
    rule = _rule(
        conditions=(OverrideCondition("sender_domain_type", "eq", "external"),),
        override_action="human_review",
        override_requires_human_review=True,
    )
    result = apply_overrides(BASE_DECISION, "subject", "body", "a@b.com", [rule])

    assert result["action"] == "human_review"
    assert result["requires_human_review"] is True
    assert result["department"] == "Support"  # unset field left alone


def test_first_matching_override_wins_by_priority_order():
    """The repository is what guarantees ascending priority_order; this
    function just trusts the order it's given and applies the FIRST
    match."""
    first = _rule(id="p1", name="first", conditions=(OverrideCondition("category", "eq", "Support"),), override_department="Sales")
    second = _rule(id="p2", name="second", conditions=(OverrideCondition("category", "eq", "Support"),), override_department="Billing")

    result = apply_overrides(BASE_DECISION, "subject", "body", "a@b.com", [first, second])

    assert result["department"] == "Sales"
    assert "OVERRIDE:p2:second" not in result["matched_rules"]


def test_multiple_conditions_are_anded_together():
    rule = _rule(
        conditions=(
            OverrideCondition("category", "eq", "Support"),
            OverrideCondition("priority", "eq", "Critical"),  # BASE_DECISION's priority is "Medium"
        ),
        override_department="Billing",
    )
    result = apply_overrides(BASE_DECISION, "subject", "body", "a@b.com", [rule])
    assert result["department"] == "Support"  # not matched -- priority condition failed


def test_in_operator_matches_any_value_in_the_list():
    rule = _rule(conditions=(OverrideCondition("category", "in", ["Billing", "Support"]),), override_department="IT")
    result = apply_overrides(BASE_DECISION, "subject", "body", "a@b.com", [rule])
    assert result["department"] == "IT"


def test_contains_operator_on_subject_text():
    rule = _rule(conditions=(OverrideCondition("subject_contains", "contains", "URGENT"),), override_department="IT")

    matching = apply_overrides(BASE_DECISION, "This is URGENT please help", "body", "a@b.com", [rule])
    not_matching = apply_overrides(BASE_DECISION, "Just a question", "body", "a@b.com", [rule])

    assert matching["department"] == "IT"
    assert not_matching["department"] == "Support"


def test_contains_operator_is_case_insensitive():
    rule = _rule(conditions=(OverrideCondition("subject_contains", "contains", "urgent"),), override_department="IT")
    result = apply_overrides(BASE_DECISION, "This is URGENT", "body", "a@b.com", [rule])
    assert result["department"] == "IT"


def test_sender_email_domain_condition_extracts_the_domain():
    rule = _rule(conditions=(OverrideCondition("sender_email_domain", "eq", "vip-client.com"),), override_department="Sales")

    matching = apply_overrides(BASE_DECISION, "s", "b", "person@vip-client.com", [rule])
    not_matching = apply_overrides(BASE_DECISION, "s", "b", "person@other.com", [rule])

    assert matching["department"] == "Sales"
    assert not_matching["department"] == "Support"


def test_intent_contains_checks_membership_in_the_intent_list():
    rule = _rule(conditions=(OverrideCondition("intent", "contains", "Inquiry"),), override_department="IT")
    result = apply_overrides(BASE_DECISION, "s", "b", "a@b.com", [rule])
    assert result["department"] == "IT"


def test_is_spam_boolean_condition():
    spam_decision = {**BASE_DECISION, "supporting_signals": {**BASE_DECISION["supporting_signals"], "spam": {"is_spam": True, "confidence": 0.9}}}
    rule = _rule(conditions=(OverrideCondition("is_spam", "eq", True),), override_action="quarantine")

    result = apply_overrides(spam_decision, "s", "b", "a@b.com", [rule])
    not_matching = apply_overrides(BASE_DECISION, "s", "b", "a@b.com", [rule])

    assert result["action"] == "quarantine"
    assert not_matching["action"] == "auto_route"


def test_an_override_can_never_disable_human_review_for_a_high_impact_department():
    """The one non-negotiable safety net (see app/routing/overrides.py's
    own docstring): even if an override explicitly tries to force
    requires_human_review=False, a resulting HIGH_IMPACT department (HR/
    Legal/Billing) still requires review."""
    rule = _rule(
        conditions=(OverrideCondition("category", "eq", "Support"),),
        override_department="Billing",
        override_requires_human_review=False,
    )
    result = apply_overrides(BASE_DECISION, "s", "b", "a@b.com", [rule])

    assert result["department"] == "Billing"
    assert result["requires_human_review"] is True
    assert "R-HIGH-IMPACT-DEPARTMENT-REVIEW" in result["matched_rules"]


def test_high_impact_safety_net_does_not_fire_for_a_non_high_impact_department():
    rule = _rule(
        conditions=(OverrideCondition("category", "eq", "Support"),),
        override_department="IT",
        override_requires_human_review=False,
    )
    result = apply_overrides(BASE_DECISION, "s", "b", "a@b.com", [rule])

    assert result["department"] == "IT"
    assert result["requires_human_review"] is False
    assert "R-HIGH-IMPACT-DEPARTMENT-REVIEW" not in result["matched_rules"]
