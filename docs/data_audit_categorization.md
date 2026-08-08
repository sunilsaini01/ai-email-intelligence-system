# Email Categorization — Data Audit, Taxonomy, and Data Strategy Decision

**Status: gates all of Phase 5.** Nothing in `docs/model_cards/email_categorization.md`
or `docs/architecture_email_categorization.md` should be read as PRD-compliant
until the "Data Strategy Decision" section below is resolved by real annotation
(§4 Option A) — see that section for exactly what changes when it is.

This document follows the same structure as `docs/data_audit_priority.md`
(Phase 4's equivalent audit) because Phase 5 hits the identical shape of
problem: a PRD-named dataset that doesn't hold up under inspection, and a
taxonomy that needs an explicit, defensible data strategy before any model
number gets reported.

## 1. PRD Requirements (FR-21 to FR-24)

| ID | Requirement (verbatim, PRD §5 Module 4) |
|---|---|
| FR-21 | System shall assign category labels: Support / Sales / Billing / Legal / HR / IT / Marketing / General |
| FR-22 | System shall support multi-label assignment (one email may belong to multiple categories) |
| FR-23 | Category taxonomy shall be configurable per organization via admin UI |
| FR-24 | System shall return a confidence score for each assigned category |

**Not required by the PRD, but load-bearing for §4's decision below:** PRD
§14.1 names Email Categorization's evaluation as **F1-micro + Hamming Loss**
(secondary: Precision@K, Coverage Error), business threshold **F1-micro >
0.80**. PRD §9.1 names the baseline architecture as **TF-IDF + One-vs-Rest
Logistic Regression**, production target **fine-tuned BERT**, task type
**Multi-label Classification** — this is a direct, explicit instruction to
build a multi-label system, not an 8-way multi-class one; see §7 for why that
distinction is architecturally load-bearing, not cosmetic.

**FR-23 (per-org configurable taxonomy) is out of scope for this phase**, for
the same reason Phase 1 deferred real authentication: there is no multi-tenant
organization concept anywhere in this codebase yet (no `organizations` table,
no admin UI, no per-tenant config store). Building configurability for a
concept that doesn't exist yet would be speculative infrastructure ahead of
evidence it's needed — the taxonomy is hard-coded to the 8 FR-21 labels for
now, and FR-23 is carried forward as a documented, explicit gap (see
`docs/architecture_email_categorization.md` "Known Gaps"), not silently
dropped.

## 2. Data Audit — what actually exists today

### 2.1 The PRD's named dataset does not exist in this repository, and would not be usable if it did

PRD §8.1 names the categorization training dataset as **"TREC 2006/2007
Email, ~37,000 docs, TREC, Research license."** Two independent problems
with this, checked directly rather than assumed:

1. **It is not present anywhere in this repo.** `Glob` for `trec*` /
   `*trec*` across the entire project returns zero matches. `data/raw/`
   contains only `spamassassin/`, `enron/`, `sms_spam/`. No download, no
   loader, no reference to TREC in `app/data_ingestion/dataset_registry.py`.
2. **Even if it were downloaded, it would not answer this requirement.**
   "TREC 2006/2007" is the standard shorthand for the **TREC Public Spam
   Corpora** (TREC Spam Track, 2006 and 2007 editions) — a spam/ham binary
   classification benchmark, not a business-category-labelled email dataset.
   It carries no Support/Sales/Billing/Legal/HR/IT/Marketing/General
   taxonomy, or anything resembling one. This is stated as a direct,
   checkable fact about that corpus's actual contents, not an assumption —
   the same corpus family is why the PRD's own Module 2 (Spam Detection)
   dataset table already lists TREC-adjacent spam corpora (SpamAssassin)
   under *that* module.

**Conclusion: the PRD's data-requirements table entry for Categorization is
inapplicable as written.** Best read as a documentation carry-over error (a
spam corpus name landing in the categorization row) rather than a deliberate
data source — flagged here explicitly per this phase's "FACT vs ASSUMPTION"
discipline, not silently substituted with something else.

### 2.2 Checking the one real candidate already in the repo: Enron's `X-Folder` header

`app/data_ingestion/enron_loader.py` already extracts an `X-Folder` field
(`msg.get("X-Folder", "")`) from every Enron message — an Outlook/Lotus Notes
mailbox folder path each employee filed that message under. This is the only
existing signal in the repo that could plausibly serve as category weak
supervision, so it was checked directly rather than assumed useful or
assumed useless:

```
python -c "... sample 5,000 Enron messages, tally X-Folder values ..."

464  \John_Arnold_Jun2001\Notes Folders\All documents
420  \John_Arnold_Jun2001\Notes Folders\'sent mail
353  \Phillip_Allen_Dec2000\Notes Folders\All documents
310  \PALLEN (Non-Privileged)\Allen, Phillip K.\Sent Items
296  \PALLEN (Non-Privileged)\Allen, Phillip K.\Deleted Items
 47  \PALLEN (Non-Privileged)\Allen, Phillip K.\Inbox
 40  \Phillip_Allen_Dec2000\Notes Folders\Notes inbox
 16  \John_Arnold_Nov2001\Notes Folders\Bmc
 13  \John_Arnold_Nov2001\Notes Folders\Compaq
 12  \John_Arnold_Nov2001\Notes Folders\Continental airlines
  2  \John_Arnold_Nov2001\Notes Folders\Corestaff
  ...(38 unique values in a 5,000-message sample)
```

**Finding: `X-Folder` is personal mailbox organization (Sent Items, Deleted
Items, Inbox, "All documents"), or a counterparty/topic name specific to one
employee's filing habits (a vendor like "Compaq," an airline, a person's
name) — not a business-department taxonomy.** None of the 38 observed values
map to Support, Sales, Billing, Legal, HR, IT, or Marketing. This is already
independently flagged in `app/data_ingestion/dataset_registry.py`'s existing
`enron` entry (`"X-Folder labels are noisy weak supervision, not ground
truth"`) — this audit confirms that flag with direct evidence and goes
further: for *this specific* 8-category taxonomy, `X-Folder` isn't just
noisy, it's off-taxonomy. Using it would mean silently relabeling one
person's mail-filing habits as if they were FR-21's business categories,
which is worse than admitting no data exists (the same reasoning
`docs/data_audit_priority.md` §4 already applied to rejecting a public proxy
dataset).

### 2.3 Full data-source inventory check

| Check | Finding |
|---|---|
| `docs/annotation_guidelines_categorization.md` (this phase) | Written as part of this phase — see §5. Contains definitions and process, zero labelled emails (guideline documents were never meant to contain data). |
| `data/processed/*` | No categorization-labelled parquet exists anywhere. `priority_synthetic_v1` is priority-only; no `category_*` directory exists yet. |
| `app/data_ingestion/dataset_registry.py` | Zero registered datasets carry `email_categorization` as a *trustworthy* task tag before this phase. (The pre-existing `enron` entry lists `"email_categorization"` in its `tasks` list — read in context, that reflects "Enron's raw text is domain-relevant training *material* for categorization," not "Enron carries category ground truth." This audit is the point where that distinction gets made explicit, since the registry field alone doesn't carry it.) |
| `data/raw/custom/` | Same 0-byte placeholder noted in `docs/data_audit_priority.md` §2 — never populated for any module. |
| SpamAssassin / SMS Spam / Amazon Polarity / CNN-DailyMail | Checked against the taxonomy: none carry a Support/Sales/Billing/Legal/HR/IT/Marketing/General field or anything mappable to one — all are single-task datasets for other modules. |

**Finding: zero trustworthy category-labelled emails exist in this
repository, and the one candidate weak-supervision signal in the codebase
(`X-Folder`) does not match this taxonomy on inspection.** This is the same
class of finding as `docs/data_audit_priority.md` §2 ("zero priority-labelled
emails exist"), reached independently and reached the same way: by checking,
not assuming.

### Data Readiness Report

| Dataset | Rows | Labels | Class Distribution | Missingness | Duplicates | Temporal Coverage | Source | License | Quality | Suitability |
|---|---|---|---|---|---|---|---|---|---|---|
| Category-labelled (human) | **0** | N/A | N/A | N/A | N/A | N/A | None | N/A | N/A | **Not usable — does not exist** |
| TREC 2006/2007 (PRD-named) | **0 present in repo; ~0 usable if fetched** | N/A | N/A | N/A | N/A | N/A | Not downloaded | N/A | Wrong dataset for this task (spam corpus, not category-labelled) | **Not usable — PRD reference does not describe a categorization dataset** |
| Enron `X-Folder` (weak signal, checked) | ~500K available | 38+ raw folder strings, off-taxonomy | N/A (not FR-21 categories) | Present on most messages, absent on some | Not deduplicated for this use | 1999–2002 | CMU/Kaggle, `data/raw/enron/emails.csv` | Research use | Real corporate text; folder labels are personal filing habits, not department taxonomy | **Not usable even as weak supervision for this taxonomy — confirmed by direct sampling, §2.2** |
| Enron corpus (raw text only, ignoring `X-Folder`) | ~500K available, 1.4GB on disk | None (no category field) | N/A | Sparse `Date`/`To` on some messages | ~5-8% duplicate (registry-documented) | 1999–2002 | Same as above | Research use | Real enterprise text spanning legal, HR-adjacent, trading/sales, IT-support topics — thematically plausible for this task | Usable **only** as the text/metadata source for a synthetic bootstrap (§4), same role it plays for `priority_synthetic_v1` |
| **`category_synthetic_v1`** (this phase, generated) | 10,000 (see `run_metadata.json` for exact split sizes) | Support/Sales/Billing/Legal/HR/IT/Marketing/General, **heuristic-derived, multi-label** | See `run_metadata.json` — expected long-tailed, General as largest bucket (fallback default) | None (rows missing required fields dropped upstream) | Deduplicated on raw message body | 1999–2002 (inherited from Enron) | Derived from `enron`, `backend/scripts/generate_synthetic_category_dataset.py` | Research use (inherited) | Real text + real headers, **synthetic labels**, deliberately injected label noise, structural keyword leakage (see §4) | **Pipeline development only — see §4. Not usable for any PRD-compliance claim.** |

## 3. Label Taxonomy (FR-21)

Following the PRD's exact 8 labels — not the illustrative 6-category example
in this phase's own instructions (HR/Finance/IT/Sales/Support/Legal), which
was explicitly flagged there as an example, not a requirement. The PRD names
**Support, Sales, Billing, Legal, HR, IT, Marketing, General** — "Billing"
and "Finance" are related but not identical concepts (Billing is
transactional/operational; a hypothetical "Finance" category would be
broader, e.g. budget planning), and the PRD does not include a general
"Finance" label, so this document uses the PRD's own wording throughout.

**Operating question the label answers: "Which business function should
handle this email?"** Not "how urgent is it" (Priority, Module 3) and not
"how does the sender feel" (Sentiment, Module 6, not yet built) — a single
email can be both Billing and urgent, or Support and angry; those are
independent axes, and conflating them here would duplicate signal that
belongs to a different module.

| Category | Business meaning | Positive examples | Explicit exclusions |
|---|---|---|---|
| **Support** | Customer-facing issue resolution, technical or product assistance requests from an external party. | "My order hasn't arrived," "the app crashes when I click X," a customer asking how a feature works. | An *internal* employee's IT problem is IT, not Support (Support implies an external/customer relationship) — see IT below. |
| **Sales** | Prospecting, leads, deal/opportunity discussion, pricing inquiries from a prospective or existing customer about buying more. | "Can we get a quote for 50 seats," a prospect asking about enterprise pricing, a partner proposing a deal. | A question from an *existing* customer about their *current* bill is Billing, not Sales, even if it touches money — Sales is about acquiring/expanding business, Billing is about servicing an existing financial relationship. |
| **Billing** | Invoices, payments, refunds, billing disputes, subscription/plan charges. | "Invoice #12345 attached," a payment failure notice, a refund request, a dispute over a charge. | A question about contract *terms* (as opposed to the resulting charge) is Legal, not Billing — see the Finance+Legal multi-label example below. |
| **Legal** | Contracts, compliance, regulatory, legal notices, terms-of-service disputes, subpoenas. | A contract redline, a compliance audit request, a cease-and-desist, a data-processing-agreement question. | A routine invoice referencing "per your contract" in passing is Billing, not automatically Legal — Legal applies when the email is *about* the legal/contractual matter itself, not merely mentions a contract exists. |
| **HR** | Employee-related: hiring, benefits, payroll (employee-facing, not customer billing), performance, internal policy, workplace conduct. | A benefits enrollment question, an offer letter, a PTO request, a workplace complaint. | Payroll *processing* errors affecting an employee are HR; a *customer's* billing question is Billing — same underlying concept (money owed) but different party and different category. |
| **IT** | Internal technical/infrastructure issues, access requests, system outages, software/hardware provisioning — the *internal* analog of Support. | "I need VPN access," "my laptop won't boot," an internal outage notice, a password reset request. | A customer-reported product bug is Support, not IT, even though both are "technical" — the party (internal employee vs. external customer) is the distinguishing signal, not the subject matter. |
| **Marketing** | Campaigns, newsletters, promotional content, brand/PR, content requests, event planning (outbound-facing). | A newsletter draft for review, a campaign performance report, an event sponsorship request, a press inquiry. | A customer replying to a promotional newsletter with a purchase question is Sales (or Support), not Marketing — Marketing is for content *about* outbound campaigns, not inbound responses to them. |
| **General** | Fallback for email that doesn't clearly belong to any of the above, or is purely administrative/social with no departmental owner. | "Happy Friday!", an all-hands meeting reminder, a building-maintenance notice, small talk. | General is a genuine fallback, not a "didn't bother to read it" bucket — an email should only land here after the other seven are considered and rejected, mirroring `docs/data_audit_priority.md` §3's "Medium is the default bucket, prefer it when genuinely unsure" pattern, but for absence-of-signal rather than ambiguity. |

### Borderline, multi-label, and escalation rules

- **Multi-label is expected, not an edge case** (FR-22). The canonical
  example from this phase's own brief — *"Please review the legal terms of
  the invoice before payment"* — is genuinely **both Legal and Billing**: it
  requests legal review (Legal) of a specific invoice/payment action
  (Billing). Forcing a single label here would discard real information a
  downstream router needs.
- **A department-name mention alone does not imply that category.** "CC'ing
  Legal on this FYI" in an otherwise pure Billing email doesn't make the
  email Legal — the *content*, not an incidental name-drop, decides the
  label (same anti-keyword-worship principle as
  `docs/data_audit_priority.md` §3's "automated emails default to Low
  regardless of alarming subject lines").
- **A reply/forward inherits its thread's prior categories at minimum**,
  and may add new ones if the reply introduces a new concern (e.g., a
  Billing thread where someone replies "I'm also escalating this to
  Legal" becomes Billing + Legal from that point). Thread lineage isn't
  tracked end-to-end in this codebase yet (same gap noted in
  `docs/data_audit_priority.md` §3/§5) — stated for the human annotation
  process, not yet enforceable automatically.
- **Ambiguous/short emails** ("Thanks!", "Got it", "+1") default to
  inheriting the parent thread's category(ies) if known, else **General** —
  never guessed from a one-word reply alone.
- **Internal vs. external party is the single most useful disambiguator**
  for the Support/IT and Sales/Billing pairs specifically — annotators
  should check sender domain before content when those pairs are close
  calls.

## 4. Data Strategy Decision

| | **A — Custom annotation** | **B — Public/proxy dataset** | **C — Synthetic/heuristic bootstrap** |
|---|---|---|---|
| Validity vs. PRD | Only option that actually satisfies FR-21/22/24's underlying business need | Would not satisfy it — no public dataset shares this exact 8-label, multi-label business taxonomy | Does not satisfy it, and structurally cannot |
| Domain relevance | High, if sourced from real enterprise email | Low-to-medium — closest public analogues (e.g. helpdesk ticket categories, 20 Newsgroups) use different label spaces built for different purposes | Medium — real Enron email text, but the *label* is not real |
| Annotation quality | Controllable (guidelines + IAA gate, see §5) | N/A — inherited from whatever the proxy's original labels meant, if any | N/A — deterministic/heuristic, not human judgment |
| Cost | High — genuine paid-labor line item, larger than Priority's because multi-label annotation takes longer per item (8 independent yes/no decisions, not 1 pick-one) | Low | Low (compute only) |
| Time | Weeks (guideline pilot → full annotation → adjudication → agreement validation) | Days | Hours |
| Leakage risk | Manageable with proper split design (§7) | Unknown, and moot since no suitable proxy exists | **High and structural** — if labels are generated from the same keyword features the model trains on, the model trivially learns the generating function, not real category signal. Must be disclosed, not hidden — identical risk class to `priority_synthetic_v1` (`docs/data_audit_priority.md` §4). |
| Business realism | High | Low even if a proxy existed — a helpdesk taxonomy doesn't map cleanly to inbound enterprise email spanning Sales/Legal/HR/Marketing | Low — heuristic captures obvious keyword-driven cases, not genuinely ambiguous or multi-topic ones |
| Suitable for final PRD evaluation? | **Yes — the only option that is** | No (and no usable candidate exists per §2) | **No, explicitly and permanently no** — true even after further engineering, because the underlying labels never become real |

**Decision: Option C, strictly scoped to pipeline/architecture development —
not Option A** (out of scope for what an engineering session can produce;
no path to hiring and coordinating annotators from inside a codebase), **and
Option B is rejected outright** (§2 already establishes no suitable public
dataset exists for this taxonomy; the PRD's own named candidate, TREC, is
the wrong corpus entirely). This mirrors `docs/data_audit_priority.md` §4's
decision and reasoning exactly, because the underlying problem is the same
shape: a real business taxonomy with zero real ground truth anywhere in
reach of this engineering session.

### What this decision means concretely

Phase 5 is split into the same two tracks as Phase 4:

1. **Pipeline/architecture track (this phase, now):** build the full
   ingestion → feature engineering → multi-label training → multi-label
   evaluation → serving → audit-logging → feedback path, prove it works
   mechanically, using a clearly-labelled **synthetic bootstrap dataset**
   (`category_synthetic_v1`, `backend/scripts/generate_synthetic_category_dataset.py`).
   All metrics from this track are **pipeline validation metrics**, not
   business-readiness evidence, for the same structural-leakage reason as
   priority: the label generator and the model's own keyword features share
   the same lexicon (`app/feature_engineering/category_keywords.py`).
2. **PRD-compliant track (future, blocked on annotation budget):** once a
   real annotation effort exists (§5 below defines exactly what that needs
   to look like), the *same* pipeline (loader → feature extractors →
   `CategoryMLPipeline` → `Trainer` → `ArtifactManager`) re-runs against real
   labels with zero architecture changes required. That is the entire
   engineering point of building the pipeline now.

**No metric produced in track 1 will be described as satisfying FR-21
through FR-24's underlying business need, or the PRD's F1-micro > 0.80
target, in any document in this repository.** Every number is labelled
`[SYNTHETIC DEV DATA]`, and the surrounding text says what it does and does
not prove — see §6 for the explicit three-way distinction this phase's
instructions require (pipeline validation / model validation / PRD
compliance).

## 5. Feature Availability Audit

Auditing what this codebase can actually produce today for a categorization
model, honestly, the same way `docs/data_audit_priority.md` §5 did for FR-17:

| Signal | Available from | Status | Consequence if used anyway |
|---|---|---|---|
| Subject/body keywords per category | The email itself | **Available, real** — `ContentFeatureExtractor` extended with 8 new category-keyword-count fields (`app/feature_engineering/category_keywords.py`, §6 of the architecture doc) | — |
| TF-IDF text signal | The email itself | **Available, real** — same `TfidfVectorizer` machinery as spam/priority | — |
| Sender domain (internal/external/freemail) | Metadata (email headers) | **Available, real** — reuses `MetadataFeatureExtractor` unchanged; the single most useful disambiguator per §3 for Support/IT and Sales/Billing pairs | — |
| Time-of-day / day-of-week | Metadata | **Available, real**, but **expected weak for this task** — unlike Priority (FR-17 names it directly), nothing in FR-21-24 or the taxonomy in §3 ties category to time. Included for pipeline consistency (same `MetadataFeatureExtractor` output every other module uses), not because it's expected to carry real category signal — stated honestly rather than implied as a deliberate feature choice. | If a future feature-importance analysis on real data shows it's pure noise for this task, it should be dropped then, not defended because it's "already there." |
| Recipient/thread structure (CC count, is_reply, is_forward) | Metadata | **Available, real** | — |
| Organization's actual department names/routing rules | Would come from a real admin-configured taxonomy (FR-23) | **Does not exist** — no multi-tenant org config store in this codebase | Not implemented; taxonomy is hard-coded to FR-21's 8 labels (§1) |
| Sender's historical category pattern (e.g. "this sender is always Sales") | Would come from a persistent sender profile store | **Does not exist** — identical gap to Priority's FR-17 sender-history limitation (`docs/data_audit_priority.md` §5) | Not implemented; would be the same leakage risk if backfilled from synthetic labels |

## 6. Leakage-Safe Split Design

Identical reasoning to `docs/data_audit_priority.md` §6, restated for this
dataset because both leakage channels apply here unchanged:

1. **Sender leakage**: the same Enron sender-repetition problem — a random
   split can place near-duplicate emails from the same sender in both train
   and test.
2. **Synthetic-label leakage**: because labels are generated by a
   keyword-driven heuristic (§4), this is the more severe channel — it
   exists regardless of split strategy, which is why track-1 metrics are
   capped in interpretation (§4), not just split more carefully.

**Split strategy: grouped by `sender_email`** (`sklearn.model_selection.GroupShuffleSplit`),
identical mechanism to `priority_synthetic_v1` — every email from a given
sender lands entirely in one of train/val/test. Multi-label stratification
adds a wrinkle plain grouped splitting doesn't fully solve (a rare category
like Legal could end up underrepresented in one split purely by which
senders happened to land there) — this is disclosed in
`run_metadata.json`'s per-split label distribution once generated, not
assumed away.

## 7. Multi-Class vs. Multi-Label — Why Multi-Label, Not a Simplification

This is not optional or open for reinterpretation: **PRD §9.1 explicitly
names "Multi-label Classification" as Categorization's task type, and FR-22
explicitly requires it.** Restated here anyway (rather than silently
assumed) because this phase's instructions require the decision to be
justified, not just followed:

| | Multi-class (pick exactly one) | Multi-label (this phase's choice) | Hierarchical |
|---|---|---|---|
| Matches FR-22 | No — directly contradicts "one email may belong to multiple categories" | **Yes** | Not directly; would need a taxonomy tree the PRD doesn't define |
| Matches the worked example (§3) | No — "legal terms of the invoice" would force a lossy Legal-*or*-Billing choice | **Yes** — both labels, independently scored | N/A |
| Model architecture | Single softmax over 8 classes | **One-vs-Rest**: 8 independent binary classifiers (per PRD §9.1's own named baseline), or any estimator exposing per-label probabilities | A cascade of classifiers, one per tree level |
| Evaluation | Accuracy / single-label F1 | **F1-micro, Hamming loss** (PRD §14.1's named metrics only make sense for multi-label — Hamming loss has no meaning for single-label) | Level-wise + full-path metrics |
| API response shape | One `category` field | **List of `{category, confidence}`** (FR-24) | Path + per-level confidence |

**Decision: multi-label, One-vs-Rest, per PRD §9.1 and FR-22.** No
alternative was seriously considered as a replacement — this section exists
to make the "why" explicit and connect it to FR-22/§14.1 rather than to
present a genuine three-way tradeoff, since the PRD already settles it.
