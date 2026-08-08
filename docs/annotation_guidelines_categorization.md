# Email Categorization — Annotation Guidelines & Human Annotation Strategy

**Status: this is a specification for the annotation effort that has NOT yet
happened** (Option A of `docs/data_audit_categorization.md` §4). Nothing in
this document should be read as describing completed work — it exists so
that if/when annotation budget is approved, the process starts here instead
of from a blank page. See `docs/categorization_label_quality_report.md` for
what currently exists in its place (a synthetic dataset, explicitly not a
substitute for this).

## 1. Category Definitions (canonical — supersedes any shorter restatement elsewhere)

For each of the 8 FR-21 categories: business meaning, inclusion criteria,
exclusion criteria, and worked examples. This is the annotator-facing
expansion of `docs/data_audit_categorization.md` §3 — that document is the
source of truth for the taxonomy's *design rationale*; this section is the
operational reference an annotator has open while labeling.

### CATEGORY: Support

**Business meaning:** Customer-facing issue resolution — an external party
needs help with a product/service they already have.

**Include:**
- Bug reports, "it doesn't work" reports
- How-do-I-use-this questions from existing customers
- Account access problems reported by a customer
- Service degradation complaints from a customer

**Exclude:**
- An employee's own IT problem → **IT**, not Support (internal vs. external
  party is the deciding signal, not the technical nature of the problem)
- A billing/payment complaint with no technical component → **Billing**
- A product bug report that also demands a refund → **Support + Billing**
  (multi-label; the bug is Support, the refund ask is Billing)

**Positive example:** *"Hi, I can't log into my account since yesterday, it
just spins on the loading screen. Can you help?"*

**Borderline example:** *"Your product crashed and now I want my money
back."* → **Support + Billing** (technical complaint + explicit refund
request — both are genuinely present, not a coin-flip between them).

### CATEGORY: Sales

**Business meaning:** Prospecting, deal-making, pricing inquiries aimed at
acquiring new business or expanding existing business.

**Include:**
- Pricing/quote requests from a prospect
- A partner or reseller proposing a deal
- An existing customer asking about upgrading their plan (net-new revenue)
- Demo requests

**Exclude:**
- An existing customer disputing their *current* charge → **Billing**, not
  Sales (servicing an existing relationship, not acquiring new business)
- A prospect's technical question about whether the product supports X →
  still **Sales** if the purpose is evaluating a purchase, not **Support**
  (Support is for people who already have the product)

**Positive example:** *"We're evaluating your platform for our 200-person
team, can someone send pricing for the Enterprise tier?"*

**Borderline example:** *"We're an existing customer on the Basic plan and
want to talk about moving to Enterprise."* → **Sales** (expansion revenue),
not Billing, even though it's about money — the intent is to buy more, not
to resolve a charge.

### CATEGORY: Billing

**Business meaning:** Invoices, payments, refunds, subscription charges,
billing disputes — servicing money already owed on an existing relationship.

**Include:**
- Invoice questions/requests
- Payment failure notices
- Refund requests
- Disputed charges
- Subscription cancellation *specifically for billing reasons* ("too
  expensive")

**Exclude:**
- Contract *terms* interpretation (as opposed to the resulting charge) →
  **Legal**
- Employee payroll issues → **HR**, not Billing (different party — Billing
  is customer-facing, HR is employee-facing, even though both are "money
  owed" in a loose sense)

**Positive example:** *"Invoice #4471 shows a charge for a service we
cancelled last month, please correct and refund."*

**Borderline example:** *"Please review the legal terms of the invoice
before payment."* → **Legal + Billing** (the canonical multi-label example
from `docs/data_audit_categorization.md` §3 — legal review of a specific
payment action; forcing one label here loses real information).

### CATEGORY: Legal

**Business meaning:** Contracts, compliance, regulatory matters, legal
notices, terms-of-service disputes.

**Include:**
- Contract drafts/redlines
- Compliance audit requests
- Cease-and-desist letters, subpoenas
- Data-processing-agreement / privacy-regulation questions
- Terms-of-service disputes

**Exclude:**
- An invoice that merely references "per your contract" in passing →
  **Billing** alone, unless the email is actually *about* the contract term
  itself
- HR policy questions (these follow employment law but are handled by HR,
  not routed to Legal in this taxonomy) → **HR**

**Positive example:** *"Attached is our proposed redline to Section 4.2 of
the MSA — please have Legal review before we sign."*

**Borderline example:** A vendor contract renewal notice with a price
increase → **Legal + Billing** if it discusses both the contract terms and
the resulting charge; **Legal** alone if it's purely about the terms.

### CATEGORY: HR

**Business meaning:** Employee-related communication — hiring, benefits,
payroll, performance, internal policy, workplace conduct.

**Include:**
- Benefits enrollment, PTO requests
- Offer letters, onboarding
- Performance review scheduling
- Workplace conduct complaints
- Employee payroll corrections

**Exclude:**
- A customer's billing question → **Billing**, never HR, regardless of
  surface similarity ("payment issue")
- An employee's IT access request → **IT**, not HR, even though HR often
  *initiates* IT provisioning during onboarding — route by subject matter
  (access/systems = IT), not by which department historically kicks off the
  process

**Positive example:** *"I'd like to enroll in the dental plan during open
enrollment, where do I submit the form?"*

**Borderline example:** *"New hire starts Monday, please set up their
laptop and email."* → **HR + IT** (HR is coordinating, but the actual ask is
IT provisioning) — multi-label, not a judgment call between the two.

### CATEGORY: IT

**Business meaning:** Internal technical/infrastructure issues, access
requests, system outages, hardware/software provisioning — the internal
analog of Support.

**Include:**
- VPN/system access requests
- Hardware/software provisioning
- Internal outage notices
- Password resets (internal accounts)

**Exclude:**
- A customer-reported product bug → **Support**, not IT — same technical
  subject matter, different party
- HR policy about *who* is eligible for a laptop → **HR**, not IT (that's a
  benefits/policy question, not a provisioning request)

**Positive example:** *"My laptop won't boot after last night's update,
need it fixed before my 10am meeting."*

**Borderline example:** *"Customer support team is reporting the ticketing
system is down for everyone."* → **IT** (the internal system outage is the
subject), even though it's *about* the Support team, because the ask is
internal infrastructure repair, not a customer-facing issue.

### CATEGORY: Marketing

**Business meaning:** Campaigns, newsletters, promotional content, brand/PR,
event planning — outbound-facing.

**Include:**
- Newsletter drafts for review
- Campaign performance reports
- Event sponsorship coordination
- Press/media inquiries
- Content/copy review requests

**Exclude:**
- A customer's reply to a promotional email asking a purchase question →
  **Sales** (or **Support**), not Marketing — Marketing is for content
  *about* outbound campaigns, not inbound replies to them
- Internal marketing-team payroll/HR matters → **HR**

**Positive example:** *"Can you review the subject line for next week's
product-launch newsletter before we send?"*

**Borderline example:** A journalist emailing about a product review →
**Marketing** (PR/brand angle), unless they're specifically asking for a
demo account to review, in which case **Marketing + Sales**.

### CATEGORY: General

**Business meaning:** Genuine fallback — no clear departmental owner, or
purely administrative/social content.

**Include:**
- Building/facilities notices
- All-hands meeting reminders
- Social/small-talk ("Happy Friday!")
- Anything genuinely reviewed against all 7 other categories and rejected

**Exclude:**
- Anything that fits one of the 7 categories above, even weakly — General
  is not a "didn't read carefully enough" bucket. An annotator should be
  able to explain *why* none of the other 7 apply, not just default here
  when unsure (see §8 disagreement analysis — "defaulted to General without
  checking" is itself a labelled failure mode to watch for).

**Positive example:** *"Reminder: the elevator will be out of service
Thursday 9am-12pm."*

## 2. Multi-Label vs. Multi-Class — Binding Decision

**Multi-label.** Established in `docs/data_audit_categorization.md` §7 per
PRD §9.1 and FR-22 directly — not re-litigated here. Practical consequence
for annotation: **every email gets independent yes/no judgments against all
8 categories**, not a single forced pick. An annotator should actively check
each of the 8 before submitting, not stop at the first plausible match.

## 3. Sampling Strategy

Random sampling alone under-represents rare categories (Legal, HR are
expected to be a small fraction of raw email volume) and over-represents
easy, obviously-worded examples. Sampling must ensure coverage across:

- **Senders** — no single sender/domain dominates the sample (mirrors the
  sender-diversity concern already driving the leakage-safe split design,
  `docs/data_audit_categorization.md` §6)
- **Email length** — short (<50 words) and long (>500 words) emails both
  represented; short emails are disproportionately ambiguous (§1's "General"
  borderline note) and need deliberate coverage, not accidental inclusion
- **Time period** — if annotating real organizational email, span multiple
  months/quarters to avoid overfitting to one period's vocabulary
  (campaign-specific Marketing terms, a single quarter's Legal matter, etc.)
- **Business context** — deliberately oversample from categories expected
  to be rare (Legal, HR) via keyword pre-filtering *for sampling only, never
  for labeling* — i.e., a keyword search can help find candidate Legal
  emails to include in the annotation pool, but the keyword match itself
  must never be used as the label (that would just be a differently-shaped
  version of the synthetic heuristic this whole effort exists to replace)
- **Difficult/ambiguous emails** — deliberately include multi-topic and
  short-reply emails, not just clear-cut cases; a dataset that's 100% easy
  examples produces a model that looks good and fails immediately in
  production

## 4. Dataset Size

**PRD does not specify a minimum for categorization** (§8.2 only specifies
sizes for Priority — 10,000+ — and Intent — 5,000+; Categorization has no
equivalent line item). Per this phase's instruction to recommend a
defensible target when the PRD is silent, not invent one arbitrarily:

**Recommended target: 8,000 emails minimum for the full gold dataset**,
justified as follows:
- **8 categories, multi-label** → more independent judgments per email than
  Priority's 4-way single-label (8 yes/no decisions vs. 1 four-way pick),
  so per-category *effective* sample size needs similar volume to Priority's
  10,000-row target even though headline row count can be somewhat lower —
  8,000 rows × up to 8 label judgments each yields comparable annotation
  effort and per-category statistical power to Priority's 10,000 × 1.
- **Rarest expected category** (Legal, by analogy to typical enterprise
  email volume patterns) needs at minimum ~300-500 positive examples to
  train a usable binary classifier within the One-vs-Rest architecture
  (§7) — at an estimated 3-5% natural Legal prevalence, 8,000 emails yields
  roughly 240-400 naturally, which is why §3's deliberate oversampling for
  rare categories matters: without it, 8,000 random emails likely
  under-shoots even this floor.
- **Test set specifically** needs enough per-category positives that a
  per-label F1 score isn't dominated by single-digit sample noise — the
  same statistical-power problem `docs/model_cards/priority_classification.md`
  "Class Imbalance" documents for Priority's 11-example Critical test slice
  applies here per rare category, and is the reason for the oversampling
  strategy in §3.
- **This is an engineering recommendation, not a PRD requirement** — stated
  explicitly, per this phase's instruction not to present a chosen number as
  if the PRD mandated it.

## 5. Number of Annotators

**3 independent annotators**, following this phase's stated starting
recommendation and consistent with the PRD's own §8.2 requirement for
Priority (which does specify 3). No taxonomy-specific reason was found to
deviate from 3 upward or downward:
- Category definitions (§1) are moderately complex (8 categories, several
  documented near-miss pairs) — comparable complexity to Priority's 4-level
  taxonomy, which the PRD sets at 3.
- Budget/ambiguity tradeoff: fewer than 3 loses the ability to measure
  agreement meaningfully at all (2 annotators only supports pairwise Cohen's
  Kappa, no majority vote possible on disagreement); more than 3 raises cost
  proportionally without a specific driver here (unlike, say, a
  safety-critical single-annotator-error-intolerant task, which this isn't).

## 6. Annotation Interface / Format

```json
{
    "email_id": "EMAIL_00147",
    "categories": ["Legal", "Billing"],
    "annotator_id": "A02",
    "confidence": "medium",
    "notes": "Invoice dispute that explicitly requests legal review of contract terms before payment — both labels genuinely apply, not a coin flip."
}
```

- `categories`: list, not a single string — enforces the multi-label
  decision (§2) at the data-entry level, not just in downstream code.
- `confidence`: annotator's own self-reported certainty (`high`/`medium`/
  `low`), used in §9 disagreement analysis to distinguish "annotator was
  unsure and got it wrong" from "annotator was confident and still
  disagreed with peers" — these indicate different failure modes (personal
  uncertainty vs. genuine taxonomy ambiguity).
- `notes`: free text, optional but strongly encouraged on any non-obvious
  call — this is what feeds §9's ambiguity taxonomy and §10's guideline
  revisions.
- **Do not store additional sensitive email content in the annotation
  record beyond `email_id`** — the annotation tool references the source
  email by ID; PII/full body text stays in the source system, not
  duplicated into annotation metadata, per this phase's explicit
  instruction and consistent with `app/security/pii_anonymizer.py`'s
  existence elsewhere in this codebase (not yet wired into any module, but
  the general principle — don't duplicate sensitive content into a new
  store without a reason — applies here regardless).

**Tooling: Label Studio** (self-hosted, open source) — per PRD §8.2's own
choice for Priority annotation; reused here rather than introducing a
second tool for no taxonomy-specific reason. Label Studio supports
multi-label text classification natively.

## 7. Independent Annotation

All 3 annotators label the same evaluation subset independently, with no
visibility into peers' decisions until after submission — enforced by
Label Studio's task-assignment model (each annotator sees only their own
queue). This is required for §8's agreement measurement to mean anything;
annotators who can see each other's labels don't produce an independent
signal, they produce an anchored one.

## 8. Inter-Annotator Agreement

**Why not raw percentage agreement:** for a multi-label task with an
expected-imbalanced category like Legal (§4: ~3-5% prevalence), two
annotators who both mark "not Legal" on 95% of emails without really
looking would show 95% raw agreement while having learned nothing about
whether they agree on the cases that matter. This is the identical
reasoning `docs/data_audit_priority.md` and the priority model card already
apply to F1-vs-accuracy — restated here for agreement measurement
specifically, per this phase's requirement to explain why percentage
agreement alone is inappropriate.

**Method: per-category Cohen's Kappa (3 annotators → computed pairwise
and averaged), not a single combined multi-label statistic.** Each of the 8
categories is scored as its own independent binary annotation task (present
/ absent), because that's how the labeling decision is actually made (§1 —
8 separate yes/no judgments per email) and how the model is actually
architected (§7 — One-vs-Rest, 8 independent binary classifiers). A single
blended "multi-label Kappa" would average across categories with very
different base rates and obscure exactly the rare-category agreement
problems (Legal, HR) that matter most to catch early. For 3-annotator
agreement specifically within each per-category binary judgment, Fleiss'
Kappa is the correct generalization of Cohen's Kappa (which is 2-annotator
only) — used per category, then reported as a table of 8 Kappa values, not
one number.

**Acceptance threshold: Kappa ≥ 0.70 per category**, as an **engineering
recommendation**, not an existing PRD requirement (the PRD sets this
threshold for Priority specifically, §8.2; it is adopted here by analogy
because it's a defensible standard "substantial agreement" bar in
annotation literature generally, not because the PRD mandates it for
Categorization). Categories that don't clear 0.70 after the guideline
refinement in §9-10 should be flagged as taxonomy problems, not pushed
through with a lower bar.

## 9. Disagreement Analysis

When annotators disagree, the majority label is **not** taken automatically
— disagreement is first classified into an ambiguity taxonomy, because the
*reason* for disagreement determines whether the guideline needs fixing or
the email is genuinely multi-label and the "disagreement" is actually every
annotator being partially right:

| Disagreement cause | Signature | Resolution |
|---|---|---|
| Unclear category definition | Same disagreement pattern repeats across many unrelated emails | Revise §1's definition, re-annotate affected examples |
| Overlapping categories | Annotators picked different-but-adjacent categories from a documented near-miss pair (e.g. Support vs. IT, Sales vs. Billing) | Check whether it's genuinely multi-label (both apply) before treating as an error at all |
| Insufficient context | Annotator notes indicate missing thread history or unclear sender relationship | Needs thread-level context, not a guideline fix — flag for tooling improvement (thread grouping isn't implemented yet, `docs/data_audit_categorization.md` §3) |
| Genuinely ambiguous email | Short, low-information email (e.g. "Thanks, will do") with no clear category signal at all | Apply §1's General-fallback rule explicitly, document as inherently low-agreement, don't force guideline changes to chase an unfixable case |
| Annotator misunderstanding | One annotator's notes show a clear misreading of the guideline itself (not the email) | Annotator retraining, not a guideline change |

This ambiguity taxonomy is itself a deliverable of the annotation pilot —
it should be revised as real disagreement patterns are observed, not
treated as fixed in advance.

## 10. Adjudication

1. Identify all disagreements (any category where the 3 annotators don't
   unanimously agree on present/absent).
2. Classify each via the §9 taxonomy.
3. For "unclear definition" and "overlapping categories" causes: revise §1
   before proceeding further, then re-annotate the affected examples with
   the clarified guideline (not just adjudicate the old answers under a
   rule that didn't exist when they were given).
4. For remaining disagreements: a fourth reviewer (lead annotator or ML
   engineer familiar with the taxonomy) makes the final call, with the
   specific reason recorded per email (not just "majority wins").
5. The adjudicated result becomes that email's gold label.
6. Guideline changes triggered by this process get a version bump (§11) —
   the guideline is a living document during the pilot phase, frozen once
   the full annotation run begins (mid-annotation guideline changes make
   earlier and later annotations incomparable).

**Test-set adjudication leakage rule:** adjudication discussion for
test-set emails must happen only after all 3 annotators have independently
submitted — never adjudicate-as-you-go on the test set, which would let
adjudicator judgment leak into what's supposed to be an independently
double/triple-checked gold set.

## 11. Gold Dataset — Three-Way Split

- **Training data**: majority-vote or single-annotator-pass acceptable
  (lower per-item cost, higher volume need) — used to train models, not to
  evaluate them.
- **Validation data**: same annotation rigor as training; used for model
  selection/tuning only, never for final reported metrics.
- **Test data**: full 3-annotator + adjudication process (§7-10), human
  reviewed, **fixed after finalization** — no further edits once training
  begins, so that a metric measured against it means the same thing every
  time it's re-measured. This mirrors `docs/data_audit_priority.md` §6's
  leakage-safe test-set discipline, extended to labeling process rigor as
  well as split mechanics.

## 12. Label Distribution (to be measured, not assumed)

Once annotated, compute and report:
- Count and % prevalence per category (out of 8)
- Minority class size and identity (expected Legal or HR, per §4's
  reasoning, but this must be *measured*, not assumed to match the
  synthetic dataset's distribution — the synthetic generator's own
  distribution, per `docs/categorization_label_quality_report.md`, is a
  heuristic artifact, not a forecast of real distribution)
- Average labels per email (multi-label — expect > 1.0; a value close to
  1.0 would suggest either a genuinely mostly-single-topic corpus or
  under-application of the multi-label instruction and is worth
  investigating either way)
- Imbalance ratio (largest category ÷ smallest)

**If severe imbalance exists:** per this phase's explicit instruction, do
not reach immediately for oversampling. First determine whether it reflects
real business distribution (if General really is 40% of real inbound email,
that's a fact about the business, not a data problem) — only then evaluate
class weights (§7's One-vs-Rest per-classifier weighting, same mechanism
already used for Priority), threshold adjustment per label, stratified
sampling for any *re*-annotation round, or targeted additional annotation
specifically for the underrepresented category.

## 13. Label Quality Acceptance Criteria

Before any model is described as trained on this gold data:

- [ ] Category definitions approved (§1)
- [ ] Annotation guidelines finalized (this document, version-locked)
- [ ] Required annotation sample completed (§4 target, or a documented,
      justified deviation)
- [ ] 3 independent annotators used for validation/test data (§5, §7)
- [ ] Inter-annotator agreement measured per category (§8)
- [ ] Agreement meets the Kappa ≥ 0.70 target per category, or every
      shortfall is explained (§9) rather than silently accepted
- [ ] Adjudication completed for all disagreements (§10)
- [ ] No unresolved critical label conflicts remain
- [ ] Class distribution reviewed and, if imbalanced, the cause determined
      (§12)
- [ ] Test set finalized and frozen (§11)
- [ ] Dataset version created (`docs/categorization_label_quality_report.md`,
      versioned per `docs/data_audit_categorization.md`'s pattern)

**None of these are checked today.** This document is the specification
for doing so, not a record of having done so — see
`docs/categorization_label_quality_report.md` for the current, honest
status (Case C: no trustworthy data exists).
