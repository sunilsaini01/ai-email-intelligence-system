# Phase 8 — Email Routing Engine: Requirements Traceability

Extracted directly from `project document/PRD_AI_Email_Intelligence_System.md`
§5, Module 8. No requirement below was invented — every row cites its PRD
source line.

## Functional Requirements (PRD §5, Module 8)

| PRD Requirement | Design | Implementation | Test | Evidence |
|---|---|---|---|---|
| **FR-37**: "System shall automatically route emails to the correct department and/or agent" | Department-level routing via `resolve_routing()`; agent-level explicitly deferred (no `users`/`agents` table exists — see `docs/routing_taxonomy.md`) | `app/routing/rules.py`, `app/services/routing_service.py` | `tests/test_routing_rules.py`, `tests/test_routing_endpoint.py` | Every response has a `department` field (or `None` for quarantine) and `action`; `agent_id` is not a field in this phase's schema, disclosed as deferred, not silently omitted |
| **FR-38**: "Routing shall use combined signals: category, intent, sentiment, keywords, sender domain" | All 5 named signals participate in actual decisions, not merely composed for display. **Fixed during the Phase 8 engineering review**: `sender_domain_type` was previously computed and attached to `RoutingSignals` but never read by `resolve_routing()` — a real FR-38 gap, not just a documentation issue. Now wired into `R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW` (external sender + HR/Legal/Billing department → additional corroborating reason for mandatory review, recorded in `matched_rules`) — deliberately conservative: never selects or overrides a department, and has no effect for non-HIGH_IMPACT departments. Spam and Priority additionally composed as architecturally necessary (gate + urgency modifier) though not literally enumerated in FR-38's text — flagged explicitly, not silently added | `app/routing/rules.py:resolve_routing()` (sender-domain rule), `app/services/routing_service.py:route()` (composition) | `tests/test_routing_rules.py` (`test_external_sender_with_high_impact_department_adds_review_rule` and 3 companion tests proving it cannot select a department or fire outside HIGH_IMPACT) | `docs/routing_signal_reliability.md`, `docs/routing_conflict_resolution.md` "Sender Domain" |
| **FR-39**: "System shall support configurable rule-based overrides with priority ordering" | Versioned, code-defined rules (`routing_rules_v1`), evaluated in a fixed sequence — **not** a DB-backed CRUD API, a confirmed scope decision given no auth/multi-tenancy exists. Note on "priority ordering": the current implementation is a single sequential function, not a data-driven, independently-testable priority field per rule — the Phase 8 engineering review flagged this as a real, if low-risk, gap between what "priority ordering" implies and what's implemented; each rule's outcome is individually unit-tested, but rule *sequencing itself* is an emergent property of code layout, not an inspectable, enforced data structure. Not changed in this fix pass (out of the approved scope: "do not refactor the entire rule engine") | `app/routing/rules.py:RULE_REGISTRY`, `docs/routing_rules.md` | `tests/test_routing_rules.py` (precedence, tie-breaking, outcome-level coverage) | `docs/routing_rules.md` "Why Not a DB-Backed `/routing/rules` API" |
| **FR-40**: "All routing decisions shall be logged with the reasoning (which rules/signals fired)" | Every decision persists `reason`, `matched_rules`, `supporting_signals`, `model_versions`, `upstream_failures`. **Fixed during the Phase 8 engineering review**: quarantine decisions' `confidence` field was sourced from `SpamService`'s argmax-label `confidence` (routinely the HAM-label confidence, since the real 0.06 threshold classifies `is_spam=True` far below 0.5) instead of `spam_score` (the actual spam-class probability) — every quarantine's logged confidence was semantically wrong. Also fixed: `R-HIGH-IMPACT-DEPARTMENT-REVIEW` previously only appeared in `matched_rules` if no other rule had already set `requires_human_review` — under-reporting HIGH_IMPACT as a contributing factor when a confidence-based rule fired first; now recorded unconditionally whenever the department is HIGH_IMPACT | `app/models/routing_decision_log.py`, `app/database/repositories/routing_decision_repository.py`, migration `d4a8f3c216e7`, `app/services/routing_service.py:route()`, `app/routing/rules.py:resolve_routing()` | `tests/test_routing_prediction_log.py`, `tests/test_routing_service.py::test_route_quarantine_confidence_uses_spam_score_not_argmax_confidence`, `tests/test_routing_rules.py::test_high_impact_rule_is_recorded_even_when_review_already_required_by_another_rule` | Verified against real disposable Postgres 16 (upgrade → downgrade → upgrade) and SQLite |
| **FR-41**: "System shall detect routing errors via human feedback and adjust rule weights" | Feedback capture implemented (`FeedbackLogger.log_routing_feedback`); **automatic weight adjustment deliberately NOT implemented** — same stance every other module's feedback path takes (capture only, human-reviewed promotion is a separate future step) | `app/services/feedback_service.py`, `POST /api/v1/routing/feedback` | `tests/test_routing_endpoint.py::test_routing_feedback_is_logged` | `docs/routing_conflict_resolution.md`; `docs/ml_data_maturity_roadmap.md` "FR-41 automatic rule-weight adjustment" |
| **FR-42**: "Round-robin and skills-based routing between agents shall be supported" | **Not implemented this phase** — no `users`/`agents` table exists anywhere in this codebase (confirmed by repository audit before implementation began) | — | — | `docs/routing_taxonomy.md` "Not Implemented: Agent-Level Routing"; `docs/ml_data_maturity_roadmap.md` |

## Non-Functional Requirements

| PRD Requirement | Source | Design | Evidence |
|---|---|---|---|
| Routing Accuracy > 92% | PRD §14.1 | Not measured — no human-labelled routing-outcome ground truth exists | `docs/model_cards/routing.md` "Evaluation"; `docs/ml_data_maturity_roadmap.md` |
| No inter-service network calls within the monolith | PRD's implicit architecture + this codebase's own `docs/architecture.md` Phase 1 decision | `RoutingService` calls `SpamService`/`CategoryService`/`IntentService`/`SentimentService`/`PriorityService` directly, in-process | `docs/architecture_routing.md` "Composition Boundary" |
| No Kafka/Kubernetes/multi-agent-orchestrator | `docs/architecture.md` Phase 1 decision, reaffirmed by the Phase 8 brief's RULE 12 | Not introduced | `docs/architecture_routing.md` |
| Auditability — every decision explainable | PRD §13.3's worked example (`"reason": "Category: Shipping (0.88) + Intent: Complaint (0.94)..."`) | `reason`, `matched_rules`, `supporting_signals` present on every response | `tests/test_routing_endpoint.py::test_predict_returns_a_structurally_valid_response` |

## Explicitly Not Implemented This Phase (and why)

| PRD reference | Why deferred |
|---|---|
| FR-42 (agent-level round-robin/skills-based routing) | No `users`/`agents` table exists anywhere in this codebase |
| FR-39's literal `GET/POST/PUT/DELETE /routing/rules` CRUD API | No auth/multi-tenancy exists yet — an unauthenticated endpoint able to rewrite live routing logic is worse than not having it; see `docs/routing_rules.md` |
| FR-41's automatic rule-weight adjustment | Deliberately excluded — matches every other module's "capture feedback, never auto-retrain" stance |
| Sender history (frequency, prior corrections) | No data source exists; not required by any implemented rule |
| A composite numeric `RoutingScore` | Deliberately not implemented — see `docs/routing_conflict_resolution.md` "No Composite RoutingScore" |
| A sixth trained ML classifier for routing | Evaluated and rejected before implementation — see `docs/model_cards/routing.md` "Why Not a New ML Model" |

## Engineering Gates — Outcome

| Gate | Outcome |
|---|---|
| PRD requirements extracted (FR-37 to FR-42) | Done |
| Repository audited (services/API/DB/inference/test conventions) | Done — see `docs/architecture_routing.md` |
| Existing service contracts audited | Done — RoutingService composes existing `classify()`/`analyze()` methods unchanged |
| Routing input contract defined | Done — `RoutingPredictionRequest` (subject, body, sender_email) |
| Signal reliability audit completed | Done — `docs/routing_signal_reliability.md` |
| Department taxonomy verified | Done — `docs/routing_taxonomy.md` (confirmed decision: reuse Category's 8 labels) |
| Routing strategy selected and justified | Done — deterministic rules + weak-signal corroboration, no new ML model; `docs/model_cards/routing.md` |
| Rule precedence documented | Done — `docs/routing_conflict_resolution.md` |
| Conflict resolution implemented | Done — `app/routing/rules.py` |
| Low-confidence behavior implemented | Done — `R-CATEGORY-LOW-CONFIDENCE`, `R-CATEGORY-TIE` |
| Intent reliability policy implemented | Done — Escalation/Refund corroboration-gated, never independently select a department |
| Spam interaction defined | Done — hard gate, quarantine, pre-empts routing |
| Priority interaction defined | Done — urgency modifier only, never selects a department |
| Category interaction defined | Done — primary evidence, provisional status exposed |
| Sentiment interaction defined | Done — urgency modifier only, weakest footing disclosed |
| Keyword engine implemented | Done — word-boundary-safe, reuses existing lexicon, versioned |
| Sender-domain handling implemented | Done — informational only, never gates a decision |
| Sender-history status documented | Done — confirmed absent, deferred |
| Fallback behavior implemented | Done — `R-NO-EVIDENCE-FALLBACK`, never drops an email |
| Human-review path implemented | Done — `requires_human_review`, independent of `action` |
| Explainability implemented | Done — `reason`, `matched_rules`, `supporting_signals` on every response |
| API implemented | Done — `POST /routing/predict`, `POST /routing/feedback` |
| Database implemented | Done — `routing_decision_logs` |
| Alembic migration verified | Done — real disposable Postgres 16, upgrade/downgrade/upgrade round-trip |
| Feedback implemented | Done — capture only, no auto-adjustment |
| Security review completed | Done — `docs/architecture_routing.md` "Security Review" |
| Performance benchmark completed | Partial — routing's own overhead is sub-millisecond; full P50/P95/P99 under load not measured (no load-testing infrastructure exists in this codebase for any module) |
| Failure isolation implemented | Done — per-signal try/except, never crashes on 1-5 upstream failures |
| Unit tests added | Done — `tests/test_routing_rules.py`, `tests/test_routing_keyword_matcher.py` |
| Integration tests added | Done — `tests/test_routing_endpoint.py`, `tests/test_routing_prediction_log.py`, `tests/test_routing_service.py` |
| Adversarial/edge-case tests added | Done — `tests/test_routing_security.py` |
| Regression tests pass | Done — 265 passed, 1 skipped (pre-existing opt-in slow test), 0 failed |
| Routing evaluation completed | Done, as ENGINEERING VALIDATION — `docs/model_cards/routing.md` "Evaluation" |
| Manual evaluation set created | Done — 20 examples, `docs/error_analysis_routing.md`, surfaced a real, high-priority cross-module finding (Spam's domain-transfer precision gap) |
| ML data maturity roadmap created | Done — `docs/ml_data_maturity_roadmap.md` |
| Documentation completed | Done — this file plus 8 companion docs |
| Production-readiness level assigned | Done — LEVEL 2 (Routing logic validated); see `docs/model_cards/routing.md` "Production Readiness" |
