from app.pipeline.ml_pipeline import MLPipeline
from app.pipeline.pipeline_config import PipelineConfig

texts = [
    "free money click here",
    "winner claim your prize",
    "meeting scheduled tomorrow",
    "project discussion today",
    "limited time offer",
    "regards thanks for update",
]

labels = [1, 1, 0, 0, 1, 0]

models = [
    "logistic_regression",
    "naive_bayes",
    "svm",
]

for model_name in models:

    print("\n" + "=" * 50)
    print(f"Testing : {model_name}")
    print("=" * 50)

    config = PipelineConfig(
    model_type=model_name,
    )

    pipeline = MLPipeline(config)
    pipeline.fit(
        X_train=texts,
        y_train=labels,
    )

    predictions = pipeline.predict(texts)

    print("\nPredictions")
    print(predictions)

    try:
        probabilities = pipeline.predict_proba(texts)

        print("\nPrediction Probabilities")
        print(probabilities)

    except AttributeError:

        print("\nNo probability output for this model.")

    save_path = f"{model_name}.joblib"

    pipeline.save(save_path)

    print(f"\nModel Saved -> {save_path}")

    pipeline.load(save_path)

    print("Model Loaded Successfully")