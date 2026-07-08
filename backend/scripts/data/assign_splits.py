import pandas as pd
from pathlib import Path

output_dir = Path("data/processed/v1.0")

split_df = pd.DataFrame({
    "email_id": ["e1", "e2", "e3"],
    "split": ["train", "test", "train"]
})

split_df.to_parquet(output_dir / "splits.parquet", index=False)

print("splits.parquet created")

