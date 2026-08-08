# Phase 6 — Email Summarization: Requirements Traceability

Extracted directly from `project document/PRD_AI_Email_Intelligence_System.md`.
No requirement below was invented — every row cites its PRD source line.
Design/Implementation/Test/Evidence columns are filled in as this phase
progresses; a blank cell means "not yet built," not "not applicable."

## Functional Requirements (PRD §5, Module 5)

| PRD Requirement | Design | Implementation | Test | Evidence |
|---|---|---|---|---|
| **FR-25**: "System shall generate a 2–3 sentence summary for emails longer than 200 words" | `SummarizationService` checks word count; emails ≤200 words are returned with a `skipped_short_input` flag instead of forced through the model (per Step 6 "empty/short-input behavior" — forcing a "summary" of something already short is not useful and risks the model inventing content to fill a minimum length) | `app/services/summarization_service.py` | `test_summarization_endpoint.py::test_short_email_is_not_forced_through_model` | See model card "Intended Use" |
| **FR-26**: "Summaries shall preserve: key names, dates, monetary amounts, and action items" | Preservation is measured, not assumed: a regex-based entity extractor (reusing `app/feature_engineering/patterns.py`'s `CURRENCY_PATTERN`, plus new date/name patterns) runs on both source and summary; the response includes which source entities survived into the summary, so a caller (and this report) can see preservation rate as a number, not a claim | `app/nlp/summary_grounding.py` | `test_summary_grounding.py` | Model card "Entity Preservation" — measured, not assumed, rate reported honestly including misses |
| **FR-27**: "System shall summarize an entire email thread as a cohesive narrative, not per-message" | `ThreadSummarizer` concatenates messages in chronological order, strips re-quoted prior messages (each reply's quoted-parent block is redundant with the parent message already in the thread — `EmailPreprocessor`'s `remove_quoted_replies` already does exactly this per-message), then summarizes the deduplicated narrative as one unit, not N per-message summaries merged | `app/nlp/thread_summarizer.py` | `test_thread_summarizer.py` | Architecture doc "Thread Handling" |
| **FR-28**: "System shall support both extractive (key sentence selection) and abstractive (T5/BART generation) summarization" | Both implemented and independently selectable via `summary_type` request field; extractive = TextRank sentence ranking (PRD §9.1's own named baseline), abstractive = off-the-shelf `sshleifer/distilbart-cnn-6-6` (a distilled BART model — satisfies "BART generation" without requiring a fine-tune this phase, see Gate 4 / data audit for why fine-tuning isn't justified) | `app/nlp/extractive_summarizer.py`, `app/nlp/abstractive_summarizer.py` | `test_extractive_summarizer.py`, `test_abstractive_summarizer.py` | Model selection report in model card |

## Non-Functional Requirements

| PRD Requirement | Source | Design | Evidence |
|---|---|---|---|
| Latency: P50 < 2s, P95 < 4s, hard limit 8s | PRD §6.1 | Measured separately for extractive (expected sub-100ms — no transformer inference) and abstractive (transformer inference — the actual bottleneck) paths; hard limit enforced via request timeout | Model card "Performance" |
| Evaluation: **ROUGE-L + BERTScore** primary, ROUGE-1/ROUGE-2/Human Eval secondary, **BERTScore > 0.85** | PRD §14.1 | ROUGE-1/2/L implemented (`rouge-score` package, added to `requirements-dev.txt`). **BERTScore NOT implemented this phase** — see "Known Gaps": it requires downloading a second large model (`roberta-large` by default, ~1.4GB) purely for evaluation, an infrastructure cost not clearly justified when ROUGE already gives a directionally consistent signal for this phase's baseline-vs-off-the-shelf-model comparison; flagged as a gap, not silently skipped | `docs/model_cards/email_summarization.md` "Evaluation" |
| Milestone 3 target: ROUGE-L > 0.38, BERTScore > 0.83 | PRD §17, "Milestone 3 — Full NLP Pipeline (End Phase 7)" | **Not this phase's target.** Milestone 3 is explicitly scheduled for end of Phase 7, one phase later than this one, and assumes a *fine-tuned* T5-small/BART — this phase evaluates an off-the-shelf model, consistent with the "baseline before fine-tuning" precedent already set by spam/priority/categorization. Reported for reference, not claimed as met or as this phase's bar | Model card |
| Data (PRD §8.1): CNN/DailyMail (300K), XSum (227K), HuggingFace Datasets, MIT license | PRD §8.1 | **Neither exists in this repository.** See `docs/data_audit_summarization.md` for what does exist (BBC News Summary, a Phase 2 EDA artifact) and the resulting data strategy decision | `docs/data_audit_summarization.md` |
| Architecture (PRD §9.1): baseline TextRank (extractive), production fine-tuned T5-small/BART | PRD §9.1 | TextRank baseline built; abstractive uses an off-the-shelf (not fine-tuned) BART-family model this phase | Model card "Why This Approach" |

## Explicitly Not Implemented This Phase (and why)

| PRD reference | Why deferred |
|---|---|
| `GET /emails/{id}/summary`, full `email_classifications.summary` column (PRD §12.1, §13.2) | Same reason spam/priority/category all stand alone: no `emails` table exists yet (Module 1 — email ingestion — hasn't been built). This phase ships its own standalone `summary_logs` table, same migration path as the other three modules. |
| Integration into the aggregate multi-agent pipeline response (PRD §11, the `total_processing_ms`/`routing`/`similar_emails` combined JSON example) | That response blends Category + Intent + Sentiment + Summary + Routing — most of those modules don't exist yet (Sentiment: Phase 7, Intent: Phase 7, Routing: later). Out of scope for a single module's phase, same reasoning already applied when Priority and Categorization shipped standalone. |
| BERTScore evaluation | See Non-Functional Requirements table above — infrastructure cost not justified this phase, documented as a gap. |
| Fine-tuning T5-small/BART on domain data | No email-summary paired dataset exists to fine-tune against (see Gate 4 / data audit) — fine-tuning on the wrong domain (news) would not obviously transfer better than using an already-summarization-tuned off-the-shelf model zero-shot. |
