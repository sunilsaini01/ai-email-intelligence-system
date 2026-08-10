# Dashboard Security (Module 11 / Phase 11)

## Identity: current vs. future (Stage 14)

**CURRENT (this phase, and every phase since Phase 1):** there is no
real authentication anywhere in this codebase. `organization_id` is a
caller-supplied string defaulting to `"default"`. `reviewer_id`
(on every feedback write, on Auto-Reply's approve/edit/reject, and on
the Review Queue's confirm action) is a caller-supplied string, never
verified against any identity provider. The frontend's "Reviewer" field
(`DateRangePicker.tsx`) is a free-text label, explicitly **not** a
login — this is stated in its placeholder text and in code comments,
not left implicit.

**FUTURE (not built, not scoped this phase):** `organization_id` would
be derived from an authenticated session/token, not a request parameter;
`reviewer_id` would be the authenticated principal, not a submitted
string; role-based access control would gate which dashboard sections
and actions a given user can reach. Nothing in this phase's design
blocks that migration — every endpoint already threads `organization_id`
through as a parameter, which becomes "derived from the authenticated
request" as a boundary-only change, the same migration path
`docs/vector_tenant_isolation.md` already described for Phase 9.

## CORS

`app/main.py` adds `CORSMiddleware`, allowing origins from
`Settings.CORS_ORIGINS` (default: the Vite dev server's own origins,
`http://localhost:5173` / `http://127.0.0.1:5173`) — **not** a wildcard.
Given there is no real auth, an open CORS policy would let any page on
the internet call this API from a visiting user's browser and read the
response (email volume, categories, SLA data, etc.). This is a
structural mitigation, not a substitute for real authentication — it
only restricts which *browser origins* can make the call, not which
*callers* (a non-browser client, or a request forged server-side, is
unaffected by CORS entirely).

## PII exposure

The Review Queue exposes each item's **subject line** (`row.subject`)
so a reviewer has enough context to judge a prediction — it does **not**
expose the email body anywhere in any dashboard response. This mirrors
existing precedent (Phase 9's `SimilarEmailMatch` already exposes
`subject` in search results); it is a deliberate, minimal necessary
disclosure, not an oversight. CSV/PDF report exports carry only
aggregated counts and evidence labels — no subject, no body, no raw
per-email content at all.

## Free-text fields written straight to the database

`feedback_events.module`, `.reviewer_id`, `.reason`, and the Review
Queue's `module` request field are **not** validated against a fixed
enum at the API boundary — they're free-text strings, the same trust
model `reviewer_id` already had. This is a deliberate scope choice (an
enum would need updating every time a new module's feedback shape is
added) rather than an oversight; malformed values simply produce
dashboard rows that don't match any known module and are silently
excluded from per-module aggregation (no crash, no data corruption).

## Known gaps carried forward, not fixed this phase

- No rate limiting on any dashboard endpoint, including the export
  endpoints (PDF generation is CPU work; report generation
  time is disclosed in `docs/dashboard_performance.md`, but nothing
  prevents a caller from requesting many reports concurrently).
- No audit trail of *who viewed* dashboard data, only who *acted*
  (feedback/confirm) — consistent with every other module in this
  codebase never logging read access.
