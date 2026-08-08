# Model Card — Sentiment Analysis (VADER Lexicon Baseline, PROVISIONAL)

> **THIS MODEL IS NOT PRD-COMPLIANT AND IS UNVALIDATED ON EMAIL DATA.**
> No human-labelled email sentiment data exists anywhere in this
> repository. The served model (`VaderSentimentPredictor`) is a lexicon
> scorer that requires no training data and was never fit to any dataset —
> its accuracy on real email sentiment is genuinely unmeasured, not merely
> "measured on the wrong domain" the way priority/category's synthetic
> models are. See `docs/data_audit_sentiment.md` for the full data strategy
> decision and `docs/error_analysis_sentiment.md` for concrete, characterized
> failure modes.

## Model Details

| Field | Value |
|---|---|
| Model type | VADER (Valence Aware Dictionary and sEntiment Reasoner) — lexicon + rule-based compound polarity scorer |
| Package | `vaderSentiment==3.3.2` |
| Training data | **None.** VADER ships a fixed, pre-built lexicon; nothing in this repo trains it. |
| Serving code | `backend/app/inference/sentiment_predictor.py` (`VaderSentimentPredictor`) |
| Taxonomy mapping | 5-class bucketing of VADER's `compound` score (`-1.0` to `+1.0`) — see `docs/data_audit_sentiment.md` §3 for exact thresholds, disclosed as a heuristic choice |
| Preprocessing | `EmailPreprocessor(SENTIMENT_CONFIG)` — `lowercase=False` (preserves VADER's capitalization-intensity signal, see "A Bug Found and Fixed" below), `remove_stopwords=False`, `lemmatize=False`, `min_token_length=1` |
| Model version reported by API | `vader-lexicon-3.3.2` |

## Why VADER, Not a Trained Classifier — Model Selection (Gate 22)

Two candidates were built and evaluated this phase (`docs/data_audit_sentiment.md`
§4 has the full comparison table); this section is the evidence behind that
decision, not a restatement of it.

**Candidate A — VADER zero-shot (chosen, served).** Requires no training
data. Runs directly on real email text (no domain-transfer question to ask,
since nothing was trained on a different domain). Latency: **0.79ms average**
per prediction (`train_sentiment_model.py`'s benchmark, n=879, real Enron
test split) — negligible compared to even the cheapest classical baseline
elsewhere in this codebase.

**Candidate B — TF-IDF + classical ML, trained on `sentiment_synthetic_v1`
(built, evaluated, NOT served).** `sentiment_synthetic_v1`'s labels are
themselves VADER's own bucketed compound score over real Enron text — so a
classifier trained on it is trained to predict VADER's own output, not an
independent signal. Its ceiling is agreement with VADER, not improvement
over it. **Measured result** (`backend/scripts/train_sentiment_model.py`,
held-out test split, n=879):

| Model | Macro F1 (vs. VADER-derived labels) | Weighted F1 | Accuracy |
|---|---|---|---|
| **Logistic Regression (best)** | **0.3324** | 0.6392 | 0.6212 |
| SVM | 0.2917 | 0.6689 | 0.7531 |
| Naive Bayes | 0.2128 | 0.6383 | 0.7304 |

**This result argues against serving Candidate B, not just "doesn't argue
for it."** A classifier trained directly on its own label source achieving
only 0.33 macro F1 against that same source means TF-IDF surface features
cannot even reliably reproduce VADER's own bucketing function on held-out
data — the label-imitation task is already hard, before any question of
real-world accuracy enters. Serving this classifier instead of VADER itself
would mean shipping a strictly worse approximation of VADER, dressed up as
a "trained model," which is a more misleading framing than calling VADER
directly. Comparison artifacts (`artifacts/sentiment_comparison.joblib`,
`artifacts/sentiment_comparison_metrics.json`) are retained for this
evidence trail; `SentimentService` does not load them.

**Decision: VADER is served.** Simplest architecture that satisfies the
requirements (Gate 22's own instruction), and the one candidate whose
failure modes are at least well-characterized (see "Error Analysis" below)
rather than compounding a lexicon's limitations with an imperfect imitation
of it.

## A Bug Found and Fixed: `SENTIMENT_CONFIG`'s Inherited `lowercase=True`

`SENTIMENT_CONFIG` was declared in an earlier phase (before any sentiment
module existed to consume it) and was never exercised until this phase
wired it into `SentimentService`. It only overrode `remove_stopwords` and
`lemmatize`, silently inheriting `PreprocessingConfig`'s `lowercase=True`
default. VADER's lexicon explicitly scores capitalized sentiment words more
intensely than lowercase ones ("GREAT" > "great" — documented VADER
behavior) — lowercasing before scoring was discarding a signal the scorer
is designed to use. Found via `backend/scripts/qualitative_eval_sentiment.py`,
fixed by setting `lowercase=False` (and `min_token_length=1`, same
reasoning `SUMMARY_CONFIG` already needed — VADER scores whole text, not a
token bag). The 14-example qualitative set happened not to contain a
capitalized sentiment word, so this fix's practical impact is not
demonstrated by that set specifically — it is a correctness fix in
principle, not a measured improvement.

## Calibration

**Not validated, and cannot be, absent ground truth.** `probabilities` in
the API response is a **disclosed heuristic distribution**
(`_pseudo_distribution()` in `sentiment_predictor.py`), derived from how far
VADER's compound score sits from the nearest bucket boundary, with
remaining mass spread only to ordinally-adjacent classes. This is NOT a
calibrated probability in the sense priority/spam's model cards report
(Brier score, reliability diagrams) — there is no held-out ground truth to
compute either metric against. Do not treat `confidence` as a trustworthy
probability; treat it only as "how deep into its bucket this score fell."

## Error Analysis

See `docs/error_analysis_sentiment.md` for the full breakdown. Headline:
**5/14 (36%) matched author-intended labels** on a hand-written qualitative
set (not statistically meaningful, not ground truth). Dominant failure
pattern: lexicon scoring cannot detect politeness-masked negativity
("polite complaints"), indirect/implicit negativity, or sarcasm — all
well-known, structural limitations of word-lookup sentiment scoring,
disclosed in `docs/data_audit_sentiment.md` in advance rather than
discovered as a surprise. A second pattern — compound-score saturation
toward "Very Positive" on longer, paragraph-length text — is corroborated
independently by the full synthetic dataset's own label distribution
(64.7% "Very Positive" out of 10,000 real Enron emails, `sentiment_synthetic_v1/run_metadata.json`),
which is not a plausible distribution for real business correspondence and
is disclosed as a limitation of applying VADER (tuned for short
social-media text) to full email bodies.

## Intended Use

- **Pipeline development and architecture validation only.** Proves the
  ingestion (N/A here — zero-shot) → service → API → audit-logging →
  feedback path works end-to-end for a generation-free, artifact-free
  inference module.
- **Not intended for any real triage, routing, escalation, or trend
  decision.** FR-31 (feed into priority score) and FR-32 (sender trend
  tracking) are explicitly deferred, not merely unimplemented by omission —
  see `docs/data_audit_sentiment.md` §1.

## Limitations

1. **No human ever validated a single sentiment label this model produces
   against real email data.** This is a stronger limitation than
   priority/category's "trained on synthetic labels" — there, at least a
   labelling *process* (even if heuristic) ran over real email text; here,
   VADER's fixed lexicon was built entirely outside this codebase, on
   unknown (not email) text, by its original authors.
2. **Cannot detect sarcasm, indirect negativity, or politeness-masked
   complaints** — see "Error Analysis" above. These are not edge cases in
   business email; polite complaints in particular may be the *majority*
   presentation of workplace dissatisfaction.
3. **Compound-score saturation on long text** — skews toward extreme
   ("Very Positive"/"Very Negative") on paragraph-length input more than a
   scorer tuned for short text should. Directly evidenced, not assumed
   (see "Error Analysis").
4. **The 5-class bucket thresholds (`±0.05`, `±0.6`) are this phase's own
   disclosed heuristic**, not derived from any human-agreement study — real
   annotation may draw these boundaries differently (`docs/annotation_guidelines_sentiment.md` §1).
5. **`confidence`/`probabilities` are a heuristic distribution, not a
   calibrated probability** — see "Calibration" above.
6. **FR-30 (emotion detection), FR-31 (priority integration), FR-32 (sender
   trend tracking) are explicitly out of scope this phase** — see
   `docs/data_audit_sentiment.md` §1 for the reasoning behind each deferral.

## Path to a PRD-Compliant Model (Not Implemented — Blocked on Annotation)

Identical structure to priority/category's path, per
`docs/data_audit_sentiment.md` §4:
1. Real annotation — minimum 3,000 emails, 3 annotators, Fleiss' Kappa ≥
   0.65 on the 5-class ordinal taxonomy (`docs/annotation_guidelines_sentiment.md`).
2. Once real labels exist, re-evaluate whether VADER zero-shot is still the
   right serving choice, or whether a classifier trained on *real* labels
   (not VADER's own pseudo-labels) can exceed it — this phase's rejection
   of Candidate B was specific to imitation-of-VADER training data, not a
   general claim that trained classifiers can't beat lexicon scoring once
   real signal exists to train on.
3. Only then do the PRD's F1-weighted targets (0.80-0.82, both stated in
   different places in the PRD — see `docs/data_audit_sentiment.md` §1)
   become a meaningful bar.
