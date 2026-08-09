# ML Data Maturity Roadmap (Track B)

**This document is a data-quality improvement roadmap, not a Phase 8
implementation task list.** Phase 8 (Track A, see `docs/architecture_
routing.md`) was built using the current available modules while respecting
their reliability — it was deliberately **not** blocked by, and does
**not** fix, any of the gaps below. Synthetic-labelled datasets remain
suitable for engineering/prototype validation but must be replaced or
supplemented with trustworthy human-labelled data before making production
ML performance claims about any of the modules below.

## Priority Classification (Phase 4)

| | |
|---|---|
| Current dataset | `priority_synthetic_v1` |
| Current label source | Heuristic (keyword-rule bootstrap) applied to real Enron email text |
| Current domain | Real email, but Enron's internal B2B energy-trading correspondence, not necessarily the deploying org's traffic |
| Current evidence | Pipeline-validated only; see `docs/data_audit_priority.md` |
| Failure modes | No specific class-level failure root-caused (unlike Intent's Escalation/Refund) — general synthetic-label caveat applies uniformly across all 4 classes |
| Required future dataset | 10,000+ real emails, human-annotated, 3 annotators, Cohen's Kappa ≥ 0.70 (PRD §8.2 — this is the PRD's own stated minimum, not invented here) |
| Recommended replacement dataset | `TO BE RESEARCHED` — no specific external dataset has been evaluated against this taxonomy |
| Annotation requirements | See PRD §8.2 directly; full process spec not yet written (unlike Categorization, which has `docs/annotation_guidelines_categorization.md`) — **a gap this roadmap surfaces, not previously documented** |
| Retraining requirement | Re-run `train_priority_model.py` / `PriorityMLPipeline` unchanged against real labels — zero architecture changes required by design |
| Evaluation requirement | F1-macro > 0.85 for High/Critical (PRD §14.1) becomes meaningful only once evaluated against real labels |
| Blocks production readiness? | **Yes** |

## Email Categorization (Phase 5)

| | |
|---|---|
| Current dataset | `category_synthetic_v1` |
| Current label source | Heuristic (keyword-rule bootstrap) applied to real Enron email text |
| Current domain | Real email, Enron B2B correspondence |
| Current evidence | Pipeline-validated only; see `docs/data_audit_categorization.md` |
| Failure modes | Per-category probability calibration unverified (unlike Spam/Priority); see `docs/model_cards/email_categorization.md` "Calibration" |
| Required future dataset | 8,000+ emails, per-category Kappa ≥ 0.70 (engineering-recommended target, no PRD-specified minimum) |
| Recommended replacement dataset | `TO BE RESEARCHED` |
| Annotation requirements | Already fully specified — `docs/annotation_guidelines_categorization.md` |
| Retraining requirement | Re-run `train_category_model.py` / `CategoryMLPipeline` unchanged |
| Evaluation requirement | F1-micro > 0.80 (PRD §14.1), plus the calibration check never yet performed |
| Blocks production readiness? | **Yes** — additionally blocks Routing's department-selection accuracy, since Routing's taxonomy IS Category's label space (`docs/routing_taxonomy.md`) |

## Intent Detection (Phase 7B)

| | |
|---|---|
| Current dataset | `intent_synthetic_v1` |
| Current label source | Heuristic (keyword-rule bootstrap) applied to real Enron email text |
| Current domain | Real email, but Order/Refund/Cancel are consumer-transactional concepts largely absent from Enron's B2B corpus — worse domain mismatch than Priority/Category |
| Current evidence | Pipeline-validated only; see `docs/data_audit_intent.md` |
| Failure modes | **Escalation**: demonstrated unreliable, not just unvalidated — fires on unrelated text AND misses its own target case (`docs/error_analysis_intent.md`). **Refund**: F1 = 0.0 on its own test set. |
| Required future dataset | 5,000+ emails minimum, 3 annotators, per-class Kappa ≥ 0.65 (`docs/data_audit_intent.md` §4 / `docs/intent_labeling_strategy.md`) |
| Recommended replacement dataset | `TO BE RESEARCHED` — specifically needs consumer-transactional email content (Order/Refund/Cancel), which Enron structurally lacks; a second, domain-matched source may be needed in addition to any annotated Enron subset |
| Annotation requirements | Fully specified — `docs/intent_labeling_strategy.md` |
| Retraining requirement | Re-run `train_intent_model.py` / `IntentMLPipeline` unchanged; **additionally** re-evaluate whether Escalation/Refund's poor performance was a data-quality artifact (current evidence strongly suggests this) or a genuinely harder class even with real labels — current evidence cannot distinguish these |
| Evaluation requirement | F1-macro > 0.80 (PRD §14.1) |
| Blocks production readiness? | **Yes** — additionally blocks Routing's unreliable-Intent policy from ever being relaxed (`docs/routing_conflict_resolution.md`) |

## Sentiment Analysis (Phase 7A)

| | |
|---|---|
| Current dataset | **None** — VADER is zero-shot, never trained or fit to anything |
| Current label source | N/A |
| Current domain | N/A — general-purpose lexicon, never adapted to email or any specific organization |
| Current evidence | **No ground truth exists to validate against, on any domain** (`docs/data_audit_sentiment.md`) — weaker evidentiary footing than any synthetic-labelled module |
| Failure modes | Cannot detect sarcasm, indirect negativity, politeness-masked complaints — 5/14 (36%) on a 14-example qualitative set (`docs/error_analysis_sentiment.md`) |
| Required future dataset | Full annotation process specified but not started — `docs/annotation_guidelines_sentiment.md` |
| Recommended replacement dataset | `TO BE RESEARCHED` |
| Annotation requirements | Fully specified — `docs/annotation_guidelines_sentiment.md` |
| Retraining requirement | A comparison classifier already exists (`train_sentiment_model.py` → `artifacts/sentiment_comparison.joblib`) but is deliberately not served, because training on VADER's own pseudo-labels can only imitate VADER, not improve on it (`docs/model_cards/sentiment.md` "Model Selection") — **real human-labelled data would justify revisiting this decision**, not just retraining the same comparison model |
| Evaluation requirement | F1-weighted > 0.82 (PRD §14.1) — currently not measurable at all |
| Blocks production readiness? | **Yes** — additionally blocks Routing from ever treating Sentiment as more than a borderline-confidence modifier |

## Spam Detection (Phase 3) — Newly Surfaced by Phase 8's Composition

| | |
|---|---|
| Current dataset | Real, labelled: SpamAssassin, SMS Spam Collection, Amazon Polarity |
| Current label source | Real (dataset-native labels, not synthetic) |
| Current domain | Spam/ham corpora — promotional email, SMS spam, product reviews |
| Current evidence | **Real and strong on its own evaluation domain**: 99.44% recall / 91.33% precision at threshold 0.06 (`docs/model_cards/spam_detection.md`) |
| Failure modes — **newly discovered during Phase 8's qualitative evaluation** | The `0.06` threshold, chosen to maximize recall on the spam/ham corpora above, produces a high false-positive rate on ordinary short business-email text unlike its training domain — verified: a sales pricing inquiry (spam_score 0.39), a billing refund request (0.19), an HR complaint (0.10), and an IT access request (0.14) all scored above threshold. See `docs/error_analysis_routing.md` "Headline Finding." **This was not visible before Phase 8** because no prior module composed Spam's output with ordinary Enron-style business text at decision time — Priority/Category/Intent all consume Enron text independently, but none of them gate on Spam's output the way Routing does. |
| Required future dataset | A held-out evaluation set of real, ordinary business email (ideally the SAME domain Priority/Category/Intent already use — Enron, or the deploying org's own traffic) labelled spam/ham, to measure Spam's actual precision **outside** its original training domain |
| Recommended replacement/supplement dataset | `TO BE RESEARCHED` — Enron itself is a candidate (already licensed and in use for 3 other modules), but Enron has no native spam/ham labels and would need either heuristic bootstrapping (same synthetic-label caveat as Priority/Category/Intent) or manual spot-check annotation |
| Annotation requirements | Not yet specified — this is a new finding, not a pre-existing tracked gap |
| Retraining requirement | Threshold recalibration (not necessarily a full retrain) against the new out-of-domain holdout, once it exists — changing `0.06` without in-domain validation data risks silently reducing the recall Phase 3's FR-11 target depends on |
| Evaluation requirement | Measure precision specifically on ordinary business email, separately from the existing recall/precision numbers (which remain valid and should not be re-stated or replaced, only supplemented) |
| Blocks production readiness? | **Yes, and specifically blocks Routing** — `R-SPAM-GATE` pre-empts all department routing, so this gap has an outsized practical effect on Routing's usefulness today, disproportionate to Spam's otherwise-strongest-evidence status in this system |

## Routing-Specific Gaps (Phase 8, New)

These are not upstream-model data gaps — they are Phase 8's own scope
boundaries, tracked here per the Phase 8 brief's requirement that Track B
cover the full picture, not just the four inherited ML modules.

| Gap | Current state | What's needed | Blocks production readiness? |
|---|---|---|---|
| Routing-outcome ground truth | None — `docs/error_analysis_routing.md`'s 20-example set is qualitative only | A real, human-annotated sample of (email → correct department/action) pairs, sized and sampled per a documented methodology (PRD's own suggested 100–500 range, §"Manual Routing Gold Set") | **Yes** — "Routing Accuracy > 92%" (PRD §14.1) cannot be measured without this |
| DB-backed, auth-protected `/routing/rules` CRUD (FR-39 literal API) | Rules are versioned code (`docs/routing_rules.md`) | Real auth + multi-tenancy (blocked since Phase 1, `docs/architecture.md`) | No — code-defined rules are a legitimate, documented, safer interim state |
| Agent-level routing (FR-42) | Department only, no `agent_id` | A `users`/`agents` table and assignment logic — doesn't exist anywhere in this codebase | No — department-level routing is PRD-compliant for FR-37's "and/or agent" wording; agent assignment is an additive future capability |
| Sender history (frequency, prior corrections, last seen) | Does not exist | New persistence, minimal schema, only if a future phase's requirements actually need it | No — not currently used by any rule |
| FR-41 automatic rule-weight adjustment from feedback | Feedback captured (JSONL), never auto-applied | A validated, human-reviewed promotion pipeline from feedback → threshold/rule change — deliberately not built this phase (see `docs/routing_conflict_resolution.md` and every other module's identical feedback-capture-only stance) | No — manual, reviewed threshold changes remain possible without this automation |

## Summary Statement

**Synthetic-labelled datasets (Priority, Category, Intent) are currently
suitable for engineering/prototype validation but must be replaced or
supplemented with trustworthy human-labelled data before making production
ML performance claims.** Sentiment has no ground truth of any kind and
carries the weakest footing of the four inherited modules. Spam — this
system's one real, validated signal — was newly found during Phase 8 to
have an undocumented precision gap outside its training domain, with an
outsized practical impact on Routing specifically, since it gates first.
None of these gaps blocked Phase 8's engineering implementation (RULE 6);
all of them block Routing (and every module that depends on it) from being
described as production-ready (see `docs/model_cards/routing.md`
"Production Readiness Level").
