import pandas as pd

from app.splitting.split_pipeline import (
    assign_corpus_splits,
)

df = pd.DataFrame({
    "email_id": [
        "e1",
        "e2",
        "e3",
        "e4",
        "e5",
        "e6",
        "e7",
        "e8",
        "e9",
        "e10",
    ]
})

split_df = assign_corpus_splits(df)

print(split_df)

print("\nSPLIT COUNTS:")
print(split_df["split"].value_counts())