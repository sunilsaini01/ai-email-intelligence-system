"""
Phase 8 — Email Routing Engine: QUALITATIVE / EXPLORATORY evaluation.

============================================================================
NOT GROUND TRUTH, NOT A ROUTING-ACCURACY MEASUREMENT. 20 hand-written,
author-labelled examples run through the full RoutingService path (real
trained Spam/Category/Intent/Priority artifacts + zero-shot Sentiment +
the rule engine), used to surface failure patterns for
docs/error_analysis_routing.md -- same role and same scale as
qualitative_eval_intent.py/qualitative_eval_sentiment.py. Sampling method:
author-written to cover each department, each high-impact department, the
unreliable-Intent policy, spam/degenerate input, and signal-conflict cases
-- NOT randomly sampled from real traffic (none exists), NOT claimed
statistically representative of anything.
============================================================================

Run from the repo root (requires all four trained artifacts):
    PYTHONPATH=backend python backend/scripts/qualitative_eval_routing.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.routing_service import RoutingService

# (label, subject, body, sender_email, expected_department, expected_requires_review)
# expected_department is None only for the spam/quarantine case.
EXAMPLES = [
    ("Support: bug report", "App crashing", "The app crashes every time I try to log in. This is a bug.", "user@example.com", "Support", False),
    ("Sales: pricing inquiry", "Pricing", "Can you send me a quote for the enterprise plan? We're evaluating your product.", "lead@example.com", "Sales", False),
    ("Billing: refund request", "Refund", "Please refund my last invoice, I was charged twice for the same subscription.", "customer@example.com", "Billing", True),  # HIGH_IMPACT
    ("Legal: contract review", "Contract", "Legal has flagged a compliance issue in the data processing agreement -- please review before signing.", "counsel@example.com", "Legal", True),  # HIGH_IMPACT
    ("HR: workplace complaint", "Confidential", "I need to report a workplace harassment complaint regarding my manager.", "employee@enron.com", "HR", True),  # HIGH_IMPACT
    ("IT: access request", "VPN access", "My VPN access stopped working after the password reset. Can IT help?", "employee@enron.com", "IT", False),
    ("Marketing: press inquiry", "Press", "I'm a journalist requesting comment for a media inquiry about your recent product launch.", "press@example.com", "Marketing", False),
    ("General: no clear category", "Hi", "Just wanted to say hello and see how things are going.", "friend@gmail.com", "General", True),  # low/no evidence
    ("Escalation, corroborated by negative sentiment", "Third time asking", "This is absolutely unacceptable. I've emailed three times with no response -- please escalate this to your manager immediately.", "angry@example.com", None, True),
    ("Escalation, NOT corroborated", "FYI", "Please escalate this to the team when you get a chance, no rush.", "colleague@enron.com", None, False),
    ("Refund intent, non-Billing category", "Question", "Does your product support SSO? Also, could I get a refund if it doesn't work out?", "user@example.com", None, True),
    ("Spam-like content", "WIN FREE MONEY NOW", "CLICK HERE to claim your lottery winnings!!! Limited time, act now, free prize guaranteed!!!", "unknown@spamdomain.biz", None, None),  # quarantine expected but not asserted as ground truth
    ("Empty email", "", "", "", None, None),  # known edge case -- see docs/error_analysis_routing.md
    ("Critical priority, ambiguous category", "URGENT", "URGENT URGENT need help now", "vip@example.com", None, True),
    ("HTML email, billing", "<b>Invoice</b>", "<p>Please see attached <b>invoice</b> and process the <i>payment</i>.</p>", "billing@example.com", "Billing", True),  # HIGH_IMPACT
    ("Cancel + Complaint (multi-intent)", "Cancelling", "Cancelling my subscription -- your support has been unhelpful for weeks.", "exuser@example.com", None, None),
    ("Order status inquiry", "Order #45821", "Can you tell me the status of order #45821?", "customer@example.com", None, None),
    ("Internal sender, IT outage", "System down", "The internal server is down, this is affecting the whole team.", "admin@enron.com", "IT", False),
    ("Unicode/non-English content", "Frage", "Können Sie mir bitte eine Rechnung für den Kauf schicken? 😀", "user@example.de", None, None),
    ("Scheduling request", "Meeting", "Are you available for a call next Tuesday to discuss the proposal?", "prospect@example.com", None, None),
]


def main():
    service = RoutingService()

    print(f"{'Label':<48} {'Dept (pred/exp)':<28} {'Review (pred/exp)':<20} {'Action':<14} Rules")
    print("-" * 160)

    dept_matches = 0
    review_matches = 0
    dept_checked = 0
    review_checked = 0

    for label, subject, body, sender_email, expected_dept, expected_review in EXAMPLES:
        result = service.route(subject=subject, body=body, sender_email=sender_email)
        dept = result["department"]
        review = result["requires_human_review"]

        dept_str = f"{dept}/{expected_dept}"
        review_str = f"{review}/{expected_review}"

        if expected_dept is not None:
            dept_checked += 1
            if dept == expected_dept:
                dept_matches += 1
        if expected_review is not None:
            review_checked += 1
            if review == expected_review:
                review_matches += 1

        print(f"{label:<48} {dept_str:<28} {review_str:<20} {result['action']:<14} {result['matched_rules']}")

    print(
        f"\nDepartment match: {dept_matches}/{dept_checked} (only rows with a firm expectation). "
        f"Review-flag match: {review_matches}/{review_checked}. "
        f"Qualitative, n={len(EXAMPLES)}, not statistically meaningful -- see docs/error_analysis_routing.md."
    )


if __name__ == "__main__":
    main()
