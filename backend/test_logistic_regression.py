from sklearn.feature_extraction.text import TfidfVectorizer

from app.ml_models.logistic_regression_model import (
    train_logistic_regression,
    inspect_lr_weights,
    save_model,
    load_model,
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

# Train Logistic Regression

model = train_logistic_regression(
    X_train=X,
    y_train=labels,
)

# Save Model

save_model(
    model,
    "backend/models/logistic_regression.pkl",
)

print("\n✅ Model saved successfully.")

# Load Model

loaded_model = load_model(
    "backend/models/logistic_regression.pkl"
)

print("✅ Model loaded successfully.")

# Predictions

predictions = loaded_model.predict(X)

print("\nPredictions")
print(predictions)

# Prediction Probabilities

print("\nPrediction Probabilities")
print(loaded_model.predict_proba(X))

# Inspect Learned Weights

inspect_lr_weights(
    model=loaded_model,
    feature_names=vectorizer.get_feature_names_out().tolist(),
    n_top=5,
)