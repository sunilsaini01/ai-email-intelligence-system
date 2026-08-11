from dataclasses import asdict

import numpy as np
from scipy.sparse import (
    csr_matrix,
    hstack,
)

from app.feature_engineering.feature_models import ContentFeatures
from app.feature_engineering.metadata_models import MetadataFeatures


def build_feature_matrix(
    tfidf_matrix,
    content_feat_list: list[ContentFeatures],
    metadata_feat_list: list[MetadataFeatures],
    scaler=None,
    fit_scaler: bool = False,
) -> csr_matrix:
    """
    Combine TF-IDF features with engineered features.

    `scaler` (an EngineeredFeatureScaler, optional): scaling must happen
    between concatenation and sparsification — content+metadata features mix
    raw counts (word_count in the hundreds) with 0/1 booleans, and feeding
    that unscaled into a distance-sensitive classifier (SVM/LR) lets the
    largest-magnitude raw counts dominate. `scaler=None` preserves the
    original unscaled behavior exactly (used by Naive Bayes callers, which
    require non-negative input and would break on a StandardScaler's
    negative outputs — see app/pipeline/priority_pipeline.py).
    """
    # Convert dataclasses into NumPy arrays

    content_array = np.array(
        [list(asdict(f).values()) for f in content_feat_list],
        dtype=np.float32,
    )

    metadata_array = np.array(
        [list(asdict(f).values()) for f in metadata_feat_list],
        dtype=np.float32,
    )

    # Combine engineered features

    engineered_features = np.hstack(
        [
            content_array,
            metadata_array,
        ]
    )

    if scaler is not None:
        engineered_features = (
            scaler.fit_transform(engineered_features)
            if fit_scaler
            else scaler.transform(engineered_features)
        )

    # Convert engineered features to sparse

    engineered_sparse = csr_matrix(
        engineered_features
    )

    # Combine TF-IDF + engineered features

    combined_matrix = hstack(
        [
            tfidf_matrix,
            engineered_sparse,
        ]
    )

    return combined_matrix

def feature_summary(
    content_features: list[ContentFeatures],
    metadata_features: list[MetadataFeatures],
) -> None:
    """
    Print a summary of engineered features.
    """

    content_count = len(
        asdict(content_features[0])
    )

    metadata_count = len(
        asdict(metadata_features[0])
    )

    print(f"Content Features : {content_count}")
    print(f"Metadata Features: {metadata_count}")
    print(f"Total Features   : {content_count + metadata_count}")