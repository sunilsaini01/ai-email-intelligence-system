from dataclasses import dataclass


@dataclass
class PredictionResult:
    """
    Standard prediction response returned by all ML models.
    """

    label: str
    confidence: float
    probabilities: dict[str, float]
    processing_ms: float


@dataclass
class MultiLabelPredictionResult:
    """
    Prediction response for multi-label classifiers (Module 4 / FR-22,
    FR-24). Not a shape PredictionResult can express: there is no single
    "label" or "confidence" for a multi-label decision — FR-24 requires a
    confidence score per *assigned* category, and a caller (or a future
    routing rule) may also need the full per-category distribution to see
    how close a non-assigned category came, not just what got picked.
    """

    labels: list[str]  # categories assigned (crossed the decision threshold)
    label_confidences: dict[str, float]  # confidence for each assigned label only
    all_scores: dict[str, float]  # full distribution over every category in the taxonomy
    processing_ms: float