# Department Routing Taxonomy (FR-37)

## Decision: Reuse Category's 8-Label Taxonomy

The PRD names departments only in prose (§3.2's pain-point table: Customer
Support, Sales, HR, IT Helpdesk, Operations, Management) — never as a closed
enum tied to FR-37–40. That list does not match Category's own FR-21
taxonomy (Support, Sales, Billing, Legal, HR, IT, Marketing, General):
§3.2 has "Operations" and "Customer Support" where Category has "Billing",
"Legal", "Marketing", and plain "Support".

Confirmed with the project owner before implementation: **routing reuses
Category's 8 labels as the department taxonomy** (`app/routing/
department_taxonomy.py:DEPARTMENTS`, aliasing `CATEGORY_LABELS`). It is the
only closed, already-implemented, already-predicted taxonomy anywhere in
this codebase — inventing a ninth label set to reconcile PRD prose with
Category's real output would be exactly the kind of unevidenced assumption
this phase's brief prohibits.

**Consequence, disclosed rather than hidden:** "Operations" and
"Management" (§3.2 prose) have no corresponding department and no upstream
signal (no category, no intent, no keyword lexicon) identifies them. An
email that is genuinely an Operations-analytics request or a Management
visibility request falls through to `General` + mandatory human review —
the same outcome as any other low-evidence email, not a special case.

## Per-Department Reference

| Department | Responsibility | High-Impact? | Primary Signal | Corroborating Signals |
|---|---|---|---|---|
| **Support** | General product/service issues, bugs, how-to questions | No | Category | Keywords ("not working", "bug", "help") |
| **Sales** | Leads, pricing, demos, upgrades, purchase intent | No | Category | Keywords ("quote", "pricing", "demo") |
| **Billing** | Invoices, payments, charges, refunds, subscriptions | **Yes** — financial action | Category | Intent=Refund (`R-REFUND-BILLING-CORROBORATED`), Keywords ("invoice", "refund", "charge") |
| **Legal** | Contracts, compliance, regulatory, legal notices | **Yes** | Category | Keywords ("contract", "subpoena", "gdpr") |
| **HR** | Benefits, payroll, employment matters, workplace complaints | **Yes** — PRD §3.2's own "legal liability" example | Category | Keywords ("payroll", "pto", "termination") |
| **IT** | Internal IT tickets: VPN, access, password resets, outages | No | Category | Keywords ("vpn", "password reset", "outage") |
| **Marketing** | Press, campaigns, sponsorships, media inquiries | No | Category | Keywords ("campaign", "press", "sponsorship") |
| **General** | Catch-all / fallback — no other department has sufficient positive evidence | No | — (defined by absence, same as Category's own definition) | Landing point for §3.2's unsupported "Operations"/"Management" prose departments |

`HIGH_IMPACT_DEPARTMENTS = {HR, Legal, Billing}` (`app/routing/
department_taxonomy.py`) — chosen directly from the PRD's own stated risk
language (§3.2: HR's "legal liability"; Legal obviously; Billing as the
system's only financial-action category, per the Phase 8 brief's §20
"CRITICAL RULE" naming financial action explicitly). Any decision landing on
one of these three **always** carries `requires_human_review=True`
regardless of routing confidence — see `docs/routing_conflict_resolution.md`
`R-HIGH-IMPACT-DEPARTMENT-REVIEW`.

## Fallback Behavior

Every department that is not `HIGH_IMPACT` and not `General` follows the
ordinary confidence-threshold rule (`R-CATEGORY-AUTO-ROUTE` /
`R-CATEGORY-LOW-CONFIDENCE` / `R-CATEGORY-TIE`, see `docs/routing_rules.md`).
`General` itself has no keyword lexicon of its own, by the same design
Category already uses (`app/feature_engineering/category_keywords.py`: "No
GENERAL_KEYWORDS set: General is the taxonomy's explicit fallback... it's
defined by the ABSENCE of the other 7 signals").

## Not Implemented: Agent-Level Routing (FR-42)

FR-42 ("round-robin and skills-based routing between agents") requires an
agent/user roster this codebase does not have — no `users` or `agents`
table exists anywhere (confirmed by repository audit: `docs/architecture.md`
defers real auth and multi-tenancy from Phase 1 onward). Every routing
response's `department` field is populated; there is no `agent_id`
equivalent field at all in this phase's schema. Documented here as a known
gap, not silently omitted — see `docs/ml_data_maturity_roadmap.md` and
README.md's "Known Gaps".
