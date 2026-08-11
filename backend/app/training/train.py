from app.pipeline.pipeline_config import PipelineConfig
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from app.training.trainer import Trainer

logger = get_logger()


def train_model(
    X_train,
    y_train,
    model_type: str = "logistic_regression",
):
    """
    Complete training workflow.

    Build Configuration
            ↓
    Create Trainer
            ↓
    Train Model
            ↓
    Save Model
            ↓
    Return Pipeline
    """

    logger.info("Training Started")

    config = PipelineConfig(
        model_type=model_type,
    )

    trainer = Trainer(config)

    pipeline = trainer.train(
        X_train=X_train,
        y_train=y_train,
    )

    artifact_manager = ArtifactManager()

    artifact_manager.save_model(
        pipeline,
        f"{model_type}.joblib",
    )

    logger.info("Training Finished Successfully")

    return pipeline