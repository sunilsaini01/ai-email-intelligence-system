"""
ChromaDB-backed VectorStore (Module 9 / Phase 9, Step 9/Step 34).

PRD's own §12.2 names ChromaDB for dev, Pinecone for prod -- this phase
implements the dev tier; a future `PineconeVectorStore` would implement
the same `VectorStore` Protocol without `RetrievalService` changing at
all. Runs embedded/in-process (`chromadb.PersistentClient`, a local
on-disk store, not a network service) -- no new Docker Compose service,
no new infrastructure dependency, consistent with RULE 14 (no
Kafka/Kubernetes/distributed infra without evidence). Persisted under
`artifacts/chroma/` -- alongside every other module's trained artifacts,
not a separate top-level directory, so `artifacts/` remains the one place
this project's non-code, non-data build outputs live.

Tenant isolation (Step 5 / RULE 7): `organization_id` is injected into
EVERY upsert's metadata and EVERY query's `where` filter by this class
itself, not left to the caller to remember -- defense in depth on top of
the Protocol already requiring it as a parameter (app/retrieval/
vector_store.py). There is no method on this class that can read or write
a vector without an organization_id scoping it.

Similarity metric: cosine (`hnsw:space: "cosine"` set at collection
creation) -- Chroma's default is squared L2, which would silently produce
a different ranking than the cosine-normalized embeddings this project's
embedders emit (app/inference/*_embedder.py both L2-normalize their
output). Explicit, not left to the library default. See
docs/vector_store_decision.md "Similarity Metric".
"""

from pathlib import Path

import chromadb

from app.retrieval.vector_store import VectorMatch

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PERSIST_DIR = str(_REPO_ROOT / "artifacts" / "chroma")


def _sanitize_metadata(metadata: dict) -> dict:
    """Chroma metadata values must be str/int/float/bool -- None (a
    legitimate value for e.g. `department` before Routing has run) is
    dropped rather than passed through and rejected by the client."""
    return {k: v for k, v in metadata.items() if v is not None}


class ChromaVectorStore:
    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR):
        self._client = chromadb.PersistentClient(path=persist_dir)

    def _collection(self, name: str):
        return self._client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )

    def upsert(
        self,
        collection: str,
        organization_id: str,
        vector_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        scoped_metadata = _sanitize_metadata({**metadata, "organization_id": organization_id})
        self._collection(collection).upsert(
            ids=[vector_id], embeddings=[embedding], metadatas=[scoped_metadata]
        )

    def query(
        self,
        collection: str,
        organization_id: str,
        embedding: list[float],
        top_k: int,
        where: dict | None = None,
    ) -> list[VectorMatch]:
        scoped_where = {"organization_id": organization_id}
        if where:
            # Chroma's `where` needs an explicit boolean combinator once
            # more than one condition is present -- a single-key dict
            # (just organization_id) is valid as-is.
            scoped_where = {"$and": [scoped_where, *({k: v} for k, v in where.items())]}

        result = self._collection(collection).query(
            query_embeddings=[embedding], n_results=top_k, where=scoped_where
        )

        ids = result["ids"][0] if result["ids"] else []
        distances = result["distances"][0] if result["distances"] else []
        metadatas = result["metadatas"][0] if result["metadatas"] else []

        matches = []
        for vector_id, distance, metadata in zip(ids, distances, metadatas, strict=True):
            # Chroma returns cosine DISTANCE (1 - cosine_similarity) for the
            # "cosine" space -- converted back to similarity here so every
            # VectorStore implementation returns the same "higher = more
            # similar" convention (app/retrieval/vector_store.py's
            # VectorMatch.score docstring).
            matches.append(VectorMatch(id=vector_id, score=1.0 - distance, metadata=dict(metadata)))
        return matches

    def delete(self, collection: str, organization_id: str, vector_id: str) -> None:
        # Chroma's delete() is a no-op if the id doesn't exist -- matches
        # the Protocol's idempotent-delete contract without extra handling.
        self._collection(collection).delete(
            ids=[vector_id], where={"organization_id": organization_id}
        )
