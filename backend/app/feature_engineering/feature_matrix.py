import numpy as np

from dataclasses import asdict

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
) -> csr_matrix:
    """
    Combine TF-IDF features with engineered features.
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