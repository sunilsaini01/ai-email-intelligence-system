import pandas as pd

from app.analysis.eda import (
    plot_class_distribution,
    analyze_text_length,
    analyze_nulls,
    analyze_source_distribution
)

data = {

    "body_clean": [
        "Hello this is normal email",
        "Win money now",
        "",
        "Important urgent issue"
    ],

    "spam_label": [
        "ham",
        "spam",
        "spam",
        "ham"
    ],

    "data_source": [
        "enron",
        "sms_spam",
        "enron",
        "amazon"
    ]
}

df = pd.DataFrame(data)

plot_class_distribution(
    df,
    "spam_label",
    "Spam Distribution"
)

analyze_text_length(df)

analyze_nulls(df)

analyze_source_distribution(df)