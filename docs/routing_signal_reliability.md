# Routing Signal Reliability Audit (Module 8 / Phase 8)

Single source of truth: `backend/app/routing/signal_reliability.py`. This
document explains each row; it does not re-derive the classification —
routing does not re-evaluate an upstream model's evidence quality, it only
labels and propagates what each module already disclosed.

| Signal | Source | Data Quality | Validation | Domain Match | Failure Modes | Operational Risk | Routing Policy |
|---|---|---|---|---|---|---|---|
| **Spam** | `SpamPredictor` (TF-IDF + calibrated SVM) | Real labelled data (SpamAssassin/SMS Spam/Amazon corpora) | 99.44% recall / 91.33% precision, measured | Real spam/ham email text | Threshold tuned to 0.06 for recall — trades precision for near-zero missed spam; **empty/degenerate input can be classified as spam** (verified: `SpamService().classify("", "")` → `is_spam=True`, see `docs/error_analysis_routing.md`) | Low — this system's one real, PRD-relevant metric | **Hard gate.** `is_spam=True` → quarantine, no department routing, pre-empts every other signal (`R-SPAM-GATE`). |
| **Category** | `CategoryPredictor` (TF-IDF + features + OvR SVM) | Real Enron text, **synthetic/heuristic labels** | Pipeline-validated only, not human-validated (`docs/data_audit_categorization.md`) | Real email, but B2B energy-trading corpus, not the deploying org's actual traffic | No calibration check performed (unlike spam/priority) | Medium — primary department-selection signal | **Primary evidence.** Auto-routes above `CATEGORY_AUTO_ROUTE_THRESHOLD` (0.55, HEURISTIC); below it, or tied with the runner-up, routes to human review as a candidate only. |
| **Priority** | `PriorityPredictor` (TF-IDF + features + LogReg) | Real Enron text, synthetic/heuristic labels | Pipeline-validated only (`docs/data_audit_priority.md`) | Same Enron caveat as Category | 4-class argmax, no threshold tuning | Low-medium — never selects a department | **Urgency modifier only.** `Critical` on a low-confidence auto-route downgrades to human review (`R-CRITICAL-PRIORITY-CONFIDENCE-CHECK`); never chooses or overrides a department. |
| **Sentiment** | `VaderSentimentPredictor` (zero-shot VADER lexicon) | No training/fitting to any dataset at all | **No ground truth exists to validate against, on any domain** (`docs/data_audit_sentiment.md`) | Domain-agnostic lexicon, never adapted to email or this org | Cannot detect sarcasm, indirect negativity, politeness-masked complaints (`docs/error_analysis_sentiment.md`, 5/14 qualitative) | Low-medium — never selects a department | **Urgency modifier only**, weaker footing than Priority. Negative/Very Negative on a borderline auto-route (within 0.10 of threshold) downgrades to human review (`R-BORDERLINE-CONFIDENCE-NEGATIVE-SENTIMENT`). Never chooses a department. |
| **Intent** | `IntentPredictor` (TF-IDF-only OvR LogReg) | Real Enron text, synthetic/heuristic labels | Pipeline-validated only (`docs/data_audit_intent.md`) | Order/Refund/Cancel are consumer-transactional concepts largely absent from Enron's B2B corpus — worse domain mismatch than Category/Priority | **Escalation**: fires on unrelated text AND misses its own target case (`docs/error_analysis_intent.md`). **Refund**: F1 = 0.0 on its own test set. | High if trusted naively — this is exactly why RULE 4 exists | **Corroborating evidence only, with the two unreliable classes explicitly restricted.** See "Unreliable Intent Policy" in `docs/routing_conflict_resolution.md`. Never selects or overrides a department by itself. |
| **Keywords** | `app/routing/keyword_matcher.py`, reusing `CATEGORY_KEYWORDS` | Deterministic, word-boundary-safe regex | Not a probability; not calibrated against anything | Same hand-built lexicon Category's synthetic-label generator uses | False negatives on paraphrased text with no literal keyword match | Low — only used when Category is unavailable | **Fallback only**, and even then never auto-routes — `R-CATEGORY-UNAVAILABLE-KEYWORD-FALLBACK` always sets `human_review`. |
| **Sender domain** | `app/routing/sender_domain.py`, reusing `FREEMAIL_DOMAINS`/`INTERNAL_DOMAINS` | Static, hand-maintained sets (`INTERNAL_DOMAINS` currently only `enron.com` — must be reconfigured per deployment) | Not applicable — not a model | N/A | Malformed/absent sender → `"unknown"`, never raises; classification call itself failure-isolated (falls back to `"unknown"`, recorded in `upstream_failures`) | Low | **Corroborating signal, narrowly scoped.** `external` + a HIGH_IMPACT department (HR/Legal/Billing) adds `R-EXTERNAL-SENDER-HIGH-IMPACT-REVIEW` to the audit trail (`docs/routing_rules.md`) — never selects or overrides a department, and has no effect at all for non-HIGH_IMPACT departments (Phase 8 brief SS26: "do not make security decisions based solely on a sender domain" — this rule doesn't; it only ever adds a review-supporting reason where review was already effectively mandatory). |

## Reliability Labels Used in API Responses

Every entry in a `/routing/predict` response's `supporting_signals` carries
one of these labels (`app/routing/signal_reliability.py`):

| Label | Meaning |
|---|---|
| `validated` | Real labelled data, measured performance (Spam only) |
| `provisional_synthetic` | Real email text, heuristically-fabricated labels (Category, Priority, Intent) |
| `unvalidated` | No ground truth exists at all to validate against (Sentiment) |
| `heuristic` | Deterministic but not a calibrated probability (Keywords) |
| `informational` | Never a routing decision by itself (Sender domain) |

## What This Table Deliberately Does NOT Claim

No composite "trust score" numerically blends these rows into a single
number (see `docs/routing_conflict_resolution.md` "No Composite
RoutingScore"). A model trained on poor labels can be highly confident and
still wrong — `Routing Trust = Model Confidence × Data Reliability × Domain
Validity` is a conceptual principle this table and the rule engine embody
through discrete policy (gating, downgrading, requiring corroboration), not
a literal formula with invented weights.
