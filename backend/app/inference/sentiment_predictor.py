"""
Production inference wrapper for sentiment analysis (Module 6 / Phase 7A) --
the SERVED path. See docs/data_audit_sentiment.md §4 for why this wraps
VADER (lexicon-based, zero-shot) rather than a trained classifier: no
trustworthy email-domain, 5-class-taxonomy training data exists, and a
classifier trained on this phase's only available proxy (VADER-pseudo-labels
over Enron text -- see train_sentiment_model.py) could only ever approximate
VADER's own output, never exceed it.

Structurally different from every other *Predictor in this codebase: there
is no ArtifactManager.load_model() call, because there is no fitted
estimator to load. SentimentIntensityAnalyzer() is a fixed, versioned
lexicon shipped inside the vaderSentiment package itself -- "loading" it is
just constructing the object, comparable in spirit to how
ExtractiveSummarizer needs no persisted artifact either (app/nlp/, Phase 6).
"""

import time

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.inference.prediction_models import PredictionResult

LABELS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]

# Same bucket thresholds as generate_synthetic_sentiment_dataset.py -- kept
# as separate constants (not a shared import) because that script's
# thresholds are a data-generation decision and these are a serving
# decision; today they are deliberately identical (one bucketing scheme,
# disclosed once in docs/data_audit_sentiment.md §3), but nothing here
# requires them to stay coupled if serving-time calibration ever diverges
# from how the comparison dataset was built.
_VERY_NEGATIVE_MAX = -0.6
_NEGATIVE_MAX = -0.05
_POSITIVE_MIN = 0.05
_VERY_POSITIVE_MIN = 0.6

_BOUNDARIES = [_VERY_NEGATIVE_MAX, _NEGATIVE_MAX, _POSITIVE_MIN, _VERY_POSITIVE_MIN]


def bucket_compound(compound: float) -> str:
    if compound <= _VERY_NEGATIVE_MAX:
        return "Very Negative"
    if compound <= _NEGATIVE_MAX:
        return "Negative"
    if compound < _POSITIVE_MIN:
        return "Neutral"
    if compound < _VERY_POSITIVE_MIN:
        return "Positive"
    return "Very Positive"


def _pseudo_distribution(compound: float, label: str) -> dict[str, float]:
    """
    VADER produces a single compound score, not a calibrated class
    distribution -- there is no "probability of Very Negative vs Negative"
    the way a softmax gives one. This derives a DISCLOSED HEURISTIC
    distribution, not a measured probability: confidence is how far the
    compound score sits from the nearest bucket boundary (relative to that
    bucket's own width), and because the label scale is ordinal, whatever
    mass isn't on the predicted label goes to its immediate neighbor(s) on
    the scale, never to a distant, unrelated class.

    See docs/model_cards/sentiment.md "Calibration" -- this has NOT been
    validated against real ground truth (none exists), and must not be read
    as a calibrated confidence score.
    """
    idx = LABELS.index(label)

    lower = -1.0 if idx == 0 else _BOUNDARIES[idx - 1]
    upper = 1.0 if idx == len(LABELS) - 1 else _BOUNDARIES[idx]
    width = max(upper - lower, 1e-9)
    depth = min(compound - lower, upper - compound) / width
    confidence = round(0.5 + 0.5 * max(0.0, min(depth * 2, 1.0)), 4)

    remainder = round(1.0 - confidence, 4)
    dist = dict.fromkeys(LABELS, 0.0)
    dist[label] = confidence

    neighbors = [i for i in (idx - 1, idx + 1) if 0 <= i < len(LABELS)]
    if neighbors and remainder > 0:
        share = round(remainder / len(neighbors), 4)
        for i in neighbors:
            dist[LABELS[i]] = share

    return dist


class VaderSentimentPredictor:
    """
    Loads the VADER lexicon once (cheap -- no model download, unlike
    AbstractiveSummarizer) and reuses it for all incoming predictions.
    """

    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()

    def predict(self, text: str) -> PredictionResult:
        start = time.perf_counter()

        scores = self.analyzer.polarity_scores(text or "")
        compound = scores["compound"]
        label = bucket_compound(compound)
        probabilities = _pseudo_distribution(compound, label)

        processing_ms = (time.perf_counter() - start) * 1000

        return PredictionResult(
            label=label,
            confidence=probabilities[label],
            probabilities=probabilities,
            processing_ms=round(processing_ms, 2),
        )

    def predict_batch(self, texts: list[str]) -> list[PredictionResult]:
        start = time.perf_counter()
        results = [self.predict(text) for text in texts]
        total_ms = (time.perf_counter() - start) * 1000
        avg_ms = round(total_ms / len(texts), 2) if texts else 0.0
        for result in results:
            result.processing_ms = avg_ms
        return results
