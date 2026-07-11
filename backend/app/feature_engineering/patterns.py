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
    r"[$£€¥₹]\s*[\d,]+|[\d,]+\s*[$£€¥₹]"
)

# ----------------------------------------
# Sentence Split Pattern
# ----------------------------------------

SENTENCE_PATTERN = re.compile(
    r"[.!?]+"
)