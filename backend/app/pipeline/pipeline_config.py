from dataclasses import dataclass


@dataclass
class PipelineConfig:
    """
    Central configuration for the Email Intelligence ML Pipeline.
    """

    # TF-IDF Configuration
    tfidf_max_features: int = 50_000
    tfidf_ngram_range: tuple = (1, 2)
    tfidf_sublinear_tf: bool = True
    tfidf_min_df: int = 3
    tfidf_max_df: float = 0.95

    # Logistic Regression Configuration
    lr_C: float = 1.0
    lr_penalty: str = "l2"
    lr_max_iter: int = 1000
    
    # Naive Bayes Configuration
    nb_alpha: float = 1.0
    nb_variant: str = "complement"

    # SVM Configuration
    svm_C: float = 1.0
    svm_max_iter: int = 2000

    # Model Saving
    model_save_path: str = "saved_model.joblib"

    # General ML Configuration
    class_weight: str = "balanced"
    random_state: int = 42

    # Model Selection
    model_type: str = "logistic_regression"

    # Options:
    # "logistic_regression"
    # "naive_bayes"
    # "svm"

    # Prediction Task
    task: str = "spam"

    # Options:
    # spam
    # priority
    # category
    # sentiment
    # intent