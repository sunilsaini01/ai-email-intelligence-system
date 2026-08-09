"""
all-MiniLM-L6-v2 embedder, loaded via raw `transformers`
(AutoTokenizer/AutoModel + manual mean-pooling), deliberately NOT via the
`sentence-transformers` package.

Why: `sentence-transformers==5.6.0` segfaults on import in this
environment (verified directly with Python's faulthandler -- the crash is
inside sentence-transformers' own `base/model_card.py` import chain, not
in `torch`, which imports and runs fine standalone). `transformers` is
already a proven, working dependency in this codebase (Phase 6's
abstractive summarizer). Loading the same published weights
(`sentence-transformers/all-MiniLM-L6-v2` on the Hugging Face Hub) through
`transformers` directly and mean-pooling the token embeddings ourselves is
the standard, well-documented way to reproduce sentence-transformers'
output without the wrapper package -- verified empirically before this
file was written: sim(refund, reimburse)=0.56, sim(refund, weather)=-0.03
on a smoke test, the semantically sane result. See
docs/embedding_model_decision.md.

Lazy-loaded (constructed on first use, not at import time) -- same
reasoning as AbstractiveSummarizer's lazy load (app/nlp/
abstractive_summarizer.py): downloading/loading transformer weights is a
real, measured cost that shouldn't land on module import.
"""

import time

import torch

HF_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_VERSION = "all-MiniLM-L6-v2-via-transformers-v1"
DIMENSION = 384


def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed = (last_hidden_state * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


class MiniLmEmbedder:
    def __init__(self):
        from transformers import AutoModel, AutoTokenizer

        self.dimension = DIMENSION
        self.model_version = MODEL_VERSION
        self._tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_NAME)
        self._model = AutoModel.from_pretrained(HF_MODEL_NAME)
        self._model.eval()

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        with torch.no_grad():
            encoded = self._tokenizer(
                texts, padding=True, truncation=True, max_length=256, return_tensors="pt"
            )
            output = self._model(**encoded)
            pooled = _mean_pool(output.last_hidden_state, encoded["attention_mask"])
            normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return normalized.tolist()


def measure_embed_latency_ms(embedder: "MiniLmEmbedder", text: str) -> float:
    """Used by the Step 26 performance benchmark script -- not called in
    the request path."""
    start = time.perf_counter()
    embedder.embed(text)
    return (time.perf_counter() - start) * 1000
