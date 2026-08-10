# Phase 11 Requirements Traceability (FR-53 to FR-62)

> **Updated post-implementation (Stage 19).** Every "Planned status"
> below is now a **verified** status: implemented, exercised by real
> tests (461/461 backend tests passing, including the Phase 11-specific
> suites), and checked against a real disposable Postgres 16 container
> for schema-touching changes. Four real bugs were found and fixed
> during Stage 17's adversarial review — see
> `docs/error_analysis_dashboard.md`. A status is never marked FULL
> here just because code exists for it; see each FR's own "Limitations"
> row for what FULL/PARTIAL still excludes.

Legend: **FULL** — fully implemented and tested. **PARTIAL** — implemented
with disclosed limitations. **NOT IMPLEMENTED** — deliberately out of
scope this phase, documented why. **BLOCKED** — cannot be done at all
without a prerequisite this phase does not build (e.g., real auth).

## Dashboard & Analytics

### FR-53 — Display email volume by hour/day, category distribution, sentiment trends, SLA status, agent workload

| | |
|---|---|
| Existing support | None as a composite view. Per-module raw data exists (see audit report §2) but nothing aggregates it. |
| New implementation | `GET /api/v1/dashboard/overview` + `/email-volume` + `/categories` + `/sentiment` + `/sla` + `/agents`, backed by a new analytics query layer (`app/services/dashboard_service.py`) that queries existing prediction-log tables directly (read-only, no new source-of-truth tables for raw counts). |
| Data source | `spam_prediction_logs`, `category_prediction_logs`, `sentiment_prediction_logs`, `emails` (for SLA/resolution), `reply_drafts` (agent-workload proxy) |
| Database | New: `organization_id` column added (migration) to the 7 tables identified in the audit as missing it; new `emails.priority` + `emails.resolved_at` columns (SLA calculation, see architecture doc §SLA) |
| Frontend | Executive Overview + Email Volume + Category Analytics + Sentiment Trends + SLA Dashboard + Agent Workload pages |
| Tests | Aggregation correctness (known counts in, known aggregate out), empty-DB case, date-range edge cases |
| Evidence status | **Volume/category/sentiment counts are real, structural counts of what the system logged** — not a claim about model *accuracy*. Sentiment/category values displayed are labeled per §Model Evidence Policy (provisional/synthetic) so raw counts are never confused with validated predictions. |
| Limitations | "Email volume" undercounts real traffic if a module was called directly without going through `emails` indexing (Phase 9's known non-auto-wired gap, see audit §5.7) — the dashboard sources volume from prediction-log row counts (the actual per-request source of truth), not from `emails`, specifically because of this. Agent workload is a **proxy** metric (reviewer_id/organization_id are caller-supplied, not authenticated identities — see FR-58 note below). |
| **Verified status** | **PARTIAL** — real counts, honestly labeled evidence, disclosed volume-source caveat |

### FR-54 — Real-time dashboard updates via WebSocket, 30s refresh

| | |
|---|---|
| Existing support | None — confirmed zero WebSocket usage anywhere in the codebase. |
| New implementation | `WebSocket /api/v1/dashboard/ws` using FastAPI's native `WebSocket` support (no new dependency); in-process pub/sub (a simple `asyncio`-based broadcaster, not Redis/Kafka per the non-goals). Client falls back to 30s polling of `/dashboard/overview` on disconnect. |
| Data source | Same aggregation layer as FR-53, pushed on a timer or on new-prediction events |
| Database | None new |
| Frontend | `websocket/` client module with reconnect + polling fallback |
| Tests | Connect/disconnect, reconnect-after-drop, fallback-to-polling, broadcast-to-multiple-clients |
| Evidence status | N/A (transport mechanism, not a model claim) |
| Limitations | In-process broadcaster means updates are only seen by clients connected to the same API process — documented as a scalability limit (Stage 7), consistent with "no Kafka/Redis" instruction; horizontal scaling of the dashboard's real-time layer is explicitly out of scope this phase. |
| **Verified status** | **PARTIAL** — functional single-process real-time updates, documented scaling limit |

### FR-55 — Date-range filtering: Today / Week / Month / Custom

| | |
|---|---|
| Existing support | None — no dashboard endpoints exist yet to filter. |
| New implementation | Shared `DateRangeParams` dependency (`start`, `end`, or named preset) applied to every `/dashboard/*` GET endpoint |
| Data source | `created_at` columns (all tables, all UTC per existing convention) |
| Database | New indexes on `created_at` for all 8 prediction/log tables (audit finding: none exist today) |
| Frontend | Shared date-range picker component reused across all dashboard pages |
| Tests | Boundary dates, invalid ranges (end < start), very large ranges, timezone-conversion correctness |
| Evidence status | N/A |
| Limitations | All filtering is UTC-based server-side; display-side timezone conversion is a frontend concern only (see architecture doc §Timezone Policy) |
| **Verified status** | **FULL** |

### FR-56 — Auto-generated weekly analytics reports, PDF + CSV export

| | |
|---|---|
| Existing support | None. `pandas` is already an (undeclared) transitive dependency; no PDF library exists. |
| New implementation | `POST /api/v1/dashboard/reports/export?format=csv\|pdf`; CSV via stdlib `csv`; PDF via `reportlab` (new dependency, chosen over `weasyprint` specifically to avoid native system libraries on Windows dev machines) |
| Data source | Same aggregation layer as FR-53/57 |
| Database | None new (reports are generated on demand, not pre-materialized) |
| Frontend | "Reports" page with format toggle + download |
| Tests | CSV structural correctness, PDF generation doesn't crash on empty data, large-range report generation time |
| Evidence status | Report explicitly carries the same evidence-status labels as the live dashboard — a PDF must not present synthetic/unvalidated metrics as validated just because it looks like a formal document. |
| Limitations | "Auto-generated weekly" is implemented as an on-demand endpoint, not a scheduled job — no scheduler/cron infrastructure exists in this codebase yet (would need APScheduler or an OS-level cron, a new dependency/infra decision out of scope unless explicitly requested). Documented as a gap, not silently narrowed. |
| **Verified status** | **PARTIAL** — on-demand export works; scheduled auto-generation deferred and disclosed |

### FR-57 — Model accuracy trends over time, feedback correction rates

| | |
|---|---|
| Existing support | None. No model has any real accuracy ground truth in production (per README's own evidence-status table). |
| New implementation | `GET /api/v1/dashboard/models` — displays what's **actually measurable**: feedback correction rate over time (real, from new `feedback_events` table), confidence-score distributions over time (real), and each model's **offline** validation metric (Spam's 99.44%/91.33%, others' synthetic/off-domain caveats) as a static reference value, never conflated with live production accuracy. |
| Data source | `feedback_events` (new), prediction-log tables' `confidence` columns |
| Database | `feedback_events` (new table, see architecture doc) |
| Frontend | Model Quality page with explicit REAL VALIDATED / PROVISIONAL / SYNTHETIC / OFF-DOMAIN / UNVALIDATED badges per module (master prompt's own required taxonomy) |
| Tests | Correction-rate computation correctness, badge-assignment-per-module correctness, zero-feedback case |
| Evidence status | This is the FR most at risk of accidentally presenting misleading data — the entire `docs/model_evidence_policy.md` (Stage 18) exists specifically to constrain this page. |
| Limitations | "Trends over time" for correction rate are only as meaningful as feedback volume, which is currently zero (same class of gap as Auto-Reply's Human Acceptance Rate) |
| **Verified status** | **PARTIAL** — real correction-rate tracking; "model accuracy trends" limited to offline reference metrics + confidence distributions, not a live accuracy claim (none exists to show) |

## Feedback Loop

### FR-58 — Users correct spam/priority/category/sentiment/intent/routing predictions

| | |
|---|---|
| Existing support | 6 of 7 `*/feedback` endpoints already exist and work (summarization's 7th shape is accept/reject, not a correction in the same sense). |
| New implementation | Existing endpoints **unchanged** (backward compatible); each now also dual-writes to `feedback_events` (same pattern as Phase 10's `_log_review_action` dual DB+log write) |
| Data source | Existing `*/feedback` endpoints |
| Database | `feedback_events` |
| Frontend | Review Queue page's "correct" action calls the existing per-module feedback endpoint directly — no new backend correction logic invented, only a UI for what already exists |
| Tests | Dual-write correctness (JSONL still gets the record AND `feedback_events` does), existing feedback tests must keep passing unmodified |
| Evidence status | N/A (this is a data-collection mechanism, not a model claim) |
| Limitations | "Users" has no real identity system — see FR-59 |
| **Verified status** | **FULL** for the correction mechanism itself; **PARTIAL** for "users" (caller-supplied identity only) |

### FR-59 — Every correction logged with user ID, timestamp, original value, corrected value

| | |
|---|---|
| Existing support | Timestamp/original/corrected exist today. **User ID does not exist anywhere in the feedback path** (audit finding F2). |
| New implementation | `feedback_events.reviewer_id` (String, caller-supplied — same trust model as `reply_drafts.reviewer_id`, not a new precedent) |
| Data source | Request body field, passed through from the frontend's (unauthenticated) "reviewer name" input |
| Database | `feedback_events` |
| Frontend | A simple reviewer-name field (not a login) feeding `reviewer_id` |
| Tests | `reviewer_id` persisted correctly, null-reviewer_id handled without crashing |
| Evidence status | N/A |
| Limitations | **This is explicitly a caller-supplied string, not an authenticated identity** — documented prominently on the dashboard itself (Stage 14's CURRENT/FUTURE identity split), not just in docs. Anyone can claim any reviewer_id. This is the same standing limitation as `reply_drafts.reviewer_id` since Phase 10, extended consistently, not newly introduced. |
| **Verified status** | **PARTIAL** — literal fields all present and logged; "user ID" is unauthenticated by design, disclosed everywhere it's displayed |

### FR-60 — Surface low-confidence predictions for human review (active learning foundation)

| | |
|---|---|
| Existing support | None. No confidence-threshold logic exists anywhere. |
| New implementation | `GET /api/v1/dashboard/review-queue` — computed query (not a materialized table, see architecture doc §Review Queue) over the 5 modules with a scalar/normalizable confidence value (spam, priority, sentiment, routing, and category/intent via min-per-label), excluding items already present in `feedback_events` (i.e., already reviewed) |
| Data source | `spam_prediction_logs`, `priority_prediction_logs`, `category_prediction_logs`, `sentiment_prediction_logs`, `intent_prediction_logs`, `routing_decision_logs` — NOT `summary_logs` (no confidence concept exists for summarization, disclosed rather than forced) |
| Database | Uses existing confidence columns + new `feedback_events` (to exclude already-reviewed items) |
| Frontend | Human Review Queue page: inspect / confirm-correct / submit-correction actions |
| Tests | Ranking-order correctness (see FR-60 architecture design), exclusion-of-reviewed-items correctness, empty-queue case |
| Evidence status | Confidence values themselves inherit each module's own evidence caveats (a "low confidence" flag on a synthetic-label model is a different kind of signal than on Spam's real model) — labeled per item in the queue UI. |
| Limitations | Summarization has no queue entry (no confidence signal exists to rank it on) — disclosed, not silently omitted. Ranking (confidence × business-impact) is a documented heuristic, not a validated prioritization model. |
| **Verified status** | **PARTIAL** — real queue over 6 of 7 correctable modules, documented ranking heuristic |

### FR-61 — Feedback volume threshold triggers a retraining pipeline

| | |
|---|---|
| Existing support | None. |
| New implementation | Configurable `RETRAINING_FEEDBACK_THRESHOLD` (per module) in `Settings`; a background check (on each feedback write) that, when a module's unconsumed correction count crosses the threshold, writes a `retraining_requested` audit-log event and a row in `feedback_events`-adjacent state (a boolean/timestamp flag, not a new heavy table) — **does not trigger any actual retraining**. |
| Data source | `feedback_events` count per module |
| Database | A small `retraining_triggers` table (module, threshold_crossed_at, feedback_count_at_trigger, consumed: bool) — or a computed check with no dedicated table; final shape decided in architecture doc, see Stage 11 design |
| Frontend | Model Quality page shows "retraining threshold reached" as a status badge per module, informational only |
| Tests | Threshold-crossing detection correctness, idempotency (crossing the threshold twice doesn't double-trigger), event is observable via API/log |
| Evidence status | N/A |
| Limitations | **No automated retraining execution exists or is built this phase, by explicit instruction.** This is a trigger/event/audit mechanism only — a future CI/CD/MLOps phase (12+) is the intended consumer. Documented as such everywhere it's surfaced, so it cannot be mistaken for an active retraining pipeline. |
| **Verified status** | **PARTIAL** — trigger/event mechanism fully implemented and observable; execution deliberately NOT IMPLEMENTED (by design, matching the master prompt's own non-goal) |

### FR-62 — Track feedback correction rate as a model-quality proxy metric

| | |
|---|---|
| Existing support | None. |
| New implementation | `correction_rate = corrections / reviewed_predictions` (not `/all_predictions` — see architecture doc §Correction Rate for why the denominator needs a "confirmed correct, no change" action too, and how the Review Queue's "confirm" action supplies it) |
| Data source | `feedback_events` (both CORRECTION and CONFIRM actions) |
| Database | `feedback_events` |
| Frontend | Model Quality page: overall, by-model, by-confidence-bucket, and over-time correction rate charts |
| Tests | Rate calculation correctness with mixed CONFIRM/CORRECTION events, zero-denominator (no reviews yet) handling, per-confidence-bucket bucketing correctness |
| Evidence status | This is a genuinely measurable proxy the moment real review activity happens — unlike FR-57's "model accuracy," this metric doesn't depend on ground truth existing, only on human review activity existing, which is a real, achievable bar. |
| Limitations | Zero until real review activity happens — same "no observations yet, not 0%" framing as Auto-Reply's Human Acceptance Rate |
| **Verified status** | **FULL** — mechanism is complete and correct; **display honestly shows "no data yet"** until real reviews occur |

## Summary

| FR | Planned status |
|---|---|
| FR-53 | PARTIAL |
| FR-54 | PARTIAL |
| FR-55 | FULL |
| FR-56 | PARTIAL |
| FR-57 | PARTIAL |
| FR-58 | FULL (mechanism) / PARTIAL (identity) |
| FR-59 | PARTIAL |
| FR-60 | PARTIAL |
| FR-61 | PARTIAL (trigger only, by design) |
| FR-62 | FULL (mechanism) |

No FR is BLOCKED outright — the `feedback_events` table (your Q1 decision)
resolves what would otherwise have blocked FR-59/60/61/62 entirely.
