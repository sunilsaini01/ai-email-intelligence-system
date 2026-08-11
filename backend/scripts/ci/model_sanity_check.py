"""
Model sanity checks (Phase 13 / FR-70).

Answers exactly one question per served model: "does the trained artifact
still load and produce a structurally valid prediction?" It does NOT
answer "is the model accurate" -- that is a data-quality/evidence
question this script has no way to measure and does not attempt to.
See docs/architecture_ci_cd.md for the distinction this project draws
between the two, and docs/evidence/ for each module's real evidence
status.

Exit code 0 means every artifact loaded and every sample prediction was
structurally valid (correct types, no NaN/Inf, known label vocabulary
where one exists). Exit code 1 means at least one module failed one of
those checks -- this is meant to be a hard CI gate.

Run: python -m scripts.ci.model_sanity_check   (from backend/)
"""

# Windows import-order workaround (see app/main.py and app/agents/runner.py
# for the same guard) -- must be the first real imports whenever a single
# process will transitively import both transformers and sklearn/pandas.
import pandas  # noqa: F401
import sklearn  # noqa: F401

import math
import sys
import time
from dataclasses import dataclass, field

SAMPLE_SUBJECT = "Order not received"
SAMPLE_BODY = (
    "Hi team, I placed an order two weeks ago and it still hasn't arrived. "
    "Could you please check the status and let me know when to expect it?"
)

PRIORITY_LABELS = {"Critical", "High", "Medium", "Low"}
SENTIMENT_LABELS = {"Very Negative", "Negative", "Neutral", "Positive", "Very Positive"}


@dataclass
class CheckResult:
    module: str
    ok: bool
    duration_ms: float
    detail: str = ""
    errors: list[str] = field(default_factory=list)


def _is_finite_probability(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and 0.0 <= float(value) <= 1.0 and math.isfinite(float(value))


def _check_spam() -> CheckResult:
    from app.services.spam_service import get_spam_service

    start = time.perf_counter()
    errors = []
    try:
        service = get_spam_service()
        result = service.classify(SAMPLE_SUBJECT, SAMPLE_BODY)
        if not isinstance(result.get("is_spam"), bool):
            errors.append(f"is_spam is not bool: {result.get('is_spam')!r}")
        if not _is_finite_probability(result.get("spam_score")):
            errors.append(f"spam_score not a finite [0,1] value: {result.get('spam_score')!r}")
        if not _is_finite_probability(result.get("confidence")):
            errors.append(f"confidence not a finite [0,1] value: {result.get('confidence')!r}")
    except Exception as exc:  # noqa: BLE001 -- sanity check must catch and report, not crash the runner
        errors.append(f"{type(exc).__name__}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    return CheckResult("spam", not errors, duration_ms, errors=errors)


def _check_priority() -> CheckResult:
    from app.services.priority_service import get_priority_service

    start = time.perf_counter()
    errors = []
    try:
        service = get_priority_service()
        result = service.classify(SAMPLE_SUBJECT, SAMPLE_BODY)
        if result.get("priority") not in PRIORITY_LABELS:
            errors.append(f"priority {result.get('priority')!r} not in {PRIORITY_LABELS}")
        if not _is_finite_probability(result.get("confidence")):
            errors.append(f"confidence not a finite [0,1] value: {result.get('confidence')!r}")
        probs = result.get("probabilities") or {}
        for label, p in probs.items():
            if not _is_finite_probability(p):
                errors.append(f"probabilities[{label!r}] not finite [0,1]: {p!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    return CheckResult("priority", not errors, duration_ms, errors=errors)


def _check_category() -> CheckResult:
    from app.services.category_service import get_category_service

    start = time.perf_counter()
    errors = []
    try:
        service = get_category_service()
        result = service.classify(SAMPLE_SUBJECT, SAMPLE_BODY)
        categories = result.get("categories")
        if not isinstance(categories, list):
            errors.append(f"categories is not a list: {categories!r}")
        else:
            for entry in categories:
                if not _is_finite_probability(entry.get("confidence")):
                    errors.append(f"category confidence not finite [0,1]: {entry!r}")
        all_scores = result.get("all_scores") or {}
        for label, score in all_scores.items():
            if not _is_finite_probability(score):
                errors.append(f"all_scores[{label!r}] not finite [0,1]: {score!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    return CheckResult("category", not errors, duration_ms, errors=errors)


def _check_sentiment() -> CheckResult:
    from app.services.sentiment_service import get_sentiment_service

    start = time.perf_counter()
    errors = []
    try:
        service = get_sentiment_service()
        result = service.analyze(SAMPLE_SUBJECT, SAMPLE_BODY)
        if result.get("sentiment") not in SENTIMENT_LABELS:
            errors.append(f"sentiment {result.get('sentiment')!r} not in {SENTIMENT_LABELS}")
        if not _is_finite_probability(result.get("confidence")):
            errors.append(f"confidence not a finite [0,1] value: {result.get('confidence')!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    return CheckResult("sentiment", not errors, duration_ms, errors=errors)


def _check_intent() -> CheckResult:
    from app.services.intent_service import get_intent_service

    start = time.perf_counter()
    errors = []
    try:
        service = get_intent_service()
        result = service.analyze(SAMPLE_SUBJECT, SAMPLE_BODY)
        intents = result.get("intents")
        if not isinstance(intents, list):
            errors.append(f"intents is not a list: {intents!r}")
        else:
            for entry in intents:
                if not _is_finite_probability(entry.get("confidence")):
                    errors.append(f"intent confidence not finite [0,1]: {entry!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    return CheckResult("intent", not errors, duration_ms, errors=errors)


def _check_summarization() -> CheckResult:
    from app.services.summarization_service import get_summarization_service

    start = time.perf_counter()
    errors = []
    try:
        service = get_summarization_service()
        # Long enough to skip the short-input passthrough path (FR-25) so
        # this actually exercises the extractive model, not just a no-op.
        long_body = SAMPLE_BODY * 6
        result = service.summarize(subject=SAMPLE_SUBJECT, body=long_body, summary_type="extractive")
        summary = result.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"summary is empty or not a string: {summary!r}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    return CheckResult("summarization", not errors, duration_ms, errors=errors)


def _check_feature_schema() -> CheckResult:
    """
    Explicit, standalone check of the Phase 6 feature-schema fingerprint
    mechanism itself (app/feature_engineering/feature_schema.py) -- proves
    the protection is wired up and deterministic, independent of whether
    any individual model happens to exercise it on this sample input.
    """
    from app.feature_engineering.feature_schema import FeatureSchema

    start = time.perf_counter()
    errors = []
    try:
        first = FeatureSchema.current()
        second = FeatureSchema.current()
        if first.fingerprint != second.fingerprint:
            errors.append("FeatureSchema.current() is not deterministic across calls")
        if first.feature_count <= 0:
            errors.append(f"feature_count is not positive: {first.feature_count}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    return CheckResult("feature_schema", not errors, duration_ms, errors=errors)


def main() -> int:
    checks = [
        _check_feature_schema,
        _check_spam,
        _check_priority,
        _check_category,
        _check_sentiment,
        _check_intent,
        _check_summarization,
    ]

    results = [check() for check in checks]

    all_ok = True
    print("Model sanity check results (artifact load + inference validity, NOT accuracy):")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"  [{status}] {result.module:<16} {result.duration_ms:8.1f} ms")
        for error in result.errors:
            print(f"           - {error}")
        all_ok = all_ok and result.ok

    if not all_ok:
        print("\nOne or more model sanity checks failed. See docs/architecture_ci_cd.md.")
        return 1

    print("\nAll model sanity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
