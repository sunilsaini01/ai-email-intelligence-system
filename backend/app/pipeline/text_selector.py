from sklearn.base import BaseEstimator, TransformerMixin


class TextSelector(BaseEstimator, TransformerMixin):
    """
    Select a text column from a DataFrame, dictionary,
    or list-like object.

    This transformer is used inside the TF-IDF branch
    of the production pipeline.
    """

    def __init__(self, key: str = "body_clean"):
        self.key = key

    def fit(self, X, y=None):
        """
        No learning is required.
        """
        return self

    def transform(self, X):
        """
        Extract the desired text column.

        Supports:
        - pandas DataFrame
        - dictionary
        - already extracted list of strings
        """

        if hasattr(X, "__getitem__"):
            try:
                return X[self.key]
            except Exception:
                pass

        return X