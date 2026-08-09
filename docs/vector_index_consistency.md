# Database / Vector-Store Consistency (Module 9 / Phase 9, Step 19/Step 29)

## The Problem

Postgres (`emails`) and the vector store (Chroma) are two separate
systems. A write to one can succeed while the other fails, or one can be
updated without the other, producing genuine inconsistency — the class of
problem this document exists to define behavior for, per RULE 12 ("do not
allow stale metadata to produce incorrect filtering").

## Index Lifecycle State (Step 19)

`emails.index_status` (`app/models/email_record.py`):

```
PENDING  -- DB row exists (upsert succeeded), vector not yet confirmed written
INDEXED  -- both systems confirmed consistent for this row
FAILED   -- DB row exists, vector write failed (embedding/vector-store error)
STALE    -- soft-deleted; vector has been actively removed, row kept for audit
```

`POST /retrieval/index`'s sequence (`app/api/v1/endpoints/retrieval.py`):

```
1. Postgres upsert (content_hash identity settled)  → index_status = PENDING
2. Embed + vector-store upsert
   SUCCESS → mark_indexed()  → index_status = INDEXED
   FAILURE → mark_failed()   → index_status = FAILED, HTTP 503 returned
3. (never silently returns 200 while index_status stays PENDING/FAILED)
```

A `FAILED` row is NOT retried automatically — nothing in this codebase
auto-retries a failed operation from any module. The caller sees the 503
and can retry the same `/retrieval/index` call, which is safe (idempotent
by content_hash) whether or not the first attempt partially succeeded.

## What Happens on Metadata Change (Step 19's explicit questions)

| Change | Behavior |
|---|---|
| Category/department changes | Caller re-calls `/retrieval/index` with the same `(subject, body)` (same content_hash) and new values → same `vector_id` → Chroma metadata overwritten on upsert. No special-case code — see `app/services/retrieval_service.py`'s docstring |
| Resolution status changes | `PATCH /retrieval/emails/{id}/resolution` updates Postgres ONLY — never touches the vector store. Deliberate: resolution_status is filtered against fresh Postgres at query time, never stored in vector metadata at all (see `docs/resolution_status_design.md` for why) — so there is no vector-side staleness possible for this field by construction, not by discipline |
| Email deleted | Soft-delete (`is_deleted=True` in Postgres) AND immediate vector removal (`RetrievalService.delete_vector()`, called synchronously by the same DELETE request) — not lazy, not eventually-consistent. See "Soft Delete" below |
| Re-classification (a new Category/Routing prediction changes the label) | Same as "Category/department changes" above — the caller is responsible for re-calling `/retrieval/index`; this phase does not auto-detect upstream reclassification (Category/Routing don't currently emit any event this module could subscribe to) |

## Soft Delete (Step 20)

`DELETE /retrieval/emails/{id}`:

1. `EmailRepository.soft_delete()` — `is_deleted=True`, `index_status=STALE`, row kept (not physically deleted, consistent with every soft-delete precedent's audit-preservation reasoning).
2. `RetrievalService.delete_vector()` — called synchronously, in the same request, immediately after — the vector is actually removed from Chroma, not just flagged.

This double mechanism (immediate vector removal + a Postgres `is_deleted`
check applied again at search time) is deliberate belt-and-suspenders: if
step 2 ever failed silently in some future refactor, a soft-deleted
email's vector could still exist in Chroma but would still never surface
in a search result, because `search_similar_emails()`
(`app/api/v1/endpoints/retrieval.py`) checks `record.is_deleted` on every
candidate against fresh Postgres state before including it in results —
verified directly:
`tests/test_retrieval_endpoint.py::test_delete_removes_email_from_search_results`.

## Why No Outbox/Event Pattern, No Kafka

Considered (per Step 29's own suggestion) and rejected as unnecessary at
this project's current scale: the DB→vector sequence above is a single
in-process, synchronous call chain (RULE 14 — no Kafka/distributed infra
without evidence). The `PENDING`/`INDEXED`/`FAILED`/`STALE` state machine
on `emails.index_status` is the "simple reliable indexing state" Step 29
explicitly names as likely sufficient — and is sufficient here because
there is exactly one consumer (this same process) of the consistency
signal, not a distributed system with independent readers that would
need an event log to coordinate.
