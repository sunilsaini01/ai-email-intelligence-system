# Model Evidence Policy (Module 11 / Phase 11)

The master prompt's own non-negotiable constraint for this phase: **the
dashboard must not display synthetic/off-domain metrics as if they
represent real production model accuracy.** This document is the single
source of truth for how that's enforced in code, so the policy can't
silently drift from what the dashboard actually shows.

## The five badges

Every dashboard number that originates from a classifier/model carries
exactly one of these, computed from `EVIDENCE_MAP` in
`app/services/dashboard_service.py` — a constant, not a per-request
computation, because it reflects a documented project fact (this
project's own evaluation history), not live data:

| Badge | Meaning | Modules |
|---|---|---|
| REAL_VALIDATED | Real evaluation domain, measured metrics | Spam |
| SYNTHETIC | Trained on heuristically-labelled, fabricated data | Priority, Category, Intent |
| OFF_DOMAIN | Real, human-written labels, but wrong domain | Summarization |
| UNVALIDATED | No training, no fitting, no ground truth at all | Sentiment |
| PROVISIONAL | Composition/no-ground-truth cases | Routing, Retrieval, Auto-Reply |

This mapping is copied directly from the README's own "Progress" table
disclosure (each module's own row), not independently re-derived — the
dashboard is not a second, potentially-drifting source of truth about
evidence quality; the README stays the canonical record, and this
mapping is a code-level reflection of it.

## Where this is enforced

- **Category/Sentiment/Priority distribution pages** (`/dashboard/categories`,
  `/dashboard/sentiment`, `/dashboard/priority`): every response carries
  an `evidence` field; the frontend renders `<EvidenceBadge>` next to
  every chart built from it.
- **Model Quality page** (`/dashboard/models`): every module row shows
  its evidence badge alongside its correction rate — this is the page
  most at risk of accidentally implying "correction rate == accuracy,"
  so it additionally shows `offline_reference_metric` as a clearly
  separate, static reference value (Spam's real 99.44%/91.33%; every
  other module's cell is either `null` or an explicitly off-domain
  reference like Summarization's ROUGE score) rather than one blended
  number.
- **Reports (CSV/PDF)**: the same evidence labels are included in every
  export — see `app/services/dashboard_report_export.py`. A formal-
  looking PDF is exactly the context where a manager might mistake a
  synthetic metric for validated accuracy; this phase explicitly refused
  to let the export format be more misleading than the live dashboard.

## What correction rate IS and IS NOT evidence of

`feedback_correction_rate` (FR-62) is real, measurable evidence of
*how often reviewed predictions get corrected* — a genuinely different
and achievable claim from *model accuracy*, because it depends only on
review activity existing, not on ground truth existing. It is
**never** presented as an accuracy proxy on its own without the
module's evidence badge next to it, and it is `null` (not `0%`) until
real review activity exists — see `docs/feedback_loop.md` and the
"no observations yet" convention established by Auto-Reply's own
Human Acceptance Rate in Phase 10, extended consistently here.

## Auto-Reply and Retrieval specifically

Both are PROVISIONAL for the same underlying reason different Phase
9/10 caveats produce: Retrieval's embedding fitting is unsupervised (no
fabricated labels, unlike Priority/Category/Intent) but has no
relevance-outcome ground truth; Auto-Reply calls a third-party LLM this
project neither trains nor validates, and has zero real Human
Acceptance Rate observations. Collapsing both into one badge label is a
controlled simplification — the dashboard's five-badge vocabulary
cannot express every nuance the README's own longer prose disclosure
does; anyone needing the full nuance is pointed to the relevant model
card via each page's `evidence.note` tooltip text.
