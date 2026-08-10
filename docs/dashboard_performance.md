# Dashboard Performance (Module 11 / Phase 11, Stage 15)

## What was actually measured

Real, warm-process latency against a disposable Postgres 16 container,
via `TestClient` (not mocked): every `/dashboard/*` GET endpoint
returned in low tens of milliseconds at this project's current data
volume (a handful of rows per table — no real production traffic
exists yet, see `PHASE_11_AUDIT_REPORT.md`). CSV export: ~1.9KB in
well under 100ms. PDF export (`reportlab`): ~4.4KB in well under 200ms.
These numbers are **only meaningful at today's data volume** — see
below for what changes as real volume grows.

## Known, disclosed scaling limits (not fixed this phase)

1. **Python-side aggregation, not SQL-side.** Every dashboard query
   fetches matching rows and buckets/aggregates them in Python
   (`app/services/dashboard_service.py`), not via SQL `GROUP BY`/
   `date_trunc`/window functions. Chosen deliberately for portability —
   this codebase's DB tests run against SQLite (aiosqlite), and Postgres-
   only aggregation SQL would need a second code path or abandon that
   test strategy. At real production volume, this needs to become
   SQL-side aggregation; the migration path is per-function (each
   `get_*` function in `dashboard_service.py` is independently
   replaceable) since none of them share a query-building abstraction
   that would need a bigger rewrite.
2. **Review Queue scans up to 500 rows per module, per request**
   (`_QUEUE_SCAN_CAP` in `dashboard_service.py`) — an adversarial-review
   fix (see `docs/error_analysis_dashboard.md`) that bounds what was
   previously a genuinely unbounded full-table scan, but is itself only
   a mitigation, not a real solution. A correct "globally most urgent
   across all history" ranking at real volume needs either a
   materialized/indexed low-confidence view or a background job that
   maintains one — not built this phase.
3. **No indexes on `feedback_events.action`/`confidence` individually**
   beyond the composite `(organization_id, created_at)` and
   `(module, action)` indexes — correction-rate queries filter by
   `module` + `organization_id` + date range, which the existing
   indexes cover; a future `confidence`-bucketed query at scale may
   need its own index once real data volume makes that query slow.
4. **In-process WebSocket broadcaster** (`dashboard_broadcaster.py`) —
   only clients connected to the same API process receive push updates.
   If this API ever runs as multiple replicas, cross-replica updates
   require Redis pub/sub or similar — explicitly not built, per the
   master prompt's own "no Kafka/Redis" instruction. The 30s polling
   fallback (`hooks/useDashboardData.ts`'s `refetchInterval`) is what
   makes this degrade gracefully instead of silently under-delivering.
5. **No scheduled report generation.** FR-56's "auto-generated weekly"
   is implemented as an on-demand export endpoint — no scheduler/cron
   dependency exists in this codebase (would be a new infrastructure
   decision, disclosed as out of scope rather than silently narrowed).

## What was verified NOT to regress

The dashboard's own queries run against tables Spam/Priority/etc.'s
`*/predict` endpoints also write to, on the same connection pool
(`pool_size=5, max_overflow=10` — `app/database/session.py`, unchanged
this phase). Every dashboard query is a `SELECT`, and every ML endpoint's
own write is still wrapped in its existing `DB_WRITE_TIMEOUT_SECONDS`
bound — dashboard read load does not change any ML endpoint's own
write-path behavior. Full regression suite (461 tests, spanning every
module) passed unmodified after every Phase 11 change, confirming no
existing endpoint's behavior shifted.

## Frontend

`npm run build` (`tsc -b && vite build`) succeeds; production bundle is
~655KB unminified/~195KB gzipped as one chunk — large enough that Vite's
own build output warns about it, but not code-split, since a 10-page
internal manager dashboard with no real users yet does not currently
justify the added complexity of route-based code-splitting. Documented
as a disclosed, deliberate non-optimization, not an oversight.
