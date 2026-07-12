from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV


def tune_logistic_regression(
    X_train,
    y_train,
):
    """
    Tune Logistic Regression using GridSearchCV.
    Returns the best trained model.
    """

    model = LogisticRegression(
        solver="saga",
        class_weight="balanced",
        random_state=42,
        max_iter=1000,
    )

    param_grid = {
        "C": [0.01, 0.1, 1.0, 10.0],
    }

    grid_search = GridSearchCV(
        estimator=model,
        param_grid=param_grid,
        scoring="f1",
        cv=3,
        n_jobs=-1,
        verbose=1,
    )

    grid_search.fit(
        X_train,
        y_train,
    )

    return grid_search


def print_best_parameters(
    grid_search,
) -> None:
    """
    Display the best hyperparameters found.
    """

    print("\n========== BEST PARAMETERS ==========")

    print(f"Best Score : {grid_search.best_score_:.4f}")

    print(f"Best Parameters : {grid_search.best_params_}")