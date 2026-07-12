from sklearn.feature_extraction.text import TfidfVectorizer

from app.ml_models.hyperparameter_tuning import (
    tune_logistic_regression,
    print_best_parameters,
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

# Hyperparameter Tuning

grid_search = tune_logistic_regression(
    X_train=X,
    y_train=labels,
)

# Best Parameters

print_best_parameters(grid_search)

# Best Model

best_model = grid_search.best_estimator_

print("\n========== BEST MODEL ==========")
print(best_model)