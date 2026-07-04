import pandas as pd

from backend.app.preprocessing.email_preprocessing import preprocess_email_body
from backend.app.security.pii_anonymizer import anonymize_email_body

# ─────────────────────────────────────────
# TEST 1 — HTML stripping
# ─────────────────────────────────────────

def test_html_stripping():
    raw = "<p>Hello <b>World</b></p>"

    result = preprocess_email_body(raw)

    assert "<" not in result["body_clean"]
    assert "Hello" in result["body_clean"]
    assert "World" in result["body_clean"]


# ─────────────────────────────────────────
# TEST 2 — quoted reply removal
# ─────────────────────────────────────────

def test_quoted_reply_removal():
    raw = (
        "Thanks for your response.\n\n"
        "On Mon 14 Jun, John wrote:\n"
        "> I can help you."
    )

    result = preprocess_email_body(raw)

    assert "John wrote" not in result["body_no_quotes"]
    assert "Thanks for your response" in result["body_no_quotes"]


# ─────────────────────────────────────────
# TEST 3 — empty input
# ─────────────────────────────────────────

def test_empty_input_handled():
    result = preprocess_email_body("")

    assert result["body_clean"] == ""
    assert result["body_no_quotes"] == ""


# ─────────────────────────────────────────
# TEST 4 — PII anonymization
# ─────────────────────────────────────────

def test_pii_removed_before_api_use():
    text = "Please charge my card 4532-1234-5678-9012"

    anon_text, _ = anonymize_email_body(text)

    assert "4532" not in anon_text

