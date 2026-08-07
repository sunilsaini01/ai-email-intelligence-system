# Priority Classification Module — Architecture (Phase 4)

> **Data status: SYNTHETIC, NOT PRD-compliant.** See `docs/data_audit_priority.md`
> before reading any metric in this document or `docs/model_cards/priority_classification.md`
> as evidence of real-world readiness.

## What This Module Establishes

The second production ML module, and the first one that required extending
shared infrastructure rather than only reusing it: `MLPipeline` (spam) is
TF-IDF-only, but FR-17 requires priority to incorporate metadata (time of
day, sender domain) and keyword signals alongside text. `PriorityMLPipeline`
(`app/pipeline/priority_pipeline.py`) is what actually wires the
already-existing-but-previously-unused `ContentFeatureExtractor` /
`MetadataFeatureExtractor` / `build_feature_matrix` into a trainable
pipeline — see "What Changed in Shared Infrastructure" below.

## Request Flow

```
POST /api/v1/priority/predict {subject, body, sender_email?, received_at?, ...}
        │
        ▼
Pydantic validation (PriorityPredictionRequest) — subject/body required, everything
        │                                          else optional with documented defaults
        ▼
PriorityService.classify()
        │  builds a "record" dict: body_clean (via EmailPreprocessor(PRIORITY_CONFIG)),
        │  subject_raw, sender_email, received_at (defaults to now()), recipient lists,
        │  is_reply/is_forward (auto-derived from subject if not supplied),
        │  thread_depth/attachments (always defaulted — see docs/data_audit_priority.md §5)
        ▼
PriorityClassifierBackend.predict()          ── Protocol boundary, same pattern as spam
        │  (currently: PriorityPredictor → TF-IDF + engineered features + calibrated LR)
        ▼
        ├──► structured log (app.priority logger) ── metadata only, never body/subject
        ├──► PriorityPredictionRepository           ── audit row, best-effort (never blocks the response)
        │
        ▼
PriorityPredictionResponse {priority, confidence, probabilities, model_version, processing_ms}
```

## What Changed in Shared Infrastructure (and why that's the right call)

Per this phase's "REUSE > EXTEND > REFACTOR > CREATE NEW" instruction, every
change below is additive and backward-compatible — spam's tests were run
after each change and stayed green throughout:

| File | Change | Backward compatibility |
|---|---|---|
| `feature_matrix.py` | `build_feature_matrix()` gained optional `scaler`/`fit_scaler` params | `scaler=None` default preserves exact original behavior; had zero production callers before this phase |
| `training/trainer.py` | `Trainer.__init__()` gained optional `pipeline_cls` param | Defaults to `MLPipeline` — spam's `Trainer(config)` calls are unaffected |
| `evaluation/model_evaluator.py` | `evaluate_model()` gained optional `average` param | Defaults to `"binary"` — spam's calls (which never pass it) are unaffected |
| `feature_engineering/feature_models.py` | `ContentFeatures` gained 3 fields (urgency/escalation/sla keyword counts) | Additive dataclass fields, always populated by the extractor — no existing test constructs this dataclass directly |
| `feature_engineering/domains.py` | `INTERNAL_DOMAINS` populated with `"enron.com"` | Was an empty, unconfigured set; this is a real fact about the Phase 4 dataset's source, not a stand-in for a real org's config |
| `preprocessing/email_preprocessor.py` | New `PRIORITY_CONFIG` (existing pattern: `SPAM_CONFIG`, `SENTIMENT_CONFIG`, `SUMMARY_CONFIG`) | New constant, nothing removed |
| `services/feedback_service.py` | `FeedbackLogger` gained `module` param; new `get_priority_feedback_logger()` | Defaults to `module="spam"` — existing `get_feedback_logger()` unchanged |

**Genuinely new** (no existing analog to extend): `PriorityMLPipeline`,
`PriorityPredictor`, `PriorityClassifierBackend`, `PriorityService`,
`priority_keywords.py`, the priority API/schema/DB/repository/migration
files, and the synthetic dataset generator — these exist because priority's
actual shape (multiclass, metadata-dependent, no threshold-policy layer) has
no equivalent in spam to extend.

## Why a Separate `PriorityClassifierBackend` Protocol, Not a Shared One

Spam's `SpamClassifierBackend` requires a `positive_label` field because the
service compares one probability against a tunable threshold. Priority has
no threshold layer — the model's argmax prediction *is* the decision, full
stop. Forcing both backends into one shared Protocol would mean adding a
meaningless `positive_label` to every future multiclass backend just to
satisfy an interface it structurally can't use. Two small, honest Protocols
beat one Protocol with a field that lies about what some of its
implementations need.

## Why Naive Bayes Doesn't Get Scaled Engineered Features

`ComplementNB`/`MultinomialNB` require non-negative input (they model
counts). `StandardScaler` centers features at zero mean, which produces
negative values for anything below the mean — feeding that to NB raises a
`ValueError`, not a silent wrong answer. `PriorityMLPipeline` checks
`config.model_type != "naive_bayes"` and skips scaling for that path only,
keeping the raw non-negative engineered features. Locked in by
`test_naive_bayes_path_does_not_scale_engineered_features` in
`tests/test_priority_pipeline.py`.

## Feature Availability — What's Real, What's Defaulted

See `docs/data_audit_priority.md` §5 for the full audit. Summary: subject/body
text and metadata derived from real headers (hour of day, sender domain,
reply/forward, recipient counts) are real signals in both training and
serving. `thread_depth` and attachment fields are defaulted identically on
both sides (no train/serve skew, but zero information content). Sender
history (FR-17) has no implementation at all — no data source exists.

## Performance (measured, not estimated)

| Operation | Measured | Note |
|---|---|---|
| One-time sklearn/spaCy import cost | ~6.5s (measured for the predictor's own import chain; the full chain triggered by unpickling `PriorityMLPipeline` — see below — is larger) | Paid once per process, not per request |
| `PriorityService()` construction (first call in a process) | **~29s** | See "Known Gap" below — this is NOT joblib deserializing 3.5MB slowly; it's Python resolving `app.pipeline.priority_pipeline`'s import chain (TfidfVectorizer, PipelineFactory → sklearn.svm/naive_bayes/calibration, EngineeredFeatureScaler, both keyword lexicons) for the first time, triggered implicitly by unpickling — nothing in `priority_service.py`/`priority_predictor.py` imports that module directly, so pickle's on-demand import pays the cost at construction time instead of at process-import time |
| First `classify()` call after construction | ~1.2s | Pays `EmailPreprocessor`'s lazy spaCy model load (`en_core_web_sm`) — same lazy-load pattern spam's preprocessor already uses |
| Warm `classify()` call (steady state) | **~3-12ms** | Well inside the PRD's latency budget for this class of operation once warm |

**Fixed** (`app/main.py`'s `lifespan` handler, added as a same-phase
follow-up once this cost was measured): both `get_spam_service()` and
`get_priority_service()` are now called eagerly at app startup, non-fatally
(a missing artifact is logged as a warning, not raised — the app still
starts, and the existing per-request 503 still covers that case). Verified
end-to-end against a real Uvicorn process: startup takes ~9s (paying the
warm-up cost once), and the first real request's actual prediction logic
then runs in single-digit milliseconds. Confirmed inert for the existing
test suite — plain `TestClient(app)` (used by `tests/conftest.py`'s shared
`client` fixture) never triggers ASGI lifespan events at all; only
`with TestClient(app) as client:` does, which is exactly what
`tests/test_startup_warmup.py` uses to exercise this.

**A separate, more serious bug was found while verifying this fix, and is
now partially fixed**: when the async DB write (`repository.log_prediction(...)`)
can't establish a connection — reproduced against this environment's local
Postgres, which appears to hang on an IPv6 (`::1`) connection attempt rather
than failing fast the way it does under pytest — the entire request used to
hang indefinitely (75+ seconds observed, unresolved). Fixed by wrapping the
write in `asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS)`
(`app/database/session.py`), proven against a fake hanging session in
`tests/test_db_write_timeout.py`.

**Migrations independently verified against a real Postgres** (Docker,
temporary container on a non-conflicting port — this machine's native
Postgres install and docker-compose's `postgres` service both claim host
port 5432, so a separate verification container was used rather than
fighting that conflict): both `spam_prediction_logs` and
`priority_prediction_logs` were created with `alembic upgrade head` and
their schemas inspected column-by-column against the ORM models — exact
match. A direct, standalone write through `SpamPredictionRepository`
against this real database completed in 0.06s.

**A third, distinct, NOT-yet-fixed issue surfaced during this
verification**: the identical write that completes in 60ms when called
directly hangs when the same operation runs inside an actual live
FastAPI/Uvicorn request on this Windows environment — after
`run_in_threadpool(service.classify, ...)` returns and the route proceeds to
`await asyncio.wait_for(repository.log_prediction(...), timeout=3.0)`, no
`spam_prediction_log_failed` warning is ever logged and the response is
never sent, well past the 3-second timeout. This means `asyncio.wait_for`
is not successfully cancelling *this specific* code path under *this*
specific runtime combination (Uvicorn's default event loop + `anyio`'s
threadpool bridge for `run_in_threadpool` + SQLAlchemy async's own
greenlet-based sync/async bridge), even though the identical
`asyncio.wait_for` mechanism is proven to cancel a plain hanging coroutine
(the regression test) and the DB operation itself is fast and correct in
isolation. Root cause not identified — plausible candidates are a
Windows-specific `ProactorEventLoop` interaction, or a limitation of
cancelling a greenlet-bridged call mid-flight — but not confirmed. **This
means the fix above is proven to bound a hang at the Python/asyncio level,
but is not yet proven to bound a hang encountered via the full real request
path on Windows.** Flagged explicitly rather than claimed as resolved.

## Security Review (Step 20)

**Decision: PII anonymization is NOT wired into the priority path, for the
same reason as spam** (`docs/architecture_spam_detection.md`'s own Known
Gaps): `app/security/pii_anonymizer.py` exists but nothing in this module
calls an external LLM or third-party API with email content — FR-09's
actual driver ("anonymize before external API calls") doesn't apply yet.
Revisit when auto-reply (LLM) or any external API touches this text, not
before — wiring anonymization in without a concrete external-call driver
would degrade the audit log's readability (subject/body get masked) for no
corresponding privacy benefit.

**What was checked, specifically, before reaching that decision** (per
Step 20's instruction not to wire anonymization in reflexively):
- `PriorityPredictionRepository` stores subject/body in plaintext, same as
  `SpamPredictionRepository` — consistent, not a new exposure.
- No new external API calls were introduced by this module.
- Input validation: `PriorityPredictionRequest` requires `body`, defaults
  everything else — Pydantic rejects malformed types before any model work,
  same as spam.
- No new authentication surface — this module inherits Phase 1's stated gap
  (no auth exists yet anywhere in this codebase); not a regression specific
  to priority.

## Known Gaps

| Deferred | Reason |
|---|---|
| Real annotated training data | The core Phase 4 blocker — see `docs/data_audit_priority.md` §4. Nothing else in this table matters until this is resolved. |
| **DB write hangs on the live request path (Windows)** | **Open, most significant remaining bug.** `asyncio.wait_for` cancels a plain hanging coroutine (unit-tested) but does not observably cancel this same write when reached via a real Uvicorn request on this machine — see "Performance" above for the full reproduction. Root cause not identified. |
| FR-18 (Critical → notification) | No webhook dispatcher or in-app notification channel exists anywhere in this codebase yet. Out of scope for this phase. |
| Sender history (FR-17) | No persistent sender/account profile data source exists. |
| Real sentiment signal (FR-17) | Approximated by keyword lexicons pending Phase 7 (Sentiment Analysis). |
| `thread_depth` / attachment extraction | No loader in this repo extracts real values yet — defaulted identically at train and serve time. |
| ~~Probability calibration verification~~ | **Done** — measured via `check_priority_calibration.py`; see model card. |
| ~~Eager model warm-up at startup~~ | **Done** — `app/main.py`'s `lifespan` handler; verified against a real Uvicorn process. |
| ~~Alembic migrations not run against a real database~~ | **Done** — both verified against a real Postgres in Docker; schemas match the ORM models exactly. |
| **`docker-compose.yml`'s Postgres port (5432) conflicts with a native Postgres install** | Discovered during migration verification, not yet documented anywhere a future developer would see it before hitting the same confusing "wrong server" symptom. |
