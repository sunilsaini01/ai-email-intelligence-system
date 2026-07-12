from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


def build_text_pipeline() -> Pipeline:
    """
    Build a simple text classification pipeline.

    Flow:
    Raw Text
        ↓
    TF-IDF
        ↓
    Logistic Regression
    """

    pipeline = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    max_features=50_000,
                    ngram_range=(1, 2),
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=1.0,
                    solver="saga",
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=42,
                ),
            ),
        ]
    )

    return pipeline