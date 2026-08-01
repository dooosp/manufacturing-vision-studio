"""Development-only E1 v2 diagnostics and immutable candidate selection."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from statistics import median
from types import MappingProxyType
from typing import Any, Literal, cast

import numpy as np
from jsonschema import Draft202012Validator
from PIL import Image
from PIL import __version__ as pillow_version

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1 import trust_boundaries as trust_boundary_module
from manufacturing_vision_studio.e1.baseline import evaluate_v0_1_baseline
from manufacturing_vision_studio.e1.domain import (
    CadRevision,
    CaseGroup,
    DatasetProfile,
    DefectType,
    ViewId,
)
from manufacturing_vision_studio.e1.domain_v2 import E1V2CasePlan, EvaluationScope
from manufacturing_vision_studio.e1.generator import (
    E1Generator,
    _render_pristine,
    _scale_image,
    _translate_image,
)
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.geometry import (
    GeometryConfig,
    _render_silhouette,
    alignment_objective,
    largest_component_silhouette,
    silhouette_edges,
)
from manufacturing_vision_studio.e1.metrics_v2 import (
    E1V2EvaluationObservation,
    evaluate_v2_metrics,
    observation_from_case,
)
from manufacturing_vision_studio.e1.model import _connected_components
from manufacturing_vision_studio.e1.oracle import geometry_for_case, render_defect_truth
from manufacturing_vision_studio.e1.policy_v2 import E1V2InferenceInput, E1V2InferencePolicy
from manufacturing_vision_studio.e1.protocol import load_e1_protocol
from manufacturing_vision_studio.e1.protocol_v2 import (
    E1V2Protocol,
    load_e1_v2_protocol,
    verify_e1_v1_history,
)

CandidateId = Literal["A", "B"]

_PRESERVED_SNAPSHOT = "8d636717a1b04267933b214a3121acfb93182e46"
_PRESERVED_RECORD_SHA256 = "f2a257a731d991ceba74f791e24a15e983fd806734af2ea973fc5808daab7280"
_PRESERVED_SELECTION_FILE_SHA256 = (
    "18ca69bba321f24105c95cc3482b9658e7a2f03ef274ac75a5ed44f822782a9b"
)
_PRESERVED_EXECUTION_PROJECTION_SHA256 = (
    "90c5c7a894b1289572718fce13f39177fafe278707fae697accb0cd9828de429"
)
_PRESERVED_CANDIDATE_SHA256 = {
    "A": "ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84",
    "B": "983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029",
}
_PRESERVED_V2_CONFIG_FILE_SHA256 = (
    "1cb3f58c6b743d48aa1f2fd8e294d899dcf3e1a8c9022646d011b8c2b657ae68"
)

_MAX_SELECTION_FILE_BYTES = 4_000_000
_MAX_EMBEDDED_RAW_BYTES = 2_000_000
_MAX_EMBEDDED_COMPRESSED_BYTES = 500_000
_MAX_EMBEDDED_BASE64_LENGTH = 4 * ((_MAX_EMBEDDED_COMPRESSED_BYTES + 2) // 3)
_V0_1_BASELINE_INPUT_PATHS = (
    "configs/evaluation/e1-v1.json",
    "docs/evaluation/results/v0.1.0-synthetic.json",
    "docs/releases/v0.1.0/evidence-bundle.zip",
    "schemas/v1/analysis-result.schema.json",
    "schemas/v1/evaluation-report.schema.json",
    "schemas/v1/evidence-bundle-manifest.schema.json",
    "schemas/v1/human-disposition.schema.json",
    "schemas/v1/image-input-metadata.schema.json",
    "schemas/v1/inspection-case.schema.json",
)

_SCALE_DELTAS = (-0.020, -0.015, -0.010, -0.005, 0.005, 0.010, 0.015, 0.020)
_ENDPOINT_DELTAS = (-0.020, 0.020)


def declared_evaluation_seeds(protocol: E1V2Protocol) -> frozenset[int]:
    """Expand only checked-in seed-block declarations; never plan or render a scope."""

    generator = protocol.document["generator"]
    blocks = generator["seed_blocks"]
    seeds: set[int] = set()
    for scope_record in blocks.values():
        for block in scope_record.values():
            start = block["start"]
            count = block["count"]
            seeds.update(range(start, start + count))
    return frozenset(seeds)


@dataclass(frozen=True, slots=True)
class ScaleDiagnosticPlan:
    diagnostic_id: str
    seed: int
    combination: str
    cad_revision: CadRevision
    view_id: ViewId
    scale_delta: float
    translation_x: int = 0
    translation_y: int = 0
    rotation_degrees: float = 0.0
    exposure_gain_delta: float = 0.0
    defect_type: str | None = None
    defect_severity: str | None = None
    expected_feature_id: str | None = None

    def diagnostic_truth_record(self) -> dict[str, object]:
        return {
            "scale_delta": self.scale_delta,
            "translation_x": self.translation_x,
            "translation_y": self.translation_y,
            "rotation_degrees": self.rotation_degrees,
            "exposure_gain_delta": self.exposure_gain_delta,
            "defect_type": self.defect_type,
            "defect_severity": self.defect_severity,
            "expected_feature_id": self.expected_feature_id,
        }


def build_scale_diagnostic_matrix(protocol: E1V2Protocol) -> tuple[ScaleDiagnosticPlan, ...]:
    """Build the preregistered 48 plus five 12-row development diagnostic matrix."""

    if protocol.protocol_version != "2.0.0":
        raise ValueError("scale diagnostics require E1 protocol 2.0.0")
    rows: list[ScaleDiagnosticPlan] = []

    def add(
        combination: str,
        revision: CadRevision,
        view: ViewId,
        scale: float,
        **values: object,
    ) -> None:
        ordinal = len(rows)
        rows.append(
            ScaleDiagnosticPlan(
                diagnostic_id=f"e1-v2-development-diagnostic-{ordinal:03d}",
                seed=800000 + ordinal,
                combination=combination,
                cad_revision=revision,
                view_id=view,
                scale_delta=scale,
                **values,  # type: ignore[arg-type]
            )
        )

    for revision in CadRevision:
        for view in ViewId:
            for scale in _SCALE_DELTAS:
                add("scale_only", revision, view, scale)

    pairs = tuple((revision, view) for revision in CadRevision for view in ViewId)
    for revision, view in pairs:
        for scale in _ENDPOINT_DELTAS:
            sign = -1 if scale < 0 else 1
            add(
                "scale_translation",
                revision,
                view,
                scale,
                translation_x=4 * sign,
                translation_y=-2 * sign,
            )
    for revision, view in pairs:
        for scale in _ENDPOINT_DELTAS:
            add(
                "scale_rotation",
                revision,
                view,
                scale,
                rotation_degrees=-1.0 if scale < 0 else 1.0,
            )
    for revision, view in pairs:
        for scale in _ENDPOINT_DELTAS:
            add(
                "scale_exposure",
                revision,
                view,
                scale,
                exposure_gain_delta=-0.05 if scale < 0 else 0.05,
            )

    defect_types = tuple(item.value for item in DefectType)
    feature_by_type = {
        "scratch": "top_face",
        "stain": "top_face",
        "edge_chip": "top_edge",
        "burr": "bottom_edge",
        "blocked_hole": "hole_left",
        "hole_geometry_deviation": "hole_right",
    }
    for severity in ("MEDIUM", "HIGH"):
        combination = f"scale_{severity.lower()}_defect"
        defect_index = 0
        for revision, view in pairs:
            for scale in _ENDPOINT_DELTAS:
                defect_type = defect_types[defect_index % len(defect_types)]
                defect_index += 1
                add(
                    combination,
                    revision,
                    view,
                    scale,
                    defect_type=defect_type,
                    defect_severity=severity,
                    expected_feature_id=feature_by_type[defect_type],
                )
    if len(rows) != 108:
        raise AssertionError("scale diagnostic matrix must contain exactly 108 rows")
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class CandidateEvaluationRecord:
    candidate_id: str
    determinism_verified: bool = True
    dependency_guard_passed: bool = True
    work_cap_passed: bool = True
    development_gates_passed: bool = True
    medium_high_defect_recall: float = 0.0
    trust_verified: bool = True
    v0_1_regression_verified: bool = True
    maximum_diagnostic_truth_recall_drop: float = 0.0
    diagnostic_median_dice_drop: float = 0.0
    development_nuisance_false_positives: int = 0
    medium_high_defect_false_negatives: int = 0
    affected_feature_mapping_errors: int = 0
    positive_case_median_dice: float = 0.0
    median_post_normalization_objective: float = 0.0
    worst_case_candidate_pixels: int = 0
    runtime_p95_ns: int = 0
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.candidate_id not in {"A", "B"}:
            raise ValueError("candidate_id must be A or B")

    @property
    def eligible(self) -> bool:
        return not self.rejection_reasons

    def ranking_key(self) -> tuple[float | int, ...]:
        return (
            self.development_nuisance_false_positives,
            self.medium_high_defect_false_negatives,
            self.affected_feature_mapping_errors,
            -self.positive_case_median_dice,
            self.median_post_normalization_objective,
            self.worst_case_candidate_pixels,
            0 if self.candidate_id == "A" else 1,
        )

    def as_record(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
            if field != "rejection_reasons"
        } | {"rejection_reasons": list(self.rejection_reasons)}

    @classmethod
    def from_record(cls, value: dict[str, object]) -> CandidateEvaluationRecord:
        fields = set(cls.__dataclass_fields__)
        if set(value) != fields:
            raise ValueError("candidate record fields are invalid")
        parsed = dict(value)
        reasons = parsed["rejection_reasons"]
        if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
            raise ValueError("candidate rejection reasons are invalid")
        parsed["rejection_reasons"] = tuple(reasons)
        return cls(**parsed)  # type: ignore[arg-type]


def _freeze_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("audit evidence must contain only JSON-compatible values")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("audit evidence mappings must use string keys")
            frozen[key] = _freeze_json_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise TypeError("audit evidence must contain only JSON-compatible values")


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError("stored audit evidence is not JSON-compatible")


@dataclass(frozen=True, slots=True)
class CandidateSelectionRecord:
    selected_candidate_id: str | None
    candidates: tuple[CandidateEvaluationRecord, ...]
    outcome: str
    implementation_projection: tuple[tuple[str, str], ...] = ()
    implementation_projection_sha256: str = ""
    configuration_sha256: str = ""
    audit_evidence: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    record_sha256: str = ""

    def __post_init__(self) -> None:
        frozen_evidence = _freeze_json_value(self.audit_evidence)
        if not isinstance(frozen_evidence, Mapping):
            raise TypeError("audit evidence must be a JSON object")
        object.__setattr__(self, "audit_evidence", frozen_evidence)

    @property
    def audit_evidence_status(self) -> Literal["UNVERIFIED"]:
        return "UNVERIFIED"

    @property
    def audit_verification_status(self) -> Literal["UNVERIFIED"]:
        return "UNVERIFIED"

    def as_record(self, *, include_self_hash: bool = True) -> dict[str, object]:
        record: dict[str, object] = {
            "schema_version": self.schema_version,
            "record_type": "e1_candidate_selection_v2",
            "configuration_sha256": self.configuration_sha256,
            "audit_evidence_status": self.audit_evidence_status,
            "audit_evidence": _thaw_json_value(self.audit_evidence),
            "implementation_projection": [
                {"path": path, "sha256": digest} for path, digest in self.implementation_projection
            ],
            "implementation_projection_sha256": self.implementation_projection_sha256,
            "candidates": [candidate.as_record() for candidate in self.candidates],
            "selected_candidate_id": self.selected_candidate_id,
            "outcome": self.outcome,
        }
        if include_self_hash:
            record["record_sha256"] = self.record_sha256
        return record


def select_candidate(
    records: Sequence[CandidateEvaluationRecord],
) -> CandidateSelectionRecord:
    """Apply eligibility before the frozen seven-term semantic ranking."""

    if {record.candidate_id for record in records} != {"A", "B"} or len(records) != 2:
        raise ValueError("candidate selection requires exactly A and B")
    evaluated = tuple(
        replace(record, rejection_reasons=_rejection_reasons(record))
        for record in sorted(records, key=lambda item: item.candidate_id)
    )
    eligible = [record for record in evaluated if record.eligible]
    selected = min(eligible, key=CandidateEvaluationRecord.ranking_key) if eligible else None
    return CandidateSelectionRecord(
        selected_candidate_id=None if selected is None else selected.candidate_id,
        candidates=evaluated,
        outcome="HOLD" if selected is None else "SELECTED",
    )


def _rejection_reasons(record: CandidateEvaluationRecord) -> tuple[str, ...]:
    reasons: list[str] = []
    if not record.determinism_verified:
        reasons.append("DETERMINISM_NOT_VERIFIED")
    if not record.dependency_guard_passed:
        reasons.append("DEPENDENCY_GUARD_FAILED")
    if not record.v0_1_regression_verified:
        reasons.append("V0_1_REGRESSION_NOT_VERIFIED")
    if not record.trust_verified:
        reasons.append("TRUST_NOT_VERIFIED")
    if not record.work_cap_passed:
        reasons.append("WORK_CAP_EXCEEDED")
    if not record.development_gates_passed:
        reasons.append("DEVELOPMENT_GATE_FAILED")
    if record.medium_high_defect_recall < 0.90:
        reasons.append("MEDIUM_HIGH_DEFECT_RECALL_BELOW_0_90")
    if record.maximum_diagnostic_truth_recall_drop > 0.05:
        reasons.append("DIAGNOSTIC_TRUTH_RECALL_DROP_EXCEEDED")
    if record.diagnostic_median_dice_drop > 0.01:
        reasons.append("DIAGNOSTIC_MEDIAN_DICE_DROP_EXCEEDED")
    return tuple(reasons)


def implementation_projection_paths() -> tuple[str, ...]:
    """Return the hard-coded, sorted dependency closure for Task 4."""

    paths = (
        "configs/evaluation/e1-v1-history-integrity.json",
        "configs/evaluation/e1-v1.json",
        "configs/evaluation/e1-v2.json",
        "docs/evaluation/results/e1-full-v0.2.0-hold.json",
        "docs/evaluation/results/e1-mini-v0.2.0-hold.json",
        "docs/evaluation/results/v0.1.0-synthetic.json",
        "docs/releases/v0.1.0/evidence-bundle.zip",
        "docs/releases/v0.2.0/E1_HOLD.md",
        "schemas/e1-case-manifest.v1.json",
        "schemas/e1-candidate-selection.v2.json",
        "schemas/e1-evaluation-protocol.v1.json",
        "schemas/e1-evaluation-protocol.v2.json",
        "schemas/e1-evaluation-result.v1.json",
        "schemas/e1-threshold-lock.v1.json",
        "schemas/v1/analysis-result.schema.json",
        "schemas/v1/evaluation-report.schema.json",
        "schemas/v1/evidence-bundle-manifest.schema.json",
        "schemas/v1/human-disposition.schema.json",
        "schemas/v1/image-input-metadata.schema.json",
        "schemas/v1/inspection-case.schema.json",
        "src/manufacturing_vision_studio/canonical.py",
        "src/manufacturing_vision_studio/canonical_png.py",
        "src/manufacturing_vision_studio/config.py",
        "src/manufacturing_vision_studio/e1/baseline.py",
        "src/manufacturing_vision_studio/e1/diagnostics_v2.py",
        "src/manufacturing_vision_studio/e1/domain.py",
        "src/manufacturing_vision_studio/e1/domain_v2.py",
        "src/manufacturing_vision_studio/e1/feature_mapping.py",
        "src/manufacturing_vision_studio/e1/generator.py",
        "src/manufacturing_vision_studio/e1/generator_v2.py",
        "src/manufacturing_vision_studio/e1/geometry.py",
        "src/manufacturing_vision_studio/e1/geometry_search.py",
        "src/manufacturing_vision_studio/e1/metrics.py",
        "src/manufacturing_vision_studio/e1/metrics_v2.py",
        "src/manufacturing_vision_studio/e1/model.py",
        "src/manufacturing_vision_studio/e1/oracle.py",
        "src/manufacturing_vision_studio/e1/policy_v2.py",
        "src/manufacturing_vision_studio/e1/protocol.py",
        "src/manufacturing_vision_studio/e1/protocol_v2.py",
        "src/manufacturing_vision_studio/e1/registration_v2.py",
        "src/manufacturing_vision_studio/e1/trust_boundaries.py",
        "src/manufacturing_vision_studio/errors.py",
        "src/manufacturing_vision_studio/evidence.py",
        "src/manufacturing_vision_studio/images.py",
        "src/manufacturing_vision_studio/model.py",
        "src/manufacturing_vision_studio/registry.py",
        "src/manufacturing_vision_studio/schema_validation.py",
    )
    return tuple(sorted(paths))


def projection_digest(entries: Sequence[tuple[str, str]]) -> str:
    payload = "\n".join(f"{path}\0{digest}" for path, digest in entries).encode()
    return hashlib.sha256(payload).hexdigest()


def implementation_projection() -> tuple[tuple[str, str], ...]:
    from manufacturing_vision_studio.e1.protocol_v2 import PROJECT_ROOT

    entries: list[tuple[str, str]] = []
    for relative_path in implementation_projection_paths():
        path = PROJECT_ROOT / relative_path
        if not path.is_file():
            raise ValueError(f"implementation projection dependency is missing: {relative_path}")
        entries.append((relative_path, sha256_bytes(path.read_bytes())))
    return tuple(entries)


def verify_dependency_guard(
    entries: Sequence[tuple[str, str]],
) -> dict[str, object]:
    """Verify exact paths and raw bytes against the hard-coded eligibility closure."""

    expected_paths = implementation_projection_paths()
    supplied = dict(entries)
    missing = tuple(path for path in expected_paths if path not in supplied)
    extra = tuple(sorted(set(supplied) - set(expected_paths)))
    duplicate_count = len(entries) - len(supplied)
    mismatched: list[str] = []
    from manufacturing_vision_studio.e1.protocol_v2 import PROJECT_ROOT

    for path in expected_paths:
        if path in supplied and sha256_bytes((PROJECT_ROOT / path).read_bytes()) != supplied[path]:
            mismatched.append(path)
    passed = not missing and not extra and duplicate_count == 0 and not mismatched
    return {
        "passed": passed,
        "missing_paths": list(missing),
        "extra_paths": list(extra),
        "duplicate_count": duplicate_count,
        "mismatched_paths": mismatched,
        "path_count": len(entries),
    }


def verify_determinism_evidence(
    runs: Sequence[Sequence[dict[str, object]]],
    *,
    expected_case_ids: Sequence[str],
) -> dict[str, object]:
    """Require two complete, ordered, byte-identical result projections."""

    protocol = "two_complete_ordered_result_projections_v2"
    if len(runs) != 2:
        return {
            "passed": False,
            "protocol": protocol,
            "run_count": len(runs),
            "expected_case_count": len(expected_case_ids),
            "reason": "TWO_COMPLETE_RUNS_REQUIRED",
            "projection_sha256": [],
        }
    digests: list[str] = []
    for run in runs:
        case_ids = tuple(item.get("case_id") for item in run)
        if case_ids != tuple(expected_case_ids):
            return {
                "passed": False,
                "protocol": protocol,
                "run_count": 2,
                "expected_case_count": len(expected_case_ids),
                "reason": "INCOMPLETE_OR_REORDERED_RUN",
                "projection_sha256": digests,
            }
        digests.append(canonical_json_hash(list(run)))
    return {
        "passed": digests[0] == digests[1],
        "protocol": protocol,
        "run_count": 2,
        "expected_case_count": len(expected_case_ids),
        "reason": None if digests[0] == digests[1] else "RESULT_PROJECTION_MISMATCH",
        "projection_sha256": digests,
    }


def run_development_trust_audit(
    plans: Sequence[E1V2CasePlan],
    work_root: Path | str,
) -> dict[str, object]:
    """Run the public frozen suite once, then project the six allowed development plans."""

    allowed: dict[str, E1V2CasePlan] = {}
    for plan in plans:
        if (
            plan.scope is not EvaluationScope.DEVELOPMENT
            or plan.group is not CaseGroup.TRUST_BOUNDARY
        ):
            continue
        specification = plan._render_plan.trust_boundary
        if specification is None:
            raise ValueError("development trust plan lacks its specification")
        if specification.scenario_id in allowed:
            raise ValueError("development trust scenario is duplicated")
        allowed[specification.scenario_id] = plan
    if len(allowed) != 6:
        raise ValueError("development trust audit requires exactly six declared scenarios")

    v1_protocol = load_e1_protocol()
    golden_path = trust_boundary_module.DEFAULT_GOLDEN_BUNDLE_PATH
    suite = trust_boundary_module.run_trust_boundary_suite(
        Path(work_root).resolve(),
        protocol=v1_protocol,
        golden_bundle_path=golden_path,
    )
    projected: list[dict[str, object]] = []
    for result in suite.results:
        matched_plan = allowed.get(result.scenario_id)
        if matched_plan is None:
            continue
        specification = matched_plan._render_plan.trust_boundary
        assert specification is not None
        if (
            result.split != "development"
            or result.expected_error_code != specification.expected_error_code
        ):
            raise ValueError("development trust declaration does not match public suite")
        projected.append({"case_id": matched_plan.case_id} | result.as_record())
    projected.sort(key=lambda item: str(item["case_id"]))
    return {
        "audit_method": "public_frozen_v1_trust_suite_then_development_projection",
        "full_suite_scenario_count": len(suite.results),
        "full_suite_all_passed": suite.all_passed,
        "full_suite_results": [result.as_record() for result in suite.results],
        "scenario_count": len(projected),
        "publication_count": sum(_integer_value(item["publication_count"]) for item in projected),
        "all_passed": len(projected) == 6 and all(bool(item["passed"]) for item in projected),
        "protocol_configuration_sha256": v1_protocol.configuration_sha256,
        "golden_bundle_sha256": sha256_bytes(golden_path.read_bytes()),
        "results": projected,
    }


def repair_candidate_selection_from_preserved_run(
    preserved_root: Path | str,
    *,
    protocol: E1V2Protocol | None = None,
) -> CandidateSelectionRecord:
    """Audit an immutable one-run comparison without rerunning candidate inference.

    Input bytes and already-recorded correction transforms are reconstructed for
    verification. Candidate search, policy inference, and timing are never called.
    """

    resolved_protocol = protocol or load_e1_v2_protocol()
    source_root = Path(preserved_root).resolve()
    preserved_selection, preserved_candidates = _load_and_verify_preserved_run(source_root)
    generator = E1V2Generator(resolved_protocol)
    development = generator.plan_cases(EvaluationScope.DEVELOPMENT)
    diagnostic_plans = build_scale_diagnostic_matrix(resolved_protocol)

    development_inputs, generated_by_id = _audit_development_inputs(
        development,
        generator,
        preserved_candidates,
    )
    diagnostic_inputs, diagnostic_rendered = _audit_diagnostic_inputs(
        diagnostic_plans,
        resolved_protocol,
        preserved_candidates,
    )

    with tempfile.TemporaryDirectory(prefix="mvs-e1-v2-selection-audit-") as temporary:
        trust = run_development_trust_audit(development, Path(temporary) / "trust")
    baseline = run_v0_1_baseline_audit()
    history = {"passed": True} | verify_e1_v1_history()
    current_entries = implementation_projection()
    current_guard = verify_dependency_guard(current_entries)
    if not bool(trust["all_passed"]):
        raise ValueError("current trust audit failed")
    if not bool(baseline["v0_1_regression"]):
        raise ValueError("current v0.1 baseline audit failed")
    if not bool(current_guard["passed"]):
        raise ValueError("current dependency audit failed")

    original_entries = tuple(
        (str(item["path"]), str(item["sha256"]))
        for item in preserved_selection["implementation_projection"]
    )
    supplied_paths = {path for path, _digest in original_entries}
    required_paths = set(implementation_projection_paths())
    execution_guard = {
        "passed": False,
        "reason": "INCOMPLETE_DEPENDENCY_CLOSURE",
        "snapshot_entry_verification_passed": True,
        "required_path_count": len(required_paths),
        "supplied_path_count": len(original_entries),
        "missing_paths": sorted(required_paths - supplied_paths),
        "extra_paths": sorted(supplied_paths - required_paths),
    }

    audit_candidates: dict[str, object] = {}
    candidate_records: list[CandidateEvaluationRecord] = []
    silhouette_cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
    expected_inference_ids = tuple(
        [plan.case_id for plan in development if plan.group is not CaseGroup.TRUST_BOUNDARY]
        + [plan.diagnostic_id for plan in diagnostic_plans]
    )
    for candidate_id in ("A", "B"):
        artifact = preserved_candidates[candidate_id]
        original_candidate = _object_value(artifact, "candidate")
        evidence = _derive_candidate_audit(
            candidate_id,
            artifact,
            development,
            diagnostic_plans,
            generated_by_id,
            diagnostic_rendered,
            expected_inference_ids,
            silhouette_cache,
        )
        audit_candidates[candidate_id] = evidence
        candidate_records.append(
            _candidate_from_preserved_metrics(
                original_candidate,
                trust_passed=bool(trust["all_passed"]),
                baseline_passed=bool(baseline["v0_1_regression"]),
            )
        )

    audit_evidence: dict[str, Any] = {
        "evidence_version": "2.0.0",
        "provenance": {
            "method": "preserved_one_run_post_run_audit",
            "comparison_rerun": False,
            "candidate_search_rerun": False,
            "candidate_inference_rerun": False,
            "benchmark_rerun": False,
            "recorded_transform_replay_only": True,
            "original_record_sha256": _PRESERVED_RECORD_SHA256,
            "original_selection_file_sha256": _PRESERVED_SELECTION_FILE_SHA256,
            "original_execution_projection_sha256": (
                _PRESERVED_EXECUTION_PROJECTION_SHA256
            ),
            "original_execution_projection": [
                {"path": path, "sha256": digest} for path, digest in original_entries
            ],
            "repository_snapshot_containing_execution_projection": _PRESERVED_SNAPSHOT,
            "candidate_artifact_sha256": dict(_PRESERVED_CANDIDATE_SHA256),
            "embedded_candidate_artifacts": {
                candidate_id: _encode_embedded_candidate_artifact(document)
                for candidate_id, document in preserved_candidates.items()
            },
            "current_audit_projection_sha256": projection_digest(current_entries),
        },
        "comparison_inputs": {
            "development": development_inputs,
            "diagnostic": diagnostic_inputs,
        },
        "execution_dependency_guard": execution_guard,
        "current_audits": {
            "dependency_guard": current_guard,
            "trust": trust,
            "baseline": baseline,
            "history": history,
        },
        "candidate_evidence": audit_candidates,
    }
    return finalize_candidate_selection(
        candidate_records,
        resolved_protocol,
        audit_evidence=audit_evidence,
    )


def _build_fresh_comparison_audit(
    output_root: Path,
    protocol: E1V2Protocol,
    development: Sequence[E1V2CasePlan],
    diagnostic_plans: Sequence[ScaleDiagnosticPlan],
    *,
    current_entries: Sequence[tuple[str, str]],
    trust_audit: Mapping[str, Any],
    baseline_audit: Mapping[str, Any],
    history_audit: Mapping[str, Any],
    dependency_audit: Mapping[str, Any],
) -> dict[str, Any]:
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_hashes: dict[str, str] = {}
    for candidate_id in ("A", "B"):
        payload = (output_root / f"candidate-{candidate_id.lower()}.json").read_bytes()
        artifact_hashes[candidate_id] = sha256_bytes(payload)
        artifacts[candidate_id] = _canonical_json_object(
            payload,
            f"fresh Candidate {candidate_id}",
        )
    generator = E1V2Generator(protocol)
    development_inputs, _generated = _audit_development_inputs(
        development,
        generator,
        artifacts,
    )
    diagnostic_inputs, _rendered = _audit_diagnostic_inputs(
        diagnostic_plans,
        protocol,
        artifacts,
    )
    expected_ids = tuple(
        [plan.case_id for plan in development if plan.group is not CaseGroup.TRUST_BOUNDARY]
        + [plan.diagnostic_id for plan in diagnostic_plans]
    )
    candidate_evidence = {
        candidate_id: _fresh_candidate_evidence(
            candidate_id,
            artifact,
            artifact_hashes[candidate_id],
            expected_ids,
        )
        for candidate_id, artifact in artifacts.items()
    }
    return {
        "evidence_version": "2.0.0",
        "provenance": {
            "method": "fresh_one_run_comparison_fail_closed",
            "candidate_comparison_executed": True,
            "candidate_artifact_sha256": artifact_hashes,
            "embedded_candidate_artifacts": {
                candidate_id: _encode_embedded_candidate_artifact(document)
                for candidate_id, document in artifacts.items()
            },
            "current_execution_projection_sha256": projection_digest(current_entries),
        },
        "comparison_inputs": {
            "development": development_inputs,
            "diagnostic": diagnostic_inputs,
        },
        "current_audits": {
            "dependency_guard": dict(dependency_audit),
            "trust": dict(trust_audit),
            "baseline": dict(baseline_audit),
            "history": dict(history_audit),
        },
        "candidate_evidence": candidate_evidence,
    }


def _fresh_candidate_evidence(
    candidate_id: str,
    artifact: Mapping[str, Any],
    artifact_sha256: str,
    expected_ids: Sequence[str],
) -> dict[str, object]:
    development_rows = _list_value(artifact, "development")
    diagnostic_rows = _list_value(artifact, "diagnostics")
    development_traces = [
        _object_value(_object_value(row, "inference_trace"), "geometry_trace")
        for row in development_rows
        if "inference_trace" in row
    ]
    diagnostic_traces = [
        _object_value(_object_value(row, "inference_trace"), "geometry_trace")
        for row in diagnostic_rows
    ]
    result_projection: list[dict[str, object]] = [
        {
            "case_id": str(row["case_id"]),
            "result_sha256": canonical_json_hash(_object_value(row, "inference_trace")),
        }
        for row in development_rows
        if "inference_trace" in row
    ]
    observations: list[dict[str, object]] = []
    for row in diagnostic_rows:
        trace = _object_value(row, "inference_trace")
        observations.append(
            {
                "diagnostic_id": str(row["diagnostic_id"]),
                "elapsed_normalization_ns": int(trace["elapsed_normalization_ns"]),
            }
        )
        deterministic_trace = {
            key: value for key, value in trace.items() if key != "elapsed_normalization_ns"
        }
        result_projection.append(
            {
                "case_id": str(row["diagnostic_id"]),
                "result_sha256": canonical_json_hash(deterministic_trace),
            }
        )
    if tuple(item["case_id"] for item in result_projection) != tuple(expected_ids):
        raise ValueError("fresh comparison result projection is incomplete")
    benchmark = dict(_object_value(artifact, "benchmark"))
    benchmark["observations"] = observations
    return {
        "candidate_artifact_sha256": artifact_sha256,
        "candidate_record": _object_value(artifact, "candidate"),
        "determinism": verify_determinism_evidence(
            (result_projection,),
            expected_case_ids=expected_ids,
        )
        | {"observed_complete_run_projection_sha256": canonical_json_hash(result_projection)},
        "benchmark": benchmark,
        "operation_counts": _operation_count_evidence(
            development_traces,
            diagnostic_traces,
        ),
    }


def _load_and_verify_preserved_run(
    source_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    selection_bytes = (source_root / "e1-v2-candidate-selection.json").read_bytes()
    if sha256_bytes(selection_bytes) != _PRESERVED_SELECTION_FILE_SHA256:
        raise ValueError("preserved selection bytes changed")
    snapshot_selection = _git_snapshot_blob(
        _PRESERVED_SNAPSHOT,
        "configs/evaluation/e1-v2-candidate-selection.json",
    )
    if snapshot_selection != selection_bytes:
        raise ValueError("preserved selection does not match its repository snapshot")
    selection = _canonical_json_object(selection_bytes, "preserved selection")
    if selection.get("record_sha256") != _PRESERVED_RECORD_SHA256:
        raise ValueError("preserved selection record identity changed")
    selfless = {key: value for key, value in selection.items() if key != "record_sha256"}
    if canonical_json_hash(selfless) != _PRESERVED_RECORD_SHA256:
        raise ValueError("preserved selection self-hash changed")
    entries = tuple(
        (str(item["path"]), str(item["sha256"]))
        for item in selection["implementation_projection"]
    )
    if (
        selection.get("implementation_projection_sha256")
        != _PRESERVED_EXECUTION_PROJECTION_SHA256
        or projection_digest(entries) != _PRESERVED_EXECUTION_PROJECTION_SHA256
    ):
        raise ValueError("preserved execution projection changed")
    for path, expected_digest in entries:
        if sha256_bytes(_git_snapshot_blob(_PRESERVED_SNAPSHOT, path)) != expected_digest:
            raise ValueError(f"snapshot does not contain projected bytes: {path}")

    candidates: dict[str, dict[str, Any]] = {}
    for candidate_id in ("A", "B"):
        payload = (source_root / f"candidate-{candidate_id.lower()}.json").read_bytes()
        if sha256_bytes(payload) != _PRESERVED_CANDIDATE_SHA256[candidate_id]:
            raise ValueError(f"preserved Candidate {candidate_id} bytes changed")
        document = _canonical_json_object(payload, f"preserved Candidate {candidate_id}")
        candidate = _object_value(document, "candidate")
        if candidate.get("candidate_id") != candidate_id:
            raise ValueError("preserved candidate identity changed")
        candidates[candidate_id] = document
    original_by_id = {
        str(item["candidate_id"]): item for item in selection["candidates"]
    }
    for candidate_id, artifact in candidates.items():
        raw = dict(_object_value(artifact, "candidate"))
        raw["rejection_reasons"] = original_by_id[candidate_id]["rejection_reasons"]
        if raw != original_by_id[candidate_id]:
            raise ValueError("preserved candidate metrics do not match selection")
    return selection, candidates


def _git_snapshot_blob(snapshot: str, relative_path: str) -> bytes:
    from manufacturing_vision_studio.e1.protocol_v2 import PROJECT_ROOT

    completed = subprocess.run(
        ["git", "show", f"{snapshot}:{relative_path}"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError(f"repository snapshot blob is unavailable: {relative_path}")
    return completed.stdout


def _canonical_json_object(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            parsed[key] = value
        return parsed

    try:
        document = json.loads(payload, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be an object")
    if canonical_json_bytes(document) + b"\n" != payload:
        raise ValueError(f"{label} is not canonical JSON")
    return document


def _object_value(document: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _list_value(document: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be an object array")
    return value


def _integer_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("audit value must be an integer")
    return value


def _float_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("audit value must be numeric")
    return float(value)


def _audit_development_inputs(
    plans: Sequence[E1V2CasePlan],
    generator: E1V2Generator,
    candidates: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, object]], dict[str, E1V2InferenceInput]]:
    candidate_rows = {
        candidate_id: _list_value(artifact, "development")
        for candidate_id, artifact in candidates.items()
    }
    if any(len(rows) != len(plans) for rows in candidate_rows.values()):
        raise ValueError("preserved development case count changed")
    inputs: list[dict[str, object]] = []
    inference_by_id: dict[str, E1V2InferenceInput] = {}
    for index, plan in enumerate(plans):
        rows = [candidate_rows[candidate_id][index] for candidate_id in ("A", "B")]
        if any(row.get("case_id") != plan.case_id for row in rows):
            raise ValueError("preserved development order changed")
        if plan.group is CaseGroup.TRUST_BOUNDARY:
            specification = plan._render_plan.trust_boundary
            if specification is None or any(row.get("trust_boundary") is not True for row in rows):
                raise ValueError("preserved trust input changed")
            inputs.append(
                plan.membership_record()
                | {
                    "input_kind": "trust_scenario",
                    "scenario_id": specification.scenario_id,
                    "expected_error_code": specification.expected_error_code,
                }
            )
            continue
        generated = generator.generate_case(plan)
        inference = E1V2InferenceInput.from_generated(generated)
        inference_by_id[plan.case_id] = inference
        for row in rows:
            trace = _object_value(row, "inference_trace")
            source_hashes = _object_value(trace, "source_hashes")
            if source_hashes != {
                "reference_sha256": generated.reference_sha256,
                "inspection_sha256": generated.inspection_sha256,
            }:
                raise ValueError("preserved development source hashes changed")
        inputs.append(
            generated.membership_record()
            | {
                "input_kind": "inference",
            }
        )
    return inputs, inference_by_id


def _audit_diagnostic_inputs(
    plans: Sequence[ScaleDiagnosticPlan],
    protocol: E1V2Protocol,
    candidates: Mapping[str, Mapping[str, Any]],
) -> tuple[
    list[dict[str, object]],
    dict[str, tuple[E1V2InferenceInput, np.ndarray, bytes]],
]:
    candidate_rows = {
        candidate_id: _list_value(artifact, "diagnostics")
        for candidate_id, artifact in candidates.items()
    }
    if any(len(rows) != len(plans) for rows in candidate_rows.values()):
        raise ValueError("preserved diagnostic case count changed")
    inputs: list[dict[str, object]] = []
    rendered: dict[str, tuple[E1V2InferenceInput, np.ndarray, bytes]] = {}
    for index, plan in enumerate(plans):
        rows = [candidate_rows[candidate_id][index] for candidate_id in ("A", "B")]
        if any(
            row.get("diagnostic_id") != plan.diagnostic_id
            or row.get("seed") != plan.seed
            or row.get("combination") != plan.combination
            for row in rows
        ):
            raise ValueError("preserved diagnostic order changed")
        inference, truth, truth_bytes = _render_diagnostic(plan, protocol)
        rendered[plan.diagnostic_id] = (inference, truth, truth_bytes)
        truth_record = plan.diagnostic_truth_record() | {
            "authoritative_mask_sha256": sha256_bytes(truth_bytes)
        }
        for row in rows:
            trace = _object_value(row, "inference_trace")
            if _object_value(trace, "source_hashes") != {
                "reference_sha256": inference.reference_sha256,
                "inspection_sha256": inference.inspection_sha256,
            } or _object_value(row, "diagnostic_truth") != truth_record:
                raise ValueError("preserved diagnostic inputs changed")
        inputs.append(
            {
                "diagnostic_id": plan.diagnostic_id,
                "seed": plan.seed,
                "combination": plan.combination,
                "cad_revision": plan.cad_revision.value,
                "view_id": plan.view_id.value,
                "reference_sha256": inference.reference_sha256,
                "inspection_sha256": inference.inspection_sha256,
                "diagnostic_truth": truth_record,
            }
        )
    return inputs, rendered


def _derive_candidate_audit(
    candidate_id: str,
    artifact: Mapping[str, Any],
    development: Sequence[E1V2CasePlan],
    diagnostic_plans: Sequence[ScaleDiagnosticPlan],
    generated_by_id: Mapping[str, E1V2InferenceInput],
    diagnostic_rendered: Mapping[str, tuple[E1V2InferenceInput, np.ndarray, bytes]],
    expected_inference_ids: Sequence[str],
    silhouette_cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]],
) -> dict[str, object]:
    development_rows = _list_value(artifact, "development")
    diagnostic_rows = _list_value(artifact, "diagnostics")
    original_candidate = _object_value(artifact, "candidate")
    development_objectives: list[dict[str, object]] = []
    diagnostic_geometry: list[dict[str, object]] = []
    result_projection: list[dict[str, object]] = []
    development_traces: list[Mapping[str, Any]] = []
    diagnostic_traces: list[Mapping[str, Any]] = []

    for development_plan, row in zip(development, development_rows, strict=True):
        if development_plan.group is CaseGroup.TRUST_BOUNDARY:
            continue
        trace = _object_value(row, "inference_trace")
        geometry_trace = _object_value(trace, "geometry_trace")
        if development_plan.case_id not in generated_by_id:
            raise ValueError("preserved development inference input is missing")
        development_objectives.append(
            {
                "case_id": development_plan.case_id,
                "objective_after_rounded_8_decimals": float(
                    geometry_trace["objective_after"]
                ),
            }
        )
        development_traces.append(geometry_trace)
        result_projection.append(
            {
                "case_id": development_plan.case_id,
                "result_sha256": canonical_json_hash(trace),
            }
        )

    for diagnostic_plan, row in zip(diagnostic_plans, diagnostic_rows, strict=True):
        trace = _object_value(row, "inference_trace")
        geometry_trace = _object_value(trace, "geometry_trace")
        inference, _truth, _truth_bytes = diagnostic_rendered[diagnostic_plan.diagnostic_id]
        try:
            components = _recorded_objective_components(
                inference,
                geometry_trace,
                silhouette_cache,
            )
        except ValueError as exc:
            raise ValueError(
                f"Candidate {candidate_id} {diagnostic_plan.diagnostic_id}: {exc}"
            ) from exc
        diagnostic_geometry.append(
            {
                "diagnostic_id": diagnostic_plan.diagnostic_id,
                **components,
                "identity_truth_pixel_recall": float(trace["identity_truth_pixel_recall"]),
                "selected_truth_pixel_recall": float(trace["selected_truth_pixel_recall"]),
                "identity_dice": float(trace["identity_dice"]),
                "selected_dice": float(trace["selected_dice"]),
            }
        )
        diagnostic_traces.append(geometry_trace)
        deterministic_trace = {
            key: value for key, value in trace.items() if key != "elapsed_normalization_ns"
        }
        result_projection.append(
            {
                "case_id": diagnostic_plan.diagnostic_id,
                "result_sha256": canonical_json_hash(deterministic_trace),
            }
        )
    if tuple(item["case_id"] for item in result_projection) != tuple(expected_inference_ids):
        raise ValueError("preserved inference result order changed")

    benchmark_source = _object_value(artifact, "benchmark")
    benchmark_observations = [
        {
            "diagnostic_id": str(row["diagnostic_id"]),
            "elapsed_normalization_ns": int(
                _object_value(row, "inference_trace")["elapsed_normalization_ns"]
            ),
        }
        for row in diagnostic_rows
    ]
    runtime_samples = [
        _integer_value(item["elapsed_normalization_ns"])
        for item in benchmark_observations
    ]
    if (
        len(runtime_samples) != 108
        or _nearest_rank_p95(runtime_samples) != int(benchmark_source["p95_ns"])
        or int(benchmark_source["p95_ns"]) != int(original_candidate["runtime_p95_ns"])
    ):
        raise ValueError("preserved benchmark observations do not reproduce p95")
    benchmark = dict(benchmark_source)
    benchmark["observations"] = benchmark_observations

    operation_counts = _operation_count_evidence(development_traces, diagnostic_traces)
    if operation_counts["worst_case_candidate_pixels"] != int(
        original_candidate["worst_case_candidate_pixels"]
    ):
        raise ValueError("preserved operation counts do not reproduce worst case")

    serialized_objective_values = [
        _float_value(item["objective_after_rounded_8_decimals"])
        for item in development_objectives
    ] + [
        _float_value(item["original_objective_after_rounded_8_decimals"])
        for item in diagnostic_geometry
    ]
    if abs(
        float(median(serialized_objective_values))
        - float(original_candidate["median_post_normalization_objective"])
    ) > 5e-9:
        raise ValueError("serialized objectives do not corroborate median objective")
    defect_rows = [
        row
        for plan, row in zip(diagnostic_plans, diagnostic_geometry, strict=True)
        if plan.defect_type is not None
    ]
    recall_drop = max(
        (
            _float_value(row["identity_truth_pixel_recall"])
            - _float_value(row["selected_truth_pixel_recall"])
            for row in defect_rows
        ),
        default=0.0,
    )
    dice_drop = float(
        median(
            _float_value(row["identity_dice"]) - _float_value(row["selected_dice"])
            for row in defect_rows
        )
    )
    if (
        recall_drop != float(original_candidate["maximum_diagnostic_truth_recall_drop"])
        or dice_drop != float(original_candidate["diagnostic_median_dice_drop"])
    ):
        raise ValueError("preserved diagnostic truth metrics do not reproduce candidate metrics")

    determinism = verify_determinism_evidence(
        (result_projection,),
        expected_case_ids=expected_inference_ids,
    )
    return {
        "candidate_artifact_sha256": _PRESERVED_CANDIDATE_SHA256[candidate_id],
        "preserved_candidate_record": dict(original_candidate),
        "determinism": determinism
        | {
            "observed_complete_run_projection_sha256": canonical_json_hash(result_projection),
            "limited_repeat_observation": {
                "case_id": expected_inference_ids[0],
                "reported_equal": bool(original_candidate["deterministic"]),
                "persisted_repeat_projection": False,
                "scope": "first_ordinary_development_case_only",
            },
        },
        "benchmark": benchmark,
        "operation_counts": operation_counts,
        "development_objectives": development_objectives,
        "diagnostic_geometry": diagnostic_geometry,
    }


def _recorded_objective_components(
    inference: E1V2InferenceInput,
    trace: Mapping[str, Any],
    silhouette_cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]],
) -> dict[str, object]:
    cache_key = (inference.reference_sha256, inference.inspection_sha256)
    silhouettes = silhouette_cache.get(cache_key)
    if silhouettes is None:
        silhouettes = (
            largest_component_silhouette(_decode_rgb(inference.reference_bytes)),
            largest_component_silhouette(_decode_rgb(inference.inspection_bytes)),
        )
        silhouette_cache[cache_key] = silhouettes
    reference, inspection = silhouettes
    before = alignment_objective(
        reference,
        inspection,
        silhouette_edges(reference),
        silhouette_edges(inspection),
    )
    serialized_transform = {
        "rotation_degrees": float(trace["correction_rotation_degrees"]),
        "scale": float(trace["correction_scale"]),
        "dx": float(trace["correction_dx"]),
        "dy": float(trace["correction_dy"]),
    }
    config = GeometryConfig()
    exact_scale, scale_restoration = _restore_exact_frozen_bound(
        serialized_transform["scale"],
        boundary_flag=bool(trace["at_scale_bound"]),
        bounds=config.correction_scale_bounds,
        identifiers=("correction_scale_bounds.lower", "correction_scale_bounds.upper"),
        representations=("1/1.02", "1/0.98"),
    )
    exact_rotation, rotation_restoration = _restore_exact_frozen_bound(
        serialized_transform["rotation_degrees"],
        boundary_flag=bool(trace["at_rotation_bound"]),
        bounds=config.rotation_bounds_degrees,
        identifiers=("rotation_bounds_degrees.lower", "rotation_bounds_degrees.upper"),
        representations=("-1.5", "1.5"),
    )
    restorations = [
        restoration
        for restoration in (scale_restoration, rotation_restoration)
        if restoration is not None
    ]
    corrected = _render_silhouette(
        inspection,
        exact_rotation,
        exact_scale,
        serialized_transform["dx"],
        serialized_transform["dy"],
    )
    after = alignment_objective(
        reference,
        corrected,
        silhouette_edges(reference),
        silhouette_edges(corrected),
    )
    serialized_checks = {
        "objective_before": before.value,
        "objective_after": after.value,
        "foreground_iou_before": before.foreground_iou,
        "foreground_iou_after": after.foreground_iou,
    }
    for key, reconstructed in serialized_checks.items():
        if round(reconstructed, 8) != float(trace[key]):
            raise ValueError(f"recorded transform does not reproduce {key}")
    return {
        "derivation": (
            "recorded_transform_with_exact_frozen_bound_restoration"
            if restorations
            else "replay_from_recorded_8_decimal_transform_parameters"
        ),
        "serialized_transform": serialized_transform,
        "applied_replay_transform": {
            "rotation_degrees": exact_rotation,
            "scale": exact_scale,
            "dx": serialized_transform["dx"],
            "dy": serialized_transform["dy"],
        },
        "bound_restorations": restorations,
        "original_objective_before_rounded_8_decimals": float(trace["objective_before"]),
        "original_objective_after_rounded_8_decimals": float(trace["objective_after"]),
        "replayed_objective_before": before.value,
        "replayed_objective_after": after.value,
        "silhouette_xor_rate_before": before.silhouette_xor_rate,
        "silhouette_xor_rate_after": after.silhouette_xor_rate,
        "normalized_edge_mae_before": before.normalized_edge_mae,
        "normalized_edge_mae_after": after.normalized_edge_mae,
        "foreground_iou_before": before.foreground_iou,
        "foreground_iou_after": after.foreground_iou,
    }


def _verify_recorded_diagnostic_geometry(
    inference: E1V2InferenceInput,
    inference_trace: Mapping[str, Any],
    recorded: Mapping[str, Any],
    *,
    diagnostic_id: str,
    silhouette_cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]],
) -> None:
    geometry_trace = _object_value(inference_trace, "geometry_trace")
    expected = {
        "diagnostic_id": diagnostic_id,
        **_recorded_objective_components(
            inference,
            geometry_trace,
            silhouette_cache,
        ),
        "identity_truth_pixel_recall": float(
            inference_trace["identity_truth_pixel_recall"]
        ),
        "selected_truth_pixel_recall": float(
            inference_trace["selected_truth_pixel_recall"]
        ),
        "identity_dice": float(inference_trace["identity_dice"]),
        "selected_dice": float(inference_trace["selected_dice"]),
    }
    if recorded != expected:
        raise ValueError(f"diagnostic replay evidence changed: {diagnostic_id}")


def _verify_candidate_replay_evidence(
    evidence: Mapping[str, Any],
    embedded: Mapping[str, Mapping[str, Any]],
    protocol: E1V2Protocol,
) -> None:
    diagnostic_plans = build_scale_diagnostic_matrix(protocol)
    _inputs, rendered = _audit_diagnostic_inputs(
        diagnostic_plans,
        protocol,
        embedded,
    )
    summaries = _object_value(evidence, "candidate_evidence")
    silhouette_cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
    for candidate_id in ("A", "B"):
        summary = _object_value(summaries, candidate_id)
        artifact_rows = _list_value(embedded[candidate_id], "diagnostics")
        recorded_geometry = (
            _list_value(summary, "diagnostic_geometry")
            if "diagnostic_geometry" in summary
            else None
        )
        if recorded_geometry is not None and len(recorded_geometry) != len(
            diagnostic_plans
        ):
            raise ValueError("candidate diagnostic replay count changed")
        for index, (plan, artifact_row) in enumerate(
            zip(diagnostic_plans, artifact_rows, strict=True)
        ):
            inference_trace = _object_value(artifact_row, "inference_trace")
            inference = rendered[plan.diagnostic_id][0]
            if recorded_geometry is None:
                _recorded_objective_components(
                    inference,
                    _object_value(inference_trace, "geometry_trace"),
                    silhouette_cache,
                )
                continue
            _verify_recorded_diagnostic_geometry(
                inference,
                inference_trace,
                recorded_geometry[index],
                diagnostic_id=plan.diagnostic_id,
                silhouette_cache=silhouette_cache,
            )


def _restore_exact_frozen_bound(
    serialized_value: float,
    *,
    boundary_flag: bool,
    bounds: tuple[float, float],
    identifiers: tuple[str, str],
    representations: tuple[str, str],
) -> tuple[float, dict[str, object] | None]:
    if not boundary_flag:
        return serialized_value, None
    matching_indices = [
        index for index, bound in enumerate(bounds) if round(bound, 8) == serialized_value
    ]
    if len(matching_indices) != 1:
        raise ValueError("boundary flag does not identify one unique frozen bound")
    index = matching_indices[0]
    restored = bounds[index]
    return restored, {
        "serialized_value": serialized_value,
        "restored_exact_value": restored,
        "restored_exact_representation": representations[index],
        "bound_identifier": identifiers[index],
        "configuration_path": "configs/evaluation/e1-v2.json",
        "configuration_sha256": _PRESERVED_V2_CONFIG_FILE_SHA256,
    }


def _operation_count_evidence(
    development: Sequence[Mapping[str, Any]],
    diagnostic: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    def total(rows: Sequence[Mapping[str, Any]], field_name: str) -> int:
        return sum(int(row[field_name]) for row in rows)

    all_rows = tuple(development) + tuple(diagnostic)
    return {
        "development_inference_case_count": len(development),
        "diagnostic_case_count": len(diagnostic),
        "total_candidates_evaluated": total(all_rows, "candidates_evaluated"),
        "development_candidates_evaluated": total(development, "candidates_evaluated"),
        "diagnostic_candidates_evaluated": total(diagnostic, "candidates_evaluated"),
        "total_coarse_candidates_evaluated": total(
            all_rows, "coarse_candidates_evaluated"
        ),
        "total_refine_candidates_evaluated": total(
            all_rows, "refine_candidates_evaluated"
        ),
        "total_candidate_pixels_evaluated": total(
            all_rows, "candidate_pixels_evaluated"
        ),
        "development_candidate_pixels_evaluated": total(
            development, "candidate_pixels_evaluated"
        ),
        "diagnostic_candidate_pixels_evaluated": total(
            diagnostic, "candidate_pixels_evaluated"
        ),
        "worst_case_candidate_pixels": max(
            (int(row["candidate_pixels_evaluated"]) for row in all_rows),
            default=0,
        ),
    }


def _candidate_from_preserved_metrics(
    preserved: Mapping[str, Any],
    *,
    trust_passed: bool,
    baseline_passed: bool,
) -> CandidateEvaluationRecord:
    if not trust_passed or not baseline_passed:
        raise ValueError("post-run audits must pass before recording their separate evidence")
    return CandidateEvaluationRecord(
        candidate_id=str(preserved["candidate_id"]),
        determinism_verified=False,
        dependency_guard_passed=False,
        work_cap_passed=bool(preserved["work_cap_passed"]),
        development_gates_passed=bool(preserved["development_gates_passed"]),
        medium_high_defect_recall=float(preserved["medium_high_defect_recall"]),
        trust_verified=False,
        v0_1_regression_verified=False,
        maximum_diagnostic_truth_recall_drop=float(
            preserved["maximum_diagnostic_truth_recall_drop"]
        ),
        diagnostic_median_dice_drop=float(preserved["diagnostic_median_dice_drop"]),
        development_nuisance_false_positives=int(
            preserved["development_nuisance_false_positives"]
        ),
        medium_high_defect_false_negatives=int(
            preserved["medium_high_defect_false_negatives"]
        ),
        affected_feature_mapping_errors=int(preserved["affected_feature_mapping_errors"]),
        positive_case_median_dice=float(preserved["positive_case_median_dice"]),
        median_post_normalization_objective=float(
            preserved["median_post_normalization_objective"]
        ),
        worst_case_candidate_pixels=int(preserved["worst_case_candidate_pixels"]),
        runtime_p95_ns=int(preserved["runtime_p95_ns"]),
    )


def run_v0_1_baseline_audit() -> dict[str, object]:
    """Execute the public baseline gate with all known path overrides rejected."""

    override_names = ("MVS_DATA_DIR", "MVS_SCHEMA_DIR")
    present = [name for name in override_names if os.environ.get(name)]
    if present:
        raise ValueError(f"baseline audit rejects environment overrides: {present!r}")
    from manufacturing_vision_studio.e1.protocol_v2 import PROJECT_ROOT

    bindings = tuple(
        (
            path,
            sha256_bytes((PROJECT_ROOT / path).read_bytes()),
        )
        for path in _V0_1_BASELINE_INPUT_PATHS
    )
    result = evaluate_v0_1_baseline(load_e1_protocol()).as_record()
    return result | {
        "audit_method": "public_evaluate_v0_1_baseline_with_path_overrides_rejected",
        "environment_boundary": {
            "policy": "reject_nonempty_known_path_overrides",
            "checked": list(override_names),
            "observed": [],
        },
        "input_bindings": [
            {"path": path, "sha256": digest} for path, digest in bindings
        ],
    }


def _verify_current_baseline_audit(recorded: Mapping[str, Any]) -> None:
    bindings = _list_value(recorded, "input_bindings")
    recorded_paths = tuple(str(binding["path"]) for binding in bindings)
    if recorded_paths != _V0_1_BASELINE_INPUT_PATHS:
        raise ValueError("current baseline audit changed: input binding paths")
    expected = run_v0_1_baseline_audit()
    if recorded != expected:
        raise ValueError("current baseline audit changed")


def _encode_embedded_candidate_artifact(document: Mapping[str, Any]) -> dict[str, object]:
    raw = canonical_json_bytes(document) + b"\n"
    compressed = zlib.compress(raw, level=9)
    return {
        "encoding_protocol": "rfc1950_zlib_level_9_then_rfc4648_base64_v1",
        "uncompressed_bytes": len(raw),
        "compressed_bytes": len(compressed),
        "uncompressed_sha256": sha256_bytes(raw),
        "compressed_sha256": sha256_bytes(compressed),
        "payload_base64": base64.b64encode(compressed).decode("ascii"),
    }


def _decode_embedded_candidate_artifact(
    envelope: Mapping[str, Any],
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    if envelope.get("encoding_protocol") != (
        "rfc1950_zlib_level_9_then_rfc4648_base64_v1"
    ):
        raise ValueError("embedded candidate encoding protocol is invalid")
    expected_raw_length = int(envelope["uncompressed_bytes"])
    expected_compressed_length = int(envelope["compressed_bytes"])
    if not 1 <= expected_raw_length <= _MAX_EMBEDDED_RAW_BYTES or not (
        1 <= expected_compressed_length <= _MAX_EMBEDDED_COMPRESSED_BYTES
    ):
        raise ValueError("embedded candidate lengths exceed the audit cap")
    encoded = envelope.get("payload_base64")
    if not isinstance(encoded, str):
        raise ValueError("embedded candidate payload is invalid")
    expected_encoded_length = 4 * ((expected_compressed_length + 2) // 3)
    if (
        len(encoded) > _MAX_EMBEDDED_BASE64_LENGTH
        or len(encoded) != expected_encoded_length
    ):
        raise ValueError("embedded candidate exceeds the encoded-length cap")
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("embedded candidate base64 is invalid") from exc
    if base64.b64encode(compressed).decode("ascii") != encoded:
        raise ValueError("embedded candidate base64 is noncanonical")
    if (
        len(compressed) != expected_compressed_length
        or sha256_bytes(compressed) != envelope.get("compressed_sha256")
    ):
        raise ValueError("embedded candidate compressed binding changed")
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, expected_raw_length + 1)
    if len(raw) > expected_raw_length or decompressor.unconsumed_tail:
        raise ValueError("embedded candidate exceeds declared uncompressed length")
    raw += decompressor.flush(expected_raw_length + 1 - len(raw))
    if (
        not decompressor.eof
        or decompressor.unused_data
        or len(raw) != expected_raw_length
        or sha256_bytes(raw) != expected_sha256
        or envelope.get("uncompressed_sha256") != expected_sha256
    ):
        raise ValueError("embedded candidate raw binding changed")
    return _canonical_json_object(raw, "embedded candidate artifact")


def _validate_selection_audit_bindings(
    evidence: Mapping[str, Any],
    *,
    candidates: Sequence[CandidateEvaluationRecord],
    current_entries: Sequence[tuple[str, str]],
) -> None:
    """Validate portable bindings without treating audit claims as verified."""

    provenance = _object_value(evidence, "provenance")
    if provenance.get("method") == "fresh_one_run_comparison_fail_closed":
        if (
            provenance.get("candidate_comparison_executed") is not True
            or provenance.get("current_execution_projection_sha256")
            != projection_digest(current_entries)
        ):
            raise ValueError("fresh comparison provenance changed")
        artifact_hashes = _object_value(provenance, "candidate_artifact_sha256")
        envelopes = _object_value(provenance, "embedded_candidate_artifacts")
        embedded: dict[str, dict[str, Any]] = {}
        for candidate_id in ("A", "B"):
            expected_hash = artifact_hashes.get(candidate_id)
            if not isinstance(expected_hash, str):
                raise ValueError("fresh candidate artifact hash is invalid")
            embedded[candidate_id] = _decode_embedded_candidate_artifact(
                _object_value(envelopes, candidate_id),
                expected_sha256=expected_hash,
            )
        outer_by_id = {candidate.candidate_id: candidate for candidate in candidates}
        summaries = _object_value(evidence, "candidate_evidence")
        for candidate_id in ("A", "B"):
            summary = _object_value(summaries, candidate_id)
            artifact = embedded[candidate_id]
            artifact_candidate = _object_value(artifact, "candidate")
            if (
                summary.get("candidate_artifact_sha256") != artifact_hashes[candidate_id]
                or _object_value(summary, "candidate_record") != artifact_candidate
            ):
                raise ValueError("fresh candidate summary binding changed")
            outer_record = outer_by_id[candidate_id].as_record()
            for key, value in artifact_candidate.items():
                if key != "rejection_reasons" and outer_record.get(key) != value:
                    raise ValueError("fresh outer candidate metrics changed")
            development_rows = _list_value(artifact, "development")
            diagnostic_rows = _list_value(artifact, "diagnostics")
            development_traces = [
                _object_value(_object_value(row, "inference_trace"), "geometry_trace")
                for row in development_rows
                if "inference_trace" in row
            ]
            diagnostic_traces = [
                _object_value(_object_value(row, "inference_trace"), "geometry_trace")
                for row in diagnostic_rows
            ]
            if _object_value(summary, "operation_counts") != _operation_count_evidence(
                development_traces,
                diagnostic_traces,
            ):
                raise ValueError("fresh candidate operation counts changed")
            benchmark = _object_value(summary, "benchmark")
            observations = _list_value(benchmark, "observations")
            samples = [
                _integer_value(item["elapsed_normalization_ns"])
                for item in observations
            ]
            if _nearest_rank_p95(samples) != outer_by_id[candidate_id].runtime_p95_ns:
                raise ValueError("fresh candidate benchmark changed")
            determinism = _object_value(summary, "determinism")
            if (
                determinism.get("passed") is not False
                or determinism.get("reason") != "TWO_COMPLETE_RUNS_REQUIRED"
                or outer_by_id[candidate_id].determinism_verified is not False
            ):
                raise ValueError("fresh candidate determinism evidence changed")
        return

    exact_provenance = {
        "method": "preserved_one_run_post_run_audit",
        "comparison_rerun": False,
        "candidate_search_rerun": False,
        "candidate_inference_rerun": False,
        "benchmark_rerun": False,
        "recorded_transform_replay_only": True,
        "original_record_sha256": _PRESERVED_RECORD_SHA256,
        "original_selection_file_sha256": _PRESERVED_SELECTION_FILE_SHA256,
        "original_execution_projection_sha256": _PRESERVED_EXECUTION_PROJECTION_SHA256,
        "repository_snapshot_containing_execution_projection": _PRESERVED_SNAPSHOT,
        "candidate_artifact_sha256": _PRESERVED_CANDIDATE_SHA256,
        "current_audit_projection_sha256": projection_digest(current_entries),
    }
    for key, expected in exact_provenance.items():
        if provenance.get(key) != expected:
            raise ValueError(f"selection audit provenance changed: {key}")
    original_projection = _list_value(provenance, "original_execution_projection")
    original_entries = tuple(
        (str(item["path"]), str(item["sha256"])) for item in original_projection
    )
    if projection_digest(original_entries) != _PRESERVED_EXECUTION_PROJECTION_SHA256:
        raise ValueError("original execution projection digest changed")
    execution_guard = _object_value(evidence, "execution_dependency_guard")
    supplied_paths = {path for path, _digest in original_entries}
    required_paths = set(implementation_projection_paths())
    if (
        execution_guard.get("passed") is not False
        or execution_guard.get("reason") != "INCOMPLETE_DEPENDENCY_CLOSURE"
        or execution_guard.get("snapshot_entry_verification_passed") is not True
        or execution_guard.get("required_path_count") != len(required_paths)
        or execution_guard.get("supplied_path_count") != len(original_entries)
        or execution_guard.get("missing_paths")
        != sorted(required_paths - supplied_paths)
        or execution_guard.get("extra_paths")
        != sorted(supplied_paths - required_paths)
    ):
        raise ValueError("execution dependency-guard evidence changed")
    embedded_envelopes = _object_value(provenance, "embedded_candidate_artifacts")
    embedded = {
        candidate_id: _decode_embedded_candidate_artifact(
            _object_value(embedded_envelopes, candidate_id),
            expected_sha256=_PRESERVED_CANDIDATE_SHA256[candidate_id],
        )
        for candidate_id in ("A", "B")
    }
    candidate_evidence = _object_value(evidence, "candidate_evidence")
    outer_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    for candidate_id in ("A", "B"):
        _validate_candidate_audit_evidence(
            candidate_id,
            _object_value(candidate_evidence, candidate_id),
            embedded[candidate_id],
            outer_by_id[candidate_id],
        )


def _verify_selection_audit_evidence(
    evidence: Mapping[str, Any],
    *,
    candidates: Sequence[CandidateEvaluationRecord],
    current_entries: Sequence[tuple[str, str]],
    protocol: E1V2Protocol,
) -> None:
    provenance = _object_value(evidence, "provenance")
    if provenance.get("method") == "fresh_one_run_comparison_fail_closed":
        _validate_fresh_comparison_audit_evidence(
            evidence,
            candidates=candidates,
            current_entries=current_entries,
            protocol=protocol,
        )
        return
    exact_provenance = {
        "method": "preserved_one_run_post_run_audit",
        "comparison_rerun": False,
        "candidate_search_rerun": False,
        "candidate_inference_rerun": False,
        "benchmark_rerun": False,
        "recorded_transform_replay_only": True,
        "original_record_sha256": _PRESERVED_RECORD_SHA256,
        "original_selection_file_sha256": _PRESERVED_SELECTION_FILE_SHA256,
        "original_execution_projection_sha256": _PRESERVED_EXECUTION_PROJECTION_SHA256,
        "repository_snapshot_containing_execution_projection": _PRESERVED_SNAPSHOT,
        "candidate_artifact_sha256": _PRESERVED_CANDIDATE_SHA256,
        "current_audit_projection_sha256": projection_digest(current_entries),
    }
    for key, expected in exact_provenance.items():
        if provenance.get(key) != expected:
            raise ValueError(f"selection audit provenance changed: {key}")

    snapshot_selection = _canonical_json_object(
        _git_snapshot_blob(
            _PRESERVED_SNAPSHOT,
            "configs/evaluation/e1-v2-candidate-selection.json",
        ),
        "repository snapshot selection",
    )
    if snapshot_selection.get("record_sha256") != _PRESERVED_RECORD_SHA256:
        raise ValueError("repository snapshot selection identity changed")
    original_projection = _list_value(provenance, "original_execution_projection")
    if original_projection != snapshot_selection.get("implementation_projection"):
        raise ValueError("original execution projection is not recoverable from snapshot")
    original_entries = tuple(
        (str(item["path"]), str(item["sha256"])) for item in original_projection
    )
    if projection_digest(original_entries) != _PRESERVED_EXECUTION_PROJECTION_SHA256:
        raise ValueError("original execution projection digest changed")

    execution_guard = _object_value(evidence, "execution_dependency_guard")
    supplied_paths = {path for path, _digest in original_entries}
    required_paths = set(implementation_projection_paths())
    expected_missing = sorted(required_paths - supplied_paths)
    if (
        execution_guard.get("passed") is not False
        or execution_guard.get("reason") != "INCOMPLETE_DEPENDENCY_CLOSURE"
        or execution_guard.get("snapshot_entry_verification_passed") is not True
        or execution_guard.get("required_path_count") != len(required_paths)
        or execution_guard.get("supplied_path_count") != len(original_entries)
        or execution_guard.get("missing_paths") != expected_missing
        or execution_guard.get("extra_paths") != sorted(supplied_paths - required_paths)
    ):
        raise ValueError("execution dependency-guard evidence changed")

    current_audits = _object_value(evidence, "current_audits")
    if _object_value(current_audits, "dependency_guard") != verify_dependency_guard(
        current_entries
    ):
        raise ValueError("current dependency-guard evidence changed")
    _verify_current_baseline_audit(_object_value(current_audits, "baseline"))
    trust = _object_value(current_audits, "trust")
    development = E1V2Generator(protocol).plan_cases(EvaluationScope.DEVELOPMENT)
    with tempfile.TemporaryDirectory(prefix="mvs-e1-v2-selection-load-trust-") as temporary:
        expected_trust = run_development_trust_audit(
            development,
            Path(temporary) / "trust",
        )
    if trust != expected_trust:
        raise ValueError("current trust audit changed")
    trust_results = _list_value(trust, "results")
    full_trust_results = _list_value(trust, "full_suite_results")
    if (
        trust.get("full_suite_scenario_count") != 24
        or trust.get("full_suite_all_passed") is not True
        or trust.get("all_passed") is not True
        or trust.get("publication_count") != 0
        or len(full_trust_results) != 24
        or not all(
            result.get("passed") is True and result.get("publication_count") == 0
            for result in full_trust_results
        )
        or not all(result.get("passed") is True for result in trust_results)
    ):
        raise ValueError("current trust audit is not a proved pass")
    history = _object_value(current_audits, "history")
    expected_history = {"passed": True} | verify_e1_v1_history()
    if history != expected_history:
        raise ValueError("current history audit changed")

    embedded_envelopes = _object_value(provenance, "embedded_candidate_artifacts")
    embedded = {
        candidate_id: _decode_embedded_candidate_artifact(
            _object_value(embedded_envelopes, candidate_id),
            expected_sha256=_PRESERVED_CANDIDATE_SHA256[candidate_id],
        )
        for candidate_id in ("A", "B")
    }
    _validate_comparison_input_evidence(
        _object_value(evidence, "comparison_inputs"),
        embedded,
        protocol,
        trust_results,
    )
    candidate_evidence = _object_value(evidence, "candidate_evidence")
    outer_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    for candidate_id in ("A", "B"):
        _validate_candidate_audit_evidence(
            candidate_id,
            _object_value(candidate_evidence, candidate_id),
            embedded[candidate_id],
            outer_by_id[candidate_id],
        )
    _verify_candidate_replay_evidence(evidence, embedded, protocol)


def _validate_fresh_comparison_audit_evidence(
    evidence: Mapping[str, Any],
    *,
    candidates: Sequence[CandidateEvaluationRecord],
    current_entries: Sequence[tuple[str, str]],
    protocol: E1V2Protocol,
) -> None:
    provenance = _object_value(evidence, "provenance")
    if (
        provenance.get("candidate_comparison_executed") is not True
        or provenance.get("current_execution_projection_sha256")
        != projection_digest(current_entries)
    ):
        raise ValueError("fresh comparison provenance changed")
    artifact_hashes = _object_value(provenance, "candidate_artifact_sha256")
    envelopes = _object_value(provenance, "embedded_candidate_artifacts")
    embedded: dict[str, dict[str, Any]] = {}
    for candidate_id in ("A", "B"):
        expected_hash = artifact_hashes.get(candidate_id)
        if not isinstance(expected_hash, str):
            raise ValueError("fresh candidate artifact hash is invalid")
        embedded[candidate_id] = _decode_embedded_candidate_artifact(
            _object_value(envelopes, candidate_id),
            expected_sha256=expected_hash,
        )
    current_audits = _object_value(evidence, "current_audits")
    if _object_value(current_audits, "dependency_guard") != verify_dependency_guard(
        current_entries
    ):
        raise ValueError("fresh comparison dependency audit changed")
    _verify_current_baseline_audit(_object_value(current_audits, "baseline"))
    trust = _object_value(current_audits, "trust")
    development = E1V2Generator(protocol).plan_cases(EvaluationScope.DEVELOPMENT)
    with tempfile.TemporaryDirectory(prefix="mvs-e1-v2-selection-load-trust-") as temporary:
        expected_trust = run_development_trust_audit(
            development,
            Path(temporary) / "trust",
        )
    if trust != expected_trust:
        raise ValueError("current trust audit changed")
    trust_results = _list_value(trust, "results")
    history = _object_value(current_audits, "history")
    expected_history = {"passed": True} | verify_e1_v1_history()
    if history != expected_history:
        raise ValueError("current history audit changed")
    if (
        trust.get("all_passed") is not True
        or trust.get("publication_count") != 0
        or history.get("passed") is not True
    ):
        raise ValueError("fresh comparison prerequisite audit did not pass")
    _validate_comparison_input_evidence(
        _object_value(evidence, "comparison_inputs"),
        embedded,
        protocol,
        trust_results,
    )
    outer_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    summaries = _object_value(evidence, "candidate_evidence")
    for candidate_id in ("A", "B"):
        summary = _object_value(summaries, candidate_id)
        artifact = embedded[candidate_id]
        artifact_candidate = _object_value(artifact, "candidate")
        if (
            summary.get("candidate_artifact_sha256") != artifact_hashes[candidate_id]
            or _object_value(summary, "candidate_record") != artifact_candidate
        ):
            raise ValueError("fresh candidate summary binding changed")
        outer_record = outer_by_id[candidate_id].as_record()
        for key, value in artifact_candidate.items():
            if key != "rejection_reasons" and outer_record.get(key) != value:
                raise ValueError("fresh outer candidate metrics changed")
        development_rows = _list_value(artifact, "development")
        diagnostic_rows = _list_value(artifact, "diagnostics")
        development_traces = [
            _object_value(_object_value(row, "inference_trace"), "geometry_trace")
            for row in development_rows
            if "inference_trace" in row
        ]
        diagnostic_traces = [
            _object_value(_object_value(row, "inference_trace"), "geometry_trace")
            for row in diagnostic_rows
        ]
        if _object_value(summary, "operation_counts") != _operation_count_evidence(
            development_traces,
            diagnostic_traces,
        ):
            raise ValueError("fresh candidate operation counts changed")
        benchmark = _object_value(summary, "benchmark")
        observations = _list_value(benchmark, "observations")
        samples = [_integer_value(item["elapsed_normalization_ns"]) for item in observations]
        if _nearest_rank_p95(samples) != outer_by_id[candidate_id].runtime_p95_ns:
            raise ValueError("fresh candidate benchmark changed")
        determinism = _object_value(summary, "determinism")
        if (
            determinism.get("passed") is not False
            or determinism.get("reason") != "TWO_COMPLETE_RUNS_REQUIRED"
            or outer_by_id[candidate_id].determinism_verified is not False
        ):
            raise ValueError("fresh candidate determinism evidence changed")
    _verify_candidate_replay_evidence(evidence, embedded, protocol)


def _validate_comparison_input_evidence(
    comparison_inputs: Mapping[str, Any],
    embedded: Mapping[str, Mapping[str, Any]],
    protocol: E1V2Protocol,
    trust_results: Sequence[Mapping[str, Any]],
) -> None:
    development_inputs = _list_value(comparison_inputs, "development")
    diagnostic_inputs = _list_value(comparison_inputs, "diagnostic")
    development = E1V2Generator(protocol).plan_cases(EvaluationScope.DEVELOPMENT)
    artifact_development = {
        candidate_id: _list_value(document, "development")
        for candidate_id, document in embedded.items()
    }
    trust_by_case = {str(result["case_id"]): result for result in trust_results}
    if len(development_inputs) != len(development):
        raise ValueError("development input evidence count changed")
    membership_fields = (
        "scope",
        "case_id",
        "recipe_id",
        "seed_family",
        "seed",
        "expected_outcome",
        "defect_id",
        "group",
    )
    for index, (plan, recorded) in enumerate(
        zip(development, development_inputs, strict=True)
    ):
        membership = plan.membership_record()
        if any(recorded.get(field) != membership[field] for field in membership_fields):
            raise ValueError("development membership evidence changed")
        artifact_rows = [artifact_development[key][index] for key in ("A", "B")]
        if any(row.get("case_id") != plan.case_id for row in artifact_rows):
            raise ValueError("embedded development order changed")
        if plan.group is CaseGroup.TRUST_BOUNDARY:
            specification = plan._render_plan.trust_boundary
            if (
                specification is None
                or recorded.get("input_kind") != "trust_scenario"
                or recorded.get("scenario_id") != specification.scenario_id
                or recorded.get("expected_error_code") != specification.expected_error_code
                or plan.case_id not in trust_by_case
                or any(row.get("trust_boundary") is not True for row in artifact_rows)
            ):
                raise ValueError("development trust-input evidence changed")
        else:
            if recorded.get("input_kind") != "inference":
                raise ValueError("development inference-input kind changed")
            for artifact_row in artifact_rows:
                source_hashes = _object_value(
                    _object_value(artifact_row, "inference_trace"),
                    "source_hashes",
                )
                if source_hashes != {
                    "reference_sha256": recorded["reference_sha256"],
                    "inspection_sha256": recorded["inspection_sha256"],
                }:
                    raise ValueError("development input source binding changed")

    diagnostic_plans = build_scale_diagnostic_matrix(protocol)
    artifact_diagnostics = {
        candidate_id: _list_value(document, "diagnostics")
        for candidate_id, document in embedded.items()
    }
    if len(diagnostic_inputs) != len(diagnostic_plans):
        raise ValueError("diagnostic input evidence count changed")
    for index, (diagnostic_plan, recorded) in enumerate(
        zip(diagnostic_plans, diagnostic_inputs, strict=True)
    ):
        if (
            recorded.get("diagnostic_id") != diagnostic_plan.diagnostic_id
            or recorded.get("seed") != diagnostic_plan.seed
            or recorded.get("combination") != diagnostic_plan.combination
            or recorded.get("cad_revision") != diagnostic_plan.cad_revision.value
            or recorded.get("view_id") != diagnostic_plan.view_id.value
        ):
            raise ValueError("diagnostic input identity changed")
        truth = _object_value(recorded, "diagnostic_truth")
        expected_truth = diagnostic_plan.diagnostic_truth_record()
        if any(truth.get(key) != value for key, value in expected_truth.items()):
            raise ValueError("diagnostic truth declaration changed")
        for candidate_id in ("A", "B"):
            artifact_row = artifact_diagnostics[candidate_id][index]
            trace = _object_value(artifact_row, "inference_trace")
            if (
                artifact_row.get("diagnostic_id") != diagnostic_plan.diagnostic_id
                or _object_value(artifact_row, "diagnostic_truth") != truth
                or _object_value(trace, "source_hashes")
                != {
                    "reference_sha256": recorded["reference_sha256"],
                    "inspection_sha256": recorded["inspection_sha256"],
                }
            ):
                raise ValueError("embedded diagnostic input binding changed")


def _validate_candidate_audit_evidence(
    candidate_id: str,
    evidence: Mapping[str, Any],
    embedded: Mapping[str, Any],
    outer: CandidateEvaluationRecord,
) -> None:
    original = _object_value(embedded, "candidate")
    if (
        evidence.get("candidate_artifact_sha256") != _PRESERVED_CANDIDATE_SHA256[candidate_id]
        or _object_value(evidence, "preserved_candidate_record") != original
        or original.get("candidate_id") != candidate_id
        or outer.candidate_id != candidate_id
    ):
        raise ValueError("candidate artifact summary binding changed")
    metric_fields = (
        "work_cap_passed",
        "development_gates_passed",
        "medium_high_defect_recall",
        "maximum_diagnostic_truth_recall_drop",
        "diagnostic_median_dice_drop",
        "development_nuisance_false_positives",
        "medium_high_defect_false_negatives",
        "affected_feature_mapping_errors",
        "positive_case_median_dice",
        "median_post_normalization_objective",
        "worst_case_candidate_pixels",
        "runtime_p95_ns",
    )
    if any(getattr(outer, field) != original[field] for field in metric_fields) or any(
        (
            outer.determinism_verified,
            outer.dependency_guard_passed,
            outer.trust_verified,
            outer.v0_1_regression_verified,
        )
    ):
        raise ValueError("outer candidate does not preserve metrics and fail-closed proofs")

    development_rows = _list_value(embedded, "development")
    diagnostic_rows = _list_value(embedded, "diagnostics")
    development_traces = [
        _object_value(_object_value(row, "inference_trace"), "geometry_trace")
        for row in development_rows
        if "inference_trace" in row
    ]
    diagnostic_traces = [
        _object_value(_object_value(row, "inference_trace"), "geometry_trace")
        for row in diagnostic_rows
    ]
    if _object_value(evidence, "operation_counts") != _operation_count_evidence(
        development_traces,
        diagnostic_traces,
    ):
        raise ValueError("candidate operation-count evidence changed")

    benchmark = _object_value(evidence, "benchmark")
    benchmark_source = dict(benchmark)
    observations = _list_value(benchmark_source, "observations")
    del benchmark_source["observations"]
    if benchmark_source != _object_value(embedded, "benchmark"):
        raise ValueError("candidate benchmark metadata changed")
    expected_observations = [
        {
            "diagnostic_id": row["diagnostic_id"],
            "elapsed_normalization_ns": _object_value(row, "inference_trace")[
                "elapsed_normalization_ns"
            ],
        }
        for row in diagnostic_rows
    ]
    samples = [_integer_value(item["elapsed_normalization_ns"]) for item in observations]
    if (
        observations != expected_observations
        or _nearest_rank_p95(samples) != outer.runtime_p95_ns
        or benchmark.get("p95_ns") != outer.runtime_p95_ns
    ):
        raise ValueError("candidate benchmark observations changed")

    development_objectives = _list_value(evidence, "development_objectives")
    expected_development_objectives = [
        {
            "case_id": row["case_id"],
            "objective_after_rounded_8_decimals": _object_value(
                _object_value(row, "inference_trace"), "geometry_trace"
            )["objective_after"],
        }
        for row in development_rows
        if "inference_trace" in row
    ]
    if development_objectives != expected_development_objectives:
        raise ValueError("candidate development objectives changed")

    geometry = _list_value(evidence, "diagnostic_geometry")
    if len(geometry) != len(diagnostic_rows):
        raise ValueError("candidate diagnostic geometry count changed")
    serialized_objectives = [
        _float_value(item["objective_after_rounded_8_decimals"])
        for item in development_objectives
    ]
    defect_drops: list[tuple[float, float]] = []
    result_projection: list[dict[str, object]] = [
        {
            "case_id": row["case_id"],
            "result_sha256": canonical_json_hash(_object_value(row, "inference_trace")),
        }
        for row in development_rows
        if "inference_trace" in row
    ]
    for row, derived in zip(diagnostic_rows, geometry, strict=True):
        trace = _object_value(row, "inference_trace")
        geometry_trace = _object_value(trace, "geometry_trace")
        diagnostic_id = str(row["diagnostic_id"])
        if derived.get("diagnostic_id") != diagnostic_id:
            raise ValueError("candidate diagnostic geometry order changed")
        expected_serialized_transform = {
            "rotation_degrees": float(geometry_trace["correction_rotation_degrees"]),
            "scale": float(geometry_trace["correction_scale"]),
            "dx": float(geometry_trace["correction_dx"]),
            "dy": float(geometry_trace["correction_dy"]),
        }
        if _object_value(derived, "serialized_transform") != expected_serialized_transform:
            raise ValueError("candidate serialized diagnostic transform changed")
        exact_scale, scale_restoration = _restore_exact_frozen_bound(
            expected_serialized_transform["scale"],
            boundary_flag=bool(geometry_trace["at_scale_bound"]),
            bounds=GeometryConfig().correction_scale_bounds,
            identifiers=("correction_scale_bounds.lower", "correction_scale_bounds.upper"),
            representations=("1/1.02", "1/0.98"),
        )
        exact_rotation, rotation_restoration = _restore_exact_frozen_bound(
            expected_serialized_transform["rotation_degrees"],
            boundary_flag=bool(geometry_trace["at_rotation_bound"]),
            bounds=GeometryConfig().rotation_bounds_degrees,
            identifiers=("rotation_bounds_degrees.lower", "rotation_bounds_degrees.upper"),
            representations=("-1.5", "1.5"),
        )
        restorations = [
            item
            for item in (scale_restoration, rotation_restoration)
            if item is not None
        ]
        expected_method = (
            "recorded_transform_with_exact_frozen_bound_restoration"
            if restorations
            else "replay_from_recorded_8_decimal_transform_parameters"
        )
        if (
            derived.get("bound_restorations") != restorations
            or derived.get("derivation") != expected_method
            or _object_value(derived, "applied_replay_transform")
            != {
                "rotation_degrees": exact_rotation,
                "scale": exact_scale,
                "dx": expected_serialized_transform["dx"],
                "dy": expected_serialized_transform["dy"],
            }
            or derived.get("original_objective_before_rounded_8_decimals")
            != geometry_trace["objective_before"]
            or derived.get("original_objective_after_rounded_8_decimals")
            != geometry_trace["objective_after"]
        ):
            raise ValueError("candidate frozen-bound replay evidence changed")
        for suffix in ("before", "after"):
            objective = _float_value(derived[f"replayed_objective_{suffix}"])
            weighted = 0.70 * _float_value(
                derived[f"silhouette_xor_rate_{suffix}"]
            ) + 0.30 * _float_value(derived[f"normalized_edge_mae_{suffix}"])
            if abs(objective - weighted) > 1e-15 or round(objective, 8) != float(
                geometry_trace[f"objective_{suffix}"]
            ):
                raise ValueError("candidate diagnostic objective components changed")
        truth_fields = (
            "identity_truth_pixel_recall",
            "selected_truth_pixel_recall",
            "identity_dice",
            "selected_dice",
        )
        if any(derived.get(field) != trace[field] for field in truth_fields):
            raise ValueError("candidate diagnostic truth metrics changed")
        if _object_value(row, "diagnostic_truth").get("defect_type") is not None:
            defect_drops.append(
                (
                    float(trace["identity_truth_pixel_recall"])
                    - float(trace["selected_truth_pixel_recall"]),
                    float(trace["identity_dice"]) - float(trace["selected_dice"]),
                )
            )
        serialized_objectives.append(float(geometry_trace["objective_after"]))
        deterministic_trace = {
            key: value for key, value in trace.items() if key != "elapsed_normalization_ns"
        }
        result_projection.append(
            {
                "case_id": diagnostic_id,
                "result_sha256": canonical_json_hash(deterministic_trace),
            }
        )
    if (
        max((item[0] for item in defect_drops), default=0.0)
        != outer.maximum_diagnostic_truth_recall_drop
        or float(median(item[1] for item in defect_drops))
        != outer.diagnostic_median_dice_drop
        or abs(float(median(serialized_objectives)) - outer.median_post_normalization_objective)
        > 5e-9
    ):
        raise ValueError("candidate aggregate metrics changed")

    determinism = _object_value(evidence, "determinism")
    expected_determinism = verify_determinism_evidence(
        (result_projection,),
        expected_case_ids=tuple(str(item["case_id"]) for item in result_projection),
    )
    limited = _object_value(determinism, "limited_repeat_observation")
    if (
        any(determinism.get(key) != value for key, value in expected_determinism.items())
        or determinism.get("observed_complete_run_projection_sha256")
        != canonical_json_hash(result_projection)
        or limited.get("case_id") != result_projection[0]["case_id"]
        or limited.get("reported_equal") != original["deterministic"]
        or limited.get("persisted_repeat_projection") is not False
    ):
        raise ValueError("candidate determinism evidence changed")


def finalize_candidate_selection(
    records: Sequence[CandidateEvaluationRecord],
    protocol: E1V2Protocol,
    *,
    audit_evidence: dict[str, Any],
) -> CandidateSelectionRecord:
    semantic = select_candidate(records)
    entries = implementation_projection()
    partial = replace(
        semantic,
        implementation_projection=entries,
        implementation_projection_sha256=projection_digest(entries),
        configuration_sha256=protocol.configuration_sha256,
        audit_evidence=audit_evidence,
    )
    return replace(
        partial,
        record_sha256=canonical_json_hash(partial.as_record(include_self_hash=False)),
    )


def write_candidate_selection(
    path: Path | str,
    record: CandidateSelectionRecord,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(record.as_record()) + b"\n")


def load_candidate_selection(path: Path | str) -> CandidateSelectionRecord:
    """Load portable selection semantics without executing audit verification."""

    source = Path(path)
    try:
        with source.open("rb") as stream:
            payload = stream.read(_MAX_SELECTION_FILE_BYTES + 1)
    except OSError as exc:
        raise ValueError("candidate selection could not be loaded") from exc
    if len(payload) > _MAX_SELECTION_FILE_BYTES:
        raise ValueError("candidate selection exceeds the file-size cap")
    document = _canonical_json_object(payload, "candidate selection")
    from manufacturing_vision_studio.e1.protocol_v2 import PROJECT_ROOT, load_e1_v2_protocol

    schema = json.loads((PROJECT_ROOT / "schemas/e1-candidate-selection.v2.json").read_text())
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
    except Exception as exc:
        raise ValueError("candidate selection failed schema validation") from exc
    supplied_hash = document.get("record_sha256")
    projection = {key: value for key, value in document.items() if key != "record_sha256"}
    if supplied_hash != canonical_json_hash(projection):
        raise ValueError("candidate selection self-hash does not match")
    current_entries = implementation_projection()
    supplied_entries = tuple(
        (item["path"], item["sha256"])
        for item in document["implementation_projection"]
    )
    if supplied_entries != current_entries:
        raise ValueError("candidate selection implementation projection changed")
    current_projection_hash = projection_digest(current_entries)
    if document["implementation_projection_sha256"] != current_projection_hash:
        raise ValueError("candidate selection projection hash does not match")
    protocol = load_e1_v2_protocol()
    if document["configuration_sha256"] != protocol.configuration_sha256:
        raise ValueError("candidate selection configuration binding changed")
    if document["audit_evidence_status"] != "UNVERIFIED":
        raise ValueError("candidate selection audit evidence status changed")
    supplied_candidates = tuple(
        CandidateEvaluationRecord.from_record(item)
        for item in document["candidates"]
    )
    audit_evidence = document["audit_evidence"]
    if not isinstance(audit_evidence, dict):
        raise ValueError("candidate selection audit evidence is invalid")
    _validate_selection_audit_bindings(
        audit_evidence,
        candidates=supplied_candidates,
        current_entries=current_entries,
    )
    semantic = select_candidate(supplied_candidates)
    if (
        semantic.candidates != supplied_candidates
        or semantic.selected_candidate_id != document["selected_candidate_id"]
        or semantic.outcome != document["outcome"]
    ):
        raise ValueError("candidate selection semantic ranking does not match")
    return CandidateSelectionRecord(
        selected_candidate_id=semantic.selected_candidate_id,
        candidates=supplied_candidates,
        outcome=semantic.outcome,
        implementation_projection=current_entries,
        implementation_projection_sha256=current_projection_hash,
        configuration_sha256=protocol.configuration_sha256,
        audit_evidence=audit_evidence,
        schema_version=document["schema_version"],
        record_sha256=supplied_hash,
    )


def verify_candidate_selection_audit(path: Path | str) -> None:
    """Re-execute the complete audit, raising on failure and retaining no status."""

    record = load_candidate_selection(path)
    protocol = load_e1_v2_protocol()
    current_entries = implementation_projection()
    mutable_evidence = _thaw_json_value(record.audit_evidence)
    if not isinstance(mutable_evidence, dict):
        raise TypeError("stored audit evidence is not a JSON object")
    _verify_selection_audit_evidence(
        mutable_evidence,
        candidates=record.candidates,
        current_entries=current_entries,
        protocol=protocol,
    )


def compare_candidates(
    output_root: Path | str,
    *,
    protocol: E1V2Protocol | None = None,
) -> CandidateSelectionRecord:
    """Run only explicit development plus the separate diagnostic matrix."""

    resolved_protocol = protocol or load_e1_v2_protocol()
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    generator = E1V2Generator(resolved_protocol)
    development = generator.plan_cases(EvaluationScope.DEVELOPMENT)
    diagnostics = build_scale_diagnostic_matrix(resolved_protocol)
    with tempfile.TemporaryDirectory(prefix="mvs-e1-v2-comparison-audit-") as temporary:
        trust_audit = run_development_trust_audit(development, Path(temporary) / "trust")
    baseline_audit = run_v0_1_baseline_audit()
    history_audit = {"passed": True} | verify_e1_v1_history()
    current_entries = implementation_projection()
    dependency_audit = verify_dependency_guard(current_entries)
    trust_result_values = trust_audit.get("results")
    if not isinstance(trust_result_values, list) or not all(
        isinstance(item, dict) for item in trust_result_values
    ):
        raise ValueError("development trust audit results are invalid")
    trust_results = {str(item["case_id"]): item for item in trust_result_values}
    records = [
        _evaluate_candidate(
            candidate_id,
            protocol=resolved_protocol,
            generator=generator,
            development=development,
            diagnostic_plans=diagnostics,
            output_root=destination,
            trust_results=trust_results,
            dependency_guard_passed=bool(dependency_audit["passed"]),
            trust_verified=bool(trust_audit["all_passed"]),
            baseline_verified=bool(baseline_audit["v0_1_regression"]),
        )
        for candidate_id in ("A", "B")
    ]
    audit_evidence = _build_fresh_comparison_audit(
        destination,
        resolved_protocol,
        development,
        diagnostics,
        current_entries=current_entries,
        trust_audit=trust_audit,
        baseline_audit=baseline_audit,
        history_audit=history_audit,
        dependency_audit=dependency_audit,
    )
    finalized = finalize_candidate_selection(
        records,
        resolved_protocol,
        audit_evidence=audit_evidence,
    )
    write_candidate_selection(destination / "e1-v2-candidate-selection.json", finalized)
    return finalized


def _evaluate_candidate(
    candidate_id: str,
    *,
    protocol: E1V2Protocol,
    generator: E1V2Generator,
    development: Sequence[E1V2CasePlan],
    diagnostic_plans: Sequence[ScaleDiagnosticPlan],
    output_root: Path,
    trust_results: Mapping[str, Mapping[str, Any]],
    dependency_guard_passed: bool,
    trust_verified: bool,
    baseline_verified: bool,
) -> CandidateEvaluationRecord:
    policy = E1V2InferencePolicy(protocol, candidate_id=candidate_id)
    observations: list[E1V2EvaluationObservation] = []
    development_records: list[dict[str, object]] = []
    objectives: list[float] = []
    worst_pixels = 0
    for plan in development:
        if plan.group is CaseGroup.TRUST_BOUNDARY:
            render_plan = plan._render_plan
            trust_result = trust_results.get(plan.case_id)
            if trust_result is None:
                raise ValueError("development trust result is missing")
            observations.append(
                E1V2EvaluationObservation(
                    case_id=plan.case_id,
                    scope=EvaluationScope.DEVELOPMENT.value,
                    group=CaseGroup.TRUST_BOUNDARY.value,
                    expected_outcome="ABSTAIN",
                    actual_outcome=cast(
                        Literal["NORMAL", "ANOMALY", "ABSTAIN"],
                        str(trust_result["actual_outcome"]),
                    ),
                    anomaly_score=None,
                    cad_revision=render_plan.cad_revision.value,
                    view_id=render_plan.view_id.value,
                    total_pixels=512 * 384,
                    abstention_reason=(
                        None
                        if trust_result["actual_error_code"] is None
                        else str(trust_result["actual_error_code"])
                    ),
                )
            )
            development_records.append(
                {
                    "case_id": plan.case_id,
                    "actual_outcome": trust_result["actual_outcome"],
                    "actual_error_code": trust_result["actual_error_code"],
                    "publication_count": trust_result["publication_count"],
                    "passed": trust_result["passed"],
                    "trust_boundary": True,
                }
            )
            continue
        generated = generator.generate_case(plan)
        inference = E1V2InferenceInput.from_generated(generated)
        result = policy.inspect(inference)
        observations.append(observation_from_case(generated, result))
        development_records.append(
            {"case_id": generated.plan.case_id, "inference_trace": result.as_record()}
        )
        objectives.append(result.geometry_trace.alignment.objective_after)
        worst_pixels = max(
            worst_pixels,
            result.geometry_trace.alignment.candidate_pixels_evaluated,
        )

    metric_summary = evaluate_v2_metrics(observations)
    positive_median_dice = (
        float(median(metric_summary.positive_case_dice))
        if metric_summary.positive_case_dice
        else 0.0
    )
    feature_errors = (
        metric_summary.feature_mapping_denominator - metric_summary.feature_mapping_correct
    )
    medium_high_recall = (
        1.0
        - metric_summary.medium_high_defect_false_negatives
        / metric_summary.medium_high_defect_denominator
        if metric_summary.medium_high_defect_denominator
        else 0.0
    )
    nuisance_rate = (
        metric_summary.nuisance_false_positives / metric_summary.nuisance_denominator
        if metric_summary.nuisance_denominator
        else 1.0
    )
    feature_rate = (
        metric_summary.feature_mapping_correct / metric_summary.feature_mapping_denominator
        if metric_summary.feature_mapping_denominator
        else 0.0
    )

    diagnostic_records: list[dict[str, object]] = []
    recall_drops: list[float] = []
    dice_drops: list[float] = []
    runtime_samples: list[int] = []
    if diagnostic_plans:
        warm_inference, _, _ = _render_diagnostic(diagnostic_plans[0], protocol)
        for _ in range(5):
            policy._align(warm_inference)
    for diagnostic_plan in diagnostic_plans:
        inference, truth, truth_bytes = _render_diagnostic(diagnostic_plan, protocol)
        started = time.perf_counter_ns()
        policy._align(inference)
        elapsed = time.perf_counter_ns() - started
        runtime_samples.append(elapsed)
        result = policy.inspect(inference)
        objectives.append(result.geometry_trace.alignment.objective_after)
        worst_pixels = max(
            worst_pixels,
            result.geometry_trace.alignment.candidate_pixels_evaluated,
        )
        predicted = (
            np.zeros_like(truth)
            if result.predicted_mask_bytes is None
            else _decode_mask(result.predicted_mask_bytes)
        )
        identity = _identity_difference(inference)
        identity_recall = _recall(identity, truth)
        selected_recall = _recall(predicted, truth)
        identity_dice = _dice(identity, truth)
        selected_dice = _dice(predicted, truth)
        if diagnostic_plan.defect_type is not None:
            recall_drops.append(identity_recall - selected_recall)
            dice_drops.append(identity_dice - selected_dice)
        diagnostic_records.append(
            {
                "diagnostic_id": diagnostic_plan.diagnostic_id,
                "seed": diagnostic_plan.seed,
                "combination": diagnostic_plan.combination,
                "diagnostic_truth": diagnostic_plan.diagnostic_truth_record()
                | {"authoritative_mask_sha256": sha256_bytes(truth_bytes)},
                "inference_trace": result.as_record()
                | {
                    "elapsed_normalization_ns": elapsed,
                    "residual_pixels": int(np.count_nonzero(predicted)),
                    "residual_component_count": len(_connected_components(predicted)),
                    "identity_truth_pixel_recall": identity_recall,
                    "selected_truth_pixel_recall": selected_recall,
                    "identity_dice": identity_dice,
                    "selected_dice": selected_dice,
                },
            }
        )

    runtime_p95 = _nearest_rank_p95(runtime_samples)
    development_gates = (
        medium_high_recall >= 0.90
        and nuisance_rate <= 0.05
        and positive_median_dice >= 0.70
        and feature_rate >= 0.95
    )
    candidate_cap = 44_236_800 if candidate_id == "A" else 35_278_848
    candidate = CandidateEvaluationRecord(
        candidate_id=candidate_id,
        determinism_verified=False,
        dependency_guard_passed=dependency_guard_passed,
        work_cap_passed=worst_pixels <= candidate_cap,
        development_gates_passed=development_gates,
        medium_high_defect_recall=medium_high_recall,
        trust_verified=trust_verified,
        v0_1_regression_verified=baseline_verified,
        maximum_diagnostic_truth_recall_drop=max(recall_drops, default=0.0),
        diagnostic_median_dice_drop=float(median(dice_drops)) if dice_drops else 0.0,
        development_nuisance_false_positives=metric_summary.nuisance_false_positives,
        medium_high_defect_false_negatives=(metric_summary.medium_high_defect_false_negatives),
        affected_feature_mapping_errors=feature_errors,
        positive_case_median_dice=positive_median_dice,
        median_post_normalization_objective=(float(median(objectives)) if objectives else 0.0),
        worst_case_candidate_pixels=worst_pixels,
        runtime_p95_ns=runtime_p95,
    )
    output_record = {
        "candidate": candidate.as_record(),
        "inputs": {
            "development_scope": "development",
            "development_case_count": len(development),
            "diagnostic_case_count": len(diagnostic_plans),
            "configuration_sha256": protocol.configuration_sha256,
        },
        "benchmark": {
            "clock": "perf_counter_ns",
            "warmups": 5,
            "samples": len(runtime_samples),
            "p95_method": "nearest_rank",
            "p95_ns": runtime_p95,
            "image_size": [512, 384],
            "cpu": platform.processor() or platform.machine(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pillow": pillow_version,
            "runner": sys.platform,
        },
        "development": development_records,
        "diagnostics": diagnostic_records,
    }
    (output_root / f"candidate-{candidate_id.lower()}.json").write_bytes(
        canonical_json_bytes(output_record) + b"\n"
    )
    return candidate


def _render_diagnostic(
    plan: ScaleDiagnosticPlan,
    protocol: E1V2Protocol,
) -> tuple[E1V2InferenceInput, np.ndarray, bytes]:
    v1_generator = E1Generator()
    templates = v1_generator.plan_cases(DatasetProfile.FULL)
    base = next(
        item
        for item in templates
        if item.cad_revision is plan.cad_revision and item.view_id is plan.view_id
    )
    render_plan = replace(base, case_id=plan.diagnostic_id, seed=plan.seed)
    geometry = geometry_for_case(
        plan.cad_revision,
        plan.view_id,
        image_size=(512, 384),
        feature_regions=protocol.feature_ownership(plan.cad_revision, plan.view_id).feature_boxes,
    )
    reference = _render_pristine(render_plan, geometry)
    inspection = reference.copy()
    truth_image = Image.new("L", (512, 384), 0)
    if plan.defect_type is not None:
        source_defect = next(
            item.defect
            for item in templates
            if item.defect is not None
            and item.defect.defect_type.value == plan.defect_type
            and item.defect.severity.value == plan.defect_severity
        )
        assert source_defect is not None and plan.expected_feature_id is not None
        defect = replace(
            source_defect,
            defect_id=f"{plan.diagnostic_id}-truth-001",
            target_feature_id=plan.expected_feature_id,
        )
        inspection, truth_image = render_defect_truth(
            reference,
            defect,
            seed=plan.seed,
            geometry=geometry,
        )
    inspection = _scale_image(
        inspection,
        factor=1.0 + plan.scale_delta,
        fill=geometry.background,
    )
    if plan.rotation_degrees:
        inspection = inspection.rotate(
            plan.rotation_degrees,
            resample=Image.Resampling.NEAREST,
            expand=False,
            fillcolor=geometry.background,
        )
    if plan.translation_x or plan.translation_y:
        inspection = _translate_image(
            inspection,
            dx=plan.translation_x,
            dy=plan.translation_y,
            fill=geometry.background,
        )
    if plan.exposure_gain_delta:
        pixels = np.asarray(inspection, dtype=np.float64)
        inspection = Image.fromarray(
            np.clip(np.rint(pixels * (1.0 + plan.exposure_gain_delta)), 0, 255).astype(np.uint8),
            mode="RGB",
        )
    reference_bytes = encode_png(reference, mode="RGB")
    inspection_bytes = encode_png(inspection, mode="RGB")
    truth_bytes = encode_png(truth_image, mode="L")
    return (
        E1V2InferenceInput(
            reference_bytes=reference_bytes,
            inspection_bytes=inspection_bytes,
            reference_sha256=sha256_bytes(reference_bytes),
            inspection_sha256=sha256_bytes(inspection_bytes),
            part_id=render_plan.part_id,
            cad_revision=plan.cad_revision,
            view_id=plan.view_id,
        ),
        np.asarray(truth_image, dtype=np.uint8) > 0,
        truth_bytes,
    )


def _decode_mask(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8) > 0


def _decode_rgb(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8)


def _identity_difference(inference: E1V2InferenceInput) -> np.ndarray:
    reference = _decode_rgb(inference.reference_bytes)
    inspection = _decode_rgb(inference.inspection_bytes)
    return np.max(np.abs(reference.astype(np.int16) - inspection.astype(np.int16)), axis=2) >= 32


def _recall(predicted: np.ndarray, truth: np.ndarray) -> float:
    denominator = int(np.count_nonzero(truth))
    return 1.0 if denominator == 0 else float(np.count_nonzero(predicted & truth) / denominator)


def _dice(predicted: np.ndarray, truth: np.ndarray) -> float:
    denominator = int(np.count_nonzero(predicted) + np.count_nonzero(truth))
    return 1.0 if denominator == 0 else float(2 * np.count_nonzero(predicted & truth) / denominator)


def _nearest_rank_p95(samples: Sequence[int]) -> int:
    if not samples:
        return 0
    ordered = sorted(samples)
    rank = max(1, int(np.ceil(0.95 * len(ordered))))
    return ordered[rank - 1]


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="E1 v2 development candidate diagnostics")
    parser.add_argument("--output-root", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("compare-candidates")
    args = parser.parse_args()
    if args.command == "compare-candidates":
        record = compare_candidates(args.output_root)
        print(json.dumps(record.as_record(), sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
