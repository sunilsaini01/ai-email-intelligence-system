# Phase 7B — Intent Detection: Requirements Traceability

Extracted directly from `project document/PRD_AI_Email_Intelligence_System.md`.
No requirement below was invented — every row cites its PRD source line.

## Functional Requirements (PRD §5, Module 7)

| PRD Requirement | Design | Implementation | Test | Evidence |
|---|---|---|---|---|
| **FR-33**: "System shall identify primary intent: Complaint / Inquiry / Request / Feedback / Escalation / Order / Cancel / Refund / Schedule" | `IntentMLPipeline` (TF-IDF + One-vs-Rest LR), trained on `intent_synthetic_v1` (keyword-heuristic bootstrap, disclosed SYNTHETIC per your confirmed decision) | `app/pipeline/intent_pipeline.py`, `app/inference/intent_predictor.py`, `app/services/intent_service.py` | `test_intent_pipeline.py`, `test_intent_endpoint.py` | Model card "Per-Class F1" — F1-macro 0.3891, with 2 of 9 classes (Escalation, Refund) demonstrably unreliable, not just unvalidated |
| **FR-34**: "System shall support multi-intent detection per email" | `OneVsRestClassifier` + `MultiLabelBinarizer`, same multi-label mechanics as Categorization; confirmed multi-label directly from the PRD's own "Complaint + Refund" example, not inferred | `app/pipeline/intent_pipeline.py` | `test_intent_pipeline.py::test_predict_returns_a_list_of_label_lists`, qualitative eval's Cancel+Refund case | `docs/intent_labeling_strategy.md` §1 |
| **FR-35**: "System shall extract key entities: order IDs, dates, amounts, product names, person names" | Reuses `summary_grounding.extract_entities()` for dates/amounts/names (FR-26's extraction logic, identical need); new `ORDER_ID_PATTERN` regex + `extract_product_names()` (spaCy PRODUCT NER, disclosed low-recall) | `app/nlp/intent_entities.py` | `test_intent_entities.py` | Model card "FR-35 Entity Extraction" — verified against the PRD's own "order #45821" example |
| **FR-36**: "Intent shall be used as a signal for both routing and auto-reply generation" | **Not implemented this phase** — this phase produces the intent signal (API response + audit log) only; routing (Phase 8) and auto-reply (a later phase) don't exist yet to consume it | `IntentPredictionResponse`, `intent_prediction_logs` (the raw material a future consumer would read) | — | `docs/architecture_intent.md` "Known Gaps" |

## Non-Functional Requirements

| PRD Requirement | Source | Design | Evidence |
|---|---|---|---|
| Latency (bundled with Priority/Category/Sentiment): P50 < 200ms, P95 < 400ms, hard limit 1s | PRD §6.1 | Measured: 2.57ms for a combined classify+entity-extract call in smoke testing — well under budget; not yet formally P50/P95 benchmarked at load | Smoke test output, this report §21 |
| Evaluation: **F1-macro**, target **> 0.80** (metrics table) or **> 0.78** (Definition of Done — PRD states both) | PRD §14.1, §17 | **Not evaluable as PRD-compliant** — synthetic labels only. 0.3891 reported as a pipeline-validation number, explicitly not compared against the PRD target as if it meant anything for real intent accuracy | Model card |
| Data (PRD §8.1/8.2): **Custom annotation required**, 5,000+ emails, min 500/class × 9 | PRD §8.1/8.2 | **Confirmed independently** — no proxy dataset exists in this repo or is named by the PRD (unlike Sentiment/Summarization). `docs/intent_labeling_strategy.md` specifies the full annotation plan (not yet executed) | `docs/data_audit_intent.md` §2 |
| Architecture (PRD § model comparison table): baseline **TF-IDF + Multi-label LR**, production **fine-tuned BERT** | PRD § model comparison table | Classical baseline implemented and served (LR chosen over SVM/NB by F1-macro). BERT fine-tuning **not implemented** — no labelled data exists to fine-tune against or evaluate, same blocking reason as every other module's advanced-model step | Model card "Why Logistic Regression" |

## Explicitly Not Implemented This Phase (and why)

| PRD reference | Why deferred |
|---|---|
| FR-36 (routing/auto-reply integration) | Consumers (Phase 8 Routing, later Auto-Reply) don't exist yet — same reasoning already applied to every prior module's cross-phase integration points |
| Sentiment↔Intent coupling of any kind | Explicit architectural boundary from Phase 7A, reaffirmed this phase — no shared encoder, no `sentiment → intent` dependency; a future Routing Engine composes both signals, not this module |
| BERT fine-tuning | No labelled email-domain intent data exists to fine-tune against or evaluate |
| A dedicated `INTENT_CONFIG` preprocessing config | No intent-specific preprocessing sensitivity was found this phase (unlike Sentiment's capitalization finding) — `CATEGORY_CONFIG` reused; revisit if evidence emerges |
| Calibration analysis | Given Escalation/Refund's demonstrated unreliability, a calibration study would measure noise for 2 of 9 classes — deferred, disclosed as a gap, not silently skipped |

## Engineering Gates (this phase's own Section 30) — Outcome

| Gate | Outcome |
|---|---|
| PRD requirements extracted | Done — FR-33 to FR-36 above |
| Intent taxonomy verified | Done — `docs/intent_taxonomy.md`, 2 naming collisions flagged (Escalation, Feedback) |
| Data audit completed | Done — `docs/data_audit_intent.md`, PRD's "custom annotation required" claim independently verified |
| Domain match evaluated | Done — LOW, and specifically worse for Order/Refund/Cancel than priority/category's domain mismatch |
| Label quality evaluated | Done — SYNTHETIC/keyword-heuristic, with a concrete root-caused reliability failure for Escalation |
| Human annotation requirement determined | Done — `docs/intent_labeling_strategy.md`, not yet executed |
| Single/multi-label decision documented | Done — multi-label, determined directly from PRD text, not a judgment call |
| Leakage analysis completed | Done — `docs/data_audit_intent.md` §5, deliberately NOT coupled to shared `ContentFeatures` (unlike priority/category's disclosed leakage channel) |
| Baseline strategy defined | Done — per your confirmed decision: synthetic bootstrap + trained multi-label classifier |
| Advanced model decision justified | Done — BERT not attempted, no data to justify it |
| API implemented | Done — `POST /api/v1/intent/predict` + `/feedback` |
| Database implemented | Done — `intent_prediction_logs`, verified against real Postgres incl. downgrade/upgrade round-trip |
| Alembic migration verified against real PostgreSQL | Done — 6 migrations run clean from empty DB, all tables correct |
| Feedback implemented | Done — reuses `FeedbackLogger.log_correction()` unchanged |
| Security review completed | Done — `tests/test_intent_security.py` |
| Performance benchmark completed | Partial — smoke-tested latency (2.57ms), not formally load-tested |
| Artifact compatibility verified | Done — deliberately no `FeatureSchema` coupling (nothing to fingerprint) |
| Error analysis completed | Done — `docs/error_analysis_intent.md`, found and root-caused Escalation's specific unreliability |
| Documentation completed | Done — this document + 6 others |
| All previous tests pass | Done — 180 → 214 passed (34 new), 1 skipped, zero regressions |
| New Intent tests pass | Done — 34/34, including catching and fixing a real order-ID regex bug during test-writing |
| Sentiment regression tests pass | Done — verified as part of the full 214-test run, no Sentiment file touched this phase |
| DB hang remains bounded | Done — reviewed, not re-investigated (no new information to add), same `asyncio.wait_for` pattern reused |
| Production-readiness level honestly assigned | Done — LEVEL 1, see final report |
