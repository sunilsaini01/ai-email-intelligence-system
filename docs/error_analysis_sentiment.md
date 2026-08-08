# Sentiment Analysis — Error Analysis

**Status: qualitative/exploratory, not statistically meaningful.** Based on
14 hand-written examples (`backend/scripts/qualitative_eval_sentiment.py`),
each labelled with the *author's own* judgment of intended sentiment — not
third-party annotated, no inter-rater agreement measured. This surfaces
failure *patterns* worth documenting, not a trustworthy accuracy number (see
Gate 20's own instruction: this is qualitative/exploratory evaluation, never
to be conflated with ground truth). Separate from, and not blended into,
`data_audit_sentiment.md`'s dataset-level analysis.

**Result: 5/14 (36%) matched the author's intended label**, run through the
exact same path `SentimentService` uses in production (`EmailPreprocessor`
with `SENTIMENT_CONFIG`, then `VaderSentimentPredictor`).

## Per-example results

| Category | Predicted | Intended | Match | Error class |
|---|---|---|---|---|
| Positive email | Positive | Positive | ✅ | — |
| Negative email | Negative | Negative | ✅ | — |
| Neutral email | Positive | Neutral | ❌ | MODEL ERROR |
| Polite complaint | Positive | Negative | ❌ | MODEL ERROR |
| Indirect complaint | Neutral | Negative | ❌ | MODEL ERROR |
| Mixed sentiment | Negative | Negative | ✅ | — |
| Short email (positive) | Very Positive | Positive | ❌ | AMBIGUITY |
| Short email (negative) | Negative | Negative | ✅ | — |
| Long email (measured, professional) | Very Positive | Neutral | ❌ | MODEL ERROR |
| Forwarded thread | Positive | Neutral | ❌ | MODEL ERROR |
| Business email (escalation) | Positive | Negative | ❌ | MODEL ERROR |
| Customer-support email (satisfied) | Very Positive | Very Positive | ✅ | — |
| Sarcasm | Very Positive | Very Negative | ❌ | MODEL ERROR (structural, expected) |
| Very negative, explicit escalation | Negative | Very Negative | ❌ | AMBIGUITY |

## Error categories, with cause

**MODEL ERROR — lexicon scorers cannot see intent, only words (7/9 misses,
the dominant pattern):**
- *Politeness ≠ sentiment* (Polite complaint, Neutral email): VADER scores
  courteous phrasing ("please," "appreciate," "find attached") as mildly
  positive regardless of the substantive complaint underneath — exactly the
  borderline case `annotation_guidelines_sentiment.md` §1 calls out in
  advance as something a lexicon approach cannot handle, not a surprise
  found after the fact.
- *Indirect/implicit negativity* (Indirect complaint, Business escalation):
  "I noticed the report was submitted a bit later than usual again" and
  "Per our SLA, this ticket should have been resolved within 24 hours"
  contain no lexically negative words at all — the negativity is pragmatic
  (violated expectation, implied consequence), which a word-lookup scorer
  structurally cannot access.
- *Length saturation* (Long professional email, Forwarded thread): VADER's
  compound score aggregates per-sentence valence without length
  normalization tuned for paragraph-length text — it was designed for
  short social-media posts. This matches the dataset generator's own
  finding (`data_audit_sentiment.md` §2 / `run_metadata.json`): 64.7% of
  10,000 real Enron emails bucketed "Very Positive," a implausibly skewed
  distribution for real business correspondence, and the same root cause.
- *Sarcasm* ("Oh great, ANOTHER outage... Really loving this service."):
  predicted Very Positive against an intended Very Negative — the single
  most severe miss in this set, and a well-known, structural limitation of
  lexicon-based scoring disclosed in advance (`data_audit_sentiment.md`),
  not discovered as a surprise.

**AMBIGUITY — adjacent-class boundary misses, not clear failures (2/9):**
- "Short email (positive)" (Very Positive vs. intended Positive) and "Very
  negative, explicit escalation" (Negative vs. intended Very Negative) both
  land one bucket away from the author's intent on an ordinal 5-class
  scale. This is evidence the `±0.6` "Very" threshold
  (`data_audit_sentiment.md` §3) is an approximate, disclosed heuristic,
  not a validated boundary — real annotation would very plausibly draw
  these lines differently.

## A real, fixed bug this evaluation caught

Running this eval originally exposed that `SENTIMENT_CONFIG`
(`app/preprocessing/email_preprocessor.py`) inherited
`PreprocessingConfig`'s `lowercase=True` default. VADER's lexicon explicitly
scores capitalized sentiment words more intensely than lowercase ones
("GREAT" > "great") — lowercasing before scoring was silently discarding a
signal VADER is designed to use. Fixed by setting `lowercase=False` in
`SENTIMENT_CONFIG` (also added `min_token_length=1` for the same reason
`SUMMARY_CONFIG` needed it — VADER scores whole text, not a token bag, so
dropping short tokens ahead of scoring is actively harmful). This particular
14-example set happened not to contain a capitalized sentiment word, so its
before/after scores were nearly identical — the fix is correct in principle
(preserves a real VADER capability) but its practical impact is not
demonstrated by this evaluation set specifically.

## What this does and does not justify

**Does justify:** shipping VADER as a disclosed-PROVISIONAL default (§
`data_audit_sentiment.md`), since its failure modes are well-characterized
and match its known, documented limitations rather than behaving
unpredictably. **Does not justify:** any claim of accuracy on real email
sentiment — a 36% match rate on 14 author-labelled examples is evidence of
*failure patterns*, not a performance number, and must never be quoted as
one.
