# Error Analysis — Manager Dashboard (Module 11 / Phase 11, Stage 17)

Real bugs found during this phase's own adversarial review pass
(Stage 17's explicit checklist), each verified against a real disposable
Postgres 16 container or a real pytest run before being called fixed —
not theorized, not assumed away by unit tests alone.

## 1. SLA calculation crashed on real Postgres-vs-SQLite datetime handling

**Found via**: running `tests/test_dashboard_service.py`'s SLA tests
against the in-memory SQLite engine this codebase's DB tests use.

**Root cause**: SQLite has no true timezone-aware column type —
`DateTime(timezone=True)` columns round-trip as **naive** datetimes
under aiosqlite, even though the same column is genuinely tz-aware
under real Postgres. `get_sla()` computed `(resolved_at_or_now -
received_at)`, mixing a tz-aware `datetime.now(UTC)` with a naive
`received_at` read back from the DB — `TypeError: can't subtract
offset-naive and offset-aware datetimes`.

**Fix**: defensive normalization — if a fetched datetime is naive,
attach `UTC` explicitly before arithmetic (this codebase's only
timezone; every writer already uses `datetime.now(UTC)`). See
`app/services/dashboard_service.py::get_sla`.

**Why this matters beyond the test failure**: this same code path runs
against real Postgres in production, where columns ARE tz-aware — the
bug was invisible there. It surfaced only because this phase's tests
follow this project's own established convention of testing against
SQLite. Had this shipped without dialect-portable tests, the SLA
endpoint would have worked in every manual/demo check (real Postgres)
and only crashed once someone's test harness (or a future SQLite-backed
environment) exercised it.

## 2. Custom date ranges relied on accidental Postgres session-timezone behavior

**Found via**: adversarial review Stage 17's explicit "timezone errors"
checklist item, verified by sending a naive (no UTC offset) custom
range — exactly what an HTML `datetime-local` input produces, which is
what this phase's own `DateRangePicker.tsx` uses — against a real
Postgres container.

**Root cause**: `resolve_date_range()` passed a naive `start`/`end`
straight into SQLAlchemy `.where()` filters against `TIMESTAMPTZ`
columns. It happened to return correct-looking results, because
asyncpg/Postgres interprets a naive timestamp parameter against the
session's timezone — which is UTC by default in this project's
docker-compose, but is a property of the deployment, not something this
code enforced or verified. A differently-configured Postgres instance
(non-UTC session timezone) would have silently misinterpreted every
custom-range filter.

**Fix**: naive `start`/`end` are now normalized to UTC explicitly in
`resolve_date_range()` before use, matching the same defensive pattern
as fix #1 — correctness no longer depends on an unstated assumption
about the database server's configuration.

## 3. Double-clicking "Confirm" on the Review Queue could race and duplicate a review

**Found via**: adversarial review Stage 17's explicit "duplicate
feedback" checklist item — reasoning through what happens if the same
`POST /dashboard/review-queue/{id}/confirm` request is submitted twice
before the first one's response causes the queue to refresh (a real,
plausible human behavior, not a contrived attack).

**Root cause**: `confirm_review_item()` had no guard against a
prediction_id that already had a `feedback_events` row — two rapid
requests could both pass whatever check existed (none) and each insert
a `CONFIRM` row for the same prediction, silently double-counting one
real review as two in FR-62's correction-rate denominator.

**Fix**: `confirm_review_item()` now checks
`FeedbackEventRepository.get_reviewed_prediction_ids()` before
inserting and raises `AlreadyReviewedError` (mapped to HTTP 409) if the
prediction was already reviewed. Verified with a real test that fires
the same confirm request twice and asserts exactly one `feedback_events`
row exists afterward (`tests/test_dashboard_endpoint.py`).

**Disclosed residual limitation**: this is a check-then-insert guard,
not an atomic database constraint — a sufficiently precise race
(two requests reaching the check within the same event-loop tick,
before either commits) could still both pass. A fully atomic fix would
need a partial unique index on `feedback_events`, deliberately not
added this phase because the correct partial-index condition differs
by module (classifier modules should be unique per prediction;
retrieval/auto-reply's RELEVANCE judgments legitimately may recur for
the same `prediction_id` from different reviewers) — solving that
generally is a bigger design question than this phase's scope, and the
practical (human-speed, single-reviewer) risk this fix already closes
is the realistic threat model.

## 4. Review Queue had no bound on rows scanned per module

**Found via**: adversarial review Stage 17's explicit "N+1 queries" /
"slow dashboard queries" checklist items.

**Root cause**: `get_review_queue()` selected every row from all 6
correctable modules' tables for the caller's organization, with no
`LIMIT`, before filtering by confidence in Python. At today's data
volume this is invisible; at real production volume, every Review
Queue page load would degrade into a full-table scan across 6 tables.

**Fix**: capped to the 500 most recently created rows per module
(`_QUEUE_SCAN_CAP`), ordered by `created_at DESC`. Documented explicitly
as a mitigation, not a complete solution — see
`docs/dashboard_performance.md` for what a real fix would require.

## What adversarial review did NOT find a bug in

Checked and confirmed correct, not just assumed: tenant isolation
(every dashboard query filters by `organization_id`), evidence-badge
mapping (matches README's own documented per-module evidence table),
zero-observation nullability (`feedback_correction_rate`/
`auto_reply_acceptance_rate` are `null`, never `0`, when unreviewed —
verified by dedicated tests), and CSV/PDF report consistency (both
formats derive from one shared `build_report_data()` call, no
independent computation paths that could drift).
