"""
Email categorization pipeline (Module 4).

Why this can't just reuse PriorityMLPipeline as-is, even though the shape
looks similar (TF-IDF + ContentFeatures + MetadataFeatures, same as
priority): categorization is multi-label (FR-22, PRD §9.1), not single-label
multiclass. `y_train` here is a list of label-lists, not a list of scalar
strings, and the classifier is a One-vs-Rest ensemble of 8 independent
binary classifiers, not one multiclass estimator — `predict()` and
`predict_proba()` therefore return fundamentally different shapes (a matrix
of independent per-label decisions/probabilities, not a single softmax
distribution that sums to 1 per row). Reusing PriorityMLPipeline's `fit`
signature would either silently coerce multi-label data into single-label
(losing FR-22's whole point) or require a parallel set of `if multilabel:`
branches inside a class that already has a documented, working single-label
contract (Trainer, PriorityService, and their tests all depend on
PriorityMLPipeline staying single-label-shaped). A second, explicit pipeline
class is the honest boundary — see docs/data_audit_categorization.md §7 for
why multi-label is the correct formulation for this task, not a convenience
choice.

Interface parity with MLPipeline/PriorityMLPipeline (fit/predict/
predict_proba/save/load) is deliberate, same reasoning as
PriorityMLPipeline's docstring: Trainer only calls those five methods, so it
works with this pipeline unchanged via `pipeline_cls=CategoryMLPipeline`.
"""

from datetime import UTC, datetime

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

from app.feature_engineering.category_keywords import CATEGORY_LABELS
from app.feature_engineering.content_features import ContentFeatureExtractor
from app.feature_engineering.feature_matrix import build_feature_matrix
from app.feature_engineering.feature_scaler import EngineeredFeatureScaler
from app.feature_engineering.feature_schema import FeatureSchema
from app.feature_engineering.metadata_features import MetadataFeatureExtractor
from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.pipeline_factory import PipelineFactory


def _parse_datetime(value) -> datetime:
    """Same contract as priority_pipeline.py's _parse_datetime — never raises."""
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
    """Identical field contract to priority_pipeline.py's _record_to_features —
    a `record` is the same shape CategoryService builds from a
    CategoryPredictionRequest (see app/services/category_service.py)."""
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


class CategoryMLPipeline:
    """
    Raw email record (dict)
        v
    TF-IDF (body_clean)  +  ContentFeatures  +  MetadataFeatures
        v
    [scaled for LR/SVM; unscaled for Naive Bayes — same constraint as
     PriorityMLPipeline, see build_feature_matrix's docstring]
        v
    One-vs-Rest(base classifier) — 8 independent binary decisions
        v
    Multi-hot label set (Support/Sales/Billing/Legal/HR/IT/Marketing/General)
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.tfidf: TfidfVectorizer | None = None
        self.content_extractor = ContentFeatureExtractor()
        self.metadata_extractor = MetadataFeatureExtractor()
        # Same non-negativity constraint as PriorityMLPipeline — Naive Bayes
        # can't take a StandardScaler's (possibly negative) output.
        self._use_scaling = config.model_type != "naive_bayes"
        self.scaler = EngineeredFeatureScaler() if self._use_scaling else None
        self.mlb = MultiLabelBinarizer(classes=list(CATEGORY_LABELS))
        self.classifier: OneVsRestClassifier | None = None
        self.classes_ = None
        # Phase 6 Gate 1 (cross-module hardening) — see
        # app/feature_engineering/feature_schema.py's module docstring for
        # why this exists (the Phase 5 incident that broke priority's
        # artifact) and app/pipeline/priority_pipeline.py for the identical
        # mechanism there.
        self.feature_schema: FeatureSchema | None = None

    def _vectorize(self, records: list[dict], fit: bool):
        if not fit:
            stored_schema = getattr(self, "feature_schema", None)
            if stored_schema is not None:
                stored_schema.validate_compatible_with(FeatureSchema.current())

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

    def fit(self, X_train: list[dict], y_train: list[list[str]]):
        """
        `y_train` is a list of label-lists (e.g. [["Legal", "Billing"], ["General"]]),
        not a list of scalar strings — the multi-label equivalent of
        PriorityMLPipeline.fit's y_train.
        """
        matrix = self._vectorize(X_train, fit=True)
        self.feature_schema = FeatureSchema.current()
        y_binary = self.mlb.fit_transform(y_train)

        base_estimator = PipelineFactory.create_model(config=self.config, build_only=True)
        self.classifier = OneVsRestClassifier(estimator=base_estimator)
        self.classifier.fit(matrix, y_binary)
        self.classes_ = self.mlb.classes_

        return self

    def predict(self, X: list[dict]) -> list[list[str]]:
        """Returns a list of label-lists — may be empty for a row where no
        category crossed the decision threshold (see CategoryService for the
        General-fallback safety net, a service-layer policy choice, not a
        model-layer one — same separation as SpamService's threshold)."""
        matrix = self._vectorize(X, fit=False)
        y_binary = self.classifier.predict(matrix)
        return [list(labels) for labels in self.mlb.inverse_transform(y_binary)]

    def predict_proba(self, X: list[dict]) -> np.ndarray:
        """Returns an (n_samples, n_labels) array of independent per-category
        probabilities — rows do NOT sum to 1 (unlike single-label multiclass),
        because each category is an independent yes/no decision."""
        matrix = self._vectorize(X, fit=False)
        return self.classifier.predict_proba(matrix)

    def save(self, path: str):
        joblib.dump(self, path)

    def load(self, path: str):
        loaded = joblib.load(path)
        self.__dict__.update(loaded.__dict__)
        return self
