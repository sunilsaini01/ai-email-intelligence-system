# Analytics Data Model (Module 11 / Phase 11)

Full design rationale lives in `docs/architecture_dashboard.md` §1 —
this is the short reference version: what exists, where, and why no
separate `dashboard_metrics`/`sla_events`/`agent_workload_metrics`
tables were built.

## New tables

| Table | Purpose | Key columns |
|---|---|---|
| `feedback_events` | Unified, queryable home for every correction/confirmation/relevance judgment across all 9 modules (FR-58–62) | `module`, `action` (CORRECTION\|CONFIRM\|ACCEPT\|REJECT\|RELEVANCE), `prediction_id`, `original_value`/`corrected_value` (JSON), `confidence`, `reviewer_id`, `organization_id` |
| `retraining_triggers` | FR-61's threshold-crossing audit log — one row per crossing, nothing else | `module`, `feedback_count_at_trigger`, `threshold_used`, `consumed` |

## Modified tables

- `emails`: `+priority` (nullable, caller-supplied snapshot — same
  pattern as `category`/`department`), `+resolved_at` (set only on a
  real transition into `RESOLVED`).
- `spam_prediction_logs`, `priority_prediction_logs`,
  `category_prediction_logs`, `summary_logs`,
  `sentiment_prediction_logs`, `intent_prediction_logs`,
  `routing_decision_logs`: `+organization_id` (model-level default,
  zero application-code changes to the six `*/predict` endpoints).
- New composite indexes: `(organization_id, created_at)` on all 8
  prediction/log tables (none existed before — audit finding), plus
  `(organization_id, received_at)` on `emails`.

Migration: `backend/alembic/versions/d1e9a4c73f58_phase11_dashboard_schema.py`.
Verified via a real, disposable Postgres 16 container — full upgrade →
downgrade → upgrade round-trip, plus a genuine ORM insert/read round-trip
against every new/changed column (not just the migration DDL in
isolation).

## Why not `dashboard_metrics`/`sla_events`/`agent_workload_metrics`

Every one of these would duplicate data already sitting in the eight
existing tables. The dashboard reads and aggregates on request
(`app/services/dashboard_service.py`) instead of maintaining a
parallel, eventually-inconsistent copy — consistent with "avoid
unnecessary duplication" and this codebase's existing precedent (Routing
never got its own prediction artifact table either; it composes).

## Why `email_id` was NOT added to the six prediction tables

Considered and rejected — see `docs/architecture_dashboard.md` §1's
"email_id was considered and deliberately dropped" note. `emails.priority`
solves the one feature (SLA) that actually needed a priority↔email link,
without adding schema surface nothing would populate.

## Aggregation strategy

Python-side, not SQL `date_trunc`/window functions — this codebase's DB
tests run against SQLite (aiosqlite), and every existing repository is
deliberately dialect-portable. At this project's actual data volume (no
real production traffic exists yet), this is simple, correct, and
sufficient. **Not** how this should be done once real volume exists —
see `docs/dashboard_performance.md` for the disclosed scaling limit and
what would need to change.
