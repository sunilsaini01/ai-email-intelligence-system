"""
Per-organization category taxonomy (FR-23: "Category taxonomy shall be
configurable per organization via admin UI").

What is configurable, and what is not: the category model is trained on
the fixed FR-21 label set (app/feature_engineering/category_keywords.py),
so an organization can RENAME a label (display_name) and DISABLE one it
doesn't use -- but it cannot invent a brand-new category the model has
never been trained to recognise. Adding one is a retraining job, not a
setting; docs/architecture/category_taxonomy.md says so plainly rather
than letting the admin UI imply otherwise.

Two separate concerns, kept apart on purpose:
  - disabled_categories(): which model labels routing must ignore. Routing
    keeps working on MODEL labels, since department_taxonomy.py maps
    model labels to departments.
  - apply_display_taxonomy(): renames/filters a category result for
    presentation (API responses, the dashboard).
"""

from app.feature_engineering.category_keywords import CATEGORY_LABELS

FALLBACK_CATEGORY = "General"


def disabled_categories(taxonomy: dict | None) -> frozenset[str]:
    taxonomy = taxonomy or {}
    return frozenset(
        label
        for label, config in taxonomy.items()
        if label in CATEGORY_LABELS and label != FALLBACK_CATEGORY and not config.get("enabled", True)
    )


def display_name(taxonomy: dict | None, label: str) -> str:
    config = (taxonomy or {}).get(label) or {}
    return config.get("display_name") or label


def taxonomy_view(taxonomy: dict | None) -> list[dict]:
    """Every model label with its effective configuration -- what the
    admin UI renders."""
    disabled = disabled_categories(taxonomy)
    return [
        {
            "label": label,
            "display_name": display_name(taxonomy, label),
            "enabled": label not in disabled,
            "can_disable": label != FALLBACK_CATEGORY,
        }
        for label in CATEGORY_LABELS
    ]


def filter_disabled(result: dict, disabled: frozenset[str]) -> dict:
    """Drops disabled labels from a CategoryService.classify() result.
    If every assigned label was disabled, falls back to General -- the
    same "never leave an email uncategorised" rule CategoryService itself
    applies when no classifier fires."""
    if not disabled:
        return result
    all_scores = {k: v for k, v in result["all_scores"].items() if k not in disabled}
    categories = [c for c in result["categories"] if c["category"] not in disabled]
    if not categories:
        categories = [{"category": FALLBACK_CATEGORY, "confidence": all_scores.get(FALLBACK_CATEGORY, 0.0)}]
    return {**result, "categories": categories, "all_scores": all_scores}


def apply_display_taxonomy(result: dict, taxonomy: dict | None) -> dict:
    """filter_disabled() plus display names. Adds `label` (model label)
    next to the renamed `category`, so feedback and routing can still
    refer to the label the model actually emitted."""
    filtered = filter_disabled(result, disabled_categories(taxonomy))
    return {
        **filtered,
        "categories": [
            {**c, "label": c["category"], "category": display_name(taxonomy, c["category"])}
            for c in filtered["categories"]
        ],
        "all_scores": {display_name(taxonomy, k): v for k, v in filtered["all_scores"].items()},
    }
