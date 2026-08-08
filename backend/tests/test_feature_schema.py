"""
Unit tests for FeatureSchema (Phase 6 Gate 1 — cross-module hardening).

Directly regression-tests the Phase 5 incident class of bug: a shared
ContentFeatures/MetadataFeatures change silently breaking an already-fitted
pipeline. See app/feature_engineering/feature_schema.py's module docstring.
"""

import pytest

from app.feature_engineering.feature_schema import FeatureSchema, FeatureSchemaMismatchError


def test_current_schema_is_deterministic():
    first = FeatureSchema.current()
    second = FeatureSchema.current()
    assert first == second
    assert first.fingerprint == second.fingerprint


def test_current_schema_has_a_positive_feature_count():
    schema = FeatureSchema.current()
    assert schema.feature_count > 0
    assert schema.feature_count == len(schema.feature_names)


def test_identical_schema_validates_without_raising():
    schema = FeatureSchema.current()
    schema.validate_compatible_with(FeatureSchema.current())  # must not raise


def test_added_field_is_detected_and_rejected():
    original = FeatureSchema.current()
    with_extra_field = FeatureSchema(
        feature_names=original.feature_names + ("brand_new_field",),
        feature_count=original.feature_count + 1,
        fingerprint="deadbeefcafe",
    )
    with pytest.raises(FeatureSchemaMismatchError) as exc_info:
        original.validate_compatible_with(with_extra_field)
    assert "brand_new_field" in str(exc_info.value)
    assert "retrained" in str(exc_info.value)


def test_removed_field_is_detected_and_rejected():
    original = FeatureSchema.current()
    without_first_field = FeatureSchema(
        feature_names=original.feature_names[1:],
        feature_count=original.feature_count - 1,
        fingerprint="deadbeefcafe",
    )
    with pytest.raises(FeatureSchemaMismatchError) as exc_info:
        original.validate_compatible_with(without_first_field)
    assert original.feature_names[0] in str(exc_info.value)


def test_reordered_fields_are_detected_and_rejected():
    original = FeatureSchema.current()
    assert len(original.feature_names) >= 2, "need at least 2 fields to test reordering"
    reordered_names = (
        (original.feature_names[1], original.feature_names[0]) + original.feature_names[2:]
    )
    reordered = FeatureSchema(
        feature_names=reordered_names,
        feature_count=original.feature_count,
        fingerprint="deadbeefcafe",
    )
    with pytest.raises(FeatureSchemaMismatchError) as exc_info:
        original.validate_compatible_with(reordered)
    assert "declaration order changed" in str(exc_info.value)
