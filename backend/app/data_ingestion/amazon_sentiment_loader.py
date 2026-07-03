import pandas as pd


def load_amazon_sentiment(
    csv_path: str,
    num_samples: int = 100_000
) -> pd.DataFrame:

    df = pd.read_csv(
        csv_path,
        header=None,
        names=["label", "title", "content"],
        encoding="latin-1"
    )

    # Take subset for initial experimentation
    df = df.head(num_samples)

    # Original labels:
    # 1 = negative
    # 2 = positive

    label_map = {
        1: "Negative",
        2: "Positive"
    }

    df["sentiment_label"] = df["label"].map(label_map)

    df["sentiment_confidence"] = 0.75

    df["source"] = "amazon_polarity"

    df["body_text_raw"] = (
        df["title"].fillna("") + " " +
        df["content"].fillna("")
    )

    df["is_email"] = False

    return df[[
        "source",
        "body_text_raw",
        "sentiment_label",
        "sentiment_confidence",
        "is_email"
    ]]