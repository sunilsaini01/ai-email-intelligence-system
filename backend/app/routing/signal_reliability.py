"""
Single source of truth for each routing input's evidentiary status --
referenced by RoutingService (embedded in every response's
supporting_signals) and generated verbatim into
docs/routing_signal_reliability.md, so the two can never drift apart.

Values are business/engineering judgments carried forward from each
upstream module's own documented data-quality status (README.md's Progress
table, each module's docs/data_audit_*.md) -- NOT re-derived here. Routing
does not re-evaluate an upstream model's evidence quality; it only labels
and propagates what was already disclosed.
"""

VALIDATED = "validated"
PROVISIONAL_SYNTHETIC = "provisional_synthetic"
UNVALIDATED = "unvalidated"
HEURISTIC = "heuristic"
INFORMATIONAL = "informational"

SIGNAL_RELIABILITY: dict[str, str] = {
    # Real labelled data, measured recall/precision (README.md Progress table).
    "spam": VALIDATED,
    # Real email text, heuristically-fabricated labels (docs/data_audit_categorization.md).
    "category": PROVISIONAL_SYNTHETIC,
    # Real email text, heuristically-fabricated labels; two classes
    # (Escalation, Refund) additionally demonstrated unreliable, not merely
    # unvalidated -- see docs/error_analysis_intent.md. Routing's own
    # rule-level handling of those two classes is documented in
    # app/routing/rules.py, not re-encoded here.
    "intent": PROVISIONAL_SYNTHETIC,
    # Real email text, heuristically-fabricated labels (docs/data_audit_priority.md).
    "priority": PROVISIONAL_SYNTHETIC,
    # Zero-shot VADER lexicon scorer, never trained/fit to anything, no
    # ground truth exists at all (docs/data_audit_sentiment.md) -- the
    # weakest evidentiary footing of any signal routing consumes.
    "sentiment": UNVALIDATED,
    # Deterministic word-boundary regex match against a hand-built lexicon --
    # not a probability, not calibrated, never presented as "learned".
    "keywords": HEURISTIC,
    # Static internal/freemail/external classification, never a security or
    # routing decision by itself (app/routing/sender_domain.py docstring).
    "sender_domain": INFORMATIONAL,
}
