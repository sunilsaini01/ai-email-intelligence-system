"""
Tests for app/mlops/model_metadata.py (Phase 15A / FR-71).

Covers the two things this module exists to guarantee: provenance
round-trips through the metrics JSON without clobbering pre-existing
training-time fields, and a metrics file with no `provenance` key (a
model trained before this phase) is treated as "no provenance recorded",
not an error.
"""

import json

import pytest

from app.mlops.model_metadata import (
    MODULE_EVIDENCE_STATUS,
    REGISTRABLE_MODULES,
    EvidenceStatus,
    ModelProvenance,
    get_deployed_model_version,
    read_provenance,
    write_provenance,
)


def test_registrable_modules_matches_evidence_status_keys():
    assert set(REGISTRABLE_MODULES) == set(MODULE_EVIDENCE_STATUS.keys())


def test_read_provenance_returns_none_for_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist_metrics.json"
    assert read_provenance(missing) is None


def test_read_provenance_returns_none_when_no_provenance_key(tmp_path):
    path = tmp_path / "spam_baseline_metrics.json"
    path.write_text(json.dumps({"model_version": "svm-20260101-000000"}), encoding="utf-8")
    assert read_provenance(path) is None


def test_write_provenance_preserves_existing_training_fields(tmp_path):
    path = tmp_path / "spam_baseline_metrics.json"
    original = {
        "model_version": "svm-20260101-000000",
        "decision_threshold": 0.7,
        "comparison": [{"model": "svm", "recall": 0.98}],
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    provenance = ModelProvenance(
        mlflow_run_id="abc123",
        mlflow_model_name="spam",
        mlflow_model_version="3",
        mlflow_stage="Production",
        evidence_status=EvidenceStatus.REAL_HELDOUT,
        promoted_at="2026-08-20T00:00:00+00:00",
    )
    write_provenance(path, provenance)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model_version"] == "svm-20260101-000000"
    assert data["decision_threshold"] == 0.7
    assert data["comparison"] == original["comparison"]
    assert data["provenance"]["mlflow_run_id"] == "abc123"
    assert data["provenance"]["mlflow_model_version"] == "3"


def test_write_then_read_provenance_round_trips(tmp_path):
    path = tmp_path / "priority_baseline_metrics.json"
    path.write_text(json.dumps({"model_version": "lr-20260101-000000"}), encoding="utf-8")

    provenance = ModelProvenance(
        evidence_status=EvidenceStatus.SYNTHETIC_LABEL,
        rollback_of="2",
    )
    write_provenance(path, provenance)

    loaded = read_provenance(path)
    assert loaded is not None
    assert loaded.evidence_status == EvidenceStatus.SYNTHETIC_LABEL
    assert loaded.rollback_of == "2"


def test_get_deployed_model_version_returns_none_none_when_file_missing(tmp_path):
    version, provenance = get_deployed_model_version("spam", artifact_dir=str(tmp_path))
    assert version is None
    assert provenance is None


def test_get_deployed_model_version_reads_version_and_provenance(tmp_path):
    path = tmp_path / "spam_baseline_metrics.json"
    path.write_text(
        json.dumps(
            {
                "model_version": "svm-20260101-000000",
                "provenance": {
                    "evidence_status": "real_holdout",
                    "mlflow_model_version": "5",
                },
            }
        ),
        encoding="utf-8",
    )
    version, provenance = get_deployed_model_version("spam", artifact_dir=str(tmp_path))
    assert version == "svm-20260101-000000"
    assert provenance is not None
    assert provenance.evidence_status == EvidenceStatus.REAL_HELDOUT
    assert provenance.mlflow_model_version == "5"


@pytest.mark.parametrize("module", list(MODULE_EVIDENCE_STATUS.keys()))
def test_synthetic_label_modules_never_marked_real_holdout(module):
    """The exact failure mode this whole phase exists to prevent: a
    synthetic-label module's disclosed status silently drifting to claim
    stronger (real_holdout) evidence."""
    status = MODULE_EVIDENCE_STATUS[module]
    if module != "spam":
        assert status != EvidenceStatus.REAL_HELDOUT
