# AI Email Intelligence System

> **Status:** Phase 4 of 15 (PRD phase numbering). Modular monolith, no
> Kafka/K8s/microservices yet — deliberately, see `docs/architecture.md`.
> Full PRD: [`project document/PRD_AI_Email_Intelligence_System.md`](project%20document/PRD_AI_Email_Intelligence_System.md).

## Progress

| Phase | Module | Status |
|---|---|---|
| 1 | Problem Discovery & PRD | ✅ Done |
| 2 | Dataset Collection & EDA | ✅ Done |
| 3 | Spam Detection | ✅ Done — TF-IDF + calibrated SVM, 99.44% recall / 91.33% precision on held-out test |
| 4 | Priority Classification | 🟡 Pipeline complete, **trained on synthetic data — not PRD-compliant**. See `docs/data_audit_priority.md`. |
| 5–15 | Categorization, Summarization, Sentiment/Intent, Routing, RAG, Auto-Reply, Dashboard, CI/CD, Cloud, MLOps | ⬜ Not started |

**Read this before trusting any priority-classification metric**: Phase 4's
model is trained on heuristically-labelled synthetic data (real Enron email
text, fabricated labels), not human annotation. This is disclosed
everywhere it matters — `docs/data_audit_priority.md`,
`docs/model_cards/priority_classification.md`, the dataset's own
`run_metadata.json` — because presenting synthetic-data metrics as
real-world evidence would be actively misleading. Spam's metrics are real
and PRD-relevant; priority's are pipeline-validation only.

## What's Here

**Backend**: FastAPI (async), layered architecture (`api` / `services` /
`models` / `schemas`), async PostgreSQL via SQLAlchemy 2.0 + asyncpg,
Alembic migrations, structured JSON logging, request logging + global error
handling middleware, liveness/readiness health checks, eager ML-model
warm-up at startup, Dockerized local dev stack.

**ML modules**, each following the same pattern (data audit → feature
engineering → baseline model comparison → calibration → served API →
DB-backed audit logging → human-feedback endpoint):

| | Spam Detection | Priority Classification |
|---|---|---|
| Model | TF-IDF + calibrated Linear SVM | TF-IDF + engineered features + Logistic Regression |
| Endpoint | `POST /api/v1/spam/predict` | `POST /api/v1/priority/predict` |
| Feedback | `POST /api/v1/spam/feedback` | `POST /api/v1/priority/feedback` |
| Model card | [`docs/model_cards/spam_detection.md`](docs/model_cards/spam_detection.md) | [`docs/model_cards/priority_classification.md`](docs/model_cards/priority_classification.md) |
| Architecture | [`docs/architecture_spam_detection.md`](docs/architecture_spam_detection.md) | [`docs/architecture_priority_classification.md`](docs/architecture_priority_classification.md) |

Both models are swappable behind a `typing.Protocol` boundary
(`SpamClassifierBackend` / `PriorityClassifierBackend`) — a future
transformer model replaces the concrete predictor class without an API
change.

**Data pipeline**: DVC-versioned datasets, a dataset registry that records
domain-match/trust-level per source (so a low-quality dataset can't
silently feed a model without a documented reason), checksum-verified
ingestion, task-aware preprocessing (`EmailPreprocessor` with per-task
configs), reusable content/metadata feature extractors
(`app/feature_engineering/`).

**Testing**: 50 tests across data validation, model behavior, API contracts,
and DB persistence — `pytest`, `pytest-asyncio`, `aiosqlite` for DB tests
without a live Postgres.

## Quickstart

```bash
# Local (no Docker)
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
make run            # from project root
make test           # from project root

# Docker (API + Postgres)
cp backend/.env.example backend/.env
make docker-up
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/ready
```

API docs (auto-generated): `http://localhost:8000/docs`

To exercise the trained models, artifacts are already committed under
`artifacts/`. To retrain from scratch:

```bash
cd backend
PYTHONPATH=. python scripts/train_spam_model.py
PYTHONPATH=. python scripts/generate_synthetic_priority_dataset.py
PYTHONPATH=. python scripts/train_priority_model.py
```

**Troubleshooting**: if you already have Postgres installed natively on this
machine, it's probably also listening on port 5432 — see the comment above
`ports:` in `docker-compose.yml` for what that looks like and how to work
around it (map to a different host port, e.g. `5433:5432`, and set
`POSTGRES_PORT` in `backend/.env` to match).

## Project Structure

```
backend/
├── app/
│   ├── api/v1/endpoints/       # spam.py, priority.py, health.py
│   ├── core/                    # config, logging — cross-cutting
│   ├── data_ingestion/          # corpus loaders + dataset_registry.py
│   ├── database/                # async session, repositories/
│   ├── evaluation/              # shared multiclass/binary model_evaluator
│   ├── feature_engineering/     # content/metadata feature extractors, keyword lexicons
│   ├── inference/                # SpamPredictor/PriorityPredictor + Protocol backends
│   ├── middleware/               # request logging, global error handling
│   ├── models/                   # SQLAlchemy ORM (*_prediction_log.py)
│   ├── pipeline/                  # PipelineConfig/Factory, MLPipeline, PriorityMLPipeline
│   ├── preprocessing/             # EmailPreprocessor + task-specific configs
│   ├── schemas/                   # Pydantic request/response contracts
│   ├── services/                  # spam_service, priority_service, feedback_service
│   ├── training/                  # Trainer, ArtifactManager
│   └── main.py                    # app factory + startup warm-up
├── alembic/                        # DB migrations
├── scripts/                        # training + dataset generation scripts
├── tests/
├── requirements.txt
└── requirements-dev.txt
artifacts/                          # trained model artifacts + versioned copies
data/                                # DVC-tracked datasets (raw/processed)
docker/Dockerfile
docker-compose.yml
docs/
├── architecture.md                     # Phase 1 decisions + module doc index
├── architecture_spam_detection.md
├── architecture_priority_classification.md
├── data_audit_priority.md              # data strategy decision — read before priority's model card
├── model_cards/
└── git_workflow.md
project document/
└── PRD_AI_Email_Intelligence_System.md
```

## Docs

- [`docs/architecture.md`](docs/architecture.md) — Phase 1 decisions, what's deliberately deferred, module doc index.
- [`docs/data_audit_priority.md`](docs/data_audit_priority.md) — the Phase 4 data blocker, label taxonomy, and the synthetic-data strategy decision. Read this before trusting any priority metric.
- [`docs/architecture_spam_detection.md`](docs/architecture_spam_detection.md) / [`docs/model_cards/spam_detection.md`](docs/model_cards/spam_detection.md)
- [`docs/architecture_priority_classification.md`](docs/architecture_priority_classification.md) / [`docs/model_cards/priority_classification.md`](docs/model_cards/priority_classification.md)
- [`docs/git_workflow.md`](docs/git_workflow.md) — branching, commit conventions.

## Known Gaps (tracked, not hidden)

- **Priority classification needs real annotated data** (10,000+ emails, 3 annotators, Cohen's Kappa ≥ 0.70) to be PRD-compliant — the single biggest open item. See `docs/data_audit_priority.md` §4.
- A DB-write hang under the live request path on Windows is not yet root-caused (`docs/architecture_priority_classification.md` "Performance").
- FR-18 (Critical → notification) and FR-17's sender-history signal have no supporting infrastructure yet — both require modules that don't exist (notification service, persistent sender history) rather than being an oversight in this module.

## Next (Phase 5)

Blocked on the annotation effort above before more ML modules compound the
same data problem. See each module's architecture doc for its own "Known
Gaps" section for smaller, unblocked follow-ups.
