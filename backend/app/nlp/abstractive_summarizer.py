"""
Abstractive summarization — off-the-shelf, NOT fine-tuned, distilled BART
(FR-28's "abstractive (T5/BART generation)" half; PRD Sec9.1 names
"Fine-tuned T5-small/BART" as the eventual production model).

Why off-the-shelf, not fine-tuned, this phase: fine-tuning needs paired
(email, reference-summary) training data. docs/data_audit_summarization.md
Gate 4 establishes that no such dataset exists — BBC News Summary is real
and human-written, but news, not email, and at the wrong summary length to
be a fine-tuning target for FR-25's 2-3-sentence shape. Fine-tuning against
the wrong domain/format would not obviously transfer better than using a
model already fine-tuned for summarization (just on a different corpus)
zero-shot — the same "don't fine-tune without data that justifies it"
discipline already applied to spam/priority/categorization's classical
baselines, extended here to the generative case.

Why sshleifer/distilbart-cnn-6-6 specifically: it IS a BART model (PRD
Sec9.1 literally names "BART generation"), already fine-tuned for
summarization (on CNN/DailyMail — a PRD-named dataset, notably, even
though this repo doesn't have that raw data itself), and distilled to ~half
the parameter count of bart-large-cnn — a meaningfully smaller memory/
latency footprint on this CPU-only environment while keeping the
architecture the PRD actually names, not a different model family entirely.

Model/dependency footprint verified directly in this environment before
committing to this design: torch 2.12.1+cpu and transformers 5.13.0 were
already installed (not via requirements.txt — see requirements.txt's
comment on this), first model load (incl. one-time weight download) took
~115s, warm inference on a ~90-word email took ~3s. See the model card
"Performance" for the full measured numbers this design decision is based on.
"""

import logging
import time
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger("app.nlp.abstractive")

MODEL_NAME = "sshleifer/distilbart-cnn-6-6"
# BART's own positional-embedding limit -- inputs longer than this are
# truncated by the tokenizer regardless of what chunking.py does upstream;
# documented here as the hard ceiling chunking.py's map-reduce strategy
# exists to work around.
MODEL_MAX_INPUT_TOKENS = 1024


@dataclass
class AbstractiveResult:
    summary: str
    model_name: str
    input_token_count: int
    was_truncated: bool
    processing_ms: float


class AbstractiveSummarizer:
    """
    Loads the model once (expensive — see module docstring's measured
    ~115s first-load cost, mirroring PriorityPredictor's "load once, reuse"
    pattern) and reuses it for every call. NOT wrapped behind the
    Protocol-backend pattern spam/priority/category use (no swappable
    classical-vs-transformer choice here — this class IS the transformer;
    a future different abstractive model would replace this class's
    internals, same as PriorityPredictor would if its classical model were
    ever replaced, without needing a second abstraction layer for a
    single-implementation seam that doesn't exist yet).
    """

    def __init__(self):
        # Deferred import: keeps `import app.nlp.abstractive_summarizer`
        # itself cheap for anything that only needs the dataclass/constants
        # (e.g. tests that check MODEL_MAX_INPUT_TOKENS without loading
        # 300MB of weights) -- same lazy-load rationale EmailPreprocessor
        # already applies to its spaCy model.
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        start = time.perf_counter()
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
        logger.info(
            "abstractive_model_loaded",
            extra={"model": MODEL_NAME, "load_ms": round((time.perf_counter() - start) * 1000, 2)},
        )

    def summarize(self, text: str, max_length: int = 60, min_length: int = 15) -> AbstractiveResult:
        start = time.perf_counter()

        inputs = self.tokenizer(
            [text],
            max_length=MODEL_MAX_INPUT_TOKENS,
            truncation=True,
            return_tensors="pt",
        )
        input_token_count = inputs["input_ids"].shape[1]
        # A second, untruncated pass just to detect truncation would double
        # tokenization cost for every call -- comparing against a rough
        # word-count proxy is cheap and only needs to be directionally
        # right (it drives a logged flag for observability, not a
        # correctness-critical decision).
        was_truncated = len(text.split()) > MODEL_MAX_INPUT_TOKENS

        summary_ids = self.model.generate(
            inputs["input_ids"],
            max_length=max_length,
            min_length=min_length,
            num_beams=4,
        )
        summary = self.tokenizer.decode(summary_ids[0], skip_special_tokens=True)

        processing_ms = round((time.perf_counter() - start) * 1000, 2)

        return AbstractiveResult(
            summary=summary.strip(),
            model_name=MODEL_NAME,
            input_token_count=int(input_token_count),
            was_truncated=was_truncated,
            processing_ms=processing_ms,
        )


@lru_cache
def get_abstractive_summarizer() -> AbstractiveSummarizer:
    return AbstractiveSummarizer()
