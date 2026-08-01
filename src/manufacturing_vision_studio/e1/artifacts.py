"""Strict, canonical, fail-closed artifact storage for E1 evaluation runs."""

from __future__ import annotations

import json
import os
import stat
import uuid
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator, FormatChecker

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.e1.protocol import E1Protocol, load_e1_protocol
from manufacturing_vision_studio.errors import EvidenceError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
E1SchemaName = Literal["case-manifest", "evaluation-result", "threshold-lock"]

_SCHEMA_PATHS: dict[E1SchemaName, Path] = {
    "case-manifest": PROJECT_ROOT / "schemas" / "e1-case-manifest.v1.json",
    "evaluation-result": PROJECT_ROOT / "schemas" / "e1-evaluation-result.v1.json",
    "threshold-lock": PROJECT_ROOT / "schemas" / "e1-threshold-lock.v1.json",
}
_SHA256_ZERO = "0" * 64
_CASE_BINDING_FIELDS = (
    "case_id",
    "recipe_id",
    "seed_family",
    "reference_sha256",
    "inspection_sha256",
    "authoritative_mask_sha256",
    "expected_outcome",
    "defect_id",
)
DEFAULT_VOLATILE_FIELDS = frozenset(
    {"evaluation_run_id", "generated_at", "duration_ms", "local_absolute_paths"}
)
_RESULT_DIGEST_FIELDS = frozenset({"result_sha256", "deterministic_projection_sha256"})
_CALIBRATION_GATE_IDS = (
    "medium_high_defect_recall",
    "nuisance_only_false_positive_rate",
    "positive_case_median_dice",
    "affected_feature_mapping_accuracy",
)
_RESULT_GATE_CONTRACTS = (
    ("medium_high_defect_recall", "test_defect_medium_high", "gte", 0.9),
    ("nuisance_only_false_positive_rate", "test_nuisance_only", "lte", 0.05),
    ("positive_case_median_dice", "test_positive_all_severities", "gte", 0.7),
    (
        "affected_feature_mapping_accuracy",
        "test_positive_with_known_feature",
        "gte",
        0.95,
    ),
    ("revision_mismatch_publication_count", "all_trust_boundary_cases", "eq", 0),
    ("corrupted_evidence_publication_count", "all_trust_boundary_cases", "eq", 0),
    ("bundle_verify_reimport_rate", "all_bundle_eligible_cases", "gte", 1.0),
    ("dataset_split_hash_overlap", "development_calibration_test", "eq", 0),
    ("same_seed_manifest_equivalence", "full_profile_two_runs", "is_true", True),
    ("v0_1_regression", "v0_1_0_suite", "is_true", True),
)
_SPLIT_ORDER = {"development": 0, "calibration": 1, "test": 2}
_GROUP_ORDER = {"clean": 0, "nuisance": 1, "defect": 2, "trust_boundary": 3}
_INVENTORY_KEYS = {
    "schema_version",
    "hash_contract",
    "artifact_count",
    "payload_byte_size",
    "artifacts",
    "payload_sha256",
}
_INVENTORY_ENTRY_KEYS = {"path", "sha256", "byte_size", "media_type"}
_MAX_INVENTORY_ENTRIES = 4096


class E1ArtifactError(EvidenceError):
    """An E1 artifact could not be trusted or safely published."""


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """One verified artifact inventory entry."""

    path: str
    sha256: str
    byte_size: int
    media_type: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """A deterministic projection and the canonical hash of that projection."""

    document: Any
    sha256: str


def load_e1_schema(schema_name: E1SchemaName) -> dict[str, Any]:
    """Load and validate one repository-owned E1 schema without network resolution."""

    path = _SCHEMA_PATHS[schema_name]
    try:
        schema = _strict_json_loads(path.read_bytes())
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, TypeError) as exc:
        raise E1ArtifactError(
            "Required E1 schema is unavailable or malformed",
            code="SCHEMA_INVALID",
            details={"schema": schema_name},
        ) from exc
    return schema


def validate_e1_document(document: dict[str, Any], schema_name: E1SchemaName) -> None:
    """Validate a document structurally and enforce its cross-field hash bindings."""

    schema = load_e1_schema(schema_name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        field = ".".join(str(part) for part in first.absolute_path) or "$"
        raise E1ArtifactError(
            "E1 document does not satisfy its schema",
            code="SCHEMA_INVALID",
            details={"schema": schema_name, "field": field, "reason": first.message},
        )
    if schema_name == "case-manifest":
        _validate_case_manifest_semantics(document)
    elif schema_name == "threshold-lock":
        _validate_threshold_lock_semantics(document)
    else:
        _validate_evaluation_result_semantics(document)


def bind_document_sha256(document: dict[str, Any], field_name: str) -> dict[str, Any]:
    """Return a copy with ``field_name`` bound to the canonical self-excluding hash."""

    if not field_name or "." in field_name:
        raise ValueError("field_name must be one top-level JSON field")
    bound = deepcopy(document)
    bound[field_name] = _SHA256_ZERO
    bound[field_name] = canonical_json_hash(_without_top_level(bound, {field_name}))
    return bound


def verify_document_sha256(document: dict[str, Any], field_name: str) -> None:
    """Verify a top-level self-excluding SHA-256 binding."""

    declared = document.get(field_name)
    expected = canonical_json_hash(_without_top_level(document, {field_name}))
    if declared != expected:
        raise E1ArtifactError(
            "E1 document hash binding does not match",
            code="HASH_MISMATCH",
            details={"field": field_name, "expected": expected, "actual": declared},
        )


def case_binding_sha256(case: dict[str, Any]) -> str:
    """Hash the exact case-binding projection frozen by E1 protocol v1."""

    source_hashes = _expect_dict(case.get("source_hashes"), "source_hashes")
    defect = case.get("defect")
    defect_id = defect.get("defect_id") if isinstance(defect, dict) else None
    projection = {
        "case_id": case.get("case_id"),
        "recipe_id": case.get("recipe_id"),
        "seed_family": case.get("seed_family"),
        "reference_sha256": source_hashes.get("reference_sha256"),
        "inspection_sha256": source_hashes.get("inspection_sha256"),
        "authoritative_mask_sha256": source_hashes.get("authoritative_mask_sha256"),
        "expected_outcome": case.get("expected_outcome"),
        "defect_id": defect_id,
    }
    if tuple(projection) != _CASE_BINDING_FIELDS:
        raise AssertionError("case binding projection drifted")
    return canonical_json_hash(projection)


def finalize_case_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Bind each case and the dataset manifest, then validate the complete document."""

    finalized = deepcopy(document)
    cases = finalized.get("cases")
    if not isinstance(cases, list):
        raise E1ArtifactError("Case manifest cases must be an array", code="SCHEMA_INVALID")
    for raw_case in cases:
        case = _expect_dict(raw_case, "case")
        source_hashes = _expect_dict(case.get("source_hashes"), "source_hashes")
        source_hashes["case_binding_sha256"] = case_binding_sha256(case)
    finalized = bind_document_sha256(finalized, "manifest_sha256")
    validate_e1_document(finalized, "case-manifest")
    return finalized


def finalize_threshold_lock(document: dict[str, Any]) -> dict[str, Any]:
    """Bind and validate an immutable calibration threshold-lock artifact."""

    finalized = bind_document_sha256(document, "threshold_lock_sha256")
    validate_e1_document(finalized, "threshold-lock")
    return finalized


def deterministic_projection(
    document: Any,
    *,
    excluded_fields: frozenset[str] = DEFAULT_VOLATILE_FIELDS | _RESULT_DIGEST_FIELDS,
) -> ProjectionResult:
    """Remove only declared top-level volatile fields and hash the projection."""

    projected = (
        _without_top_level(document, set(excluded_fields))
        if isinstance(document, dict)
        else deepcopy(document)
    )
    return ProjectionResult(document=projected, sha256=canonical_json_hash(projected))


def finalize_evaluation_result(document: dict[str, Any]) -> dict[str, Any]:
    """Bind deterministic and exact result hashes without creating a self-hash cycle."""

    finalized = deepcopy(document)
    finalized["deterministic_projection_sha256"] = _SHA256_ZERO
    finalized["result_sha256"] = _SHA256_ZERO
    finalized["deterministic_projection_sha256"] = deterministic_projection(finalized).sha256
    finalized = bind_document_sha256(finalized, "result_sha256")
    validate_e1_document(finalized, "evaluation-result")
    return finalized


class E1ArtifactStore:
    """A root-pinned store for immutable canonical E1 files and inventories."""

    def __init__(
        self,
        root: Path,
        *,
        allowed_root: Path | None = None,
        max_artifact_bytes: int = 25 * 1024 * 1024,
        max_total_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        if max_artifact_bytes < 1 or max_total_bytes < max_artifact_bytes:
            raise ValueError("artifact limits are invalid")
        requested_root = _absolute_lexical(root)
        requested_allowed = _absolute_lexical(allowed_root or requested_root)
        if not requested_root.is_relative_to(requested_allowed):
            raise E1ArtifactError("Artifact root escapes allowed root", code="UNSAFE_PATH")
        _ensure_directory_without_symlinks(requested_allowed)
        _ensure_directory_without_symlinks(requested_root)
        self.root = requested_root.resolve(strict=True)
        self.allowed_root = requested_allowed.resolve(strict=True)
        if not self.root.is_relative_to(self.allowed_root):
            raise E1ArtifactError("Artifact root escapes allowed root", code="UNSAFE_PATH")
        self.max_artifact_bytes = max_artifact_bytes
        self.max_total_bytes = max_total_bytes

    def write_json(
        self,
        relative_path: str,
        document: dict[str, Any],
        *,
        schema_name: E1SchemaName | None = None,
        replace: bool = False,
    ) -> ArtifactRecord:
        """Validate and atomically publish one canonical JSON document."""

        if schema_name is not None:
            validate_e1_document(document, schema_name)
        data = canonical_json_bytes(document)
        self.write_bytes(relative_path, data, replace=replace)
        return ArtifactRecord(
            path=_validate_relative_path(relative_path),
            sha256=sha256_bytes(data),
            byte_size=len(data),
            media_type="application/json",
        )

    def write_bytes(self, relative_path: str, data: bytes, *, replace: bool = False) -> None:
        """Atomically publish bounded bytes without following path components."""

        normalized = _validate_relative_path(relative_path)
        if len(data) > self.max_artifact_bytes:
            raise E1ArtifactError("Artifact exceeds byte limit", code="INPUT_TOO_LARGE")
        parent, name = self._prepare_parent(normalized, create=True)
        directory_fd = _open_directory(parent)
        temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            view = memoryview(data)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None

            if replace:
                _assert_replace_target_safe(directory_fd, name)
                os.replace(
                    temporary_name,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            else:
                try:
                    os.link(
                        temporary_name,
                        name,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise E1ArtifactError(
                        "Artifact already exists and is immutable",
                        code="STORAGE_CONFLICT",
                        details={"path": normalized},
                    ) from exc
                os.unlink(temporary_name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
            os.close(directory_fd)

    def read_json(
        self,
        relative_path: str,
        *,
        schema_name: E1SchemaName | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Read canonical JSON and verify its optional digest and schema."""

        data = self.read_bytes(relative_path, expected_sha256=expected_sha256)
        try:
            document = _strict_json_loads(data)
        except ValueError as exc:
            raise E1ArtifactError("Artifact JSON is malformed", code="SCHEMA_INVALID") from exc
        if canonical_json_bytes(document) != data:
            raise E1ArtifactError(
                "Artifact JSON is not canonical",
                code="CANONICAL_JSON_MISMATCH",
                details={"path": relative_path},
            )
        if schema_name is not None:
            validate_e1_document(document, schema_name)
        return document

    def read_bytes(self, relative_path: str, *, expected_sha256: str | None = None) -> bytes:
        """Read a bounded regular artifact without following a final symlink."""

        normalized = _validate_relative_path(relative_path)
        parent, name = self._prepare_parent(normalized, create=False)
        directory_fd = _open_directory(parent)
        descriptor: int | None = None
        try:
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise E1ArtifactError(
                    "Artifact is missing",
                    code="EVIDENCE_INCOMPLETE",
                    details={"path": normalized},
                ) from exc
            if stat.S_ISLNK(before.st_mode):
                raise E1ArtifactError("Artifact is a symlink", code="SYMLINK_INPUT")
            if not stat.S_ISREG(before.st_mode):
                raise E1ArtifactError("Artifact is not a regular file", code="NON_REGULAR_INPUT")
            if before.st_nlink != 1:
                raise E1ArtifactError("Artifact has multiple hard links", code="NON_REGULAR_INPUT")
            if before.st_size > self.max_artifact_bytes:
                raise E1ArtifactError("Artifact exceeds byte limit", code="INPUT_TOO_LARGE")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(name, flags, dir_fd=directory_fd)
            opened = os.fstat(descriptor)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise E1ArtifactError("Artifact changed during validation", code="SYMLINK_INPUT")
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise E1ArtifactError("Artifact has multiple hard links", code="NON_REGULAR_INPUT")
            chunks: list[bytes] = []
            remaining = self.max_artifact_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > self.max_artifact_bytes:
                raise E1ArtifactError("Artifact exceeds byte limit", code="INPUT_TOO_LARGE")
            after = os.fstat(descriptor)
            if (
                after.st_nlink != 1
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
            ):
                raise E1ArtifactError(
                    "Artifact changed during validation", code="NON_REGULAR_INPUT"
                )
        except E1ArtifactError:
            raise
        except OSError as exc:
            raise E1ArtifactError("Artifact path is unsafe", code="SYMLINK_INPUT") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)
        actual = sha256_bytes(data)
        if expected_sha256 is not None and actual != expected_sha256:
            raise E1ArtifactError(
                "Artifact hash does not match",
                code="HASH_MISMATCH",
                details={"path": normalized, "expected": expected_sha256, "actual": actual},
            )
        return data

    def build_inventory(
        self,
        relative_paths: list[str],
        *,
        media_types: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build a sorted, hash-bound inventory over already published artifacts."""

        normalized = [_validate_relative_path(path) for path in relative_paths]
        if not normalized:
            raise E1ArtifactError("Artifact inventory cannot be empty", code="SCHEMA_INVALID")
        if len(normalized) > _MAX_INVENTORY_ENTRIES:
            raise E1ArtifactError("Artifact inventory exceeds limit", code="INPUT_TOO_LARGE")
        if len(normalized) != len(set(normalized)):
            raise E1ArtifactError(
                "Artifact inventory contains duplicate paths", code="SCHEMA_INVALID"
            )
        records: list[ArtifactRecord] = []
        total = 0
        for path in sorted(normalized):
            data = self.read_bytes(path)
            total += len(data)
            if total > self.max_total_bytes:
                raise E1ArtifactError("Artifact inventory exceeds limit", code="INPUT_TOO_LARGE")
            records.append(
                ArtifactRecord(
                    path=path,
                    sha256=sha256_bytes(data),
                    byte_size=len(data),
                    media_type=(media_types or {}).get(path, _media_type_for_path(path)),
                )
            )
        artifacts = [record.as_dict() for record in records]
        return {
            "schema_version": "1.0.0",
            "hash_contract": "mvs-canonical-json/v1",
            "artifact_count": len(artifacts),
            "payload_byte_size": total,
            "artifacts": artifacts,
            "payload_sha256": _inventory_payload_sha256(artifacts),
        }

    def write_inventory(
        self,
        relative_path: str,
        members: list[str],
        *,
        media_types: dict[str, str] | None = None,
    ) -> ArtifactRecord:
        """Build and immutably publish an artifact inventory."""

        inventory_path = _validate_relative_path(relative_path)
        if inventory_path in {_validate_relative_path(path) for path in members}:
            raise E1ArtifactError("Inventory cannot include itself", code="SCHEMA_INVALID")
        inventory = self.build_inventory(members, media_types=media_types)
        _validate_inventory_shape(inventory)
        return self.write_json(inventory_path, inventory)

    def verify_inventory(
        self, relative_path: str, *, expected_sha256: str | None = None
    ) -> tuple[ArtifactRecord, ...]:
        """Verify canonical inventory bytes, every member, and aggregate bindings."""

        inventory_path = _validate_relative_path(relative_path)
        inventory = self.read_json(inventory_path, expected_sha256=expected_sha256)
        _validate_inventory_shape(inventory)
        raw_artifacts = cast(list[dict[str, Any]], inventory["artifacts"])
        if any(raw["path"] == inventory_path for raw in raw_artifacts):
            raise E1ArtifactError("Inventory cannot include itself", code="SCHEMA_INVALID")
        if inventory["payload_byte_size"] > self.max_total_bytes:
            raise E1ArtifactError("Artifact inventory exceeds limit", code="INPUT_TOO_LARGE")
        records: list[ArtifactRecord] = []
        total = 0
        for raw in raw_artifacts:
            path = cast(str, raw["path"])
            data = self.read_bytes(path, expected_sha256=cast(str, raw["sha256"]))
            if len(data) != raw["byte_size"]:
                raise E1ArtifactError(
                    "Artifact size does not match inventory", code="HASH_MISMATCH"
                )
            total += len(data)
            if total > self.max_total_bytes:
                raise E1ArtifactError("Artifact inventory exceeds limit", code="INPUT_TOO_LARGE")
            records.append(
                ArtifactRecord(
                    path=path,
                    sha256=cast(str, raw["sha256"]),
                    byte_size=cast(int, raw["byte_size"]),
                    media_type=cast(str, raw["media_type"]),
                )
            )
        if total != inventory["payload_byte_size"]:
            raise E1ArtifactError("Inventory payload size does not match", code="HASH_MISMATCH")
        expected_payload = _inventory_payload_sha256(raw_artifacts)
        if inventory["payload_sha256"] != expected_payload:
            raise E1ArtifactError("Inventory payload hash does not match", code="HASH_MISMATCH")
        return tuple(records)

    def _prepare_parent(self, relative_path: str, *, create: bool) -> tuple[Path, str]:
        pure = PurePosixPath(relative_path)
        current = self.root
        for part in pure.parts[:-1]:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                if not create:
                    raise E1ArtifactError(
                        "Artifact parent is missing", code="EVIDENCE_INCOMPLETE"
                    ) from None
                current.mkdir(mode=0o700)
                metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise E1ArtifactError("Artifact path contains a symlink", code="SYMLINK_INPUT")
            if not stat.S_ISDIR(metadata.st_mode):
                raise E1ArtifactError(
                    "Artifact parent is not a directory", code="NON_REGULAR_INPUT"
                )
            if not current.resolve(strict=True).is_relative_to(self.root):
                raise E1ArtifactError("Artifact path escapes root", code="UNSAFE_PATH")
        return current, pure.name


def _validate_case_manifest_semantics(document: dict[str, Any]) -> None:
    verify_document_sha256(document, "manifest_sha256")
    protocol = _validate_protocol_binding(document)
    expected_generator = _generator_binding(protocol)
    if document["generator"] != expected_generator:
        raise E1ArtifactError(
            "Manifest generator binding does not match the frozen protocol",
            code="HASH_MISMATCH",
        )
    cases = cast(list[dict[str, Any]], document["cases"])
    case_ids = [cast(str, case["case_id"]) for case in cases]
    expected_case_ids = _protocol_case_ids(protocol, cast(str, document["profile"]))
    if tuple(case_ids) != expected_case_ids:
        raise E1ArtifactError(
            "Manifest cases do not match the frozen profile",
            code="SCHEMA_INVALID",
        )
    canonical_case_ids = [
        cast(str, case["case_id"])
        for case in sorted(
            cases,
            key=lambda case: (
                _SPLIT_ORDER[cast(str, case["split"])],
                _GROUP_ORDER[cast(str, case["group"])],
                cast(int, case["ordinal"]),
            ),
        )
    ]
    if case_ids != canonical_case_ids or len(case_ids) != len(set(case_ids)):
        raise E1ArtifactError(
            "Case manifests must have unique case-id ordering", code="SCHEMA_INVALID"
        )
    wrapper_generator = document["generator"]
    profile = document["profile"]
    group_counts = {name: 0 for name in ("clean", "nuisance", "defect", "trust_boundary")}
    split_counts = {
        split: {name: 0 for name in group_counts}
        for split in ("development", "calibration", "test")
    }
    for case in cases:
        expected_case_id = f"e1-{case['split']}-{case['group']}-{cast(int, case['ordinal']):03d}"
        if case["case_id"] != expected_case_id:
            raise E1ArtifactError("Case identity fields do not match", code="SCHEMA_INVALID")
        if case["recipe_id"] != f"mvs-e1-recipe-v1/{expected_case_id}":
            raise E1ArtifactError("Case recipe binding does not match", code="SCHEMA_INVALID")
        if case["generator"] != wrapper_generator:
            raise E1ArtifactError("Case generator binding does not match", code="HASH_MISMATCH")
        memberships = cast(list[str], case["profile_membership"])
        if profile == "mini" and "mini" not in memberships:
            raise E1ArtifactError("Mini manifest contains a non-mini case", code="SCHEMA_INVALID")
        source_hashes = cast(dict[str, Any], case["source_hashes"])
        if source_hashes["case_binding_sha256"] != case_binding_sha256(case):
            raise E1ArtifactError("Case binding hash does not match", code="HASH_MISMATCH")
        group = cast(str, case["group"])
        split = cast(str, case["split"])
        group_counts[group] += 1
        split_counts[split][group] += 1

    counts = cast(dict[str, Any], document["counts"])
    if counts["case_count"] != len(cases):
        raise E1ArtifactError("Case count does not match manifest", code="SCHEMA_INVALID")
    if counts["trust_case_count"] != group_counts["trust_boundary"]:
        raise E1ArtifactError("Trust case count does not match manifest", code="SCHEMA_INVALID")
    if counts["inference_case_count"] != len(cases) - group_counts["trust_boundary"]:
        raise E1ArtifactError("Inference case count does not match manifest", code="SCHEMA_INVALID")
    if counts["group_counts"] != group_counts:
        raise E1ArtifactError("Group counts do not match manifest", code="SCHEMA_INVALID")
    for split, actual_groups in split_counts.items():
        declared = cast(dict[str, Any], counts["split_counts"])[split]
        if declared["case_count"] != sum(actual_groups.values()):
            raise E1ArtifactError("Split count does not match manifest", code="SCHEMA_INVALID")
        if declared["group_counts"] != actual_groups:
            raise E1ArtifactError("Split groups do not match manifest", code="SCHEMA_INVALID")


def _validate_threshold_lock_semantics(document: dict[str, Any]) -> None:
    verify_document_sha256(document, "threshold_lock_sha256")
    _validate_protocol_binding(document)
    gates = cast(list[dict[str, Any]], document["calibration_gate_results"])
    gate_ids = tuple(cast(str, gate["gate_id"]) for gate in gates)
    if gate_ids != _CALIBRATION_GATE_IDS:
        raise E1ArtifactError(
            "Calibration gates must be complete and protocol ordered", code="SCHEMA_INVALID"
        )
    expected_contracts = {
        "medium_high_defect_recall": ("gte", 0.9),
        "nuisance_only_false_positive_rate": ("lte", 0.05),
        "positive_case_median_dice": ("gte", 0.7),
        "affected_feature_mapping_accuracy": ("gte", 0.95),
    }
    for gate in gates:
        if (gate["operator"], gate["threshold"]) != expected_contracts[gate["gate_id"]]:
            raise E1ArtifactError(
                "Calibration gate contract does not match protocol", code="SCHEMA_INVALID"
            )
        if gate["passed"] != _gate_passed(
            cast(str, gate["operator"]), gate["observed"], gate["threshold"]
        ):
            raise E1ArtifactError(
                "Calibration gate outcome does not match its observation",
                code="SCHEMA_INVALID",
            )
    all_passed = all(cast(bool, gate["passed"]) for gate in gates)
    locked = document["lock_status"] == "LOCKED"
    if locked != all_passed or cast(bool, document["test_execution_allowed"]) != locked:
        raise E1ArtifactError(
            "Threshold lock status does not match calibration gates", code="SCHEMA_INVALID"
        )


def _validate_evaluation_result_semantics(document: dict[str, Any]) -> None:
    verify_document_sha256(document, "result_sha256")
    protocol = _validate_protocol_binding(document)
    if document["generator"] != _generator_binding(protocol):
        raise E1ArtifactError(
            "Result generator binding does not match the frozen protocol",
            code="HASH_MISMATCH",
        )
    expected_projection = deterministic_projection(document).sha256
    if document["deterministic_projection_sha256"] != expected_projection:
        raise E1ArtifactError(
            "Deterministic result projection does not match", code="HASH_MISMATCH"
        )
    excluded = tuple(cast(list[str], document["reproducibility"]["volatile_fields_excluded"]))
    if excluded != tuple(sorted(DEFAULT_VOLATILE_FIELDS)):
        raise E1ArtifactError(
            "Result volatile-field projection does not match protocol", code="SCHEMA_INVALID"
        )
    status = document["evaluation_status"]
    metrics = document["metrics"]
    if status == "COMPLETED" and metrics is None:
        raise E1ArtifactError("Completed result requires metrics", code="EVIDENCE_INCOMPLETE")
    if status == "CALIBRATION_HOLD" and metrics is not None:
        raise E1ArtifactError("Calibration HOLD cannot publish test metrics", code="SCHEMA_INVALID")
    if metrics is not None and document["verdict"] != metrics["verdict"]:
        raise E1ArtifactError("Result verdict does not match metrics", code="SCHEMA_INVALID")
    reproducibility = cast(dict[str, Any], document["reproducibility"])
    projection_hashes = cast(list[str], reproducibility["deterministic_projection_sha256s"])
    if reproducibility["equivalent"] != (projection_hashes[0] == projection_hashes[1]):
        raise E1ArtifactError(
            "Repeatability verdict does not match projection hashes",
            code="SCHEMA_INVALID",
        )
    if metrics is not None:
        _validate_result_gates(cast(dict[str, Any], metrics))


def _validate_result_gates(metrics: dict[str, Any]) -> None:
    gates = cast(list[dict[str, Any]], metrics["gates"])
    actual_contracts = tuple(
        (gate["gate_id"], gate["scope"], gate["operator"], gate["threshold"]) for gate in gates
    )
    if actual_contracts != _RESULT_GATE_CONTRACTS:
        raise E1ArtifactError(
            "Result gates do not match the frozen protocol order",
            code="SCHEMA_INVALID",
        )
    for gate in gates:
        if gate["passed"] != _gate_passed(
            cast(str, gate["operator"]), gate["observed"], gate["threshold"]
        ):
            raise E1ArtifactError(
                "Result gate outcome does not match its observation",
                code="SCHEMA_INVALID",
            )
    passed = sum(bool(gate["passed"]) for gate in gates)
    expected_summary = {
        "passed": passed,
        "total": len(gates),
        "all_passed": passed == len(gates),
    }
    if metrics["gate_summary"] != expected_summary:
        raise E1ArtifactError("Result gate summary is inconsistent", code="SCHEMA_INVALID")
    expected_verdict = "PASS" if expected_summary["all_passed"] else "HOLD"
    if metrics["verdict"] != expected_verdict:
        raise E1ArtifactError("Result gate verdict is inconsistent", code="SCHEMA_INVALID")


def _gate_passed(operator: str, observed: Any, threshold: Any) -> bool:
    if observed is None:
        return False
    if operator == "is_true":
        return observed is True and threshold is True
    if isinstance(observed, bool) or isinstance(threshold, bool):
        return False
    if not isinstance(observed, (int, float)) or not isinstance(threshold, (int, float)):
        return False
    if operator == "gte":
        return observed >= threshold
    if operator == "lte":
        return observed <= threshold
    if operator == "eq":
        return observed == threshold
    return False


def _validate_protocol_binding(document: dict[str, Any]) -> E1Protocol:
    try:
        protocol = load_e1_protocol()
    except ValueError as exc:
        raise E1ArtifactError(
            "Frozen E1 protocol is unavailable", code="EVIDENCE_INCOMPLETE"
        ) from exc
    expected = {
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.protocol_version,
        "protocol_sha256": protocol.configuration_sha256,
    }
    if document["protocol"] != expected:
        raise E1ArtifactError(
            "Artifact protocol binding does not match the frozen protocol",
            code="HASH_MISMATCH",
        )
    return protocol


def _generator_binding(protocol: E1Protocol) -> dict[str, str]:
    return {
        "generator_id": protocol.generator_id,
        "generator_version": protocol.generator_version,
        "generator_configuration_sha256": protocol.generator_configuration_sha256,
    }


def _protocol_case_ids(protocol: E1Protocol, profile: str) -> tuple[str, ...]:
    if profile == "mini":
        return protocol.exact_mini_case_ids
    profiles = _expect_dict(protocol.document.get("dataset_profiles"), "dataset_profiles")
    composition = _expect_dict(profiles.get("split_composition"), "split_composition")
    case_ids: list[str] = []
    for split in _SPLIT_ORDER:
        split_contract = _expect_dict(composition.get(split), f"split_composition.{split}")
        group_counts = _expect_dict(
            split_contract.get("group_counts"), f"split_composition.{split}.group_counts"
        )
        for group in _GROUP_ORDER:
            count = group_counts.get(group)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise E1ArtifactError(
                    "Frozen E1 profile counts are invalid", code="EVIDENCE_INCOMPLETE"
                )
            case_ids.extend(f"e1-{split}-{group}-{ordinal:03d}" for ordinal in range(count))
    return tuple(case_ids)


def _strict_json_loads(data: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            data,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("JSON is malformed") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON root must be an object")
    return cast(dict[str, Any], parsed)


def _without_top_level(document: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in document.items() if key not in excluded}


def _expect_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise E1ArtifactError(f"{field} must be an object", code="SCHEMA_INVALID")
    return cast(dict[str, Any], value)


def _validate_relative_path(path: str) -> str:
    if not path or len(path) > 240 or "\\" in path or "\x00" in path:
        raise E1ArtifactError("Artifact path is unsafe", code="UNSAFE_PATH")
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or pure.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise E1ArtifactError("Artifact path is unsafe", code="UNSAFE_PATH")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise E1ArtifactError("Artifact path is unsafe", code="UNSAFE_PATH")
    return pure.as_posix()


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _ensure_directory_without_symlinks(path: Path) -> None:
    if not path.is_absolute():
        raise E1ArtifactError("Artifact root must be absolute", code="UNSAFE_PATH")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as exc:
                raise E1ArtifactError(
                    "Artifact root cannot be created", code="UNSAFE_PATH"
                ) from exc
            metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise E1ArtifactError("Artifact root contains a symlink", code="SYMLINK_INPUT")
        if not stat.S_ISDIR(metadata.st_mode):
            raise E1ArtifactError(
                "Artifact root parent is not a directory", code="NON_REGULAR_INPUT"
            )


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise E1ArtifactError("Artifact directory is unsafe", code="SYMLINK_INPUT") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise E1ArtifactError("Artifact parent is not a directory", code="NON_REGULAR_INPUT")
    return descriptor


def _assert_replace_target_safe(directory_fd: int, name: str) -> None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise E1ArtifactError("Artifact destination is a symlink", code="SYMLINK_INPUT")
    if not stat.S_ISREG(metadata.st_mode):
        raise E1ArtifactError("Artifact destination is not regular", code="NON_REGULAR_INPUT")


def _media_type_for_path(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".txt": "text/plain",
    }.get(suffix, "application/octet-stream")


def _inventory_payload_sha256(artifacts: list[dict[str, Any]]) -> str:
    projection = {
        "algorithm": "sha256",
        "artifacts": [
            {
                "path": artifact["path"],
                "sha256": artifact["sha256"],
                "byte_size": artifact["byte_size"],
                "media_type": artifact["media_type"],
            }
            for artifact in artifacts
        ],
    }
    return canonical_json_hash(projection)


def _validate_inventory_shape(inventory: dict[str, Any]) -> None:
    if set(inventory) != _INVENTORY_KEYS:
        raise E1ArtifactError("Artifact inventory fields are invalid", code="SCHEMA_INVALID")
    if (
        inventory["schema_version"] != "1.0.0"
        or inventory["hash_contract"] != "mvs-canonical-json/v1"
    ):
        raise E1ArtifactError("Artifact inventory version is unsupported", code="SCHEMA_INVALID")
    artifacts = inventory["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise E1ArtifactError("Artifact inventory entries are invalid", code="SCHEMA_INVALID")
    if len(artifacts) > _MAX_INVENTORY_ENTRIES:
        raise E1ArtifactError("Artifact inventory exceeds limit", code="INPUT_TOO_LARGE")
    paths: list[str] = []
    total = 0
    for raw in artifacts:
        if not isinstance(raw, dict) or set(raw) != _INVENTORY_ENTRY_KEYS:
            raise E1ArtifactError("Artifact inventory entry is invalid", code="SCHEMA_INVALID")
        path = raw["path"]
        digest = raw["sha256"]
        byte_size = raw["byte_size"]
        media_type = raw["media_type"]
        if not isinstance(path, str):
            raise E1ArtifactError("Artifact inventory path is invalid", code="SCHEMA_INVALID")
        paths.append(_validate_relative_path(path))
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise E1ArtifactError("Artifact inventory digest is invalid", code="SCHEMA_INVALID")
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise E1ArtifactError("Artifact inventory size is invalid", code="SCHEMA_INVALID")
        if not isinstance(media_type, str) or not media_type or len(media_type) > 128:
            raise E1ArtifactError("Artifact inventory media type is invalid", code="SCHEMA_INVALID")
        total += byte_size
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise E1ArtifactError("Artifact inventory paths are not canonical", code="SCHEMA_INVALID")
    if inventory["artifact_count"] != len(artifacts):
        raise E1ArtifactError("Artifact inventory count is invalid", code="SCHEMA_INVALID")
    if inventory["payload_byte_size"] != total:
        raise E1ArtifactError("Artifact inventory size is invalid", code="HASH_MISMATCH")
    if inventory["payload_sha256"] != _inventory_payload_sha256(artifacts):
        raise E1ArtifactError("Artifact inventory hash is invalid", code="HASH_MISMATCH")
