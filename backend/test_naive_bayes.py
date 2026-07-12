from sklearn.feature_extraction.text import TfidfVectorizer
from app.training.artifact_manager import ArtifactManager
from app.ml_models.naive_bayes_model import (
    train_naive_bayes,
    inspect_nb_features,
)

# Sample Dataset

texts = [
    "free money click here",
    "winner claim your prize",
    "meeting scheduled tomorrow",
    "project discussion today",
    "limited time offer",
    "regards thanks for update",
]

labels = [1, 1, 0, 0, 1, 0]

# TF-IDF Vectorization

vectorizer = TfidfVectorizer()

X = vectorizer.fit_transform(texts)

# Train Naive Bayes

model = train_naive_bayes(
    X_train=X,
    y_train=labels,
)

artifact_manager = ArtifactManager()

artifact_manager.save_model(
    model,
    "naive_bayes.joblib",
)

loaded_model = artifact_manager.load_model(
    "naive_bayes.joblib",
)

# Predictions

predictions = loaded_model.predict(X)

print("\nPredictions")
print(predictions)

# Prediction Probabilities

print("\nPrediction Probabilities")
print(loaded_model.predict_proba(X))

# Inspect Learned Features

inspect_nb_features(
    model=loaded_model,
    feature_names=vectorizer.get_feature_names_out().tolist(),
    n_top=5,
)