"""
Feature-schema versioning and compatibility validation (cross-module
hardening — Phase 6 Gate 1).

Why this exists: Phase 5 added 7 fields to ContentFeatures, which silently
broke PriorityMLPipeline's already-trained artifact — its fitted
StandardScaler rejected the new feature width with a cryptic sklearn
ValueError three call frames down ("X has 55 features, but StandardScaler
is expecting 48"). That failure was caught by the existing test suite going
red, but only because a test happened to exercise the exact broken
inference path — a shared-code change with thinner coverage could have
shipped a crashing (or, worse, silently-wrong) production artifact.

The fix here is deliberately NOT a heavyweight schema-migration system —
it's the smallest mechanism that turns a cryptic downstream crash into an
immediate, explicit failure at the actual point of divergence: fingerprint
the exact ORDERED list of engineered feature names a pipeline was fit
against, store it in the pickled artifact, and re-check it before every
prediction. A mismatch fails loudly with both schemas shown side by side,
not whatever exception sklearn happens to raise several layers down.

What this deliberately does NOT do: auto-migrate, reshape, pad, or
truncate a mismatched feature vector to "make it work." An artifact whose
schema no longer matches the running code's feature extractors is not safe
to use for that reason alone — the only correct fix is a retrain, and this
module's job is to make that fact impossible to miss, not to paper over it.
"""

import dataclasses
import hashlib
from dataclasses import dataclass

from app.feature_engineering.feature_models import ContentFeatures
from app.feature_engineering.metadata_models import MetadataFeatures


class FeatureSchemaMismatchError(RuntimeError):
    """
    Raised when a loaded pipeline's stored feature schema no longer matches
    the feature schema the currently-running code would produce.

    This means the artifact was trained against a DIFFERENT version of
    ContentFeatures/MetadataFeatures than what's installed now. The only
    correct fix is retraining — see the module docstring for why this
    error does not attempt to auto-correct the mismatch.
    """


@dataclass(frozen=True)
class FeatureSchema:
    """
    A fingerprint of the exact, ORDERED engineered-feature field names a
    pipeline was fit against. Order matters, not just membership —
    build_feature_matrix concatenates dataclass fields in declaration
    order (see feature_matrix.py's use of `asdict(f).values()`, which
    Python 3.7+ dataclasses guarantee preserves declaration order), so a
    reordering is exactly as breaking as an addition/removal and both must
    be caught, not just set-membership differences.
    """

    feature_names: tuple[str, ...]
    feature_count: int
    fingerprint: str  # short hash of the ordered names, for quick comparison/display

    @classmethod
    def current(cls) -> "FeatureSchema":
        """
        Computes the schema the CURRENTLY INSTALLED ContentFeatures/
        MetadataFeatures code would produce. Called both at fit time (to
        snapshot what a new artifact is trained against) and at predict
        time (to check what's actually installed right now).
        """
        names = tuple(
            [f.name for f in dataclasses.fields(ContentFeatures)]
            + [f.name for f in dataclasses.fields(MetadataFeatures)]
        )
        fingerprint = hashlib.sha256(",".join(names).encode()).hexdigest()[:12]
        return cls(feature_names=names, feature_count=len(names), fingerprint=fingerprint)

    def validate_compatible_with(self, other: "FeatureSchema") -> None:
        """
        Raises FeatureSchemaMismatchError if `other` doesn't match `self`.
        Called as `stored_schema.validate_compatible_with(FeatureSchema.current())`
        from a pipeline's predict path — `self` is what the artifact was
        fit against, `other` is what's installed right now.
        """
        if self.fingerprint == other.fingerprint:
            return

        added = set(other.feature_names) - set(self.feature_names)
        removed = set(self.feature_names) - set(other.feature_names)
        reordered = not added and not removed and self.feature_names != other.feature_names

        detail = [
            f"Feature schema mismatch: artifact was fit against schema "
            f"{self.fingerprint} ({self.feature_count} features), but the "
            f"currently-installed code produces schema {other.fingerprint} "
            f"({other.feature_count} features)."
        ]
        if added:
            detail.append(f"Fields added since training: {sorted(added)}.")
        if removed:
            detail.append(f"Fields removed since training: {sorted(removed)}.")
        if reordered:
            detail.append("Same field names, but declaration order changed.")
        detail.append(
            "This artifact must be retrained against the current code — "
            "do not reshape, pad, or truncate the feature vector to force a match."
        )
        raise FeatureSchemaMismatchError(" ".join(detail))
