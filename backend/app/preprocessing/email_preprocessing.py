import html
import re


def anonymize_pii(text: str) -> str:
    """
    Placeholder for now.
    Real PII masking later.
    """

    return text


def preprocess_email_body(raw_body: str) -> dict[str, str]:

    # Step 1 — Decode HTML entities
    text = html.unescape(raw_body)

    # Step 2 — Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Step 3 — Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    body_clean = text

    # Step 4 — Remove quoted replies
    text_no_quotes = re.sub(
        r"(^>.*$)",
        "",
        text,
        flags=re.MULTILINE
    )

    text_no_quotes = re.sub(
        r"On .{10,100} wrote:.*",
        "",
        text_no_quotes,
        flags=re.DOTALL
    )

    text_no_quotes = re.sub(
        r"\s+",
        " ",
        text_no_quotes
    ).strip()

    body_no_quotes = text_no_quotes

    # Step 5 — Remove signatures
    body_no_sig = re.split(
        r"\n--\s*\n",
        body_no_quotes
    )[0].strip()

    # Step 6 — PII anonymization
    body_anonymized = anonymize_pii(body_no_sig)

    return {
        "body_clean": body_clean,
        "body_no_quotes": body_no_quotes,
        "body_anonymized": body_anonymized,
    }