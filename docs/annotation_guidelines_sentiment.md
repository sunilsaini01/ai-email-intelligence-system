# Sentiment Analysis — Annotation Guidelines & Human Annotation Strategy

**Status: forward-looking process document, not a record of completed
work.** No human annotation has happened for sentiment — this document
specifies what it would take, the same role
[`annotation_guidelines_categorization.md`](annotation_guidelines_categorization.md)
plays for categorization. See [`data_audit_sentiment.md`](data_audit_sentiment.md)
§4 for why this remains unstarted (out of scope for an engineering session,
not an oversight).

## 1. Class Definitions (canonical, FR-29's 5-class taxonomy)

**Operating question: "What is the emotional polarity and intensity of this
email's language toward its subject?"** Not urgency (Priority), not a
specific named emotion (FR-30, out of scope — see `data_audit_sentiment.md`
§1).

| Class | Definition | Positive examples | Explicit exclusions |
|---|---|---|---|
| **Very Negative** | Strong, unambiguous negative affect — anger, severe dissatisfaction, explicit threat to the relationship (e.g., "canceling," "escalating to legal," "worst experience"). | "This is the third time you've failed to fix this. I am cancelling my contract and escalating to legal." | A factual bad-news email with no emotional language (e.g., a routine outage notice) is not Very Negative merely because its *content* is bad — sentiment measures the writer's expressed affect, not the news itself. |
| **Negative** | Clear dissatisfaction or frustration, without the intensity markers above. | "I'm disappointed this hasn't been resolved yet. Please look into it soon." | A polite request for correction ("could you please double check this") without dissatisfaction language is Neutral, not Negative — see borderline rules below. |
| **Neutral** | Informational, transactional, or mixed-with-no-clear-lean content. | Status updates, scheduling emails, factual questions, most routine business correspondence. | The default bucket — most legitimate business email is Neutral, same asymmetric-cost reasoning Priority's guidelines already apply to its own default class. |
| **Positive** | Clear satisfaction, appreciation, or agreement. | "Thanks, this worked perfectly." "Happy to confirm the meeting." | Polite closing conventions alone ("Best regards," "Thank you for your time") do not make an otherwise-neutral or negative email Positive — sentiment must come from substantive content, not sign-off boilerplate. |
| **Very Positive** | Strong, unambiguous positive affect — enthusiasm, explicit praise, gratitude beyond routine politeness. | "This is exactly what we needed, the team is thrilled — thank you so much for the fast turnaround!" | — |

**Borderline rules (the part a lexicon score cannot apply, and the reason
real annotation would add value beyond VADER):**
- **Politeness ≠ sentiment.** A "polite complaint" ("I would really appreciate
  it if this could be looked into") is Negative in substance despite
  surface-level courteous phrasing — VADER's lexicon approach is known to
  under-weight this pattern (see `docs/error_analysis_sentiment.md`).
- **Sarcasm and irony** flip literal polarity; a lexicon scorer cannot detect
  this at all. Annotators must label the *intended* sentiment.
- **Mixed sentiment** (praise + complaint in one email) is labelled by the
  dominant/final expressed sentiment, with a `mixed: true` flag recorded
  separately rather than forcing a single dominant label to absorb the
  ambiguity silently.
- **Forwarded/quoted content** should not drive the label — only the
  forwarding sender's own added text expresses their sentiment; the
  quoted material's original sentiment is a different email's label.

## 2. Sampling Strategy

Stratify by (a) `is_reply`/`is_forward` (sentiment expression differs
meaningfully between an original message and a reply-chain), and (b) VADER's
own pre-computed bucket (from `sentiment_synthetic_v1`), oversampling VADER's
Negative/Very-Negative buckets specifically — those are rarer in ordinary
business correspondence and are exactly the buckets FR-31's priority-boost
logic (deferred, but the eventual reason this data matters) cares about most.

## 3. Dataset Size

Minimum **3,000 emails**, mirroring the PRD's general expectation for a
5-class task at Categorization's scale (37K docs / 8 classes ≈ 4.6K/class;
5-class sentiment at 3K ≈ 600/class, adequate for a classical TF-IDF baseline
per the same reasoning already applied to priority/category's 10K/4-class
target). Should be revisited once a real annotation budget is scoped — this
is a floor, not a validated target.

## 4. Number of Annotators

**3 independent annotators per email**, matching the PRD's priority/category
precedent (§8.2) and this document's own IAA requirement below (Fleiss'
Kappa needs ≥3 raters to be meaningful, not just Cohen's Kappa's 2).

## 5. Inter-Annotator Agreement

**Fleiss' Kappa** (not Cohen's — 3+ raters), computed per the standard
weighted scheme for ordinal categories (Very Negative through Very Positive
is an ordered scale, so a Negative/Neutral disagreement should count as
"closer" than a Very Negative/Very Positive disagreement — plain unweighted
Kappa would treat both the same, which misrepresents how close raters
actually were). **Target: Fleiss' Kappa ≥ 0.65** — set slightly below
priority/category's 0.70 bar because sentiment intensity ("Negative" vs.
"Very Negative") is inherently more subjective than priority/category's more
concrete decision criteria; 0.65 is still "substantial agreement" on the
standard Landis & Koch scale.

## 6. Disagreement Analysis & Adjudication

Disagreements are categorized (not just averaged away) into: intensity-only
(adjacent classes, e.g. Negative vs. Very Negative), polarity flip (opposite
sides of Neutral — a genuine, more serious disagreement), and sarcasm/mixed
flag disputes. A fourth, senior annotator adjudicates polarity-flip
disagreements specifically (the category that most threatens label
validity); intensity-only disagreements resolve to the median of the three
ratings on the ordinal scale.

## 7. Gold Dataset — Three-Way Split

Identical mechanism to priority/category: leakage-safe split by
`sender_email` (`GroupShuffleSplit`), train/val/test, no sender appearing in
more than one split — see `data_audit_sentiment.md` §5 for why this matters
even more for a synthetic bootstrap than for real annotation (real
annotation removes the label-leakage risk but sender-text leakage remains
regardless of label source).

## 8. Label Distribution (to be measured, not assumed)

Business email sentiment is expected to skew Neutral (most email is
transactional), with Negative more common than Positive in contexts where
people write to report problems rather than to praise — this expectation
should be checked against real annotation output, not assumed to hold, the
same discipline `data_audit_priority.md` applies to its own class-imbalance
numbers.

## 9. Label Quality Acceptance Criteria

A completed annotation batch is acceptable only if: Fleiss' Kappa ≥ 0.65
across the full batch, no single class falls below 5% of the labelled set
(a class with near-zero examples cannot be evaluated meaningfully regardless
of overall Kappa), and adjudicated disagreement rate is separately reported
(a batch can hit the Kappa bar while still having a concerning
polarity-flip rate that a single aggregate number would hide).
