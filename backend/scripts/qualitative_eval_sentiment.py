"""
Phase 7A — Sentiment Analysis: QUALITATIVE / EXPLORATORY evaluation.

============================================================================
NOT GROUND TRUTH. These 14 examples were hand-written for this phase, each
labelled with the author's own judgment of intended sentiment -- not
annotated by a third party, not measured for inter-rater agreement. This is
qualitative/exploratory evaluation only (per this phase's own Gate 20), used
to surface failure PATTERNS worth documenting (docs/error_analysis_sentiment.md),
not to compute a trustworthy accuracy number. Separate from, and not mixed
into, data/processed/sentiment_synthetic_v1's VADER-labelled dataset.
============================================================================

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/qualitative_eval_sentiment.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.sentiment_predictor import VaderSentimentPredictor
from app.preprocessing.email_preprocessor import SENTIMENT_CONFIG, EmailPreprocessor

# (category, text, author's intended label)
EXAMPLES = [
    ("Positive email", "Thanks so much for the quick turnaround -- this is exactly what we needed.", "Positive"),
    ("Negative email", "I'm frustrated that this issue is still unresolved after two weeks.", "Negative"),
    ("Neutral email", "Please find attached the updated schedule for next week's meetings.", "Neutral"),
    ("Polite complaint", "I would really appreciate it if this could be looked into, as it has been affecting our workflow for some time now.", "Negative"),
    ("Indirect complaint", "I noticed the report was submitted a bit later than usual again this month.", "Negative"),
    ("Mixed sentiment", "The new dashboard looks great, but the login process is still broken and it's costing us time every day.", "Negative"),
    ("Short email (positive)", "Sounds good, thanks!", "Positive"),
    ("Short email (negative)", "Not acceptable.", "Negative"),
    (
        "Long email (measured, professional)",
        "Following our conversation last week, I wanted to provide an update on the project timeline. "
        "We have completed the initial phase of development and are now moving into the testing period. "
        "The team has identified a few minor issues that will need to be addressed before we can proceed "
        "to the next milestone. We anticipate these will be resolved within the next few days. Please let "
        "me know if you have any questions or would like to schedule a call to discuss further.",
        "Neutral",
    ),
    (
        "Forwarded thread (original sender's anger buried in a quote)",
        "FYI, see below.\n\n---------- Forwarded message ----------\nFrom: Customer\n"
        "This is completely unacceptable, I am furious and demand a refund immediately.",
        "Neutral",  # the FORWARDING sender's own text carries no sentiment -- see annotation guidelines §1
    ),
    ("Business email (escalation, formal register)", "Per our SLA, this ticket should have been resolved within 24 hours. Please escalate to your manager if this cannot be addressed today.", "Negative"),
    ("Customer-support email (satisfied resolution)", "Just wanted to say the support team resolved my issue quickly and professionally. Really appreciate it.", "Very Positive"),
    ("Sarcasm", "Oh great, ANOTHER outage. Really loving this service.", "Very Negative"),
    ("Very negative, explicit escalation", "This is the third time you've failed to fix this. I am cancelling my contract and escalating to legal.", "Very Negative"),
]


def main():
    predictor = VaderSentimentPredictor()
    # Routed through the SAME preprocessing SentimentService actually uses
    # (subject+body -> EmailPreprocessor(SENTIMENT_CONFIG).process() ->
    # predict) -- an earlier version of this script called the predictor
    # directly on raw text, which meant it wasn't exercising quote/signature
    # stripping at all and silently understated what the served API does.
    preprocessor = EmailPreprocessor(SENTIMENT_CONFIG)
    correct = 0

    print(f"{'Category':<45} {'Predicted':<15} {'Intended':<15} {'Match':<6} Compound")
    print("-" * 110)
    for category, text, intended in EXAMPLES:
        cleaned = preprocessor.process(text)
        result = predictor.predict(cleaned)
        match = "YES" if result.label == intended else "no"
        if result.label == intended:
            correct += 1
        print(f"{category:<45} {result.label:<15} {intended:<15} {match:<6} conf={result.confidence}")

    print(f"\n{correct}/{len(EXAMPLES)} matched the author's intended label (qualitative, not statistically meaningful at n=14).")


if __name__ == "__main__":
    main()
