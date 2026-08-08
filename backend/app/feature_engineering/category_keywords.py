"""
Category-signal vocabularies (Module 4 / FR-21's 8-label taxonomy).

One frozenset per category, not one combined bag-of-words, for the same
reason app/feature_engineering/priority_keywords.py splits urgency from
escalation from SLA language: keeping them separate lets error analysis
attribute a misclassification to a specific category's keyword signal
instead of one undifferentiated count, and lets each category's count feed
its own One-vs-Rest binary classifier as an independent feature (see
app/pipeline/category_pipeline.py).

These same lexicons drive BOTH the synthetic label generator
(scripts/generate_synthetic_category_dataset.py) AND the model's own
features (via ContentFeatureExtractor) — this is the same structural
leakage channel already disclosed for priority_keywords.py's role in
priority_synthetic_v1 (see docs/data_audit_priority.md §4 and, for this
module, docs/data_audit_categorization.md §4). Not a coincidence to avoid;
a documented, deliberate scoping decision.
"""

SUPPORT_KEYWORDS = frozenset({
    "not working",
    "doesn't work",
    "broken",
    "bug",
    "issue",
    "problem",
    "error",
    "crash",
    "crashed",
    "can't log in",
    "cannot log in",
    "help",
    "trouble",
    "how do i",
    "not able to",
    "stopped working",
})

SALES_KEYWORDS = frozenset({
    "quote",
    "pricing",
    "price",
    "demo",
    "trial",
    "upgrade",
    "purchase",
    "buy",
    "proposal",
    "opportunity",
    "prospect",
    "enterprise plan",
    "reseller",
    "partnership",
    "evaluating your",
    "interested in your product",
})

BILLING_KEYWORDS = frozenset({
    "invoice",
    "payment",
    "billing",
    "refund",
    "charge",
    "charged",
    "subscription",
    "receipt",
    "overdue",
    "past due",
    "billed",
    "credit card",
    "autopay",
    "dispute the charge",
    "cancel my subscription",
})

LEGAL_KEYWORDS = frozenset({
    "contract",
    "agreement",
    "legal",
    "compliance",
    "regulatory",
    "subpoena",
    "terms of service",
    "cease and desist",
    "liability",
    "nda",
    "non-disclosure",
    "data processing agreement",
    "gdpr",
    "audit",
    "redline",
    "counsel",
})

HR_KEYWORDS = frozenset({
    "benefits",
    "payroll",
    "onboarding",
    "offer letter",
    "pto",
    "vacation request",
    "performance review",
    "employee",
    "hiring",
    "recruiter",
    "open enrollment",
    "hr policy",
    "resignation",
    "termination",
    "workplace",
})

IT_KEYWORDS = frozenset({
    "vpn",
    "password reset",
    "access request",
    "laptop",
    "server",
    "network",
    "outage",
    "provisioning",
    "install",
    "login credentials",
    "firewall",
    "it ticket",
    "system down",
    "reboot",
    "software update",
})

MARKETING_KEYWORDS = frozenset({
    "campaign",
    "newsletter",
    "press",
    "media inquiry",
    "sponsorship",
    "brand",
    "content review",
    "social media",
    "promotion",
    "launch",
    "webinar",
    "event",
    "advertising",
    "pr request",
})

# No GENERAL_KEYWORDS set: General is the taxonomy's explicit fallback
# (docs/data_audit_categorization.md §3) — it's defined by the ABSENCE of
# the other 7 signals, not by its own keyword list. A keyword list for
# "General" would just be noise competing with the 7 real signals.

CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    "Support": SUPPORT_KEYWORDS,
    "Sales": SALES_KEYWORDS,
    "Billing": BILLING_KEYWORDS,
    "Legal": LEGAL_KEYWORDS,
    "HR": HR_KEYWORDS,
    "IT": IT_KEYWORDS,
    "Marketing": MARKETING_KEYWORDS,
}

CATEGORY_LABELS: tuple[str, ...] = (
    "Support", "Sales", "Billing", "Legal", "HR", "IT", "Marketing", "General",
)
