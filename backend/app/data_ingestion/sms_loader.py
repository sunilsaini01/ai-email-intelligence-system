import pandas as pd


def load_sms_spam(csv_path: str) -> pd.DataFrame:

    df = pd.read_csv(
        csv_path,
        encoding="latin-1"
    )

    # Keep only required columns
    df = df[["v1", "v2"]]

    # Rename columns
    df.columns = ["label", "text"]

    # Keep valid labels only
    df = df[df["label"].isin(["spam", "ham"])]

    # Standardized schema
    df["spam_label"] = df["label"]

    df["source"] = "sms_spam"

    df["is_email"] = False

    df["body_text_raw"] = df["text"].fillna("")

    return df[[
        "source",
        "spam_label",
        "body_text_raw",
        "is_email"
    ]]