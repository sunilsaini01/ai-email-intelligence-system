"""
Tests for app/mlops/component_versions.py (Phase 15A / FR-71).

This registry exists specifically so a zero-shot/pretrained/external
component is never mistaken for a trained artifact. These tests guard the
one invariant that matters: no component here overlaps with a
REGISTRABLE_MODULES name, and none claims stronger evidence than its own
classification allows.
"""

from app.mlops.component_versions import NON_REGISTERED_COMPONENTS, get_component_versions
from app.mlops.model_metadata import REGISTRABLE_MODULES, EvidenceStatus


def test_get_component_versions_returns_the_static_list():
    assert get_component_versions() == NON_REGISTERED_COMPONENTS


def test_no_non_registered_component_shares_a_name_with_a_registrable_module():
    names = {c.component_name for c in NON_REGISTERED_COMPONENTS}
    assert names.isdisjoint(REGISTRABLE_MODULES)


def test_every_component_has_a_non_empty_version_identifier():
    for component in NON_REGISTERED_COMPONENTS:
        assert component.version_identifier.strip() != ""


def test_pretrained_and_zero_shot_components_never_claim_real_holdout_evidence():
    for component in NON_REGISTERED_COMPONENTS:
        assert component.evidence_status != EvidenceStatus.REAL_HELDOUT
