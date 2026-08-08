# Model Card — Email Summarization (Extractive Baseline + Abstractive Option)

> **Evaluated against BBC News Summary — real, human-written summaries,
> but NEWS, not email.** See `docs/data_audit_summarization.md`. Every
> metric in this document is a **model validation** metric (real signal
> about summary quality on formal written English), not evidence of
> real-world email-summarization quality or PRD compliance for FR-25/26/27.

## Purpose

Convert a long email (or thread) into a short summary while preserving
key names, dates, monetary amounts, and action items (FR-25/26), and
summarize whole threads as one cohesive narrative (FR-27), supporting
both extractive and abstractive generation (FR-28).

## Intended Use

- Summarizing individual emails or threads longer than 200 words (FR-25)
  in a triage/inbox context, using the **extractive path** (the default —
  see "Why Extractive Is the Default," below) for anything latency-sensitive.
- The abstractive path, used deliberately by a caller that has explicitly
  opted in and accepted its measured latency cost (see "Performance").

## Non-Intended Use

- **Not validated on real email** — see "Dataset" below. Do not present
  either model's BBC-measured ROUGE numbers as evidence of email-domain
  quality.
- **Not a substitute for reading Critical/High-priority emails** — a
  summary can omit content (see "Entity Preservation" and "Hallucination
  & Faithfulness Risk"); it is a triage aid, not a replacement for the
  source.
- **The abstractive path should not be used in a hard-latency-bound
  calling context** without accounting for its measured ~4.5s average /
  ~7.6s P95 latency on this CPU-only environment (see "Performance").

## Models

| | Extractive (default) | Abstractive (opt-in) |
|---|---|---|
| Approach | TextRank: TF-IDF sentence vectors → cosine-similarity graph → PageRank centrality → top-K sentences in original order | Off-the-shelf (NOT fine-tuned) `sshleifer/distilbart-cnn-6-6` — a distilled BART model already fine-tuned for summarization (on CNN/DailyMail) |
| PRD alignment | PRD §9.1's named baseline architecture | PRD §9.1 names "Fine-tuned T5-small/BART" as the eventual production model — this is BART, off-the-shelf rather than fine-tuned (see "Why Not Fine-Tune," below) |
| New dependencies | `networkx` (already installed in this environment) | `torch`, `transformers` (already installed in this environment — **not previously declared in requirements.txt**, now added; see `docs/architecture_email_summarization.md`) |
| Deterministic? | Yes | Yes (`num_beams=4`, no sampling) |

## Why Extractive Is the Default

**Measured directly, not assumed** (`backend/scripts/evaluate_summarization_models.py`,
BBC News Summary test sample, n=40):

| Model | ROUGE-1 | ROUGE-2 | ROUGE-L | Avg latency | P95 latency | Avg entity preservation |
|---|---|---|---|---|---|---|
| **Extractive (TextRank)** | **0.6843** | **0.6233** | **0.4834** | **2.57ms** | **4.41ms** | **0.4722** |
| Abstractive (distilbart-cnn-6-6) | 0.3575 | 0.2606 | 0.2782 | 4,501.72ms | 7,601.15ms | 0.3133 |

Extractive wins every column. Two very different reasons, not one:

1. **Latency**: PRD §6.1 sets Summarization's SLA at P50 < 2s, P95 < 4s,
   hard limit 8s. Extractive clears this by roughly three orders of
   magnitude. Abstractive's P95 (7.6s) is *within* the 8s hard limit on
   this specific 40-example sample, but blows through both the P50 and
   P95 *targets* substantially, and a P95 this close to the hard limit on
   a small sample is not a comfortable production margin.
2. **ROUGE**: **read this result correctly, not naively.** BBC News
   Summary's reference summaries are themselves extractive in nature —
   verbatim sentences lifted from the source article (see
   `docs/data_audit_summarization.md` §2's worked example). ROUGE measures
   lexical overlap with the reference. An extractive method scoring far
   higher than an abstractive (paraphrasing) one against extractive-style
   references is an expected, well-documented property of ROUGE, **not
   proof that the abstractive model produces objectively worse
   summaries.** A human-preference evaluation could plausibly favor the
   abstractive summaries' more natural phrasing despite the lower ROUGE —
   that evaluation was not run this phase (see "Known Gaps"). What ROUGE
   *does* legitimately show here: on this benchmark, extractive summaries
   are demonstrably more faithful to the reference's specific word choices,
   which is a real, relevant signal for FR-26 (verbatim source spans are,
   definitionally, faithful to the source).

**Both remain available via `summary_type` (FR-28 requires supporting
both) — extractive is the service default, not the only option.**

## Why Not Fine-Tune

`docs/data_audit_summarization.md` Gate 4: no real email+reference-summary
dataset exists anywhere in reach of this engineering session. Fine-tuning
against BBC News Summary (news, wrong domain, wrong reference length —
median 142 words vs. FR-25's 2-3-sentence target) would optimize toward
the wrong target shape, with no reason to expect the result transfers
better to email than the already-summarization-tuned model used zero-shot.
Same "don't fine-tune without data that justifies it" discipline already
applied to every classical baseline in this repository, extended to the
generative case.

## Dataset

`data/processed/summarization_bbc_v1` — see `docs/data_audit_summarization.md`
for the full audit. Summary: 2,127 unique (deduplicated from 2,225) BBC
News articles with real, human-written reference summaries; 1,701/213/213
train/val/test, stratified by category. **Real summaries, wrong domain** —
supports model-quality comparison, not PRD compliance.

## Preprocessing

`EmailPreprocessor(SUMMARY_CONFIG)` — strips HTML, quoted replies, and
signatures (per-message, load-bearing for FR-27's thread-dedup — see
`app/nlp/thread_summarizer.py`), preserves casing (dates/names/amounts are
case-sensitive-meaningful) and does not lemmatize (a lemmatized "pay" for
source "paid" would be a needless, unfaithful edit in output meant to be
read verbatim).

**A real preprocessing bug was found and fixed this phase**: `SUMMARY_CONFIG`
inherited `PreprocessingConfig`'s default `min_token_length=2`, which
silently dropped every single-character token — including single digits
and the word "I" — from any text that passed through it. `"I will pay you
$5 for the 3 items"` became `"will pay you $5 for the items"`: a dropped
subject pronoun and, materially worse for FR-26, a **silently vanished
quantity**. Caught by this phase's own test suite
(`tests/test_summarization_security.py`), not shipped silently. Fixed by
setting `min_token_length=1` on `SUMMARY_CONFIG` specifically — the
default remains unchanged for spam/priority/category, where token
filtering is a reasonable feature-engineering step, not a reader-facing
prose fidelity issue.

**A second real bug was found and fixed in the same pass**: the
sentence-splitting utility (`app/nlp/extractive_summarizer.py`) discarded
each sentence's terminal punctuation when splitting, so a multi-sentence
extractive summary was rejoined with **no periods between the original
sentences at all** — readable as one run-on string. Fixed by capturing
each sentence WITH its trailing punctuation. Caught by this phase's own
tests, not the BBC evaluation (which measures lexical overlap, not
readability, and ROUGE's own tokenizer ignores punctuation — this bug did
not move any ROUGE number, only real output readability, which is exactly
the kind of defect an automatic metric alone cannot catch).

## Entity Preservation (FR-26)

Measured via `app/nlp/summary_grounding.py`, NOT assumed: regex-based
extraction for dates (`DATE_PATTERN`, extended this phase to also catch
spelled-out amounts like "15000 dollars," not just symbol-prefixed ones)
and monetary amounts, spaCy NER for person names. Reports a preservation
rate — fraction of source entities found (case-insensitive substring
match) in the summary — `None` (not `0.0`) when the source contained no
such entities, so "nothing to preserve" isn't conflated with "preserved
nothing."

**Known conservative bias**: substring matching means a summary that
writes "J. Smith" for a source's "John Smith" is scored as NOT preserving
that name — understating true preservation somewhat. Not fixed with fuzzy
matching, which could just as easily overstate it; disclosed instead.

## Hallucination & Faithfulness Risk

- **Extractive summarization structurally cannot hallucinate** in the
  usual generative sense — every returned sentence is a verbatim substring
  of the (preprocessed) source. Its failure mode is *omission* (a real
  action item not selected into the summary), not invention.
- **Abstractive summarization can, in principle, invent or misstate
  content** — this is inherent to any generative seq2seq model. Not tested
  exhaustively this phase (no dedicated adversarial hallucination-probing
  dataset exists), but the entity-preservation measurement above is a
  direct, if partial, proxy: abstractive's measured preservation rate
  (0.3133) is meaningfully *lower* than extractive's (0.4722), consistent
  with (though not proof of) the abstractive path dropping or
  paraphrasing-past entities more often. **Residual risk is real and not
  quantified further this phase** — do not treat the abstractive path's
  output as verified-faithful without a human check, especially for
  Critical/High-priority email content.

## Prompt Injection (Step 19)

Both models are structurally low-risk, for different reasons:
- **Extractive**: has no mechanism to "follow" anything — it selects and
  returns existing source sentences via TF-IDF/PageRank scoring. Injected
  text like "ignore previous instructions" is just another sentence
  competing for centrality score, not a control-flow input.
- **Abstractive**: `distilbart-cnn-6-6` is a fine-tuned seq2seq
  *summarization* model, not an instruction-tuned chat model — it has no
  trained "instruction-following" behavior to hijack in the first place.
  This is a materially smaller attack surface than an LLM-based
  summarizer would have, **not a claim of zero risk** — a sufficiently
  unusual input could still influence generation in unexpected ways, just
  not via a recognized "instruction" channel this model was ever trained
  to obey. Verified structurally (see `tests/test_summarization_security.py`),
  not just asserted.

## Performance (measured, not estimated)

| Operation | Extractive | Abstractive |
|---|---|---|
| Startup warm-up cost | Included in eager startup warm-up (cheap — TF-IDF/networkx, no model download) | **NOT eagerly warmed** — lazy-loads on first abstractive request; first load measured ~115s (one-time weight download + init) |
| Avg inference latency | 2.57ms | 4,501.72ms |
| P95 inference latency | 4.41ms | 7,601.15ms |
| PRD SLA (P50<2s / P95<4s / hard limit 8s) | **Meets with enormous margin** | **Misses P50/P95 targets; P95 within (but close to) the 8s hard limit on this sample** |

## Cost

No external API calls (both models run locally) — no per-request monetary
cost, unlike an external LLM API. The real cost is compute/latency,
quantified above, and the one-time ~115s abstractive model download
(cached after first load).

## Limitations

1. **No real email-domain evaluation exists** — see "Dataset." The
   central limitation, applies to every metric in this document.
2. **Abstractive latency substantially exceeds the PRD's own SLA targets**
   on this CPU-only environment — usable only where a caller has
   explicitly accepted that cost (see "Why Extractive Is the Default").
3. **Entity preservation is measured, not guaranteed** — 47.2%
   (extractive) / 31.3% (abstractive) average preservation rates mean a
   majority of source dates/amounts/names are NOT reliably surviving into
   the summary today. FR-26 compliance is a measured number, not an
   achieved property.
4. **No BERTScore** (PRD §14.1's secondary metric) — disclosed gap, see
   `docs/phase6_requirements_traceability.md`.
5. **No human-preference evaluation** — the "ROUGE structurally favors
   extractive" caveat above means a human quality judgment could tell a
   materially different story; not collected this phase.
6. **Thread handling's near-duplicate detection uses a simple Jaccard
   threshold** (`app/nlp/thread_summarizer.py`), not semantic similarity —
   a quoted reply reworded significantly rather than quoted verbatim could
   evade dedup and get double-counted.

## Known Gaps (Not Implemented — Documented for Next Phase)

1. Human-preference evaluation (rubric: factuality/relevance/completeness/
   conciseness/actionability, 1-5 scale each) — would directly resolve the
   "ROUGE favors extractive" ambiguity above, not yet run.
2. BERTScore.
3. Real email+reference-summary annotation effort (mirrors
   `docs/annotation_guidelines_categorization.md`'s process, adapted for a
   generation task) — not started; see `docs/data_audit_summarization.md` §7.
4. Semantic (not just Jaccard-lexical) thread deduplication.
