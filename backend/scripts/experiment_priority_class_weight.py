"""
Phase 4 Step 9 (class imbalance investigation) — does class_weight="balanced"
actually help logistic regression (the winning baseline), or was it assumed
without evidence? Compares against class_weight=None on the same synthetic
dataset, same split. This is a single documented comparison, not a tuning
loop — per the phase's own "ML principle": don't chase the metric, understand
the cause. If neither setting closes the gap meaningfully, that's evidence
the ceiling here is set by minority-class sample size and label noise, not
by an untried class-weight setting (see model card).

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/experiment_priority_class_weight.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sklearn.metrics import f1_score

from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.priority_pipeline import PriorityMLPipeline
from app.preprocessing.email_preprocessor import PRIORITY_CONFIG, EmailPreprocessor
from app.training.logger import get_logger
from app.training.trainer import Trainer
from scripts.train_priority_model import LABELS, clean_and_build_records, load_split

logger = get_logger()

CRITICAL_HIGH = ["Critical", "High"]


def main():
    preprocessor = EmailPreprocessor(PRIORITY_CONFIG)

    train_df = load_split("train")
    test_df = load_split("test")

    train_records = clean_and_build_records(train_df, preprocessor)
    test_records = clean_and_build_records(test_df, preprocessor)
    train_labels = train_df["priority_label"].tolist()
    test_labels = test_df["priority_label"].tolist()

    rows = []
    for weight_label, class_weight in [("None (sklearn default)", None), ("balanced", "balanced")]:
        config = PipelineConfig(model_type="logistic_regression", task="priority", class_weight=class_weight)
        trainer = Trainer(config, pipeline_cls=PriorityMLPipeline)
        trainer.train(X_train=train_records, y_train=train_labels)

        preds = trainer.pipeline.predict(test_records)
        macro_f1 = f1_score(test_labels, preds, labels=LABELS, average="macro", zero_division=0)
        critical_high_f1 = f1_score(test_labels, preds, labels=CRITICAL_HIGH, average="macro", zero_division=0)
        per_class = dict(
            zip(LABELS, f1_score(test_labels, preds, labels=LABELS, average=None, zero_division=0), strict=True)
        )
        rows.append(
            {
                "class_weight": weight_label,
                "macro_f1": round(macro_f1, 4),
                "critical_high_f1": round(critical_high_f1, 4),
                "per_class_f1": {k: round(float(v), 4) for k, v in per_class.items()},
            }
        )

    print("\n================ CLASS WEIGHT COMPARISON (Logistic Regression, priority) ================\n")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
