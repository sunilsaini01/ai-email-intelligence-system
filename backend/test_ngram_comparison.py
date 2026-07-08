from app.vectorization.tfidf_vectorizer import (
    TFIDFConfig,
    TFIDFVectorizer,
)

texts = [
    "refund payment completed",
    "refund order cancelled",
    "payment successful",
    "cancel order now",
    "refund payment pending",
]

for n in [1, 2, 3]:

    config = TFIDFConfig(
        min_df=1,
        max_df=1.0,
        ngram_range=(1, n),
    )

    vectorizer = TFIDFVectorizer(config)

    vectorizer.fit(texts)

    print(f"\nN-gram (1,{n})")
    print("Vocabulary Size:", vectorizer.vocabulary_size())
    print(vectorizer.get_feature_names())