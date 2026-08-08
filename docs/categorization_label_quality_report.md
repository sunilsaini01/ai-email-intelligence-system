# Email Categorization — Label Quality Report

**Classification: UNTRUSTWORTHY (synthetic).** This report exists to make
that classification explicit and auditable, per this phase's Case
A/B/C label-quality framework. Read alongside
`docs/data_audit_categorization.md` (the data strategy decision this report
is a consequence of) and `docs/annotation_guidelines_categorization.md`
(the process that would need to run before this classification could change
to PROVISIONAL or TRUSTWORTHY).

## 1. Dataset Source

`category_synthetic_v1` (`data/processed/category_synthetic_v1/`), generated
by `backend/scripts/generate_synthetic_category_dataset.py` from real Enron
corporate email text and headers (`data/raw/enron/emails.csv`). Registered
in `backend/app/data_ingestion/dataset_registry.py` with
`trust_level="synthetic_bootstrap"`.

## 2. Number of Emails

10,000 total (7,000 train / 2,121 val / 879 test), grouped-split by sender
(no sender crosses a split boundary — see §6 below).

## 3. Category Taxonomy

FR-21's 8 labels: Support, Sales, Billing, Legal, HR, IT, Marketing,
General. Full operational definitions in
`docs/annotation_guidelines_categorization.md` §1.

## 4. Annotation Methodology

**None. This is the central finding of this report.** No human annotator
looked at any email in this dataset. Labels were assigned by a deterministic
keyword-matching heuristic (`app/feature_engineering/category_keywords.py`
lexicons, per-category adaptive thresholds set from each category's own
score distribution) plus a random per-category label-noise injection (4%
per-bit flip rate, to avoid a trivially-reconstructable lookup table — see
`docs/data_audit_categorization.md` §4). This is Option C from that
document's data-strategy decision, exercised deliberately and disclosed, not
mistaken for annotation.

## 5. Number of Annotators

**Zero.** Not "fewer than recommended" — genuinely zero. Compare against
`docs/annotation_guidelines_categorization.md` §5's specification of 3
independent annotators for the (not-yet-started) real effort.

## 6. Annotation Guidelines

Exist as a specification for future work
(`docs/annotation_guidelines_categorization.md`) but were not used to
produce this dataset — the heuristic generator has its own, separate,
deterministic rule set (keyword lexicons + adaptive thresholds), which is
related to but not the same artifact as the human-facing guidelines. This
distinction matters: the guidelines encode nuanced judgment calls (the
Sales-vs-Billing "existing vs. new revenue" distinction, the multi-label
"legal terms of the invoice" example) that a keyword-count heuristic cannot
apply.

## 7. Inter-Annotator Agreement

**Not applicable — there is only one "annotator" (a deterministic script),
so there is no agreement to measure.** This is precisely why this dataset
cannot be classified as TRUSTWORTHY or even PROVISIONAL: agreement
measurement is the mechanism that would let this report make any claim
about label reliability, and it doesn't exist here.

## 8. Disagreement Analysis

Not applicable, for the same reason as §7.

## 9. Adjudication Process

Not applicable. No adjudication occurred because no independent judgments
existed to adjudicate between.

## 10. Final Label Distribution

From `data/processed/category_synthetic_v1/run_metadata.json` (full
10,000-row dataset, post-noise):

| Category | Count | % of rows |
|---|---|---|
| Legal | 3,652 | 36.52% |
| General | 3,277 | 32.77% |
| Support | 2,754 | 27.54% |
| Marketing | 2,004 | 20.04% |
| Billing | 1,538 | 15.38% |
| Sales | 1,356 | 13.56% |
| IT | 1,127 | 11.27% |
| HR | 1,147 | 11.47% |

Average labels per email: **1.686** (post-noise; 1.599 pre-noise) — confirms
the dataset is genuinely multi-label, not a single-label taxonomy wearing a
multi-label API (locked in by
`tests/test_category_dataset.py::test_average_labels_per_email_is_genuinely_multilabel`).
Measured per-(row, category)-bit noise flip rate: 5.66%, close to the
configured 4% target (the difference is expected — the configured rate is a
per-bit Bernoulli probability, not a guaranteed exact rate).

**Reading this distribution honestly**: this is real Enron corporate text's
keyword-hit distribution, filtered through the category lexicons — it says
something about how Enron-era corporate email happens to use Legal/Billing-
adjacent contract and payment language, and essentially nothing about what
real category prevalence would look like in a different organization's
inbound email. Legal's 36.5% share, for instance, almost certainly reflects
Enron's contract-heavy trading-company vocabulary ("agreement," "contract,"
"compliance") rather than a genuine 1-in-3 real-world Legal rate — see
`docs/data_audit_categorization.md` §2.1 for the same caution already
applied to why Enron text isn't domain-representative of a typical
business's inbound support/sales/billing mix.

## 11. Dataset Limitations

1. **Zero human judgment anywhere in the label-generation path** — the
   central, disqualifying limitation; everything else is secondary to this.
2. **Structural keyword leakage**: the same lexicons that generate the
   labels also feed the model's own `ContentFeatures` (via
   `ContentFeatureExtractor`) — a model can partially "cheat" by
   re-deriving the generating function rather than learning genuine
   category signal. Noise injection (§4) mitigates but does not eliminate
   this (see `docs/data_audit_categorization.md` §4).
3. **Enron domain shift**: 2001-2002 energy-sector corporate email, not
   representative of a 2026 SaaS/enterprise-support inbox's category mix or
   vocabulary.
4. **`X-Folder` was evaluated and rejected as a labeling signal** (direct
   empirical check, `docs/data_audit_categorization.md` §2.2) — this
   dataset's labels come entirely from body/subject keyword matching, not
   from any real organizational signal in the source data.
5. **Per-category adaptive thresholds are themselves a heuristic choice**
   (70th percentile of each category's own nonzero-score distribution) —
   defensible as a way to avoid one fixed cutoff over/under-firing across
   categories with very different natural hit rates, but still a modeling
   decision, not a discovered ground truth.

## 12. Final Gold Dataset Version

**None exists.** `category_synthetic_v1` is not a gold dataset and is never
described as one anywhere in this repository — it is the pipeline-
validation placeholder specified as acceptable scope by
`docs/data_audit_categorization.md` §4's Option C. A real gold dataset
(`category_gold_v1` or similar) would be produced by the process in
`docs/annotation_guidelines_categorization.md`, versioned via DVC per that
document's §13, once that process actually runs.

## 13. Suitable for Model Training?

**Yes — for pipeline/architecture validation training only.** This is
exactly what `backend/scripts/train_category_model.py` does, and its output
metrics are explicitly labeled `SYNTHETIC_DATA: true`,
`PRD_COMPLIANT: false` in `artifacts/category_baseline_metrics.json`. Not
suitable for training any model whose output will be described as
production-ready or business-accurate.

## 14. Suitable for PRD-Compliance Evaluation?

**No.** FR-21 through FR-24 require the system to correctly assign business
categories to real email — a claim this dataset cannot support because no
human ever verified that its labels reflect the actual business category of
any of these 10,000 emails. The PRD's own F1-micro > 0.80 threshold (§14.1)
is reported against this dataset in `category_baseline_metrics.json`
(0.7023, below target) purely as a pipeline-validation reference number —
see that file's own `warning` field and
`docs/model_cards/email_categorization.md` for how that number should and
should not be read.

## Acceptance Criteria (from `docs/annotation_guidelines_categorization.md` §13)

| Criterion | Status |
|---|---|
| Category definitions approved | ✅ Done (`docs/data_audit_categorization.md` §3, `docs/annotation_guidelines_categorization.md` §1) |
| Annotation guidelines finalized | ✅ Done as a specification (this phase); not yet exercised |
| Required annotation sample completed | ❌ Not started |
| 3 independent annotators used | ❌ Not started |
| Inter-annotator agreement measured | ❌ Not applicable — no annotation occurred |
| Agreement meets target or shortfall explained | ❌ N/A |
| Adjudication completed | ❌ N/A |
| No unresolved critical label conflicts | ❌ N/A (no conflicts possible with zero annotators) |
| Class distribution reviewed | ✅ Done for the synthetic dataset (§10) — **not** for real data, which doesn't exist yet |
| Test set finalized | ❌ Only the synthetic test split is finalized; no gold test set exists |
| Dataset version created | ✅ `category_synthetic_v1` versioned in the dataset registry — **not** a gold version |

**Bottom line, stated once more because it's the entire point of this
report existing: this dataset does not satisfy the acceptance criteria for
claiming the categorization model is production-ready, and no document in
this repository claims otherwise.**
