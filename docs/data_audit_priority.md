# Priority Classification — Data Audit, Taxonomy, and Data Strategy Decision

**Status: gates all of Phase 4.** Nothing in `docs/model_cards/priority_classification.md`
or `docs/architecture_priority_classification.md` should be read as PRD-compliant
until the "Data Strategy Decision" section below is resolved by real annotation
(§ Option A) — see that section for exactly what changes when it is.

## 1. PRD Requirements (FR-16 to FR-20)

| ID | Requirement (verbatim, PRD §5 Module 3) |
|---|---|
| FR-16 | System shall assign a priority label: Critical / High / Medium / Low |
| FR-17 | Priority shall incorporate: sender history, subject keywords, body sentiment, time of day |
| FR-18 | Critical emails shall trigger immediate notifications (in-app + configurable webhook) |
| FR-19 | System shall allow agents and managers to override priority labels |
| FR-20 | Priority overrides shall be logged as feedback for model improvement |

Data requirement (PRD §8.2): **10,000+ priority-labelled emails, minimum 3
annotators per email, Cohen's Kappa ≥ 0.70, detailed guidelines before
annotation starts.** Milestone 2 (PRD §17) target: **F1-macro > 0.82** for the
priority model (the PRD states 0.82 at Milestone 2 and 0.85 as the general
per-class bar in §14.1 for High/Critical specifically — both are tracked
below; neither is claimed as met by synthetic data).

## 2. Data Audit — what actually exists today

| Check | Finding |
|---|---|
| `data/annotations/guidelines/annotation_guidelines_v1.0.md` | Exists. Contains label *definitions* and 2 illustrative examples per class. No borderline/escalation/exclusion rules, no annotator process, no labelled emails. |
| `data/processed/v1.0/train.parquet` | 3 rows, columns `[email_id, body_clean, spam_label]`. This is `tests/data/test_pipeline.py`'s fixture output (`run_metadata.json` records `"sha256": "dummy_checksum_123"` and `pipeline_script: "test_pipeline_metadata.py"`) — a test artifact, not project data. No priority column exists anywhere in it. |
| `backend/app/data_ingestion/dataset_registry.py` | Zero registered datasets carry a priority label. |
| `data/raw/custom/` | Exists, 0 bytes — the placeholder Phase 2 left for custom annotation output. Never populated. |
| Full-corpus search (Enron 1.4GB, SpamAssassin 46MB, Amazon 1.7GB, etc.) | No priority-pattern matches beyond one coincidental keyword hit in an unrelated Amazon reviews file. |

**Finding: zero priority-labelled emails exist in this repository.** The
10,000+ / 3-annotator / Kappa ≥ 0.70 requirement is unmet. This is stated
plainly because the alternative — proceeding as if it were met — would mean
reporting a model's metrics as evidence for a business decision (routing,
notification, SLA escalation) with no verified ground truth behind them.

### Data Readiness Report

| Dataset | Rows | Labels | Class Distribution | Missingness | Duplicates | Temporal Coverage | Source | License | Quality | Suitability |
|---|---|---|---|---|---|---|---|---|---|---|
| Priority-labelled (human) | **0** | N/A | N/A | N/A | N/A | N/A | None | N/A | N/A | **Not usable — does not exist** |
| Enron corpus (raw text) | ~500K available, 1.4GB on disk | None (no priority field) | N/A | Sparse `Date`/`To` headers on some messages (see §4) | ~412 removed by Message-ID in unrelated test fixture; not yet deduplicated for this use | 1999–2002 (Enron collapse era) | CMU/Kaggle, `data/raw/enron/emails.csv` | Research use | Real corporate text, but zero priority ground truth | Usable **only** as the text/metadata source for a synthetic bootstrap (§4) |
| **`priority_synthetic_v1`** (generated) | **10,000** (7,000/2,121/879 train/val/test) | Critical/High/Medium/Low, **heuristic-derived** | Low 57.4% / Medium 32.9% / High 8.0% / Critical 1.7% | None (text/sender/date required by the generator; rows without them are dropped upstream) | Deduplicated on raw message body | 1999–2002 (inherited from Enron) | Derived from `enron`, `backend/scripts/generate_synthetic_priority_dataset.py` | Research use (inherited) | Real text + real headers, **synthetic labels**, 5.64% deliberately injected label noise, 1,353 unique senders | **Pipeline development only — see §4.** Not usable for any PRD-compliance claim. |

## 3. Label Taxonomy

Derived from the PRD's problem framing (§2.1: "a critical customer complaint
lands in spam," "a compliance-critical legal notice sits unread") and the
Phase 2 guideline draft, extended with the borderline/exclusion rules that
draft was missing.

**Operating question the label answers: "How urgently must a human act on
this, and what happens if they don't act within a normal business cycle?"**
Not "how negative is the tone" (that's sentiment, a different, not-yet-built
signal) and not "how long is it" (that's summarization-worthy, not
priority-worthy).

| Label | Definition | Positive examples | Explicit exclusions |
|---|---|---|---|
| **Critical** | Immediate, material business/security/legal/safety impact; a delay of hours causes damage that can't be undone by a later response. | Active security breach, legal notice/subpoena, production outage affecting customers, imminent contract/compliance deadline (<24h), safety incident. | A merely angry customer email is NOT automatically Critical (see Escalation below) — anger alone is a sentiment signal, not an urgency signal. |
| **High** | Real business impact, needs same-business-day handling, but the world doesn't end if it waits a few hours. | Customer complaint with financial impact, payment/billing dispute, escalated support ticket, a VIP sender's ordinary request. | A polite request with a distant deadline ("sometime next month") is not High merely because the sender is important — importance modulates, doesn't override, actual urgency. |
| **Medium** | Normal business communication expecting a response within the standard cycle (1–2 business days). | Status updates, ordinary customer inquiries, internal requests, meeting coordination. | Default bucket — most legitimate business email is Medium. If unsure between Medium and High, prefer Medium (asymmetric cost: over-escalating trains the model to cry wolf, which the PRD explicitly identifies as a failure mode in existing tools §2.1). |
| **Low** | No action required, or action has no deadline. | Newsletters, FYI broadcasts, automated notifications, routine internal announcements. | Spam is NOT Low — spam is a separate binary label (Module 2) with its own quarantine path; a priority label should never be assigned to something that should have been filtered as spam upstream. |

**Borderline / escalation rules** (the part the Phase 2 draft didn't cover):
- **Escalation language ("please escalate," "speaking to your manager," repeated follow-ups) raises priority by one level from what content alone would suggest**, capped at Critical — it's a signal of accumulating impact, not a new independent feature.
- **A reply/forward of a higher-priority thread inherits at minimum the parent's priority** — a one-word "Agreed." reply to a Critical thread is still operationally Critical (this is the exact scenario the PRD names in §2.2: "a one-word reply means nothing without its thread"). This repo does not yet track thread lineage end-to-end (see §4), so this rule is stated for the human annotation process and cannot yet be enforced automatically.
- **Ambiguous/multi-intent emails** (e.g., a complaint that also contains a routine question) are labelled by their *most urgent* contained intent, not an average.
- **Automated/system-generated emails default to Low** regardless of alarming-sounding subject lines (e.g., "CRITICAL: disk usage report" from a monitoring cron job) — annotators must check sender/structure, not just keywords. This rule exists specifically because it's the failure mode a keyword-only heuristic (§4) is most exposed to.

## 4. Data Strategy Decision

| | **A — Custom annotation** | **B — Public/proxy dataset** | **C — Synthetic/heuristic bootstrap** |
|---|---|---|---|
| Validity vs. PRD | Only option that actually satisfies FR-required data spec | Would still not satisfy it (wrong label space) | Does not satisfy it, and cannot |
| Domain relevance | High (real enterprise email, if sourced right) | **Low** — no public dataset uses this label space; closest analogues (support-ticket priority sets) are ticket systems, not raw email, and carry different selection bias | Medium — real Enron email text + real headers, but the *label* is not real |
| Annotation quality | Controllable (guidelines + Kappa gate) | N/A — inherited from whatever the proxy's original labels meant | N/A — deterministic/heuristic, not human judgment |
| Cost | High — 10K+ emails × 3 annotators is a genuine paid-labor line item | Low | Low (compute only) |
| Time | Weeks (guideline pilot → full annotation → adjudication → Kappa validation) | Days | Hours |
| Leakage risk | Manageable with proper split design | Unknown — proxy dataset's own construction may already leak | **High and structural** — if labels are generated from the same keyword features the model trains on, the model will trivially learn the generating function, not real-world priority. Must be disclosed, not hidden. |
| Business realism | High | Low — a support-ticket taxonomy doesn't map cleanly to raw inbound email | Low — heuristic captures the taxonomy's obvious cases, not its hard ones |
| Suitable for final PRD evaluation? | **Yes — the only option that is** | No | **No, explicitly and permanently no** — this is true even after more engineering, because the underlying labels never become real |

**Decision: Option C, strictly scoped to pipeline/architecture development —
not Option A (out of scope for what an engineering session can produce; there
is no path to hiring and coordinating 3 human annotators from inside a
codebase), and Option B is rejected outright (no public dataset shares this
label space; adapting one would mean silently relabeling someone else's
taxonomy as if it were this one, which is worse than admitting no data
exists).**

### What this decision means concretely

Phase 4 is split into two tracks, and every artifact below is tagged with
which track it belongs to:

1. **Pipeline/architecture track (this phase, now):** build the full
   ingestion → feature engineering → training → evaluation → serving →
   audit-logging → feedback path, prove it works mechanically, using a
   clearly-labelled **synthetic bootstrap dataset**. All metrics from this
   track are **pipeline validation metrics**, not business-readiness
   evidence, because of the leakage risk named above — a heuristic-labelled
   dataset lets the model partially "cheat" by re-deriving the same keyword
   rule that generated its own labels. This is disclosed in every place a
   metric appears (model card, this doc, the completion report), not
   hidden behind a good-looking F1 score.
2. **PRD-compliant track (future, blocked on annotation budget):** once a
   real annotation effort exists — Label Studio deployment, 3 annotators,
   guideline pilot, Kappa ≥ 0.70 gate — the *same* pipeline (loader → feature
   extractors → `PriorityMLPipeline` → `Trainer` → `ArtifactManager`) re-runs
   against real labels with zero architecture changes. That's the entire
   point of building the pipeline now: the annotation gap is a data problem,
   not an engineering problem, and the engineering shouldn't wait on it.

**No metric produced in track 1 will be described as satisfying FR-16
through FR-20's underlying business need, or the PRD's F1-macro targets, in
any document in this repository.** Where a number is reported, it is
labelled `[SYNTHETIC DEV DATA]` and the surrounding text says what it does
and does not prove.

## 5. Feature Availability Audit (FR-17)

FR-17 names four signals. Auditing each against what this codebase can
actually produce today, honestly:

| FR-17 signal | Available from | Status | Consequence if used anyway |
|---|---|---|---|
| Subject keywords | The email itself | **Available, real** — `ContentFeatureExtractor` + new `priority_keywords.py` (urgency/escalation/SLA lexicons, §6) | — |
| Time of day | Metadata (email headers) | **Available, real** — Enron's `Date` header parses to `hour_of_day`/`day_of_week`/`is_after_hours`/`is_friday_afternoon` via the existing `MetadataFeatureExtractor` | — |
| Body sentiment | Would come from the Phase 7 Sentiment module | **Not available — Phase 7 doesn't exist yet.** A lightweight lexicon-based polarity proxy is added *only* as a labelled stand-in (see model card), not presented as "sentiment analysis" | If presented as real sentiment output, overstates what Phase 7 will actually deliver (a fine-tuned classifier, not a word list) |
| Sender history | Would come from a persistent sender/account profile store | **Does not exist in this codebase.** No CRM, no `senders` table, no historical interaction log — Module 1 (email ingestion/persistence) doesn't exist yet, and even once it does, "history" needs volume over time to mean anything | **Not implemented.** Fabricating a `sender_priority_history` feature (e.g., defaulting everyone to "unknown") would be a column that's constant noise at best, and if backfilled from the same synthetic labels, a direct leakage channel at worst. Documented as an open gap, not a silent placeholder. |

**Feature classification (as requested):**
1. **Available from the email itself:** subject text, body text, length/punctuation/capitalization features, urgency/escalation/SLA keyword counts, URL/phone/currency mentions, Re:/Fwd: subject prefixes.
2. **Available from metadata:** hour of day, day of week, weekend/after-hours/Friday-afternoon flags, sender domain classification, recipient counts (all derivable from real Enron headers where present).
3. **Available from historical systems:** none, today. This is the honest gap behind FR-17's "sender history" clause.
4. **Unavailable at inference:** `thread_depth` and attachment fields — no loader in this repo currently extracts message threading references (`In-Reply-To`/`References` headers) or MIME attachment parts, so these default to `0`/`False` both in training and at inference. This is a real, disclosed train/serve consistency point (both sides use the same default, so there's no skew *between* them — but the feature itself carries no signal until a loader is extended to populate it).

## 6. Leakage-Safe Split Design

Random row-level splitting is inappropriate here for two independent reasons:

1. **Sender leakage**: Enron email is highly repetitive per sender (the same
   person emails the same recipients using similar phrasing). A random split
   can put near-duplicate emails from the same sender in both train and test,
   inflating apparent accuracy on patterns the model only "recognizes,"
   not generalizes.
2. **Synthetic-label leakage** (§4): because labels are generated by a
   keyword-driven heuristic, this is a second, more severe leakage channel
   than sender overlap — it exists regardless of split strategy, which is
   exactly why track-1 metrics are capped in interpretation (§4), not just
   split more carefully.

**Split strategy: grouped by `sender_email`** (`sklearn.model_selection.GroupShuffleSplit`),
not plain stratified — every email from a given sender lands entirely in one
of train/val/test. This is a proxy for true thread-level grouping (no
`In-Reply-To`/`References` extraction exists yet, per §5) but is a real,
available signal today, unlike thread ID. Stratification on label is
attempted within the grouping constraint on a best-effort basis (group
splits can't guarantee perfect class balance the way row-level stratified
splits can — documented in the data readiness numbers once the dataset is
generated, not assumed here).
