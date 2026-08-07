"""
Priority classification pipeline (Module 3).

Why this can't just reuse MLPipeline as-is:
    MLPipeline (spam) is TF-IDF -> classifier, full stop. FR-17 requires
    priority to incorporate subject keywords, time of day, and (a proxy for)
    sentiment — signals that live in ContentFeatures/MetadataFeatures, not in
    the TF-IDF matrix. Those extractors and build_feature_matrix() already
    existed in the codebase, unused by any production pipeline until now —
    this class is what actually wires them together, rather than introducing
    a second, parallel feature-engineering system.

Interface parity with MLPipeline (fit/predict/predict_proba/save/load) is
deliberate: Trainer only calls those five methods, so Trainer works with
either pipeline class unchanged (see the `pipeline_cls` param added to
Trainer.__init__).
"""

from datetime import UTC, datetime

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer

from app.feature_engineering.content_features import ContentFeatureExtractor
from app.feature_engineering.feature_matrix import build_feature_matrix
from app.feature_engineering.feature_scaler import EngineeredFeatureScaler
from app.feature_engineering.metadata_features import MetadataFeatureExtractor
from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.pipeline_factory import PipelineFactory


def _parse_datetime(value) -> datetime:
    """
    Accepts a datetime already, an ISO string, or a raw RFC 2822 header
    string (what the Enron loader hands back) — falls back to "now" rather
    than raising, matching EmailPreprocessor's own "never raises" contract
    for untrusted upstream text.
    """
    if isinstance(value, datetime):
        return value
    if value:
        from email.utils import parsedate_to_datetime

        try:
            parsed = parsedate_to_datetime(str(value))
            if parsed is not None:
                return parsed
        except (TypeError, ValueError):
            pass
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            pass
    return datetime.now(UTC)


def _record_to_features(record: dict, content_extractor: ContentFeatureExtractor,
                          metadata_extractor: MetadataFeatureExtractor):
    """
    A `record` is the same shape PriorityService builds from a
    PriorityPredictionRequest — see app/services/priority_service.py.
    Fields not derivable from a raw request (thread_depth, attachments) get
    the same defaults at train time and inference time; see
    docs/data_audit_priority.md §5 for why that's a disclosed limitation, not
    a train/serve skew (both sides use the identical default).
    """
    content = content_extractor.extract(
        body_clean=record.get("body_clean", ""),
        subject_raw=record.get("subject_raw", ""),
        is_reply=record.get("is_reply", False),
    )
    metadata = metadata_extractor.extract(
        received_at=_parse_datetime(record.get("received_at")),
        sender_email=record.get("sender_email", "") or "",
        recipient_to=record.get("recipient_to") or [],
        recipient_cc=record.get("recipient_cc") or [],
        thread_depth=record.get("thread_depth", 0),
        is_reply=record.get("is_reply", False),
        is_forward=record.get("is_forward", False),
        has_attachments=record.get("has_attachments", False),
        attachment_count=record.get("attachment_count", 0),
    )
    return content, metadata


class PriorityMLPipeline:
    """
    Raw email record (dict)
        v
    TF-IDF (body_clean)  +  ContentFeatures  +  MetadataFeatures
        v
    [scaled for LR/SVM; unscaled for Naive Bayes — see build_feature_matrix's
     docstring for why NB can't take a StandardScaler's negative output]
        v
    Classifier (multiclass: Critical/High/Medium/Low)
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.tfidf: TfidfVectorizer | None = None
        self.content_extractor = ContentFeatureExtractor()
        self.metadata_extractor = MetadataFeatureExtractor()
        # Naive Bayes requires non-negative input (see build_feature_matrix) —
        # scaling is skipped for that path, not attempted-then-worked-around.
        self._use_scaling = config.model_type != "naive_bayes"
        self.scaler = EngineeredFeatureScaler() if self._use_scaling else None
        self.classifier = None
        self.classes_ = None

    def _vectorize(self, records: list[dict], fit: bool):
        texts = [r.get("body_clean", "") for r in records]
        if fit:
            self.tfidf = TfidfVectorizer(
                max_features=self.config.tfidf_max_features,
                ngram_range=self.config.tfidf_ngram_range,
                sublinear_tf=self.config.tfidf_sublinear_tf,
                min_df=1,
            )
            tfidf_matrix = self.tfidf.fit_transform(texts)
        else:
            tfidf_matrix = self.tfidf.transform(texts)

        feature_pairs = [
            _record_to_features(r, self.content_extractor, self.metadata_extractor)
            for r in records
        ]
        content_feats = [pair[0] for pair in feature_pairs]
        metadata_feats = [pair[1] for pair in feature_pairs]

        return build_feature_matrix(
            tfidf_matrix,
            content_feats,
            metadata_feats,
            scaler=self.scaler,
            fit_scaler=fit,
        )

    def fit(self, X_train: list[dict], y_train: list[str]):
        matrix = self._vectorize(X_train, fit=True)

        self.classifier = PipelineFactory.create_model(config=self.config, build_only=True)
        self.classifier.fit(matrix, y_train)
        self.classes_ = self.classifier.classes_

        return self

    def predict(self, X):
        matrix = self._vectorize(X, fit=False)
        return self.classifier.predict(matrix)

    def predict_proba(self, X):
        matrix = self._vectorize(X, fit=False)
        return self.classifier.predict_proba(matrix)

    def save(self, path: str):
        joblib.dump(self, path)

    def load(self, path: str):
        loaded = joblib.load(path)
        self.__dict__.update(loaded.__dict__)
        return self
