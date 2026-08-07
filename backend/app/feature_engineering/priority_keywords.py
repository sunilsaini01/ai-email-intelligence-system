"""
Priority-signal vocabularies (Module 3 / FR-17's "subject keywords" clause).

Three separate lists, not one combined "urgency" bag-of-words, because they
capture different operational signals (see docs/data_audit_priority.md §3):
escalation language should push an existing issue up a level, SLA language is
specifically about deadlines/breach risk, and general urgency language is the
broadest, weakest signal of the three. Keeping them separate lets error
analysis attribute a misclassification to a specific signal category instead
of one undifferentiated "keyword count."
"""

URGENCY_KEYWORDS = frozenset({
    "urgent",
    "asap",
    "immediately",
    "critical",
    "emergency",
    "right away",
    "time-sensitive",
    "time sensitive",
    "action required",
    "important",
    "priority",
    "deadline",
    "before end of day",
    "eod",
    "outage",
    "down",
    "breach",
})

ESCALATION_KEYWORDS = frozenset({
    "escalate",
    "escalation",
    "escalating",
    "your manager",
    "speak to your manager",
    "third time",
    "again",
    "still waiting",
    "no response",
    "unacceptable",
    "formal complaint",
    "legal action",
    "cancel my account",
    "cancelling my account",
})

SLA_KEYWORDS = frozenset({
    "sla",
    "service level agreement",
    "contract",
    "penalty",
    "breach of contract",
    "compliance",
    "regulatory",
    "audit",
    "deadline",
    "past due",
    "overdue",
})
