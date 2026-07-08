"""
Utility helper functions for email text preprocessing.
These functions are reused by the main preprocessing pipeline.
"""

import re
import html
import spacy

from bs4 import BeautifulSoup
from nltk.corpus import stopwords

# ---------------------------------------------------
# Load spaCy only once
# ---------------------------------------------------

nlp = spacy.load(
    "en_core_web_sm",
    disable=["parser", "ner"]
)

# ---------------------------------------------------
# Stopwords
# ---------------------------------------------------

STOP_WORDS = set(stopwords.words("english"))

NEGATION_WORDS = {
    "not",
    "no",
    "never",
    "none",
    "cannot",
    "can't",
    "won't",
    "don't",
    "doesn't",
    "didn't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "hasn't",
    "haven't"
}

SAFE_STOP_WORDS = STOP_WORDS - NEGATION_WORDS


# ===================================================
# 1. Safe Decode
# ===================================================

def safe_decode(raw_bytes: bytes) -> str:
    """
    Decode raw email bytes safely.
    UTF-8 first.
    Latin-1 fallback.
    """

    try:
        return raw_bytes.decode("utf-8")

    except UnicodeDecodeError:
        return raw_bytes.decode(
            "latin-1",
            errors="replace"
        )


# ===================================================
# 2. Strip HTML
# ===================================================

def strip_html(text: str) -> str:

    if not text:
        return ""

    text = html.unescape(text)

    soup = BeautifulSoup(text, "html.parser")

    for tag in soup(["style", "script", "head", "meta", "link"]):
        tag.decompose()

    return soup.get_text(
        separator=" ",
        strip=True
    )


# ===================================================
# 3. Remove Quoted Replies
# ===================================================

def remove_quoted_replies(text: str) -> str:

    if not text:
        return ""

    # Gmail / Apple Mail
    text = re.sub(
        r"On .{10,200}wrote:\s*",
        "",
        text,
        flags=re.DOTALL
    )

    # Outlook
    text = re.sub(
        r"(-{3,}|_{3,})\s*(Original Message|Forwarded Message).*",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Lines starting with >
    text = re.sub(
        r"^>.*$",
        "",
        text,
        flags=re.MULTILINE
    )

    return text.strip()


# ===================================================
# 4. Remove Signature
# ===================================================

def remove_signature(text: str) -> str:

    if not text:
        return ""

    parts = re.split(
        r"\n--\s*\n",
        text,
        maxsplit=1
    )

    return parts[0].strip()


# ===================================================
# 5. Normalize URLs
# ===================================================

URL_PATTERN = re.compile(r"http[s]?://\S+")


def normalize_urls(
    text: str,
    replacement: str = "URL_TOKEN"
) -> str:

    if not text:
        return ""

    return URL_PATTERN.sub(
        replacement,
        text
    )


# ===================================================
# 6. Normalize Whitespace
# ===================================================

def normalize_whitespace(text: str) -> str:

    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# ===================================================
# 7. Lowercase
# ===================================================

def lowercase(text: str) -> str:

    if not text:
        return ""

    return text.lower()


# ===================================================
# 8. Lemmatization
# ===================================================

def lemmatize(text: str) -> str:

    if not text:
        return ""

    doc = nlp(text)

    tokens = []

    for token in doc:

        if token.is_space:
            continue

        if token.is_punct:
            continue

        tokens.append(token.lemma_.lower())

    return " ".join(tokens)


# ===================================================
# 9. Stopword Removal
# ===================================================

def remove_stopwords(text: str) -> str:

    if not text:
        return ""

    tokens = []

    for word in text.split():

        if word not in SAFE_STOP_WORDS:
            tokens.append(word)

    return " ".join(tokens)