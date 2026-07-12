import numpy as np
from sklearn.linear_model import LogisticRegression

def train_logistic_regression(
    X_train,
    y_train,
    C: float = 1.0,
    penalty: str = "l2",
    max_iter: int = 1000,
    class_weight: str = "balanced",
) -> LogisticRegression:
        """
        Train a Logistic Regression model for email classification.
        """
        model = LogisticRegression(
            C=C,
            solver="saga",
            max_iter=max_iter,
            class_weight=class_weight,
            random_state=42,
        )
    
        model.fit(
        X_train,
        y_train,
    )
        return model
    
    

def inspect_lr_weights(
    model: LogisticRegression,
    feature_names: list[str],
    n_top: int = 20,
    class_name: str = "spam",
) -> None:
    """
    Display the most important positive and negative features
    learned by the Logistic Regression model.
    """
    weights = model.coef_[0]
    top_positive = np.argsort(weights)[-n_top:][::-1]
    top_negative = np.argsort(weights)[:n_top]
    
    print(f"\nTop {n_top} features → {class_name}:")
    for idx in top_positive:
        print(f"  {feature_names[idx]:40s} weight: {weights[idx]:+.4f}")

    print(f"\nTop {n_top} features → NOT {class_name}:")
    for idx in top_negative:
        print(f"  {feature_names[idx]:40s} weight: {weights[idx]:+.4f}")
        