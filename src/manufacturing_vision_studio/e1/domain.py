"""Typed, immutable contracts for the E1 synthetic evaluation corpus."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class DatasetProfile(StrEnum):
    MINI = "mini"
    FULL = "full"


class DatasetSplit(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    TEST = "test"


class CaseGroup(StrEnum):
    CLEAN = "clean"
    NUISANCE = "nuisance"
    DEFECT = "defect"
    TRUST_BOUNDARY = "trust_boundary"


class ExpectedOutcome(StrEnum):
    NORMAL = "NORMAL"
    ANOMALY = "ANOMALY"
    ABSTAIN = "ABSTAIN"


class SupportBoundary(StrEnum):
    SUPPORTED_NORMAL_RANGE = "SUPPORTED_NORMAL_RANGE"
    UNSUPPORTED_OR_ABSTAIN_RANGE = "UNSUPPORTED_OR_ABSTAIN_RANGE"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DefectType(StrEnum):
    SCRATCH = "scratch"
    STAIN = "stain"
    EDGE_CHIP = "edge_chip"
    BURR = "burr"
    BLOCKED_HOLE = "blocked_hole"
    HOLE_GEOMETRY_DEVIATION = "hole_geometry_deviation"


class NuisanceType(StrEnum):
    TRANSLATION = "translation"
    ROTATION = "rotation"
    SCALE = "scale"
    EXPOSURE = "exposure"
    DIRECTIONAL_SHADING = "directional_shading"
    GAUSSIAN_BLUR = "gaussian_blur"
    SENSOR_NOISE = "sensor_noise"
    JPEG_COMPRESSION = "jpeg_compression"
    BACKGROUND_FIXTURE = "background_fixture"


class CadRevision(StrEnum):
    REV_A = "rev-A"
    REV_B = "rev-B"


class ViewId(StrEnum):
    FRONT = "front"
    OBLIQUE_LEFT = "oblique_left"
    OBLIQUE_RIGHT = "oblique_right"


FeatureRegion = tuple[float, float, float, float]

# The frozen E1 contract now carries per-view regions. This fallback matches the
# v0.1 model and is used only when loading an older frozen draft during migration.
E1_FEATURE_REGIONS: Final[Mapping[str, FeatureRegion]] = MappingProxyType(
    {
        "top_face": (0.10, 0.14, 0.90, 0.86),
        "hole_left": (0.20, 0.32, 0.39, 0.68),
        "hole_right": (0.61, 0.32, 0.80, 0.68),
        "top_edge": (0.10, 0.12, 0.90, 0.25),
        "bottom_edge": (0.10, 0.75, 0.90, 0.88),
    }
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RecipeParameter:
    """One fully resolved numeric recipe parameter."""

    name: str
    unit: str
    value: int | float

    def __post_init__(self) -> None:
        if not self.name or not self.unit:
            raise ValueError("recipe parameter name and unit must be non-empty")
        if isinstance(self.value, bool):
            raise ValueError("recipe parameter value must be numeric")

    def as_record(self) -> dict[str, object]:
        return {"name": self.name, "unit": self.unit, "value": self.value}


@dataclass(frozen=True, slots=True)
class DefectSpec:
    """Generator-owned positive truth for one defect case."""

    defect_id: str
    defect_type: DefectType
    severity: Severity
    target_feature_id: str
    parameters: tuple[RecipeParameter, ...]

    def __post_init__(self) -> None:
        if not self.defect_id or not self.target_feature_id:
            raise ValueError("defect identity and target feature must be non-empty")
        names = tuple(parameter.name for parameter in self.parameters)
        if not names or names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("defect parameters must be non-empty, unique, and sorted")

    def as_record(self) -> dict[str, object]:
        return {
            "defect_id": self.defect_id,
            "type": self.defect_type.value,
            "severity": self.severity.value,
            "target_feature_id": self.target_feature_id,
            "parameters": [parameter.as_record() for parameter in self.parameters],
        }


@dataclass(frozen=True, slots=True)
class NuisanceSpec:
    """One supported nuisance family with resolved parameter values."""

    nuisance_type: NuisanceType
    parameters: tuple[RecipeParameter, ...]

    def __post_init__(self) -> None:
        names = tuple(parameter.name for parameter in self.parameters)
        if not names or names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("nuisance parameters must be non-empty, unique, and sorted")

    def as_record(self) -> dict[str, object]:
        return {
            "type": self.nuisance_type.value,
            "parameters": [parameter.as_record() for parameter in self.parameters],
        }


@dataclass(frozen=True, slots=True)
class TrustBoundarySpec:
    """Expected fail-closed behavior for one adversarial case recipe."""

    scenario_id: str
    expected_error_code: str
    publication_allowed: bool

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.expected_error_code:
            raise ValueError("trust-boundary identity and error code must be non-empty")
        if self.publication_allowed:
            raise ValueError("E1 trust-boundary cases must fail closed")

    def as_record(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "expected_error_code": self.expected_error_code,
            "publication_allowed": self.publication_allowed,
        }


@dataclass(frozen=True, slots=True)
class E1CasePlan:
    """A deterministic case recipe before any bytes are rendered."""

    case_id: str
    profile_membership: tuple[DatasetProfile, ...]
    split: DatasetSplit
    group: CaseGroup
    ordinal: int
    seed_family: str
    seed: int
    recipe_id: str
    recipe_version: str
    part_id: str
    cad_revision: CadRevision
    view_id: ViewId
    expected_outcome: ExpectedOutcome
    support_boundary: SupportBoundary
    defect: DefectSpec | None = None
    nuisances: tuple[NuisanceSpec, ...] = ()
    trust_boundary: TrustBoundarySpec | None = None

    def __post_init__(self) -> None:
        if not self.case_id or not self.seed_family or not self.recipe_id:
            raise ValueError("case, seed-family, and recipe identities must be non-empty")
        if not self.recipe_version or not self.part_id:
            raise ValueError("recipe version and part identity must be non-empty")
        if not 0 <= self.seed <= 0xFFFFFFFF or self.ordinal < 0:
            raise ValueError("seed must be uint32 and ordinal must be non-negative")
        profiles = tuple(profile.value for profile in self.profile_membership)
        if (
            not profiles
            or DatasetProfile.FULL not in self.profile_membership
            or profiles != tuple(sorted(set(profiles)))
        ):
            raise ValueError("profile membership must be sorted, unique, and include full")
        nuisance_types = tuple(nuisance.nuisance_type.value for nuisance in self.nuisances)
        if nuisance_types != tuple(sorted(set(nuisance_types))):
            raise ValueError("nuisance entries must be unique and sorted by type")
        self._validate_group_contract()

    def _validate_group_contract(self) -> None:
        if self.group is CaseGroup.DEFECT:
            if (
                self.defect is None
                or self.expected_outcome is not ExpectedOutcome.ANOMALY
                or self.support_boundary is not SupportBoundary.SUPPORTED_NORMAL_RANGE
                or self.trust_boundary is not None
            ):
                raise ValueError("defect plan does not satisfy the positive-case contract")
            return
        if self.defect is not None:
            raise ValueError("only defect cases may carry defect truth")
        if self.group is CaseGroup.TRUST_BOUNDARY:
            if (
                self.trust_boundary is None
                or self.expected_outcome is not ExpectedOutcome.ABSTAIN
                or self.support_boundary is not SupportBoundary.UNSUPPORTED_OR_ABSTAIN_RANGE
            ):
                raise ValueError("trust plan does not satisfy the abstention contract")
            return
        if self.trust_boundary is not None:
            raise ValueError("only trust-boundary cases may carry a trust scenario")
        if (
            self.expected_outcome is not ExpectedOutcome.NORMAL
            or self.support_boundary is not SupportBoundary.SUPPORTED_NORMAL_RANGE
        ):
            raise ValueError("clean and nuisance cases must be supported normal cases")
        if self.group is CaseGroup.CLEAN and self.nuisances:
            raise ValueError("clean cases may not carry nuisance entries")
        if self.group is CaseGroup.NUISANCE and not self.nuisances:
            raise ValueError("nuisance cases must carry at least one nuisance entry")

    @property
    def included_in_mini(self) -> bool:
        return DatasetProfile.MINI in self.profile_membership

    def as_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "profile_membership": [profile.value for profile in self.profile_membership],
            "split": self.split.value,
            "group": self.group.value,
            "ordinal": self.ordinal,
            "seed_family": self.seed_family,
            "seed": self.seed,
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "part_identity": {
                "part_id": self.part_id,
                "cad_revision": self.cad_revision.value,
            },
            "view_id": self.view_id.value,
            "expected_outcome": self.expected_outcome.value,
            "support_boundary": self.support_boundary.value,
            "defect": None if self.defect is None else self.defect.as_record(),
            "nuisance_profile": [nuisance.as_record() for nuisance in self.nuisances],
            "trust_boundary": (
                None if self.trust_boundary is None else self.trust_boundary.as_record()
            ),
        }


@dataclass(frozen=True, slots=True)
class E1GeneratedCase:
    """Canonical generated bytes plus every required source binding."""

    plan: E1CasePlan
    generator_id: str
    generator_version: str
    generator_configuration_sha256: str
    reference_bytes: bytes
    inspection_bytes: bytes
    authoritative_mask_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    authoritative_mask_sha256: str
    case_binding_sha256: str

    def __post_init__(self) -> None:
        if not self.generator_id or not self.generator_version:
            raise ValueError("generator identity must be non-empty")
        for value in (
            self.generator_configuration_sha256,
            self.reference_sha256,
            self.inspection_sha256,
            self.authoritative_mask_sha256,
            self.case_binding_sha256,
        ):
            if _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError("generated-case hashes must be lowercase SHA-256")

    def as_manifest_record(self) -> dict[str, object]:
        record = self.plan.as_record()
        record.update(
            {
                "generator": {
                    "generator_id": self.generator_id,
                    "generator_version": self.generator_version,
                    "generator_configuration_sha256": self.generator_configuration_sha256,
                },
                "source_hashes": {
                    "reference_sha256": self.reference_sha256,
                    "inspection_sha256": self.inspection_sha256,
                    "authoritative_mask_sha256": self.authoritative_mask_sha256,
                    "case_binding_sha256": self.case_binding_sha256,
                },
            }
        )
        return record


@dataclass(frozen=True, slots=True)
class AuthoritativeMaskValidation:
    """Validated generator truth, independent of all predicted outputs."""

    sha256: str
    width: int
    height: int
    positive_pixel_count: int
    target_feature_overlap_pixels: int | None

    @property
    def is_empty(self) -> bool:
        return self.positive_pixel_count == 0
