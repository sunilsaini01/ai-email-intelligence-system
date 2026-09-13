from sklearn.calibration import CalibratedClassifierCV
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.svm import LinearSVC

from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.pipeline_factory import PipelineFactory


def test_logistic_regression_is_isotonic_calibrated():
    config = PipelineConfig(model_type="logistic_regression")
    model = PipelineFactory.create_model(config=config, build_only=True)

    assert isinstance(model, CalibratedClassifierCV)
    assert model.method == "isotonic"
    assert model.cv == 3


def test_svm_is_sigmoid_calibrated():
    config = PipelineConfig(model_type="svm")
    model = PipelineFactory.create_model(config=config, build_only=True)

    assert isinstance(model, CalibratedClassifierCV)
    assert isinstance(model.estimator, LinearSVC)
    assert model.method == "sigmoid"


def test_naive_bayes_variants_are_uncalibrated():
    complement_config = PipelineConfig(model_type="naive_bayes", nb_variant="complement")
    multinomial_config = PipelineConfig(model_type="naive_bayes", nb_variant="multinomial")

    assert isinstance(
        PipelineFactory.create_model(config=complement_config, build_only=True), ComplementNB
    )
    assert isinstance(
        PipelineFactory.create_model(config=multinomial_config, build_only=True), MultinomialNB
    )


def test_unsupported_model_type_raises():
    config = PipelineConfig(model_type="not-a-real-model")

    try:
        PipelineFactory.create_model(config=config, build_only=True)
        assert False, "expected ValueError"
    except ValueError:
        pass
