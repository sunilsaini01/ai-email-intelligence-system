# Sentiment Analysis Module — Architecture (Phase 7A)

> **Data status**: no human ever labelled a single email for sentiment in
> this repository. The served model is a zero-shot lexicon scorer, not
> trained on anything — see `docs/data_audit_sentiment.md` before trusting
> any metric in `docs/model_cards/sentiment.md`.

## What This Module Establishes

The fifth production ML module, and the first one that requires **no
trained artifact at all** — not "an artifact that might be missing" (spam/
priority/category's 503 path) and not "an artifact that's optional /
lazy-loaded" (summarization's abstractive path), but structurally none.
`VaderSentimentPredictor` wraps a fixed lexicon shipped inside the
`vaderSentiment` package; "loading the model" is just constructing an
object, cheaper than every other module's warm-up by a wide margin (0.79ms
average prediction latency vs. priority's ~29s first-construction cost).

## Request Flow

```
POST /api/v1/sentiment/predict {subject?, body}
        │
        ▼
Pydantic validation (SentimentPredictionRequest)
        │
        ▼
SentimentService.analyze()
        │  EmailPreprocessor(SENTIMENT_CONFIG).process(f"{subject} {body}")
        │  (lowercase=False -- preserves VADER's capitalization-intensity
        │   signal; see model card "A Bug Found and Fixed")
        ▼
VaderSentimentPredictor.predict(cleaned_text)
        │  SentimentIntensityAnalyzer().polarity_scores() -> compound score
        │  bucket_compound() -> one of FR-29's 5 classes
        │  _pseudo_distribution() -> disclosed heuristic confidence (NOT calibrated)
        ▼
        ├──► structured log (app.sentiment) -- metadata only, never body/subject
        ├──► SentimentPredictionRepository -- audit row (subject/body stored,
        │    same as spam/priority/category -- no `emails` table yet)
        │
        ▼
SentimentPredictionResponse {sentiment, confidence, probabilities,
                              model_version, processing_ms}
```

## Why `app/inference/sentiment_predictor.py`, Not `app/pipeline/`

Every classification module before this one (spam/priority/category) fits
the "TF-IDF (+ engineered features) → classical classifier, fit/predict/
save/load" shape that `MLPipeline`/`PriorityMLPipeline`/`CategoryMLPipeline`
share, and `Trainer`/`ArtifactManager` persist. `VaderSentimentPredictor`
has no `fit()` at all — there is nothing to train, nothing to persist, and
nothing for `ArtifactManager` to load. It fits the `inference/` layer's
`*ClassifierBackend` Protocol pattern (dependency inversion, same as
`SpamClassifierBackend`/`PriorityClassifierBackend`) without needing
`pipeline/`'s training-oriented machinery at all — the honest fit, not a
forced one. (A trained comparison classifier *was* built this phase,
reusing `MLPipeline`/`Trainer`/`ArtifactManager` exactly as-is — see
`backend/scripts/train_sentiment_model.py` — but it is explicitly not what
`SentimentService` serves; see the model card's "Model Selection.")

## No `SentimentServiceUnavailable` — Why This Module Has No 503 Path

Same reasoning as summarization's endpoint: there is no "hasn't been
trained yet" state to guard against, because nothing about
`VaderSentimentPredictor` depends on a training script having run. If the
`vaderSentiment` package itself failed to import, that surfaces as a
process-startup `ImportError`, not a per-request 503 — the same failure
class as a missing `transformers` install, not a runtime state this
service needs to handle per-request.

## Feature-Schema / Artifact-Compatibility: Deliberately Not Involved

Phase 6 Gate 1 (`app/feature_engineering/feature_schema.py`) exists because
`ContentFeatures`/`MetadataFeatures` are *shared* across priority and
category — extending one silently broke the other's artifact once already.
Sentiment's served path touches neither dataclass (VADER scores raw text
directly, not engineered features) and has no persisted artifact to
version at all, so `FeatureSchema` has nothing to fingerprint here. This
was a deliberate design choice, not an oversight: reusing
`ContentFeatureExtractor` for sentiment-specific lexicon features was
considered and rejected specifically to avoid re-coupling a third module
into the same shared-artifact fragility that Gate 1 was built to guard
against (see `docs/data_audit_sentiment.md` §4 "Why C over D," and the
Phase 7A repository audit's Gate G finding).

## Database — Same Pattern as Spam/Priority/Category, Not Summarization

`sentiment_prediction_logs` stores `subject`/`body` directly, unlike
`summary_logs`. Same reasoning as the other three modules' audit logs (no
`emails` table exists yet to reference) — summarization's decision to
*not* store source content was specific to that module's generation-task
shape (Step 16's "avoid sensitive-content duplication," applied there
because the *summary itself* already substantially represents the source);
sentiment produces a short label, not a substitute for the source, so the
same "store the source for feedback correction to point at" reasoning spam/
priority/category already use applies here too. Verified structurally:
`tests/test_sentiment_prediction_log.py`.

This phase also fixed a pre-existing gap surfaced auditing this: `app/models/__init__.py`
was missing `CategoryPredictionLog` and `SummaryLog` (added in Phases 5/6,
never registered for Alembic's `Base.metadata` discovery). Fixed alongside
adding `SentimentPredictionLog`, verified against a real, disposable
Postgres 16 container (`alembic upgrade head` from a clean database, all 5
tables created correctly) — not just SQLite, per this phase's own Gate 30
instruction. Regression-tested: `tests/test_model_metadata_registration.py`.

## Security Review

**No PII anonymization applied before scoring** — same reasoning already
established for summarization: not evaluated as necessary for a pure
polarity-scoring task, and anonymizing entities isn't in tension with
sentiment scoring the way it is with FR-26's entity preservation (there's
no direct conflict), but no requirement currently calls for it either.
Revisit if/when this text ever reaches an external API (none does today).

**Prompt injection**: not applicable. `VaderSentimentPredictor` is a fixed
lexicon lookup with no instruction-following mechanism of any kind — a
structurally smaller attack surface than even the extractive summarizer
(which at least does document-structure-dependent sentence selection).
Verified via `tests/test_sentiment_security.py`, not just asserted.

**Structured log hygiene**: `app.sentiment` logger only ever receives
`sentiment`/`confidence`/`model_version`/`processing_ms` in its `extra`
fields — never raw subject/body text, even though the DB audit row does
store them (different trust surfaces, same distinction spam/priority/
category already draw). Verified: `tests/test_sentiment_security.py`.

## Explicitly Deferred This Phase (Not Oversights — See `data_audit_sentiment.md` §1)

| Deferred | Reason |
|---|---|
| FR-30 (primary emotion detection) | Distinct 5-class taxonomy needing its own data audit — treated like Intent (Phase 7B), not bundled into polarity sentiment |
| FR-31 (feed into priority score) | Would require modifying `priority_service.py`'s decision logic before sentiment itself has any real-world evidence behind it — same coupling risk this phase's own principles warn against for Sentiment/Intent |
| FR-32 (sender trend tracking) | Analytics/aggregation capability belonging with the Phase 10 dashboard (`GET /analytics/sentiment`), not a single-prediction API |

## Known Gaps

| Gap | Reason |
|---|---|
| Real email-domain sentiment ground truth | Gate H/I conclusion — no such dataset found anywhere in reach of this session; see `docs/data_audit_sentiment.md` §2 |
| Sarcasm / indirect / politeness-masked negativity detection | Structural limitation of lexicon scoring — see `docs/error_analysis_sentiment.md` |
| Calibrated confidence scores | No ground truth exists to calibrate against — see model card "Calibration" |
| 5-class bucket thresholds validated by human agreement | Currently a disclosed heuristic (`±0.05`/`±0.6` on VADER compound) — see `docs/data_audit_sentiment.md` §3 |
