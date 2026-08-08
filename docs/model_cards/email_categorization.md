# Model Card — Email Categorization (Baseline, SYNTHETIC Data)

> **THIS MODEL IS NOT PRD-COMPLIANT.** It is trained on
> `data/processed/category_synthetic_v1` — heuristically-labelled, not
> human-annotated. Every metric in this document is a **pipeline validation
> metric**, not evidence of real-world categorization quality. See
> `docs/data_audit_categorization.md` for the full data strategy decision
> and `docs/categorization_label_quality_report.md` for why this dataset is
> classified UNTRUSTWORTHY.

## Purpose / Intended Use / Non-Intended Use

- **Purpose**: prove the ingestion → feature engineering → multi-label
  training → multi-label evaluation → serving → audit-logging → feedback
  path works end-to-end for Module 4 (FR-21 to FR-24), the same role
  `priority_baseline.joblib` plays for Module 3.
- **Intended use**: pipeline development and architecture validation only.
- **Not intended for any real routing, triage, or category-based automation
  decision.** A false-negative category assignment (a Legal email routed
  as General) or a false-positive one (a routine email routed to Legal)
  are both live risks with this model — see "Error Analysis" below for
  measured evidence of both failure directions.

## Model Details

| Field | Value |
|---|---|
| Model type | Linear SVM (`sklearn.svm.LinearSVC`), probability-calibrated via `CalibratedClassifierCV`, wrapped `OneVsRestClassifier` (8 independent binary classifiers) |
| Features | TF-IDF (uni+bigram) + `ContentFeatures` (30 fields, incl. 7 category keyword counts) + `MetadataFeatures` (16 fields) — engineered features scaled via `EngineeredFeatureScaler`, TF-IDF left unscaled |
| Class weight | `"balanced"`, applied per binary sub-problem |
| Framework | scikit-learn 1.9 |
| Training script | `backend/scripts/train_category_model.py` |
| Artifact | `artifacts/category_baseline.joblib`, `artifacts/versions/category_{version}.joblib` |
| Current version | `svm-20260808-131201` |
| Training data | `data/processed/category_synthetic_v1` — **synthetic, see warning above** |
| Task type | Multi-label classification (FR-22, PRD §9.1) — NOT multiclass. See `docs/data_audit_categorization.md` §7. |
| Decision rule | Each of the 8 binary classifiers' own default threshold (0.5 on calibrated probability); a row with zero categories crossing threshold falls back to `["General"]` at the **service layer** (`CategoryService`), not the model — see "Probability & the General Fallback" below. |

## Why SVM, Over Logistic Regression and Naive Bayes

All three compared identically: same TF-IDF config, same engineered
features, One-vs-Rest wrapping, `class_weight="balanced"`, same
`category_synthetic_v1` split.

| Model | F1-micro | F1-macro | Hamming Loss | Precision-micro | Recall-micro | Subset Accuracy |
|---|---|---|---|---|---|---|
| **SVM (chosen)** | **0.7023** | **0.6768** | **0.1132** | 0.8459 | 0.6004 | **0.4528** |
| Logistic Regression | 0.6817 | 0.6540 | 0.1503 | 0.6443 | **0.7238** | 0.4187 |
| Naive Bayes | 0.4113 | 0.3380 | 0.2662 | 0.4047 | 0.4182 | 0.2218 |

**SVM wins on the PRD's own named primary metric (F1-micro) and secondary
metric (Hamming loss, PRD §14.1) simultaneously** — not a split decision
requiring a tiebreaker. Logistic Regression has meaningfully higher recall
(0.7238 vs. 0.6004) but noticeably lower precision (0.6443 vs. 0.8459),
netting a worse F1-micro; whether that tradeoff is preferable depends on a
business cost model for false-positive vs. false-negative category
assignments that doesn't exist yet (unlike spam, where FR-11 explicitly
states the cost asymmetry). Naive Bayes is not competitive on any axis —
consistent with the same weak-baseline pattern already documented for it in
`docs/model_cards/priority_classification.md`.

**Subset accuracy (0.4528) is a much stricter bar than any of the above** —
it requires all 8 per-email label decisions to be simultaneously correct.
Reported because it's the honest answer to "how often does the model get
the *entire* email completely right," not because it's the metric to
optimize (PRD names F1-micro/Hamming loss for a reason: they don't demand
perfection on every one of 8 independent decisions to register partial
credit).

**Latency/model size**: not the deciding factor at this data scale, same
finding as both other model cards.

## Probability & the General Fallback

Unlike priority (a single 4-way argmax) or spam (one threshold on one
probability), categorization has **8 independent binary decisions per
email**, and it is a legitimate model outcome for all 8 to say "no" — every
category's own classifier can independently conclude it doesn't apply. FR-21
names General as the taxonomy's catch-all specifically for this situation,
and the synthetic dataset's own label generator assigns `["General"]`
whenever no other category's keyword threshold is met (see
`docs/data_audit_categorization.md` §3) — so the model has genuinely been
trained to predict General as a normal 8th label, not just as an API-layer
default.

As a safety net for the residual case where inference produces zero labels
despite that training signal (verified structurally impossible in training
data — `tests/test_category_dataset.py::test_every_row_has_at_least_one_category`
— but not something the served model can be mathematically guaranteed to
reproduce on novel input), `CategoryService` assigns `["General"]` using the
model's own (sub-threshold) General score as the reported confidence. This
mirrors `SpamService` owning its threshold policy rather than embedding it
in the model — see that service's module docstring.

## Class Imbalance & Label Co-occurrence

Label distribution (`data/processed/category_synthetic_v1/run_metadata.json`,
full 10,000-row dataset): Legal 36.5% / General 32.8% / Support 27.5% /
Marketing 20.0% / Billing 15.4% / Sales 13.6% / HR 11.5% / IT 11.3%. Average
1.686 labels/email — see
`docs/categorization_label_quality_report.md` §10 for why this specific
distribution is an artifact of Enron's vocabulary, not a real-world
forecast. No category collapsed to a near-zero sample size the way
Priority's Critical class did (min. support in the test split: IT at 105
examples) — multi-label's structural advantage here is that even a
"rare" category still gets its own dedicated binary classifier trained on
every row, not a thin slice of a shared softmax.

**SMOTE was not attempted**, for the identical reason documented in
`docs/model_cards/priority_classification.md`'s "Class Imbalance" section:
interpolating between sparse TF-IDF vectors produces synthetic vectors
corresponding to no real, coherent text. `class_weight="balanced"` (applied
per binary sub-problem inside `OneVsRestClassifier`) is the appropriate
lever here, same reasoning, not re-litigated.

## Error Analysis

Per-category precision/recall/F1 (SVM, test set, n=879):

| Category | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| Support | 0.906 | 0.707 | 0.795 | 246 |
| Legal | 0.806 | 0.744 | 0.774 | 352 |
| HR | 0.960 | 0.564 | 0.711 | 172 |
| IT | 0.967 | 0.552 | 0.703 | 105 |
| Marketing | 0.956 | 0.532 | 0.684 | 203 |
| Billing | 0.882 | 0.484 | 0.625 | 124 |
| General | 0.683 | 0.563 | 0.617 | 245 |
| Sales | 0.857 | 0.359 | 0.506 | 117 |

**The dominant, consistent pattern across every category except General:
precision is high (0.81-0.97), recall is the weak axis (0.36-0.74).** This
is a genuinely useful, specific finding, not a vague "needs more data":
the model is conservative — when it does assign a category, it's usually
right, but it silently under-assigns across the board. HR, IT, and Marketing
in particular combine near-0.96 precision with barely-above-half recall.
**Practical implication if this were ever wired to real routing (it is
not — see "Intended Use"): the likely failure mode is under-categorization
(emails that should get a specific department tag stay in General or get
fewer tags than they should), not false alarms.** This is a different, and
arguably safer, failure direction than the opposite (aggressively
over-tagging), but it means a downstream consumer relying on "if Legal
isn't tagged, it isn't Legal" would be wrong more often than "if Legal is
tagged, it is Legal."

**A concrete, hand-checked failure case** (not cherry-picked for being
representative — included because it's a genuine, surprising miss found
while sanity-checking the served endpoint, and reporting only the successes
would be exactly the kind of selective disclosure this phase's instructions
prohibit): the email *"Hope everyone has a great weekend, see you Monday!"*
(subject: "Happy Friday") was classified **Legal at 0.817 confidence** — a
clear-cut General case with zero Legal keyword matches. `all_scores` showed
General itself at only 0.08. This is very likely the TF-IDF component
picking up on Enron-corpus stylistic patterns correlated with Legal's
33.6%-prevalence training signal rather than any genuine legal content, not
a keyword-matching bug (the keyword features for this input are all zero,
confirmed by direct inspection) — i.e., a base-rate/prior effect from
Legal's high prevalence outweighing weak textual evidence, on an input
short enough to give TF-IDF little to work with. This is exactly the kind
of failure mode real annotation (with all its more genuinely varied
negative examples) would surface and correct, and heuristic synthetic
labels cannot.

**Per-label confusion matrices** (format `[[TN, FP], [FN, TP]]`, test set):

| Category | TN | FP | FN | TP |
|---|---|---|---|---|
| Support | 615 | 18 | 72 | 174 |
| Sales | 755 | 7 | 75 | 42 |
| Billing | 747 | 8 | 64 | 60 |
| Legal | 464 | 63 | 90 | 262 |
| HR | 703 | 4 | 75 | 97 |
| IT | 772 | 2 | 47 | 58 |
| Marketing | 671 | 5 | 95 | 108 |
| General | 570 | 64 | 107 | 138 |

Legal and General are the only two categories with a non-trivial false-
positive count (63 and 64 respectively) — consistent with both being the
two most prevalent labels in training (36.5% and 32.8%), and with the
"Happy Friday" example above being a Legal false positive specifically.
Every other category's false-positive count is in the single digits,
reinforcing the "precision is high, recall is the weak axis" finding as the
dominant, not incidental, pattern.

**What this analysis does NOT show**: like priority's model card's
equivalent section, it cannot say anything about real-world category
confusion patterns (e.g., "does the model confuse Sales inquiries with
Support requests the way a human triager would") because there are no real
labels to compare against. The recall-weak/precision-strong pattern above
is about how *this specific heuristic-labelled dataset* interacts with a
One-vs-Rest SVM, which is exactly what pipeline validation is supposed to
surface (`docs/data_audit_categorization.md` §4).

## Calibration

**Not separately re-verified for categorization** the way
`check_priority_calibration.py` does for priority — flagged as a known gap
(see architecture doc), not silently skipped. `CalibratedClassifierCV` is
structurally present (SVM requires it for `predict_proba` at all, same as
spam and priority's SVM path), but multi-label calibration verification
needs a per-category reliability analysis (8 separate calibration curves,
not one), which is meaningfully more work than the single-curve check
priority's script performs and was not built this phase. This gap matters
concretely: FR-24 requires a confidence score per category, and this model
card cannot yet say whether "0.7 confidence" means the same thing across
all 8 categories or is systematically off in one direction for some of
them (the precision/recall asymmetry in "Error Analysis" above is a hint
in that direction, not a substitute for an actual calibration measurement).

## Intended Use

- Pipeline development and architecture validation only — see the warning
  banner and "Purpose" above.

## Limitations

1. **Trained on synthetic, heuristically-generated multi-label tags — no
   human ever annotated these emails.** Primary limitation, supersedes all
   others; see `docs/data_audit_categorization.md` and
   `docs/categorization_label_quality_report.md`.
2. **F1-micro (0.7023) is below the PRD's own 0.80 target** (PRD §14.1) —
   reported honestly, not tuned to clear the bar (no threshold or
   hyperparameter search was performed specifically to push this number up).
3. **Recall is the dominant weakness** (0.36-0.74 across 7 of 8 categories)
   — see "Error Analysis." Not yet root-caused beyond the class-weight
   lever already applied; a threshold sweep per category (analogous to
   spam's single-threshold calibration) is the next cheapest thing to try,
   not yet done this phase.
4. **Per-category probability calibration is not verified** — see
   "Calibration" above. FR-24's confidence scores should not yet be treated
   as comparable across categories.
5. **FR-23 (per-organization configurable taxonomy) is entirely
   unimplemented** — the 8 labels are hard-coded; no multi-tenant config
   store exists anywhere in this codebase. See
   `docs/data_audit_categorization.md` §1.
6. **Enron-sourced text is 2001-2002 corporate email** — same domain-shift
   caveat as every other Enron-derived dataset in this repository.
7. **Sender-history / organizational-routing-history signals are not used**
   — no persistent sender profile store exists, same gap already documented
   for priority's FR-17.
8. **Thread lineage is not tracked** — the "a reply inherits its thread's
   categories" rule (`docs/data_audit_categorization.md` §3) is stated for
   the human annotation process and cannot yet be enforced automatically,
   same limitation as priority's equivalent thread rule.

## Path to a PRD-Compliant Model (Not Implemented — Blocked on Annotation)

Identical structure to `docs/model_cards/priority_classification.md`'s
equivalent section:

1. Real annotation effort per `docs/annotation_guidelines_categorization.md`
   — 3 annotators, per-category Kappa ≥ 0.70 (engineering recommendation,
   not a PRD-stated number for this module — see that document §8), on real
   (anonymized) enterprise email, not more Enron.
2. Re-run this exact pipeline (`train_category_model.py`,
   `CategoryMLPipeline`, `Trainer`, `ArtifactManager`) against the real
   labels — zero architecture changes required, by design (the entire
   point of building the pipeline now, same as priority's).
3. Only then does the PRD's F1-micro > 0.80 target become a meaningful bar.
4. Once real data exists, revisit per-category calibration (currently
   unmeasured, see "Calibration") and the recall-weak pattern above — worth
   determining whether it's a synthetic-label artifact (heuristic labels
   under-representing genuine positive cases the model could otherwise
   learn) or a genuine model/feature limitation, which is not answerable
   from synthetic data alone.
