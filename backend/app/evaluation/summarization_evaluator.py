"""
Summarization evaluation — ROUGE-1/2/L against human-written reference
summaries (PRD Sec14.1's named primary/secondary metrics for Module 5,
minus BERTScore — see docs/phase6_requirements_traceability.md for why
BERTScore is a disclosed gap this phase, not silently skipped).

Why a separate file from model_evaluator.py: ROUGE has no relationship to
sklearn's classification metrics that file already wraps (no
predict/predict_proba, no confusion matrix, no label space) — same
reasoning evaluate_multilabel_model() got its own function rather than a
branch of evaluate_model(), taken one step further here because even the
INPUT SHAPE differs (pairs of (reference, candidate) strings, not
(y_true, y_pred) label arrays).

ROUGE's limitations (documented here, not just asserted in the model
card): it measures n-gram / longest-common-subsequence overlap with a
reference — a summary can score well by reusing the reference's exact
words while being factually wrong (rouge doesn't check truth), and can
score poorly while being an excellent summary that just phrases things
differently (rouge doesn't understand paraphrase). It is a proxy for
quality, not quality itself — this is exactly why
app/nlp/summary_grounding.py's entity-preservation check exists alongside
it: ROUGE alone cannot answer FR-26's actual question ("were the dates/
amounts/names preserved"), only a lexical-overlap approximation of it.
"""

from dataclasses import dataclass

from rouge_score import rouge_scorer


@dataclass
class RougeScores:
    rouge1_f: float
    rouge2_f: float
    rougeL_f: float


def compute_rouge(reference: str, candidate: str) -> RougeScores:
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    scores = scorer.score(reference, candidate)
    return RougeScores(
        rouge1_f=round(scores["rouge1"].fmeasure, 4),
        rouge2_f=round(scores["rouge2"].fmeasure, 4),
        rougeL_f=round(scores["rougeL"].fmeasure, 4),
    )


def compute_corpus_rouge(references: list[str], candidates: list[str]) -> dict:
    """
    Averages per-example F-measures across a corpus — the standard way
    ROUGE is reported at corpus scale (PRD Sec14.1's "ROUGE-L" target is a
    corpus-level number, not a per-example one).
    """
    if len(references) != len(candidates):
        raise ValueError(
            f"references ({len(references)}) and candidates ({len(candidates)}) must be equal length"
        )
    if not references:
        raise ValueError("cannot compute corpus ROUGE over zero examples")

    per_example = [compute_rouge(ref, cand) for ref, cand in zip(references, candidates, strict=True)]

    n = len(per_example)
    return {
        "rouge1_f": round(sum(s.rouge1_f for s in per_example) / n, 4),
        "rouge2_f": round(sum(s.rouge2_f for s in per_example) / n, 4),
        "rougeL_f": round(sum(s.rougeL_f for s in per_example) / n, 4),
        "n_examples": n,
    }
