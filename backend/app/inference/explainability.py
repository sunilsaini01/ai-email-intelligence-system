"""
Per-prediction explanations (PRD SS6.5: "All classification decisions
accompanied by SHAP/LIME explanations"; Persona 3: "explainable decisions").

Every served classifier here (spam, priority, category, intent) is linear
-- TF-IDF (+ scaled engineered features) into Logistic Regression or a
linear SVM, wrapped in CalibratedClassifierCV. For a linear model, SHAP
values have a closed form: coefficient x (feature value - baseline value)
(SHAP's own LinearExplainer computes exactly this). This module computes it
directly, with an all-zero baseline -- the natural reference for TF-IDF,
where "word absent" is 0 -- instead of pulling in the `shap` package for
arithmetic it would do the same way. The contributions are in the model's
decision-function (log-odds) space, BEFORE calibration; calibration is
monotonic, so the direction and ranking of contributions carry over to
the calibrated probability, but the magnitudes are not probability deltas.

Coefficients of a CalibratedClassifierCV are averaged over its internal
cross-validation folds -- each fold is its own fitted estimator.

LIME (the PRD's choice for neural models) is not needed: no neural
classifier is served. DistilBART summarization is a generator, not a
classifier, and is outside this requirement.
"""

import logging

import numpy as np

logger = logging.getLogger("app.explainability")

EXPLANATION_METHOD = "linear_shap_zero_baseline"
DEFAULT_TOP_K = 6


def _fold_coefficients(estimator) -> np.ndarray:
    """(n_outputs, n_features) coefficients, averaged across calibration folds."""
    if hasattr(estimator, "calibrated_classifiers_"):
        return np.mean([np.atleast_2d(c.estimator.coef_) for c in estimator.calibrated_classifiers_], axis=0)
    return np.atleast_2d(estimator.coef_)


def _direction_vector(estimator, classes: list, target) -> np.ndarray:
    coef = _fold_coefficients(estimator)
    # Compared as strings: callers pass labels as the API reports them
    # (e.g. spam's positive label "1"), while sklearn's classes_ may hold
    # numpy ints -- "1" == np.int64(1) is False and would silently flip
    # every contribution's sign.
    class_names = [str(c) for c in classes]
    if coef.shape[0] == 1:
        # Binary model: coef_ points toward classes[1].
        return coef[0] if str(target) == class_names[1] else -coef[0]
    return coef[class_names.index(str(target))]


# get_feature_names_out() rebuilds the whole vocabulary array on every
# call; a loaded pipeline never changes, so names are cached per object.
_NAMES_CACHE: dict[int, list[str]] = {}


def _feature_names(pipeline, n_features: int) -> list[str]:
    cached = _NAMES_CACHE.get(id(pipeline))
    if cached is not None and len(cached) == n_features:
        return cached
    names = _build_feature_names(pipeline, n_features)
    _NAMES_CACHE[id(pipeline)] = names
    return names


def _build_feature_names(pipeline, n_features: int) -> list[str]:
    tfidf = getattr(pipeline, "tfidf", None)
    if tfidf is None and hasattr(pipeline, "pipeline"):
        tfidf = pipeline.pipeline.named_steps.get("tfidf")
    names = [f"word:{w}" for w in tfidf.get_feature_names_out()] if tfidf is not None else []

    schema = getattr(pipeline, "feature_schema", None)
    extra = n_features - len(names)
    if extra > 0 and schema is not None and len(schema.feature_names) == extra:
        names += [f"feature:{n}" for n in schema.feature_names]
    elif extra > 0:
        names += [f"feature_{i}" for i in range(extra)]
    return names


def _matrix_and_direction(pipeline, model_input, target):
    """Returns (1 x n sparse feature row, direction vector) for the four
    pipeline shapes this codebase serves."""
    if hasattr(pipeline, "pipeline"):  # MLPipeline (spam): sklearn Pipeline(tfidf, classifier)
        steps = pipeline.pipeline.named_steps
        matrix = steps["tfidf"].transform([model_input])
        return matrix, _direction_vector(steps["classifier"], list(pipeline.pipeline.classes_), target)

    matrix = pipeline._vectorize([model_input], fit=False)  # noqa: SLF001 -- same transform predict() uses
    classifier = pipeline.classifier
    if hasattr(classifier, "estimators_") and hasattr(pipeline, "mlb"):  # one-vs-rest multi-label
        label_index = [str(c) for c in pipeline.classes_].index(str(target))
        return matrix, _direction_vector(classifier.estimators_[label_index], [0, 1], 1)
    return matrix, _direction_vector(classifier, list(pipeline.classes_), target)


def explain_linear(pipeline, model_input, target, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    matrix, direction = _matrix_and_direction(pipeline, model_input, target)
    row = matrix.tocsr()
    names = _feature_names(pipeline, row.shape[1])
    contributions = [(names[j], float(v * direction[j])) for j, v in zip(row.indices, row.data, strict=True)]
    contributions = [c for c in contributions if c[1] != 0.0]
    contributions.sort(key=lambda c: abs(c[1]), reverse=True)
    return [
        {"feature": name, "contribution": round(value, 4), "effect": "supports" if value > 0 else "opposes"}
        for name, value in contributions[:top_k]
    ]


def explain_prediction(predictor, model_input, targets, top_k: int = DEFAULT_TOP_K) -> dict | None:
    """Best-effort wrapper used by the services: returns None (never
    raises) when the predictor isn't a linear pipeline this module
    understands -- e.g. a test double, or a future non-linear model.
    `targets` is one label or a list (multi-label modules explain every
    assigned label)."""
    pipeline = getattr(predictor, "pipeline", None)
    if pipeline is None:
        return None
    try:
        labels = targets if isinstance(targets, list) else [targets]
        return {
            "method": EXPLANATION_METHOD,
            "space": "decision_function (pre-calibration log-odds)",
            "by_label": {str(t): explain_linear(pipeline, model_input, t, top_k) for t in labels},
        }
    except Exception:
        logger.warning("explanation_failed", exc_info=True)
        return None
