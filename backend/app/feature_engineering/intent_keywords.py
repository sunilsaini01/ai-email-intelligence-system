"""
Intent-signal vocabularies (Module 7 / FR-33's 9-class taxonomy).

Unlike priority_keywords.py/category_keywords.py, these lexicons feed ONLY
the synthetic label generator (scripts/generate_synthetic_intent_dataset.py)
-- NOT any ContentFeatures field consumed by the trained model. See
docs/data_audit_intent.md §5: IntentMLPipeline is deliberately TF-IDF-only,
so there is no "keyword count is also a model feature" leakage channel the
way there is for priority/category. Kept here (not inline in the generator
script) purely so the rules are independently inspectable and documented,
matching the sibling *_keywords.py modules' location convention.
"""

COMPLAINT_KEYWORDS = frozenset({
    "disappointed",
    "unacceptable",
    "frustrated",
    "frustrating",
    "poor service",
    "not satisfied",
    "worst experience",
    "unhappy",
    "complaint",
    "terrible",
    "very unhappy",
    "let down",
    "fed up",
})

INQUIRY_KEYWORDS = frozenset({
    "wondering",
    "question",
    "could you clarify",
    "asking about",
    "want to know",
    "please advise",
    "information about",
    "inquiry",
    "do you know",
    "can you tell me",
    "does your product",
})

REQUEST_KEYWORDS = frozenset({
    "please send",
    "requesting",
    "could you provide",
    "need you to",
    "please provide",
    "kindly",
    "request",
    "would you mind",
    "please share",
})

FEEDBACK_KEYWORDS = frozenset({
    "feedback",
    "suggestion",
    "just wanted to share",
    "thought you'd like to know",
    "review",
    "wanted to let you know",
    "great job",
    "nice work",
    "appreciate the improvement",
})

ESCALATION_KEYWORDS = frozenset({
    "escalate",
    "escalating",
    "speak to your manager",
    "speak to a manager",
    "supervisor",
    "senior attention",
    "third time",
    "still unresolved",
    "raise this further",
})

ORDER_KEYWORDS = frozenset({
    "order",
    "purchase",
    "shipment",
    "tracking number",
    "delivery",
    "my order",
    "placed an order",
    "order number",
    "order status",
})

CANCEL_KEYWORDS = frozenset({
    "cancel",
    "terminate",
    "unsubscribe",
    "discontinue",
    "close my account",
    "stop my subscription",
    "cancel my subscription",
    "cancel my order",
})

REFUND_KEYWORDS = frozenset({
    "refund",
    "reimburse",
    "money back",
    "return my payment",
    "credit my account",
    "refund my",
    "want my money back",
})

SCHEDULE_KEYWORDS = frozenset({
    "schedule",
    "reschedule",
    "meeting",
    "calendar",
    "appointment",
    "book a time",
    "available time",
    "book a call",
    "set up a call",
})

# No default/fallback keyword set, unlike category's "General" — FR-33
# names no default intent, and this phase deliberately does not invent one
# (see docs/intent_taxonomy.md "Request" entry and
# docs/data_audit_intent.md §5's design-decision note). An email may
# legitimately carry zero of these 9 intents.

INTENT_KEYWORDS: dict[str, frozenset[str]] = {
    "Complaint": COMPLAINT_KEYWORDS,
    "Inquiry": INQUIRY_KEYWORDS,
    "Request": REQUEST_KEYWORDS,
    "Feedback": FEEDBACK_KEYWORDS,
    "Escalation": ESCALATION_KEYWORDS,
    "Order": ORDER_KEYWORDS,
    "Cancel": CANCEL_KEYWORDS,
    "Refund": REFUND_KEYWORDS,
    "Schedule": SCHEDULE_KEYWORDS,
}

INTENT_LABELS: tuple[str, ...] = (
    "Complaint", "Inquiry", "Request", "Feedback", "Escalation",
    "Order", "Cancel", "Refund", "Schedule",
)
