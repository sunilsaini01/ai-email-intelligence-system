# Active Learning Foundation (Module 11 / Phase 11, FR-60/FR-61)

## What this phase builds

FR-60 asks for low-confidence predictions to be surfaced for human
review — "the foundation of an active-learning workflow," per the
master prompt's own framing. This phase builds exactly that foundation:
a ranked queue and a feedback-capture mechanism. It does **not** build
active learning itself (a system that uses that feedback to actually
improve a model) — see "What this explicitly is not," below.

## Review Queue membership

A prediction enters the queue when its confidence is below a per-module
threshold (`Settings.LOW_CONFIDENCE_THRESHOLD_SINGLE_LABEL` /
`_MULTI_LABEL`, documented development defaults — 0.6 / 0.5 — not
validated calibration points) **and** it has no `feedback_events` row
yet (confirmed or corrected). Confirming or correcting an item removes
it from the queue permanently — see `docs/feedback_loop.md`.

Six of seven correctable modules participate: spam, priority, category,
sentiment, intent, routing. **Summarization does not** — it has no
confidence concept at all (`summary_logs` carries no confidence column;
`entity_preservation_rate` is a different kind of signal, not a
prediction-confidence score) — disclosed, not silently forced into the
queue.

Multi-label modules (category, intent) use the **minimum** confidence
across all predicted labels for threshold comparison — the row's
weakest link, not its average or strongest label. A category prediction
with `{"Billing": 0.95, "Legal": 0.2}` qualifies for review because the
Legal label is genuinely uncertain, even though Billing is not.

## Ranking: urgency, not just confidence

```
urgency = (1 - confidence) * priority_weight
```

`priority_weight` (Critical=4, High=3, Medium=2, Low=1, unknown=1) is
only ever available for the **priority module's own** queue items — a
low-confidence `priority_prediction_logs` row already carries its own
`predicted_priority` on the same row. Every other module's items get
`priority_weight = 1` uniformly, because no cross-table link exists to
tell (say) a low-confidence category prediction what priority its email
carries — see `PHASE_11_AUDIT_REPORT.md` for why that link was
deliberately not built. This is disclosed in the queue's own `note`
field and in the UI, not silently presented as if every module were
weighted the same way.

This is a documented heuristic, not a validated prioritization model —
no evidence exists that this specific weighting improves review
efficiency; it encodes a reasonable intuition (a wrong low-confidence
Critical-priority prediction matters more than a wrong low-confidence
General one) and nothing more.

## What this explicitly is NOT

- **Not automated retraining.** FR-61's threshold-crossing mechanism
  (`retraining_triggers`) writes an audit row and a structured log line —
  `retraining_requested` — and stops there. No model artifact is
  touched, no training script runs, no CI/CD job is invoked. A later
  MLOps/CI/CD phase is the intended consumer of these rows (the
  `consumed` column exists specifically for that future phase to claim
  a trigger without deleting history).
- **Not a feedback-to-training-data pipeline.** Corrections captured
  via `feedback_events` are not promoted into any training dataset by
  this phase — same stance every existing `*/feedback` endpoint already
  took before Phase 11 (see `app/services/feedback_service.py`'s own
  docstrings). Doing so would be a separate, explicit, human-reviewed
  step.
- **Not calibrated.** The 0.5/0.6 confidence thresholds are development
  defaults, not derived from any measured calibration curve for any of
  the six participating modules.
