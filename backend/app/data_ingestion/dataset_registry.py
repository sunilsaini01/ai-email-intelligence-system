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
}