"""
Department taxonomy (FR-37).

The PRD names departments only in prose (SS3.2's pain-point table: Customer
Support, Sales, HR, IT Helpdesk, Operations, Management) -- never as a closed
enum tied to FR-37-40. It is NOT the same list as Category's own FR-21
taxonomy (Support, Sales, Billing, Legal, HR, IT, Marketing, General): SS3.2
has "Operations" and "Customer Support" where Category has "Billing",
"Legal", "Marketing", and "Support". Inventing a third, new taxonomy to
reconcile them would be exactly the kind of assumption Phase 8's brief
prohibits.

Decision (confirmed with the project owner before implementation): reuse
Category's 8 labels as the department taxonomy. It is the only closed,
already-implemented, already-predicted taxonomy that exists anywhere in this
codebase -- routing by anything else would mean inventing a mapping from
Category's real output onto a taxonomy nothing actually predicts.
Consequence: "Operations" and "Management" (SS3.2 prose) have no
corresponding department and no upstream signal covers them -- documented
here as a known gap, not silently dropped. An email that is genuinely an
Operations-analytics request has no category, intent, or keyword signal in
this codebase that identifies it; it falls through to General + human
review, same as any other low-evidence email.

See docs/routing_taxonomy.md for the full per-department writeup this module
is the single source of truth for.
"""

from app.feature_engineering.category_keywords import CATEGORY_LABELS

# Same 8 labels Category (FR-21) predicts -- see module docstring for why
# routing does not define its own, different list.
DEPARTMENTS: tuple[str, ...] = CATEGORY_LABELS

# General is Category's own explicit "defined by absence" fallback
# (app/feature_engineering/category_keywords.py) -- reused here for the same
# reason: it is the only department with no keyword signal of its own by
# design, making it the correct catch-all when routing has no positive
# evidence for anything else.
FALLBACK_DEPARTMENT = "General"

# Departments the PRD (SS3.2) itself flags as carrying outsized business risk
# if misrouted or over-trusted: HR ("sensitive complaints (harassment,
# legal)... legal liability"), Legal (obviously), Billing (the system's only
# financial-action category -- SS20's "CRITICAL RULE" names financial action
# explicitly). A department in this set NEVER skips human review purely
# because model confidence was high -- see
# app/routing/rules.py:R-HIGH-IMPACT-DEPARTMENT-REVIEW and
# docs/routing_conflict_resolution.md. This is a business-risk judgment
# grounded in the PRD's own language, not a numeric confidence policy --
# labelled HEURISTIC/business-defined, not learned.
HIGH_IMPACT_DEPARTMENTS: frozenset[str] = frozenset({"HR", "Legal", "Billing"})

DEPARTMENT_RESPONSIBILITIES: dict[str, str] = {
    "Support": "General product/service issues, bugs, how-to questions -- FR-21's 'Support' category.",
    "Sales": "Leads, pricing, demos, upgrades, purchase intent.",
    "Billing": "Invoices, payments, charges, refunds, subscriptions -- HIGH_IMPACT (financial action).",
    "Legal": "Contracts, compliance, regulatory, legal notices -- HIGH_IMPACT.",
    "HR": "Benefits, payroll, employment matters, workplace complaints -- HIGH_IMPACT.",
    "IT": "Internal IT tickets: VPN, access, password resets, outages.",
    "Marketing": "Press, campaigns, sponsorships, media inquiries.",
    "General": (
        "Catch-all / fallback -- assigned when no other department has "
        "sufficient positive evidence (Category's own definition of "
        "'General', reused here). Also the landing point for SS3.2's "
        "'Operations' and 'Management' prose-only departments, which have "
        "no upstream ML or keyword signal in this codebase -- see module "
        "docstring."
    ),
}
