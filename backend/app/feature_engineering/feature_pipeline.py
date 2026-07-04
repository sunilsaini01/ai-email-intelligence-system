from sklearn.feature_extraction.text import TfidfVectorizer
import pandas as pd


def build_tfidf_features(
    train_texts,
    val_texts,
    max_features=5000
):
    """
    Build TF-IDF features.
    Fit only on train data.
    """

    vectorizer = TfidfVectorizer(
        max_features=max_features,
        ngram_range=(1, 2),
        sublinear_tf=True,
        strip_accents="unicode",
        analyzer="word",
        min_df=1,
    )

    X_train = vectorizer.fit_transform(train_texts)
    X_val = vectorizer.transform(val_texts)

    return X_train, X_val, vectorizer


def build_metadata_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build simple metadata features.
    """

    features = pd.DataFrame()

    features["word_count"] = df["body_clean"].str.split().str.len()

    features["has_attachments"] = (
        df["has_attachments"].astype(int)
    )

    features["recipient_count"] = (
        df["recipient_count"].fillna(1)
    )

    return features