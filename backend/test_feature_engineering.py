import pandas as pd

from app.feature_engineering.feature_pipeline import (
    build_tfidf_features,
    build_metadata_features,
)

train_texts = [
    "free money offer now",
    "meeting scheduled tomorrow",
    "claim your reward",
]

val_texts = [
    "important meeting update",
]

X_train, X_val, vectorizer = build_tfidf_features(
    train_texts,
    val_texts,
)

print("TF-IDF TRAIN SHAPE:")
print(X_train.shape)

print("\nTF-IDF VAL SHAPE:")
print(X_val.shape)

df = pd.DataFrame({
    "body_clean": train_texts,
    "has_attachments": [0, 1, 0],
    "recipient_count": [1, 3, 2],
})

metadata_features = build_metadata_features(df)

print("\nMETADATA FEATURES:")
print(metadata_features)