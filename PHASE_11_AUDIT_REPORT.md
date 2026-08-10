# Phase 11 Audit Report — Manager Dashboard, Analytics & Human Feedback Loop

> Stage 1 deliverable. Read before Stage 2 (requirements traceability) or any
> code is written. This report describes what actually exists in the
> repository today — verified by reading the code, not assumed from the PRD
> or from prior phase docs.

## 1. Scope of this audit

Read directly for this report: every SQLAlchemy model (`app/models/*.py`),
every Alembic migration, every repository (`app/database/repositories/*.py`),
every `*/feedback` endpoint and `FeedbackLogger` method
(`app/services/feedback_service.py`), the API router
(`app/api/v1/router.py`), `app/core/config.py`, `docker-compose.yml`,
`requirements.txt`, `app/api/v1/endpoints/reply.py` (most recent, most
representative endpoint), and `tests/conftest.py`.

## 2. Existing data sources (verified table-by-table)

| Table | Columns of dashboard interest | `organization_id`? | Link to `emails`? | Confidence field? |
|---|---|---|---|---|
| `emails` (`EmailRecord`) | subject, body, sender_email, received_at, category, department, resolution_status, index_status, is_deleted, created_at/updated_at | ✅ | — (is the canonical table) | — |
| `spam_prediction_logs` | is_spam, status, spam_score, confidence, threshold_used, model_version, processing_ms, created_at | ❌ | ❌ | ✅ `confidence` |
| `priority_prediction_logs` | predicted_priority, confidence, synthetic_model, model_version, processing_ms, created_at | ❌ | ❌ | ✅ `confidence` |
| `category_prediction_logs` | predicted_categories (JSON list), confidences (JSON dict per label), synthetic_model, created_at | ❌ | ❌ | ✅ per-label dict, not scalar |
| `summary_logs` | summary, summary_type, input_word_count, entity_preservation_rate, created_at | ❌ | ❌ | ❌ no confidence concept at all |
| `sentiment_prediction_logs` | predicted_sentiment, confidence, synthetic_model, created_at | ❌ | ❌ | ✅ `confidence` |
| `intent_prediction_logs` | predicted_intents (JSON list), confidences (JSON dict), entities (JSON), synthetic_model, created_at | ❌ | ❌ | ✅ per-label dict |
| `routing_decision_logs` | department, action, confidence, requires_human_review, reason, matched_rules, supporting_signals, upstream_failures, created_at | ❌ | ❌ | ✅ `confidence` |
| `reply_drafts` | status, generation_policy, edit_distance, reviewer_id, retrieved_context_count, latencies, created_at, reviewed_at | ✅ | `source_email_id` (nullable) | — (not a classifier) |

**Finding F1 (structural, affects almost every FR):** every prediction-log
table is fully independent — no `email_id` foreign key, no
`organization_id`, and each stores its own copy of subject/body (a
deliberate Phase 3–8 decision made before `emails` existed — see
`spam_prediction_log.py`'s own docstring). There is currently **no way to
join** "this category prediction," "this sentiment prediction," and "this
routing decision" as being about the same email, except by matching on
subject+body text or timestamp proximity — both fragile. `reply_drafts` and
`emails` are the only two tables with `organization_id` at all.

This directly affects:
- **FR-53** (category distribution, sentiment trends, SLA status per email) — computable per-module today, but not as a single per-email operational view, since nothing links the six modules' independent decisions about the same message.
- **FR-58/59** (correct a spam/priority/category/sentiment/intent/routing prediction) — correctable today only against a specific `prediction_log.id`, not against "this email" as a unit.
- Any tenant/organization-scoped dashboard query — six of eight tables have no `organization_id` column to filter on at all.

## 3. Existing feedback mechanism (verified, not assumed)

**Finding F2 (blocks FR-59 as literally written):** feedback today is
**JSONL-file-based, not database-backed** —
`app/services/feedback_service.py`'s `FeedbackLogger` writes to
`artifacts/{module}_feedback.jsonl`, one file per module (spam, priority,
category, summarization, sentiment, intent, routing, retrieval,
auto_reply). Every one of its five logging methods
(`log_correction`, `log_summary_feedback`, `log_routing_feedback`,
`log_retrieval_feedback`, `log_auto_reply_feedback`) records
`feedback_id`, `module`, the original/corrected values, an optional
`comment`, and `created_at` — **none of them accept or record a user
identifier**. FR-59 literally requires "user ID, timestamp, original
value, corrected value" — the timestamp/original/corrected fields exist;
**user ID does not exist anywhere in the feedback path today**, not as a
column, not as a function parameter, not even as an unvalidated
caller-supplied string (unlike `reply_drafts.reviewer_id`, which is at
least caller-supplied). This is the single largest gap Phase 11 must
close, not a minor omission.

Existing feedback endpoints (all fire-and-forget, all `POST
/api/v1/{module}/feedback`, all return only `{status, feedback_id}`, none
support **reading back** feedback — there is no `GET .../feedback` anywhere
in this codebase):

| Module | Feedback shape |
|---|---|
| spam / priority | scalar `predicted_label` → `corrected_label` |
| category | list `predicted_label` → `corrected_label` (multi-label) |
| summarization | accept/reject + optional corrected text + 1–5 quality score |
| sentiment / intent | scalar/list predicted → corrected |
| routing | department + action pair |
| retrieval | query + result_email_id + boolean useful |
| auto_reply | draft_id + boolean useful (separate from the draft's own status column) |

**Nothing in this codebase reads these JSONL files back** for analytics —
they are write-only today. FR-57 ("feedback correction rates"), FR-60
(surface low-confidence predictions), FR-61 (threshold-triggered
retraining), and FR-62 (correction rate as a proxy metric) all require
reading feedback back in aggregate, which the current JSONL-per-module
design does not support efficiently (no indexing, no query capability, no
join back to the originating prediction).

## 4. Existing reusable infrastructure

- **`GUID` type** (`spam_prediction_log.py`) — Postgres-native UUID /
  SQLite-CHAR(36) portable UUID column, reused by every model since. Any
  new dashboard table should reuse this, not reinvent it.
- **Async repository pattern** — one repository class per table under
  `app/database/repositories/`, session injected via `Depends(get_db)`.
  `reply.py`'s endpoint-level orchestration (calling multiple repositories,
  never doing raw joins in the endpoint) is the most recent and most
  relevant precedent for a dashboard aggregation endpoint.
- **`synthetic_model: bool`** column exists on five of the eight tables
  (spam does not have it — spam's evidence is real) as the existing,
  precedented mechanism for "is this prediction backed by validated
  evidence." Any new "evidence status" concept for the dashboard should
  reuse this signal, not invent a parallel one.
- **Structured JSON logging** (`python-json-logger`) is already the
  project's logging convention — `reply.py`'s `_log_review_action` is the
  most recent example of a dual-write (DB column + structured log line)
  pattern already established for auditability.
- **Docker Compose**: two services only, `postgres` + `api`. No `redis`,
  no message broker, no frontend service. Consistent with the master
  prompt's "simplest architecture" instruction — a WebSocket
  implementation must work in-process, in the existing FastAPI app.
- **Testing**: `tests/conftest.py` provides only a `TestClient` fixture
  today; DB-backed tests (e.g. `test_reply_draft_repository.py`) build
  their own `aiosqlite`-backed async session per test file rather than a
  shared fixture — Phase 11's DB tests should follow that same
  established pattern rather than introduce a new one.

## 5. Existing gaps this phase inherits (confirmed by reading the code, not just prior docs)

1. **No real authentication anywhere.** `organization_id` is a
   query-parameter string defaulting to `"default"`
   (`reply.py: organization_id: str = "default"`); `reviewer_id` is a
   caller-supplied field on the request body
   (`ReplyReviewActionRequest.reviewer_id`), never verified against
   anything. Nothing enforces that the caller is who they claim to be.
   Every dashboard/feedback identity concept Phase 11 introduces inherits
   this same limitation and must be documented as such, not silently
   presented as secure.
2. **No WebSocket infrastructure exists anywhere in this codebase** —
   confirmed by a repo-wide search; FR-54 is entirely new work, not an
   extension of anything.
3. **No confidence-threshold / low-confidence-flagging logic exists
   anywhere** — every `*/predict` endpoint returns a confidence value but
   nothing currently classifies "low confidence" for any module. FR-60 is
   entirely new logic, and `summary_logs` has no confidence concept to
   apply it to at all (flagged as a real design question for Stage 3/4,
   not silently ignored).
4. **No PDF or reporting library is currently a dependency.** `pandas` is
   used pervasively (`app/analysis/eda.py`, every `data_ingestion/*`
   loader, every training/dataset-generation script) but was never added
   to `requirements.txt` — a pre-existing, disclosed gap (see that file's
   own header comment), not something Phase 10 or earlier introduced. No
   PDF library (reportlab/weasyprint/fpdf2/etc.) exists at all — FR-56's
   PDF export needs a new dependency decision.
5. **No indexes beyond primary keys and `emails`' own unique constraint**
   exist on any table — in particular, **no index on any `created_at`
   column** across all eight prediction/log tables. Every FR-53/55/57
   dashboard query filters by date range; at current (near-empty,
   test-only) data volume this is invisible, but it is a real, disclosed
   performance risk the moment real volume exists.
6. **The DB-write-hang technical debt item is unresolved**
   (`docs/technical_debt/database_write_hang.md`) — mitigated via
   `DB_WRITE_TIMEOUT_SECONDS`, not root-caused. Any new dashboard writes
   (feedback, review-queue state changes) inherit this same risk; nothing
   in this phase should touch that mitigation without a specific reason.
7. **Retrieval indexing (Phase 9) is not auto-wired** — the `emails`
   table only contains what has been manually indexed via
   `POST /retrieval/index`. A dashboard's "email volume" KPI sourced from
   `emails` would undercount actual traffic through the system, since most
   modules (spam/priority/category/etc.) log directly to their own tables
   and never touch `emails` at all. **This means `emails` is NOT a
   reliable source for FR-53's "total email volume"** — the
   highest-volume-of-truth table for raw traffic is actually whichever
   prediction-log table is called on every request (see Stage 3 open
   question below).
8. **Auto-Reply Human Acceptance Rate has zero real observations** —
   confirmed still true; `reply_drafts` has real columns
   (`status`, `edit_distance`, `reviewed_at`) ready to aggregate the moment
   real reviews happen, but querying it today returns an empty/near-empty
   result set, which the dashboard must render as "No real observations
   yet," never as `0%` (master prompt's own explicit instruction,
   confirmed here as consistent with what the schema actually supports).

## 6. Risks / blocking issues for Stage 2 onward

- **BLOCKING for FR-59 as literally specified**: a `user_id`/reviewer
  identity field must be added to the feedback path — it does not exist
  today in any form. This requires either (a) extending the JSONL
  records with a caller-supplied field (cheap, but keeps feedback
  unqueryable for FR-57/60/61/62's aggregate needs), or (b) introducing a
  proper Postgres feedback table (bigger change, but the only way FR-57's
  "correction rate," FR-60's "surface for review," FR-61's "threshold
  trigger," and FR-62's "track over time" can be computed without
  parsing JSONL files at request time). **This is the central
  architectural fork for Stage 2–4 and needs an explicit decision before
  design proceeds** — see the question below.
- **Six of eight prediction tables have no `organization_id`.** If the
  dashboard is meant to be tenant-scoped (consistent with `emails` and
  `reply_drafts` already being tenant-scoped), these six tables need a
  migration adding the column, defaulted for existing rows the same way
  `emails.organization_id` was. If the dashboard is single-tenant for now
  (matches "no real auth yet" reality), this can be deferred and
  documented as a known limitation instead.
- **No `email_id` link** means FR-53's per-email composite view (all six
  modules' decisions about one message) cannot be built as a real join —
  only as best-effort correlation, or by requiring new writes to start
  carrying the link going forward (old rows stay unlinked).
- **PDF generation** needs a dependency decision before Stage 4/5 can
  finalize the reports design.
- **Confidence semantics differ across modules** (scalar vs. per-label
  dict vs. absent for summarization) — FR-60's "low-confidence
  predictions" needs a per-module normalization rule, not one global
  threshold.

## 7. What is explicitly NOT touched by this audit

Per the master prompt's own non-goals: no changes proposed to
authentication, Kafka, Kubernetes, model registry, or automated retraining
execution. The DB-write-hang mitigation is documented, not modified. This
audit does not recommend fixing Phase 9's non-auto-wired indexing gap as a
Phase 11 prerequisite — it is named here only because it changes what
"email volume" should be sourced from.
