# Sentiment Analysis — Data Audit, Taxonomy, and Data Strategy Decision

**Status: gates all of Phase 7A.** Nothing in `docs/model_cards/sentiment.md` or
`docs/architecture_sentiment.md` should be read as PRD-compliant until the
"Data Strategy Decision" section below is resolved by real annotation (§4,
Option A) — see that section for exactly what changes when it is. This
follows the identical pattern already established for
[`docs/data_audit_priority.md`](data_audit_priority.md) and
[`docs/data_audit_categorization.md`](data_audit_categorization.md); this
document does not repeat the reasoning behind that pattern, only applies it.

## 1. PRD Requirements (FR-29 to FR-32, PRD §5 Module 6)

| ID | Requirement (verbatim) |
|---|---|
| FR-29 | System shall classify email sentiment: Very Negative / Negative / Neutral / Positive / Very Positive |
| FR-30 | System shall detect primary emotion: Anger / Frustration / Confusion / Satisfaction / Urgency |
| FR-31 | Negative or Very Negative sentiment on non-spam emails shall increase priority score |
| FR-32 | System shall track sentiment trends per sender over time (for proactive escalation) |

**Scope of this phase (7A), per explicit decision, not oversight:** FR-30
(emotion) is a distinct 5-class taxonomy requiring its own data audit — it is
out of scope here, deferred the same way Intent Detection (Module 7 / Phase
7B) is deferred, per this phase's own "do not prematurely couple" principle.
FR-31 (feed into Priority) would mean modifying `priority_service.py`'s
decision logic before Sentiment itself has any real-world evidence behind
it — the same coupling risk this phase's own instructions warn against for
Sentiment/Intent, applied here to Sentiment/Priority. FR-32 (sender trend
tracking) is an aggregation/analytics capability that belongs with the
Analytics Dashboard (PRD Phase 10, `GET /analytics/sentiment`), not a
single-prediction API — this phase implements prediction + audit logging
only, the same scope boundary every prior module used before its own
dashboard phase existed. All three are documented here as explicit deferred
integration points, not silently dropped.

PRD's own suggested models (§ model comparison table): **Classical = VADER +
TextBlob** (lexicon-based, not TF-IDF+LR like every other module in this
table), **Advanced = fine-tuned RoBERTa-base**. Target metric: **F1-weighted**
— the PRD states two different thresholds in two places (`> 0.82` in the
evaluation-metrics table, `> 0.80` in "Definition of Done") — both are
recorded here rather than silently picking one, since neither is claimed as
met by this phase's data regardless.

## 2. Data Audit — what actually exists today

| Check | Finding |
|---|---|
| `backend/app/data_ingestion/amazon_sentiment_loader.py` | Exists (written in an earlier phase, never wired into any training script until now). Loads `amazon_review_polarity_csv` into `(source, body_text_raw, sentiment_label, sentiment_confidence, is_email=False)`. **`sentiment_confidence` is a hardcoded constant (`0.75`) for every row, not a measured value** — flagged explicitly so it is never mistaken for real annotation confidence if this loader is ever reused. |
| `data/raw/amazon_reviews/amazon_review_polarity_csv/` | Real corpus present on disk, ~3.6M rows available (train+test CSVs), **binary label only** (1=negative, 2=positive — no neutral, no 5-class, no "very" gradations). |
| `data/raw/twitter_sentiment/` | Empty placeholder (`.gitkeep` only). The PRD's second suggested sentiment dataset was never acquired. |
| Full-corpus search (`Glob **/*sentiment*` under `data/`) | No other sentiment-labelled data of any kind exists anywhere in this repository. |
| `dataset_registry.py` (`amazon_polarity` entry, written in an earlier phase, before this audit) | Already correctly flags `domain_match: low`, `trust_level: supplementary`, with known issues including *"Product reviews ≠ business email tone... binary polarity only — no 5-class sentiment or emotion"* and *"Use for Stage 1 pre-training only, then fine-tune on enterprise email."* No enterprise-email-with-sentiment-labels dataset exists to do that fine-tuning against — that prescribed next step is itself blocked. |
| `data/raw/enron/emails.csv` | Real corporate email text, already used as the text source for `priority_synthetic_v1`/`category_synthetic_v1`. **No sentiment label of any kind** — same as those two modules before their synthetic bootstraps were built. |

**Finding: zero human-labelled, email-domain sentiment data exists in this
repository**, and the one sentiment dataset that does exist (Amazon Reviews
Polarity) fails on two independent axes simultaneously, not one:

1. **Domain mismatch** — product reviews, not email. Registry already rates
   this `low`.
2. **Taxonomy mismatch** — binary (Negative/Positive) cannot express FR-29's
   5-class taxonomy (Very Negative/Negative/Neutral/Positive/Very Positive)
   without fabricating additional class boundaries with no basis in the
   original 2-class labels.

This makes Amazon-trained sentiment classification a **worse** evidentiary
position than `priority_synthetic_v1`/`category_synthetic_v1`, which at
least train on real *email* text — Amazon's *input* text is also
domain-mismatched, not just its labels.

### Data Readiness Report

| Dataset | Rows | Labels | Domain match | Trust level | Suitability |
|---|---|---|---|---|---|
| Email sentiment (human-labelled) | **0** | N/A | N/A | N/A | **Not usable — does not exist** |
| Amazon Reviews Polarity | ~3.6M available | Binary (Negative/Positive), real (Amazon's own) | **Low** (wrong domain) | Supplementary | Rejected for training or evaluation — see §4 |
| Enron corpus (raw text, no sentiment label) | ~500K available | None | Medium (real email, 2001-02 domain shift, inherited limitations — see `dataset_registry.py`'s `enron` entry) | Supplementary source | Usable only as the text source for a synthetic bootstrap (§4), same role it already plays for priority/category |
| **`sentiment_synthetic_v1`** (generated this phase) | see `run_metadata.json` | 5-class, **VADER-lexicon-derived pseudo-labels** | Medium (real email text; label itself is machine-heuristic, not human) | `synthetic_bootstrap` | **Pipeline development / classical-baseline-comparison only — see §4.** Not usable for any PRD-compliance claim. |

## 3. Label Taxonomy (FR-29)

Following the PRD's exact 5-class taxonomy — **Very Negative / Negative /
Neutral / Positive / Very Positive** — rather than the simpler 3-class
(Negative/Neutral/Positive) scheme most sentiment tooling defaults to,
because the PRD is explicit about wanting the 5-class gradation (it feeds
FR-31's escalation logic, where "Very Negative" is presumably meant to carry
more priority weight than plain "Negative," even though FR-31 itself is
deferred this phase — see §1).

**Operating question the label answers: "What is the emotional polarity and
intensity of this email's language?"** Not "how urgent is this" (that's
Priority, a different, already-built signal) and not "what specific emotion
is present" (that's FR-30, deferred — see §1).

Because no human annotation exists, this taxonomy is operationalized via
VADER's compound polarity score (range -1.0 to +1.0) rather than through
annotator judgment, using threshold buckets:

| Label | VADER compound range | Rationale |
|---|---|---|
| Very Negative | `compound <= -0.6` | |
| Negative | `-0.6 < compound <= -0.05` | `-0.05` is VADER's own published neutral boundary |
| Neutral | `-0.05 < compound < 0.05` | |
| Positive | `0.05 <= compound < 0.6` | |
| Very Positive | `compound >= 0.6` | |

**This bucketing is a disclosed heuristic choice, not a validated boundary.**
The `±0.05` neutral band is VADER's own documented convention; the `±0.6`
"Very" threshold is this phase's own choice (roughly the 90th/10th
percentile of compound scores on real email-adjacent text in informal
testing), with no human-agreement study behind it. It should be revisited if
real annotation ever happens (§4, Option A) — real annotators may draw the
Negative/Very-Negative line in a different place than a fixed lexicon
threshold does.

## 4. Data Strategy Decision

| | **A — Custom annotation** | **B — Amazon Reviews Polarity (public/proxy)** | **C — VADER zero-shot (no training)** | **D — VADER-pseudo-labeled Enron (synthetic bootstrap)** |
|---|---|---|---|---|
| Validity vs. PRD | Only option that actually satisfies FR-29's underlying business need | Does not satisfy it (wrong domain AND wrong taxonomy) | Does not satisfy it (unvalidated on email domain) | Does not satisfy it, and cannot (label is machine-heuristic) |
| Domain relevance | High (real enterprise email, if sourced right) | **Low** — product reviews, not email | Medium — runs directly on real email text, no training-domain mismatch to speak of (nothing was trained) | Medium — real Enron email text, same as priority/category |
| Taxonomy fit | Controllable (guidelines specify the 5-class scheme directly) | **None** — binary only, cannot express 5 classes without fabrication | Full — VADER's continuous compound score maps to any bucket scheme chosen | Full (inherits VADER's bucketing) |
| Cost | High — genuine paid-labor line item | Low | **None** — no training step, no dataset needed | Low (compute only) |
| Time | Weeks | Hours | **Minutes** | Hours |
| Leakage risk | Manageable with proper split design | Unknown (not applicable — rejected before this matters) | None — nothing is trained | Structural, same class as priority/category: a classifier trained on VADER-pseudo-labels can only ever approximate VADER's own outputs (this is empirically verified in `docs/model_cards/sentiment.md` §Model Selection, not just asserted) |
| Suitable for final PRD evaluation? | **Yes — the only option that is** | No | No (unvalidated on domain) | No, and structurally cannot become so (see leakage row) |

**Decision: Option C (VADER zero-shot) is the served default; Option D is
built and evaluated as a documented comparison, not served.** Option A is
out of scope for the same reason it is for priority/category (no path to
hiring/coordinating human annotators from inside an engineering session).
Option B is rejected outright — training on Amazon reviews would produce a
model with *two* independent mismatches to defend simultaneously, a strictly
worse evidentiary position than what priority/categorization already
disclosed, for no offsetting benefit.

### Why C over D as the served model (the model-selection reasoning, stated in advance)

A classifier trained on VADER-pseudo-labels is being trained to predict
VADER's own output. Its ceiling is *agreement with VADER*, not improvement
over it — there is no information in the training signal beyond what VADER
already computed. Serving that trained classifier instead of VADER itself
would dress up a lexicon score as if it were a "model-learned" result, which
is a *more* misleading framing than calling VADER directly, not a more
rigorous one. Option D is still built and evaluated (§ baseline comparison,
`docs/model_cards/sentiment.md`) because comparing the two empirically is
itself informative evidence (does a trained classifier even reach
near-total agreement with its own label source? — a real check on the
synthetic dataset's internal consistency), and because it mirrors the same
"trained TF-IDF baseline" step every other module in this repo has gone
through. But the served API defaults to VADER, per "choose the simplest
model that satisfies the requirements" (this phase's own §22).

### What this decision means concretely

1. **Served (this phase, now):** `VaderSentimentPredictor` — zero-shot,
   lexicon-based, no artifact dependency, runs directly on real email text.
   Its accuracy on real email sentiment is genuinely unvalidated (no ground
   truth exists to validate against) — this is disclosed as **PROVISIONAL**,
   not claimed as accurate.
2. **Comparison-only (this phase, documented, not served):** a TF-IDF +
   classical-ML classifier trained on `sentiment_synthetic_v1`
   (VADER-pseudo-labeled Enron text), evaluated against VADER's own labels
   on a held-out split. Existing purely as evidence for the model-selection
   decision above, using the same `MLPipeline`/`Trainer`/`ArtifactManager`
   path every other module uses — see `docs/model_cards/sentiment.md`.
3. **PRD-compliant track (future, blocked on annotation budget):** identical
   to priority/category's track 2 — once real human-labelled email
   sentiment exists, the same served predictor's interface is unchanged;
   only the model behind `SentimentClassifierBackend` needs to swap from
   VADER to a trained-and-validated classifier.

**No metric produced in this phase will be described as satisfying FR-29's
underlying business need, or the PRD's F1-weighted target, in any document in
this repository.**

## 5. Leakage-Safe Split Design (for `sentiment_synthetic_v1`, comparison track only)

Same two reasons already established for priority/category, applied here:

1. **Sender leakage** — Enron email is repetitive per sender; a random split
   can place near-duplicate emails from the same sender in both train and
   test.
2. **Synthetic-label leakage** — VADER's compound score is a deterministic
   function of the text itself, so *any* classifier trained on VADER-labels
   is, structurally, learning to approximate VADER's own text-scoring
   function — this exists independent of split strategy (see §4's
   model-selection reasoning), which is why the comparison track's numbers
   are capped in interpretation regardless of how carefully the split is done.

**Split strategy: grouped by `sender_email`** (`GroupShuffleSplit`), identical
mechanism to `generate_synthetic_priority_dataset.py`.
