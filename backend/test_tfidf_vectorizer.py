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
    max_df=1.0,
)

vectorizer = TFIDFVectorizer(config)

X = vectorizer.fit_transform(texts)

print("Vocabulary")
print(vectorizer.get_feature_names())

print("\nTF-IDF Matrix")
print(X.toarray())

print("\nVocabulary Size")
print(vectorizer.vocabulary_size())

print("\nIDF Scores")
print(vectorizer.idf_scores())

# Save
vectorizer.save("backend/tfidf_vectorizer.pkl")

print("\nVectorizer Saved")

# Load
loaded = TFIDFVectorizer(config)
loaded.load("backend/tfidf_vectorizer.pkl")

print("\nLoaded Vocabulary")
print(loaded.get_feature_names())

print("\nTop Features")
print(vectorizer.top_features())