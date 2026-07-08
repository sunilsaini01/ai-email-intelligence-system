from app.vectorization.bow_vectorizer import (
    BoWConfig,
    BoWVectorizer,
)

texts = [
    "refund payment",
    "cancel order",
    "refund order",
]

config = BoWConfig(
    min_df=1,
    max_df=1.0
)

vectorizer = BoWVectorizer(config)

X = vectorizer.fit_transform(texts)

print("Vocabulary")
print(vectorizer.get_feature_names())

print("\nVectors")
print(X.toarray())

print("\nVocabulary Size")
print(vectorizer.vocabulary_size())

# Save
vectorizer.save("backend/vectorizer.pkl")

print("\nVectorizer Saved")

# Load
loaded = BoWVectorizer(config)
loaded.load("backend/vectorizer.pkl")

print("\nLoaded Vocabulary")
print(loaded.get_feature_names())