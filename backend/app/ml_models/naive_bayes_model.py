import numpy as np
from sklearn.naive_bayes import (
    ComplementNB,
    MultinomialNB,
)


def train_naive_bayes(
    X_train,
    y_train,
    alpha: float = 1.0,
    variant: str = "complement",
):
    """
    Train a Naive Bayes model for email classification.

    Parameters
    ----------
    X_train : sparse matrix
        TF-IDF feature matrix.

    y_train : array-like
        Training labels.

    alpha : float
        Laplace smoothing parameter.

    variant : str
        "complement" or "multinomial".
    """

    if variant == "complement":
        model = ComplementNB(alpha=alpha)
    else:
        model = MultinomialNB(alpha=alpha)

    model.fit(
        X_train,
        y_train,
    )

    return model

def inspect_nb_features(
    model,
    feature_names: list[str],
    n_top: int = 20,
) -> None:
    """
    Display the most predictive features for each class.

    For Naive Bayes, these are the log probabilities
    P(feature | class).
    """
    for class_idx, class_label in enumerate(model.classes_):
        log_probs = model.feature_log_prob_[class_idx]
        top_idx = np.argsort(log_probs)[-n_top:][::-1]
        
        print(f"\nClass '{class_label}' — Top {n_top} features:")

        for idx in top_idx:
            print(
                f"  {feature_names[idx]:40s} "
                f"log_P: {log_probs[idx]:.4f}"
            )
            
