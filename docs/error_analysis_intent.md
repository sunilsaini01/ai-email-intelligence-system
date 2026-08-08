# Intent Detection — Error Analysis

**Status: qualitative/exploratory, not statistically meaningful.** Based on
14 hand-written examples (`backend/scripts/qualitative_eval_intent.py`),
run through the full `IntentService` path (preprocessing + trained
`intent_baseline.joblib` classifier + entity extraction). Same role as
`docs/error_analysis_sentiment.md` — surfaces failure patterns, not a
trustworthy accuracy number.

**Result: 3/14 (21%) exact label-set matches** — notably worse than
Sentiment's 36%, and worth taking seriously as a finding, not explaining
away.

## Per-example results

| Category | Predicted | Intended | Match |
|---|---|---|---|
| Simple inquiry | Inquiry | Inquiry | ✅ |
| Simple complaint | *(none)* | Complaint | ❌ |
| Simple request | Escalation, Refund, Request | Request | ❌ |
| Cancel + Refund (PRD's own example) | Cancel, Refund | Cancel, Refund | ✅ |
| Order status | Escalation, Order | Order | ❌ |
| Escalation | *(none)* | Escalation | ❌ |
| Schedule | Escalation, Schedule | Schedule | ❌ |
| Feedback (positive, not complaint) | Complaint | Feedback | ❌ |
| Complaint + Escalation | *(none)* | Complaint, Escalation | ❌ |
| Polite complaint (no explicit complaint word) | *(none)* | Complaint | ❌ |
| Indirect request phrased as a question | Escalation | Request | ❌ |
| Short, ambiguous ("Thanks!") | *(none)* | *(none)* | ✅ |
| No intent (pure FYI) | Escalation, Schedule | *(none)* | ❌ |
| False-positive risk: "order" as an ordinary word ("in order to proceed") | Order | *(none)* | ❌ |

## The Dominant, Serious Finding: "Escalation" Is Unreliable in Both Directions

**Escalation appears as a false positive in 4 of the 14 examples** — on a
contract request, an order-status question, a scheduling email, and a pure
FYI note, none of which have anything to do with escalation. **Simultaneously,
Escalation fails to fire on the one example actually written to trigger it**
("This is my third email. Please escalate to your manager" → predicted
empty). This is not a threshold-tuning nuance — a classifier that both
over-fires on unrelated text AND under-fires on its own target case is not
exhibiting a coherent decision boundary for this class at all.

**Root cause, traced to the training data, not the classifier
architecture**: Escalation is `intent_synthetic_v1`'s second-rarest class
(4.41% prevalence, 441 positive rows out of 10,000 — see
`data/processed/intent_synthetic_v1/run_metadata.json`), and its training
F1 was already the second-lowest of all 9 classes (0.0968, see
`docs/model_cards/intent.md`). Combined with `class_weight="balanced"`
(which up-weights rare-class errors during training specifically to avoid
the classifier ignoring rare classes entirely), the practical effect on a
weak, noisy signal is a decision boundary that fires unpredictably rather
than conservatively. **DATA ERROR + MODEL ERROR, compounding**: the
underlying keyword-heuristic labels for Escalation are thin and noisy to
begin with (§`docs/data_audit_intent.md`), and `class_weight="balanced"`
amplifies that thin signal's instability rather than correcting it.

## Other Failure Categories

**MODEL ERROR — "Order" false-positives on the ordinary word "order"**:
predicted on "In order to proceed, please confirm receipt" — exactly the
false-positive risk flagged *in advance* in
`app/feature_engineering/patterns.py`'s `ORDER_ID_PATTERN` comment and the
qualitative eval's own example name. Root cause: `intent_keywords.py`'s
`ORDER_KEYWORDS` includes the bare word "order," and the synthetic
generator's adaptive threshold collapsed to 1 (a single keyword hit) for
every class (see `run_metadata.json`'s `per_class_thresholds`) — a single,
common-English-word occurrence is enough to trigger a positive label in
training data, which the classifier then learned as real signal.

**MODEL ERROR — Complaint under-fires without lexical cues**: "Your support
team has been unhelpful for weeks" and the polite-complaint example (no
literal "complaint"/"disappointed"/"unacceptable" word) both predicted
empty. Same structural limitation already disclosed for Sentiment's VADER
(lexicon/keyword-adjacent approaches cannot detect dissatisfaction that
isn't lexically explicit) — expected, not a surprise, but confirmed
concretely here for a second module.

**AMBIGUITY — Feedback vs. Complaint**: "Just wanted to say the new UI is a
big improvement" (positive Feedback) predicted Complaint — the two classes'
keyword lexicons likely share surface vocabulary (commentary about a
product) that TF-IDF alone can't disambiguate by sentiment polarity, since
this classifier has no sentiment-awareness at all (deliberately not
coupled to the Sentiment module — see `docs/architecture_intent.md`).

**AMBIGUITY — Request vs. Inquiry/Order boundary**: "Could you send me the
invoice for last month?" predicted Escalation only (missing Request
entirely) — a genuine miss, not a defensible boundary call, reinforcing
the Escalation over-firing finding above rather than a separate issue.

## What This Does and Does Not Justify

**Does justify**: shipping `intent_baseline.joblib` as disclosed
`SYNTHETIC`/pipeline-validation-only (`docs/data_audit_intent.md`), and
specifically flagging **Escalation as the least trustworthy of the 9
classes** in the model card — this is stronger, evidence-based guidance
than a generic "not PRD-compliant" disclaimer. **Does not justify**: any
claim of usable accuracy for real intent routing — 21% exact-match on 14
author-labelled examples, with a specific, root-caused class-level failure
mode identified, is evidence of *why* this model should not drive FR-36's
routing/auto-reply consumers yet, not just *that* it's unvalidated.
