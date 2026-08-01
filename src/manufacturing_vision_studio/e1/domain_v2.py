"""Immutable public contracts for the isolated E1 v2 corpus."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from manufacturing_vision_studio.e1.domain import CaseGroup, E1CasePlan, ExpectedOutcome

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvaluationScope(StrEnum):
    DEVELOPMENT = "development"
    SMOKE = "smoke"
    CALIBRATION = "calibration"
    RELEASE_TEST = "release_test"


@dataclass(frozen=True, slots=True)
class E1V2CasePlan:
    """One preregistered v2 case and its read-only v1 render recipe."""

    scope: EvaluationScope
    case_id: str
    recipe_id: str
    seed_family: str
    seed: int
    group: CaseGroup
    ordinal: int
    expected_outcome: ExpectedOutcome
    defect_id: str | None
    _render_plan: E1CasePlan = field(repr=False)

    def __post_init__(self) -> None:
        if not all((self.case_id, self.recipe_id, self.seed_family)):
            raise ValueError("v2 case identities must be non-empty")
        if not 0 <= self.seed <= 0xFFFFFFFF or self.ordinal < 0:
            raise ValueError("v2 seed must be uint32 and ordinal non-negative")
        if self.group is CaseGroup.DEFECT:
            if self.expected_outcome is not ExpectedOutcome.ANOMALY or not self.defect_id:
                raise ValueError("v2 defect case must bind anomaly truth")
        elif self.defect_id is not None:
            raise ValueError("only v2 defect cases may bind a defect ID")

    def membership_record(self) -> dict[str, object]:
        return {
            "scope": self.scope.value,
            "case_id": self.case_id,
            "recipe_id": self.recipe_id,
            "seed_family": self.seed_family,
            "seed": self.seed,
            "expected_outcome": self.expected_outcome.value,
            "defect_id": self.defect_id,
            "group": self.group.value,
        }


@dataclass(frozen=True, slots=True)
class E1V2GeneratedCase:
    """Canonical v2 source bytes and their independently bound digests."""

    plan: E1V2CasePlan
    reference_bytes: bytes
    inspection_bytes: bytes
    authoritative_mask_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    authoritative_mask_sha256: str
    case_binding_sha256: str

    def __post_init__(self) -> None:
        for digest in (
            self.reference_sha256,
            self.inspection_sha256,
            self.authoritative_mask_sha256,
            self.case_binding_sha256,
        ):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("v2 generated case hashes must be lowercase SHA-256")

    def membership_record(self) -> dict[str, object]:
        record = self.plan.membership_record()
        record.update(
            {
                "reference_sha256": self.reference_sha256,
                "inspection_sha256": self.inspection_sha256,
                "authoritative_mask_sha256": self.authoritative_mask_sha256,
                "case_binding_sha256": self.case_binding_sha256,
            }
        )
        return record

    def as_manifest_record(self) -> dict[str, object]:
        record = self.membership_record()
        record["source_hashes"] = {
            "reference_sha256": self.reference_sha256,
            "inspection_sha256": self.inspection_sha256,
            "authoritative_mask_sha256": self.authoritative_mask_sha256,
            "case_binding_sha256": self.case_binding_sha256,
        }
        return record
