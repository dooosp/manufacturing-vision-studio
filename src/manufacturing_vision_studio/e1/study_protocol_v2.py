"""Strict immutable protocol and checked diagnostic matrix for the E1 study."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from jsonschema import Draft202012Validator

from manufacturing_vision_studio.canonical import canonical_json_hash, sha256_bytes
from manufacturing_vision_studio.e1.domain import CadRevision, ViewId

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STUDY_PROTOCOL_PATH = (
    PROJECT_ROOT / "configs" / "evaluation" / "e1-feasibility-study.v1.json"
)
DEFAULT_DIAGNOSTIC_MATRIX_PATH = (
    PROJECT_ROOT / "configs" / "evaluation" / "e1-feasibility-diagnostic-108.json"
)
STUDY_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "e1-feasibility-study-config.v1.json"
_MAX_JSON_BYTES = 4 * 1024 * 1024
_EXPECTED_BASE_COMMIT = "9fd6d0c600206083fde4fafc874e0226b5df60b3"
_EXPECTED_ARTIFACT_ROOT_IDENTITY = "docs/evaluation/results/e1-feasibility-study"
_EXPECTED_RAW_DATA_ROOT_IDENTITY = "data/e1-feasibility-study"
_EXPECTED_PHASE_1_MODES = ("NEAREST", "BILINEAR", "BICUBIC")
_EXPECTED_PHASE_2_COUNTS = {
    "clean": 24,
    "nuisance": 30,
    "defect": 60,
    "trust_boundary": 6,
    "total": 120,
}
_EXPECTED_SOURCE_HASHES = {
    "candidate_a_raw_sha256": "ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84",
    "candidate_b_raw_sha256": "983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029",
    "selection_raw_sha256": "92d3a2f86645a4d0fc33cfc39b769c6d2c4234383c7f132e803c449c7a66f2f3",
    "selection_record_sha256": "3d4aa7e95240ed2bd4c018fb0762fdf788f919069cfbb935fd228de4b67dc2fe",
    "task4_report_raw_sha256": "b6a2093082aa63631adb233c282466539720281ab96b53bc3928cf292efc8835",
    "task4_progress_ledger_raw_sha256": (
        "fcef0c3b22b962f185911cc74bdad45f1bd2860c42ae8e59bac76d6741c13ea7"
    ),
}
_EXPECTED_OWNERSHIP_MAP_HASHES = {
    "rev-A/front": "eadc490b04f8240e8356b3e20e75db08d79dfc5e27af180574d707836b3b776f",
    "rev-A/oblique_left": "2d2a52ecae44ccae98455180211aaf528078707948dbf83f792223c550d3a074",
    "rev-A/oblique_right": "8c42a88c3ffdf3dda10b073665b6d7a565ddde54a7a7450ba3c0f4782be14477",
    "rev-B/front": "5f69348a9ce7b646054dce02f95a0ff8ebd420c641ab40f414b0afa645ef49bc",
    "rev-B/oblique_left": "1fb2f752d738a7bf595f8cae97860452a3a8628ea5cb3eec4347d1f42fe43b8b",
    "rev-B/oblique_right": "373337ec46da320dbbcdf0ffa14c22794db05208cd9491e5b272e0d34169830d",
}
_EXPECTED_IMPLEMENTATION_PROJECTION_PATHS = (
    "Makefile",
    "configs/evaluation/e1-feasibility-diagnostic-108.json",
    "configs/evaluation/e1-feasibility-study.v1.json",
    "configs/evaluation/e1-v1-history-integrity.json",
    "configs/evaluation/e1-v1.json",
    "configs/evaluation/e1-v2-candidate-selection.json",
    "configs/evaluation/e1-v2.json",
    "pyproject.toml",
    "schemas/e1-candidate-selection.v2.json",
    "schemas/e1-case-manifest.v1.json",
    "schemas/e1-evaluation-protocol.v1.json",
    "schemas/e1-evaluation-protocol.v2.json",
    "schemas/e1-evaluation-result.v1.json",
    "schemas/e1-feasibility-study-artifact.v1.json",
    "schemas/e1-feasibility-study-config.v1.json",
    "schemas/e1-threshold-lock.v1.json",
    "src/manufacturing_vision_studio/__init__.py",
    "src/manufacturing_vision_studio/adapters.py",
    "src/manufacturing_vision_studio/canonical.py",
    "src/manufacturing_vision_studio/canonical_png.py",
    "src/manufacturing_vision_studio/config.py",
    "src/manufacturing_vision_studio/e1/__init__.py",
    "src/manufacturing_vision_studio/e1/domain.py",
    "src/manufacturing_vision_studio/e1/domain_v2.py",
    "src/manufacturing_vision_studio/e1/feature_mapping.py",
    "src/manufacturing_vision_studio/e1/generator.py",
    "src/manufacturing_vision_studio/e1/generator_v2.py",
    "src/manufacturing_vision_studio/e1/known_transform_v2.py",
    "src/manufacturing_vision_studio/e1/metrics.py",
    "src/manufacturing_vision_studio/e1/metrics_v2.py",
    "src/manufacturing_vision_studio/e1/model.py",
    "src/manufacturing_vision_studio/e1/oracle.py",
    "src/manufacturing_vision_studio/e1/policy_v2.py",
    "src/manufacturing_vision_studio/e1/protocol.py",
    "src/manufacturing_vision_studio/e1/protocol_v2.py",
    "src/manufacturing_vision_studio/e1/study_artifacts_v2.py",
    "src/manufacturing_vision_studio/e1/study_cli_v2.py",
    "src/manufacturing_vision_studio/e1/study_inference_v2.py",
    "src/manufacturing_vision_studio/e1/study_protocol_v2.py",
    "src/manufacturing_vision_studio/e1/study_retention_v2.py",
    "src/manufacturing_vision_studio/e1/study_runner_v2.py",
    "src/manufacturing_vision_studio/e1/study_truth_v2.py",
    "src/manufacturing_vision_studio/errors.py",
    "src/manufacturing_vision_studio/evidence.py",
    "src/manufacturing_vision_studio/images.py",
    "src/manufacturing_vision_studio/model.py",
    "src/manufacturing_vision_studio/registry.py",
)
_EXPECTED_DIRECT_IMPORT_ALLOWLIST = {
    "known_transform_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.canonical_png",
    ),
    "study_artifacts_v2": ("manufacturing_vision_studio.canonical",),
    "study_cli_v2": (),
    "study_inference_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.e1.domain",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.model",
        "manufacturing_vision_studio.e1.protocol_v2",
        "manufacturing_vision_studio.errors",
        "manufacturing_vision_studio.images",
        "manufacturing_vision_studio.model",
    ),
    "study_protocol_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.e1.domain",
    ),
    "study_retention_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.e1.protocol_v2",
    ),
    "study_runner_v2": (
        "manufacturing_vision_studio.canonical_png",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.metrics_v2",
        "manufacturing_vision_studio.e1.protocol_v2",
    ),
    "study_truth_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.canonical_png",
        "manufacturing_vision_studio.e1.domain",
        "manufacturing_vision_studio.e1.domain_v2",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.generator",
        "manufacturing_vision_studio.e1.generator_v2",
        "manufacturing_vision_studio.e1.metrics_v2",
        "manufacturing_vision_studio.e1.oracle",
        "manufacturing_vision_studio.e1.protocol_v2",
    ),
}


class StudyProtocolError(ValueError):
    """A bounded study protocol, frozen matrix, or bound snapshot is invalid."""


@dataclass(frozen=True, slots=True)
class DiagnosticGates:
    max_recall_drop: float
    median_dice_drop: float
    medium_high_recall: float


@dataclass(frozen=True, slots=True)
class DevelopmentGates:
    medium_high_recall: float
    nuisance_fpr: float
    median_dice: float
    feature_accuracy: float


@dataclass(frozen=True, slots=True)
class FrozenDiagnosticPlan:
    diagnostic_id: str
    seed: int
    combination: str
    cad_revision: CadRevision
    view_id: ViewId
    scale_delta: float
    translation_x: int
    translation_y: int
    rotation_degrees: float
    exposure_gain_delta: float
    defect_type: str | None
    defect_severity: str | None
    expected_feature_id: str | None

    def as_record(self) -> dict[str, object]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "seed": self.seed,
            "combination": self.combination,
            "cad_revision": self.cad_revision.value,
            "view_id": self.view_id.value,
            "scale_delta": self.scale_delta,
            "translation_x": self.translation_x,
            "translation_y": self.translation_y,
            "rotation_degrees": self.rotation_degrees,
            "exposure_gain_delta": self.exposure_gain_delta,
            "defect_type": self.defect_type,
            "defect_severity": self.defect_severity,
            "expected_feature_id": self.expected_feature_id,
        }


@dataclass(frozen=True, slots=True)
class StudyProtocolV2:
    source_path: Path
    schema_path: Path
    _document: dict[str, Any] = field(repr=False)
    configuration_sha256: str
    diagnostic_matrix_sha256: str
    artifact_root_identity: str
    raw_data_root_identity: str
    artifact_root: Path
    raw_data_root: Path
    phase_1_modes: tuple[str, ...]
    phase_1_limits: Mapping[str, int | float]
    phase_2_counts: Mapping[str, int]
    diagnostic_gates: DiagnosticGates
    development_gates: DevelopmentGates
    source_hashes: Mapping[str, str]
    ownership_map_hashes: Mapping[str, str]
    _implementation_projection_paths: tuple[str, ...] = field(repr=False)
    _direct_import_allowlist: Mapping[str, tuple[str, ...]] = field(repr=False)

    @classmethod
    def from_path(cls, path: Path) -> StudyProtocolV2:
        document = _load_json_object(path)
        schema_path = _local_schema_path(path, document)
        schema = _load_json_object(schema_path)
        try:
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(document)
        except Exception as exc:
            raise StudyProtocolError(f"study protocol failed schema validation: {exc}") from exc
        matrix_sha256 = _validate_protocol_document(document)
        paths = _object(document, "paths")
        phase_1 = _object(document, "phase_1")
        phase_2 = _object(document, "phase_2")
        diagnostic = _object(document, "diagnostic_gates")
        development = _object(document, "development_gates")
        allowlist = _object(document, "direct_import_allowlist")
        artifact_root_identity = _string(paths, "artifact_root")
        raw_data_root_identity = _string(paths, "raw_data_root")
        return cls(
            source_path=path,
            schema_path=schema_path,
            _document=document,
            configuration_sha256=canonical_json_hash(document),
            diagnostic_matrix_sha256=matrix_sha256,
            artifact_root_identity=artifact_root_identity,
            raw_data_root_identity=raw_data_root_identity,
            artifact_root=_project_path(artifact_root_identity),
            raw_data_root=_project_path(raw_data_root_identity),
            phase_1_modes=tuple(_string_list(phase_1, "modes")),
            phase_1_limits=MappingProxyType(_numeric_mapping(_object(phase_1, "limits"))),
            phase_2_counts=MappingProxyType(_integer_mapping(_object(phase_2, "counts"))),
            diagnostic_gates=DiagnosticGates(
                _number(diagnostic, "max_recall_drop"),
                _number(diagnostic, "median_dice_drop"),
                _number(diagnostic, "medium_high_recall"),
            ),
            development_gates=DevelopmentGates(
                _number(development, "medium_high_recall"),
                _number(development, "nuisance_fpr"),
                _number(development, "median_dice"),
                _number(development, "feature_accuracy"),
            ),
            source_hashes=MappingProxyType(_string_mapping(_object(document, "source_hashes"))),
            ownership_map_hashes=MappingProxyType(
                _string_mapping(_object(document, "ownership_map_hashes"))
            ),
            _implementation_projection_paths=tuple(
                _string_list(document, "implementation_projection_paths")
            ),
            _direct_import_allowlist=MappingProxyType(
                {key: tuple(_string_list(allowlist, key)) for key in sorted(allowlist)}
            ),
        )

    @property
    def document(self) -> dict[str, Any]:
        return deepcopy(self._document)

    @property
    def base_commit(self) -> str:
        return _string(self._document, "base_commit")

    def implementation_projection_paths(self) -> tuple[str, ...]:
        return self._implementation_projection_paths

    def direct_import_allowlist(self) -> Mapping[str, tuple[str, ...]]:
        return self._direct_import_allowlist


def load_study_protocol_v2(
    path: Path | str = DEFAULT_STUDY_PROTOCOL_PATH,
) -> StudyProtocolV2:
    return StudyProtocolV2.from_path(Path(path).expanduser().resolve())


def load_frozen_diagnostic_matrix(
    path: Path | str = DEFAULT_DIAGNOSTIC_MATRIX_PATH,
) -> tuple[FrozenDiagnosticPlan, ...]:
    source_path = Path(path).expanduser().resolve()
    return _load_frozen_diagnostic_matrix_bytes(_read_bounded_bytes(source_path), source_path)


def _load_frozen_diagnostic_matrix_bytes(
    source_bytes: bytes,
    source_path: Path,
) -> tuple[FrozenDiagnosticPlan, ...]:
    document = _parse_json_object(source_bytes, source_path)
    if document.get("record_type") != "e1_feasibility_diagnostic_matrix_v1":
        raise StudyProtocolError("frozen diagnostic matrix record type is invalid")
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise StudyProtocolError("frozen diagnostic matrix rows must be an array")
    plans = tuple(_frozen_plan(row, ordinal) for ordinal, row in enumerate(rows))
    _validate_frozen_matrix(plans)
    return plans


def _validate_protocol_document(document: Mapping[str, Any]) -> str:
    if document.get("base_commit") != _EXPECTED_BASE_COMMIT:
        raise StudyProtocolError("study base commit is not the frozen E1 v2 HOLD commit")
    paths = _object(document, "paths")
    path_identities = {
        "artifact_root": _string(paths, "artifact_root"),
        "raw_data_root": _string(paths, "raw_data_root"),
    }
    if path_identities != {
        "artifact_root": _EXPECTED_ARTIFACT_ROOT_IDENTITY,
        "raw_data_root": _EXPECTED_RAW_DATA_ROOT_IDENTITY,
    }:
        raise StudyProtocolError("study path identities changed")
    for identity in path_identities.values():
        _project_path(identity)
    phase_1 = _object(document, "phase_1")
    if tuple(_string_list(phase_1, "modes")) != _EXPECTED_PHASE_1_MODES:
        raise StudyProtocolError("phase 1 resampling modes or ordering changed")
    limits = _object(phase_1, "limits")
    if _integer(limits, "diagnostic_rows") != 108 or (
        _integer(limits, "seed_start"),
        _integer(limits, "seed_end"),
    ) != (800000, 800107):
        raise StudyProtocolError("phase 1 diagnostic limits changed")
    if _number(limits, "threshold") != 0.0025 or _integer(limits, "difference_mask_minimum") != 32:
        raise StudyProtocolError("phase 1 fixed threshold or raw difference mask changed")
    counts = _integer_mapping(_object(_object(document, "phase_2"), "counts"))
    if (
        counts != _EXPECTED_PHASE_2_COUNTS
        or sum(counts[name] for name in counts if name != "total") != counts["total"]
    ):
        raise StudyProtocolError("phase 2 development counts changed")
    if _string_mapping(_object(document, "source_hashes")) != _EXPECTED_SOURCE_HASHES:
        raise StudyProtocolError("historical source hashes changed")
    if _string_mapping(_object(document, "ownership_map_hashes")) != _EXPECTED_OWNERSHIP_MAP_HASHES:
        raise StudyProtocolError("ownership-map hashes changed")
    implementation_projection = tuple(
        _string_list(document, "implementation_projection_paths")
    )
    if implementation_projection != _EXPECTED_IMPLEMENTATION_PROJECTION_PATHS:
        raise StudyProtocolError(
            "implementation projection changed or is not sorted and unique"
        )
    direct_import_allowlist = _object(document, "direct_import_allowlist")
    actual_allowlist = {
        key: tuple(_string_list(direct_import_allowlist, key))
        for key in sorted(direct_import_allowlist)
    }
    if actual_allowlist != _EXPECTED_DIRECT_IMPORT_ALLOWLIST:
        raise StudyProtocolError("direct import allowlist changed or is not sorted and unique")
    _validate_gates(document)
    _validate_snapshots(document)
    matrix = _object(document, "diagnostic_matrix")
    matrix_path = _project_path(_string(matrix, "path"))
    matrix_bytes = _read_bounded_bytes(matrix_path)
    actual = sha256_bytes(matrix_bytes)
    if actual != _string(matrix, "sha256"):
        raise StudyProtocolError("frozen diagnostic matrix raw hash does not match")
    _load_frozen_diagnostic_matrix_bytes(matrix_bytes, matrix_path)
    return actual


def _validate_gates(document: Mapping[str, Any]) -> None:
    diagnostic = _object(document, "diagnostic_gates")
    development = _object(document, "development_gates")
    if (
        _number(diagnostic, "max_recall_drop"),
        _number(diagnostic, "median_dice_drop"),
        _number(diagnostic, "medium_high_recall"),
    ) != (0.05, 0.01, 0.90):
        raise StudyProtocolError("phase 1 promotion gates changed")
    if (
        _number(development, "medium_high_recall"),
        _number(development, "nuisance_fpr"),
        _number(development, "median_dice"),
        _number(development, "feature_accuracy"),
    ) != (0.90, 0.05, 0.70, 0.95):
        raise StudyProtocolError("phase 2 performance gates changed")


def _validate_snapshots(document: Mapping[str, Any]) -> None:
    snapshots = document.get("negative_result_snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != 2:
        raise StudyProtocolError("negative-result snapshot bindings are invalid")
    source_hashes = _object(document, "source_hashes")
    required = {
        "task4_report": source_hashes["task4_report_raw_sha256"],
        "task4_progress_ledger": source_hashes["task4_progress_ledger_raw_sha256"],
    }
    seen: set[str] = set()
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise StudyProtocolError("negative-result snapshot entry is invalid")
        name = _string(snapshot, "name")
        expected = required.get(name)
        if expected is None or name in seen:
            raise StudyProtocolError("negative-result snapshot name is invalid")
        seen.add(name)
        if _string(snapshot, "raw_sha256") != expected:
            raise StudyProtocolError("negative-result snapshot hash binding is invalid")
        if not _string(snapshot, "original_sibling_path").startswith("/Users/jangtaeho/"):
            raise StudyProtocolError(
                "negative-result provenance must retain its original sibling path"
            )
        local_path = _project_path(_string(snapshot, "checked_in_path"))
        if sha256_bytes(_read_bounded_bytes(local_path)) != expected:
            raise StudyProtocolError("checked negative-result snapshot bytes changed")
    if seen != set(required):
        raise StudyProtocolError("negative-result snapshot coverage is incomplete")


def _validate_frozen_matrix(plans: tuple[FrozenDiagnosticPlan, ...]) -> None:
    if len(plans) != 108:
        raise StudyProtocolError("frozen diagnostic matrix must contain 108 rows")
    expected_ids = tuple(f"e1-v2-development-diagnostic-{ordinal:03d}" for ordinal in range(108))
    if tuple(plan.diagnostic_id for plan in plans) != expected_ids:
        raise StudyProtocolError("frozen diagnostic IDs are missing, duplicated, or out of order")
    if tuple(plan.seed for plan in plans) != tuple(range(800000, 800108)):
        raise StudyProtocolError("frozen diagnostic seed binding is invalid")
    if Counter(plan.combination for plan in plans) != {
        "scale_only": 48,
        "scale_translation": 12,
        "scale_rotation": 12,
        "scale_exposure": 12,
        "scale_medium_defect": 12,
        "scale_high_defect": 12,
    }:
        raise StudyProtocolError("frozen diagnostic combination counts are invalid")


def _frozen_plan(value: object, ordinal: int) -> FrozenDiagnosticPlan:
    if not isinstance(value, dict):
        raise StudyProtocolError(f"frozen diagnostic row {ordinal} must be an object")
    required = {
        "diagnostic_id",
        "seed",
        "combination",
        "cad_revision",
        "view_id",
        "scale_delta",
        "translation_x",
        "translation_y",
        "rotation_degrees",
        "exposure_gain_delta",
        "defect_type",
        "defect_severity",
        "expected_feature_id",
    }
    if set(value) != required:
        raise StudyProtocolError(f"frozen diagnostic row {ordinal} fields are invalid")
    try:
        plan = FrozenDiagnosticPlan(
            diagnostic_id=_string(value, "diagnostic_id"),
            seed=_integer(value, "seed"),
            combination=_string(value, "combination"),
            cad_revision=CadRevision(_string(value, "cad_revision")),
            view_id=ViewId(_string(value, "view_id")),
            scale_delta=_number(value, "scale_delta"),
            translation_x=_integer(value, "translation_x"),
            translation_y=_integer(value, "translation_y"),
            rotation_degrees=_number(value, "rotation_degrees"),
            exposure_gain_delta=_number(value, "exposure_gain_delta"),
            defect_type=_optional_string(value, "defect_type"),
            defect_severity=_optional_string(value, "defect_severity"),
            expected_feature_id=_optional_string(value, "expected_feature_id"),
        )
    except ValueError as exc:
        raise StudyProtocolError(f"frozen diagnostic row {ordinal} identity is invalid") from exc
    defect_values = (plan.defect_type, plan.defect_severity, plan.expected_feature_id)
    if any(item is None for item in defect_values) != all(item is None for item in defect_values):
        raise StudyProtocolError(f"frozen diagnostic row {ordinal} defect truth is incomplete")
    return plan


def _load_json_object(path: Path) -> dict[str, Any]:
    return _parse_json_object(_read_bounded_bytes(path), path)


def _read_bounded_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as source:
            loaded = source.read(_MAX_JSON_BYTES + 1)
    except OSError as exc:
        raise StudyProtocolError(f"input could not be read from {path}: {exc}") from exc
    if len(loaded) > _MAX_JSON_BYTES:
        raise StudyProtocolError(f"input exceeds {_MAX_JSON_BYTES} byte limit: {path}")
    return loaded


def _parse_json_object(source_bytes: bytes, path: Path) -> dict[str, Any]:
    try:

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            loaded: dict[str, Any] = {}
            for key, value in pairs:
                if key in loaded:
                    raise ValueError(f"duplicate JSON key: {key}")
                loaded[key] = value
            return loaded

        loaded = json.loads(
            source_bytes,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StudyProtocolError(f"JSON could not be loaded from {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise StudyProtocolError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], loaded)


def _local_schema_path(config_path: Path, document: Mapping[str, Any]) -> Path:
    reference = document.get("$schema")
    if (
        not isinstance(reference, str)
        or not reference
        or "://" in reference
        or reference.startswith("/")
    ):
        raise StudyProtocolError("study schema reference must be local and relative")
    schema_path = (config_path.parent / reference).resolve()
    if PROJECT_ROOT not in schema_path.parents:
        raise StudyProtocolError("study schema reference escapes the project")
    return schema_path


def _project_path(relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise StudyProtocolError("study runtime path must be repository-relative")
    path = (PROJECT_ROOT / relative_path).resolve()
    if PROJECT_ROOT not in path.parents:
        raise StudyProtocolError("study runtime path escapes the project")
    return path


def _object(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise StudyProtocolError(f"{key} must be an object")
    return cast(dict[str, Any], item)


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise StudyProtocolError(f"{key} must be a non-empty string")
    return item


def _optional_string(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise StudyProtocolError(f"{key} must be a string or null")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise StudyProtocolError(f"{key} must be an integer")
    return item


def _number(value: Mapping[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
        raise StudyProtocolError(f"{key} must be a finite number")
    return float(item)


def _string_list(value: Mapping[str, Any], key: str) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or not all(isinstance(entry, str) and entry for entry in item):
        raise StudyProtocolError(f"{key} must be a string array")
    return cast(list[str], item)


def _string_mapping(value: Mapping[str, Any]) -> dict[str, str]:
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise StudyProtocolError("mapping must contain only strings")
    return dict(cast(dict[str, str], value))


def _integer_mapping(value: Mapping[str, Any]) -> dict[str, int]:
    return {key: _integer(value, key) for key in value}


def _numeric_mapping(value: Mapping[str, Any]) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    for key in value:
        raw = value[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise StudyProtocolError(f"{key} must be a finite number")
        result[key] = raw
    return result
