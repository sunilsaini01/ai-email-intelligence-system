import pandas as pd
import email as email_lib


def _extract_body_text(msg):

    if msg.is_multipart():

        for part in msg.walk():

            content_type = part.get_content_type()

            if content_type == "text/plain":

                payload = part.get_payload(decode=True)

                if payload:

                    return payload.decode(
                        errors="replace"
                    )

    else:

        payload = msg.get_payload(decode=True)

        if payload:

            return payload.decode(
                errors="replace"
            )

    return ""


def load_enron_kaggle(csv_path: str) -> pd.DataFrame:

    df = pd.read_csv(
        csv_path,
        encoding="latin-1"
    )

    df = df.dropna(subset=["message"])

    df = df.drop_duplicates(subset=["message"])

    records = []

    for _, row in df.iterrows():

        try:

            msg = email_lib.message_from_string(
                row["message"]
            )

            records.append({

                "source": "enron",

                "source_file": row.get("file", ""),

                "message_id": msg.get("Message-ID", ""),

                "sender_email": msg.get("From", ""),

                "subject_raw": msg.get("Subject", ""),

                "received_at": msg.get("Date", ""),

                "recipient_to": msg.get("To", ""),

                "body_text_raw": _extract_body_text(msg),

                "x_folder": msg.get("X-Folder", ""),

                "x_origin": msg.get("X-Origin", ""),
            })

        except Exception as e:

            print(f"[WARN] {e}")

            continue

    return pd.DataFrame(records)