"""
Phase 9 — Similar Email Retrieval: fit the TF-IDF baseline embedder.

Unlike every classifier this project has trained so far (Spam/Priority/
Category/Intent), this is UNSUPERVISED -- no labels are used or needed, so
none of those modules' synthetic-label caveats apply here. Fits on real
Enron email text, reused directly from two already-generated, already-
checksummed datasets (`priority_synthetic_v1` + `category_synthetic_v1`)
rather than re-parsing the raw ~1.4GB Enron CSV (which isn't present in
this environment) -- only `subject_raw`/`body_text_raw` are used; every
label column (`priority_label`, `categories`, ...) is ignored entirely.
Two sources combined (not one) for vocabulary diversity/size, deduplicated
by `message_id` since both were sampled independently from the same
underlying Enron corpus and likely overlap.

REGRESSION NOTE (found via Phase 9's own end-to-end smoke test, fixed
before this script's first real use): an earlier version of this script
fit directly on raw `body_text_raw` with no cleaning at all. The resulting
512-term vocabulary was dominated by HTML fragments ("align left", "td
tr"), personal names, and an Enron fantasy-football mailing list's jargon
("fantasy sportsline", "league ene") -- common words like "refund" and
"weather" never made the cut, so ordinary queries produced all-zero
vectors and every similarity score came back exactly 0.0 regardless of
actual relevance. Fixed by running text through
EmailPreprocessor(SPAM_CONFIG) (strips HTML/signatures, lemmatizes,
removes stopwords -- the most aggressive cleaning config already
established in this codebase) before fitting, raising max_features, and
adding min_df to drop terms too rare to be meaningful. See
docs/error_analysis_retrieval.md for the full incident writeup.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/train_tfidf_embedder.py

Produces:
    artifacts/tfidf_embedder.joblib
    artifacts/tfidf_embedder_metrics.json
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from app.preprocessing.email_preprocessor import SPAM_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager

CORPUS_PARQUETS = [
    "data/processed/priority_synthetic_v1/train.parquet",
    "data/processed/category_synthetic_v1/train.parquet",
]
MAX_FEATURES = 1024
MIN_DF = 3  # a term must appear in >= 3 documents to survive -- drops one-off noise (names, stray tokens)
MODEL_FILENAME = "tfidf_embedder.joblib"
METRICS_FILENAME = "tfidf_embedder_metrics.json"


def _load_corpus() -> list[str]:
    frames = []
    for path in CORPUS_PARQUETS:
        df = pd.read_parquet(path)[["message_id", "subject_raw", "body_text_raw"]]
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["message_id"])
    return (combined["subject_raw"].fillna("") + "\n\n" + combined["body_text_raw"].fillna("")).tolist()


def main():
    print(f"Loading corpus text from {CORPUS_PARQUETS} (text only, no labels)...")
    raw_texts = _load_corpus()
    raw_texts = [t for t in raw_texts if t.strip()]
    print(f"{len(raw_texts)} raw documents after dedup; cleaning (strip HTML/signatures, lemmatize)...")

    preprocessor = EmailPreprocessor(SPAM_CONFIG)
    cleaned_texts = [preprocessor.process(t) for t in raw_texts]
    cleaned_texts = [t for t in cleaned_texts if t.strip()]
    print(f"Fitting TfidfVectorizer on {len(cleaned_texts)} cleaned documents...")

    vectorizer = TfidfVectorizer(
        max_features=MAX_FEATURES,
        min_df=MIN_DF,
        ngram_range=(1, 2),
        norm="l2",  # every embedder in this codebase must emit L2-normalized vectors
    )
    vectorizer.fit(cleaned_texts)

    # Sanity check baked into the training run itself, not left implicit --
    # exactly the class of vocabulary-quality bug this script's docstring
    # describes. Fails loudly rather than silently shipping a degenerate
    # artifact a second time.
    vocab = set(vectorizer.get_feature_names_out())
    sentinel_terms = {"refund", "invoice", "meeting", "contract", "urgent"}
    covered = sentinel_terms & vocab
    print(f"Vocabulary sanity check: {covered or '(none)'} of {sentinel_terms} present in vocabulary.")
    if not covered:
        raise RuntimeError(
            "None of the sentinel business terms are in the fitted vocabulary -- "
            "the corpus or cleaning step likely regressed. Refusing to save this artifact."
        )

    version = f"tfidf_baseline-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    artifact_manager = ArtifactManager()
    artifact_manager.save_model(vectorizer, MODEL_FILENAME)

    metrics_path = Path(artifact_manager.artifact_dir) / METRICS_FILENAME
    metrics_path.write_text(
        json.dumps(
            {
                "model_version": version,
                "dimension": len(vectorizer.get_feature_names_out()),
                "corpus": CORPUS_PARQUETS,
                "corpus_size_raw": len(raw_texts),
                "corpus_size_cleaned": len(cleaned_texts),
                "corpus_labels_used": False,
                "max_features": MAX_FEATURES,
                "min_df": MIN_DF,
                "vocabulary_sanity_check_terms_found": sorted(covered),
                "created_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )
    print(f"[OK] Saved {MODEL_FILENAME} (dimension={len(vectorizer.get_feature_names_out())})")
    print(f"[OK] Saved {METRICS_FILENAME}")


if __name__ == "__main__":
    main()
