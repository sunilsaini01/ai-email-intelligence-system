from sklearn.feature_extraction.text import TfidfVectorizer
import pandas as pd

from app.ml_models.logistic_regression_model import train_logistic_regression
from app.ml_models.naive_bayes_model import train_naive_bayes
from app.ml_models.svm_model import train_svm

from app.evaluation.model_evaluator import evaluate_model


# Dataset

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

# Train Models

models = {
    "Logistic Regression": train_logistic_regression(X, labels),
    "Naive Bayes": train_naive_bayes(X, labels),
    "Linear SVM": train_svm(X, labels),
}

# Evaluate Models

results = []

for name, model in models.items():

    metrics = evaluate_model(
        model=model,
        X_test=X,
        y_test=labels,
    )

    results.append({
        "Model": name,
        "Accuracy": round(metrics["accuracy"], 4),
        "Precision": round(metrics["precision"], 4),
        "Recall": round(metrics["recall"], 4),
        "F1 Score": round(metrics["f1_score"], 4),
        "ROC-AUC": round(metrics.get("roc_auc", 0.0), 4),
    })

# Comparison Table

comparison = pd.DataFrame(results)

print("\n================ MODEL COMPARISON ================\n")

print(comparison.to_string(index=False))