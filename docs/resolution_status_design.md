# Resolution Status Design (Module 9 / Phase 9, Step 4 — FR-46)

## The Problem

FR-46 requires retrieval results to be "filterable by: category,
department, resolution status." Category and department already exist as
concepts elsewhere in this codebase (Category's FR-21 taxonomy, Routing's
department field). **Resolution status does not exist anywhere in this
codebase before this phase** — no ticket/case model, no "open/closed"
concept, no agent-action workflow of any kind. Confirmed by repository
audit, not assumed.

## The PRD Does Not Define a Taxonomy

FR-46 names "resolution status" as a filter field but never enumerates its
possible values anywhere in the PRD. This is genuinely ambiguous, not an
oversight in reading — searched for "resolution" across the PRD and found
only the requirement name itself and one appearance in the vector-metadata
schema example (§12.2's `VECTOR_METADATA_SCHEMA` comment: `"resolved /
unresolved / pending"`, an illustrative comment, not a formal enum
declaration anywhere else in the document).

## Decision: A Minimal, Invented, Extensible 4-State Enum

Confirmed with the project owner before implementation:

```python
OPEN = "OPEN"
IN_PROGRESS = "IN_PROGRESS"
RESOLVED = "RESOLVED"
CLOSED = "CLOSED"
```

(`app/retrieval/resolution_status.py`) — **this is invented, not derived
from the PRD**, disclosed explicitly rather than presented as if it were
a PRD requirement. The 4-state shape (vs. the PRD comment's 3-state
"resolved/unresolved/pending") was chosen because it distinguishes "an
agent is actively working this" (`IN_PROGRESS`) from "nobody has looked at
it yet" (`OPEN`) — a distinction real support workflows generally need —
while remaining small enough to not invent a full ticketing state machine
this project has no other infrastructure for.

## No Automatic Transitions

Every email defaults to `OPEN` at index time
(`DEFAULT_RESOLUTION_STATUS = OPEN`). **Nothing in this codebase ever
changes it automatically** — there is no agent-action layer, no
"email replied to" detection, no auto-close-after-N-days logic. The only
way status changes is an explicit, human-driven call to
`PATCH /api/v1/retrieval/emails/{id}/resolution`
(`app/api/v1/endpoints/retrieval.py:update_resolution_status`). Presenting
this as more automated than it is would misrepresent what this phase
built — the PRD's own dashboard vision (§14.3, "SLA Compliance Rate")
implies a fuller workflow than this minimal field provides; that fuller
workflow is out of scope here.

## Why Resolution Status Is Filtered Against Postgres, Not Vector Metadata

Unlike `category`/`department` (relatively stable ML-model snapshots,
refreshed automatically whenever an email is re-indexed with new values),
`resolution_status` changes via a *different* code path
(`PATCH .../resolution`) that does **not** re-embed or touch the vector
store at all. Storing it in Chroma's metadata would go stale the moment an
agent marks something resolved. See
`app/services/retrieval_service.py`'s module docstring and
`docs/vector_index_consistency.md` for the full mechanism: search
over-fetches candidates from the vector store, then filters by
`resolution_status` (and `is_deleted`) against a fresh Postgres lookup —
Postgres is the single always-current source for this specific field.

## Supporting Uses (Step 4's explicit checklist)

| Use | Support |
|---|---|
| Filtering | `POST /retrieval/search` accepts `resolution_status`, filtered against fresh DB state — `tests/test_retrieval_endpoint.py::test_resolution_status_update_and_filtering` |
| Updates | `PATCH /retrieval/emails/{id}/resolution`, validated against the 4-state enum (422 on an invalid value) |
| Auditing | `emails.updated_at` reflects the change; no separate audit-trail table for status *history* was built (a disclosed gap — this phase tracks current status only, not a timeline of changes) |
| Future dashboard usage | The column and filter exist; no dashboard consumes them yet (Module 12 in the PRD's numbering, not started) |
| Future RAG/Auto-Reply usage | Resolution status is exactly the kind of signal a future Auto-Reply module would want ("only draft from RESOLVED past cases") — deliberately available as a filter now, not wired into anything yet |
