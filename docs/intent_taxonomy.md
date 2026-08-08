# Intent Detection — Taxonomy (FR-33)

Canonical reference for the 9 intent classes. Taken directly from FR-33 —
no class was invented or renamed. **Multi-label**: an email may carry zero,
one, or several of these simultaneously (FR-34, confirmed by the PRD's own
"Complaint + Refund" example) — see `docs/intent_labeling_strategy.md` for
the full multi-label decision record.

## Two Naming Collisions With Existing Concepts (flagged explicitly, not silently reused)

1. **"Escalation"** here is an *intent class* — the email's purpose is to
   escalate ("please escalate this to your manager"). This is a different
   concept from Priority's existing `ESCALATION_KEYWORDS`
   (`app/feature_engineering/priority_keywords.py`), which is a *signal
   that raises the priority level* of an email regardless of its intent.
   An email can trigger Priority's escalation signal without having
   Escalation as its primary intent, and vice versa. No code is shared
   between the two; the collision is in the English word only.
2. **"Feedback"** here is an *intent class* — the email's purpose is to
   give feedback ("wanted to share some thoughts on the new dashboard").
   This is unrelated to this system's own feedback mechanism
   (`FeedbackLogger`, `POST /intent/feedback` — human corrections to a
   prediction). An email correcting an Intent prediction is not itself an
   example of the Feedback intent class.

## Class Definitions

| Class | Business meaning | Inclusion criteria | Exclusion criteria | Example |
|---|---|---|---|---|
| **Complaint** | Expressing dissatisfaction with a product, service, or experience. | Explicit or implicit dissatisfaction language, without necessarily requesting a specific remedy. | A request for a refund/cancellation IS also Complaint if dissatisfaction is expressed — but a purely neutral cancellation ("please cancel, no longer needed") is Cancel only, not Complaint. | "Your support team has been unhelpful for weeks." |
| **Inquiry** | Asking for information, without dissatisfaction or a transactional request. | Questions, requests for clarification or information. | A question embedded in a complaint ("why does this keep happening?") is Complaint-driven, not primarily Inquiry — judge by the dominant purpose. | "Does your product support SSO integration?" |
| **Request** | Asking for an action to be taken, not covered by a more specific class below. | General action requests not better described as Order/Cancel/Refund/Schedule. | If a more specific class applies (Order, Cancel, Refund, Schedule), use that instead — Request is the residual class for action-asks, not a catch-all default the way Category's "General" is (no PRD-specified default exists for Intent — see `docs/data_audit_intent.md` §5-equivalent decision in the labeling strategy doc). | "Could you please send over the updated contract?" |
| **Feedback** | Sharing an opinion or suggestion, unprompted, not a complaint. | Constructive or positive commentary about a product/service/experience. | Negative-toned commentary with a demand for remedy is Complaint, not Feedback — Feedback is offered, not demanded. | "Just wanted to say the new UI is a big improvement." |
| **Escalation** | Explicitly asking for the matter to be raised beyond the current contact. | "Please escalate," "speak to a manager/supervisor," "this needs senior attention," repeated follow-ups referencing prior unanswered contact. | See naming-collision note above — this is about the email's stated purpose, not a general urgency signal. | "This is my third email. Please escalate to your manager." |
| **Order** | Referring to placing, tracking, or asking about a product order. | Order numbers, purchase references, shipment/delivery tracking language. | A billing dispute about an existing order leans Billing/Refund territory (Category module) more than Order intent, unless the ask is specifically about the order's fulfillment status. | "Can you tell me the status of order #45821?" |
| **Cancel** | Requesting termination of a subscription, service, order, or appointment. | "Cancel," "terminate," "unsubscribe," "discontinue," "stop my subscription." | A cancellation combined with dissatisfaction is BOTH Cancel and Complaint (multi-label) — see FR-34. | "Please cancel my subscription effective immediately." |
| **Refund** | Requesting money back. | "Refund," "reimburse," "money back," "credit my account." | Distinguish from Billing-category disputes (Category module) that don't explicitly ask for money back (e.g., "this charge looks wrong" without an explicit refund ask) — borderline, annotator judgment call, documented as such rather than silently resolved. | "I'd like a refund for my last payment." |
| **Schedule** | Requesting or coordinating a meeting, call, or appointment time. | "Schedule," "reschedule," "meeting," "calendar," "available time," "book a call." | — | "Are you available for a call next Tuesday?" |

## Ambiguous / Borderline Cases (documented, not silently resolved)

- **"Please cancel my subscription and refund my last payment."** — the
  PRD's own worked example (§8.2). **Multi-label: Cancel + Refund.** This
  is the canonical case demonstrating why single-label would lose real
  information.
- **Complaint vs. Escalation**: a complaint that also demands manager
  involvement is both. A complaint with no such demand is Complaint only.
- **Request vs. Order/Cancel/Refund/Schedule**: Request is intentionally
  the residual/least-specific class — if a more specific class's criteria
  are met, prefer the specific class, following the same "don't over-use
  the generic bucket" discipline Priority's taxonomy already applies to
  its own "Medium" default class.
- **Inquiry vs. Request**: a question that is really asking for an action
  ("could you send me the invoice?") is Request, not Inquiry, even though
  it's phrased as a question — judge by the underlying ask, not surface
  grammar.

## Not a Business-Category Invention

Every class name and definition above traces directly to FR-33's verbatim
list. Borderline rules and examples are this phase's own elaboration
(same role `docs/data_audit_priority.md` §3's borderline rules play for
Priority) — flagged as elaboration, not presented as PRD text.
