from sklearn.feature_extraction.text import TfidfVectorizer

from app.ml_models.logistic_regression_model import (
    train_logistic_regression,
)

from app.evaluation.model_evaluator import (
    evaluate_model,
    print_evaluation,
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

# TF-IDF

vectorizer = TfidfVectorizer()

X = vectorizer.fit_transform(texts)

# Train Logistic Regression

model = train_logistic_regression(
    X_train=X,
    y_train=labels,
)

# Evaluate

results = evaluate_model(
    model=model,
    X_test=X,
    y_test=labels,
)

print_evaluation(results)