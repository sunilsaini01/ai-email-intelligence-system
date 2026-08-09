"""
Phase 9 — Similar Email Retrieval: TF-IDF baseline vs. all-MiniLM-L6-v2
comparison (Step 8/Step 26).

Measures what the Phase 9 brief asked for: dimension, cold/warm latency,
and a qualitative semantic-quality check on hand-written sentence pairs
with an obvious expected relationship (similar/dissimilar) -- NOT a
formal embedding-quality benchmark (no labelled STS-style dataset exists
in this project), disclosed as exactly that, not dressed up as more.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/benchmark_embedding_models.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Sentence pairs with an unambiguous EXPECTED relationship -- similar
# pairs share a topic, dissimilar pairs don't. Not a formal STS
# benchmark; a qualitative sanity check only.
PAIRS = [
    ("I want a refund for my payment.", "Please reimburse me for the charge.", "similar"),
    ("The server is down, please help.", "Our system is not responding, urgent.", "similar"),
    ("Can we schedule a call next week?", "Are you free for a meeting on Tuesday?", "similar"),
    ("I want a refund for my payment.", "The weather is beautiful today.", "dissimilar"),
    ("The server is down, please help.", "Thanks for the great presentation.", "dissimilar"),
    ("Can we schedule a call next week?", "My credit card was charged twice.", "dissimilar"),
]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _benchmark(name, embedder):
    print(f"\n=== {name} ===")
    print(f"dimension: {embedder.dimension}")
    print(f"model_version: {embedder.model_version}")

    # Cold latency (first call after construction).
    start = time.perf_counter()
    embedder.embed("This is a cold-start warmup sentence.")
    cold_ms = (time.perf_counter() - start) * 1000
    print(f"cold-start latency (first call): {cold_ms:.1f} ms")

    # Warm latency (average of 20 subsequent calls).
    start = time.perf_counter()
    for _ in range(20):
        embedder.embed("Please process my refund request as soon as possible.")
    warm_ms = (time.perf_counter() - start) / 20 * 1000
    print(f"warm latency (avg of 20 calls): {warm_ms:.2f} ms")

    # Batch latency (10 texts in one call, if supported meaningfully).
    start = time.perf_counter()
    embedder.embed_batch(["Refund request number " + str(i) for i in range(10)])
    batch_ms = (time.perf_counter() - start) * 1000
    print(f"batch latency (10 texts, one call): {batch_ms:.1f} ms ({batch_ms / 10:.2f} ms/text)")

    # Qualitative semantic-quality check.
    print("semantic quality (qualitative, hand-written pairs, NOT a formal benchmark):")
    correct = 0
    for text_a, text_b, expected in PAIRS:
        emb_a, emb_b = embedder.embed(text_a), embedder.embed(text_b)
        score = _cosine(emb_a, emb_b)
        judged = "similar" if score >= 0.3 else "dissimilar"  # HEURISTIC cutoff for this qualitative check only
        match = "OK" if judged == expected else "MISS"
        if judged == expected:
            correct += 1
        print(f"  [{match}] score={score:.3f} expected={expected:10s} '{text_a[:35]}...' vs '{text_b[:35]}...'")
    print(f"  {correct}/{len(PAIRS)} matched expectation (qualitative, n={len(PAIRS)}, not statistically meaningful)")

    return {"cold_ms": cold_ms, "warm_ms": warm_ms, "batch_ms_per_text": batch_ms / 10, "qualitative_correct": correct}


def main():
    from app.inference.minilm_embedder import MiniLmEmbedder
    from app.inference.tfidf_embedder import TfidfEmbedder

    tfidf_results = _benchmark("TF-IDF baseline", TfidfEmbedder())
    minilm_results = _benchmark("all-MiniLM-L6-v2 (via transformers)", MiniLmEmbedder())

    print("\n=== Summary ===")
    print(f"{'Metric':<30} {'TF-IDF':>15} {'MiniLM':>15}")
    print(f"{'Warm latency (ms)':<30} {tfidf_results['warm_ms']:>15.2f} {minilm_results['warm_ms']:>15.2f}")
    print(f"{'Batch latency (ms/text)':<30} {tfidf_results['batch_ms_per_text']:>15.2f} {minilm_results['batch_ms_per_text']:>15.2f}")
    print(f"{'Qualitative match (of 6)':<30} {tfidf_results['qualitative_correct']:>15} {minilm_results['qualitative_correct']:>15}")


if __name__ == "__main__":
    main()
