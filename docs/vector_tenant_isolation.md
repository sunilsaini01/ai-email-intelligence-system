# Vector Store Tenant Isolation (Module 9 / Phase 9, Step 5 / RULE 7)

## Current State: No Real Multi-Tenancy

No auth, no organization concept with real enforcement, exists anywhere in
this codebase — deferred since Phase 1 (`docs/architecture.md`'s "Known
Gaps": *"Real auth (OAuth2/JWT) — wiring real auth before there's anything
to protect is wasted motion"*). This has not changed in Phase 9. What
changed: a vector store, unlike a per-request audit log, is corpus-wide
searchable by construction — a missing tenant boundary here is a much more
consequential class of bug than in any prior module, which is why this
phase does not defer the *boundary itself*, only its *enforcement source*.

## Decision: Option C — Contained Tenant Metadata, Deferred Real Auth

Per the Phase 9 brief's own three options (A: implement organization_id
now with real auth; B: build an abstraction ready for it; C: defer actual
authentication but enforce tenant metadata boundaries internally) —
**Option C**, confirmed with the project owner:

- `DEFAULT_ORGANIZATION_ID = "default"` (`app/retrieval/tenant.py`) is the
  single-tenant placeholder every caller uses today — same role
  `INTERNAL_DOMAINS = {"enron.com"}` plays in
  `app/feature_engineering/domains.py`: a real fact about this project's
  one current deployment, not a stand-in for real multi-tenant logic.
- Every `VectorStore` method (`upsert`/`query`/`delete`,
  `app/retrieval/vector_store.py`) takes `organization_id` as a
  **required positional argument**, never optional, never defaulted
  inside the store itself. There is no method signature that can be
  called without stating which tenant a vector belongs to.
- `ChromaVectorStore` additionally injects `organization_id` into every
  upsert's metadata and every query's `where` filter **itself** (not
  trusting the caller to remember) — defense in depth on top of the
  Protocol already requiring it.

## What This Does NOT Do

**No fake authentication was built.** `organization_id` today is whatever
the API caller puts in the request body (`RetrievalIndexRequest.
organization_id`, `RetrievalSearchRequest.organization_id`) — there is no
verification that the caller is actually entitled to that organization.
This is the honest current state, not hidden: **cross-tenant isolation is
enforced structurally (the code cannot accidentally search across
organizations even by omission), but access control (which caller may
claim which organization_id) does not exist yet**, same gap as every
other endpoint in this codebase.

## Verified

- `tests/test_retrieval_service.py::test_tenant_isolation_between_organizations`
  — indexing into `org-a` and searching `org-b` returns zero results, at
  the service layer.
- `tests/test_retrieval_security.py::test_cross_tenant_retrieval_is_never_possible`
  — the same property, framed as a security/adversarial test.
- `tests/test_retrieval_vector_store.py` — the underlying `VectorStore`
  contract test (run against both `InMemoryVectorStore` and
  `ChromaVectorStore`) includes tenant isolation as a required property
  any future implementation (e.g. a `PineconeVectorStore`) must also
  satisfy.
- `tests/test_email_record_persistence.py::test_same_content_hash_in_different_organizations_are_separate_records`
  — the same property at the Postgres layer.

## Path to Real Enforcement (Not Implemented — Blocked on Auth)

When real auth lands (still deferred, same gap `docs/architecture.md`
named at Phase 1): the API layer would derive `organization_id` from the
authenticated request's claims instead of accepting it as a client-
supplied field — a change to `app/api/v1/endpoints/retrieval.py`'s
request handling only. `RetrievalService`, `VectorStore`, and
`EmailRepository` would not need to change at all — they already treat
`organization_id` as an opaque, required scoping value, not something they
derive or trust implicitly. This is the concrete value of Option C over
Option A: the seam exists now, at zero cost to build it prematurely wrong.
