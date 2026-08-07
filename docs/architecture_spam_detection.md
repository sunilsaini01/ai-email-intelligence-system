# Spam Detection Module — Architecture (Phase 3–4)

## What This Module Establishes

The first production AI module: a classical-ML spam classifier, served over
FastAPI, with calibrated decision thresholds, audit logging, and a dependency
boundary designed to absorb a future transformer model without an API change.

## Request Flow

```
POST /api/v1/spam/predict {subject, body}
        │
        ▼
Pydantic validation (SpamPredictionRequest) ── reject malformed input, cheap, before any model work
        │
        ▼
EmailPreprocessor(SPAM_CONFIG)              ── same class used at training time (no train/serve skew)
        │
        ▼
SpamClassifierBackend.predict()             ── Protocol boundary — see "Dependency Inversion" below
        │  (currently: SpamPredictor → TF-IDF + calibrated SVM)
        ▼
SpamService.classify()                       ── applies the calibrated threshold (policy), NOT the model's argmax
        │
        ├──► structured log (app.spam logger) ── metadata only, never body/subject
        ├──► SpamPredictionRepository          ── audit row, best-effort (never blocks the response)
        │
        ▼
SpamPredictionResponse {is_spam, status, spam_score, confidence, threshold_used, model_version, processing_ms}
```

## Dependency Inversion — Why the Model Can Change Without an API Change

`SpamService` depends on `SpamClassifierBackend` (`app/inference/classifier_backend.py`),
a `typing.Protocol` — not on `SpamPredictor` (the concrete TF-IDF + sklearn
implementation) directly. The contract is deliberately narrow:

```python
def predict(self, email_record: dict) -> PredictionResult: ...
def predict_batch(self, email_records: list[dict]) -> list[PredictionResult]: ...
```

Nothing sklearn-specific (no `Pipeline`, no `predict_proba` numpy array) leaks
into the contract — only `PredictionResult`, a plain dataclass. A future
`TransformerSpamClassifier` (DistilBERT/BERT/RoBERTa) only needs to produce
that same dataclass shape. `tests/test_spam_classifier_backend.py` proves this
isn't just a docstring claim — it injects a fake backend with no ML
dependencies at all and shows `SpamService` works unchanged.

**What does NOT need to change when the model changes:** the API contract
(`app/schemas/spam.py`), the threshold/quarantine policy layer, the DB
logging, the preprocessing step (a transformer would likely need lighter
preprocessing — that's a config change to `SPAM_CONFIG`, not an architecture
change).

**What DOES change:** a new class implementing `SpamClassifierBackend`, and
the object passed into `SpamService(predictor=...)`.

## Why the Threshold Lives in the Service Layer, Not the Model

A classifier's `.predict()` uses an implicit 0.5 cutoff. Our calibrated
operating point is ~0.06 — a business decision (recall-first, per PRD FR-11:
a missed spam email is worse than a quarantined legitimate one), not a
statistical default. Keeping this in `SpamService.classify()` means:

- The threshold can be retuned without retraining (edit `spam_baseline_metrics.json`, restart).
- Swapping in a transformer model doesn't require re-deriving where policy lives — it's already isolated.
- The model artifact stays a pure "text → probability" function, testable independently of business policy.

## Why Quarantine, Never Delete (FR-13)

The API never returns "deleted." Every classification resolves to
`status: "quarantined"` or `"clear"` — quarantine is the system's hedge
against the model being wrong. At ~91% precision (see model card), roughly
1 in 11 quarantined emails is a false positive; deleting instead of
quarantining would silently destroy real correspondence at that rate.

## Why Classification Runs via `run_in_threadpool`, Not a Direct Call

The route is `async def` (required to `await` the DB write). `SpamService.classify()`
is synchronous, CPU-bound work — TF-IDF vectorization + spaCy lemmatization.
Calling it directly inside an `async def` route blocks the single event loop
thread for the duration of every prediction, serializing all concurrent
requests behind each other. This was caught and fixed during review, not
designed in from the start — worth naming because it's an easy regression to
reintroduce: a plain `def` route gets threadpool offloading for free; an
`async def` route does not extend that to sync calls made inside it.

## Why a DB Write Failure Never Fails the Request

`app/api/v1/endpoints/spam.py` wraps `SpamPredictionRepository.log_prediction()`
in try/except. A caller asking "is this spam?" needs an answer regardless of
database health — losing one audit row is recoverable; making every
prediction depend on DB uptime is not (see docs/architecture.md's
liveness/readiness reasoning — same principle, applied to a write path this time).
The failure is still logged loudly (`spam_prediction_log_failed`, `exc_info=True`)
so it's visible to monitoring, not silently swallowed.

## Model Versioning & Artifact Strategy

- `artifacts/spam_baseline.joblib` — the ONLY path the running service loads.
  Stable filename by design: deploying a new model is "retrain, restart the
  API," no config change.
- `artifacts/versions/spam_{model_version}.joblib` — one immutable copy per
  training run, for audit/rollback. `model_version` is `{model_type}-{UTC timestamp}`
  (e.g. `svm-20260727-194512`) — not a semantic `v1/v2` (that implies release
  management we don't have yet). A real model registry (MLflow, per the PRD)
  replaces this scheme without changing where `SpamService` reads the current
  version from (`spam_baseline_metrics.json`'s `model_version` field).
- `artifacts/spam_baseline_metrics.json` — the sidecar that ties a model
  artifact to the threshold it was calibrated with and the metrics that
  justified picking it. The model file alone is not deployable without this;
  they're versioned together implicitly (same training run writes both).

## Migrations

`backend/alembic/` manages schema changes against Postgres — Alembic's
async template, wired to read the DB URL from `app.core.config.get_settings()`
(one source of truth, not a second hardcoded copy in `alembic.ini`) and to
target `app.database.session.Base.metadata` (populated via `app/models/__init__.py`,
so a model that's only ever imported by an endpoint doesn't silently stay
invisible to `autogenerate`). The initial revision
(`create spam_prediction_logs table`) was hand-written rather than
autogenerated — no live Postgres instance was reachable in the environment
this was built in — but its columns are a direct match to
`app/models/spam_prediction_log.py`. Run it with:

```bash
cd backend && alembic upgrade head
```

Tests still use `Base.metadata.create_all` against an in-memory/temp SQLite
DB (see `tests/test_spam_prediction_log.py`) — that's a deliberate, separate
concern from migrations: tests need a fast, disposable schema; production
needs a reviewable, reversible change history. Alembic revisions are not
run in the test suite.

## Known Gaps (intentional, matching Phase 1's stated pattern of naming deferred work)

| Deferred | Reason |
|---|---|
| PII anonymization on the spam path | `app/security/pii_anonymizer.py` exists but isn't wired in here — no external LLM call happens in this module yet, so the PRD's specific driver (FR-09: anonymize before external API calls) doesn't yet apply. Revisit when auto-reply (LLM) or any external API touches this text. |
| `spam_prediction_logs` folding into a real `email_classifications` table | Blocked on Module 1 (email ingestion) not existing yet — see `app/models/spam_prediction_log.py` docstring for the exact migration path. When that lands, it's a normal Alembic migration (add columns / copy data), not a redesign. |
| Transformer fine-tune | Recall now meets the FR-11 target (99.4%) after class-weight tuning — see model card. Two limitations a transformer *could* address (thin margin on a 596-email test set, 20+ year old training data) are better addressed by fresher labeled data first, per the PRD's own "baseline before BERT" principle — not implemented. |
