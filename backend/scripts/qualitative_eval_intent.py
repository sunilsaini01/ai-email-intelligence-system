"""
Phase 7B — Intent Detection: QUALITATIVE / EXPLORATORY evaluation.

============================================================================
NOT GROUND TRUTH. Same role as qualitative_eval_sentiment.py -- 14
hand-written, author-labelled examples run through the full IntentService
path (preprocessing + trained classifier + entity extraction), used to
surface failure patterns for docs/error_analysis_intent.md, not to compute
a trustworthy accuracy number.
============================================================================

Run from the repo root (requires artifacts/intent_baseline.joblib):
    PYTHONPATH=backend python backend/scripts/qualitative_eval_intent.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.intent_service import IntentService

# (category, subject, body, intended intents)
EXAMPLES = [
    ("Simple inquiry", "Question", "Does your product support SSO integration?", {"Inquiry"}),
    ("Simple complaint", "Not happy", "Your support team has been unhelpful for weeks.", {"Complaint"}),
    ("Simple request", "Contract", "Could you please send over the updated contract?", {"Request"}),
    ("Cancel + Refund (PRD's own example)", "Cancel", "Please cancel my subscription and refund my last payment.", {"Cancel", "Refund"}),
    ("Order status", "Order status", "Can you tell me the status of order #45821?", {"Order"}),
    ("Escalation", "Escalate", "This is my third email. Please escalate to your manager.", {"Escalation"}),
    ("Schedule", "Meeting", "Are you available for a call next Tuesday?", {"Schedule"}),
    ("Feedback (positive, not a complaint)", "Nice work", "Just wanted to say the new UI is a big improvement.", {"Feedback"}),
    ("Complaint + Escalation", "Unacceptable", "This is unacceptable. Please escalate this to your manager immediately.", {"Complaint", "Escalation"}),
    ("Polite complaint (no explicit complaint word)", "Following up", "I would really appreciate it if this could finally be looked into, as it has been affecting our workflow for weeks.", {"Complaint"}),
    ("Indirect request phrased as a question", "Quick ask", "Could you send me the invoice for last month?", {"Request"}),
    ("Short, ambiguous", "Hi", "Thanks!", set()),
    ("No intent (pure FYI)", "FYI", "The meeting notes from yesterday are attached for your records.", set()),
    ("False-positive risk: 'order' as ordinary word, not purchase intent", "Process", "In order to proceed, please confirm receipt of this email.", set()),
]


def main():
    service = IntentService()
    correct = 0

    print(f"{'Category':<55} {'Predicted':<40} {'Intended':<30} Match")
    print("-" * 145)
    for category, subject, body, intended in EXAMPLES:
        result = service.analyze(subject=subject, body=body)
        predicted = {i["intent"] for i in result["intents"]}
        match = "YES" if predicted == intended else "no"
        if predicted == intended:
            correct += 1
        print(f"{category:<55} {str(sorted(predicted)):<40} {str(sorted(intended)):<30} {match}")

    print(f"\n{correct}/{len(EXAMPLES)} exact-set matches (qualitative, not statistically meaningful at n=14).")


if __name__ == "__main__":
    main()
