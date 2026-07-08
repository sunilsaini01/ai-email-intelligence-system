from dataclasses import dataclass
from typing import Optional
import joblib

from sklearn.feature_extraction.text import CountVectorizer


@dataclass
class BoWConfig:
    """
    Configuration for Bag of Words Vectorizer.
    """

    max_features: int = 50_000
    min_df: int = 3
    max_df: float = 0.95
    ngram_range: tuple[int, int] = (1, 1)
    binary: bool = False
    
class BoWVectorizer:
    """
    Production-ready Bag of Words Vectorizer.
    """

    def __init__(self, config: Optional[BoWConfig] = None):

        if config is None:
            config = BoWConfig()

        self.config = config

        self.vectorizer = CountVectorizer(
            max_features=config.max_features,
            min_df=config.min_df,
            max_df=config.max_df,
            ngram_range=config.ngram_range,
            binary=config.binary,
        )
        
        def fit(self, texts: list[str]):
            """
            Learn vocabulary from training texts.
            """
            self.vectorizer.fit(texts)
            return self

    def transform(self, texts: list[str]):
        """
        Convert texts into Bag of Words vectors.
        """
        return self.vectorizer.transform(texts)

    def fit_transform(self, texts: list[str]):
        """
        Learn vocabulary and transform texts.
        Used only on training data.
        """
        return self.vectorizer.fit_transform(texts)
    
    def save(self, path: str):
        """
        Save the trained vectorizer to disk.
        """
        joblib.dump(self.vectorizer, path)

    def load(self, path: str):
        """
        Load a previously trained vectorizer.
        """
        self.vectorizer = joblib.load(path)
        return self

    def get_feature_names(self):
        """
        Return the learned vocabulary.
        """
        return self.vectorizer.get_feature_names_out()

    def vocabulary_size(self):
        """
        Return vocabulary size.
        """
        return len(self.vectorizer.vocabulary_)