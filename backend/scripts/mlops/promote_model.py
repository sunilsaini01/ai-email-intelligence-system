"""
Model promotion CLI (Phase 15A / FR-71).

    python -m scripts.mlops.promote_model --module spam --version 3
    python -m scripts.mlops.promote_model --module spam --rollback-to 2
    python -m scripts.mlops.promote_model --module spam --version 3 --force

This is the ONLY thing that writes to artifacts/{module}_baseline.joblib /
artifacts/{module}_baseline_metrics.json. Training scripts (train_*.py) no
longer do -- they register an MLflow candidate and stop (see
train_spam_model.py's own comment on this exact behavior change). A
candidate becoming production always requires this explicit step.

Promotion (--version N):
    1. Download candidate N's artifact from the MLflow registry.
    2. Sanity-check it (does it load, does it produce structurally valid
       predictions) -- reuses scripts/ci/model_sanity_check.py's own
       per-module check functions against the CANDIDATE's directory, not
       the deployed one.
    3. Evaluate module-specific promotion criteria against the candidate's
       logged MLflow metrics (see PROMOTION_CRITERIA below).
    4. Compare against the currently-deployed production version's
       metrics -- refuses on an obvious regression unless --force is
       passed (and even then, prints exactly what's regressing before
       proceeding).
    5. On pass: copies the artifact into artifacts/, merges provenance
       into the metrics JSON, transitions the MLflow registry stage.

Rollback (--rollback-to N):
    Same mechanics, but skips the regression-vs-current-production check
    (the entire point of rollback is restoring an earlier, already-known
    state, which may legitimately have "worse" metrics than whatever is
    being rolled back FROM) and tags the promotion as a rollback in
    provenance for audit purposes.

Exit code 0 = promoted. Exit code 1 = refused (CI-usable: a pipeline step
that runs this and checks the exit code cannot accidentally promote a
model that fails its own criteria).
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.mlops.model_metadata import (
    MODULE_EVIDENCE_STATUS,
    REGISTRABLE_MODULES,
    ModelProvenance,
    now_iso,
    write_provenance,
)

# Resolved relative to this file, not the process's cwd -- a plain
# Path("artifacts") only worked when invoked from the repo root; running
# `python -m scripts.mlops.promote_model` from backend/ (the cwd
# scripts/ci/model_sanity_check.py's own docstring documents for the
# sibling `-m` invocation) silently resolved to a nonexistent
# backend/artifacts and crashed with a raw FileNotFoundError deep inside
# shutil.copy2 -- reproduced for real during this phase's own
# infrastructure verification, not a hypothetical. Matches the same fix
# applied to app/mlops/model_metadata.py's _DEFAULT_ARTIFACT_DIR.
ARTIFACTS_DIR = Path(__file__).resolve().parents[3] / "artifacts"

# Deliberately derived from this project's OWN already-measured baseline
# performance (see docs/model_promotion_policy.md "Where These Numbers
# Came From"), not invented targets -- a floor set well below the current
# deployed model's real numbers so it's a genuine regression gate, not
# a rubber stamp, without requiring speculative re-tuning to pass.
PROMOTION_CRITERIA: dict[str, dict[str, tuple[str, float, str]]] = {
    # metric_key -> (comparison, floor, human description)
    "spam": {
        "recall_at_threshold": (">=", 0.90, "SpamAssassin-domain recall"),
        "precision_at_threshold": (">=", 0.70, "SpamAssassin-domain precision at the calibrated threshold"),
    },
    "priority": {
        "macro_f1": (">=", 0.40, "macro F1 across Critical/High/Medium/Low"),
        "critical_high_recall": (">=", 0.15, "recall on the business-critical Critical+High classes"),
    },
    "category": {
        "f1_micro": (">=", 0.60, "micro-averaged F1 across all category labels"),
        "hamming_loss": ("<=", 0.20, "multi-label Hamming loss"),
    },
    "intent": {
        # Deliberately NOT gated per-class -- Escalation/Refund are already
        # disclosed as unreliable (README.md Known Limitations); a floor on
        # those specific classes would either be trivially low (meaningless)
        # or block promotion on a pre-existing, known issue this phase does
        # not fix. Gated on the aggregate instead, with the per-class caveat
        # carried in provenance/documentation, not hidden.
        "f1_micro": (">=", 0.35, "micro-averaged F1 across all intent labels"),
    },
}


def _sanity_check(module: str, artifact_dir: Path) -> tuple[bool, list[str]]:
    from scripts.ci import model_sanity_check as sanity

    check_fn = {
        "spam": sanity._check_spam,
        "priority": sanity._check_priority,
        "category": sanity._check_category,
        "intent": sanity._check_intent,
    }[module]
    result = check_fn(str(artifact_dir))
    return result.ok, result.errors


def _evaluate_criteria(module: str, metrics: dict[str, float]) -> tuple[bool, list[str]]:
    failures = []
    for metric_key, (cmp_op, floor, description) in PROMOTION_CRITERIA[module].items():
        value = metrics.get(metric_key)
        if value is None:
            failures.append(f"metric '{metric_key}' ({description}) missing from candidate's logged metrics")
            continue
        ok = value >= floor if cmp_op == ">=" else value <= floor
        if not ok:
            failures.append(f"{description}: {value:.4f} does not satisfy {cmp_op} {floor} (metric={metric_key})")
    return not failures, failures


def _check_regression(module: str, candidate_metrics: dict[str, float], production_metrics: dict[str, float]) -> list[str]:
    warnings = []
    for metric_key, (cmp_op, _floor, description) in PROMOTION_CRITERIA[module].items():
        cand = candidate_metrics.get(metric_key)
        prod = production_metrics.get(metric_key)
        if cand is None or prod is None:
            continue
        # "worse" direction depends on whether higher-is-better (>=) or
        # lower-is-better (<=) for this metric.
        regressed = cand < prod if cmp_op == ">=" else cand > prod
        if regressed:
            warnings.append(f"{description}: candidate {cand:.4f} vs. current production {prod:.4f}")
    return warnings


def promote(module: str, version: str, *, is_rollback: bool, force: bool) -> int:
    if module not in REGISTRABLE_MODULES:
        print(f"[ERROR] '{module}' is not a registrable module. Registrable: {REGISTRABLE_MODULES}")
        return 1

    from app.mlops.mlflow_client import (
        download_candidate,
        get_production_version,
        transition_stage,
    )

    print(f"=== {'ROLLBACK' if is_rollback else 'PROMOTE'}: {module} -> version {version} ===\n")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            downloaded_dir = download_candidate(model_name=module, version=version, dst_dir=tmp_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] Could not download version {version} from the registry: {type(exc).__name__}: {exc}")
            return 1

        print("[1/4] Sanity check (does the candidate load and predict validly)...")
        sane, errors = _sanity_check(module, downloaded_dir)
        if not sane:
            print("[FAIL] Candidate failed sanity check:")
            for e in errors:
                print(f"    - {e}")
            return 1
        print("    OK")

        try:
            candidate_metrics = get_run_metrics_for_version(module, version)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] Could not read candidate's logged metrics: {type(exc).__name__}: {exc}")
            return 1

        print("[2/4] Module-specific promotion criteria...")
        criteria_ok, failures = _evaluate_criteria(module, candidate_metrics)
        if not criteria_ok:
            print("[FAIL] Candidate does not meet promotion criteria:")
            for f in failures:
                print(f"    - {f}")
            return 1
        print("    OK")

        print("[3/4] Regression check against current production version...")
        current_prod = get_production_version(module)
        if current_prod is None:
            print("    No current production version -- nothing to compare against (first promotion).")
        elif is_rollback:
            print("    Skipped for rollback -- restoring a known-earlier state is the point of rollback.")
        else:
            regressions = _check_regression(module, candidate_metrics, current_prod["metrics"])
            if regressions and not force:
                print("[FAIL] Candidate regresses vs. current production on:")
                for r in regressions:
                    print(f"    - {r}")
                print("    Re-run with --force to promote anyway (will still be logged as an explicit override).")
                return 1
            elif regressions and force:
                print("[WARN] Regressions present, proceeding because --force was passed:")
                for r in regressions:
                    print(f"    - {r}")
            else:
                print("    OK -- no regression vs. current production.")

        print("[4/4] Deploying: copying artifact into artifacts/ and updating provenance...")
        model_filename = f"{module}_baseline.joblib"
        src = downloaded_dir / model_filename
        if not src.exists():
            print(f"[FAIL] Expected {model_filename} inside the downloaded artifact, found: {list(downloaded_dir.iterdir())}")
            return 1
        shutil.copy2(src, ARTIFACTS_DIR / model_filename)

        candidate_metrics_json_path = _find_candidate_metrics_json(module, version, downloaded_dir)
        if candidate_metrics_json_path is not None:
            shutil.copy2(candidate_metrics_json_path, ARTIFACTS_DIR / f"{module}_baseline_metrics.json")

        run_id = _get_run_id_for_version(module, version)
        run_tags = _get_run_tags(module, version)

        metrics_path = ARTIFACTS_DIR / f"{module}_baseline_metrics.json"
        # Always resolve model_version from the run's own "model_version"
        # tag (set by every train_*.py script -- see mlflow_client.tag_run's
        # docstring), NOT left as whatever the metrics JSON already had on
        # disk. Without this, a promotion where no metrics.json artifact
        # was logged (spam's per-candidate logging never logs one) silently
        # left the file's model_version pointing at the PREVIOUS production
        # model -- reproduced for real during this phase's own
        # infrastructure verification: /health/models kept reporting the
        # old version string immediately after a successful promotion.
        # Falls back to a synthesized identifier only for a run registered
        # before this tag existed.
        resolved_model_version = run_tags.get("model_version", f"{module}-mlflow-v{version}")
        _set_model_version(metrics_path, resolved_model_version)

        provenance = ModelProvenance(
            mlflow_run_id=run_id,
            mlflow_model_name=module,
            mlflow_model_version=version,
            mlflow_stage="Production",
            git_commit=run_tags.get("git_commit"),
            dataset_version=run_tags.get("dataset_version"),
            evidence_status=MODULE_EVIDENCE_STATUS[module],
            promoted_at=now_iso(),
            promoted_by="manual",
            rollback_of=(current_prod["version"] if is_rollback and current_prod else None),
        )
        write_provenance(metrics_path, provenance)

        transition_stage(model_name=module, version=version, stage="Production")

        print(f"\n[OK] {module} version {version} is now Production.")
        if current_prod is not None:
            print(f"     Previous production version ({current_prod['version']}) archived, not deleted -- ")
            print(f"     roll back with: python -m scripts.mlops.promote_model --module {module} --rollback-to {current_prod['version']}")
        print("     Restart the api/agents process to pick up the change (matches this project's existing deployment model).")
        return 0


def _find_candidate_metrics_json(module: str, version: str, downloaded_dir: Path) -> Path | None:
    """The candidate metrics JSON was logged as an MLflow artifact
    alongside the model for priority/category/intent's training scripts
    (which log a real metrics.json, unlike spam's per-candidate MLflow
    runs -- see train_spam_model.py's comment on why spam logs metrics as
    first-class MLflow metrics instead). Falls back to None (provenance
    still gets written; the pre-existing artifacts/{module}_baseline_metrics.json
    structure is left as whatever it already was) rather than failing --
    a promotion should not hard-fail just because this specific optional
    artifact wasn't logged."""
    candidates = list(downloaded_dir.glob("*_metrics.json"))
    return candidates[0] if candidates else None


def _set_model_version(metrics_path: Path, model_version: str) -> None:
    """Merges model_version into the metrics JSON, same merge discipline
    as write_provenance() (never overwrites other pre-existing keys,
    creates the file if this is the module's first-ever promotion)."""
    import json

    data = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    data["model_version"] = model_version
    metrics_path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def _get_run_tags(module: str, version: str) -> dict[str, str]:
    from app.mlops.mlflow_client import MlflowClient, configure_tracking_uri, get_run_tags

    configure_tracking_uri()
    client = MlflowClient()
    mv = client.get_model_version(module, version)
    return get_run_tags(mv.run_id)


def get_run_metrics_for_version(module: str, version: str) -> dict[str, float]:
    from app.mlops.mlflow_client import MlflowClient, configure_tracking_uri, get_run_metrics

    configure_tracking_uri()
    client = MlflowClient()
    mv = client.get_model_version(module, version)
    return get_run_metrics(mv.run_id)


def _get_run_id_for_version(module: str, version: str) -> str:
    from app.mlops.mlflow_client import MlflowClient, configure_tracking_uri

    configure_tracking_uri()
    client = MlflowClient()
    return client.get_model_version(module, version).run_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote or roll back a registered model version.")
    parser.add_argument("--module", required=True, choices=REGISTRABLE_MODULES)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--version", help="Promote this candidate version to production.")
    group.add_argument("--rollback-to", help="Roll back production to this earlier version.")
    parser.add_argument("--force", action="store_true", help="Promote despite a detected regression.")
    args = parser.parse_args()

    if args.version:
        return promote(args.module, args.version, is_rollback=False, force=args.force)
    return promote(args.module, args.rollback_to, is_rollback=True, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
