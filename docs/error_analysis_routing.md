# Email Routing Engine — Error Analysis

**Status: qualitative/exploratory, not statistically meaningful.** Based on
20 hand-written examples (`backend/scripts/qualitative_eval_routing.py`),
run through the full `RoutingService` path (real trained Spam/Category/
Intent/Priority artifacts + zero-shot Sentiment + the rule engine). Same
role and scale as `docs/error_analysis_intent.md`/`docs/error_analysis_
sentiment.md` — surfaces failure patterns, not a trustworthy accuracy
number. Sampling method: author-written to cover each department, each
high-impact department, the unreliable-Intent policy, spam/degenerate
input, and signal-conflict cases — **not** randomly sampled from real
traffic (none exists), **not** claimed statistically representative.

## Headline Finding: The Spam Gate Over-Fires on Ordinary Business Email, Blocking Most of This Sample From Reaching Department Routing

**13 of 20 examples were quarantined by `R-SPAM-GATE`** — including a
sales pricing inquiry, a billing refund request, an HR complaint, an IT
access request, and a legal contract review. Spot-checked spam scores
against the real trained model (threshold `0.06`):

| Example | `spam_score` | `is_spam` |
|---|---|---|
| Sales pricing inquiry | 0.3918 | True |
| Billing refund request | 0.1859 | True |
| HR workplace complaint | 0.1004 | True |
| IT access/VPN request | 0.1448 | True |
| IT outage (internal sender) | 0.0040 | False |
| Support bug report | 0.0079 | False |

**This is not a Phase 8 routing bug — it is a real, disclosed
characteristic of the upstream Spam model applied outside the domain it
was evaluated on.** `docs/model_cards/spam_detection.md` documents the
`0.06` threshold as deliberately chosen to maximize recall (99.44%) on a
**validation set drawn from SpamAssassin/SMS Spam/Amazon Polarity
corpora** — 91.33% precision *on that domain*. It was never evaluated
against ordinary short business-email text of the kind Category/
Priority/Intent's own Enron-derived training data already uses, and which
Routing now feeds it via composition. The practical effect discovered
here: an aggressively recall-tuned classifier, applied to text unlike its
own evaluation domain, produces enough false positives that **most of
this qualitative sample never reaches department routing at all** —
`R-SPAM-GATE` pre-empts everything (`docs/routing_conflict_resolution.md`),
so a false-positive spam call fully masks whatever Category/Intent/
Sentiment/Priority would otherwise have decided.

**This is now the highest-priority disclosed risk for Routing's practical
usefulness** — higher-impact than any of the four already-known synthetic-
label caveats, because it doesn't just weaken one signal's trustworthiness,
it can prevent department routing from running at all. Recorded as a new
entry in `docs/ml_data_maturity_roadmap.md` and README.md's "Known Gaps."
**Not fixed in this phase** — recalibrating Spam's threshold is Phase 3's
artifact and would need its own validation against a business-email-domain
holdout (which does not currently exist, same class of gap as Priority/
Category's own data situation) before changing a number that Phase 3's own
94%+ recall claim depends on. Routing's own logic (the spam gate itself,
the precedence order) is working exactly as designed; the input it's
gated on is the problem.

## Per-example results

| Example | Predicted dept. | Expected dept. | Review (pred/exp) | Action | Rules fired |
|---|---|---|---|---|---|
| Support: bug report | Support | Support ✅ | False/False ✅ | auto_route | R-CATEGORY-AUTO-ROUTE |
| Sales: pricing inquiry | *(quarantined)* | Sales ❌ | False/False | quarantine | R-SPAM-GATE |
| Billing: refund request | *(quarantined)* | Billing ❌ | False/True ❌ | quarantine | R-SPAM-GATE |
| Legal: contract review | *(quarantined)* | Legal ❌ | False/True ❌ | quarantine | R-SPAM-GATE |
| HR: workplace complaint | *(quarantined)* | HR ❌ | False/True ❌ | quarantine | R-SPAM-GATE |
| IT: access request | *(quarantined)* | IT ❌ | False/False | quarantine | R-SPAM-GATE |
| Marketing: press inquiry | *(quarantined)* | Marketing ❌ | False/False | quarantine | R-SPAM-GATE |
| General: no clear category | General | General ✅ | False/True ❌ | auto_route | R-CATEGORY-AUTO-ROUTE |
| Escalation, corroborated by negative sentiment | *(quarantined)* | — | False/True ❌ | quarantine | R-SPAM-GATE |
| Escalation, NOT corroborated | *(quarantined)* | — | False/False | quarantine | R-SPAM-GATE |
| Refund intent, non-Billing category | Billing | — | True/True ✅ | human_review | R-CATEGORY-LOW-CONFIDENCE |
| Spam-like content | *(quarantined)* | — | — | quarantine | R-SPAM-GATE |
| Empty email | *(quarantined)* | — | — | quarantine | R-SPAM-GATE |
| Critical priority, ambiguous category | *(quarantined)* | — | False/True ❌ | quarantine | R-SPAM-GATE |
| HTML email, billing | *(quarantined)* | Billing ❌ | False/True ❌ | quarantine | R-SPAM-GATE |
| Cancel + Complaint (multi-intent) | Billing | — | True/— | auto_route | R-CATEGORY-AUTO-ROUTE, R-HIGH-IMPACT-DEPARTMENT-REVIEW |
| Order status inquiry | *(quarantined)* | — | — | quarantine | R-SPAM-GATE |
| Internal sender, IT outage | IT | IT ✅ | False/False ✅ | auto_route | R-CATEGORY-AUTO-ROUTE |
| Unicode/non-English content | General | — | True/— | human_review | R-CATEGORY-LOW-CONFIDENCE |
| Scheduling request | *(quarantined)* | — | — | quarantine | R-SPAM-GATE |

Full script output (department/review match counts, restricted to rows with
a firm expectation) reproduced from a real run:
`backend/scripts/qualitative_eval_routing.py`.

## Second Finding: When Spam Doesn't Fire, the Rule Engine Itself Behaved as Designed

Excluding the 13 spam-gated rows, every remaining decision matched its
documented rule exactly:

- **Support/IT auto-routed correctly** at high confidence, no false review
  flag (the two clean non-high-impact department matches).
- **"Cancel + Complaint" correctly auto-routed to Billing with mandatory
  review** — `R-HIGH-IMPACT-DEPARTMENT-REVIEW` fired as designed on a
  HIGH_IMPACT department, independent of confidence.
- **"Refund intent, non-Billing category"** correctly stayed off Billing
  (`R-CATEGORY-LOW-CONFIDENCE`, not a Refund-driven override) and flagged
  review — the unreliable-Intent policy behaved exactly as documented in
  `docs/routing_conflict_resolution.md`: Refund never independently
  selected a department.
- **Unicode/non-English content** correctly fell to `R-CATEGORY-LOW-
  CONFIDENCE` + human review rather than a confident wrong guess — the
  Category classifier's TF-IDF vocabulary is English-only, and low
  confidence on out-of-vocabulary text is the honest, safe outcome, not a
  crash or a silent high-confidence guess.

**One genuine miss, independent of the spam-gate issue**: "General: no
clear category" auto-routed to General at a confidence high enough to
clear the auto-route threshold *without* triggering human review, even
though the input ("Just wanted to say hello...") has essentially no
department signal. This suggests the category classifier can be
overconfident on generically-worded text that happens to score highest for
General specifically — worth a follow-up check once real category
evaluation data exists (`docs/data_audit_categorization.md`), since
`General`'s own calibration was never separately verified
(`docs/model_cards/email_categorization.md` "Calibration").

## Classification

Per the Phase 8 brief's required distinction: this document is
**ENGINEERING VALIDATION** (does the rule engine behave as documented, given
its inputs) — it is explicitly **not PRODUCTION ML VALIDATION** (whether
routing decisions are actually correct in the real world), because no
human-labelled routing-outcome ground truth exists. See
`docs/model_cards/routing.md` "Evaluation" for the full validation-type
breakdown.
