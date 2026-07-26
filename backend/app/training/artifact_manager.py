from pathlib import Path
import json
import joblib


class ArtifactManager:
    """
    Responsible for saving and loading
    training artifacts.
    """

    def __init__(
        self,
        artifact_dir: str = "artifacts",
    ):
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def save_model(
        self,
        model,
        filename: str,
    ):
        """
        Save trained model.
        """

        path = self.artifact_dir / filename

        joblib.dump(
            model,
            path,
        )

        print(f"\n[OK] Model saved -> {path}")

        return path

    def load_model(
        self,
        filename: str,
    ):
        """
        Load trained model.
        """

        path = self.artifact_dir / filename

        model = joblib.load(path)

        print(f"\n[OK] Model loaded -> {path}")

        return model

    def save_json(
        self,
        data: dict,
        filename: str,
    ):
        """
        Save metadata or metrics.
        """

        path = self.artifact_dir / filename

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=4,
            )

        print(f"\n[OK] JSON saved -> {path}")

        return path