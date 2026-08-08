import re

# ----------------------------------------
# URL Detection
# ----------------------------------------

URL_PATTERN = re.compile(
    r"http[s]?://\S+|www\.\S+",
    re.IGNORECASE,
)

# ----------------------------------------
# Email Detection
# ----------------------------------------

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# ----------------------------------------
# Phone Number Detection
# ----------------------------------------

PHONE_PATTERN = re.compile(
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b|\+\d{1,3}\s?\d{6,12}\b"
)

# ----------------------------------------
# Currency Detection
# ----------------------------------------

CURRENCY_PATTERN = re.compile(
    r"[$£€¥₹]\s*[\d,]+(?:\.\d+)?"
    r"|[\d,]+(?:\.\d+)?\s*[$£€¥₹]"
    # Spelled-out amounts ("15000 dollars", "4,200.50 USD") -- added for
    # Module 5 / FR-26's preservation check (app/nlp/summary_grounding.py):
    # the symbol-only pattern above missed these entirely, which silently
    # understated how many monetary amounts a source email actually
    # contained and made preservation look worse than it was.
    r"|[\d,]+(?:\.\d+)?\s*(?:dollars?|usd|pounds?|gbp|euros?|eur|rupees?|inr)\b",
    re.IGNORECASE,
)

# ----------------------------------------
# Sentence Split Pattern
# ----------------------------------------

SENTENCE_PATTERN = re.compile(
    r"[.!?]+"
)

# ----------------------------------------
# Date Detection (Module 5 / FR-26 — summaries must preserve dates)
# ----------------------------------------
# Deliberately covers common written-English date shapes rather than every
# ISO/locale variant — this is used for FR-26's preservation check (did a
# date visible in the source text survive into the summary?), not for
# calendar parsing, so a few missed exotic formats are an acceptable,
# disclosed gap (see docs/model_cards/email_summarization.md "Entity
# Preservation"), not a silent correctness bug.
DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"  # 08/14/2026, 14-08-26
    r"|\d{4}-\d{2}-\d{2}"  # 2026-08-14 (ISO)
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?"
    r"|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?"  # August 14th, 2026 / Aug 14
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?"
    r"|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?"
    r"|Nov(?:ember)?|Dec(?:ember)?)(?:,?\s+\d{4})?"  # 14th August 2026
    r"|\b(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)(?:day)?\b)",  # Friday
    re.IGNORECASE,
)

# ----------------------------------------
# Order ID Detection (Module 7 / FR-35 — intent entity extraction)
# ----------------------------------------
# Covers the PRD's own worked example ("order #45821") plus common written
# variants ("order number 45821", "order no. 45821", "order: 45821",
# "order no. AB-9910"). Deliberately requires an explicit "order" cue word
# rather than matching any bare "#12345" — a bare hash-number is ambiguous
# (could be a ticket ID, a phone extension, anything) and matching it
# unconditionally would produce false positives on non-order numeric
# references. A disclosed recall gap (an order ID mentioned without any
# "order" cue word nearby would be missed), not a precision-vs-recall
# tuning left unresolved.
#
# The captured token is additionally required (via lookahead) to contain
# at least one digit -- found necessary during Phase 7B testing: without
# this, "in order to proceed" matched "to" as a 2-character "order ID",
# a real false positive the qualitative error analysis specifically
# flagged as a risk (docs/error_analysis_intent.md). Genuine order IDs
# contain a number; ordinary words following "order" (to, that, this) do
# not.
ORDER_ID_PATTERN = re.compile(
    r"\border\s*(?:#|number|no\.?|:)?\s*#?\s*((?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]{2,20})\b",
    re.IGNORECASE,
)