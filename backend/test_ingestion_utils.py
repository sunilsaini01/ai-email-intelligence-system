import pandas as pd

from app.data_ingestion.ingestion_utils import (
    remove_duplicates,
    validate_after_ingestion
)

data = {
    "message_id": [
        "1",
        "1",
        None
    ],
    "body_text_raw": [
        "Hello world",
        "Hello world",
        "Spam message"
    ]
}

df = pd.DataFrame(data)

print("\nBEFORE:")
print(len(df))

df = remove_duplicates(df)

print("\nAFTER:")
print(len(df))

validate_after_ingestion(
    df,
    "test_dataset"
)