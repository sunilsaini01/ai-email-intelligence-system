import pandas as pd

from dataclasses import dataclass


@dataclass
class ValidationResult:
    check_name: str
    passed: bool
    detail: str


def validate_corpus(
    df: pd.DataFrame
) -> list[ValidationResult]:

    results = []

    # 1. Null check
    for field in [
        "body_clean",
        "body_anonymized",
        "spam_label"
    ]:

        null_pct = (
            df[field].isna().mean() * 100
        )

        passed = null_pct < 5.0

        results.append(
            ValidationResult(
                check_name=f"null_check:{field}",
                passed=passed,
                detail=f"{null_pct:.1f}% null"
            )
        )

    # 2. Empty string check
    empty_pct = (
        (
            df["body_clean"]
            .str
            .strip() == ""
        ).mean() * 100
    )

    results.append(
        ValidationResult(
            check_name="empty_body_check",
            passed=empty_pct < 3.0,
            detail=f"{empty_pct:.1f}% empty body"
        )
    )

    # 3. Label validity
    valid_spam = {
        "spam",
        "ham"
    }

    invalid_spam = ~df[
        "spam_label"
    ].dropna().isin(valid_spam)

    results.append(
        ValidationResult(
            check_name="spam_label_validity",
            passed=invalid_spam.sum() == 0,
            detail=f"{invalid_spam.sum()} invalid labels"
        )
    )

    # 4. Duplicate check
    dup_count = df.duplicated(
        subset=["email_id"]
    ).sum()

    results.append(
        ValidationResult(
            check_name="duplicate_email_id",
            passed=dup_count == 0,
            detail=f"{dup_count} duplicates"
        )
    )

    # Summary
    failed = [
        r for r in results
        if not r.passed
    ]

    print(
        f"\nValidation: "
        f"{len(results)-len(failed)}/"
        f"{len(results)} checks passed"
    )

    for r in failed:

        print(
            f"[FAIL] "
            f"{r.check_name}: "
            f"{r.detail}"
        )

    return results