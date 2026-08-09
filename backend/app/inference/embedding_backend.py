"""
Protocol boundary for Module 9's embedders (Step 8 comparison: TF-IDF
baseline vs. all-MiniLM-L6-v2), mirroring every other module's
`*ClassifierBackend` Protocol. `RetrievalService` depends on this
Protocol, never on `TfidfEmbedder`/`MiniLmEmbedder` concretely -- swapping
which embedder is served is a constructor argument, not an API change.

All embedders in this codebase MUST return L2-normalized vectors (both
`TfidfEmbedder` -- sklearn's `TfidfVectorizer(norm="l2")` default -- and
`MiniLmEmbedder` -- explicit `F.normalize`) so `ChromaVectorStore`'s
cosine-space configuration produces the "dot product == cosine similarity"
identity correctly and consistently across whichever embedder is active.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingBackend(Protocol):
    dimension: int
    model_version: str

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
