# data/pipeline_metadata.py

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PipelineRun:
    """
    Record metadata for a single pipeline execution.
    Written to data/processed/vX.Y/run_metadata.json.
    """
    def __init__(self, version: str, script_name: str):
        self.version = version
        self.script_name = script_name
        self.started_at = datetime.now(UTC).isoformat()
        self.steps: list[dict] = []
        self.inputs: list[str] = []
        self.outputs: list[str] = []

    def log_step(self, step_name: str, details: dict[str, Any]) -> None:
        self.steps.append({
            "step": step_name,
            "timestamp": datetime.now(UTC).isoformat(),
            **details
        })

    def log_input(self, path: str, checksum: str) -> None:
        self.inputs.append({"path": path, "sha256": checksum})

    def log_output(self, path: str, record_count: int) -> None:
        self.outputs.append({"path": path, "record_count": record_count})

    def save(self, output_dir: str) -> None:
        metadata = {
            "corpus_version": self.version,
            "pipeline_script": self.script_name,
            "started_at": self.started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "inputs": self.inputs,
            "outputs": self.outputs,
            "steps": self.steps,
        }
        path = Path(output_dir) / "run_metadata.json"
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"[Lineage] Run metadata saved to {path}")