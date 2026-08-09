# Similar Email Retrieval — Error Analysis

**Status: qualitative/exploratory, not statistically meaningful.** Same
role as `docs/error_analysis_routing.md`/`docs/error_analysis_intent.md` —
surfaces real findings, not a trustworthy accuracy number. This document
also records two genuine engineering incidents found and fixed during this
phase's own testing, which is itself part of the honest evidence trail.

## Incident 1: TF-IDF Vocabulary Pollution (Found via End-to-End Smoke Test)

The first version of `scripts/train_tfidf_embedder.py` fit a
`TfidfVectorizer` directly on raw `body_text_raw` text with no cleaning.
An end-to-end smoke test (indexing three emails, searching for "refund")
returned **every similarity score as exactly 0.0**, including for a query
that should obviously have matched an indexed refund-related email.

**Root cause**: the 512-term vocabulary that resulted was dominated by
HTML markup fragments (`"align left"`, `"td tr"`, `"style"`), personal
names, and — specifically — an Enron internal fantasy-football mailing
list's jargon (`"fantasy sportsline"`, `"league ene"`, `"football292"`).
Common business words like "refund" and "weather" never made the cut.
Confirmed directly: `'refund' in vocab` → `False`.

**Fix**: text now runs through `EmailPreprocessor(SPAM_CONFIG)` (strips
HTML/signatures, lemmatizes) before fitting; the corpus was expanded from
one 7,000-row synthetic dataset to two combined and deduplicated
(`priority_synthetic_v1` + `category_synthetic_v1`); `max_features` raised
to 1024 with `min_df=3` to drop one-off noise. Re-verified directly:
`sim("refund...payment...account", "reimburse...bill...charge...account")`
= **0.57** post-fix (was 0.0). The training script now also runs a
sentinel-term sanity check and refuses to save an artifact if it fails —
this class of bug cannot silently reoccur without the training run itself
erroring out.

**A residual, disclosed (not fixed) limitation**: even post-fix, only 2 of
5 sentinel business terms (`"contract"`, `"meeting"`) made the vocabulary
— `"refund"`, `"invoice"`, `"urgent"` did not. This is **not a remaining
bug** — it's the same, already-well-documented Enron domain mismatch
Intent's own data audit found (`docs/data_audit_intent.md`: "Order/Refund/
Cancel are consumer-transactional concepts largely absent from Enron's
B2B corpus"). Fetching a better corpus is `TO BE RESEARCHED`, not
attempted here.

## Incident 2: A Windows Import-Order Crash (Found via Full Regression Suite)

Adding the `retrieval` endpoint module to `app/api/v1/router.py` caused
**the entire test suite to segfault** (`Windows fatal exception: access
violation`) at a pre-existing, unrelated test
(`test_category_dataset.py`, which reads a parquet file via
`pandas`/`pyarrow`) — a real, reproducible regression, not a fluke.

**Root cause, isolated by direct reproduction** (not guessed):
`app/security/pii_anonymizer.py` originally constructed
`AnalyzerEngine()`/`AnonymizerEngine()` **eagerly at module import time**.
Because `app/api/v1/router.py` imports its endpoint modules
alphabetically, `retrieval` (which transitively imports Presidio) loads
*before* `summarization` (which imports `transformers`/`torch`). When
Presidio's spaCy-backed native code initializes before `transformers`
finishes its own native runtime setup, a Windows-specific fault follows
the first time `pyarrow` is subsequently imported (by anything reading a
parquet file) — confirmed by testing with the exact same module set in a
different order, which did not crash.

**Fix attempt 1** (necessary but insufficient alone): made Presidio's
engines lazy (`app/security/pii_anonymizer.py`, `@lru_cache`-constructed
on first call) — the architecturally correct fix regardless (matches
every other heavy-dependency component's established lazy-loading
convention in this codebase), but the crash persisted, now as a *different*
fault (`Windows fatal exception: stack overflow`, inside a circular
`transformers` → lazy-`sklearn`-resolution → `pandas` → `pyarrow` import
chain) — meaning a second, independent fragility was exposed underneath
the first.

**Fix attempt 2** (resolved it): `sklearn`/`pandas` are now imported
directly and first in `app/main.py`, before `app.api.v1.router` — forcing
them into `sys.modules` before `transformers`' own lazy-module resolution
ever gets a chance to trigger that import chain itself. Verified directly:
the exact reproduction command that crashed before this fix now
completes cleanly. Full regression suite: 327 passed, 1 skipped, 0 failed
(up from the 274-test pre-Phase-9 baseline), confirmed stable across
repeated runs.

This is disclosed as a real environment/dependency-version fragility
(`transformers`/`scikit-learn`/`pandas`/`pyarrow`, this exact version
combination, Windows-specific), not an application design flaw — see
`app/main.py`'s own inline comment for the mechanism, kept in the code
itself since this is exactly the kind of fix a future contributor could
accidentally undo by reordering imports without realizing why the order
matters.

## Retrieval Quality — Qualitative Gold Set

`scripts/qualitative_eval_retrieval.py` — 15-email hand-written corpus (6
topic clusters: billing, IT access, IT outage, HR, sales, scheduling,
legal, marketing), 5 queries with author-judged expected-relevant sets.
Sampling method: hand-written for topic-cluster coverage, **not** randomly
sampled from real traffic (none exists) — not claimed statistically
representative.

| Embedder | Mean Recall@5 | Mean Precision@5 |
|---|---|---|
| TF-IDF baseline | 0.93 | 0.44 |
| all-MiniLM-L6-v2 | 0.93 | 0.44 |

**Both embedders scored identically on this metric** — disclosed
honestly as a limitation of this evaluation's scale, not evidence the two
are equivalent. With only 15 documents and `top_k=5`, Recall@5 is
forgiving enough that ranking-quality differences don't show up; the
direct pairwise comparison in `docs/embedding_model_decision.md`
(TF-IDF 3/6 vs. MiniLM 6/6 on paraphrase pairs) is the more informative
evidence of a real quality gap between the two.

One imperfect result on both embedders: the "System outage" query (`{c6}`
expected as most relevant, with `{c4, c5}` as secondary IT-access matches)
scored recall@5=0.67 for both — `c6` (the outage email) was retrieved,
but ranked behind the IT-access-cluster emails rather than the query's
primary intended match. A single, small-sample data point, not
generalized into a claim about outage-vs-access disambiguation quality.

## Classification

Per this project's established distinction: this document is **ENGINEERING
VALIDATION** (does retrieval behave sensibly on hand-constructed cases) —
explicitly **not PRODUCTION ML VALIDATION** (whether real users would find
these results useful), because no human-labelled retrieval-outcome ground
truth exists. See `docs/model_cards/embedding_retrieval.md` "Evaluation."
