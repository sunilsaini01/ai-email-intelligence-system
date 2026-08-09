# Vector Store Decision (Module 9 / Phase 9, Step 9/Step 34)

## Decision: ChromaDB, Behind a `VectorStore` Protocol

The PRD names ChromaDB for dev, Pinecone for prod (§12.2). This phase
implements the dev tier, followed the PRD rather than deviating without
reason, and — per RULE 2 — does **not** call Chroma directly from
`RetrievalService`. `app/retrieval/vector_store.py:VectorStore` is a
`Protocol` (`upsert`/`query`/`delete`, `organization_id` required on
every method); `ChromaVectorStore` (`app/retrieval/chroma_vector_store.py`)
is one implementation. A future `PineconeVectorStore` would satisfy the
same Protocol without `RetrievalService` changing at all — the same
dependency-inversion boundary every `*ClassifierBackend` Protocol already
establishes for this codebase's ML modules.

## Comparison

| | Chroma | Pinecone | FAISS | Qdrant |
|---|---|---|---|---|
| Deployment | Embedded/local (no server) | Managed cloud, API key required | Embedded library, no metadata filtering built in | Server (Docker) or embedded |
| Cost | Free, local disk | Paid, usage-based | Free | Free (self-hosted) |
| Metadata filtering | Yes, native `where` | Yes | No (would need a parallel metadata store) | Yes |
| New infrastructure required | **None** — runs in-process, persisted to `artifacts/chroma/` | An external account/API key (explicitly what the user asked to be told about before any implementation) | None | A new Docker Compose service |
| PRD alignment | Named for dev | Named for prod, not this phase | Not named | Not named |

**Chosen: Chroma.** No new Docker service, no API key, no external
account — directly answers "no paid API required" (confirmed with the
user before implementation began). Runs via `chromadb.PersistentClient`,
persisted under `artifacts/chroma/` (alongside every other module's
trained artifacts, not a new top-level directory).

FAISS was not chosen despite being dependency-light because it has no
native metadata filtering — FR-46 requires category/department/
resolution-status filtering, which would mean building and maintaining a
parallel metadata index by hand. Qdrant was not chosen because it requires
a new Docker Compose service, which RULE 14 explicitly cautions against
absent evidence Chroma can't do the job (it can, at this project's current
scale).

## Similarity Metric

**Cosine similarity**, explicit, not the library default. Chroma's
default distance for a new collection is squared L2 (Euclidean); this
project's embedders (`TfidfEmbedder`, `MiniLmEmbedder`) both emit
L2-normalized vectors, for which cosine similarity is the metric that
matches how "similar" was defined when those vectors were produced.
Configured explicitly at collection creation
(`metadata={"hnsw:space": "cosine"}`,
`ChromaVectorStore._collection()`) — verified, not assumed, that Chroma
respects this rather than silently using its default.

Chroma's native query returns cosine **distance** (`1 - similarity`) for
this space; `ChromaVectorStore.query()` converts back to similarity
(`score = 1.0 - distance`) so every `VectorStore` implementation
(`InMemoryVectorStore` included) returns the same "higher = more similar"
convention — verified by `tests/test_retrieval_vector_store.py`'s shared
contract test, run against both implementations.

**Score is NOT a probability** (RULE 5) — documented directly on
`SimilarEmailMatch.score` in `app/schemas/retrieval.py`, and not
comparable across different `embedding_model` values (a MiniLM cosine
score and a TF-IDF cosine score are not on a shared scale) — every
response carrying a score also carries `embedding_model` so a caller can
tell whether two scores are comparable.

## Docker / Local Development (Step 34)

**No new Docker Compose service.** `chromadb.PersistentClient` runs
embedded, in the same process as the FastAPI app, writing to local disk
(`artifacts/chroma/`) — the current stack (`FastAPI` + `PostgreSQL`) is
unchanged. This is a deliberate choice consistent with RULE 14 (no new
infrastructure without evidence it's needed) and this project's modular-
monolith architecture (`docs/architecture.md`'s Phase 1 decision, still
the right call at this project's current scale).
