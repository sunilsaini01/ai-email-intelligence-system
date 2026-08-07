# Model Card — Priority Classification (Baseline, SYNTHETIC Data)

> **THIS MODEL IS NOT PRD-COMPLIANT.** It is trained on `data/processed/priority_synthetic_v1`
> — heuristically-labelled, not human-annotated. Every metric in this document
> is a **pipeline validation metric**, not evidence of real-world priority
> classification quality. See `docs/data_audit_priority.md` for the full data
> strategy decision and what must change before this claim can be revisited.

## Model Details

| Field | Value |
|---|---|
| Model type | Logistic Regression (`sklearn.linear_model.LogisticRegression`, multinomial, `solver="saga"`) |
| Features | TF-IDF (uni+bigram) + `ContentFeatures` (23 fields incl. urgency/escalation/SLA keyword counts) + `MetadataFeatures` (16 fields incl. hour-of-day, sender domain type) — engineered features scaled via `EngineeredFeatureScaler`, TF-IDF left unscaled |
| Class weight | `"balanced"` — confirmed better than unweighted by direct comparison, see "Class Imbalance" below |
| Framework | scikit-learn 1.9 |
| Training script | `backend/scripts/train_priority_model.py` |
| Artifact | `artifacts/priority_baseline.joblib`, `artifacts/versions/priority_{version}.joblib` |
| Current version | `logistic_regression-20260807-195520` |
| Training data | `data/processed/priority_synthetic_v1` — **synthetic, see warning above** |

## Why Logistic Regression, Over SVM and Naive Bayes

| Model | Macro F1 | Accuracy | Critical/High F1 | Critical/High Recall | Critical F1 (alone) |
|---|---|---|---|---|---|
| **Logistic Regression (chosen)** | **0.4712** | 0.6633 | **0.2667** | **0.3252** | 0.0488 |
| SVM (calibrated) | 0.3609 | **0.6780** | 0.0538 | 0.0298 | ~0 |
| Naive Bayes | 0.2970 | 0.5995 | 0.0000 | 0.0000 | 0.0000 |

**If model selection had been done on accuracy alone, SVM would have been
chosen — and it would have been the wrong choice.** SVM has the *highest*
accuracy (0.678) of the three, but a Critical/High recall of 0.0298 — it
correctly identifies essentially none of the emails that operationally
matter most. This is the exact trap PRD §14.1's own reasoning about spam
recall vs. accuracy warns about, playing out again here: a model that's
right most of the time by being right about the majority class (Low/Medium,
~90% of the data) can still be useless for the 10% of decisions that carry
real business consequence. Naive Bayes shows the same pattern more severely
— 0.0 F1 on both Critical and High, meaning it never once correctly
identifies either class in the test set.

Logistic Regression is chosen because it's the only baseline with
non-trivial Critical/High performance, not because 0.2667 F1 is good in any
absolute sense (see "Error Analysis" below for why it's low, and "Known
Gaps" for what would actually move this number honestly).

**Latency/model size**: all three are near-identical in practice, consistent
with the same finding in the spam model card — not the deciding factor here
either.

## Class Imbalance

Label distribution in the synthetic dataset (`data/processed/priority_synthetic_v1/run_metadata.json`):
Low 57.4% / Medium 32.9% / High 8.0% / Critical 1.7%. Critical has only
~170 total examples across all 10,000 rows, and after the leakage-safe
`GroupShuffleSplit` (grouped by sender — see `docs/data_audit_priority.md` §6),
the test split contains just 11 Critical examples. Any metric computed on 11
examples carries substantial sampling variance — a difference of 1-2
correctly-classified emails swings the reported F1 meaningfully. Treat
Critical-class numbers in this document as directionally informative, not
precise.

**Class weight comparison** (`backend/scripts/experiment_priority_class_weight.py`,
Logistic Regression only, same split):

| `class_weight` | Macro F1 | Critical/High F1 | Critical F1 |
|---|---|---|---|
| `None` (sklearn default) | 0.4444 | 0.1765 | **0.0** (never predicts Critical) |
| **`"balanced"` (shipped)** | **0.4712** | **0.2667** | 0.0488 |

`"balanced"` is a confirmed improvement, not an unverified default — without
it, the model never once predicts "Critical" on the test set, which for an
urgency-detection system is the single worst failure mode possible (a
missed Critical is exactly the PRD's own worry, §2.1: "a critical customer
complaint lands in spam because it contains the word 'promotion'").

**SMOTE was not attempted**, deliberately: SMOTE interpolates between
existing minority-class samples in *feature space* to synthesize new ones.
Applied to a TF-IDF matrix (sparse, ~50,000 dimensions, most of it zero),
interpolating between two sparse vectors produces a synthetic vector that
corresponds to no real, coherent text — the "average" of two documents in a
bag-of-words space is not a sentence. This is a well-known mismatch between
SMOTE's assumption (a dense, continuous, locally-linear feature space) and
what TF-IDF actually provides, not a settings problem. `class_weight` (which
reweights the loss function, not the data) is the appropriate lever for
sparse high-dimensional text features, and the comparison above confirms it
helps.

## Probability Calibration

**Not specially calibrated** for Logistic Regression — its `predict_proba`
comes directly from the multinomial softmax. This differs from spam's SVM,
which *requires* `CalibratedClassifierCV` because `LinearSVC` has no native
`predict_proba` at all — the calibration there is structurally necessary,
not optional. Because calibration quality determines how much weight a
future auto-escalation feature (FR-18) could safely put on the confidence
score, it was measured rather than left as an assumption
(`backend/scripts/check_priority_calibration.py`, test set, multiclass
Brier score 0.4404):

| Confidence bin | n | Avg. reported confidence | Actual accuracy | Gap |
|---|---|---|---|---|
| [0.0, 0.4) | 73 | 0.337 | 0.219 | **0.118 — overconfident** |
| [0.4, 0.6) | 357 | 0.510 | 0.557 | 0.047 |
| [0.6, 0.8) | 300 | 0.695 | 0.773 | 0.078 (underconfident) |
| [0.8, 1.0) | 149 | 0.858 | 0.913 | 0.055 (underconfident) |

**Reading this correctly**: for confidence ≥ 0.6, the model is reasonably
calibrated and if anything slightly conservative (real accuracy exceeds
reported confidence) — a good direction to err in. But **the model is
overconfident specifically on its least-confident predictions**: at
"confidence 0.337" the caller might assume roughly 1-in-3 odds; the real
rate is closer to 1-in-5. Practical implication: a low-confidence (<0.4)
prediction from this model is *less* trustworthy than the number itself
suggests — treat anything in that band as "needs human review" regardless
of which label it names, not just proportionally to its stated confidence.
This was measured on synthetic data; the calibration *shape* (good when
confident, overconfident when unsure) is plausible to persist on real data
too, but the exact gap sizes should be re-measured once real labels exist.

## Error Analysis

Confusion matrix (Logistic Regression, test set, rows = actual, columns = predicted):

| Actual \ Predicted | Low | Medium | High | Critical |
|---|---|---|---|---|
| **Low** (469) | 372 | 73 | 12 | 12 |
| **Medium** (315) | 99 | 163 | 42 | 11 |
| **High** (84) | 7 | 24 | 47 | 6 |
| **Critical** (11) | 0 | 1 | 9 | 1 |

**What the errors actually look like, not just their count:**
- **Errors are overwhelmingly adjacent-class, not wild jumps.** Of Critical's
  10 misclassifications, 9 landed on High (one level off) and only 1 on
  Medium — zero landed on Low. The model is picking up *some* real ordinal
  structure in the urgency signal even where it can't nail the exact class,
  which is a meaningfully different (better) failure mode than random
  confusion would produce.
- **Low↔Medium is the largest single error mass** (73 + 99 = 172 of 833
  total non-Critical-adjacent errors) — the boundary between "no action
  needed" and "respond within normal cycle" is inherently the fuzziest one
  in the taxonomy (see `docs/data_audit_priority.md` §3: "Medium is the
  default bucket... if unsure, prefer Medium"), and the heuristic label
  generator itself likely draws this line less sharply than a human
  annotator would.
- **Causal attribution** — three separate, identifiable causes, not one
  vague "needs more data":
  1. **Minority-class sample size**: 11 Critical examples in test, ~170 in
     the full dataset, is simply too few for any linear model to carve a
     confident decision boundary in a 50,000+ dimensional TF-IDF space.
  2. **Injected label noise sets a hard ceiling.** ~5.6% of labels were
     deliberately shifted by one level (`generate_synthetic_priority_dataset.py`'s
     `_apply_label_noise`) specifically so the dataset wouldn't be perfectly
     separable — this means even a hypothetically perfect model cannot
     reach 100% agreement with the recorded labels, by construction.
  3. **The keyword-matching mismatch between label generation and feature
     extraction**: labels were generated from urgency/escalation keyword
     matches against **raw** email text; the model's own
     `urgency_keyword_count` feature is computed from **preprocessed**
     text (lemmatized, per `PRIORITY_CONFIG`). A phrase like "escalating"
     may lemmatize differently than the exact keyword string
     `ESCALATION_KEYWORDS` expects, meaning the model doesn't even have
     perfect access to the exact signal that generated its own labels —
     this is an *additional*, unintentional source of noise on top of the
     deliberate 5.6%, partially reducing (not eliminating) the structural
     leakage concern already named in `docs/data_audit_priority.md` §4.
- **What this analysis does NOT show**: it cannot say anything about
  real-world error patterns (e.g., "does the model confuse angry customers
  with automated alerts") because there are no real labels to compare
  against. The error categories above are about the *synthetic generating
  process* interacting with the *model*, which is exactly what track-1
  (pipeline validation) is supposed to surface — see
  `docs/data_audit_priority.md` §4.

## Intended Use

- **Pipeline development and architecture validation only.** Proves the
  ingestion → feature engineering → training → multiclass evaluation →
  serving → audit-logging → feedback path works end-to-end.
- **Not intended for any real triage, routing, or notification decision**
  (FR-18's "Critical emails trigger immediate notification" must NOT be
  wired to this model's output — a false Critical suppression or a
  never-fires Critical detector, per the confusion matrix above, are both
  live risks with this model).

## Limitations

1. **Trained on synthetic, heuristically-generated labels — no human ever
   annotated these emails.** This is the primary limitation and supersedes
   all others; see `docs/data_audit_priority.md`.
2. **Macro F1 (0.4712) and Critical/High F1 (0.2667) are far below the PRD's
   own targets** (0.82 macro, 0.85 Critical/High) — reported honestly, not
   narrowed by further threshold or weight tuning to look better (per this
   phase's own "don't chase metrics" principle). The gap is not a tuning
   problem; see "Error Analysis" causal attribution above.
3. **Sender history (FR-17) is not implemented at all** — no data source for
   it exists in this codebase (no CRM, no persistent sender profile). See
   `docs/data_audit_priority.md` §5.
4. **Body sentiment (FR-17) is approximated by keyword lexicons, not a real
   sentiment model** — Phase 7 (Sentiment Analysis) doesn't exist yet.
5. **`thread_depth` and attachment features are always defaulted** (0/False)
   — no loader in this repo extracts real values for them yet (same default
   used in training and at inference, so no train/serve skew, but zero
   signal from these fields regardless).
6. **Calibration is measured but imperfect** (see "Probability Calibration"
   above) — reasonably reliable at confidence ≥ 0.6, overconfident below
   0.4. Do not treat a low-confidence score as proportionally trustworthy.
7. **Enron-sourced text is 2001-2002 corporate email** — same domain-shift
   caveat as the `enron` dataset registry entry; energy-sector jargon,
   pre-modern-spam-era writing patterns.
8. **FR-18 (notifications) is entirely unimplemented** — no webhook
   dispatcher or in-app notification channel exists in this codebase. Out of
   scope for this phase; flagged, not silently skipped.

## Path to a PRD-Compliant Model (Not Implemented — Blocked on Annotation)

In order of what actually needs to happen, per `docs/data_audit_priority.md` §4:
1. Real annotation effort — 10,000+ emails, 3 annotators, Cohen's Kappa ≥
   0.70, on real (anonymized) enterprise email, not more Enron.
2. Re-run this exact pipeline (`train_priority_model.py`,
   `PriorityMLPipeline`, `Trainer`, `ArtifactManager`) against the real
   labels — zero architecture changes required, by design.
3. Only then do the PRD's F1 targets become a meaningful bar to evaluate
   against. Hitting them on synthetic data would prove nothing; missing them
   here proves even less about the real task's difficulty.
4. Once real data exists, revisit calibration verification and consider
   whether the keyword-vs-lemmatized-text mismatch (Error Analysis, cause 3)
   is worth fixing generally (matching keywords against raw or lightly
   cleaned text) — currently not worth fixing for a dataset whose labels
   won't exist post-annotation anyway.
