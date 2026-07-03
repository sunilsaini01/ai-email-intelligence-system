import hashlib
import pandas as pd


def make_dedup_key(row: dict) -> str:
    """
    Use message_id if available,
    otherwise hash body text.
    """

    if row.get("message_id"):
        return str(row["message_id"]).strip()

    body_sample = (row.get("body_text_raw") or "")[:500]

    return hashlib.md5(
        body_sample.encode("utf-8", errors="replace")
    ).hexdigest()


def remove_duplicates(df: pd.DataFrame) -> pd.DataFrame:

    df["dedup_key"] = df.apply(make_dedup_key, axis=1)

    before = len(df)

    df = df.drop_duplicates(subset=["dedup_key"])

    removed = before - len(df)

    print(f"[INFO] Removed {removed} duplicates")

    return df


def validate_after_ingestion(
    df: pd.DataFrame,
    source_name: str
) -> None:

    required_fields = [
        "body_text_raw"
    ]

    for field in required_fields:

        null_count = df[field].isna().sum()

        null_pct = (null_count / len(df)) * 100

        if null_pct > 5:
            print(
                f"[WARN] {source_name}: "
                f"{field} is {null_pct:.1f}% null"
            )
        else:
            print(
                f"[OK] {source_name}: "
                f"{field} nulls = {null_pct:.1f}%"
            )

    print(
        f"[INFO] {source_name}: "
        f"{len(df):,} records loaded"
    )