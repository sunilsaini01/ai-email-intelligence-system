# Architecture — Manager Dashboard & Analytics (Phase 11)

> Stages 3–5 deliverable: UX design, analytics data model, backend API
> design. Written before any implementation code, per the phase's own
> gate. Builds directly on `PHASE_11_AUDIT_REPORT.md`'s findings and the
> three architectural decisions confirmed before this doc was written:
> (1) a new `feedback_events` Postgres table, not JSONL extension;
> (2) `organization_id` + `email_id` backfilled onto the six prediction-log
> tables that lack them; (3) `reportlab` for PDF export.

## 1. Data model (Stage 4)

Three new tables, reusing the existing `GUID` type and `Base`/session
conventions. No `dashboard_metrics`/`sla_events`/`agent_workload_metrics`
tables — those would duplicate data already sitting in the existing eight
tables; the dashboard reads and aggregates them instead (per Stage 4's own
"avoid unnecessary duplication" instruction).

### `feedback_events` (new)

```
id                  GUID PK
module              String(30)   -- spam|priority|category|summarization|
                                    sentiment|intent|routing|retrieval|auto_reply
organization_id     String(100)
prediction_id       GUID, nullable   -- the originating *_prediction_logs.id
                                        or reply_drafts.id, when known
action              String(20)   -- CORRECTION | CONFIRM | ACCEPT | REJECT | RELEVANCE
original_value      JSON, nullable
corrected_value     JSON, nullable
confidence           Float, nullable  -- the ORIGINAL prediction's confidence,
                                          for confidence-bucket analysis (FR-62)
reviewer_id         String(100), nullable  -- caller-supplied, unauthenticated (FR-59)
reason              Text, nullable
created_at          DateTime(timezone=True)
```

Why `action` beyond just original/corrected: a plain diff can't distinguish
"agent reviewed and confirmed this was correct" from "agent corrected it" —
and FR-62's correction rate needs both counted separately (§4 below).
`CONFIRM` is new: today's feedback endpoints only ever fire on a
correction, so there has never been a way to record "reviewed, no change
needed." The Review Queue (Stage 9) is what gives users a place to press
"confirm" instead of only "correct" — without it, `reviewed_predictions`
has no real denominator and FR-62 degrades to `corrections / all_predictions`
silently, exactly what Stage 10 says not to do.

Every existing `*/feedback` endpoint keeps writing its JSONL record
unchanged (backward compatible with anything depending on those files
today), and additionally writes one `feedback_events` row
(`action=CORRECTION`). This is the same dual-write shape
`reply.py::_log_review_action` already established for Phase 10 — not a
new pattern.

### `retraining_triggers` (new, FR-61)

```
id                        GUID PK
module                    String(30)
feedback_count_at_trigger Integer
threshold_used            Integer
triggered_at              DateTime(timezone=True)
consumed                  Boolean, default False   -- for a future CI/CD phase to claim
```

One row per threshold-crossing event, not a running counter — makes the
trigger auditable (when did this fire, at what count) and idempotent (see
§5 for the crossing-detection logic). `consumed` exists so a later
MLOps phase has a real field to mark "handled" without deleting history;
Phase 11 never sets it to `True` itself.

### Migration: `organization_id` on all 7 prediction/log tables

`spam_prediction_logs`, `priority_prediction_logs`,
`category_prediction_logs`, `summary_logs`, `sentiment_prediction_logs`,
`intent_prediction_logs`, `routing_decision_logs` each get:

```
organization_id  String(100), default DEFAULT_ORGANIZATION_ID, NOT NULL
```

Backfills to `DEFAULT_ORGANIZATION_ID` for existing rows (same constant
`emails`/`reply_drafts` already use) via a `mapped_column` Python-level
default — **zero application-code changes needed in the six
`*/predict` endpoints or their repositories**: every row simply carries
the single-tenant default until real multi-tenancy exists, exactly
matching this codebase's actual current reality rather than fabricating
per-request tenant plumbing nothing yet calls.

**`email_id` was considered and deliberately dropped from this design.**
Earlier drafts of this doc proposed a nullable `email_id` link on these
six tables. On reflection that would require adding an `email_id` field
to all six `*/predict` request schemas and repositories for a linkage
almost no real caller in this codebase supplies today (even
`reply_drafts.source_email_id`, the one precedent, is optional and often
NULL) — schema surface added for a capability nothing would exercise.
Dropped in favor of a much smaller, fully real alternative: see
"`emails.priority`" below, which solves the one feature (SLA) that
actually needed a priority↔email link, without touching six existing
API contracts.

### New index: `created_at` on all 8 prediction/log tables

Every dashboard query (FR-53/55/57) filters by date range; none of these
columns are indexed today (audit finding). Composite index
`(organization_id, created_at)` on each table — covers both the new
tenant-scoping filter and the date-range filter in one index, matching
the actual query shape the dashboard will issue.

### `emails.priority` (new column)

Nullable `String(20)`, the exact same "caller-supplied snapshot at index
time" pattern `category`/`department` already established on this table
(see `EmailRecord`'s own docstring) — not a new concept, one more field
of the same kind. Threaded through `RetrievalIndexRequest`/
`EmailRepository.upsert_by_content_hash` alongside the existing
category/department parameters. This is what makes SLA (§7) computable
without needing any `email_id` link on the six prediction tables: SLA
only ever needs *an* email's priority, received time, and resolution
time — all three now live on the one `emails` row, no join required.
Real limitation, stated plainly: since Phase 9's indexing was never
auto-wired to the six prediction endpoints (a pre-existing, disclosed
gap), and priority was never previously passed to `/retrieval/index` at
all, most currently-indexed emails will have `priority = NULL` — the SLA
dashboard reports and displays this excluded count rather than silently
treating `NULL` as "Low priority" or omitting the caveat.

### `emails.resolved_at` (new column)

`emails.updated_at` changes on *any* field update, not specifically a
resolution — using it for SLA "time to resolve" would silently overstate
or understate resolution time whenever an unrelated field changes later.
Add `resolved_at: datetime | None`, set exactly once, only by
`EmailRepository.update_resolution_status` when the new status is
`RESOLVED` (and cleared back to `NULL` if status is ever moved off
`RESOLVED, so re-resolving recomputes it rather than keeping a stale
value). This is the "small, genuinely required prerequisite" the master
prompt allows without being a redesign — one column, one write path
already being touched by Phase 10's auto-mark-resolved feature.

## 2. Correction rate — the actual formula (Stage 10)

```
correction_rate = COUNT(action = 'CORRECTION') / COUNT(action IN ('CORRECTION', 'CONFIRM'))
```

NOT `/ COUNT(all predictions ever made)` — most predictions are never
reviewed at all (no agent has looked at them), so that denominator would
make the correction rate look artificially low and meaningless the moment
review volume is a small fraction of total volume, which it always will
be. The `CONFIRM` action (§1) is what makes this formula computable
instead of just theoretically correct.

Bucketing for FR-62's "by confidence bucket": five buckets
(`<0.5`, `0.5–0.7`, `0.7–0.85`, `0.85–0.95`, `>0.95`) applied to
`feedback_events.confidence` — a coarse-enough grid to be readable on a
chart, fine-enough to show whether correction rate climbs as confidence
drops (the calibration signal this metric exists to surface).

## 3. Review Queue ranking (Stage 9)

Not sorted by confidence alone. Ranking score:

```
urgency = (1 - normalized_confidence) * priority_weight
priority_weight: Critical=4, High=3, Medium=2, Low=1, unknown=1
```

`priority_weight` is only meaningfully available **within the priority
module's own queue items** — a low-confidence `priority_prediction_logs`
row already carries its own `predicted_priority` on the same row, no
join needed. For every other module's queue items (spam, category,
sentiment, intent, routing), there is no per-row priority signal
available without the `email_id` link this design deliberately did not
build (§1), so `priority_weight` defaults to `1` for all of them —
disclosed explicitly as "priority-based urgency boosting currently
applies only to Priority-module review items" in the UI and in
`docs/active_learning.md` (Stage 18), not silently presented as if every
module were weighted the same way. This is a heuristic, not a validated
prioritization model, regardless.

Queue membership: `confidence < MODULE_LOW_CONFIDENCE_THRESHOLD` (a
per-module documented default — spam/priority/sentiment/routing use 0.6,
category/intent use 0.5 per-label since multi-label confidence is
naturally more distributed) **AND** `prediction_id NOT IN (SELECT
prediction_id FROM feedback_events WHERE prediction_id IS NOT NULL)` —
already-reviewed items drop off the queue whether they were confirmed or
corrected.

## 4. Retraining trigger (Stage 11)

On every `feedback_events` INSERT with `action = CORRECTION`: count
unconsumed corrections for that `module` since the last
`retraining_triggers` row for that module (or all-time if none exists).
If count `>= RETRAINING_FEEDBACK_THRESHOLD` (default `50`, configurable
per environment via `Settings`, documented as a development default, not
a validated business threshold — per the master prompt's own instruction
not to invent one), insert a `retraining_triggers` row and log a
structured `retraining_requested` event. This check runs inline in the
feedback-write path (cheap `COUNT` query, not a background job — no
scheduler infrastructure exists yet, and one check per correction is not
expensive at this data volume). **Nothing else happens** — no model is
retrained, no artifact is touched. This is the complete scope of FR-61.

## 5. WebSocket design (Stage 7)

```
Prediction/feedback write (any endpoint)
        -> DashboardBroadcaster.notify(event_type, payload)  [in-process, asyncio]
        -> all connected WebSocket clients on THIS process receive the event
        -> React client updates the relevant chart incrementally,
           or falls back to re-fetching /dashboard/overview
```

`DashboardBroadcaster` is a plain in-memory registry of open
`WebSocket` connections (a set, guarded by an `asyncio.Lock`), not a new
service or dependency — matches the explicit "no Kafka/Redis" instruction
and the existing single-process deployment. Documented scaling limit:
if the API is ever run as multiple processes/replicas, each process's
broadcaster only knows about its own clients — a client connected to
replica A never sees an event that landed on replica B. Out of scope to
fix this phase (would need Redis pub/sub or similar); the 30s polling
fallback exists specifically so this limitation degrades gracefully
rather than silently under-delivering updates.

## 6. Backend API surface (Stage 5)

All under `/api/v1/dashboard`, all accepting the shared date-range
dependency (`range=today|week|month|custom&start=...&end=...`) and an
`organization_id` query param (default `"default"`, same trust model as
every other endpoint today):

| Endpoint | Purpose |
|---|---|
| `GET /overview` | Executive KPIs (FR-53) |
| `GET /email-volume` | Hourly/daily volume series (FR-53) |
| `GET /categories` | Category distribution (FR-53) |
| `GET /sentiment` | Sentiment trend series (FR-53) |
| `GET /priority` | Priority distribution (FR-53) |
| `GET /sla` | Within/at-risk/breached counts (FR-53) |
| `GET /agents` | Per-reviewer_id workload proxy (FR-53) |
| `GET /models` | Evidence-labeled metrics + correction rates (FR-57) |
| `GET /review-queue` | Ranked low-confidence items (FR-60) |
| `POST /review-queue/{prediction_id}/confirm` | Log a CONFIRM action |
| `GET /reports/export?format=csv|pdf` | FR-56 |
| `WS /ws` | FR-54 |

No new endpoints duplicate existing `*/feedback` endpoints — corrections
still go through them (§1); the dashboard only adds the CONFIRM action,
which has never existed anywhere before.

## 7. SLA definition (Stage 3, section 6) — documented development default

No SLA values exist anywhere in the PRD or codebase. Defaults (clearly
labeled `SLA_TARGET_HOURS` in `Settings`, configurable, not hardcoded):

| Priority | Target | At-risk threshold |
|---|---|---|
| Critical | 2h | 1.5h (75%) |
| High | 8h | 6h |
| Medium | 24h | 18h |
| Low | 72h | 54h |

`Within SLA`: not yet resolved and elapsed < target, or resolved with
`resolved_at - received_at < target`. `At Risk`: not yet resolved and
elapsed >= at-risk threshold but < target. `Breached`: elapsed >= target
regardless of resolution. Computed directly from `emails.priority` +
`emails.received_at` + `emails.resolved_at`/`resolution_status` (§1) —
no join to any prediction table required. Only emails with a non-NULL
`priority` are included in the tiered breakdown; the dashboard reports
the excluded (`priority IS NULL`) count explicitly rather than silently
underreporting or defaulting them to a tier they were never assigned.

## 8. Frontend structure (Stage 13)

```
frontend/
├── src/
│   ├── api/          -- typed fetch wrappers per dashboard endpoint
│   ├── websocket/     -- connection manager + reconnect/poll-fallback
│   ├── components/    -- KPI cards, evidence-status badges, date-range picker
│   ├── charts/         -- volume/category/sentiment/SLA chart wrappers
│   ├── pages/           -- Overview, EmailVolume, Categories, Sentiment,
│   │                        Priority, SLA, Agents, Models, ReviewQueue, Reports
│   ├── hooks/            -- useDashboardData, useWebSocket, useDateRange
│   ├── types/             -- generated/hand-written types mirroring Pydantic schemas
│   └── utils/
├── public/
└── package.json
```

React + TypeScript (PRD-specified), a lightweight charting library
(`recharts` — pure React, no native deps, easiest fit for a Windows dev
box, consistent with the `reportlab`-over-`weasyprint` reasoning above),
plain `fetch`/native `WebSocket`, no state-management library beyond
React Query for server-state caching (avoids hand-rolling cache
invalidation for 10+ endpoints).

## 9. Model evidence policy (Stage 18 preview)

Every dashboard number that originates from a classifier/model carries
one of five badges, computed from data already in this codebase (each
table's `synthetic_model` column + the module's known evaluation
domain, per the README's own evidence table) rather than a new manual
classification:

- **REAL VALIDATED** — Spam only
- **SYNTHETIC** — Priority, Category, Intent
- **OFF-DOMAIN** — Summarization
- **UNVALIDATED** — Sentiment
- **PROVISIONAL** — Routing, Retrieval, Auto-Reply (composition/no-ground-truth cases)

This mapping is a constant (`app/services/dashboard_service.py`), not a
per-request computation — it reflects a documented project fact, not
live data.
