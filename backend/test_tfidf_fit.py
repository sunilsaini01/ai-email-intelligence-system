from app.vectorization.tfidf_vectorizer import (
    TFIDFConfig,
    TFIDFVectorizer,
)

texts = [
    "refund payment",
    "cancel order",
    "refund order",
]

config = TFIDFConfig(
    min_df=1,
)

vectorizer = TFIDFVectorizer(config)

# Step 1: Learn vocabulary
vectorizer.fit(texts)

# Step 2: Transform texts
X = vectorizer.transform(texts)

print("Vocabulary")
print(vectorizer.get_feature_names())

print("\nMatrix Shape")
print(X.shape)