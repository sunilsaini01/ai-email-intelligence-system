# Routing Conflict Resolution & Precedence (Module 8 / Phase 8)

Single source of truth for the logic: `backend/app/routing/rules.py`'s
`resolve_routing()`. This document explains the precedence order and the
reasoning behind it; `docs/routing_rules.md` documents each rule
individually.

## Precedence Hierarchy

```
1. Spam gate               (R-SPAM-GATE — pre-empts everything)
2. Category (department selection)
3. High-impact department review (HR / Legal / Billing)
4. Intent corroboration (Escalation / Refund — restricted, see below)
5. Priority (urgency modifier only)
6. Sentiment (urgency modifier only)
7. Sender domain (corroborating review-modifier only, narrowly scoped to HIGH_IMPACT departments — see "Sender Domain" below; never selects or overrides a department)
```

This order is a direct implementation of the Phase 8 brief's own suggested
factor list ("Critical business rules > explicit business evidence >
validated signals > provisional signals > weak model predictions > generic
keywords"), mapped onto this codebase's actual, disclosed evidence
hierarchy (`docs/routing_signal_reliability.md`): Spam is the one
*validated* signal and gates first; Category is the *primary* signal
because department taxonomy is literally its label space
(`docs/routing_taxonomy.md`); Intent/Priority/Sentiment are all
*provisional or unvalidated* and are deliberately restricted to modifying
— never selecting — the department; Keywords and sender domain are the
weakest, used only as a last-resort fallback or as informational context.

## Tie-Breaking

Two mechanisms, both deterministic (RULE 18 — routing must never resolve
ties randomly):

1. **Category top-2 tie** (`R-CATEGORY-TIE`): if the top two category
   confidences are within `CATEGORY_TIE_MARGIN` (0.05, HEURISTIC) of each
   other, the decision routes to human review with the top candidate shown
   — not silently picking whichever the classifier happened to rank first
   by floating-point tiebreak.
2. **Keyword vote tie** (`top_department_by_keywords()`,
   `app/routing/keyword_matcher.py`): when two or more departments have the
   same keyword-match count, the winner is the alphabetically-first
   department name — arbitrary but deterministic and reproducible, per
   RULE 18.

## Unreliable Intent Policy (Escalation & Refund)

The Phase 8 brief lists six candidate strategies (SS19): ignore, down-weight,
require corroboration, human-review-only, confidence threshold, temporary
exclusion. **Chosen: a combination of "require corroboration" (Strategy C)
and "allow only to trigger human review, never a department change"
(Strategy D)** — the safest combination given the specific, root-caused
failure modes documented in `docs/error_analysis_intent.md`:

### Escalation

- **Uncorroborated** (no supporting Priority=Critical/High or
  Sentiment=Negative/Very Negative): **completely ignored.** No rule fires,
  no effect on the decision at all. Justification: Escalation is
  demonstrated to fire on unrelated text (a contract request, an
  order-status question, a scheduling email) — treating a bare Escalation
  label as evidence of anything, even a soft nudge, would import that
  false-positive rate directly into routing.
- **Corroborated**: sets `requires_human_review=True` only
  (`R-ESCALATION-CORROBORATED`). Never changes the department. Rationale:
  even a noisy signal, when it agrees with two independent
  disclosed-provisional-but-differently-derived signals (Priority, from a
  different classifier and training run; Sentiment, from a zero-shot
  lexicon with no shared training data at all), is worth a human glance —
  but "worth a glance" is the ceiling, not "worth acting on automatically."

### Refund

- **F1 = 0.0 on its own test set** — the weakest single-class result of
  any classifier shipped in this project. Refund is never permitted to
  *select* a department under any circumstance.
- If the department is already `Billing` (chosen by Category): Refund is
  treated as *corroborating* evidence, purely for the explanation text
  (`R-REFUND-BILLING-CORROBORATED`) — it does not raise confidence
  numerically (no composite score exists to raise, see below) and Billing
  already mandates human review as a HIGH_IMPACT department regardless.
- If the department is anything else: `R-REFUND-CATEGORY-MISMATCH` sets
  `requires_human_review=True` and explicitly does **not** redirect the
  department to Billing — a financial-action intent with F1=0.0
  independently selecting a financial department would be the exact
  "confidently wrong routing" the Phase 8 brief's RULE 15 warns against.

### Why Not the Other Four Strategies

- **Down-weight** was rejected because it implies a numeric score to weight
  — this implementation deliberately has none (see below).
- **Confidence threshold** was rejected as insufficient on its own: Intent's
  own reported confidence for Escalation/Refund is not the problem (the
  classifier can be "confident" and still be measurably wrong, per
  `docs/error_analysis_intent.md`) — a confidence threshold would not have
  caught the false-positive-on-unrelated-text failure mode, which occurs
  at a range of confidence levels.
- **Temporary exclusion** (dropping the class from Intent's output
  entirely) was rejected because it would silently discard information the
  PRD (FR-33) requires the system to surface — corroboration-gating keeps
  the signal visible in `supporting_signals` while controlling its
  routing *effect*, which is more transparent than deletion.

## No Composite RoutingScore

The Phase 8 brief's SS13/SS28 raise, as an optional design, a formula:
`RoutingTrust = ModelConfidence × DataReliability × DomainValidity`, and
explicitly say it "does not necessarily need to be implemented literally."
**It is not implemented literally here.** `RoutingPredictionResponse.
confidence` is:

- the Category model's own reported confidence, when Category selected the
  department (`R-CATEGORY-AUTO-ROUTE` / `R-CATEGORY-LOW-CONFIDENCE` /
  `R-CATEGORY-TIE`);
- a HEURISTIC keyword-vote share (`votes[winner] / total_votes`), clearly
  labelled as such, when Category was unavailable
  (`R-CATEGORY-UNAVAILABLE-KEYWORD-FALLBACK`);
- the Spam model's `spam_score` (the spam-class probability), for
  quarantine — **not** `SpamService`'s `confidence` field, which is the
  argmax-label confidence and is routinely the *ham*-label confidence for
  threshold-driven quarantines (fixed during the Phase 8 engineering
  review: `confidence`/`spam_score` had been swapped, silently reporting
  e.g. 0.81 "confidence" for a decision actually driven by a 0.19 spam
  probability — see `tests/test_routing_service.py::
  test_route_quarantine_confidence_uses_spam_score_not_argmax_confidence`);
- `0.0` for the no-evidence fallback.

No step multiplies these by an invented "data reliability" weight (RULE 14
— never call a heuristic weight "learned"; the surest way to avoid
mislabeling one is not inventing a blended number that has no natural units
in the first place). Instead, data-reliability judgments are expressed as
discrete rule effects — gating, downgrading to human review, requiring
corroboration — which is auditable per-rule (`matched_rules`) in a way a
single blended float would not be.

## Sender Domain

FR-38 names sender domain as one of the five signals routing "shall use."
The initial implementation computed `sender_domain_type` and attached it to
`RoutingSignals`, but `resolve_routing()` never read it — a real gap found
during the Phase 8 engineering review, not merely a documentation
oversight (`supporting_signals.sender_domain` was populated and returned,
giving the appearance of use without any actual effect).

**Fix, deliberately narrow**: `R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW` fires
when `sender_domain_type == "external"` **and** the chosen department is
HIGH_IMPACT (HR/Legal/Billing). It:

- **Never selects or overrides a department** — the condition only reads
  `department` after it has already been chosen by Category (or the
  keyword/no-evidence fallback); it never appears on the assignment side.
- **Cannot change `requires_human_review` from `False` to `True` in
  practice** — HIGH_IMPACT departments already unconditionally require
  review via `R-HIGH-IMPACT-DEPARTMENT-REVIEW`. Its purpose is
  explainability: naming "external sender + high-impact department" as an
  explicit, separately-auditable contributing reason, not causing a
  decision that wouldn't otherwise happen.
- **Deliberately excludes non-HIGH_IMPACT departments.** Most legitimate
  senders to Support, Sales, Marketing, and IT are external by nature
  (customers, leads, press) — treating "external" as caution-worthy there
  would flag ordinary traffic, not anomalies. Scoping to HR/Legal/Billing
  targets the cases where an external party discussing HR or Legal matters,
  or a person requesting a billing action from outside, is a genuinely
  more notable pattern than "the sender is not obviously staff" is on its
  own.
- **Deliberately excludes `freemail`.** A freemail sender (gmail.com etc.)
  contacting a HIGH_IMPACT department is arguably at least as
  noteworthy as a corporate-external one — treated as a candidate future
  refinement, not implemented here, to keep this fix minimal and matched
  exactly to what was approved.

## `action` vs. `requires_human_review` — Two Independent Fields

A recurring pattern worth calling out explicitly: several rules (
`R-HIGH-IMPACT-DEPARTMENT-REVIEW`, `R-CRITICAL-PRIORITY-CONFIDENCE-CHECK`,
`R-BORDERLINE-CONFIDENCE-NEGATIVE-SENTIMENT`, `R-ESCALATION-CORROBORATED`)
set `requires_human_review=True` **without** changing `action` away from
`auto_route`. This is deliberate: `action` is the system's routing
*suggestion* (what department the evidence points to); `requires_human_
review` is an orthogonal flag meaning "a human must confirm before this is
acted on unattended." A caller integrating this API should treat
`requires_human_review=True` as binding regardless of `action` — the
suggestion is still useful context for the reviewer, not discarded.
