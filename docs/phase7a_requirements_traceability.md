# Phase 7A — Sentiment Analysis: Requirements Traceability

Extracted directly from `project document/PRD_AI_Email_Intelligence_System.md`.
No requirement below was invented — every row cites its PRD source line.

## Functional Requirements (PRD §5, Module 6)

| PRD Requirement | Design | Implementation | Test | Evidence |
|---|---|---|---|---|
| **FR-29**: "System shall classify email sentiment: Very Negative / Negative / Neutral / Positive / Very Positive" | VADER compound score bucketed into the exact 5-class taxonomy via disclosed heuristic thresholds (not a lexicon-native 5-class output — VADER natively gives a continuous score plus pos/neu/neg proportions) | `app/inference/sentiment_predictor.py::bucket_compound` | `test_sentiment_predictor.py::test_bucket_compound_covers_all_five_labels` | Model card "Model Details"; `docs/data_audit_sentiment.md` §3 for threshold rationale |
| **FR-30**: "System shall detect primary emotion: Anger / Frustration / Confusion / Satisfaction / Urgency" | **Not implemented this phase** — a distinct 5-class taxonomy requiring its own data audit, deliberately deferred like Intent Detection (Phase 7B) rather than bundled in | — | — | `docs/data_audit_sentiment.md` §1 |
| **FR-31**: "Negative or Very Negative sentiment on non-spam emails shall increase priority score" | **Not implemented this phase** — would require modifying `priority_service.py`'s decision logic before sentiment has any real-world evidence behind it; deferred as a documented cross-module integration point, not silently dropped | — | — | `docs/data_audit_sentiment.md` §1, `docs/architecture_sentiment.md` "Explicitly Deferred" |
| **FR-32**: "System shall track sentiment trends per sender over time" | **Not implemented this phase** — an analytics/aggregation capability belonging with the Phase 10 dashboard (`GET /analytics/sentiment`); this phase implements prediction + audit logging (the raw material a future trend query would read), not the trend query itself | `SentimentPredictionLog` persists every prediction with a timestamp (the raw material FR-32 would eventually aggregate) | — | `docs/data_audit_sentiment.md` §1 |

## Non-Functional Requirements

| PRD Requirement | Source | Design | Evidence |
|---|---|---|---|
| Latency target (bundled with Priority/Category/Intent): P50 < 200ms, P95 < 400ms, hard limit 1s | PRD §6.1 | VADER's measured average latency is **0.79ms** (`train_sentiment_model.py` benchmark, n=879) — several orders of magnitude under the bundled target, since nothing here involves model inference in the classical/transformer sense | Model card "Why VADER, Not a Trained Classifier" |
| Evaluation: **F1-weighted**, target **> 0.82** (metrics table) or **> 0.80** (Definition of Done — PRD states both) | PRD §14.1, §17 | **Not evaluable this phase** — no ground truth exists to compute F1 against (VADER is zero-shot; the one dataset with "labels," `sentiment_synthetic_v1`, is circular — see model card "Model Selection"). The comparison-classifier's 0.33 macro F1 is reported but explicitly NOT presented as evidence toward this PRD target, since it measures agreement with VADER's own labels, not real sentiment accuracy | Model card "Model Selection" |
| Data (PRD §8.1): Amazon Reviews Polarity (3.6M), Twitter Sentiment (1.6M), HuggingFace/Kaggle | PRD §8.1 | Amazon Reviews Polarity **exists in this repo** (real corpus, `amazon_sentiment_loader.py`) but was evaluated and rejected — wrong domain (product reviews) AND wrong taxonomy (binary, not 5-class). Twitter Sentiment **was never acquired** (`data/raw/twitter_sentiment/` is an empty placeholder) | `docs/data_audit_sentiment.md` §2 |
| Architecture (PRD model comparison table): baseline **VADER + TextBlob**, production fine-tuned **RoBERTa-base** | PRD § model comparison table | VADER implemented and served. **TextBlob not implemented** — VADER alone was judged sufficient for a lexicon-based baseline (TextBlob is also lexicon-based with substantial overlap in approach; adding it would not resolve any of VADER's structural limitations documented in the error analysis, e.g. sarcasm, indirect negativity). RoBERTa fine-tuning **not implemented** — same data-blocking reason as every other module's "advanced model" step: no labelled email-domain data exists to justify or evaluate a fine-tune against | `docs/data_audit_sentiment.md` §4 |

## Explicitly Not Implemented This Phase (and why)

| PRD reference | Why deferred |
|---|---|
| FR-30 (emotion detection) | Distinct 5-class taxonomy, own data audit needed — see Functional Requirements table above |
| FR-31 (priority-score integration) | Premature cross-module coupling before sentiment has real-world evidence — see Functional Requirements table above |
| FR-32 (sender trend tracking / `GET /analytics/sentiment`) | Belongs with Phase 10's Analytics Dashboard, not a single-prediction API — see Functional Requirements table above |
| TextBlob as a second classical baseline | Judged not to add information beyond VADER — see Non-Functional Requirements table above |
| RoBERTa-base fine-tuning | No labelled email-domain sentiment data exists to fine-tune against or evaluate — same blocking reason as priority/category/summarization's advanced-model steps |
| Integration into the aggregate multi-agent pipeline response (PRD §11) | Most of that response's other modules (Intent, Routing) don't exist yet — same reasoning already applied when Priority/Category/Summarization shipped standalone |

## Engineering Gates (this phase's own Section 40) — Outcome

| Gate | Outcome |
|---|---|
| A — PRD requirements understood | Done — FR-29 to FR-32 extracted above, scope of 7A vs. 7B vs. deferred items made explicit |
| B — Repository architecture understood | Done — reuse audit covered data_ingestion/preprocessing/feature_engineering/pipeline/training/evaluation/inference/services/API/database/security |
| C — Current tests verified | Done — 152 passed/1 skipped baseline confirmed before changes |
| D — DB metadata correctness verified | Done — found AND fixed a pre-existing gap (CategoryPredictionLog/SummaryLog missing from `app/models/__init__.py`), verified against a real disposable Postgres 16 container, not just SQLite |
| E — DB write-hang status reviewed | Done — confirmed PARTIAL/mitigated-not-root-caused status, no new experiments run (none warranted — sentiment's write path is structurally identical to the other three modules') |
| F — Canonical preprocessing identified | Done — `email_preprocessor.py` confirmed canonical, `SENTIMENT_CONFIG` reused after fixing a real defect (`lowercase=True` was defeating VADER's own capitalization signal) |
| G — Artifact compatibility understood | Done — deliberately NOT coupled to `FeatureSchema`/shared `ContentFeatures` (see architecture doc), avoiding a third module joining the Phase 5 incident's fragility |
| H — Sentiment dataset quality assessed | Done — Amazon Reviews Polarity audited and rejected (`UNTRUSTWORTHY` for this purpose); `sentiment_synthetic_v1` built and classified `SYNTHETIC` |
| I — Domain match assessed | Done — Amazon: LOW (wrong domain AND wrong taxonomy). VADER zero-shot: unvalidated-on-domain (disclosed as PROVISIONAL, not claimed accurate) |
| J — Architecture design approved before coding | Done — presented to the user as a READY verdict with 3 explicit decision forks (baseline strategy, FR-30 scope, FR-31/32 scope), all confirmed before implementation began |
