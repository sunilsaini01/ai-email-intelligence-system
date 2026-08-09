# Email Routing Engine — Architecture (Phase 8)

> **Data status**: Routing composes five upstream signals, four of which
> carry their own disclosed data-quality caveats (Category/Priority/Intent:
> synthetic labels; Sentiment: no ground truth at all). See
> `docs/routing_signal_reliability.md` before trusting any routing decision
> as more than engineering/pipeline validation.

## What This Module Establishes

The eighth production module, and the first **composition** module — every
prior module (Spam through Intent) implements one independent intelligence
capability behind one predictor. Routing is a decision layer over five
existing signals, not a sixth trained classifier (`docs/model_cards/
routing.md` "Why Not a New ML Model" explains why one wasn't built).

## Request Flow

```
POST /api/v1/routing/predict {subject?, body, sender_email?}
        │
        ▼
Pydantic validation (RoutingPredictionRequest)
        │
        ▼
RoutingService.route()
        │  spam_result = SpamService.classify()          -- always called
        │  if not is_spam:
        │      category_result   = CategoryService.classify()
        │      intent_result     = IntentService.analyze()
        │      sentiment_result  = SentimentService.analyze()
        │      priority_result   = PriorityService.classify()
        │  keyword_votes  = match_department_keywords(subject+body)
        │  sender_domain  = classify_sender_domain(sender_email)
        │  signals = RoutingSignals(...)          -- pure, service-agnostic view
        │  decision = resolve_routing(signals)    -- app/routing/rules.py, pure function
        ▼
        ├──► structured log (app.routing) -- metadata only, never subject/body
        ├──► RoutingDecisionRepository -- audit row (best-effort, bounded)
        │
        ▼
RoutingPredictionResponse {department, action, confidence,
                            requires_human_review, reason, matched_rules,
                            supporting_signals, model_versions,
                            routing_rules_version, keyword_matcher_version,
                            upstream_failures, processing_ms}
```

## Composition Boundary: In-Process Calls, Not HTTP

`RoutingService` holds references to `SpamService`/`CategoryService`/
`IntentService`/`SentimentService`/`PriorityService` and calls their
existing synchronous methods directly (`spam_service.classify(...)`, etc.)
— the same modular-monolith rationale `docs/architecture.md` establishes at
Phase 1 (no inter-service network calls). The whole composed call is
offloaded to the threadpool once, at the API layer (`run_in_threadpool
(service.route, ...)`), exactly like every other module's single CPU-bound
call — not five separate threadpool hops.

This is the codebase's first module to call more than one upstream service
together. Repository audit (Gate B, before any code was written) confirmed
no orchestrator/composition point existed anywhere in `backend/app` prior
to this phase — `phase7b_intent_requirements_traceability.md`'s own FR-36
row anticipated this: *"routing (Phase 8) ... don't exist yet to consume
it."*

## Pure Logic vs. Service Wiring — `app/routing/` vs. `app/services/routing_service.py`

Mirrors the `app/nlp/` (pure generation logic) vs.
`services/summarization_service.py` (wiring) split Phase 6 established:

- `app/routing/rules.py` — `resolve_routing(RoutingSignals) ->
  RoutingDecision`, a pure function with no service dependency, unit-tested
  directly (`tests/test_routing_rules.py`) without constructing any of the
  five upstream services.
- `app/routing/keyword_matcher.py`, `app/routing/sender_domain.py`,
  `app/routing/department_taxonomy.py`, `app/routing/signal_reliability.py`
  — supporting pure logic, independently testable.
- `app/services/routing_service.py` — the only piece that knows how to
  construct/call the five real services, catches their failures, and shapes
  results into `RoutingSignals`/the response dict.

## Failure Isolation

Each of the five upstream calls is wrapped independently
(`RoutingService._safe_call`). A failing/unavailable service is recorded in
`unavailable_signals` (surfaced as `upstream_failures` in the response) and
treated as absent evidence, not a fatal error — `route()` has no
`RoutingServiceUnavailable`/503 path of its own (see `docs/model_cards/
routing.md`) and always returns a decision, worst case `R-NO-EVIDENCE-
FALLBACK` (`department=General`, `requires_human_review=True`).

**Spam-unavailable policy, stated explicitly because it's a real judgment
call**: if the Spam service itself fails, `is_spam` is `None`, and `not
None` is `True` in Python — routing proceeds as if the email were *not*
spam, rather than defaulting to quarantine-on-uncertainty. Rationale:
defaulting to quarantine whenever the spam service merely hiccups would
silently blackhole legitimate mail on a transient failure; proceeding to
normal routing (with category/keyword evidence and human review as the
safety net) is the safer default given Spam is otherwise this system's most
trustworthy signal, not the one most likely to need a defensive assumption.

## Database

`routing_decision_logs` — same JSON-column, GUID-portability pattern every
prior audit-log table uses (`app/models/routing_decision_log.py`). Two
extra indexes beyond the usual `created_at` (`department`,
`requires_human_review`) — added because this module's PRD context (§3.2's
manager persona: "real-time dashboard... SLA breach alerts") makes
querying by department/review-status a first-class access pattern, unlike
prior modules' pure audit-trail use.

`synthetic_model` (present on every prior prediction-log table) is kept for
schema uniformity, but its meaning is necessarily broader here: routing has
no model of its own, so it means "at least one upstream signal this
decision used is synthetic-labelled or unvalidated" — true for every
decision today (see `app/models/routing_decision_log.py`'s docstring and
`docs/routing_signal_reliability.md` for the per-signal detail this one
flag collapses).

Migration `d4a8f3c216e7` (down_revision `c9f2e841a7b3`, the intent
migration) verified end-to-end against a real, disposable PostgreSQL 16
Docker container: `upgrade head` → confirmed table/column/index shape via
`\d routing_decision_logs` → `downgrade -1` → confirmed table dropped →
`upgrade head` again → confirmed heads. Also exercised against SQLite in
`tests/test_routing_prediction_log.py`.

## Security Review

- No PII anonymization applied (same stance as every prior module — not
  currently required, revisit if this text ever reaches an external API).
- Prompt injection not applicable — keyword matching and rule evaluation
  are classical string/threshold logic with no instruction-following
  mechanism to exploit; verified via `tests/test_routing_security.py`.
- Structured logs (`app.routing`) confirmed to never carry raw
  subject/body — only department/action/matched_rules/processing_ms.
- Regex-DoS: every keyword pattern is a flat literal alternation (no
  nested quantifiers); input additionally capped at 20,000 chars before
  matching. Verified with a 4,000-repetition adversarial input under a 2s
  bound (`tests/test_routing_security.py::
  test_repeated_keyword_input_does_not_cause_pathological_regex_time`).
- Sender email treated as untrusted input throughout — `extract_domain()`
  never raises on malformed input, and sender-domain classification never
  gates a security or routing decision by itself
  (`app/routing/sender_domain.py`).

## Performance

Routing's own added cost (rule evaluation + keyword matching) is
sub-millisecond — the dominant cost is the sum of the (up to) five upstream
service calls it composes, each already measured and documented in its own
architecture doc. No new latency-sensitive component was introduced;
routing does not call any upstream service that itself makes a network
call.

## Known Gaps

| Gap | Reason |
|---|---|
| FR-42 (round-robin / skills-based agent routing) | No `users`/`agents` table exists anywhere in this codebase — see `docs/routing_taxonomy.md` |
| FR-39's literal DB-backed `/routing/rules` CRUD API | No auth/multi-tenancy exists yet — building it unauthenticated would be worse than not building it; see `docs/routing_rules.md` |
| FR-41's "adjust rule weights" from feedback | Deliberately not implemented — feedback is captured (JSONL) but never auto-adjusts thresholds; same stance every other module's feedback path takes (RULE about not auto-retraining from feedback) |
| Sender history (frequency, prior corrections, last seen) | No persistence exists; would require new tables beyond this phase's scope — see `docs/ml_data_maturity_roadmap.md` |
| Composite numeric `RoutingScore` | Deliberately not implemented — see `docs/routing_conflict_resolution.md` "No Composite RoutingScore" |
| Routing accuracy / precision / recall against ground truth | No human-labelled routing-outcome dataset exists — see `docs/model_cards/routing.md` "Evaluation" and `docs/ml_data_maturity_roadmap.md` |
