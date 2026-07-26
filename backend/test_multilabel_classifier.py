import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer

from app.ml_models.multilabel_classifier import (
    train_multilabel_classifier,
    save_model,
    load_model,
)

# Sample Emails


texts = [
    "payment failed please help",
    "cannot login to my account",
    "invoice refund request",
    "password reset issue",
    "billing problem and login issue",
]


# Multi-label Targets
#
# Categories:
# 0 -> Billing
# 1 -> Technical
# ------------------------------------------------------------

labels = np.array([
    [1, 0],   # Billing
    [0, 1],   # Technical
    [1, 0],   # Billing
    [0, 1],   # Technical
    [1, 1],   # Billing + Technical
])


# TF-IDF


vectorizer = TfidfVectorizer()

X = vectorizer.fit_transform(texts)

# Train

model = train_multilabel_classifier(
    X_train=X,
    y_train_multilabel=labels,
)

# Save

save_model(
    model,
    "backend/models/multilabel_classifier.pkl",
)

print("\n[OK] Model saved successfully.")

# Load

loaded_model = load_model(
    "backend/models/multilabel_classifier.pkl",
)

print("[OK] Model loaded successfully.")

# Prediction

predictions = loaded_model.predict(X)

print("\nPredictions")

print(predictions)