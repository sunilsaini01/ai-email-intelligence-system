import pandas as pd
from pathlib import Path

# Create output folder
output_dir = Path("data/processed/v1.0")
output_dir.mkdir(parents=True, exist_ok=True)

# Sample processed dataset
df = pd.DataFrame({
    "email_id": ["e1", "e2", "e3"],
    "body_clean": [
        "Hello how are you",
        "Your account is blocked",
        "Meeting at 5 PM"
    ],
    "spam_label": ["ham", "spam", "ham"]
})

# Save parquet
df.to_parquet(output_dir / "train.parquet", index=False)

print("train.parquet created")

