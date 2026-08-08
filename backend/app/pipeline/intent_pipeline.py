"""
Intent detection pipeline (Module 7 / Phase 7B).

Structurally close to CategoryMLPipeline (TF-IDF + OneVsRestClassifier +
MultiLabelBinarizer, multi-label per FR-34), but deliberately NOT a subclass
or a reuse of that class -- see docs/data_audit_intent.md §5 and
docs/architecture_intent.md for the two reasons:

1. CategoryMLPipeline hardcodes CATEGORY_LABELS as a module-level import
   inside __init__, not a constructor parameter -- it cannot serve a
   different label set without modification, and modifying an already-
   shipped, artifact-pickled, tested class carries the exact risk the
   Phase 5 ContentFeatures incident already demonstrated once.
2. This pipeline is TF-IDF-ONLY -- no ContentFeatures/MetadataFeatures, no
   FeatureSchema coupling. CategoryMLPipeline pulls in both (needed for
   FR-17-style priority/category signals); Intent's PRD entry names no such
   requirement, and the PRD's own suggested classical baseline is literally
   "TF-IDF + Multi-label LR" with nothing else. Avoiding the shared
   dataclasses a third time was a deliberate repository-audit decision, not
   an oversight -- see the Phase 7B Gate report.

Interface parity with MLPipeline/PriorityMLPipeline/CategoryMLPipeline
(fit/predict/predict_proba/save/load) is deliberate, same reasoning as
those classes' docstrings: Trainer only calls those five methods.
"""

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

from app.feature_engineering.intent_keywords import INTENT_LABELS
from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.pipeline_factory import PipelineFactory


class IntentMLPipeline:
    """
    Raw text (body_clean, already subject+body combined & preprocessed)
        v
    TF-IDF (uni+bigram)
        v
    One-vs-Rest(base classifier) -- 9 independent binary decisions
        v
    Multi-hot label set (Complaint/Inquiry/Request/Feedback/Escalation/
    Order/Cancel/Refund/Schedule) -- may be EMPTY, unlike Category (no
    "General" fallback exists in this taxonomy, see intent_keywords.py)
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.tfidf: TfidfVectorizer | None = None
        self.mlb = MultiLabelBinarizer(classes=list(INTENT_LABELS))
        self.classifier: OneVsRestClassifier | None = None
        self.classes_ = None
        # No FeatureSchema attribute -- deliberately not coupled to the
        # shared ContentFeatures/MetadataFeatures fingerprint mechanism,
        # since this pipeline never touches either dataclass. See module
        # docstring point 2.

    def _vectorize(self, texts: list[str], fit: bool):
        if fit:
            self.tfidf = TfidfVectorizer(
                max_features=self.config.tfidf_max_features,
                ngram_range=self.config.tfidf_ngram_range,
                sublinear_tf=self.config.tfidf_sublinear_tf,
                min_df=1,
            )
            return self.tfidf.fit_transform(texts)
        return self.tfidf.transform(texts)

    def fit(self, X_train: list[str], y_train: list[list[str]]):
        """
        `X_train` is a list of already-cleaned text strings (unlike
        PriorityMLPipeline/CategoryMLPipeline, which take record dicts --
        this pipeline needs nothing but body_clean, so the caller passes
        the string directly, matching plain MLPipeline's contract). `y_train`
        is a list of label-lists, the multi-label shape (may contain empty
        lists), same as CategoryMLPipeline's y_train shape.
        """
        matrix = self._vectorize(X_train, fit=True)
        y_binary = self.mlb.fit_transform(y_train)

        base_estimator = PipelineFactory.create_model(config=self.config, build_only=True)
        self.classifier = OneVsRestClassifier(estimator=base_estimator)
        self.classifier.fit(matrix, y_binary)
        self.classes_ = self.mlb.classes_

        return self

    def predict(self, X: list[str]) -> list[list[str]]:
        """Returns a list of label-lists -- may be empty for a row where no
        intent crossed the decision threshold. No fallback is applied here
        (unlike CategoryService's "General" safety net) -- see
        app/services/intent_service.py for why an empty list is a valid,
        surfaced response for this module."""
        matrix = self._vectorize(X, fit=False)
        y_binary = self.classifier.predict(matrix)
        return [list(labels) for labels in self.mlb.inverse_transform(y_binary)]

    def predict_proba(self, X: list[str]) -> np.ndarray:
        """Returns an (n_samples, n_labels) array of independent per-intent
        probabilities -- rows do NOT sum to 1, same reasoning as
        CategoryMLPipeline.predict_proba."""
        matrix = self._vectorize(X, fit=False)
        return self.classifier.predict_proba(matrix)

    def save(self, path: str):
        joblib.dump(self, path)

    def load(self, path: str):
        loaded = joblib.load(path)
        self.__dict__.update(loaded.__dict__)
        return self
