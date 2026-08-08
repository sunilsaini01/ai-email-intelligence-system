"""
Phase 6 — Email Summarization: baseline (extractive/TextRank) vs. advanced
(abstractive/distilbart-cnn-6-6) model comparison.

============================================================================
Evaluated against data/processed/summarization_bbc_v1 (BBC News Summary) --
REAL human-written summaries, WRONG domain for the PRD's actual email use
case. See docs/data_audit_summarization.md. Every metric this script
prints is a MODEL VALIDATION metric (real signal about summary quality on
formal written English), NOT a PRD-compliance metric for FR-25/26/27.
============================================================================

Uses a bounded sample of the test split, not the full 213 examples --
abstractive inference is the bottleneck (~3s/example on this CPU-only
environment, see the model card's measured "Performance" section), and a
smaller, fixed, disclosed sample is a defensible tradeoff for a baseline
comparison Step 12 explicitly asks for (quality AND latency/memory/cost),
not silently substituted for the full test set without saying so.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/evaluate_summarization_models.py

Produces:
    artifacts/summarization_model_comparison.json
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.summarization_evaluator import compute_corpus_rouge
from app.nlp.abstractive_summarizer import AbstractiveSummarizer
from app.nlp.extractive_summarizer import ExtractiveSummarizer
from app.nlp.summary_grounding import check_preservation
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger

logger = get_logger()

DATA_DIR = Path("data/processed/summarization_bbc_v1")
SAMPLE_SIZE = 40  # bounded for abstractive inference cost -- see module docstring
RANDOM_STATE = 42


def load_test_sample(n: int) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / "test.parquet")
    logger.info("Loaded %d test rows, sampling %d", len(df), n)
    return df.sample(n=min(n, len(df)), random_state=RANDOM_STATE).reset_index(drop=True)


def evaluate_extractive(df: pd.DataFrame) -> dict:
    summarizer = ExtractiveSummarizer()

    candidates = []
    latencies_ms = []
    preservation_rates = []

    for _, row in df.iterrows():
        start = time.perf_counter()
        # max_sentences=5, not FR-25's default 3 -- BBC's reference summaries
        # are far longer than FR-25's target (docs/data_audit_summarization.md
        # §4), so scoring against them with a 3-sentence extract would
        # conflate "wrong length for this benchmark" with "wrong content" in
        # the ROUGE score. The email-facing service (Step 6/api) still
        # defaults to FR-25's 2-3 sentences -- this eval-only parameter
        # choice is about fair comparison against BBC's reference length,
        # not a change to the production default.
        summary = summarizer.summarize(row["body_text_raw"], max_sentences=5)
        latencies_ms.append((time.perf_counter() - start) * 1000)
        candidates.append(summary)

        report = check_preservation(row["body_text_raw"], summary)
        if report.preservation_rate is not None:
            preservation_rates.append(report.preservation_rate)

    rouge = compute_corpus_rouge(df["summary_reference"].tolist(), candidates)

    return {
        "model": "extractive_textrank",
        "rouge": rouge,
        "avg_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2),
        "p95_latency_ms": round(sorted(latencies_ms)[int(len(latencies_ms) * 0.95)], 2),
        "avg_entity_preservation_rate": (
            round(sum(preservation_rates) / len(preservation_rates), 4) if preservation_rates else None
        ),
        "n_examples_with_entities": len(preservation_rates),
        "sample_candidates": candidates[:3],
    }


def evaluate_abstractive(df: pd.DataFrame) -> dict:
    summarizer = AbstractiveSummarizer()

    candidates = []
    latencies_ms = []
    preservation_rates = []
    truncated_count = 0

    for _, row in df.iterrows():
        result = summarizer.summarize(row["body_text_raw"], max_length=100, min_length=25)
        latencies_ms.append(result.processing_ms)
        candidates.append(result.summary)
        if result.was_truncated:
            truncated_count += 1

        report = check_preservation(row["body_text_raw"], result.summary)
        if report.preservation_rate is not None:
            preservation_rates.append(report.preservation_rate)

    rouge = compute_corpus_rouge(df["summary_reference"].tolist(), candidates)

    return {
        "model": "abstractive_distilbart_cnn_6_6",
        "rouge": rouge,
        "avg_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2),
        "p95_latency_ms": round(sorted(latencies_ms)[int(len(latencies_ms) * 0.95)], 2),
        "avg_entity_preservation_rate": (
            round(sum(preservation_rates) / len(preservation_rates), 4) if preservation_rates else None
        ),
        "n_examples_with_entities": len(preservation_rates),
        "n_truncated_inputs": truncated_count,
        "sample_candidates": candidates[:3],
    }


def main():
    df = load_test_sample(SAMPLE_SIZE)

    logger.info("Evaluating extractive (TextRank) baseline...")
    extractive_result = evaluate_extractive(df)

    logger.info("Evaluating abstractive (distilbart-cnn-6-6)...")
    abstractive_result = evaluate_abstractive(df)

    print("\n================ SUMMARIZATION MODEL COMPARISON (BBC News Summary test sample, n=%d) ================\n" % len(df))
    comparison_table = pd.DataFrame(
        [
            {
                "model": r["model"],
                "rouge1_f": r["rouge"]["rouge1_f"],
                "rouge2_f": r["rouge"]["rouge2_f"],
                "rougeL_f": r["rouge"]["rougeL_f"],
                "avg_latency_ms": r["avg_latency_ms"],
                "p95_latency_ms": r["p95_latency_ms"],
                "avg_entity_preservation_rate": r["avg_entity_preservation_rate"],
            }
            for r in (extractive_result, abstractive_result)
        ]
    )
    print(comparison_table.to_string(index=False))

    rouge_l_target = 0.38  # PRD Milestone 3 (end Phase 7) -- reference only, not this phase's bar
    print(
        f"\n[INFO] PRD Milestone 3 reference target: ROUGE-L > {rouge_l_target} (fine-tuned model, "
        "end of Phase 7). NOT this phase's bar -- these are off-the-shelf models on an off-domain "
        "dataset. See docs/data_audit_summarization.md and docs/model_cards/email_summarization.md."
    )

    artifact_manager = ArtifactManager()
    artifact_manager.save_json(
        {
            "evaluated_at": datetime.now(UTC).isoformat(),
            "dataset": "summarization_bbc_v1",
            "sample_size": len(df),
            "extractive": extractive_result,
            "abstractive": abstractive_result,
            "SYNTHETIC_DATA": False,
            "PRD_COMPLIANT": False,
            "warning": (
                "Evaluated against BBC News Summary -- real, human-written summaries, but news "
                "articles, not email, and at a length that doesn't match FR-25. These are MODEL "
                "VALIDATION metrics (real quality signal, off-domain), not PRD-compliance evidence. "
                "See docs/data_audit_summarization.md."
            ),
        },
        "summarization_model_comparison.json",
    )


if __name__ == "__main__":
    main()
