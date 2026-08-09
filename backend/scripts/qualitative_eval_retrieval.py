"""
Phase 9 — Similar Email Retrieval: QUALITATIVE / EXPLORATORY evaluation
(Step 21/22/23).

============================================================================
NOT GROUND TRUTH, NOT A RETRIEVAL-QUALITY MEASUREMENT IN THE STATISTICAL
SENSE. A small (15-email corpus, 5-query) hand-written, author-labelled
gold set -- same role and same "qualitative diagnostic, not a trustworthy
metric" caveat as qualitative_eval_intent.py/qualitative_eval_sentiment.py/
qualitative_eval_routing.py. No real retrieval-outcome ground truth exists
anywhere in this project (confirmed by repository audit before this phase
began) -- this script does NOT fabricate one; it documents a small,
author-curated set with disclosed sampling method (topic-cluster coverage,
not randomly sampled from real traffic, which doesn't exist) and computes
Recall@5/Precision@5 against THAT set only. Run with BOTH embedders to
give the Phase 8-style "docs/error_analysis_routing.md"-equivalent honest
comparison for this module. See docs/error_analysis_retrieval.md.
============================================================================

Run from the repo root (requires artifacts/tfidf_embedder.joblib and
network access for all-MiniLM-L6-v2's first download):
    PYTHONPATH=backend python backend/scripts/qualitative_eval_retrieval.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval.vector_store import InMemoryVectorStore
from app.services.retrieval_service import RetrievalService

# (id, subject, body, category, department, topic_cluster) -- topic_cluster
# is the author's own relevance-grouping judgment, used as ground truth for
# this qualitative set only.
CORPUS = [
    ("c1", "Refund request", "I want a refund for my last payment, please charge back my account.", "Billing", "Billing", "billing"),
    ("c2", "Billing issue", "This charge on my invoice is wrong, please reimburse me.", "Billing", "Billing", "billing"),
    ("c3", "Payment question", "Can you confirm my account balance and last payment?", "Billing", "Billing", "billing"),
    ("c4", "VPN not working", "My VPN access stopped working after the password reset.", "IT", "IT", "it_access"),
    ("c5", "Can't log in", "I am locked out of my account, please help me reset my password.", "IT", "IT", "it_access"),
    ("c6", "Server down", "The internal server is down, this is affecting the whole team.", "IT", "IT", "it_outage"),
    ("c7", "Workplace complaint", "I need to report a workplace harassment complaint regarding my manager.", "HR", "HR", "hr_complaint"),
    ("c8", "Benefits question", "Can you tell me about my health benefits enrollment?", "HR", "HR", "hr_benefits"),
    ("c9", "Pricing inquiry", "Can you send me a quote for the enterprise plan?", "Sales", "Sales", "sales"),
    ("c10", "Demo request", "We are evaluating your product, can we schedule a demo?", "Sales", "Sales", "sales"),
    ("c11", "Meeting request", "Are you available for a call next Tuesday to discuss the proposal?", "Support", "Support", "scheduling"),
    ("c12", "Reschedule", "Can we move our meeting to Thursday instead?", "Support", "Support", "scheduling"),
    ("c13", "Contract review", "Legal has flagged a compliance issue in the data processing agreement.", "Legal", "Legal", "legal"),
    ("c14", "NDA request", "Please send over the updated non-disclosure agreement.", "Legal", "Legal", "legal"),
    ("c15", "Newsletter", "Thanks for subscribing to our monthly product newsletter.", "Marketing", "Marketing", "marketing"),
]

# (query subject, query body, expected_relevant_ids)
QUERIES = [
    ("Charged twice", "I was charged twice for the same subscription, please refund me.", {"c1", "c2", "c3"}),
    ("Locked out", "I cannot access my account, my password isn't working.", {"c4", "c5"}),
    ("System outage", "Our systems are not responding, please investigate urgently.", {"c6", "c4", "c5"}),
    ("Schedule a call", "Could we set up a meeting sometime next week?", {"c11", "c12"}),
    ("Legal document", "Can I get a copy of the confidentiality agreement?", {"c13", "c14"}),
]

TOP_K = 5


def _recall_precision_at_k(retrieved_ids, expected_ids, k):
    retrieved_top_k = retrieved_ids[:k]
    hits = len(set(retrieved_top_k) & expected_ids)
    recall = hits / len(expected_ids) if expected_ids else 0.0
    precision = hits / len(retrieved_top_k) if retrieved_top_k else 0.0
    return recall, precision


def _evaluate(name, embedder):
    print(f"\n=== {name} ===")
    service = RetrievalService(embedder=embedder, vector_store=InMemoryVectorStore())

    for email_id, subject, body, category, department, _cluster in CORPUS:
        service.index_email(email_id, subject, body, category, department)

    recalls, precisions = [], []
    for query_subject, query_body, expected_ids in QUERIES:
        result = service.search(subject=query_subject, body=query_body, top_k=TOP_K)
        retrieved_ids = [m["content_hash"] for m in result["matches"]]
        recall, precision = _recall_precision_at_k(retrieved_ids, expected_ids, TOP_K)
        recalls.append(recall)
        precisions.append(precision)
        print(
            f"  Query: '{query_subject}' -> retrieved={retrieved_ids} "
            f"expected={sorted(expected_ids)} recall@{TOP_K}={recall:.2f} precision@{TOP_K}={precision:.2f}"
        )

    avg_recall = sum(recalls) / len(recalls)
    avg_precision = sum(precisions) / len(precisions)
    print(f"  Mean Recall@{TOP_K} = {avg_recall:.2f}, Mean Precision@{TOP_K} = {avg_precision:.2f} "
          f"(qualitative, n={len(QUERIES)} queries -- not statistically meaningful)")
    return avg_recall, avg_precision


def main():
    from app.inference.tfidf_embedder import TfidfEmbedder

    tfidf_recall, tfidf_precision = _evaluate("TF-IDF baseline", TfidfEmbedder())

    try:
        from app.inference.minilm_embedder import MiniLmEmbedder

        minilm_recall, minilm_precision = _evaluate("all-MiniLM-L6-v2", MiniLmEmbedder())
    except Exception as e:
        print(f"\nMiniLM evaluation skipped (network/model unavailable): {e}")
        minilm_recall = minilm_precision = None

    print("\n=== Summary (qualitative gold set, n=5 queries, 15-email corpus) ===")
    print(f"{'Metric':<20} {'TF-IDF':>10} {'MiniLM':>10}")
    print(f"{'Mean Recall@5':<20} {tfidf_recall:>10.2f} {minilm_recall if minilm_recall is None else f'{minilm_recall:.2f}':>10}")
    print(f"{'Mean Precision@5':<20} {tfidf_precision:>10.2f} {minilm_precision if minilm_precision is None else f'{minilm_precision:.2f}':>10}")


if __name__ == "__main__":
    main()
