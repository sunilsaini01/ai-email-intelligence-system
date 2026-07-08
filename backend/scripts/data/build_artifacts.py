from pathlib import Path

output_dir = Path("data/processed/v1.0")

with open(output_dir / "VERSION.md", "w") as f:
    f.write("# Dataset Version v1.0")

print("VERSION.md created")

