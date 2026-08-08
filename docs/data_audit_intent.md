# Intent Detection — Data Audit and Data Strategy Decision

**Status: gates all of Phase 7B.** Nothing in `docs/model_cards/intent.md` or
`docs/architecture_intent.md` should be read as PRD-compliant until the
"Data Strategy Decision" section below is resolved by real annotation
(§4, Option A). Same pattern as `docs/data_audit_priority.md` /
`docs/data_audit_categorization.md` / `docs/data_audit_sentiment.md`.

## 1. PRD Requirements (FR-33 to FR-36, PRD §5 Module 7)

| ID | Requirement |
|---|---|
| FR-33 | Identify primary intent: Complaint / Inquiry / Request / Feedback / Escalation / Order / Cancel / Refund / Schedule (9 classes) |
| FR-34 | Support multi-intent detection per email |
| FR-35 | Extract key entities: order IDs, dates, amounts, product names, person names |
| FR-36 | Intent used as a signal for routing (Phase 8) and auto-reply generation (a later phase) |

**Multi-label, confirmed directly by the PRD, not inferred**: §8.2's data
requirements state *"Multi-label allowed (one email can have Complaint +
Refund intent)"* — this resolves Step 6 of this phase's own instructions
without requiring a judgment call.

Data requirement (PRD §8.1/8.2): *"Intent | **Custom annotation required** |
5,000+ | Internal labeling | Internal"*; minimum 500 examples per class × 9
classes = 4,500. Suggested models: classical = **TF-IDF + Multi-label LR**,
advanced = **fine-tuned BERT** (§ model comparison table). Eval metric:
**F1-macro**, target `>0.80` (metrics table) vs. `>0.78` (Definition of
Done) — the PRD states both, both recorded here rather than one silently
chosen.

## 2. Data Audit — what actually exists today

| Check | Finding |
|---|---|
| `Glob **/*intent*` under `data/` | No files found. |
| `backend/app/data_ingestion/dataset_registry.py` (prior to this phase) | Zero registered datasets carry an intent label. |
| Enron, SpamAssassin, Amazon, SMS corpora | None carry any intent-style label. |
| PRD-named proxy dataset | **None exists.** Unlike Sentiment (Amazon/Twitter suggested), Priority/Category (a synthetic-bootstrap path was at least plausible against Enron), or Summarization (CNN/DailyMail suggested), the PRD names no candidate dataset for Intent at all — it goes directly to "Custom annotation required." |

**Finding: zero intent-labelled emails exist in this repository, and the
PRD's own "Custom annotation required" claim is independently verified
here, not assumed.** No off-the-shelf, zero-shot scorer analogous to VADER
(Sentiment's resolution) exists for business-intent classification —
intent categories are domain-specific business concepts, not a general
linguistic property a pre-built lexicon could score.

### Data Readiness Report

| Dataset | Rows | Labels | Domain match | Trust level | Suitability |
|---|---|---|---|---|---|
| Intent-labelled (human) | **0** | N/A | N/A | N/A | **Not usable — does not exist** |
| Enron corpus (raw text, no intent label) | ~500K available | None | **Low-to-medium, and specifically WORSE for this module than priority/category** — see §3 | Supplementary source | Usable only as the text source for a synthetic bootstrap (§4) |
| **`intent_synthetic_v1`** (generated this phase) | see `run_metadata.json` | 9-class multi-label, keyword-heuristic-derived | Low (see §3) | `synthetic_bootstrap` | **Pipeline development / classical-baseline-comparison only — see §4.** Not usable for any PRD-compliance claim. |

## 3. A Domain-Match Problem Specific to Intent (Worse Than Priority/Category's)

Priority and Categorization's synthetic bootstraps already disclose Enron's
2001-2002 domain shift as a limitation, but Enron's B2B corporate
correspondence is at least topically adjacent to priority/urgency and
department-routing concepts (legal, billing, IT, HR are all things a large
corporation's internal email naturally discusses). **Several of FR-33's 9
intents are consumer-service concepts that essentially do not occur in
Enron's internal energy-trading correspondence at all**: "Order" (product
purchase), "Refund," and "Cancel" (subscription/service cancellation) are
consumer-transactional intents; Enron in 2001 was not fielding customer
refund requests in its internal mail archive. This means, unlike priority/
category, the keyword-heuristic bootstrap for these three classes will
likely have very few genuine hits in Enron text at all — verified
empirically in `run_metadata.json`'s per-class label distribution once
generated (see below), not assumed in advance.

## 4. Data Strategy Decision

Same four-option structure as priority/category/sentiment's data audits;
not repeated in full here — see those documents for the general reasoning.
**Decision: Option D (synthetic bootstrap), per your explicit confirmation**
— real Enron text + keyword-heuristic multi-label pseudo-labels (with
injected per-label noise, mirroring `generate_synthetic_category_dataset.py`
exactly), used to train a TF-IDF + multi-label classical classifier (PRD's
own suggested classical baseline), served, and disclosed as
`SYNTHETIC`/`PIPELINE VALIDATION ONLY` throughout.

**Why this differs from Sentiment's resolution**: Sentiment had a genuine
zero-shot alternative (VADER) that required no label fabrication at all,
which is why this phase chose not to serve a classifier trained on VADER's
own pseudo-labels. No such alternative exists for Intent — there is no
pre-built, off-the-shelf scorer for domain-specific business-intent
categories. Given that, the priority/category precedent (train on a
disclosed synthetic bootstrap, serve it, mark it clearly) is the correct
one to follow here, and is what your confirmed decision selected.

**A pure rule-based baseline (this phase's alternative option, not chosen)**
was considered and rejected as the *served* path specifically because the
PRD's own suggested classical baseline is a trained classifier
("TF-IDF + Multi-label LR"), and the trained-on-synthetic-bootstrap pattern
is already an accepted, disclosed precedent in this exact codebase — a
rule-based-only baseline would be a *smaller* deliverable without a clear
reason to prefer it over the established pattern. The keyword lexicons
built for the bootstrap (`intent_keywords.py`) still exist and are
directly inspectable — nothing about the rule logic itself is hidden
inside the trained model.

### What this decision means concretely

Identical structure to priority/category's two-track plan: (1) pipeline/
architecture track (now) — full ingestion → keyword-heuristic bootstrap →
`IntentMLPipeline` → training → evaluation → serving → audit-logging →
feedback, proven mechanically, metrics disclosed as pipeline-validation
only; (2) PRD-compliant track (future, blocked on annotation budget) — the
same pipeline re-runs against real labels with zero architecture changes
once annotation happens (`docs/intent_labeling_strategy.md`).

**No metric produced in this phase will be described as satisfying FR-33
through FR-36's underlying business need, or the PRD's F1-macro target, in
any document in this repository.**

## 5. Feature/Leakage Note — Deliberately Different From Priority/Category

Priority and Categorization's keyword lexicons feed BOTH the synthetic
label generator AND the trained model's own `ContentFeatures`-based
keyword-count fields — a disclosed, structural leakage channel in both
those modules. **Intent's `intent_keywords.py` deliberately feeds ONLY the
label generator, not any model feature** — `IntentMLPipeline` is TF-IDF-only
(see `docs/architecture_intent.md` for why), so there is no equivalent
"keyword count IS a feature the model sees" leakage channel here. This was
a deliberate design choice made during this phase's repository audit
(Gate G-equivalent), not an oversight — it also avoids extending the
shared `ContentFeatures`/`MetadataFeatures` dataclasses a third time,
consistent with the lesson already carried forward from Phase 5's incident
and Phase 7A's Sentiment decision.

## 6. Leakage-Safe Split Design

Identical mechanism to priority/category: `GroupShuffleSplit` on
`sender_email`, verified zero sender overlap across train/val/test.
