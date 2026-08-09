"""
Tenant-isolation scaffold (Module 9 / Phase 9).

No auth/multi-tenancy exists anywhere in this codebase (deferred since
Phase 1, see docs/architecture.md's "Known Gaps") -- Phase 9 does NOT
implement real authentication or per-organization access control. What it
DOES do, per RULE 7 (Phase 9 brief): build the vector store so a future
auth layer's organization_id can never leak across tenants once it exists,
rather than designing something that would need retrofitting later.

DEFAULT_ORGANIZATION_ID is the single-tenant placeholder every caller uses
today, the same role INTERNAL_DOMAINS = {"enron.com"} plays in
app/feature_engineering/domains.py -- a real fact about this project's
single current deployment, not a stand-in for real multi-tenant logic.

The enforcement boundary: every VectorStore method that reads or writes
vectors REQUIRES organization_id as a positional argument (see
app/retrieval/vector_store.py) -- there is no optional/None path that
skips tenant scoping. When real auth lands, the caller-supplied
organization_id here becomes "derived from the authenticated request"
instead of "always DEFAULT_ORGANIZATION_ID" -- a one-line change at the
API boundary, not a redesign of the storage layer. See
docs/vector_tenant_isolation.md.
"""

DEFAULT_ORGANIZATION_ID = "default"
