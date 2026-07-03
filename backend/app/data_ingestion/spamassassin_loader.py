import os
import email
from email.message import Message
from pathlib import Path
from typing import Generator

def load_spamassassin(
    data_dir: str,
    encoding: str = "latin-1"
) -> Generator[dict, None, None]:
    """
    Load SpamAssassin corpus. Each folder maps to a label.
    Yields one dict per email.

    Why latin-1: many 2002-era emails use ISO-8859-1 encoding.
    UTF-8 strict will throw UnicodeDecodeError on ~15% of files.
    latin-1 never fails (it's a superset of ASCII) and is the
    correct fallback for this corpus.
    """
    label_map = {
        "spam": "spam",
        "spam_2": "spam",
        "easy_ham": "ham",
        "easy_ham_2": "ham",
        "hard_ham": "ham",   # Still ham — important edge cases
    }

    for folder_name, label in label_map.items():
        folder_path = Path(data_dir) / folder_name
        if not folder_path.exists():
            continue

        for file_path in folder_path.iterdir():
            if not file_path.is_file():
                continue

            try:
                raw = file_path.read_bytes()
                msg = email.message_from_bytes(raw)

                # Extract body — handles multipart
                body = _extract_body(msg, encoding)

                yield {
                    "email_id": None,          # Assigned later in pipeline
                    "source": "spamassassin",
                    "source_file": str(file_path),
                    "spam_label": label,
                    "is_hard_case": folder_name == "hard_ham",
                    "subject_raw": msg.get("Subject", ""),
                    "sender_email": msg.get("From", ""),
                    "received_at": msg.get("Date", ""),
                    "body_text_raw": body,
                    "message_id": msg.get("Message-ID", ""),
                }

            except Exception as e:
                # Log and continue — do not crash the pipeline on one bad file
                print(f"[WARN] Failed to parse {file_path}: {e}")
                continue


def _extract_body(msg: Message, encoding: str) -> str:
    """
    Extract plain text body from email, handling multipart.
    Prefers text/plain over text/html.
    Falls back to decoding bytes with error replacement.
    """
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(encoding, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(encoding, errors="replace")
    return ""