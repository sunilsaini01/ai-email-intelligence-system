# Intent Detection Module — Architecture (Phase 7B)

> **Data status**: no human-labelled email intent data exists anywhere in
> this repository — see `docs/data_audit_intent.md` before trusting any
> metric in `docs/model_cards/intent.md`.

## What This Module Establishes

The sixth production ML module, and the second multi-label one (FR-34,
after Categorization). Unlike Sentiment (Phase 7A, zero-shot, no trained
artifact), Intent has a served, trained artifact — the priority/category
precedent (synthetic keyword-heuristic bootstrap → trained classifier →
disclosed SYNTHETIC), not the sentiment precedent (zero-shot lexicon
scorer), because no off-the-shelf, zero-shot equivalent to VADER exists for
domain-specific business-intent categories.

## Request Flow

```
POST /api/v1/intent/predict {subject?, body}
        │
        ▼
Pydantic validation (IntentPredictionRequest)
        │
        ▼
IntentService.analyze()
        │  cleaned = EmailPreprocessor(CATEGORY_CONFIG).process(subject+body)
        │  result  = IntentPredictor.predict(cleaned)   -- trained classifier
        │  entities = extract_intent_entities(RAW subject+body)  -- FR-35,
        │             regex + spaCy NER, independent of the classifier,
        │             runs on RAW (not lemmatized) text -- see service
        │             module comment for why
        ▼
        ├──► structured log (app.intent) -- metadata only, never body/subject
        ├──► IntentPredictionRepository -- audit row (subject/body + entities stored)
        │
        ▼
IntentPredictionResponse {intents: [{intent, confidence}, ...] (may be []),
                           all_scores, entities, model_version, processing_ms}
```

## Why `IntentMLPipeline`, Not a Reuse of `CategoryMLPipeline`

Both are TF-IDF + `OneVsRestClassifier` + `MultiLabelBinarizer` — the
shapes rhyme. Two reasons a new class was created rather than reusing or
generalizing `CategoryMLPipeline`, both surfaced during this phase's
repository audit (Gate B):

1. `CategoryMLPipeline` hardcodes `CATEGORY_LABELS` as a module-level
   import inside `__init__`, not a constructor parameter — it cannot serve
   a different label set without modification.
2. Refactoring `CategoryMLPipeline` into a generic, label-set-parameterized
   class was considered and rejected: it is an already-shipped,
   artifact-pickled, tested class, and touching shared pipeline
   infrastructure is exactly what caused the Phase 5 `ContentFeatures`
   incident (see `docs/architecture_email_categorization.md` "Incident").
   A parallel, independent class carries zero risk to Category's already-
   working artifact.

## Why `IntentMLPipeline` Is TF-IDF-Only (No `ContentFeatures`/`MetadataFeatures`)

Unlike `PriorityMLPipeline`/`CategoryMLPipeline`, `IntentMLPipeline` does
not pull in the shared engineered-feature dataclasses at all — deliberately,
not by omission:

- The PRD's own suggested classical baseline for Intent is literally
  "TF-IDF + Multi-label LR," with no engineered-feature component named
  (contrast Priority's FR-17, which explicitly requires "subject keywords,
  time of day" as inputs).
- Avoiding the shared `ContentFeatures`/`MetadataFeatures` dataclasses a
  third time avoids re-opening the exact cross-module fragility the Phase
  6 `FeatureSchema` mechanism (`app/feature_engineering/feature_schema.py`)
  exists to guard against — every dataclass extension forces a retrain of
  every pipeline that consumes it; not consuming it at all is the more
  robust choice when nothing requires it. Sentiment (Phase 7A) made the
  identical choice for the identical reason.
- Consequence: `IntentMLPipeline` has no `feature_schema` attribute at all
  (verified: `tests/test_intent_pipeline.py::test_pipeline_has_no_feature_schema_attribute`)
  — there is nothing to fingerprint, and no artifact-compatibility failure
  mode of that class exists for this module.

`intent_keywords.py`'s 9 lexicons still exist, but feed ONLY the synthetic
label generator (`generate_synthetic_intent_dataset.py`), never a model
feature — see `docs/data_audit_intent.md` §5 for the full leakage-channel
comparison against priority/category.

## FR-35 Entity Extraction — Reuse, Not Reimplementation

`app/nlp/intent_entities.py` reuses `app/nlp/summary_grounding.py`'s
`extract_entities()` (dates, monetary amounts, person names — built for
FR-26, identical extraction need here) rather than reimplementing regex/NER
logic a second time, and reuses that module's cached spaCy NER pipeline
directly rather than loading a second one. Two genuinely new pieces this
phase: `ORDER_ID_PATTERN` (`app/feature_engineering/patterns.py`, requires
an explicit "order" cue word plus at least one digit in the captured token
— the digit requirement was added after this phase's own testing caught a
false positive on "in order to proceed," see
`docs/error_analysis_intent.md`) and `extract_product_names()` (spaCy's
`PRODUCT` NER label, disclosed as low-recall — `en_core_web_sm`'s small
model tier is known to under-perform on this category relative to
PERSON/ORG/DATE).

## Why Intent Detection Has a 503 Path (Unlike Sentiment)

`IntentService` raises `IntentServiceUnavailable` → HTTP 503 when
`intent_baseline.joblib` doesn't exist, mirroring Category/Priority/Spam —
this module serves a trained classifier with a real "hasn't been trained
yet" state, unlike Sentiment's zero-shot VADER predictor (nothing to be
missing). See `docs/data_audit_intent.md` §4 for why Intent's data
situation led to a different served-model choice than Sentiment's.

## No `INTENT_CONFIG` — Reuses `CATEGORY_CONFIG`

Considered and rejected creating a dedicated preprocessing config: Intent's
TF-IDF-over-lemmatized-text need is structurally identical to Categorization's
(both are bag-of-words-style multi-label classification over business-email
text), and no intent-specific preprocessing sensitivity analogous to
Sentiment's capitalization-intensity finding was discovered during this
phase's testing. If one emerges later, add a dedicated `INTENT_CONFIG`
then, rather than pre-emptively — see `train_intent_model.py`'s module
comment.

## No Coupling to Sentiment — Architectural Boundary Maintained

Per this phase's own explicit instruction and Phase 7A's precedent-setting
decision: `IntentService` does not import, depend on, or share any
infrastructure with `SentimentService` beyond both reusing the same generic
`EmailPreprocessor`/`FeedbackLogger`/API-layering patterns every module
shares. No `sentiment → intent` data flow exists. If a future Routing
Engine (Phase 8) needs both signals, it composes them at that layer, not
here — see FR-36, FR-38.

## Database — Three JSON Columns, Not Two

`intent_prediction_logs` mirrors `category_prediction_logs`'s
`predicted_categories`/`confidences` JSON-column pattern, plus a third
JSON column (`entities`) neither Category nor any prior module has —
FR-35's extracted entities are audit-logged alongside the intent decision,
same "log what was produced" principle as every other module. Subject/body
ARE stored (same as spam/priority/category/sentiment, unlike
`summary_logs`) — no `emails` table exists yet to reference.

This phase's DB-metadata audit (Step 19) found `app/models/__init__.py`
already correctly registers all 5 prior models (fixed in Phase 7A) —
verified directly before adding `IntentPredictionLog`, not assumed. All 6
migrations verified end-to-end against a real, disposable Postgres 16
Docker container, including a downgrade/upgrade round-trip
(`alembic downgrade -1` then `alembic upgrade head`), not just SQLite.

## Security Review

No PII anonymization applied (same stance as Sentiment/Summarization — not
currently required, revisit if this text ever reaches an external API).
Prompt injection not applicable (classical TF-IDF classifier + regex/NER
entity extraction, no instruction-following mechanism) — verified via
`tests/test_intent_security.py`. Structured logs confirmed to never carry
raw subject/body, same pattern as every prior module.

## Known Gaps

| Gap | Reason |
|---|---|
| Real email-domain intent ground truth | Gate 3/4 conclusion — no such dataset found anywhere in reach of this session, and the PRD itself confirms none exists; see `docs/data_audit_intent.md` |
| Escalation class reliability | Empirically the least trustworthy of the 9 classes — over-fires on unrelated text AND under-fires on its own target case; see `docs/error_analysis_intent.md` |
| Order/Cancel/Refund domain mismatch | Enron's B2B corporate correspondence has structurally little genuine consumer-transactional content — see `docs/data_audit_intent.md` §3 |
| Product-name extraction | Low-recall by disclosure — spaCy `en_core_web_sm`'s `PRODUCT` NER category is weak for the small model tier |
| FR-36's routing/auto-reply consumers | Out of scope — this phase produces the intent signal only, per the same "produce the signal, don't wire the consumer" boundary every prior module's deferred cross-module integrations already use |
