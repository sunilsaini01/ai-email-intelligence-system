# Feedback Loop (Module 11 / Phase 11, FR-58 to FR-62)

## What existed before this phase

Nine `POST /api/v1/{module}/feedback` endpoints (spam, priority,
category, summarization, sentiment, intent, routing, retrieval,
auto_reply), each writing an append-only JSONL record via
`FeedbackLogger` (`app/services/feedback_service.py`) — write-only, no
user identity captured, no query capability. See
`PHASE_11_AUDIT_REPORT.md` §3 for the full audit.

## What this phase added: `feedback_events`

Every one of those nine endpoints is **unchanged in its existing
behavior** — same request shape, same JSONL write, same response. Each
now **additionally** writes one row to the new `feedback_events` Postgres
table (`app/services/feedback_event_service.py::record_feedback_event`),
the same dual-write shape Phase 10's `_log_review_action` already
established (DB row + structured log line, not a replacement of the
existing mechanism).

Auto-Reply's approve/edit/reject actions (`POST /reply/{id}/approve|edit|reject`)
also now write to `feedback_events` — `approve`→`ACCEPT`, `edit`→`CORRECTION`
(original vs. edited text), `reject`→`REJECT` — unifying the draft
lifecycle's own review signal with every other module's feedback, per
Stage 8's "unify the existing feedback mechanisms" instruction.

## The `action` field, and why `CONFIRM` is new

`CORRECTION` / `ACCEPT` / `REJECT` / `RELEVANCE` all map to something a
feedback endpoint already did. `CONFIRM` does not — **nothing in this
codebase, before this phase, ever recorded "an agent reviewed this
prediction and it was correct."** Every feedback endpoint only ever
fires on a correction. This matters concretely: FR-62's correction rate
is `corrections / reviewed_predictions`, and without a "reviewed,
correct" event, `reviewed_predictions` has no real denominator — the
formula silently degrades to `corrections / all_predictions`, which
`docs/architecture_dashboard.md` explicitly says not to do.

`CONFIRM` is written from exactly one place: the Human Review Queue's
"Confirm correct" action (`POST /dashboard/review-queue/{id}/confirm`).
This is why the Review Queue and the feedback loop are one connected
system, not two separate Phase 11 features — the queue is what makes
FR-62's formula computable at all.

## Correction rate — the generalized formula

```
correction_rate = count(action IN CORRECTION_LIKE) / count(action IN CORRECTION_LIKE | CONFIRM_LIKE)

CORRECTION_LIKE = {CORRECTION, REJECT}
CONFIRM_LIKE    = {CONFIRM, ACCEPT}
```

`RELEVANCE` (retrieval's/auto-reply's "was this useful" judgments) is
excluded from this formula entirely — it's a relevance judgment, not a
correctness judgment, and forcing it into the same denominator would
misrepresent what's being measured. See
`app/services/dashboard_service.py::_correction_rate_for_module`.

## Identity: still unauthenticated

`reviewer_id` on every feedback write is a caller-supplied string, the
same trust model `reply_drafts.reviewer_id` established in Phase 10 —
**not a login, not verified against anything.** See
`docs/dashboard_security.md` for the full current/future split.

## What this phase deliberately does NOT do

- Does not promote any feedback into a training set or retrain any model
  — see `docs/active_learning.md` and FR-61's own scope boundary.
- Does not enforce a fixed `module` enum on `feedback_events.module` at
  the database level — a free-text field, same trust model as
  `reviewer_id`, validated only implicitly by which code paths write to
  it.
- Does not deduplicate corrections submitted through the nine
  pre-existing `*/feedback` endpoints (no `prediction_id` is available
  there to detect a duplicate against — a structural, pre-existing gap,
  not something this phase introduced or can retrofit without changing
  those nine endpoints' request contracts). The Review Queue's own
  `CONFIRM` path **does** guard against duplicates — see
  `docs/error_analysis_dashboard.md`.
