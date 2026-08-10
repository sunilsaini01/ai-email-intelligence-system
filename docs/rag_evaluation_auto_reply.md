# RAG Evaluation — Auto-Reply Generation (Phase 10, Step 15/Step 16)

## The Central Discipline: Separate Retrieval Quality From Generation Quality

A good draft produced despite bad retrieved context, or a bad draft
produced despite good retrieved context, are different failure modes with
different fixes (better retrieval vs. better prompting/a better model).
This document keeps them separate rather than reporting one conflated
"is Auto-Reply good" number — which, per RULE 2, this project does not
fabricate anyway, since no real evaluation dataset exists for either half.

## Retrieval Quality — Inherited From Phase 9, Not Re-Measured Here

Auto-Reply's retrieval call is the exact same `RetrievalService.search()`
Phase 9 already evaluated in `docs/error_analysis_retrieval.md` (15-email
qualitative gold set, Mean Recall@5 = 0.93 for both embedders on that
small set — though the more informative evidence there is the pairwise
paraphrase comparison, TF-IDF 3/6 vs. MiniLM 6/6, which is WHY Phase 10
changed the default — see `docs/architecture_auto_reply.md` "Embedder
Decision"). Phase 10 did not re-run that evaluation; it inherits Phase
9's own retrieval-quality evidence and caveats unchanged.

**What Phase 10 changed about the retrieval PATH, not its quality
evidence**: the RESOLVED-status filter (FR-48's own requirement) is new
this phase, and Section C of the Phase 10 audit found this filter is
likely to eliminate MOST or ALL candidates in this system's actual
current state (Phase 9's `resolution_status` never auto-transitions).
This is a retrieval-*availability* finding, not a retrieval-*quality*
finding — even a perfect embedder cannot supply context that was never
marked resolved in the first place.

## Generation Quality — New to This Phase, Small and Manual

No labelled dataset of (query email, ideal reply) pairs exists anywhere
in this project, and none was fabricated here (RULE 2). What exists
instead: `scripts/qualitative_eval_auto_reply.py`, 5 hand-written cases,
run directly against the real, configured Groq API — not mocked, not
estimated. Full case-by-case results in `docs/error_analysis_auto_reply.md`.

**Read qualitatively, not as a metric**:

- **With real resolved context** (1 case): the draft referenced the
  historical resolution pattern without inventing new specifics — the
  RAG mechanism visibly influenced the output in the intended way.
- **Without context, but the request is answerable from the email alone**
  (1 case): the draft asked reasonable clarifying questions rather than
  fabricating a resolution — a safe, appropriate fallback.
- **Without context, and the request has no grounding at all** (1 case):
  the draft fabricated specific-sounding support hours that were never
  provided anywhere in the input — a real, disclosed hallucination
  example, exactly the PRD's own named risk ("LLM hallucination in
  auto-replies," PRD risk table) observed directly rather than
  theorized. See `docs/error_analysis_auto_reply.md` for the full
  discussion of why this is not caught by this phase's generation-policy
  gates.
- **Injection attempt** (1 case): correctly blocked before any LLM call.
- **Sensitive PII in the body** (1 case): flagged for human review,
  generated safely (the raw card number never reached the prompt or the
  output).

## Context Usefulness — Does Retrieved Context Actually Help?

Only one of the 5 manual cases exercised the "with real context" path
(the same case run twice, with and without context, produced visibly
different — and the with-context version more specific and grounded —
drafts). This is a real, directly observed data point that retrieved
context changes generation behavior in the intended direction, but it is
**one comparison**, not a statistically meaningful claim about context
usefulness in general. A rigorous answer would require the same query
run many times with different context conditions and human-judged
quality comparisons — not built this phase, same class of gap as every
other "no real evaluation dataset" disclosure in this project.

## No-Context Fallback — Verified Behavior, Not Just Design Intent

`NO_SIMILAR_EMAILS` and `INSUFFICIENT_CONTEXT` were designed to still
produce a usable, human-reviewable draft rather than refusing to draft
anything (`docs/architecture_auto_reply.md` "Generation Policy"). This is
not just a documented intention — it was directly observed in both the
automated test suite (`tests/test_auto_reply_service.py::test_generate_with_no_context_still_generates_but_flags_no_similar_emails`)
and the real-API qualitative run (2 of 5 cases exercised this exact path
against the real Groq API and produced real, sensible output).

## What Is NOT Measured (Disclosed, Not Hidden)

| Metric | Status |
|---|---|
| Human Acceptance Rate (PRD's own primary metric, >60% target) | **NOT YET MEASURED** — requires real agents and real traffic |
| Recall@K / Precision@K for the RESOLVED-filtered retrieval specifically | Not separately measured this phase — inherits Phase 9's own (differently-scoped) numbers |
| BLEU-4 / BERTScore / Edit Distance | Not computed — no reference replies exist to score against; explicitly secondary to Human Acceptance Rate per the PRD itself |
| Hallucination rate at scale | One directly-observed example (see above), not a measured rate |
| Context-usefulness at scale | One directly-observed comparison, not a measured effect size |

## Classification

**ENGINEERING VALIDATION** (does the RAG pipeline behave sensibly on a
small number of hand-constructed, real-API-verified cases) — explicitly
**not PRODUCTION ML VALIDATION** (whether real agents find these drafts
useful enough to approve with minimal edits), because no Human Acceptance
Rate data exists. Same classification discipline every other phase's
qualitative evaluation document in this project already follows.
