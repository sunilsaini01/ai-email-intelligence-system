from app.pipeline.text_pipeline import build_text_pipeline

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

# Build Pipeline

pipeline = build_text_pipeline()

# Train Pipeline

pipeline.fit(
    texts,
    labels,
)

# Test Emails

test_emails = [
    "claim your free prize",
    "team meeting tomorrow morning",
]

# Predictions

predictions = pipeline.predict(test_emails)

print("Predictions")
print(predictions)

# Prediction Probabilities

probabilities = pipeline.predict_proba(test_emails)

print("\nPrediction Probabilities")
print(probabilities)

# Pipeline Steps

print("\nPipeline Steps")

for name, step in pipeline.named_steps.items():
    print(f"{name} -> {type(step).__name__}")