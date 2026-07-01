# AI Email Intelligence System

> **Status:** Phase 1 — Project Foundation. Modular monolith, no Kafka/K8s/microservices yet (deliberately — see `docs/architecture.md`).

## What's Here (Phase 1 Scope Only)

A FastAPI backend with: layered modular architecture, async PostgreSQL
session handling, structured JSON logging, centralized config via
`pydantic-settings`, request logging + global error handling middleware,
liveness/readiness health checks, Dockerized local dev stack, and a working
pytest suite.

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

## Project Structure

```
backend/
├── app/
│   ├── api/v1/         # versioned routes
│   ├── core/            # config, logging — cross-cutting
│   ├── database/        # async SQLAlchemy session management
│   ├── middleware/       # request logging, global error handling
│   ├── models/           # SQLAlchemy ORM (empty until Phase 2+)
│   ├── schemas/          # Pydantic request/response contracts
│   ├── services/         # business logic (empty until Phase 2+)
│   └── main.py           # app factory
├── tests/
├── requirements.txt
└── requirements-dev.txt
docker/Dockerfile
docker-compose.yml
docs/
├── architecture.md       # what was decided and why, what's deferred
└── git_workflow.md
```

## Docs

- [`docs/architecture.md`](docs/architecture.md) — Phase 1 architecture decisions, what's deliberately deferred, layer responsibilities.
- [`docs/git_workflow.md`](docs/git_workflow.md) — branching, commit conventions.

## Next (Phase 2)

Dataset collection & EDA — see project PRD. Nothing in `ai_models/`,
`data/`, or `notebooks/` yet by design; they're scaffolded but empty until
there's real data to put in them.
