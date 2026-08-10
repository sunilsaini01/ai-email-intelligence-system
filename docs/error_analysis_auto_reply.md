# Auto-Reply Generation — Error Analysis

**Status: qualitative/exploratory, not statistically meaningful.** Same
role as `docs/error_analysis_retrieval.md`/`docs/error_analysis_routing.md`
— surfaces real findings, not a trustworthy accuracy number. This document
also records a genuine engineering incident found and fixed during this
phase's own end-to-end testing, which is itself part of the honest
evidence trail.

## Incident 1: Embedder/Vector-Store Reconstructed on Every Call (Found via Real End-to-End Testing)

Unit tests always inject an explicit embedder/vector store into
`RetrievalService`, so this bug was invisible to the entire Phase 9 and
Phase 10 unit/integration test suite (62 new Phase 10 tests, all passing,
never caught it). It was found by running the actual `/reply/generate`
endpoint against a real, disposable Postgres 16 container and the real
Groq API — the same "real Docker container" verification discipline this
project applies to every migration, applied here to a live request path.

**Symptom**: `retrieval_latency_ms` on the first real request was
5848ms — far outside FR-45's 500ms retrieval budget, and close to
consuming FR-50's entire 10s generation budget on its own.

**Root cause, confirmed by direct comparison, not guessed**:
`RetrievalService._resolve_embedder()` and `_resolve_vector_store()`
constructed a brand-new default object on every call when none was
injected:

```python
def _resolve_embedder(self):
    if self._embedder is not None:
        return self._embedder
    from app.inference.minilm_embedder import MiniLmEmbedder
    return MiniLmEmbedder()  # <- new instance, every call
```

This was harmless under Phase 9's original TF-IDF default (loading a
small `.joblib` artifact is cheap either way), but became a real cost the
moment Phase 10 switched the default to MiniLM
(`docs/architecture_auto_reply.md` "Embedder Decision") —
`AutoModel.from_pretrained()` reloads the transformer's weights into
memory every time it is called, regardless of whether the underlying
files are already cached on disk.

**Fix**: both resolvers now memoize their result on the `RetrievalService`
instance (`self._resolved_default_embedder`/`self._resolved_default_vector_store`),
so a warmed-up singleton (`get_retrieval_service()`, `@lru_cache`'d, one
instance per process) actually stays warm across requests — which
`app/main.py`'s own startup-warmup comment already claimed but did not,
until this fix, actually deliver.

**Re-verified directly, before/after**:

| | Retrieval latency |
|---|---|
| Before fix, 1st request | 5848ms |
| Before fix, 2nd/3rd request (still slow — new object every time) | 1421ms / 1445ms |
| After fix, 1st request (warmup extended to cover vector store too) | 1890ms |
| After fix, 2nd/3rd request | 19ms / 19ms |

A SECOND, related gap was found in the same pass: `app/main.py`'s startup
warmup only forced `_resolve_embedder()`, not `_resolve_vector_store()` —
so even after the memoization fix, Chroma's own real, separate
multi-second cold start (`PersistentClient` initialization — independent
of the embedding model) still landed on a live caller's first request.
Fixed by extending the warmup call to force both.

**A residual, disclosed (not fixed) limitation**: the post-fix 1st-request
number (1890ms) is still higher than the warm number (19ms) — the
remainder is Presidio's own analyzer/anonymizer lazy construction
(`app/security/pii_anonymizer.py`, `@lru_cache`-based, not warmed at
startup by either Phase 9 or Phase 10). Not fixed this phase — a
pre-existing Phase 9 gap, disclosed as a known, smaller remaining
cold-start contributor rather than silently left unexplained.

## Manual Qualitative Sanity Check — Real Groq Output, 5 Cases

`scripts/qualitative_eval_auto_reply.py`, run directly against the real,
configured Groq API (not mocked). Results actually observed, not
fabricated:

| Case | generation_policy | LLM latency | Notes |
|---|---|---|---|
| Refund with matching resolved context | `NORMAL_REPLY` | ~563ms | Draft referenced the historical resolution pattern ("processed a full refund... within 3-5 business days") without inventing new details |
| Same refund request, no context | `NO_SIMILAR_EMAILS` | ~428ms | Draft asked clarifying questions instead of fabricating a resolution — a reasonable, safe fallback |
| Vague question, no context | `NO_SIMILAR_EMAILS` | ~345ms | Drafted a plausible-sounding generic answer (support hours) with specific times NOT present anywhere in the input — a real, disclosed hallucination-risk example, exactly the PRD's own named risk ("LLM hallucination in auto-replies") observed directly, not theorized |
| Prompt injection attempt | `UNSAFE_CONTENT` | N/A (LLM never called) | Correctly detected and skipped in ~10ms |
| Sensitive PII (credit card) in body | `NEEDS_HUMAN_REVIEW` | ~558ms | Draft referenced "the credit card number you provided" in the abstract, without ever reproducing the actual digits — anonymization confirmed working end-to-end, not just at the unit level |

**The vague-question case's fabricated support hours is a genuine,
disclosed finding, not swept under the rug**: given a query with zero
grounding (no historical context, no metadata about actual support
hours), the LLM still produced a confident, specific-sounding answer.
This is exactly why FR-49's human-review requirement is structural, not
optional — a system prompt instruction ("never invent facts... never
invent policy details") reduces but does not eliminate this risk, and no
generation-policy gate in this phase's design catches "the model invented
a specific-sounding but ungrounded fact" (that would require a
fact-verification step against real company policy data, which does not
exist as a system in this codebase — out of scope this phase, a
disclosed limitation, not a bug this phase claims to fix).

## Classification

Per this project's established distinction: this document is **ENGINEERING
VALIDATION** (does the pipeline behave sensibly on hand-constructed cases,
including a real, root-caused performance bug found via real testing) —
explicitly **not PRODUCTION ML VALIDATION** (whether real agents would
find these drafts useful), because no Human Acceptance Rate data exists.
See `docs/model_cards/auto_reply.md` "Evaluation."
