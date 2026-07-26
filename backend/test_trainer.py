from app.pipeline.pipeline_config import PipelineConfig
from app.training.trainer import Trainer
from app.training.artifact_manager import ArtifactManager

texts = [
    "free money click here",
    "winner claim your prize",
    "meeting scheduled tomorrow",
    "project discussion today",
    "limited time offer",
    "regards thanks for update",
]

labels = [1, 1, 0, 0, 1, 0]

config = PipelineConfig(
    model_type="logistic_regression",
)

trainer = Trainer(config)

# Train directly on raw text
trainer.train(
    X_train=texts,
    y_train=labels,
)

predictions = trainer.predict(texts)

print("\nPredictions")
print(predictions)

print("\nPrediction Probabilities")
print(trainer.predict_proba(texts))

artifact_manager = ArtifactManager()

artifact_manager.save_model(
    trainer.pipeline,
    "trainer_test.joblib",
)

loaded_model = artifact_manager.load_model(
    "trainer_test.joblib",
)

print("\nPipeline Loaded Successfully!")
print(type(loaded_model))