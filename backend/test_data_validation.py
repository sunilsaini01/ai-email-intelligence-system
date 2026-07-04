import pandas as pd

from app.validation.data_validation import (
    validate_corpus
)

data = {
    "email_id": [
        1,
        2,
        2
    ],

    "body_clean": [
        "Hello world",
        "",
        "Spam message"
    ],

    "body_anonymized": [
        "Hello world",
        "",
        "Spam message"
    ],

    "spam_label": [
        "ham",
        "spam",
        "wrong_label"
    ]
}

df = pd.DataFrame(data)

results = validate_corpus(df)