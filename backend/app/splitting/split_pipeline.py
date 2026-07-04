import pandas as pd
from sklearn.model_selection import train_test_split


def assign_corpus_splits(
    df: pd.DataFrame,
    val_size: float = 0.10,
    test_size: float = 0.10,
    random_state: int = 42,
) -> pd.DataFrame:
    """
    Assign train/val/test splits once.
    """

    train_val, test = train_test_split(
        df["email_id"],
        test_size=test_size,
        random_state=random_state,
    )

    train, val = train_test_split(
        train_val,
        test_size=val_size / (1 - test_size),
        random_state=random_state,
    )

    split_df = pd.DataFrame({
        "email_id": df["email_id"]
    })

    split_df["split"] = "train"

    split_df.loc[
        split_df["email_id"].isin(val),
        "split"
    ] = "val"

    split_df.loc[
        split_df["email_id"].isin(test),
        "split"
    ] = "test"

    return split_df