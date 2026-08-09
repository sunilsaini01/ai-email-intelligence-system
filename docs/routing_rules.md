# Routing Rules Catalogue (FR-39) — `routing_rules_v1`

Implemented as versioned, code-defined rules
(`backend/app/routing/rules.py:RULE_REGISTRY`), **not** a DB-backed table
with a CRUD API. This is a deliberate, confirmed scope decision — see
"Why Not a DB-Backed `/routing/rules` API" below — not an oversight against
the PRD's literal §13.2 endpoint list.

Every rule a decision can cite in its `matched_rules` field is listed here.
This table is kept in sync with `RULE_REGISTRY` by convention (both are
maintained by hand in the same PR whenever a rule changes) — see
`tests/test_routing_rules.py::test_every_matched_rule_id_is_registered` for
the regression guard that a rule can never fire without being documented.

| Rule ID | Priority | Condition | Action | Reason |
|---|---|---|---|---|
| `R-SPAM-GATE` | Highest — pre-empts all others | `is_spam == True` | `department=None`, `action=quarantine` | Spam-flagged email is quarantined without department routing. |
| `R-CATEGORY-AUTO-ROUTE` | 1 | Category confidence ≥ 0.55 (`CATEGORY_AUTO_ROUTE_THRESHOLD`, HEURISTIC) and not tied with runner-up | `action=auto_route` | Top category confidence clears the auto-route bar. |
| `R-CATEGORY-LOW-CONFIDENCE` | 1 | Category confidence < 0.55 | `action=human_review`, department shown as candidate | Confidence too low to auto-route unattended. |
| `R-CATEGORY-TIE` | 1 | Top-2 category confidences within 0.05 (`CATEGORY_TIE_MARGIN`, HEURISTIC) | `action=human_review` | Ambiguous between two departments. |
| `R-CATEGORY-UNAVAILABLE-KEYWORD-FALLBACK` | 1 (only when Category signal missing) | Category service failed AND a keyword department has ≥ 2 votes (`KEYWORD_FALLBACK_MIN_VOTES`, HEURISTIC) | `action=human_review` (never auto-route) | Keyword evidence stands in for a missing classifier, but is never trusted enough to auto-route alone. |
| `R-NO-EVIDENCE-FALLBACK` | 1 (last resort) | No category AND no sufficient keyword evidence | `department=General`, `action=fallback` | Never drops an email (RULE 10) — routes to General for human triage. |
| `R-HIGH-IMPACT-DEPARTMENT-REVIEW` | 2 | Chosen department ∈ {HR, Legal, Billing} | `requires_human_review=True` (action unchanged) | PRD §3.2's own stated business risk for these departments — see `docs/routing_taxonomy.md`. **Always recorded in `matched_rules` when the condition holds** — fixed during the Phase 8 engineering review, which found the prior `and not requires_review` guard silently omitted this rule from the audit trail whenever a different rule (e.g. `R-CATEGORY-LOW-CONFIDENCE`) had already set `requires_human_review` first. |
| `R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW` | 2 | Sender domain classified `external` AND chosen department ∈ {HR, Legal, Billing} | Reason text + `matched_rules` entry only — `requires_human_review` is already unconditionally `True` for HIGH_IMPACT departments via the rule above, so this rule cannot change that boolean; its purpose is explicitly naming external-sender-to-high-impact-department as a contributing factor | FR-38's sender-domain signal, wired in conservatively (Phase 8 engineering review Fix #3) — never selects or overrides a department, and has no effect for non-HIGH_IMPACT departments (most Support/Sales/Marketing/IT senders are legitimately external). See `docs/routing_conflict_resolution.md` "Sender Domain". |
| `R-ESCALATION-CORROBORATED` | 3 | Intent contains "Escalation" AND (Priority ∈ {Critical, High} OR Sentiment ∈ {Very Negative, Negative}) | `requires_human_review=True` (department unchanged) | Escalation alone is demonstrated unreliable (`docs/error_analysis_intent.md`); only acts when corroborated. |
| `R-REFUND-BILLING-CORROBORATED` | 3 | Intent contains "Refund" AND department == Billing | Reason text only, no field change | Corroborates an already-Billing decision. |
| `R-REFUND-CATEGORY-MISMATCH` | 3 | Intent contains "Refund" AND department != Billing | `requires_human_review=True` (department unchanged) | F1=0.0 class; never redirects a department by itself. |
| `R-CRITICAL-PRIORITY-CONFIDENCE-CHECK` | 4 | Priority == Critical AND action == auto_route AND confidence < 0.75 (`CRITICAL_PRIORITY_CONFIDENCE_FLOOR`, HEURISTIC) | `requires_human_review=True` | A Critical item shouldn't auto-route unattended unless confidence clears a stricter bar. |
| `R-BORDERLINE-CONFIDENCE-NEGATIVE-SENTIMENT` | 4 | Sentiment ∈ {Negative, Very Negative} AND action == auto_route AND confidence within 0.10 (`BORDERLINE_SENTIMENT_MARGIN`, HEURISTIC) of the auto-route threshold | `requires_human_review=True` | Negative sentiment on a borderline-confidence decision warrants a second look. |

All numeric thresholds are **ENGINEERING HEURISTICS**, not learned or
calibrated (RULE 14) — see `docs/ml_data_maturity_roadmap.md` for why no
routing-outcome dataset exists yet to calibrate them against, and
`docs/routing_conflict_resolution.md` for the full precedence rationale.

## Keyword Engine (`app/routing/keyword_matcher.py`, `routing_keywords_v1`)

Reuses `CATEGORY_KEYWORDS` (`app/feature_engineering/category_keywords.py`
— the same 7 department lexicons already used to build the synthetic
category dataset; no new vocabulary was invented for routing).

- **Word-boundary-safe**: `\b(?:phrase1|phrase2|...)\b` per department, each
  phrase `re.escape()`-d — fixes the one real precision gap in the
  codebase's existing keyword check (`content_features.py`'s plain
  substring containment, which matches "help" inside "helper").
- **Normalization**: irregular whitespace collapsed (`\s+` → single space)
  before matching, so a phrase like "not working" still matches across a
  line-wrapped or multi-spaced email.
- **Case-insensitive** (`re.IGNORECASE`).
- **Regex-DoS safe by construction**: every pattern is a flat alternation of
  escaped literals with no nested quantifiers — no catastrophic-backtracking
  risk regardless of input. Input is still capped at `MAX_MATCH_INPUT_CHARS`
  (20,000 chars) defensively before matching (Phase 8 brief SS25).
- **Deterministic tie-break**: when two departments have equal vote counts,
  the alphabetically-first department wins (`top_department_by_keywords()`).
- **Failure-isolated** (Phase 8 engineering review Fix #4): both the keyword
  matcher and sender-domain classification are wrapped in `RoutingService`'s
  `_safe_call`, the same failure-isolation mechanism used for the five
  upstream services — a bug in either degrades to a safe default (no keyword
  evidence / `sender_domain_type="unknown"`, recorded in `upstream_failures`)
  rather than crashing the request.

## Why Not a DB-Backed `/routing/rules` API

FR-39 ("configurable rule-based overrides") and the PRD's §13.2 API design
both point toward a `routing_rules` table with `GET/POST/PUT/DELETE
/routing/rules` CRUD, scoped by `organization_id`. This codebase has
**no auth and no multi-tenancy** — both explicitly deferred since Phase 1
(`docs/architecture.md`'s "Known Gaps": *"Real auth (OAuth2/JWT) — wiring
real auth before there's anything to protect is wasted motion"*). Building
literal CRUD endpoints today would mean an **unauthenticated** caller could
rewrite live business routing logic — a materially worse outcome than not
having the endpoint at all.

Confirmed with the project owner: routing rules are versioned code
(this file + `RULE_REGISTRY`), the same pattern the codebase already uses
for other versioned business vocabulary (`category_keywords.py`,
`intent_keywords.py`, `priority_keywords.py`). A DB-backed, auth-protected,
multi-tenant `/routing/rules` API is documented as a follow-up requirement
in `docs/ml_data_maturity_roadmap.md`, blocked on auth landing first — the
same treatment README.md already gives FR-23's deferred per-organization
category taxonomy.
