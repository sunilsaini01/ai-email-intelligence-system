from sklearn.feature_extraction.text import TfidfVectorizer
from app.training.artifact_manager import ArtifactManager
from app.ml_models.svm_model import (
    train_svm,
    inspect_svm_weights,
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

# Train SVM

model = train_svm(
    X_train=X,
    y_train=labels,
)

artifact_manager = ArtifactManager()

artifact_manager.save_model(
    model,
    "svm.joblib",
)

loaded_model = artifact_manager.load_model(
    "svm.joblib",
)

# Predictions

predictions = loaded_model.predict(X)

print("\nPredictions")
print(predictions)

# Prediction Probabilities

print("\nPrediction Probabilities")

print(
    loaded_model.predict_proba(X)
)

# Inspect Learned Weights

inspect_svm_weights(
    model=loaded_model,
    feature_names=vectorizer.get_feature_names_out().tolist(),
    n_top=5,
)