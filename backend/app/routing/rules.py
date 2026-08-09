"""
Routing rule engine (FR-39: "configurable rule-based overrides with priority
ordering"; FR-40: "logged with the reasoning (which rules/signals fired)").

Implemented as versioned, code-defined rules (a dict of RoutingSignals ->
decisions), the same pattern the rest of this codebase already uses for
versioned business vocabulary (category_keywords.py, intent_keywords.py) --
NOT a DB-backed table with a CRUD API. That's a deliberate scope decision,
confirmed with the project owner: a real GET/POST/PUT/DELETE /routing/rules
API per the PRD's SS13.2 would let an unauthenticated caller rewrite live
routing logic, because this codebase has no auth/multi-tenancy yet
(docs/architecture.md's "Known Gaps" -- real auth was deferred at Phase 1 and
still doesn't exist). DB-backed configurable rules are documented as a
follow-up gap in docs/ml_data_maturity_roadmap.md and
docs/routing_rules.md, blocked on auth landing first -- same treatment
README.md already gives FR-23's deferred per-org taxonomy.

Every rule that can fire is registered in RULE_REGISTRY (rule_id ->
description) so matched_rules in a response can always be resolved to a
human-readable reason, and so tests can assert no rule_id is ever emitted
that isn't documented here. See docs/routing_rules.md for the full,
generated-from-this-file rule catalogue, and
docs/routing_conflict_resolution.md for the precedence/tie-break rationale
this function implements.

Numeric thresholds below are ENGINEERING HEURISTICS, not learned or
calibrated values (RULE 14 -- never call a heuristic weight "learned"). No
routing dataset exists yet to calibrate them against (see
docs/ml_data_maturity_roadmap.md); they encode a deliberately conservative
default (prefer human review over confident auto-routing) and are expected
to move once real routing-outcome data exists.
"""

from dataclasses import dataclass, field

from app.routing.department_taxonomy import FALLBACK_DEPARTMENT, HIGH_IMPACT_DEPARTMENTS

ROUTING_RULES_VERSION = "routing_rules_v1"

ACTION_AUTO_ROUTE = "auto_route"
ACTION_HUMAN_REVIEW = "human_review"
ACTION_QUARANTINE = "quarantine"
ACTION_FALLBACK = "fallback"

# --- HEURISTIC thresholds (see module docstring) ----------------------------
CATEGORY_AUTO_ROUTE_THRESHOLD = 0.55
CATEGORY_TIE_MARGIN = 0.05
KEYWORD_FALLBACK_MIN_VOTES = 2
CRITICAL_PRIORITY_CONFIDENCE_FLOOR = 0.75
BORDERLINE_SENTIMENT_MARGIN = 0.10

ESCALATION_CORROBORATING_PRIORITIES = frozenset({"Critical", "High"})
ESCALATION_CORROBORATING_SENTIMENTS = frozenset({"Very Negative", "Negative"})
NEGATIVE_SENTIMENTS = frozenset({"Very Negative", "Negative"})

RULE_REGISTRY: dict[str, str] = {
    "R-SPAM-GATE": (
        "Spam-flagged email is quarantined without department routing. "
        "Highest precedence -- pre-empts every other rule."
    ),
    "R-CATEGORY-AUTO-ROUTE": (
        "Top category confidence >= CATEGORY_AUTO_ROUTE_THRESHOLD and not tied "
        "with the runner-up -- auto-routed to that category's department."
    ),
    "R-CATEGORY-LOW-CONFIDENCE": (
        "Top category confidence below CATEGORY_AUTO_ROUTE_THRESHOLD -- "
        "surfaced as a candidate department, routed to human review."
    ),
    "R-CATEGORY-TIE": (
        "Top-2 category confidences within CATEGORY_TIE_MARGIN of each other -- "
        "ambiguous, routed to human review with the top candidate shown."
    ),
    "R-CATEGORY-UNAVAILABLE-KEYWORD-FALLBACK": (
        "Category service unavailable; word-boundary keyword matching found a "
        "clear department candidate (>= KEYWORD_FALLBACK_MIN_VOTES). Keyword "
        "evidence alone never auto-routes -- always human review."
    ),
    "R-NO-EVIDENCE-FALLBACK": (
        "No category signal and no sufficient keyword evidence -- routed to "
        "the General department for human triage. Never drops an email."
    ),
    "R-HIGH-IMPACT-DEPARTMENT-REVIEW": (
        "Chosen department is HR, Legal, or Billing -- mandatory human review "
        "regardless of routing confidence (PRD SS3.2's own stated business risk "
        "for these departments)."
    ),
    "R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW": (
        "Sender domain classified 'external' AND department is HR, Legal, or "
        "Billing -- records external-sender-to-high-impact-department as an "
        "explicit, named contributing reason in the audit trail. Deliberately "
        "narrow (EXTERNAL only, HIGH_IMPACT departments only) and never "
        "changes `department`/`action` -- HIGH_IMPACT departments already "
        "unconditionally require review via R-HIGH-IMPACT-DEPARTMENT-REVIEW, "
        "so this rule's role is explainability/corroboration, not an "
        "independent department selector (FR-38's sender-domain signal, "
        "used conservatively -- see docs/routing_signal_reliability.md)."
    ),
    "R-ESCALATION-CORROBORATED": (
        "Intent 'Escalation' present AND corroborated by Priority=Critical/High "
        "or Sentiment=Negative/Very Negative -- flags human review. "
        "Uncorroborated Escalation has NO effect (see docs/error_analysis_intent.md "
        "for why Escalation alone is not trustworthy evidence)."
    ),
    "R-REFUND-BILLING-CORROBORATED": (
        "Intent 'Refund' present and department is already Billing -- "
        "corroborating evidence noted in the reason, department unchanged."
    ),
    "R-REFUND-CATEGORY-MISMATCH": (
        "Intent 'Refund' present but department is not Billing -- Refund had "
        "F1=0.0 on its own test set, so it never redirects a department by "
        "itself; flags human review instead."
    ),
    "R-CRITICAL-PRIORITY-CONFIDENCE-CHECK": (
        "Priority='Critical' on an auto-routed decision whose confidence is "
        "below CRITICAL_PRIORITY_CONFIDENCE_FLOOR -- downgraded to human review "
        "rather than auto-routing a Critical item unattended."
    ),
    "R-BORDERLINE-CONFIDENCE-NEGATIVE-SENTIMENT": (
        "Negative/Very Negative sentiment on an auto-routed decision whose "
        "confidence sits within BORDERLINE_SENTIMENT_MARGIN of the auto-route "
        "threshold -- downgraded to human review."
    ),
}


@dataclass(frozen=True)
class RoutingSignals:
    """Extracted, service-agnostic view of one email's upstream evidence --
    deliberately NOT the raw service response dicts, so resolve_routing() is
    unit-testable without constructing any of the five upstream services."""

    is_spam: bool | None = None
    spam_confidence: float | None = None

    category: str | None = None
    category_confidence: float | None = None
    category_second: str | None = None
    category_second_confidence: float | None = None

    intents: tuple[str, ...] = ()

    priority: str | None = None
    sentiment: str | None = None

    keyword_top: str | None = None
    keyword_votes: dict[str, int] = field(default_factory=dict)

    sender_domain_type: str = "unknown"

    # Names of upstream signals that raised/were unavailable this call
    # ("spam", "category", "intent", "sentiment", "priority") -- see
    # RoutingService for how these get populated via per-signal try/except.
    unavailable_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingDecision:
    department: str | None
    action: str
    confidence: float
    requires_human_review: bool
    reason: str
    matched_rules: tuple[str, ...]


def resolve_routing(signals: RoutingSignals) -> RoutingDecision:
    """Pure function: signals in, one deterministic decision out. Never
    raises, never returns a department-less non-quarantine/fallback state
    (RULE 10 -- never silently drop an email)."""
    matched: list[str] = []
    reasons: list[str] = []

    if signals.unavailable_signals:
        reasons.append(
            f"Upstream signal(s) unavailable this call: {', '.join(signals.unavailable_signals)}."
        )

    # R-SPAM-GATE -- highest precedence, pre-empts everything else.
    if signals.is_spam:
        matched.append("R-SPAM-GATE")
        confidence = signals.spam_confidence if signals.spam_confidence is not None else 0.0
        reasons.append("Spam detected; quarantined without department routing.")
        return RoutingDecision(
            department=None,
            action=ACTION_QUARANTINE,
            confidence=confidence,
            requires_human_review=False,
            reason=" ".join(reasons),
            matched_rules=tuple(matched),
        )

    requires_review = False

    # --- Department selection --------------------------------------------
    if signals.category is not None and signals.category_confidence is not None:
        margin = (
            signals.category_confidence - signals.category_second_confidence
            if signals.category_second_confidence is not None
            else 1.0
        )
        is_tied = margin < CATEGORY_TIE_MARGIN
        meets_threshold = signals.category_confidence >= CATEGORY_AUTO_ROUTE_THRESHOLD

        department = signals.category
        confidence = signals.category_confidence

        if is_tied:
            matched.append("R-CATEGORY-TIE")
            action = ACTION_HUMAN_REVIEW
            requires_review = True
            reasons.append(
                f"Category confidence tied between '{signals.category}' and "
                f"'{signals.category_second}' (margin {margin:.2f} < {CATEGORY_TIE_MARGIN})."
            )
        elif meets_threshold:
            matched.append("R-CATEGORY-AUTO-ROUTE")
            action = ACTION_AUTO_ROUTE
            reasons.append(
                f"Category '{signals.category}' ({signals.category_confidence:.2f}) "
                f">= auto-route threshold ({CATEGORY_AUTO_ROUTE_THRESHOLD})."
            )
        else:
            matched.append("R-CATEGORY-LOW-CONFIDENCE")
            action = ACTION_HUMAN_REVIEW
            requires_review = True
            reasons.append(
                f"Category '{signals.category}' confidence ({signals.category_confidence:.2f}) "
                f"below auto-route threshold ({CATEGORY_AUTO_ROUTE_THRESHOLD})."
            )
    elif (
        signals.keyword_top is not None
        and signals.keyword_votes.get(signals.keyword_top, 0) >= KEYWORD_FALLBACK_MIN_VOTES
    ):
        matched.append("R-CATEGORY-UNAVAILABLE-KEYWORD-FALLBACK")
        department = signals.keyword_top
        action = ACTION_HUMAN_REVIEW  # keyword evidence alone never auto-routes
        votes = signals.keyword_votes
        total = sum(votes.values()) or 1
        confidence = votes[signals.keyword_top] / total  # HEURISTIC, not a calibrated probability
        requires_review = True
        reasons.append(
            "Category signal unavailable; keyword evidence suggests "
            f"'{signals.keyword_top}' ({votes[signals.keyword_top]} matches). "
            "Unconfirmed -- human review required."
        )
    else:
        matched.append("R-NO-EVIDENCE-FALLBACK")
        department = FALLBACK_DEPARTMENT
        action = ACTION_FALLBACK
        confidence = 0.0
        requires_review = True
        reasons.append(
            "No category signal and no sufficient keyword evidence -- "
            "routed to General for human triage."
        )

    # --- High-impact department: mandatory review regardless of confidence -
    # Unconditional (not gated on `not requires_review`, per the Phase 8
    # engineering review's explainability fix): this rule must always appear
    # in matched_rules when the department is HIGH_IMPACT, even if another
    # rule (e.g. R-CATEGORY-LOW-CONFIDENCE) already set requires_review=True
    # first -- otherwise the audit trail under-reports that a decision was
    # HIGH_IMPACT-gated. Cannot fire twice (this block runs at most once per
    # call) and never changes `department`/`action`.
    if department in HIGH_IMPACT_DEPARTMENTS:
        matched.append("R-HIGH-IMPACT-DEPARTMENT-REVIEW")
        requires_review = True
        reasons.append(
            f"'{department}' is a high-impact department (HR/Legal/Billing) -- "
            "mandatory human review regardless of routing confidence."
        )

    # --- Sender domain: informational corroborating signal only, NEVER a
    # department selector or override (FR-38's fifth combined signal --
    # deliberately conservative, per the Phase 8 engineering review's Fix #3).
    # Scoped narrowly: EXTERNAL only (not freemail/unknown/internal), and
    # HIGH_IMPACT departments only. Cannot change `requires_review` from
    # False to True in practice (HIGH_IMPACT already mandates review
    # unconditionally, above) -- its purpose is explicitly naming this
    # specific factor in matched_rules/reason for audit-trail accuracy, not
    # causing a decision that wouldn't otherwise happen. Never applied to
    # non-HIGH_IMPACT departments: most legitimate senders to Support/Sales/
    # Marketing/IT ARE external by nature (customers, leads), so treating
    # "external" as caution-worthy there would flag ordinary traffic, not
    # anomalies.
    if signals.sender_domain_type == "external" and department in HIGH_IMPACT_DEPARTMENTS:
        matched.append("R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW")
        requires_review = True
        reasons.append(
            f"External sender combined with high-impact department '{department}' "
            "-- additional corroborating reason for mandatory human review."
        )

    # --- Intent corroboration (weak/unreliable signal policy) --------------
    intents = set(signals.intents)

    if "Escalation" in intents:
        corroborated = (
            signals.priority in ESCALATION_CORROBORATING_PRIORITIES
            or signals.sentiment in ESCALATION_CORROBORATING_SENTIMENTS
        )
        if corroborated:
            matched.append("R-ESCALATION-CORROBORATED")
            requires_review = True
            reasons.append(
                "Intent 'Escalation' corroborated by priority/sentiment -- "
                "flagged for human review. Escalation alone is never sufficient "
                "(docs/error_analysis_intent.md)."
            )
        # Uncorroborated Escalation: deliberately no effect at all -- see
        # docs/routing_conflict_resolution.md "Unreliable Intent Policy".

    if "Refund" in intents:
        if department == "Billing":
            matched.append("R-REFUND-BILLING-CORROBORATED")
            reasons.append("Intent 'Refund' corroborates the Billing department assignment.")
        else:
            matched.append("R-REFUND-CATEGORY-MISMATCH")
            requires_review = True
            reasons.append(
                f"Intent 'Refund' present but department is '{department}', not Billing -- "
                "F1=0.0 on its own test set; flagged for review, department NOT "
                "changed on intent evidence alone."
            )

    # --- Priority: urgency modifier only, never a department selector ------
    if (
        signals.priority == "Critical"
        and action == ACTION_AUTO_ROUTE
        and confidence < CRITICAL_PRIORITY_CONFIDENCE_FLOOR
    ):
        matched.append("R-CRITICAL-PRIORITY-CONFIDENCE-CHECK")
        requires_review = True
        reasons.append(
            f"Priority 'Critical' with routing confidence ({confidence:.2f}) below "
            f"the stricter {CRITICAL_PRIORITY_CONFIDENCE_FLOOR} floor used for "
            "Critical-priority items -- flagged for review rather than auto-routed "
            "unattended."
        )

    # --- Sentiment: urgency modifier only, never a department selector -----
    if (
        signals.sentiment in NEGATIVE_SENTIMENTS
        and action == ACTION_AUTO_ROUTE
        and confidence < (CATEGORY_AUTO_ROUTE_THRESHOLD + BORDERLINE_SENTIMENT_MARGIN)
    ):
        matched.append("R-BORDERLINE-CONFIDENCE-NEGATIVE-SENTIMENT")
        requires_review = True
        reasons.append(
            f"Sentiment '{signals.sentiment}' combined with borderline routing "
            f"confidence ({confidence:.2f}) -- flagged for review."
        )

    return RoutingDecision(
        department=department,
        action=action,
        confidence=confidence,
        requires_human_review=requires_review,
        reason=" ".join(reasons),
        matched_rules=tuple(matched),
    )
