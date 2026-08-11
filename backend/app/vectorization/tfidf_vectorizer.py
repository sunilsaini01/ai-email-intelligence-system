from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class TFIDFConfig:
    """
    Configuration for TF-IDF Vectorizer.
    """

    max_features: int = 50_000
    min_df: int = 3
    max_df: float = 0.95

    ngram_range: tuple = (1, 2)

    sublinear_tf: bool = True

    norm: str = "l2"

    analyzer: str = "word"

    strip_accents: str = "unicode"
    
class TFIDFVectorizer:
    """
    Production-ready TF-IDF Vectorizer.
    """

    def __init__(self, config: TFIDFConfig = None):

        if config is None:
            config = TFIDFConfig()

        self.config = config

        self.vectorizer = TfidfVectorizer(
            max_features=config.max_features,
            min_df=config.min_df,
            max_df=config.max_df,
            ngram_range=config.ngram_range,
            sublinear_tf=config.sublinear_tf,
            norm=config.norm,
            analyzer=config.analyzer,
            strip_accents=config.strip_accents,
        )
        
    def fit(self, texts: list[str]):
        """
        Learn vocabulary and IDF scores from training data.
        """
        self.vectorizer.fit(texts)
        return self
    def transform(self, texts: list[str]):
        """
        Transform texts into TF-IDF vectors.
        """
        return self.vectorizer.transform(texts)

    def fit_transform(self, texts: list[str]):
        """
        Learn vocabulary + IDF and transform training texts.
        """
        return self.vectorizer.fit_transform(texts)
    
    def save(self, path: str):
        """
        Save the trained TF-IDF vectorizer.
        """
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.vectorizer, path)

    def load(self, path: str):
        """
        Load a trained TF-IDF vectorizer.
        """
        self.vectorizer = joblib.load(path)
        return self

    def get_feature_names(self):
        """
        Return all learned features.
        """
        return self.vectorizer.get_feature_names_out()

    def vocabulary_size(self):
        """
        Return vocabulary size.
        """
        return len(self.vectorizer.vocabulary_)

    def idf_scores(self):
        """
        Return the IDF score for every feature.
        """
        return dict(
            zip(
                self.vectorizer.get_feature_names_out(),
                self.vectorizer.idf_,
            )
        )
        
    def top_features(self, n: int = 20):
        """
        Return the top N features with the highest IDF scores.
        """
        scores = self.idf_scores()

        return sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
        )[:n]