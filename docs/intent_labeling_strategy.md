# Intent Detection — Labeling Strategy (Single vs. Multi-Label + Annotation Plan)

## 1. Single-Label vs. Multi-Label — Decision

**Multi-label. Determined directly from the PRD, not a judgment call.**
FR-34: *"System shall support multi-intent detection per email."* PRD §8.2's
own data-requirements section gives the deciding example explicitly:
*"Multi-label allowed (one email can have Complaint + Refund intent)"* —
the exact "cancel my subscription and refund my last payment" scenario this
phase's own instructions raised as a hypothetical is, in fact, the PRD's
own worked example, not a hypothetical needing a business-judgment call.

**Consequence for architecture**: `IntentMLPipeline` uses the same
`OneVsRestClassifier` + `MultiLabelBinarizer` shape as `CategoryMLPipeline`
(9 independent binary decisions, not one softmax over mutually-exclusive
classes) — see `docs/architecture_intent.md`.

## 2. Annotation Strategy (Not Yet Started — Forward-Looking, per Step 7)

Same structural role as `docs/annotation_guidelines_sentiment.md` and
`docs/annotation_guidelines_categorization.md` — a process specification
for the real annotation effort this phase does not perform.

### Sample Size

PRD-specified minimum: **5,000+ emails, minimum 500 per class × 9 classes
= 4,500** (PRD §8.2). Given multi-label overlap (an email counted toward
multiple classes), the PRD's 5,000+ overall figure is the binding target,
not a simple 9×500 sum.

### Sampling Strategy

Stratify by each of the 9 classes' own keyword-heuristic pre-score (from
`intent_synthetic_v1`/`intent_keywords.py`) to ensure adequate coverage of
rare classes — per `docs/data_audit_intent.md` §3, Order/Refund/Cancel are
expected to be rare in any Enron-sourced pre-sample, so pure random
sampling from Enron would under-represent exactly the classes multi-label
correctness depends on most. If real annotation draws from a different
(non-Enron) source entirely — which is the more likely real-world path,
since Enron's domain mismatch is disclosed as more severe for this module
than for priority/category (see `docs/data_audit_intent.md` §3) — this
stratification approach would need re-deriving against that source's own
class distribution instead.

### Number of Annotators

**3 independent annotators per email**, matching the PRD's priority/
category precedent (§8.2) and Sentiment's carried-forward convention.

### Annotation Guidelines

`docs/intent_taxonomy.md` (this phase's canonical taxonomy doc) is the
starting guideline document — inclusion/exclusion criteria and borderline
cases are already specified there, reusable directly as the annotator-facing
reference rather than duplicated here.

### Pilot Annotation

Recommended: 100-email pilot batch before the full run, specifically to
surface additional borderline cases beyond the ones already documented in
`docs/intent_taxonomy.md` (Complaint/Escalation overlap, Request's
residual-class boundary) — the same "pilot catches guideline gaps before
they compound across 5,000 emails" discipline implicit in
`docs/annotation_guidelines_categorization.md`.

### Inter-Annotator Agreement

**Multi-label agreement cannot use a single scalar Kappa the way
single-label priority classification can** — each of the 9 classes is an
independent binary judgment. Recommended: compute **Cohen's Kappa
per-class** (annotator agreement on "does this email carry the Complaint
label," independently for each of the 9 classes), then report the
per-class distribution rather than one averaged number, since a single
average could hide one class (most likely a rare/ambiguous one, e.g.
Escalation vs. Complaint) with poor agreement. **Target: per-class Kappa ≥
0.65**, matching Sentiment's precedent-setting rationale (slightly below
priority/category's 0.70 single-label bar, since intent boundaries —
especially Complaint/Escalation and Inquiry/Request — are more subjective
than priority's) — an engineering recommendation, since the PRD specifies
no explicit intent-annotation agreement threshold.

### Adjudication

A fourth, senior annotator adjudicates any (email, class) pair where the 3
annotators split 2-1 or worse. Given 9 independent binary judgments per
email, this is evaluated per-class, not per-email as a whole — an email
could have unanimous agreement on 8 of its 9 class judgments and still
need adjudication on the 9th.

### Gold Dataset — Three-Way Split

Identical mechanism to priority/category/sentiment: leakage-safe split by
sender (or by whatever grouping unit the real (likely non-Enron) source
uses — see "Sampling Strategy" above), train/val/test, no leakage across
splits.

### Label Distribution (to be measured, not assumed)

Expected to be highly imbalanced given FR-33's mix of common
(Inquiry/Request/Complaint) and narrow (Order/Refund/Cancel/Schedule)
categories — should be measured against real annotation output, not
assumed to match the synthetic bootstrap's distribution (which is itself
distorted by Enron's domain mismatch — see `docs/data_audit_intent.md` §3).

### Label Quality Acceptance Criteria

A completed annotation batch is acceptable only if: per-class Kappa ≥ 0.65
for every one of the 9 classes (not just the average), no class falls
below 3% of the labelled set, and the adjudicated disagreement rate is
reported per-class alongside the Kappa scores.
