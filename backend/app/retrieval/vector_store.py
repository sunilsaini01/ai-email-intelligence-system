"""
Vector-store abstraction (Module 9 / Phase 9, Step 9).

`RetrievalService` depends on the `VectorStore` Protocol, never on Chroma
directly -- the same dependency-inversion boundary every ML module's
`*ClassifierBackend` Protocol already establishes
(app/inference/classifier_backend.py etc.). `ChromaVectorStore`
(chroma_vector_store.py) is the real implementation; `InMemoryVectorStore`
below is a pure-Python fake for tests that want to exercise
`RetrievalService`'s own logic (filtering, top-K, tenant scoping) without
depending on chromadb's specific behavior -- mirroring how RoutingService's
tests use duck-typed fake services rather than real trained models.

`organization_id` is a REQUIRED positional argument on every method, not
optional -- see app/retrieval/tenant.py for why: there is no code path
that can query or write a vector without stating which tenant it belongs
to, so cross-tenant leakage would require a bug at every call site
simultaneously, not a single missed check.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float  # cosine similarity -- see docs/vector_store_decision.md "Similarity Metric". NOT a probability.
    metadata: dict


class VectorStore(Protocol):
    def upsert(
        self,
        collection: str,
        organization_id: str,
        vector_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        """Insert or overwrite the vector at `vector_id` -- idempotent by
        construction (same vector_id twice = one stored vector, not two)."""
        ...

    def query(
        self,
        collection: str,
        organization_id: str,
        embedding: list[float],
        top_k: int,
        where: dict | None = None,
    ) -> list[VectorMatch]:
        """Top-K by cosine similarity, always scoped to `organization_id`
        first (never a global search), then to `where` if given."""
        ...

    def delete(self, collection: str, organization_id: str, vector_id: str) -> None:
        """No-op (not an error) if `vector_id` doesn't exist -- matches
        idempotent-delete semantics used elsewhere in this codebase."""
        ...


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore:
    """Pure-Python VectorStore fake -- no chromadb dependency, no disk I/O.
    Deliberately simple (linear scan, not HNSW) since it exists for
    correctness testing of RetrievalService's own logic, not for
    performance testing (that's ChromaVectorStore's job)."""

    def __init__(self):
        # {(collection, organization_id): {vector_id: (embedding, metadata)}}
        self._store: dict[tuple[str, str], dict[str, tuple[list[float], dict]]] = {}

    def upsert(
        self,
        collection: str,
        organization_id: str,
        vector_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        key = (collection, organization_id)
        self._store.setdefault(key, {})[vector_id] = (embedding, metadata)

    def query(
        self,
        collection: str,
        organization_id: str,
        embedding: list[float],
        top_k: int,
        where: dict | None = None,
    ) -> list[VectorMatch]:
        key = (collection, organization_id)
        candidates = self._store.get(key, {})

        matches = []
        for vector_id, (stored_embedding, metadata) in candidates.items():
            if where and any(metadata.get(k) != v for k, v in where.items()):
                continue
            score = _cosine_similarity(embedding, stored_embedding)
            matches.append(VectorMatch(id=vector_id, score=score, metadata=metadata))

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:top_k]

    def delete(self, collection: str, organization_id: str, vector_id: str) -> None:
        key = (collection, organization_id)
        self._store.get(key, {}).pop(vector_id, None)
