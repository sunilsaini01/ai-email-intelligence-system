# Email Summarization Module — Architecture (Phase 6)

> **Data status**: evaluated against real, human-written summaries of the
> wrong domain (news, not email) — see `docs/data_audit_summarization.md`.
> Read that before trusting any metric in `docs/model_cards/email_summarization.md`.

## What This Module Establishes

The fourth production ML module, and the first one that's a **generation**
task, not classification — no `fit`/`predict`/`classes_` shape to share
with `MLPipeline`/`PriorityMLPipeline`/`CategoryMLPipeline`. It's also the
first module to introduce a genuinely new, heavy dependency class
(`torch`/`transformers`) to this codebase, and the first to require
resolving a real, reproduced cross-module regression (Gate 1) and a
years-old-in-this-codebase open bug (Gate 2) before being allowed to add
new functionality — see the "Gates" section of the Phase 6 completion
report for the record of that work; this document covers the module itself.

## Request Flow

```
POST /api/v1/summarization/predict {subject?, body | messages, summary_type, max_sentences}
        │
        ▼
Pydantic validation (SummarizationRequest) — exactly one of body/messages required (FR-27)
        │
        ▼
SummarizationService.summarize()
        │  body case: EmailPreprocessor(SUMMARY_CONFIG).process(body)
        │  messages case: ThreadNormalizer.build_narrative() — chronological order,
        │                 per-message signature/quote stripping, near-duplicate dedup (FR-27)
        ▼
word_count <= 200?  ──yes──► return as-is (FR-25's short-input floor, "model_version": "none")
        │no
        ▼
summary_type == "extractive"?
        │yes                                          │no
        ▼                                              ▼
ExtractiveSummarizer                          chunking.summarize_long_text()
(TextRank: TF-IDF → cosine-sim graph          (map-reduce over MODEL_MAX_INPUT_TOKENS-sized
 → PageRank → top-K in original order)         chunks if needed) → AbstractiveSummarizer
        │                                              │  (sshleifer/distilbart-cnn-6-6,
        │                                              │   lazy-loaded, off-the-shelf)
        └──────────────────┬───────────────────────────┘
                            ▼
              summary_grounding.check_preservation()  (FR-26 — measured, not assumed)
                            ▼
        ├──► structured log (app.summarization) ── metadata only, never body/summary text
        ├──► SummaryRepository ── audit row, best-effort (NO source body/subject stored — Step 16)
        │
        ▼
SummarizationResponse {summary, summary_type, skipped_short_input, input_word_count,
                        preserved_entities, entity_preservation_rate, model_version, processing_ms}
```

## Why `app/nlp/`, Not `app/pipeline/` or `app/inference/`

Every prior module's inference code fits the "load a persisted, trained
estimator, call predict()" shape (`SpamPredictor`, `PriorityPredictor`,
`CategoryPredictor`, all behind a `*ClassifierBackend` Protocol). Nothing
here is trained by this codebase or persisted as a fitted artifact —
`ExtractiveSummarizer` computes TF-IDF/PageRank fresh per call (nothing to
train), and `AbstractiveSummarizer` loads pre-trained (elsewhere, by
Hugging Face) weights, not a `.joblib` this repo produced. Forcing either
into `app/inference/`'s Protocol pattern (which exists specifically to let
a classical model swap for a transformer behind a stable interface) would
be modeling a swap that isn't the shape of what's actually here — a new,
small `app/nlp/` package is the honest fit, not a refactor of infrastructure
built for a different problem shape.

## No `SummarizationServiceUnavailable` — Why This Module Has No 503 Path

Spam/priority/category all raise a typed `*ServiceUnavailable` exception
(mapped to HTTP 503) when their trained `.joblib` artifact hasn't been
produced by a training script yet. Summarization has no equivalent
artifact-dependency: extractive is pure computation, abstractive downloads
pre-trained weights from Hugging Face on first use rather than depending
on anything this repo trains. There is no "hasn't been trained yet" state
to guard against. (There IS a possible "model download failed" failure
mode for the abstractive path specifically — handled with a direct
try/except → 503 at the endpoint, not a service-level typed exception,
since it's a narrower, path-specific failure, not a whole-service
unavailability the way a missing baseline `.joblib` is.)

## New Dependency: `torch` / `transformers` (and the requirements.txt gap this surfaced)

Both were **already installed in this development environment** (verified
directly: `torch==2.12.1+cpu`, `transformers==5.13.0`) but **not declared
in `requirements.txt`** before this phase — meaning a fresh clone or CI
environment would have had no guarantee of having them, only worked here
by coincidence of this machine's global Python environment. Added
explicitly this phase (`requirements.txt`), with a note on that file
documenting that several other pre-existing runtime dependencies
(scikit-learn, pandas, spacy, presidio, ...) share the same
never-declared gap from earlier phases — a pre-existing issue, not
introduced here, and out of this phase's scope to fully reconcile (see
`requirements.txt`'s own comment for the honest accounting).

## Why the Abstractive Model Isn't Eagerly Warmed at Startup

`app/main.py`'s `lifespan` handler eagerly warms spam/priority/category
(combined ~9s, per `docs/architecture_priority_classification.md`
"Performance") plus summarization's **extractive** path (cheap — no model
download). The abstractive model's first load measured **~115s** — warming
it eagerly would very nearly double process startup time for a path most
requests won't use (extractive is the default). Lazy-loaded via
`@lru_cache`-decorated `get_abstractive_summarizer()` instead — the same
`lru_cache`-singleton pattern every other service already uses, just
triggered by first actual use instead of by startup.

## Database — Deliberately Different From the Other Three Modules

`summary_logs` stores the summarization **output** (the summary itself,
plus size/performance metadata) but, unlike `spam_prediction_logs` /
`priority_prediction_logs` / `category_prediction_logs`, does **NOT**
store the source subject/body. This is a deliberate reading of Step 16's
instruction ("Do not store full email content unnecessarily. Avoid
sensitive-content duplication.") — the other three modules' audit logs
predate that instruction being made explicit for this phase and store
source content for a documented reason (no `emails` table exists yet to
reference — see `spam_prediction_log.py`'s docstring). This module applies
the same "no `emails` table yet" reasoning to justify persisting the
*summary* (there's genuinely nowhere else for feedback correction to point
at), while treating "the full source body" as a separate question this
phase answers differently: a summarization log's job is to record what was
*produced*, and the source is not needed to audit that. Verified
structurally, not just by convention:
`tests/test_summary_prediction_log.py::test_summary_log_table_has_no_source_body_column`.

## Security Review

**PII anonymization is NOT applied before summarization — and here,
unlike spam/priority/category, that's not merely "unnecessary," it would
be actively harmful.** FR-26 requires *preserving* names/dates/amounts;
Presidio-style anonymization (`app/security/pii_anonymizer.py`) exists
specifically to *replace* exactly those entity types with placeholders.
Wiring it in ahead of summarization would directly contradict the
module's own functional requirement. Revisit only if/when this text ever
reaches an external API (no such call exists in this module today), same
trigger condition already established for the other three modules.

**Prompt injection**: see the model card's dedicated section — both
summarizer types have a structurally small attack surface (extractive has
no instruction-following mechanism at all; abstractive is a fine-tuned
seq2seq summarizer, not an instruction-tuned model), verified via
`tests/test_summarization_security.py`, not just asserted in prose.

## Known Gaps

| Deferred | Reason |
|---|---|
| Real email-domain evaluation data | Gate 4 conclusion — no such dataset found anywhere in reach of this session; see `docs/data_audit_summarization.md` §7 |
| BERTScore | Disclosed infrastructure-cost gap — see `docs/phase6_requirements_traceability.md` |
| Human-preference evaluation | Not run this phase — would resolve the "ROUGE structurally favors extractive" ambiguity the model card flags |
| Abstractive path's latency vs. PRD SLA | Measured, not solved — see model card "Performance"; usable only where a caller has explicitly opted in and accepted the cost |
| Semantic (not just lexical/Jaccard) thread-message deduplication | `app/nlp/thread_summarizer.py`'s current dedup can be evaded by a significantly reworded quote |
| Fine-tuning either model on real data | Blocked on the same data gap as everything else in this table — see model card "Why Not Fine-Tune" |
