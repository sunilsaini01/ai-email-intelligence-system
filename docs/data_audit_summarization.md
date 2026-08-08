# Email Summarization — Data Audit and Strategy Decision

**Status: gates Phase 6's evaluation claims.** Read this before trusting
any ROUGE number in `docs/model_cards/email_summarization.md` — the
short version is: real human-written reference summaries exist and were
used, but for **news articles, not email**, and at a length that doesn't
match FR-25's target. This document explains exactly what that does and
does not license claiming.

## 1. PRD-Named Datasets — Checked, Not Present

PRD §8.1 names two summarization datasets: **CNN/DailyMail (300,000
article-summary pairs)** and **XSum (227,000 article-summary pairs)**, both
via HuggingFace Datasets, MIT license. Checked directly, same discipline
applied to Phase 5's TREC check:

- Neither is present in this repository.
- `app/data_ingestion/dataset_registry.py` DOES have a `cnn_dailymail`
  entry, but it's aspirational, not descriptive of anything on disk: its
  `local_path` is `data/external/cnn_dailymail/` (empty — nothing has ever
  been downloaded there) and its `preprocessing_script` points at
  `src/data/loaders/cnn_dm_loader.py`, a path that doesn't exist anywhere
  in this codebase (the real loaders all live under
  `backend/app/data_ingestion/`). This is the same class of finding as
  Phase 5's TREC entry — a PRD-inherited dataset name in the registry that
  was never actually acquired — flagged explicitly rather than treated as
  if the entry meant real data exists.

## 2. What Actually Exists: BBC News Summary (a Phase 2 artifact)

A real dataset already sits in this repository, physically at
`data/raw/cnn_dailymail/BBC News Summary/` (the directory name is itself
misleading — it's nested under a folder called `cnn_dailymail` despite
containing the BBC News Summary dataset, not CNN/DailyMail; almost
certainly a leftover from an early, later-abandoned download attempt,
consistent with the `cnn_dailymail` registry entry describing something
that was never finished), with a loader already written for it
(`app/data_ingestion/bbc_summary_loader.py`) from Phase 2's EDA work but
never wired into any training pipeline until now.

### Verified directly (not assumed from a README or registry entry)

```
rows: 2,225 (business 510, entertainment 386, politics 417, sport 511, tech 401)
body word count:    min 89,  median 332,  max 4,432
summary word count: min 38,  median 142,  max 2,073
duplicate article bodies: 98 (of 2,225 — ~4.4%)
```

Sample (BBC "business" article, truncated):

> *Ad sales boost Time Warner profit — Quarterly profits at US media giant
> TimeWarner jumped 76% to $1.13bn (£600m) for the three months to
> December, from $639m year-earlier...*

Reference summary (truncated, same article):

> *TimeWarner said fourth quarter sales rose 2% to $11.1bn from $10.9bn.
> For the full-year, TimeWarner posted a profit of $3.36bn, up 27% from
> its 2003 performance...*

## 3. Data Readiness Report

| Dataset | Size | Source | Domain | Language | Summary availability | Summary quality | License | Splits | Domain match | Limitations |
|---|---|---|---|---|---|---|---|---|---|---|
| CNN/DailyMail (PRD-named) | 0 present | N/A — never downloaded | News | English | N/A | N/A | MIT (if downloaded) | N/A | N/A | **Does not exist in this repo** |
| XSum (PRD-named) | 0 present | N/A — never downloaded | News | English | N/A | N/A | MIT (if downloaded) | N/A | N/A | **Does not exist in this repo** |
| **BBC News Summary** (found, used) | 2,225 article/summary pairs | Derived from BBC News (2004–2005), standard academic dataset (D. Greene & P. Cunningham, 2006) | **News, not email** | English | **100% — every article has a human-written reference summary** | **Human-written, extractive-style multi-sentence abstracts** — genuine quality, not machine-generated | Research/academic use (standard for this widely-used benchmark) | Not pre-split; grouped/deduplicated split built this phase (§5) | **Low** — news articles have headlines/bylines/datelines and formal journalistic register; no sender, subject line, thread structure, signature, or quoted-reply conventions that email has | 98 duplicate bodies (4.4%) must be deduplicated before splitting (§5); reference summaries run far longer (median 142 words) than FR-25's 2–3-sentence target — a length/format mismatch independent of the domain mismatch |

## 4. Is This Data "Trustworthy"? — A More Nuanced Answer Than Phase 4/5's

Phase 4 and 5's synthetic datasets were **heuristically fabricated** —
no human ever looked at the labels. BBC News Summary is different in kind,
not just degree: **the summaries are genuinely human-written**, by
professional editors, for real published articles. That's real evidence of
*something* — specifically, of how good a summarization model is at
producing human-quality abstractive/extractive summaries of formal written
English, in general. What it is **not** evidence of:

- How well the same model handles **email-specific structure**: subject
  lines, quoted reply chains, signatures, informal register, embedded
  action requests ("please send the invoice by Friday") — none of which a
  news article has anything analogous to.
- **FR-25's specific target shape**: a 2–3 sentence summary. BBC's
  reference summaries have a median length of 142 words — multiple
  paragraphs' worth by FR-25's standard. A model tuned/evaluated to match
  BBC's reference length would produce summaries far longer than the PRD
  requires; ROUGE computed against these references would reward that
  mismatch, not penalize it.
- **FR-26's entity-preservation requirement**: BBC summaries aren't scored
  on whether they preserved names/dates/amounts/action-items specifically
  — that's a dimension this phase must measure separately (see the model
  card's "Entity Preservation" section), not something ROUGE-against-BBC
  answers on its own.

**Conclusion: BBC News Summary supports genuine MODEL VALIDATION (a real,
human-authored quality signal for comparing the extractive baseline
against the abstractive model — see the model card's baseline-vs-advanced
comparison) but does NOT support PRD COMPLIANCE (wrong domain, wrong
summary-length profile, no email-specific structure).** This is a real,
substantive distinction, not a technicality — restated in
`docs/phase6_requirements_traceability.md` and every place a ROUGE number
appears in this phase's documentation.

## 5. Data Strategy Decision

Per Gate 4's four options:

| | A — Suitable public dataset | B — Custom annotation | C — Synthetic ground truth | **D — Use what exists, scoped honestly** |
|---|---|---|---|---|
| Applies here? | Partially — BBC exists and is real, but wrong domain | Not attempted this phase — genuine email+summary annotation is a real, separate effort (see "Known Gaps") | **Rejected outright** — fabricating reference summaries and calling them ground truth is exactly what Gate 4/the Critical Data Rule forbid | **This phase's choice** |

**Decision: use BBC News Summary for what it actually validates (baseline
vs. advanced model comparison, real ROUGE numbers against real human
summaries), and explicitly do NOT claim it validates FR-25/26/27's
email-specific requirements.** No synthetic/fabricated email-summary pairs
were created — unlike Phase 4/5, there was no need to choose between "no
data" and "fabricate labels," because a genuinely real, human-authored
reference-summary dataset already existed in the repository; the honesty
obligation here is about **scoping the claim correctly**, not about
choosing between real and fake data.

**DATA QUALITY STATUS (per Gate 4's required classification): PROVISIONAL.**
Not production-grade (wrong domain for the PRD's actual email use case),
not synthetic (the summaries are genuinely human-written, not fabricated),
not blocked (real evaluation was possible and was done). Provisional is the
correct middle classification, and it is the one used consistently across
this phase's documentation.

## 6. Leakage-Safe Split Design

Two leakage channels, addressed before any train/val/test split:

1. **Duplicate articles** (98 of 2,225, §2) — deduplicated on exact body
   text before splitting, same discipline as every prior phase's dataset
   generator.
2. **Category imbalance** — sport (511) and entertainment (386) differ by
   ~32%; stratified by `category` during the split so no split is skewed
   toward one topic's vocabulary, which would bias TextRank's sentence
   scoring (topic-specific term frequency) differently across splits.

No sender/thread grouping applies here (unlike the email-derived synthetic
datasets) — BBC articles have no sender or thread concept. Split mechanism:
`sklearn.model_selection.train_test_split(..., stratify=df["category"])`,
80/10/10, `random_state=42` for reproducibility, consistent with every
other phase's fixed seed.

## 7. Known Gaps

- **No real email+summary paired dataset exists anywhere in reach of this
  engineering session** — the same class of gap Priority and Categorization
  have for their labels, but for a different reason: this isn't a "human
  annotation effort never started" gap so much as "no such dataset appears
  to be publicly available at all" for the email domain specifically (news
  summarization corpora are common; enterprise-email summarization corpora
  with human reference summaries are not, likely because emails contain
  real business PII and organizations don't publish them).
- **If this gap is ever addressed**, the annotation strategy would look
  like `docs/annotation_guidelines_categorization.md`'s process (sampling
  strategy, multiple human summarizers per email for inter-rater
  agreement on quality) adapted to a generation task rather than a
  classification one — not designed in full this phase, since Gate 4
  permits "document the blocker" as a valid outcome and a full annotation
  spec for a task this different from classification would be a
  substantial, separate effort.
