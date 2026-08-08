# data/dataset_registry.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class DatasetEntry:
    name: str
    version: str
    source_url: str
    local_path: str
    license: str
    size_approx: str
    tasks: list[str]              # Which ML tasks it's used for
    domain_match: str             # 'high' | 'medium' | 'low' | 'very_low'
    trust_level: str              # 'primary' | 'supplementary' | 'baseline_only' | 'synthetic_bootstrap'
    known_issues: list[str]
    preprocessing_script: str     # Path to the loading/cleaning script
    checksum_sha256: Optional[str] = None  # For reproducibility verification

REGISTRY: dict[str, DatasetEntry] = {
    "spamassassin": DatasetEntry(
        name="SpamAssassin Public Corpus",
        version="20030228",
        source_url="https://spamassassin.apache.org/old/publiccorpus/",
        local_path="data/raw/spamassassin/",
        license="Apache 2.0",
        size_approx="6,047 emails",
        tasks=["spam_detection"],
        domain_match="low",
        trust_level="baseline_only",
        known_issues=[
            "2002-2006 spam patterns only — modern spam evasion not represented",
            "Hard ham subset critical for FP reduction — do not skip",
            "Class imbalance: ~67% ham / ~33% spam",
        ],
        preprocessing_script="src/data/loaders/spamassassin_loader.py",
    ),

    "enron": DatasetEntry(
        name="Enron Email Dataset",
        version="kaggle-v1",
        source_url="https://www.kaggle.com/datasets/wcukierski/enron-email-dataset",
        local_path="data/raw/enron/",
        license="Research use only",
        size_approx="~500,000 emails",
        tasks=["spam_detection", "email_categorization", "rag_retrieval"],
        domain_match="medium",
        trust_level="supplementary",
        known_issues=[
            "2001-2002 data — significant domain shift from 2026 enterprise email",
            "~5-8% duplicate emails — deduplication required before any use",
            "Real PII present — apply Presidio before any analysis",
            "X-Folder labels are noisy weak supervision, not ground truth",
            "Energy sector jargon — domain-specific vocabulary not in general corpora",
        ],
        preprocessing_script="src/data/loaders/enron_loader.py",
    ),

    "sms_spam": DatasetEntry(
        name="SMS Spam Collection",
        version="v1",
        source_url="https://archive.ics.uci.edu/ml/datasets/SMS+Spam+Collection",
        local_path="data/raw/sms_spam/",
        license="CC BY 4.0",
        size_approx="5,574 messages",
        tasks=["spam_detection"],
        domain_match="very_low",
        trust_level="supplementary",
        known_issues=[
            "SMS, not email — fundamentally different format and length",
            "2007-2012 spam patterns — outdated",
            "No metadata — header features unavailable",
            "Use only for body text spam signal transfer",
        ],
        preprocessing_script="src/data/loaders/sms_spam_loader.py",
    ),

    "amazon_polarity": DatasetEntry(
        name="Amazon Reviews Polarity",
        version="2015",
        source_url="https://huggingface.co/datasets/amazon_polarity",
        local_path="data/external/amazon_polarity/",
        license="Open",
        size_approx="3.6M reviews",
        tasks=["sentiment_analysis"],
        domain_match="low",
        trust_level="supplementary",
        known_issues=[
            "Product reviews ≠ business email tone or targets",
            "Binary polarity only — no 5-class sentiment or emotion",
            "Use for Stage 1 pre-training only, then fine-tune on enterprise email",
            "Sample to 100K max for initial experiments — full 3.6M rarely needed",
        ],
        preprocessing_script="src/data/loaders/amazon_loader.py",
    ),

    "cnn_dailymail": DatasetEntry(
        name="CNN / DailyMail",
        version="3.0.0",
        source_url="https://huggingface.co/datasets/cnn_dailymail",
        local_path="data/external/cnn_dailymail/",
        license="MIT",
        size_approx="300,000 article-summary pairs",
        tasks=["summarization"],
        domain_match="low",
        trust_level="supplementary",
        known_issues=[
            "News articles, not email — structure and register differ significantly",
            "Highlights-style summaries differ from action-oriented email summaries",
            "Fine-tune further on 300-500 annotated email summaries after this",
        ],
        preprocessing_script="src/data/loaders/cnn_dm_loader.py",
    ),

    "priority_synthetic_v1": DatasetEntry(
        name="Priority Classification — Synthetic Bootstrap (Enron-sourced)",
        version="v1-synthetic",
        source_url="https://www.kaggle.com/datasets/wcukierski/enron-email-dataset",
        local_path="data/processed/priority_synthetic_v1/",
        license="Research use only (inherited from Enron)",
        size_approx="see run_metadata.json written alongside the parquet output",
        tasks=["priority_classification"],
        domain_match="low",
        trust_level="synthetic_bootstrap",
        known_issues=[
            "NOT PRD-compliant — no human ever assigned these labels. See "
            "docs/data_audit_priority.md for the full data strategy decision.",
            "Labels are generated by the same keyword heuristic "
            "(backend/app/feature_engineering/priority_keywords.py) that also "
            "feeds the model's own features — a structural leakage channel, "
            "not a sampling artifact. Metrics from this dataset are pipeline "
            "validation only, never business-readiness evidence.",
            "Inherits every Enron limitation already listed under 'enron' above "
            "(2001-2002 domain shift, PII present, energy-sector jargon).",
            "Must be replaced by real annotated data (Option A, "
            "docs/data_audit_priority.md §4) before any production claim.",
        ],
        preprocessing_script="backend/scripts/generate_synthetic_priority_dataset.py",
    ),

    "category_synthetic_v1": DatasetEntry(
        name="Email Categorization — Synthetic Bootstrap (Enron-sourced)",
        version="v1-synthetic",
        source_url="https://www.kaggle.com/datasets/wcukierski/enron-email-dataset",
        local_path="data/processed/category_synthetic_v1/",
        license="Research use only (inherited from Enron)",
        size_approx="see run_metadata.json written alongside the parquet output",
        tasks=["email_categorization"],
        domain_match="low",
        trust_level="synthetic_bootstrap",
        known_issues=[
            "NOT PRD-compliant — no human ever assigned these labels. See "
            "docs/data_audit_categorization.md for the full data strategy decision.",
            "Labels are multi-label and generated by the same keyword heuristic "
            "(backend/app/feature_engineering/category_keywords.py) that also "
            "feeds the model's own ContentFeatures — a structural leakage channel, "
            "not a sampling artifact. Metrics from this dataset are pipeline "
            "validation only, never business-readiness evidence.",
            "Enron's X-Folder header was evaluated as a candidate weak-supervision "
            "signal and rejected — it's personal mailbox organization (Sent Items, "
            "Deleted Items, counterparty names), not a business-department taxonomy. "
            "See docs/data_audit_categorization.md §2.2 for the direct evidence.",
            "Inherits every Enron limitation already listed under 'enron' above "
            "(2001-2002 domain shift, PII present, energy-sector jargon).",
            "Must be replaced by real annotated data (Option A, "
            "docs/data_audit_categorization.md §4 / "
            "docs/annotation_guidelines_categorization.md) before any production claim.",
        ],
        preprocessing_script="backend/scripts/generate_synthetic_category_dataset.py",
    ),

    "summarization_bbc_v1": DatasetEntry(
        name="BBC News Summary (email-summarization evaluation proxy)",
        version="v1",
        source_url="http://mlg.ucd.ie/datasets/bbc.html",
        local_path="data/processed/summarization_bbc_v1/",
        license="Research/academic use (standard for this widely-used benchmark)",
        size_approx="2,127 unique article/summary pairs (98 duplicates removed from 2,225 raw)",
        tasks=["email_summarization"],
        domain_match="low",
        trust_level="supplementary",
        known_issues=[
            "News articles, not email — no sender/subject/thread/signature/quoted-reply structure. "
            "See docs/data_audit_summarization.md for the full disclosure.",
            "Summaries ARE genuinely human-written (not fabricated) — this is NOT the same class of "
            "limitation as priority_synthetic_v1/category_synthetic_v1's heuristic labels. Supports "
            "real model-quality comparison; does not support PRD-compliance claims for FR-25/26/27.",
            "Reference summary length (median 142 words) is far longer than FR-25's 2-3-sentence "
            "target — a format mismatch independent of the domain mismatch.",
            "Physically stored at a misleadingly-named path (data/raw/cnn_dailymail/BBC News Summary/) "
            "left over from an abandoned CNN/DailyMail download attempt — see data audit §2.",
        ],
        preprocessing_script="backend/scripts/prepare_summarization_dataset.py",
    ),

    "sentiment_synthetic_v1": DatasetEntry(
        name="Sentiment Analysis — Synthetic Bootstrap (Enron-sourced, VADER-labeled)",
        version="v1-synthetic",
        source_url="https://www.kaggle.com/datasets/wcukierski/enron-email-dataset",
        local_path="data/processed/sentiment_synthetic_v1/",
        license="Research use only (inherited from Enron)",
        size_approx="see run_metadata.json written alongside the parquet output",
        tasks=["sentiment_analysis"],
        domain_match="medium",
        trust_level="synthetic_bootstrap",
        known_issues=[
            "NOT PRD-compliant — no human ever assigned these labels. See "
            "docs/data_audit_sentiment.md for the full data strategy decision.",
            "Labels are 5-class (Very Negative..Very Positive) generated by "
            "bucketing VADER's lexicon-based compound polarity score "
            "(backend/scripts/generate_synthetic_sentiment_dataset.py), not "
            "human judgment. A classifier trained on this dataset can only "
            "ever approximate VADER's own scoring function — a structural "
            "ceiling, not a sampling artifact. See "
            "docs/model_cards/sentiment.md 'Model Selection' for the "
            "empirical comparison that made this the basis for NOT serving "
            "the trained classifier this phase.",
            "Inherits every Enron limitation already listed under 'enron' "
            "above (2001-2002 domain shift, PII present, energy-sector "
            "jargon).",
            "Must be replaced by real annotated data (Option A, "
            "docs/data_audit_sentiment.md §4 / "
            "docs/annotation_guidelines_sentiment.md) before any production "
            "or PRD-compliance claim.",
        ],
        preprocessing_script="backend/scripts/generate_synthetic_sentiment_dataset.py",
    ),

    "intent_synthetic_v1": DatasetEntry(
        name="Intent Detection — Synthetic Bootstrap (Enron-sourced)",
        version="v1-synthetic",
        source_url="https://www.kaggle.com/datasets/wcukierski/enron-email-dataset",
        local_path="data/processed/intent_synthetic_v1/",
        license="Research use only (inherited from Enron)",
        size_approx="see run_metadata.json written alongside the parquet output",
        tasks=["intent_detection"],
        domain_match="low",
        trust_level="synthetic_bootstrap",
        known_issues=[
            "NOT PRD-compliant — no human ever assigned these labels. See "
            "docs/data_audit_intent.md for the full data strategy decision.",
            "Labels are multi-label and generated by the same keyword heuristic "
            "(backend/app/feature_engineering/intent_keywords.py) used only for "
            "label generation, not model features (see data audit §5) — a "
            "structural leakage channel between the label and the raw text the "
            "TF-IDF model trains on regardless. Metrics from this dataset are "
            "pipeline validation only, never business-readiness evidence.",
            "Several classes (Order, Refund, Cancel) are consumer-transactional "
            "concepts nearly absent from Enron's internal B2B corporate "
            "correspondence — a domain mismatch WORSE than priority/category's, "
            "see docs/data_audit_intent.md §3 for the direct evidence.",
            "Inherits every Enron limitation already listed under 'enron' above "
            "(2001-2002 domain shift, PII present, energy-sector jargon).",
            "Must be replaced by real annotated data (Option A, "
            "docs/data_audit_intent.md §4 / docs/intent_labeling_strategy.md) "
            "before any production claim.",
        ],
        preprocessing_script="backend/scripts/generate_synthetic_intent_dataset.py",
    ),
}