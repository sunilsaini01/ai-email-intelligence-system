# Email Categorization Module — Architecture (Phase 5)

> **Data status: SYNTHETIC, NOT PRD-compliant.** See
> `docs/data_audit_categorization.md` before reading any metric in this
> document or `docs/model_cards/email_categorization.md` as evidence of
> real-world readiness.

## What This Module Establishes

The third production ML module, and the first one that's genuinely
**multi-label** (FR-22, PRD §9.1) rather than binary (spam) or single-label
multiclass (priority). `CategoryMLPipeline`
(`app/pipeline/category_pipeline.py`) wraps a One-vs-Rest ensemble of 8
independent binary classifiers instead of one classifier — see "Why
Multi-Label Required a New Pipeline Class, Not a Branch" below for why this
couldn't be a parameter on `PriorityMLPipeline`.

## Request Flow

```
POST /api/v1/categorization/predict {subject, body, sender_email?, received_at?, ...}
        │
        ▼
Pydantic validation (CategoryPredictionRequest) — subject/body required, everything
        │                                          else optional with documented defaults
        ▼
CategoryService.classify()
        │  builds a "record" dict: body_clean (via EmailPreprocessor(CATEGORY_CONFIG)),
        │  subject_raw, sender_email, received_at, recipient lists,
        │  is_reply/is_forward (auto-derived from subject if not supplied)
        ▼
CategoryClassifierBackend.predict()          ── Protocol boundary, same pattern as spam/priority
        │  (currently: CategoryPredictor → TF-IDF + engineered features + One-vs-Rest calibrated SVM)
        │  returns MultiLabelPredictionResult: labels[], label_confidences{}, all_scores{}
        ▼
        ├──► General-fallback policy (if labels is empty — see model card "Probability & the General Fallback")
        ├──► structured log (app.categorization logger) ── metadata only, never body/subject
        ├──► CategoryPredictionRepository            ── audit row (JSON columns), best-effort
        │
        ▼
CategoryPredictionResponse {categories: [{category, confidence}], all_scores, model_version, processing_ms}
```

## Why Multi-Label Required a New Pipeline Class, Not a Branch

Per "REUSE > EXTEND > REFACTOR > CREATE NEW," extending `PriorityMLPipeline`
with a multi-label mode was considered and rejected: `fit()`'s `y_train`
shape (list of label-lists vs. list of scalar strings), the classifier type
(`OneVsRestClassifier` wrapping 8 binary sub-estimators vs. one multiclass
estimator), and `predict_proba()`'s return shape (independent per-label
probabilities that don't sum to 1, vs. one softmax distribution that does)
are different at every layer, not just at the top-level API. Branching
`PriorityMLPipeline` on a `multilabel: bool` would mean every one of those
three methods carries an `if` that only one caller (categorization) ever
takes, while `Trainer` and `PriorityService`'s existing, tested single-label
contract stays exposed to a code path it doesn't use. `CategoryMLPipeline`
is a new, small class instead — but everything *underneath* it is reused:
same `PipelineConfig`/`PipelineFactory` (wrapped in `OneVsRestClassifier`,
not modified), same `ContentFeatureExtractor`/`MetadataFeatureExtractor`/
`build_feature_matrix`, same `Trainer`/`ArtifactManager` (via the
`pipeline_cls` parameter priority's phase already added). See
`docs/data_audit_categorization.md` §7 for the business-requirements side
of why multi-label is correct here at all, not just an implementation note.

## What Changed in Shared Infrastructure (and why that's the right call)

| File | Change | Backward compatibility |
|---|---|---|
| `feature_engineering/feature_models.py` | `ContentFeatures` gained 7 fields (per-category keyword counts) | Additive dataclass fields — **but see the incident below; additive-for-code is not the same as additive-for-a-persisted-fitted-transform** |
| `feature_engineering/content_features.py` | `ContentFeatureExtractor` populates the 7 new fields from `category_keywords.py` | Always populated — no existing caller broken at the code level |
| `evaluation/model_evaluator.py` | New `evaluate_multilabel_model()` / `print_multilabel_evaluation()` functions | Additive functions, `evaluate_model()` untouched |
| `inference/prediction_models.py` | New `MultiLabelPredictionResult` dataclass | Additive, `PredictionResult` untouched |
| `services/feedback_service.py` | `FeedbackLogger.log_correction()`'s type hint widened to `str \| list[str]`; new `get_category_feedback_logger()` | No runtime behavior change for existing callers — `json.dumps` handles both shapes identically, and every pre-existing call site already passes a plain string |
| `preprocessing/email_preprocessor.py` | New `CATEGORY_CONFIG` (existing pattern: `SPAM_CONFIG`, `PRIORITY_CONFIG`, ...) | New constant, nothing removed |
| `data_ingestion/dataset_registry.py` | New `category_synthetic_v1` entry | Additive |

**Genuinely new** (no existing analog to extend): `CategoryMLPipeline`,
`CategoryPredictor`, `CategoryClassifierBackend`, `CategoryService`, the
category API/schema/DB/repository/migration files, `category_keywords.py`,
and the synthetic dataset generator — categorization's actual shape
(multi-label, One-vs-Rest, no single "the decision" the way priority's
argmax or spam's threshold are) has no existing equivalent to extend.

### Incident: extending `ContentFeatures` broke the already-trained priority model

**This is the one piece of "what changed in shared infrastructure" worth a
dedicated warning for the next module, not just a table row.** Adding 7
fields to `ContentFeatures` is backward-compatible *for code* — every
existing caller still imports and constructs it fine. It is **not**
backward-compatible for `PriorityMLPipeline`'s *already-trained, already-
committed* artifact: that artifact's fitted `StandardScaler` had memorized
the old 48-feature width, and rejected the new 55-feature width at
inference time with `ValueError: X has 55 features, but StandardScaler is
expecting 48 features as input`. This was caught immediately by the
existing test suite (`tests/test_priority_endpoint.py` and 3 others going
red — exactly what a regression suite is for), not discovered silently in
production. Fixed by retraining `priority_baseline.joblib` (same script,
same data, no architecture change) — see
`docs/model_cards/priority_classification.md`'s "Phase 5 Retrain Note" for
the resulting metric deltas, disclosed rather than silently updated.

**Lesson, stated for whichever module extends `ContentFeatures` or
`MetadataFeatures` next**: budget a "retrain every existing consumer of
`build_feature_matrix`, then run its full test suite" step as part of the
change, not an afterthought if tests happen to catch it. This module (Phase
5) is the second consumer of that shared feature-matrix machinery (after
priority); a third consumer makes this a recurring cost worth solving
structurally (e.g., versioning the feature schema, or fitting a fresh
scaler at load time) rather than repeatedly rediscovering it.

## Why a Separate `CategoryClassifierBackend` Protocol

Same reasoning `docs/architecture_priority_classification.md` already gives
for why priority's Protocol isn't shared with spam's: the return type is
the actual reason. `CategoryClassifierBackend.predict()` returns a
`MultiLabelPredictionResult` (a list of assigned labels + a full
distribution over 8 independent scores) — structurally different from
spam's single `positive_label`-relative probability and priority's single
scalar `label`. Three small, honest Protocols beat one Protocol with fields
that lie about what some implementations need.

## Feature Availability — What's Real, What's Included-for-Consistency-Only

See `docs/data_audit_categorization.md` §5 for the full audit. Summary:
subject/body category-keyword counts and TF-IDF are real, load-bearing
signals. Sender domain (internal/external/freemail) is real and is the
single most useful disambiguator for the Support/IT and Sales/Billing
near-miss pairs per the taxonomy (`docs/data_audit_categorization.md` §3).
Time-of-day/day-of-week are real features, computed identically to
priority's, but — unlike priority, where FR-17 names them directly —
nothing in FR-21 through FR-24 ties category to time; they're included
because `MetadataFeatureExtractor` is reused wholesale, not because a
category-specific reason to include them was established. `thread_depth`
and attachment fields are defaulted identically at train and serve time,
same disclosed-zero-signal-but-no-skew situation as priority's.

## Performance (measured, not estimated)

| Operation | Measured | Note |
|---|---|---|
| `CategoryService()` construction (first call in a process, warm process already paid sklearn/spaCy import cost from spam/priority warm-up) | Sub-second in this environment (see `test_startup_warmup.py`'s full-lifespan run) | Import-chain cost is shared with priority's `PriorityMLPipeline` import (same sklearn submodules); categorization is the *third* service warmed at startup, not the first, so most of the fixed cost was already paid |
| Warm `classify()` call (steady state) | **~15-30ms**, measured via direct `TestClient` calls during manual verification | Slightly higher than priority's ~3-12ms — expected: 8 binary `CalibratedClassifierCV`-wrapped SVMs run per request instead of 1 multiclass model, though all 8 share the same TF-IDF/engineered-feature vectorization pass, not 8 independent ones |

**Startup warm-up**: `app/main.py`'s `lifespan` handler now warms
`get_category_service()` alongside spam and priority — added in the same
change that registered the category router, not a separate follow-up (the
pattern was already established by priority's phase; no reason to defer
it here). Verified via manual `TestClient(app)` lifespan invocation matching
`tests/test_startup_warmup.py`'s existing pattern.

**Migration verified against a real Postgres** (Docker, temporary
container on host port 55432 to sidestep this machine's native-Postgres/
docker-compose 5432 conflict documented in the README): `alembic upgrade
head` ran all three migrations (spam → priority → category) cleanly from a
blank database; `category_prediction_logs`'s resulting schema was inspected
column-by-column against `CategoryPredictionLog` — exact match, including
the two `json` columns (`predicted_categories`, `confidences`). Container
torn down after verification — not left running.

## Security Review

**Decision: PII anonymization is NOT wired into the category path** — same
reasoning as spam and priority (`docs/architecture_spam_detection.md`,
`docs/architecture_priority_classification.md`): `app/security/
pii_anonymizer.py` exists but nothing in this module calls an external LLM
or third-party API with email content. Revisit when auto-reply (LLM) or any
external API touches this text.

**What was checked before reaching that decision**:
- `CategoryPredictionRepository` stores subject/body in plaintext — same
  exposure profile as `SpamPredictionRepository`/`PriorityPredictionRepository`,
  not a new one.
- No new external API calls introduced by this module.
- `CategoryPredictionRequest` requires `body`, defaults everything else —
  Pydantic rejects malformed types before any model work.
- No new authentication surface — inherits Phase 1's stated gap, not a
  regression specific to categorization.
- `docs/annotation_guidelines_categorization.md` §6 explicitly instructs
  against storing extra sensitive email content in future annotation
  records beyond an `email_id` reference — a forward-looking constraint on
  the not-yet-built annotation tooling, not something this phase's serving
  path violates today.

## Known Gaps

| Deferred | Reason |
|---|---|
| Real annotated training data | The core Phase 5 blocker — see `docs/data_audit_categorization.md` §4 and `docs/annotation_guidelines_categorization.md`. Nothing else in this table matters until this is resolved. |
| Per-category probability calibration | Not verified — see model card "Calibration." Multi-label needs 8 separate reliability curves, more work than priority's single-curve check; not built this phase. |
| Recall-weak precision-strong pattern (model card "Error Analysis") | Not root-caused beyond the class-weight lever already applied; a per-category threshold sweep is the next cheapest thing to try. |
| FR-23 (per-organization configurable taxonomy) | No multi-tenant org concept exists anywhere in this codebase — same class of gap as Phase 1's deferred real auth. |
| Sender-history / routing-history signal | No persistent sender profile store exists — identical gap to priority's FR-17 sender-history limitation. |
| Thread lineage ("a reply inherits its thread's categories") | No `In-Reply-To`/`References` extraction exists in any loader yet — same gap as priority's equivalent rule. |
| `thread_depth` / attachment extraction | Defaulted identically at train and serve time — no loader populates real values yet. |
| **Cross-module feature-schema fragility** (see the `ContentFeatures` incident above) | Not structurally fixed this phase — the next module that extends `ContentFeatures`/`MetadataFeatures` will hit the same class of issue unless a schema-versioning or fit-at-load mechanism is built first. Flagged as technical debt, not resolved. |
