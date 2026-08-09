# Model Card — Email Routing Engine (Phase 8)

> **THIS IS NOT A TRAINED MODEL.** Routing is a deterministic rule engine
> (`app/routing/rules.py`) composing five upstream signals, four of which
> carry their own disclosed data-quality caveats. There is no routing
> "accuracy" metric measured against real-world ground truth anywhere in
> this document, because no human-labelled routing-outcome dataset exists
> — see "Evaluation" below and `docs/ml_data_maturity_roadmap.md`.

## Model Details

| Field | Value |
|---|---|
| Approach | Deterministic rule engine + weak-signal corroboration (no trained classifier) |
| Rules | `backend/app/routing/rules.py:RULE_REGISTRY`, version `routing_rules_v1` |
| Keyword engine | `backend/app/routing/keyword_matcher.py`, version `routing_keywords_v1` |
| Inputs composed | Spam, Category, Intent, Sentiment, Priority (all existing services), plus keyword matching and sender-domain classification |
| Training data | **None** — there is nothing to train |
| Served via | `POST /api/v1/routing/predict` |

## Why Not a New ML Model

Compared, before implementation, against four alternatives (deterministic
rules / weighted decision engine / ML classifier / hybrid): given that
three of the four inputs Routing would need to learn from (Category,
Priority, Intent) are themselves trained on synthetic labels, and the
fourth (Sentiment) has no ground truth at all, a sixth model trained to
combine them would be learning to imitate a rule engine's own heuristics at
best, or amplifying four separate sources of label noise at worst — the
same reasoning `docs/model_cards/sentiment.md` already applied to rejecting
"train a classifier on VADER's own pseudo-labels." The PRD's own §9.1 names
Department Routing's baseline model as "Rule-based logic" (production:
"Hybrid: Rules + ML") — this phase implements the baseline, consistent with
the PRD's own build order, not a deviation from it.

## Composed Signal Summary

See `docs/routing_signal_reliability.md` for the full per-signal table.
Short version: **Spam** is the only signal with real, measured evidence
(99.44% recall); **Category/Priority/Intent** are pipeline-validated only
(synthetic Enron labels); **Sentiment** has no ground truth at all
(zero-shot VADER); **Keywords** and **sender domain** are deterministic but
never calibrated probabilities. The rule engine's precedence and the
unreliable-Intent policy (`docs/routing_conflict_resolution.md`) exist
specifically to prevent this evidence-quality gradient from being flattened
into "the model said so."

## Known Issue: Empty/Degenerate Input Can Be Classified as Spam

Discovered during Phase 8 testing, not previously documented: the real
trained spam model (threshold 0.06, calibrated for FR-11's >99% recall
target) classifies a fully empty subject+body as spam
(`SpamService().classify("", "")` → `is_spam=True, confidence=0.94` — this
is `SpamService`'s own reported field, unrelated to the routing-confidence
fix below). Consequence for routing: an empty email is quarantined
(`action=quarantine, department=None`) rather than routed to General. This
is a real, disclosed characteristic of an aggressively recall-tuned
upstream classifier on a degenerate input — not a routing bug, and not a
dropped email (quarantine is a defined, logged outcome, satisfying RULE
10). See `docs/error_analysis_routing.md`.

## Known Issue (FIXED): Quarantine Confidence Field Mismatch

Found by the Phase 8 engineering review, fixed the same day: `RoutingService`
was sourcing the quarantine decision's `confidence` — both
`RoutingPredictionResponse.confidence` and `supporting_signals.spam.
confidence` — from `SpamService`'s `confidence` field (the argmax-label
confidence) instead of `spam_score` (the spam-class probability that
actually drives `is_spam`). Because the real threshold (0.06) is far below
0.5, the argmax label is routinely still "ham" even when `is_spam=True`,
so the reported confidence was routinely the model's confidence in *not*
being spam — e.g. a real `spam_score` of 0.1859 (barely over threshold)
paired with a reported `confidence` of 0.8141. Every quarantine decision's
persisted and returned confidence was affected. Fixed in
`app/services/routing_service.py:route()`; regression-tested in
`tests/test_routing_service.py::
test_route_quarantine_confidence_uses_spam_score_not_argmax_confidence`.

## Intended Use

- **Pipeline development and architecture validation** — proves the
  five-service composition → rule evaluation → explainable decision →
  audit-logging → feedback path works end-to-end.
- **Provisional/prototype routing decisions only.** Given Category's
  synthetic labels, Priority's synthetic labels, Intent's synthetic labels
  (two classes additionally unreliable), and Sentiment's complete lack of
  ground truth, a routing decision should be treated as a *candidate*
  requiring human confirmation for anything but the clearest, highest-
  confidence, non-high-impact cases — which is exactly why
  `requires_human_review` exists as an independent field from `action`
  (see `docs/routing_conflict_resolution.md`).
- **Not intended to make unattended high-impact decisions** (financial,
  legal, HR) — `HIGH_IMPACT_DEPARTMENTS` mandates human review regardless
  of confidence, by design.

## Evaluation

**No routing accuracy/precision/recall/F1 is reported, because no
human-labelled routing-outcome dataset exists** (RULE 16 — never fabricate
evaluation metrics). What was measured instead, classified honestly as
**ENGINEERING VALIDATION**, not **PRODUCTION ML VALIDATION** (Phase 8
brief §30):

| Evaluation type | What was checked | Where |
|---|---|---|
| Rule coverage | Every one of the 12 documented rules has at least one direct unit test | `tests/test_routing_rules.py` |
| Precedence / conflict resolution | Spam gate pre-empts everything; high-impact departments always flag review; escalation/refund policy behaves as documented | `tests/test_routing_rules.py` |
| Tie-breaking determinism | Category ties and keyword-vote ties resolve identically on repeated runs | `tests/test_routing_rules.py`, `tests/test_routing_keyword_matcher.py` |
| Failure isolation | Routing never crashes when 1-of-5 or 5-of-5 upstream services fail | `tests/test_routing_service.py` |
| Integration correctness | Real trained artifacts compose into a structurally valid, schema-conformant response | `tests/test_routing_endpoint.py` |
| Database persistence | Every decision's full reasoning is durably logged | `tests/test_routing_prediction_log.py` |
| Adversarial robustness | Empty/huge/malformed/unicode/HTML/prompt-injection-style input never crashes or hangs | `tests/test_routing_security.py` |
| Manual gold-set review | 20 hand-written representative emails, expected department/action compared against actual output | `docs/error_analysis_routing.md` — sampling method and limitations disclosed there, not claimed statistically representative |

## Limitations

1. **Inherits every upstream module's data-quality limitation** — see
   `docs/routing_signal_reliability.md`. Routing cannot be more trustworthy
   than the weakest signal it depends on for a given decision.
2. **No routing-outcome ground truth exists** — "Routing Accuracy > 92%"
   (PRD §14.1) is not evaluated and cannot be, honestly, until a real
   routing-outcome dataset exists.
3. **Thresholds are engineering heuristics**, not calibrated — see
   `docs/routing_rules.md`'s HEURISTIC labels. Expected to move once real
   outcome data exists to calibrate against.
4. **No agent-level routing** (FR-42) — department only; see
   `docs/routing_taxonomy.md`.
5. **No DB-backed configurable rules** (FR-39's literal API) — code-defined
   rules only; see `docs/routing_rules.md`.
6. **Empty input can trigger spam quarantine** — see "Known Issue" above.

## Production Readiness Level

Per the Phase 8 brief's 4-level scale — assigned honestly, not
automatically claimed at the top:

| Level | Criteria | Met? |
|---|---|---|
| 1. Pipeline complete | Composition, rules, API, DB, feedback all working end-to-end | **Yes** |
| 2. Routing logic validated | Rules behave deterministically as designed, verified by direct unit tests + a manual qualitative review | **Yes** |
| 3. PRD compliant | Routing Accuracy > 92% (§14.1) measured against real ground truth; FR-42 agent routing implemented; FR-39's literal configurable-rules API implemented | **No** — none of the three sub-conditions are met |
| 4. Production ready | All of the above, plus the Spam domain-transfer gap resolved (`docs/error_analysis_routing.md`) and every upstream module's own data-quality gap closed | **No** |

**This phase reaches Level 2.** Routing's own logic — precedence, tie-
breaking, the unreliable-Intent policy, failure isolation, fallback — is
implemented and verified to behave exactly as documented. It is not Level 3
or 4 because (a) no routing-outcome ground truth exists to measure PRD
compliance against, and (b) this phase's own qualitative evaluation
surfaced a real, high-priority upstream gap (Spam's domain-transfer
precision issue) that materially limits how much of routing's logic even
gets exercised on ordinary business email today.

## Path to a PRD-Compliant, Production-Validated Routing Engine (Not Implemented — Blocked on Data + Auth)

1. Real annotation of a routing-outcome dataset (expected department/action
   for a representative email sample) — see `docs/ml_data_maturity_roadmap.md`.
2. Real annotation of Category/Priority/Intent (already blocking those
   modules independently — see their own data audits) — routing cannot
   exceed the trustworthiness of its inputs.
3. Real auth + multi-tenancy landing (blocks FR-39's literal
   `/routing/rules` CRUD API and FR-42's agent roster).
4. Only then does re-calibrating the HEURISTIC thresholds in
   `app/routing/rules.py` against real outcome data become a meaningful
   exercise, and only then do the PRD's routing-accuracy targets become a
   meaningful bar.
