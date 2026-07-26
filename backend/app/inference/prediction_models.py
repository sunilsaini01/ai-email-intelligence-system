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