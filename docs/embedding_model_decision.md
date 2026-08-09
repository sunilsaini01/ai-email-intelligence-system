# Embedding Model Decision (Module 9 / Phase 9, Step 8)

## The PRD's Suggestion Was Verified, Not Assumed — and Found Broken

The PRD suggests `all-MiniLM-L6-v2` for production, TF-IDF for baseline
(§9.1's own table: `"Email Embeddings | TF-IDF vectors | all-MiniLM-L6-v2"`).
Before writing any embedding code, `sentence-transformers` (the obvious way
to serve MiniLM) was tested directly and found to **segfault on import** in
this environment — verified with Python's `faulthandler`, the crash is
inside `sentence-transformers==5.6.0`'s own `base/model_card.py` import
chain, not in `torch`, which imports and runs fine standalone. This was
surfaced to the project owner before any implementation began, not
discovered partway through and patched over.

**Resolution**: `all-MiniLM-L6-v2`'s published weights are loaded via
`transformers` directly (`AutoTokenizer`/`AutoModel` + manual mean-pooling
+ L2 normalization, `app/inference/minilm_embedder.py`) — `transformers`
is already a proven, working dependency in this codebase (Module 6's
abstractive summarizer). This reproduces sentence-transformers' standard
output without the broken wrapper package — verified against a smoke test
before being relied on (sim(refund, reimburse)=0.56, sim(refund,
weather)=-0.03, the semantically correct result).

## Baseline (TF-IDF) Was Also a Real Bug, Not Just a Simple Baseline

The first version of `scripts/train_tfidf_embedder.py` fit directly on raw
Enron text with no cleaning. Discovered via Phase 9's own end-to-end smoke
test (not caught by a unit test — the unit tests used a fake embedder):
the resulting 512-term vocabulary was dominated by HTML fragments (`"align
left"`, `"td tr"`), personal names, and an Enron fantasy-football mailing
list's jargon (`"fantasy sportsline"`, `"league ene"`) — ordinary words
like "refund" and "weather" never made the cut, so **every similarity
score came back exactly 0.0 regardless of actual relevance**. Fixed by
running text through `EmailPreprocessor(SPAM_CONFIG)` before fitting,
combining two corpora (`priority_synthetic_v1` + `category_synthetic_v1`,
7000 real Enron documents after dedup), raising `max_features` to 1024,
and adding `min_df=3` to drop one-off noise terms — plus a sanity check
baked directly into the training script that refuses to save an artifact
if none of a small set of sentinel business terms made the vocabulary.
See `docs/error_analysis_retrieval.md` for the full incident record.

## Measured Comparison (Step 8's Actual Requirement)

`scripts/benchmark_embedding_models.py`, run directly, real numbers:

| Metric | TF-IDF baseline | all-MiniLM-L6-v2 (via transformers) |
|---|---|---|
| Dimension | 1024 | 384 |
| Cold-start latency (first call) | 1.4 ms | 152.1 ms |
| Warm latency (avg of 20 calls) | 0.20 ms | 6.27 ms |
| Batch latency (10 texts) | 0.04 ms/text | 2.12 ms/text |
| Qualitative paraphrase-pair check (6 hand-written pairs) | **3/6** correct | **6/6** correct |

**The qualitative check result is the important finding, not a footnote**:
TF-IDF scored exactly **0.000** (zero vocabulary overlap) on all three
"similar" pairs that used different words for the same concept ("refund"
vs. "reimburse," "server down" vs. "not responding," "schedule a call" vs.
"meeting Tuesday") — a structural blindness to paraphrase, not a tuning
issue. MiniLM correctly separated all 6 pairs. This is consistent with
what TF-IDF *is*: a bag-of-words method with zero notion of word meaning
beyond exact-string co-occurrence in its fitted vocabulary.

On the small qualitative retrieval gold set
(`scripts/qualitative_eval_retrieval.py`, 15-email corpus, 5 queries),
**both embedders scored identically** (Mean Recall@5 = 0.93, Mean
Precision@5 = 0.44 for both) — disclosed honestly as a limitation of that
evaluation's scale, not evidence the two are equivalent: with only 15
documents and top-K=5, the ranking metric is too forgiving to surface the
paraphrase-blindness the direct pairwise comparison demonstrated clearly.
The pairwise benchmark is the more informative evidence here.

## Decision: TF-IDF Remains the Structural Default, With the Gap Disclosed

`RetrievalService._resolve_embedder()` defaults to `TfidfEmbedder` —
**not** because it's judged better (the evidence above says otherwise for
retrieval quality), but for two disclosed, evidence-adjacent reasons:

1. **Zero network dependency, fully deterministic** — matches this
   project's established "local-first" pattern (VADER needs no download;
   every classifier's `.joblib` artifact is local) and keeps the test
   suite free of a cloud/network dependency (Phase 9 brief Step 32: "Do
   not make tests dependent on a cloud service").
2. Consistent with the PRD's own framing of TF-IDF as the module's
   baseline, not a placeholder to be silently forgotten.

**This is disclosed as a real trade-off, not resolved silently**: any
deployment that cares about retrieval quality over network-independence
should inject `MiniLmEmbedder` via `RetrievalService`'s constructor —
already fully working, already benchmarked, a one-line change, not a
redesign. Recommended explicitly as a Phase 10 follow-up in the final
Phase 9 report, not decided unilaterally here.

## Not Evaluated (and Why)

A third alternative (a larger/different sentence-embedding model) was not
benchmarked — no evidence the two already-compared options are
insufficient, and RULE 3/Step 8 asks for "at least one reasonable
alternative," satisfied by MiniLM vs. TF-IDF. Introducing a third,
heavier model without a demonstrated gap would contradict the "start with
an efficient baseline" instruction this same step gives.
