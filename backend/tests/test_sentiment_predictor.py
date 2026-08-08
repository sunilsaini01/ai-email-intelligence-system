"""
Unit tests for VaderSentimentPredictor and its bucketing function
(Module 6 / Phase 7A). No trained artifact and no skip-if-missing guard --
unlike spam/priority/category, there's nothing that could be "not trained
yet" (see app/services/sentiment_service.py's module docstring).
"""

from app.inference.sentiment_predictor import (
    LABELS,
    VaderSentimentPredictor,
    bucket_compound,
)


def test_bucket_compound_covers_all_five_labels():
    assert bucket_compound(-0.9) == "Very Negative"
    assert bucket_compound(-0.3) == "Negative"
    assert bucket_compound(0.0) == "Neutral"
    assert bucket_compound(0.3) == "Positive"
    assert bucket_compound(0.9) == "Very Positive"


def test_bucket_compound_boundaries_are_inclusive_on_the_lower_bucket():
    # -0.6 itself belongs to Very Negative (<=), -0.05 to Negative (<=),
    # 0.6 belongs to Very Positive (only < 0.6 stays Positive) -- see
    # app/inference/sentiment_predictor.py's own boundary constants.
    assert bucket_compound(-0.6) == "Very Negative"
    assert bucket_compound(-0.05) == "Negative"
    assert bucket_compound(0.05) == "Positive"
    assert bucket_compound(0.6) == "Very Positive"


def test_predict_returns_a_valid_prediction_result():
    predictor = VaderSentimentPredictor()
    result = predictor.predict("Thank you so much, this worked perfectly!")

    assert result.label in LABELS
    assert 0.0 <= result.confidence <= 1.0
    assert set(result.probabilities.keys()) == set(LABELS)
    assert abs(sum(result.probabilities.values()) - 1.0) < 1e-3
    assert result.probabilities[result.label] == result.confidence
    assert result.processing_ms >= 0


def test_predict_handles_empty_text_without_raising():
    predictor = VaderSentimentPredictor()
    result = predictor.predict("")
    assert result.label in LABELS


def test_predict_distinguishes_strong_positive_and_negative_text():
    predictor = VaderSentimentPredictor()
    positive = predictor.predict("This is wonderful, excellent, fantastic news, thank you!")
    negative = predictor.predict("This is terrible, awful, horrible, I hate this.")

    assert positive.label in {"Positive", "Very Positive"}
    assert negative.label in {"Negative", "Very Negative"}


def test_predict_batch_returns_one_result_per_input_with_averaged_latency():
    predictor = VaderSentimentPredictor()
    texts = ["Great job!", "This is bad.", "Please see the attached report."]
    results = predictor.predict_batch(texts)

    assert len(results) == len(texts)
    # Batch latency is reported as the average per item (see predict_batch),
    # not each item's own individually-timed cost.
    assert len({r.processing_ms for r in results}) == 1


def test_predict_batch_empty_list_does_not_raise():
    predictor = VaderSentimentPredictor()
    assert predictor.predict_batch([]) == []


def test_ordinal_distribution_only_spreads_mass_to_adjacent_labels():
    """Confirms the disclosed heuristic in _pseudo_distribution: whatever
    probability mass isn't on the predicted label goes only to its
    immediate ordinal neighbor(s), never to a distant, unrelated class --
    see app/inference/sentiment_predictor.py's module docstring on why this
    is a heuristic, not a calibrated probability."""
    predictor = VaderSentimentPredictor()
    result = predictor.predict("This is somewhat disappointing.")

    idx = LABELS.index(result.label)
    for i, label in enumerate(LABELS):
        if abs(i - idx) > 1:
            assert result.probabilities[label] == 0.0
