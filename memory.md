# Project Memory — AI Email Intelligence System

Catalog of every source/doc file's current status, for fast orientation in a
future session without re-reading everything. Generated 2026-08-08.

## Project Status Snapshot

Phase 6 of 15 (PRD numbering) is complete: Spam Detection, Priority
Classification, Email Categorization, and Email Summarization are all
implemented as a FastAPI modular monolith with served `/api/v1/*` endpoints,
DB-backed audit logging, and human-feedback endpoints. Phases 7-15
(Sentiment/Intent, Routing, RAG, Auto-Reply, Dashboard, CI/CD, Cloud, MLOps)
are not started. **Spam** is the only module with real, PRD-relevant
evidence (99.44% recall / 91.33% precision on held-out SpamAssassin data).
**Priority and Categorization** are trained on heuristically-labelled
*synthetic* data (real Enron text, fabricated labels via keyword heuristics)
— explicitly not PRD-compliant until real annotation happens (see
`docs/data_audit_priority.md`, `docs/data_audit_categorization.md`).
**Summarization** is evaluated on real, human-written but *off-domain* (BBC
News, not email) reference summaries (see `docs/data_audit_summarization.md`).
The single known-unresolved engineering item is
`docs/technical_debt/database_write_hang.md`: a real, reproduced DB-write
hang under the live Windows/Uvicorn request path (connects but never
completes the Postgres handshake); seven isolation experiments ruled out
asyncpg, bare asyncio, SQLAlchemy alone, and `BaseHTTPMiddleware` individually,
but the full real app still reproduces it — **mitigated (bounded via two
timeout layers), NOT root-caused, status PARTIAL**. Also note: root-level
`backend/test_*.py` files (as opposed to `backend/tests/*.py`) are informal,
assertion-free smoke-test scripts run manually during early development, not
part of the pytest suite — see the "backend/ (root-level test_*.py)" section
below.

---

## backend/app/api/

- `v1/router.py` — mounts health/spam/priority/category/summarization routers under `/api/v1`.
- `v1/endpoints/health.py` — `/health` (liveness, no DB) and `/health/ready` (readiness, checks DB via `SELECT 1`).
- `v1/endpoints/spam.py` — `/spam/predict` + `/spam/feedback`; 503 on missing artifact, `run_in_threadpool` for sync classify, DB write wrapped in `asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS)`.
- `v1/endpoints/priority.py` — `/priority/predict` + `/priority/feedback`; mirrors spam.py's pattern exactly.
- `v1/endpoints/category.py` — `/categorization/predict` + `/categorization/feedback`; mirrors priority.py, multi-label response shape.
- `v1/endpoints/summarization.py` — `/summarization/predict` + `/summarization/feedback`; no 503/unavailable path (nothing pre-trained is required for the default extractive path).
- `__init__.py` files (api/, api/v1/, api/v1/endpoints/) — empty, package markers only.

## backend/app/core/

- `config.py` — Pydantic `Settings` (env-driven), `get_settings()` `@lru_cache`'d singleton; DB/app/logging config, `SECRET_KEY` still a placeholder.
- `logging.py` — structured JSON logging setup (`CustomJsonFormatter`), explicit warning against logging PII/raw bodies.
- `__init__.py` — empty.

## backend/app/config/

- `random_seed.py` — sets global `random`/`numpy` seed (42) at import time; a one-off reproducibility script, prints on import.

## backend/app/data/

- `pipeline_metadata.py` — `PipelineRun` class: records steps/inputs/outputs/checksums for a data-pipeline execution, written to each dataset's `run_metadata.json`.

## backend/app/data_ingestion/

- `dataset_registry.py` — `REGISTRY` dict of `DatasetEntry` (source, license, domain_match, trust_level, known_issues) for every corpus used; central place documenting which datasets are trustworthy. Contains at least one aspirational (never-acquired) entry (`cnn_dailymail`).
- `enron_loader.py` — parses Enron corpus CSV/mbox-style records into a DataFrame.
- `spamassassin_loader.py` — loads SpamAssassin corpus folders (ham/spam) into records; uses latin-1 encoding deliberately.
- `sms_loader.py` — loads SMS Spam Collection CSV into a standardized `label`/`text` DataFrame.
- `amazon_sentiment_loader.py` — loads Amazon Reviews polarity CSV (used for sentiment work, not yet a shipped module).
- `bbc_summary_loader.py` — loads BBC News Summary dataset (articles + human summaries) into a DataFrame; written in Phase 2, first actually wired into training in Phase 6.
- `checksum_utils.py` — SHA-256 checksum generation/verification for raw data files.
- `ingestion_utils.py` — `make_dedup_key` (message-ID or body-hash) and related dedup/validation helpers post-ingestion.

## backend/app/database/

- `session.py` — async SQLAlchemy engine/session setup; defines `DB_CONNECT_TIMEOUT_SECONDS` (3.0s, asyncpg connect timeout) and `DB_WRITE_TIMEOUT_SECONDS` (3.0s, wraps repository writes) — both part of the DB-write-hang mitigation (see technical debt doc); `get_db()` FastAPI dependency; `Base` declarative base.
- `repositories/spam_prediction_repository.py` — writes `SpamPredictionLog` rows.
- `repositories/priority_prediction_repository.py` — writes `PriorityPredictionLog` rows.
- `repositories/category_prediction_repository.py` — writes `CategoryPredictionLog` rows (JSON columns for multi-label).
- `repositories/summary_repository.py` — writes `SummaryLog` rows (no source body/subject stored, by design).
- `__init__.py`, `repositories/__init__.py` — empty.

## backend/app/evaluation/

- `model_evaluator.py` — `evaluate_model()`: accuracy/precision/recall/F1/ROC-AUC/confusion matrix, supports `average` param for multiclass/multilabel (also has multilabel-specific evaluation with Hamming loss).
- `summarization_evaluator.py` — ROUGE-1/2/L scoring against reference summaries (`rouge-score` package); explicitly documents ROUGE's limitations (no truth/paraphrase awareness).
- `__init__.py` — empty.

## backend/app/feature_engineering/

- `content_features.py` — `ContentFeatureExtractor`: length, capitalization, punctuation, structural, keyword-count (spam/urgency/escalation/SLA/category) features from email text.
- `metadata_features.py` — `MetadataFeatureExtractor`: temporal (hour/day/weekend/after-hours) and sender-domain (internal/freemail/external) features.
- `feature_matrix.py` — `build_feature_matrix()`: concatenates TF-IDF + content + metadata arrays into one sparse matrix; optional `scaler`/`fit_scaler` params (additive, Phase 4).
- `feature_models.py` — `ContentFeatures` dataclass (all content-feature fields); grew from Phase 4 to Phase 5 additions.
- `metadata_models.py` — `MetadataFeatures` dataclass (temporal + sender fields).
- `feature_pipeline.py` — `build_tfidf_features()` / `build_metadata_features()` — older/simpler TF-IDF + metadata builder helpers (train/val split fitting).
- `feature_scaler.py` — `EngineeredFeatureScaler` wraps `StandardScaler`, fit-on-train-only discipline.
- `feature_schema.py` — `FeatureSchema`/`FeatureSchemaMismatchError` (Phase 6 Gate 1): fingerprints the ordered engineered-feature-name list a pipeline was fit against; fails loudly at predict time on mismatch instead of a cryptic sklearn shape error. Added after a real Phase 5 incident broke priority's artifact.
- `patterns.py` — compiled regexes: `URL_PATTERN`, `EMAIL_PATTERN`, `PHONE_PATTERN`, `CURRENCY_PATTERN`, `SENTENCE_PATTERN`, `DATE_PATTERN`.
- `category_keywords.py` — per-category (8 FR-21 labels) keyword frozensets; also drives the synthetic category-label generator (documented leakage channel).
- `priority_keywords.py` — `URGENCY_KEYWORDS`/`ESCALATION_KEYWORDS`/`SLA_KEYWORDS` frozensets; also drives the synthetic priority-label generator.
- `spam_keywords.py` — `SPAM_KEYWORDS` frozenset of trigger words.
- `domains.py` — `FREEMAIL_DOMAINS` and `INTERNAL_DOMAINS` (populated with `enron.com` for the Phase 4 synthetic dataset's sender domain).
- `__init__.py` — empty.

## backend/app/inference/

- `classifier_backend.py` — `SpamClassifierBackend` Protocol (dependency-inversion boundary); requires `positive_label` + `predict`/`predict_batch`.
- `priority_classifier_backend.py` — `PriorityClassifierBackend` Protocol (separate from spam's — no threshold/positive_label concept, 4-class argmax).
- `category_classifier_backend.py` — `CategoryClassifierBackend` Protocol; returns `MultiLabelPredictionResult`.
- `prediction_models.py` — `PredictionResult` (single-label) and `MultiLabelPredictionResult` (multi-label) dataclasses shared across all backends.
- `spam_predictor.py` — `SpamPredictor`: loads trained sklearn pipeline via `ArtifactManager`, wraps `predict_proba`; `positive_label = "1"`.
- `priority_predictor.py` — `PriorityPredictor`: loads `PriorityMLPipeline`, takes record dicts (not raw text) due to metadata features.
- `category_predictor.py` — `CategoryPredictor`: loads `CategoryMLPipeline`, returns independent per-label probabilities (not softmax).
- `__init__.py` — empty.

## backend/app/middleware/

- `exception_handlers.py` — `register_exception_handlers()`: global handler returns a uniform error shape, logs internals server-side, never leaks stack traces to clients.
- `request_logging.py` — `RequestLoggingMiddleware` (`BaseHTTPMiddleware` subclass): logs path/status/latency per request; deliberately never logs request bodies (PII risk). Notable: this middleware class is the one investigated (and cleared) in the DB-write-hang investigation.
- `__init__.py` — empty.

## backend/app/ml_models/

- `logistic_regression_model.py` — `train_logistic_regression()` (saga solver, class_weight configurable) + weight-inspection helper.
- `naive_bayes_model.py` — `train_naive_bayes()` (Multinomial/Complement variants).
- `svm_model.py` — `train_svm()` — `LinearSVC` wrapped in `CalibratedClassifierCV` for probability outputs; the model type actually shipped for spam and categorization.
- `multilabel_classifier.py` — `train_multilabel_classifier()` — `OneVsRestClassifier` wrapping Logistic Regression; save/load helpers.
- `hyperparameter_tuning.py` — `tune_logistic_regression()` via `GridSearchCV`; general-purpose tuning helper, not tied to a single module.

## backend/app/models/ (SQLAlchemy ORM)

- `spam_prediction_log.py` — `SpamPredictionLog` table + `GUID` `TypeDecorator` (dual Postgres/SQLite UUID support, shared by all four log models). Stores subject/body directly (no `emails` table exists yet).
- `priority_prediction_log.py` — `PriorityPredictionLog` table; same subject/body-inline pattern as spam.
- `category_prediction_log.py` — `CategoryPredictionLog` table; uses generic `JSON` (not `JSONB`) for `predicted_categories`/`confidences` so SQLite-backed tests work.
- `summary_log.py` — `SummaryLog` table; deliberately does NOT store source body/subject (Step 16 privacy decision) — only the produced summary + metadata.
- `__init__.py` — imports `PriorityPredictionLog`/`SpamPredictionLog` into `Base.metadata` for Alembic autogenerate visibility. **Note: `CategoryPredictionLog` and `SummaryLog` are NOT imported here** — a latent gap (migrations are hand-written so it hasn't bitten yet, but any future `Base.metadata.create_all()`/autogenerate use would miss those two tables).

## backend/app/nlp/ (generation, not classification — Phase 6)

- `extractive_summarizer.py` — `ExtractiveSummarizer`: TextRank (TF-IDF sentence-similarity graph + `networkx` PageRank), default summarization path, sub-100ms.
- `abstractive_summarizer.py` — `AbstractiveSummarizer`: off-the-shelf `sshleifer/distilbart-cnn-6-6` (not fine-tuned), lazy-loaded (`lru_cache`), ~115s cold load, ~3s warm inference.
- `chunking.py` — `split_into_chunks()`/`summarize_long_text()`: map-reduce chunking for abstractive path only (handles the model's context-window limit); extractive doesn't need this.
- `summary_grounding.py` — `check_preservation()`/`extract_entities()` (FR-26): regex for dates/amounts, spaCy NER for names; measures entity preservation rate, doesn't guarantee it.
- `thread_summarizer.py` — `ThreadNormalizer`/`ThreadMessage` (FR-27): chronological ordering, per-message quote/signature stripping, near-duplicate (Jaccard) dedup, single cohesive narrative construction.
- `__init__.py` — empty.

## backend/app/pipeline/

- `ml_pipeline.py` — `MLPipeline`: TF-IDF-only pipeline (spam's shape); wraps `PipelineConfig`/`PipelineFactory`.
- `priority_pipeline.py` — `PriorityMLPipeline`: TF-IDF + `ContentFeatures` + `MetadataFeatures` combined via `build_feature_matrix`; same fit/predict/save/load interface as `MLPipeline` so `Trainer` works unchanged.
- `category_pipeline.py` — `CategoryMLPipeline`: multi-label variant, `OneVsRestClassifier` of 8 binary classifiers; a new class (not a branch on `PriorityMLPipeline`) because fit/predict/predict_proba shapes genuinely differ for multi-label.
- `pipeline_config.py` — `PipelineConfig` dataclass: TF-IDF/LR/NB/SVM hyperparameters, one central config object.
- `pipeline_factory.py` — `PipelineFactory.create_model()`: builds an untrained classifier instance from config + model-type selector.
- `text_pipeline.py` — `build_text_pipeline()`: simple standalone TF-IDF + LogisticRegression sklearn `Pipeline` (used by early smoke tests, not the production path).
- `text_selector.py` — `TextSelector`: sklearn-compatible transformer that extracts a text column/key from dict/DataFrame/list input for use inside a `Pipeline`.

## backend/app/preprocessing/

- `email_preprocessor.py` — `EmailPreprocessor` + `PreprocessingConfig`: the real, reusable preprocessing pipeline (HTML strip, quote/signature removal, URL normalization, lemmatization via spaCy, negation-aware stopword removal). Defines the task-specific configs used everywhere: `SPAM_CONFIG`, `PRIORITY_CONFIG`, `CATEGORY_CONFIG`, `SUMMARY_CONFIG`, `SENTIMENT_CONFIG`.
- `email_preprocessing.py` — `preprocess_email_body()` + `anonymize_pii()` (placeholder, no-op) — an older/simpler, functional-style preprocessing script; appears to predate `email_preprocessor.py` and is not the one wired into production services.
- `text_helpers.py` — module-level spaCy load (`en_core_web_sm`, NER/parser disabled) + stopword/negation helpers; standalone utility functions reused by preprocessing.
- `__init__.py` — empty.

## backend/app/schemas/

- `health.py` — `HealthResponse`/`ReadinessResponse` Pydantic models.
- `spam.py` — `SpamPredictionRequest`/`Response`, `SpamFeedbackRequest`/`Response`.
- `priority.py` — `PriorityPredictionRequest`/`Response`, feedback schemas; most fields optional with documented training-parity defaults.
- `category.py` — mirrors priority.py's shape; multi-label response (`categories: [{category, confidence}]`, `all_scores`).
- `summarization.py` — `SummarizationRequest` (mutually exclusive `body`/`messages`), `ThreadMessageInput`, response with `skipped_short_input`/`preserved_entities`/`entity_preservation_rate`.
- `__init__.py` — empty.

## backend/app/security/

- `pii_anonymizer.py` — `anonymize_email_body()` using Microsoft Presidio (`AnalyzerEngine`/`AnonymizerEngine`); redacts PERSON/EMAIL/PHONE/CREDIT_CARD/DEFAULT. Deliberately NOT used in the summarization path (would destroy names/dates/amounts FR-26 requires preserving).
- `__init__.py` — empty.

## backend/app/services/

- `spam_service.py` — `SpamService`: loads artifact + threshold from `spam_baseline_metrics.json`, applies calibrated threshold (policy lives here, not in the model); `SpamServiceUnavailable` if artifact missing; `get_spam_service()` `lru_cache`'d singleton.
- `priority_service.py` — `PriorityService`: no separate threshold layer (argmax IS the decision); mirrors spam_service's artifact-loading pattern.
- `category_service.py` — `CategoryService`: owns the "zero categories assigned" fallback policy — assigns `["General"]` using the model's own sub-threshold score when every binary classifier says no.
- `summarization_service.py` — `SummarizationService`: orchestrates preprocessing → short-input passthrough (FR-25, 200-word floor) → extractive/abstractive → grounding (FR-26). Extractive warmed at startup; abstractive lazy-loaded (~115s cost deferred to first actual use).
- `feedback_service.py` — `FeedbackLogger`: per-module JSONL append logs (`{module}_feedback.jsonl`); `log_correction()` (scalar or list labels) and `log_summary_feedback()` (accept/reject + quality score). No auto-retraining from feedback.
- `__init__.py` — empty.

## backend/app/splitting/

- `split_pipeline.py` — `assign_corpus_splits()`: train/val/test split by `email_id` via `train_test_split`, seeded.

## backend/app/training/

- `trainer.py` — `Trainer`: train/evaluate/save/load orchestration; `pipeline_cls` param (defaults `MLPipeline`) lets the same class drive `PriorityMLPipeline`/`CategoryMLPipeline` too.
- `artifact_manager.py` — `ArtifactManager`: save/load trained model artifacts (joblib) + JSON metrics to `artifacts/`.
- `logger.py` — `get_logger()`: basic named logger with a plain text formatter (distinct from `app/core/logging.py`'s JSON structured logging — used by training scripts, not the served app).
- `train.py` — `train_model()`: a generic training-workflow wrapper (build config → Trainer → ArtifactManager); appears to be an early/generic entry point, largely superseded by the module-specific `scripts/train_*.py` scripts.
- `__init__.py` — empty.

## backend/app/validation/

- `data_validation.py` — `validate_corpus()`: null-rate/duplicate/label-sanity checks on a DataFrame, returns `ValidationResult` list.

## backend/app/vectorization/

- `bow_vectorizer.py` — `BoWConfig`/`BoWVectorizer`: `CountVectorizer` wrapper, config dataclass + save/load.
- `tfidf_vectorizer.py` — `TFIDFConfig`/`TFIDFVectorizer`: `TfidfVectorizer` wrapper, same config/save/load pattern.
- `__init__.py` — empty.

## backend/app/analysis/

- `eda.py` — `plot_class_distribution()` (matplotlib) + text-length/null/source-distribution analysis helpers used during Phase 2 EDA.

## backend/app/utils/

- `__init__.py` — empty; no other files (directory otherwise unused so far).

## backend/app/main.py, app/__init__.py

- `main.py` — `create_app()` factory + `lifespan()` startup hook that eagerly warms spam/priority/category/summarization (extractive only) services so first-request latency isn't paid by a real user; failures during warm-up are logged, not fatal.
- `__init__.py` — empty.

---

## backend/scripts/ (training, data generation, investigation)

**Production/reusable training + evaluation scripts:**
- `train_spam_model.py` — Phase 3: trains/compares LR/NB/SVM on SpamAssassin, picks best by recall, writes `artifacts/spam_baseline.joblib`.
- `train_priority_model.py` — Phase 4: trains on `priority_synthetic_v1` (SYNTHETIC, see data audit), writes `artifacts/priority_baseline.joblib`.
- `train_category_model.py` — Phase 5: trains multi-label One-vs-Rest on `category_synthetic_v1` (SYNTHETIC), writes `artifacts/category_baseline.joblib`.
- `generate_synthetic_priority_dataset.py` — Phase 4: generates `priority_synthetic_v1` from real Enron text via keyword-heuristic labels + injected noise (NOT ground truth — explicitly disclosed in-file).
- `generate_synthetic_category_dataset.py` — Phase 5: same pattern, multi-label, per-category adaptive keyword thresholds.
- `prepare_summarization_dataset.py` — Phase 6: builds `summarization_bbc_v1` from the real (but off-domain) BBC News Summary corpus.
- `evaluate_summarization_models.py` — Phase 6: extractive-vs-abstractive comparison on a bounded BBC test sample, writes `artifacts/summarization_model_comparison.json`.
- `check_priority_calibration.py` — Phase 4 follow-up: confidence-calibration check (binned confidence vs. accuracy + Brier score) for the shipped priority model.

**One-off experiment scripts (not part of the production path, don't write artifacts):**
- `experiment_class_weight_tuning.py` — sweeps spam:ham class-weight ratios to see if the FR-11 recall gap can close further than `class_weight="balanced"`.
- `experiment_priority_class_weight.py` — single documented comparison of `class_weight="balanced"` vs. `None` for priority's LR model.

**DB-write-hang investigation scripts (Phase 6 Gate 2, `docs/technical_debt/database_write_hang.md`):**
- `investigate_db_hang.py` — the main reproduction harness: fake stuck-Postgres TCP server + real Uvicorn subprocess + real HTTP request. Confirms the hang.
- `_investigate_bare_asyncio_cancel.py` — isolates bare `asyncio.wait_for` cancellation of a hung socket read (no asyncpg/SQLAlchemy). Cancels correctly.
- `_investigate_asyncpg_direct_cancel.py` — isolates `asyncio.wait_for` around a hung `asyncpg.connect()`. Cancels correctly.
- `_investigate_sqlalchemy_direct_cancel.py` — isolates `asyncio.timeout()` around a hung SQLAlchemy async engine connect. Cancels correctly.
- `_investigate_threadpool_then_sqlalchemy.py` — isolates the exact `run_in_threadpool` → `wait_for`-wrapped-SQLAlchemy sequence, bare asyncio (no FastAPI). Cancels correctly.
- `_investigate_middleware_smoking_gun.py` — same sequence as above, run with and without `BaseHTTPMiddleware`, via real Uvicorn. Cancels correctly both ways — rules out middleware as sole cause.
- All five `_investigate_*` scripts are deliberate one-off diagnostics, not part of the test suite or CI.

**`backend/scripts/data/` — small placeholder/toy scripts (produce the 3-row test fixture referenced in `docs/data_audit_priority.md` as `data/processed/v1.0`):**
- `assign_splits.py` — writes a tiny 3-row `splits.parquet`.
- `build_artifacts.py` — writes `VERSION.md` for `data/processed/v1.0`.
- `preprocess.py` — writes a tiny 3-row `train.parquet` with dummy spam labels.
- `ingest.py`, `validate.py`, `verify_checksums.py` — **empty files** (0 bytes), unimplemented placeholders.

**`backend/scripts/__pycache__/`** — compiled bytecode cache, not source (ignore).

## backend/alembic/versions/ (hand-written migrations — no live Postgres available to autogenerate against)

- `aaf9453abf37_create_spam_prediction_logs_table.py` — creates `spam_prediction_logs` (first migration, no down_revision). Uses native Postgres UUID (not the app's `GUID` TypeDecorator — migrations only ever target real Postgres).
- `57e9d6e5012d_create_priority_prediction_logs_table.py` — creates `priority_prediction_logs`.
- `83169e56d48c_create_category_prediction_logs_table.py` — creates `category_prediction_logs`; uses generic `sa.JSON()` (not `JSONB`) to match the SQLite-testable model.
- `f4a71c9d2e83_create_summary_logs_table.py` — creates `summary_logs`; no subject/body columns (matches the model's privacy decision).

---

## backend/tests/ (real pytest suite — 151 tests + 1 opt-in slow test)

- `conftest.py` — shared `client` fixture (`TestClient(create_app())`, no lifespan events run).
- `test_health.py` — liveness endpoint only (readiness needs a live DB, not covered here).
- `test_startup_warmup.py` — proves `lifespan()` eagerly warms spam/priority services (`with TestClient(app) as client:` needed to trigger lifespan).
- `test_db_write_timeout.py` — regression test proving `asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS)` bounds a hanging DB commit **in the `TestClient` fake-transport harness** — does NOT prove the real-Uvicorn case (see technical debt doc).
- `test_email_preprocessor.py` — `EmailPreprocessor` regression cases (empty string, HTML, quotes, signatures).
- `test_feature_schema.py` — `FeatureSchema` determinism + mismatch-detection (Phase 6 Gate 1 hardening).
- **Spam**: `test_spam_classifier_backend.py` (Protocol boundary proof w/ fake backend), `test_spam_endpoint.py` (integration, real artifact), `test_spam_prediction_log.py` (DB audit log, in-memory SQLite), `test_spam_service_unavailable.py` (503 on missing artifact).
- **Priority**: `test_priority_dataset.py` (dataset quality/leakage-safe split), `test_priority_endpoint.py` (integration), `test_priority_pipeline.py` (unit, `PriorityMLPipeline` incl. save/load), `test_priority_prediction_log.py` (DB audit log), `test_priority_service_unavailable.py` (503 path).
- **Category**: `test_category_dataset.py`, `test_category_endpoint.py`, `test_category_pipeline.py`, `test_category_prediction_log.py`, `test_category_service_unavailable.py` — mirror priority's five, adapted for multi-label.
- **Summarization**: `test_summarization_dataset.py` (BBC dataset quality, real-but-off-domain disclosure), `test_summarization_endpoint.py` (integration, no artifact gate needed), `test_summarization_endpoint_concurrency.py` (regression: abstractive warm-up must run in threadpool, not block the event loop), `test_summarization_security.py` (prompt-injection inertness + no PII anonymization-by-design), `test_summarization_service.py` (unit, abstractive monkeypatched), `test_summary_grounding.py` (real spaCy NER entity-preservation), `test_summary_prediction_log.py` (DB audit log, confirms no source body stored), `test_thread_summarizer.py` (FR-27 narrative construction), `test_chunking.py` (map-reduce chunk splitting), `test_extractive_summarizer.py` (TextRank unit tests), `test_abstractive_summarizer_slow.py` (real ~115s model download/inference, opt-in via `RUN_SLOW_TESTS=1`, skipped by default).

## backend/ (root-level `test_*.py`) — informal smoke-test scripts, NOT pytest suite (no assertions, just prints; run manually during early development)

- `test_amazon_loader.py`, `test_bbc_loader.py`, `test_enron_loader.py`, `test_loader.py` (SpamAssassin), `test_sms_loader.py` — exercise each `data_ingestion` loader against real raw files, print row counts/columns.
- `test_checksum.py` / `test_checksum_verify.py` — exercise `checksum_utils` save/verify against `data/raw/enron/emails.csv`.
- `test_registry.py` — prints every `dataset_registry.REGISTRY` entry.
- `test_ingestion_utils.py` — exercises dedup/validation helpers on inline dummy data.
- `test_data_validation.py` — exercises `validate_corpus()` on inline dummy data.
- `test_eda.py` — exercises EDA plotting/analysis helpers on inline dummy data.
- `test_email_preprocessing.py` — exercises the older `email_preprocessing.preprocess_email_body()` function.
- `test_email_preprocessor.py` — exercises the real `EmailPreprocessor` + named configs on a sample HTML email.
- `test_text_helpers.py` — exercises `preprocessing/text_helpers.py` functions individually.
- `test_patterns.py` — exercises regex patterns against a sample text block.
- `test_pii.py` — exercises Presidio-based `anonymize_email_body()`.
- `test_spam_keywords.py` — prints `SPAM_KEYWORDS` contents/count.
- `test_content_features.py`, `test_feature_models.py`, `test_metadata_features.py`, `test_feature_matrix.py`, `test_feature_scaler.py`, `test_feature_engineering.py` — exercise feature-engineering extractors/dataclasses/scaler on inline samples.
- `test_bow_vectorizer.py`, `test_tfidf_vectorizer.py`, `test_tfidf_fit.py`, `test_ngram_comparison.py` — exercise vectorizer wrappers on tiny inline corpora.
- `test_logistic_regression.py`, `test_naive_bayes.py`, `test_svm.py`, `test_multilabel_classifier.py`, `test_hyperparameter_tuning.py`, `test_model_comparison.py`, `test_model_evaluator.py` — exercise individual `ml_models`/`evaluation` functions on tiny inline corpora.
- `test_ml_pipeline.py`, `test_text_pipeline.py`, `test_trainer.py` — exercise pipeline/trainer classes end-to-end on tiny inline corpora.
- `test_spam_predictor.py` — exercises `SpamPredictor` against a `trainer_test.joblib` fixture artifact.
- `test_split_pipeline.py` — exercises `assign_corpus_splits()` on inline dummy data.
- `test_pipeline_metadata.py` — exercises `PipelineRun` metadata recording (this is the "dummy_checksum_123" test fixture referenced by `docs/data_audit_priority.md` as `data/processed/v1.0`).
- `test_kappa.py` — standalone `cohen_kappa_score` demo on two dummy annotator lists (not tied to real annotation data — none exists yet).
- `test_sentence_embeddings.py` — standalone `sentence-transformers` (`all-MiniLM-L6-v2`) smoke test; exploratory, not wired into any production module.

---

## docs/*.md

- `architecture.md` — Phase 1 foundation doc: modular-monolith rationale, deferred infra (Kafka/K8s/RAG/real auth), layer responsibilities, liveness/readiness split, module doc index.
- `architecture_spam_detection.md` — Phase 3-4 spam module architecture: request flow, `SpamClassifierBackend` Protocol dependency-inversion rationale, threshold-in-service-layer decision.
- `architecture_priority_classification.md` — Phase 4 priority module architecture: request flow, shared-infrastructure extensions table, first documentation of the DB-write-hang symptom.
- `architecture_email_categorization.md` — Phase 5 categorization module architecture: multi-label pipeline rationale, documents the real cross-module incident (ContentFeatures extension broke priority's artifact).
- `architecture_email_summarization.md` — Phase 6 summarization module architecture: request flow, why `app/nlp/` not `app/pipeline/`, first generation-task module.
- `data_audit_priority.md` — Phase 4 data gate: zero real priority-labelled emails exist; documents `priority_synthetic_v1`'s heuristic generation and why it's pipeline-validation-only, not PRD-compliant.
- `data_audit_categorization.md` — Phase 5 data gate: PRD-named TREC dataset doesn't exist/wouldn't fit; documents `category_synthetic_v1`'s heuristic generation, same not-PRD-compliant conclusion.
- `data_audit_summarization.md` — Phase 6 data gate: PRD-named CNN/DailyMail and XSum datasets absent; documents use of real-but-off-domain BBC News Summary instead.
- `annotation_guidelines_categorization.md` — full spec for the NOT-YET-STARTED real categorization annotation effort (category definitions, inclusion/exclusion rules) — a forward-looking process doc, not a record of completed work.
- `categorization_label_quality_report.md` — formally classifies `category_synthetic_v1` as **UNTRUSTWORTHY (synthetic)**; documents dataset size/split/methodology.
- `phase6_requirements_traceability.md` — FR-25 to FR-28 extracted from the PRD, mapped to design/implementation/test/evidence; also tracks non-functional requirements (latency, ROUGE/BERTScore) and explicitly-deferred items (BERTScore, fine-tuning).
- `git_workflow.md` — branch strategy (`main`/`develop`/`feature/*`/`fix/*`) and Conventional Commits convention.
- `technical_debt/database_write_hang.md` — **Status: MITIGATED, NOT ROOT-CAUSED (PARTIAL).** Full investigation record of the reproduced DB-write hang; seven isolation experiments, suspected-but-unconfirmed root causes (real ORM write path, `GUID` TypeDecorator, full `create_app()` assembly interaction), recommended next steps (isolate real ORM write, run full-middleware smoking gun, capture a live stack trace via `py-spy`/`faulthandler`).

## docs/model_cards/*.md

- `spam_detection.md` — SVM (calibrated, TF-IDF) chosen over LR/NB; recall 0.9944 / precision 0.9133 at threshold 0.06; real, PRD-relevant metrics.
- `priority_classification.md` — Logistic Regression on synthetic data; **not PRD-compliant** (banner warning); documents a Phase 5 forced retrain after `ContentFeatures` grew.
- `email_categorization.md` — Calibrated One-vs-Rest SVM on synthetic data; **not PRD-compliant**; documents the "General fallback" policy and unverified per-category calibration.
- `email_summarization.md` — Extractive (TextRank, default) + abstractive (distilbart-cnn-6-6, opt-in) comparison; evaluated on real-but-off-domain BBC data; documents abstractive's ~4.5s avg / ~7.6s P95 latency (exceeds PRD SLA) as why extractive is the default.

## data/**

- `annotations/guidelines/annotation_guidelines_v1.0.md` — early label definitions (spam + others) with 2 illustrative examples per class; no full annotator process yet (superseded in scope by `docs/annotation_guidelines_categorization.md` for categorization).
- `annotations/exports/`, `annotations/iaa_reports/`, `annotations/label_studio_exports/` — empty (`.gitkeep` only or fully empty) — annotation effort has not started.
- `checksums/README.md` — explains purpose of the checksums folder (reproducibility/change-detection); folder otherwise unused.
- `processed/v1.0/` — a 3-row **test fixture** (`train.parquet`, `splits.parquet`, `VERSION.md`, `run_metadata.json` with `sha256: "dummy_checksum_123"`), produced by `backend/scripts/data/*.py` toy scripts and `test_pipeline_metadata.py` — not real project data, referenced explicitly as such in `docs/data_audit_priority.md`.
- `processed/priority_synthetic_v1/` — real output of `generate_synthetic_priority_dataset.py`: 10,000 rows (7,000/2,121/879 train/val/test), Critical/High/Medium/Low heuristic labels, `run_metadata.json` marks `SYNTHETIC: true, PRD_COMPLIANT: false`.
- `processed/category_synthetic_v1/` — real output of `generate_synthetic_category_dataset.py`: 10,000 rows (7,000/2,121/879), multi-label, same synthetic/not-PRD-compliant marking.
- `processed/summarization_bbc_v1/` — real output of `prepare_summarization_dataset.py`: BBC News Summary train/val/test splits, real human summaries but wrong domain.
- `raw/spamassassin/` — real corpus, 6,101 files across `easy_ham`/`easy_ham_2`/`hard_ham`/`spam`/`spam_2` subfolders.
- `raw/enron/` — real corpus (`emails.csv` + checksum); backing source for both synthetic datasets.
- `raw/sms_spam/spam.csv` — real SMS Spam Collection corpus.
- `raw/amazon_reviews/amazon_review_polarity_csv/` — real Amazon Reviews polarity corpus (train/test CSVs), used for sentiment exploration, no shipped module yet.
- `raw/cnn_dailymail/BBC News Summary/` — real BBC News Summary corpus (2,225 articles+summaries; ~8,900 files); misleadingly nested under a `cnn_dailymail`-named folder (leftover from an abandoned early download of the PRD-named dataset) — actual content is BBC, not CNN/DailyMail.
- `raw/custom/`, `raw/twitter_sentiment/`, `raw/xsum/`, `external/cleaned_public/` — empty placeholders (`.gitkeep` only), never populated.
- `interim/{cleaned,deduplicated,parsed}/` — empty placeholders, intermediate-processing stage never used yet.
- `validation/` — two PNG plots (`spam_label_distribution.png`, `word_count_distribution.png`) from Phase 2 EDA, plus `.gitkeep`.
- `artifacts/` — empty placeholder (distinct from the repo-root `artifacts/` dir which holds the real trained model files — that root dir is out of scope for this catalog per the task's directory list).
- `processed/v1.0.dvc`, `processed/priority_synthetic_v1.dvc` — DVC pointer files for the versioned datasets.

---

## project document/

- `PRD_AI_Email_Intelligence_System.md` — the full v1.0.0 Product Requirement Document (source of every FR-xx requirement cited throughout the codebase/docs); 15-phase roadmap, functional/non-functional requirements, data requirements, evaluation metrics, milestones. Read for phase structure only — not re-summarized here in full; see README.md's progress table for the phase-by-phase status mapping.

## Root files

- `README.md` — primary project overview: progress table, architecture diagram (color-coded real/synthetic/off-domain), quickstart, known gaps list. Read first in any new session.
