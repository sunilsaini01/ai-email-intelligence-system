"""
CI-safe model registry metadata validation (Phase 15A / FR-71).

Deliberately does NOT connect to a live MLflow server -- see the master
prompt's own Phase 9 caution against making CI depend on a fragile
external MLflow service. Everything checked here is a local, static
consistency check:

  1. Every registrable module's artifacts/{module}_baseline_metrics.json
     is valid JSON with the expected top-level shape.
  2. If a `provenance` block exists, it validates against ModelProvenance
     (catches a hand-edited or corrupted metrics file before it reaches
     a promotion or a deployed pod).
  3. provenance.evidence_status (if present) matches
     MODULE_EVIDENCE_STATUS -- catches exactly the failure mode this
     whole phase exists to prevent: a synthetic-label model's provenance
     silently drifting to claim real-holdout evidence.
  4. Every module in REGISTRABLE_MODULES has a promotion-criteria entry
     in scripts/mlops/promote_model.py -- catches "added a 5th
     registrable module, forgot to define what promoting it requires."

Run: python -m scripts.mlops.validate_registry_metadata   (from backend/)
Exit 0 = all checks passed. Exit 1 = at least one failed.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.mlops.model_metadata import MODULE_EVIDENCE_STATUS, REGISTRABLE_MODULES, ModelProvenance

# See scripts/mlops/promote_model.py's ARTIFACTS_DIR comment -- same fix,
# same reason: this script's own docstring documents running it "(from
# backend/)" (matching CI's `working-directory: backend`), where a plain
# Path("artifacts") resolves to a nonexistent backend/artifacts instead of
# the real repo-root artifacts/ directory.
ARTIFACTS_DIR = Path(__file__).resolve().parents[3] / "artifacts"


def check_metrics_files() -> list[str]:
    errors = []
    for module in REGISTRABLE_MODULES:
        path = ARTIFACTS_DIR / f"{module}_baseline_metrics.json"
        if not path.exists():
            errors.append(f"{module}: no {path} -- module is registrable but has never been trained/promoted")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{module}: {path} is not valid JSON: {exc}")
            continue
        if "model_version" not in data:
            errors.append(f"{module}: {path} missing 'model_version'")

        provenance_raw = data.get("provenance")
        if provenance_raw is not None:
            try:
                provenance = ModelProvenance.model_validate(provenance_raw)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{module}: provenance block fails schema validation: {exc}")
                continue
            expected = MODULE_EVIDENCE_STATUS[module]
            if provenance.evidence_status != expected:
                errors.append(
                    f"{module}: provenance.evidence_status={provenance.evidence_status.value!r} "
                    f"does not match this project's own disclosed status {expected.value!r} "
                    f"(app/mlops/model_metadata.py MODULE_EVIDENCE_STATUS) -- a promoted model must "
                    f"never claim stronger evidence than what's actually disclosed"
                )
    return errors


def check_promotion_criteria_coverage() -> list[str]:
    from scripts.mlops.promote_model import PROMOTION_CRITERIA

    errors = []
    for module in REGISTRABLE_MODULES:
        if module not in PROMOTION_CRITERIA or not PROMOTION_CRITERIA[module]:
            errors.append(f"{module}: no promotion criteria defined in scripts/mlops/promote_model.py")
    return errors


def main() -> int:
    all_errors = []
    all_errors += check_metrics_files()
    all_errors += check_promotion_criteria_coverage()

    if all_errors:
        print("Model registry metadata validation FAILED:")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print(f"Model registry metadata validation passed for: {', '.join(REGISTRABLE_MODULES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
