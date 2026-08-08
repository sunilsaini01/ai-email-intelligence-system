# Model Card — Intent Detection (Baseline, SYNTHETIC Data)

> **THIS MODEL IS NOT PRD-COMPLIANT.** It is trained on
> `data/processed/intent_synthetic_v1` — heuristically-labelled, not
> human-annotated. Every metric in this document is a **pipeline
> validation metric**, not evidence of real-world intent-detection
> quality. See `docs/data_audit_intent.md` for the full data strategy
> decision and `docs/error_analysis_intent.md` for a specific, root-caused
> class-level reliability finding (Escalation) that goes beyond the
> generic synthetic-data caveat.

## Model Details

| Field | Value |
|---|---|
| Model type | Logistic Regression, One-vs-Rest (`sklearn.multiclass.OneVsRestClassifier`), multi-label |
| Features | TF-IDF only (uni+bigram) — no engineered `ContentFeatures`/`MetadataFeatures`, deliberately; see `docs/architecture_intent.md` |
| Class weight | `"balanced"` — same starting point as priority/category (no prior sweep done for intent yet) |
| Framework | scikit-learn 1.9 |
| Training script | `backend/scripts/train_intent_model.py` |
| Artifact | `artifacts/intent_baseline.joblib`, `artifacts/versions/intent_{version}.joblib` |
| Current version | `logistic_regression-20260808-211254` |
| Training data | `data/processed/intent_synthetic_v1` — **synthetic, see warning above** |

## Why Logistic Regression, Over SVM and Naive Bayes

| Model | F1-macro | F1-micro | F1-weighted | Hamming Loss | Subset Accuracy |
|---|---|---|---|---|---|
| **Logistic Regression (chosen)** | **0.3891** | 0.4670 | 0.5088 | 0.1786 | 0.2344 |
| SVM | 0.3335 | 0.4943 | 0.4652 | **0.1011** | **0.4073** |
| Naive Bayes | 0.1117 | 0.1538 | 0.1453 | 0.1335 | 0.3015 |

**Chosen by F1-macro** (this module's PRD-named metric, FR-33's evaluation
row) — SVM has better Hamming loss and subset accuracy (it's more
conservative, predicting fewer labels overall, which trivially improves
exact-match and per-bit accuracy on a sparse multi-label problem), but
worse F1-macro, meaning it under-serves the rarer classes more severely.
Naive Bayes is clearly worst on every metric — **F1 of exactly 0.0 on
Complaint, Escalation, and Refund**, meaning it never once correctly
predicts three of the nine classes. Same "don't let accuracy-adjacent
metrics hide minority-class failure" lesson Priority's model card already
documents, applied here to the metric PRD actually names for this module.

## Per-Class F1 (Logistic Regression, chosen model)

| Class | F1 | Note |
|---|---|---|
| Schedule | 0.6788 | Best-performing — most lexically distinctive vocabulary |
| Inquiry | 0.6201 | |
| Order | 0.5637 | See "Known Issue: Order False Positives" below — a non-trivial F1 despite a documented false-positive risk |
| Request | 0.5378 | |
| Cancel | 0.4863 | |
| Feedback | 0.3765 | |
| **Complaint** | **0.1421** | Weak — see "Known Issue: Complaint Under-Detection" |
| **Escalation** | **0.0968** | **Least reliable class overall — see "Known Issue: Escalation" below** |
| **Refund** | **0.0** | Never correctly predicted on the test set at all |

## Known Issue: Escalation Is Unreliable in Both Directions

Empirically demonstrated in `docs/error_analysis_intent.md`, not just
inferred from the low F1 above: on a 14-example qualitative set, Escalation
was predicted on 4 emails that have nothing to do with escalation
(a contract request, an order-status question, a scheduling email, a pure
FYI note) **and simultaneously failed to fire on the one example written
specifically to trigger it**. Root cause traced to the training data: 441
positive examples out of 10,000 (4.41% prevalence,
`data/processed/intent_synthetic_v1/run_metadata.json`), combined with
`class_weight="balanced"` amplifying a thin, keyword-heuristic-derived
signal into an unstable decision boundary rather than a conservative one.
**This is the single most important reason this model must not be
described as "working" for any of its 9 classes uniformly** — some
classes (Schedule, Inquiry) show real, if unvalidated, discriminative
signal; Escalation does not, and Refund (F1=0.0) is worse still.

## Known Issue: Order False Positives on the Ordinary Word "Order"

The classifier predicts Order intent on text like "In order to proceed,
please confirm receipt" (verified in `docs/error_analysis_intent.md`).
Root cause: `intent_keywords.py`'s `ORDER_KEYWORDS` includes the bare word
"order," and the synthetic label generator's adaptive threshold collapsed
to 1 for every class (`per_class_thresholds` in `run_metadata.json`) — a
single occurrence of a common English word was sufficient to generate a
positive training label. **Separate from, and not fixed by,** this same
phase's `ORDER_ID_PATTERN` regex fix (`app/feature_engineering/patterns.py`)
— that fix corrects FR-35's *entity extraction* (which now correctly
requires a digit in the captured token), not the *classifier's* keyword-
derived Order-intent false positive, which remains a live, disclosed
limitation of the trained model itself.

## Known Issue: Complaint Under-Detection Without Explicit Lexical Cues

"Your support team has been unhelpful for weeks" and a polite complaint
with no literal "complaint"/"disappointed" word both predicted zero
intents. Same structural limitation already disclosed for Sentiment's
VADER (Phase 7A) — keyword/lexicon-adjacent approaches cannot detect
dissatisfaction that isn't lexically explicit — confirmed concretely here
for a second, independent module.

## Domain Mismatch (Beyond the Standard Enron Caveat)

Order/Refund/Cancel are consumer-transactional concepts nearly absent from
Enron's internal B2B energy-trading correspondence — see
`docs/data_audit_intent.md` §3. Despite this, the adaptive per-class
threshold mechanism (inherited from Category's generator) still produced
non-trivial label counts for all three (Order 17.5%, Cancel 14.4%, Refund
5.4% of 10,000 rows) — worth noting the mechanism compensated for rarity
more than initially expected, but the label quality for these three
classes should be trusted even less than Escalation's, given both the
domain mismatch AND the specific reliability problems documented above.

## Calibration

**Not measured this phase.** Given Escalation's demonstrated unreliability
and Refund's 0.0 F1, a calibration study would be measuring noise, not
signal, for at least 2 of the 9 classes — deferred until either real data
exists or the specific class-level issues above are addressed. Disclosed
as an explicit gap, not silently skipped.

## FR-35 Entity Extraction — Separately Evaluated (Not Trained, No Calibration Concern)

Order IDs, dates, monetary amounts, and person names reuse deterministic
regex/NER extraction (`app/nlp/intent_entities.py`) — no training, no
synthetic-label concern. Verified against the PRD's own worked example
("order #45821") and several phrasing variants
(`tests/test_intent_entities.py`). Product-name extraction is disclosed
low-recall (spaCy `en_core_web_sm`'s weak `PRODUCT` category).

## Intended Use

- **Pipeline development and architecture validation only.** Proves the
  ingestion → keyword-heuristic bootstrap → multi-label training →
  evaluation → serving → entity extraction → audit-logging → feedback path
  works end-to-end.
- **Not intended for any real routing or auto-reply decision** (FR-36).
  Given Escalation's specific, demonstrated unreliability, wiring this
  model's Escalation output into any downstream escalation-triggering
  logic would be actively worse than having no signal at all.

## Limitations

1. **Trained on synthetic, heuristically-generated labels — no human ever
   annotated these emails.** Primary limitation, same class as priority/
   category. See `docs/data_audit_intent.md`.
2. **Escalation and Refund are demonstrably unreliable**, not merely
   "unvalidated" — see the two "Known Issue" sections above. This is
   stronger and more specific than the general synthetic-data disclosure.
3. **F1-macro (0.3891) is far below the PRD's own target** (0.80, also
   stated as 0.78 elsewhere) — reported honestly, not narrowed by further
   tuning to look better.
4. **No engineered features, deliberately** — see architecture doc. If
   real annotated data later shows metadata/content signals would help,
   this is a considered design choice to revisit then, not an oversight.
5. **Product-name extraction is low-recall** — see FR-35 section above.
6. **No calibration measured** — see "Calibration" above.

## Path to a PRD-Compliant Model (Not Implemented — Blocked on Annotation)

Identical structure to priority/category/sentiment's path, per
`docs/data_audit_intent.md` §4 / `docs/intent_labeling_strategy.md`:
1. Real annotation — 5,000+ emails minimum, 3 annotators, per-class Cohen's
   Kappa ≥ 0.65, on the 9-class multi-label taxonomy.
2. Re-run this exact pipeline (`train_intent_model.py`, `IntentMLPipeline`,
   `Trainer`, `ArtifactManager`) against real labels — zero architecture
   changes required, by design.
3. Specifically re-evaluate whether Escalation and Refund's poor
   performance was a data-quality artifact (as this phase's evidence
   strongly suggests) or a genuinely harder class even with real labels —
   the current evidence cannot distinguish these two possibilities.
4. Only then do the PRD's F1-macro targets become a meaningful bar.
