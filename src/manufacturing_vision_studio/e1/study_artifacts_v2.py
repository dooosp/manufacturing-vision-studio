"""Canonical, immutable artifact controls for the development-only E1 study."""

from __future__ import annotations

import json
import math
import os
import stat
import uuid
import weakref
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from jsonschema import Draft202012Validator

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)

if TYPE_CHECKING:
    from manufacturing_vision_studio.e1.study_protocol_v2 import StudyProtocolV2

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STUDY_ARTIFACT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "e1-feasibility-study-artifact.v1.json"
_MAX_SCHEMA_BYTES = 4 * 1024 * 1024
_DEFAULT_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
_MAX_INVENTORY_ENTRIES = 256
_MAX_INVENTORY_DEPTH = 8
_MAX_DIRECTORY_NAME_BYTES = 255
_SHA1_LENGTH = 40
_SHA256_LENGTH = 64
_ZERO_SHA256 = "0" * _SHA256_LENGTH
_STUDY_ID = "e1-feasibility-separability"
_PHASE_1_MODES = ("NEAREST", "BILINEAR", "BICUBIC")
_FEATURE_IDS = ("bottom_edge", "hole_left", "hole_right", "top_edge", "top_face")
_RESULT_RECORD_TYPES = {
    "scope_audit",
    "diagnostic_result",
    "feature_oracle",
    "development_result",
    "decision",
}
_PRE_DECISION_PATHS = (
    "implementation-validation.json",
    "retention-audit.json",
    "phase-1-execution-claim.json",
    "known-transform-diagnostic-108.json",
    "scope-audit.json",
    "feature-ownership-oracle.json",
    "phase-2-execution-claim.json",
    "known-transform-development-120.json",
)
_PERFORMANCE_DECISION_BRANCHES = {
    "FEATURE_CONTRACT_FAILED": (_PRE_DECISION_PATHS[:6], "FEATURE_ORACLE_FAILED"),
    "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED": (
        _PRE_DECISION_PATHS[:6],
        "NO_DIAGNOSTIC_MODE_ELIGIBLE",
    ),
    "DIFFERENCE_BASELINE_LIMITED": (
        _PRE_DECISION_PATHS,
        "NO_DEVELOPMENT_MODE_PASSED",
    ),
    "TRANSFORM_ESTIMATION_LIMITED": (
        _PRE_DECISION_PATHS,
        "DEVELOPMENT_MODE_PASSED",
    ),
}


class StudyArtifactError(ValueError):
    """A study artifact is malformed, unsafe, mutable, or unverifiable."""


@dataclass(frozen=True, slots=True)
class StudyArtifactRecord:
    path: str
    sha256: str
    byte_size: int
    media_type: str
    record_sha256: str | None


@dataclass(frozen=True, slots=True)
class StudyArtifactInventoryEntry:
    """One immutable no-follow entry from the pinned artifact-root inventory."""

    path: str
    kind: Literal["file", "directory", "symlink", "other"]
    byte_size: int
    link_count: int


@dataclass(frozen=True, slots=True)
class VerifiedStudyJson:
    """One immutable JSON verification bound to the exact bytes read once."""

    document: Mapping[str, object]
    raw_bytes: bytes
    raw_sha256: str
    record_sha256: str


@dataclass(frozen=True, slots=True)
class StudyGateRecord:
    name: str
    status: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    numerator: int | None
    denominator: int | None
    observed: float | int | bool | str | None
    operator: Literal["ge", "le", "eq"] | None
    threshold: float | int | bool | None
    reason: str | None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("study gate requires a name")
        if self.status not in {"PASS", "FAIL", "NOT_APPLICABLE"}:
            raise ValueError("study gate status is invalid")
        if self.operator not in {None, "ge", "le", "eq"}:
            raise ValueError("study gate operator is invalid")
        _require_finite_json_value(self.observed)
        _require_finite_json_value(self.threshold)
        if self.status == "NOT_APPLICABLE" and any(
            value is not None
            for value in (
                self.numerator,
                self.denominator,
                self.observed,
                self.operator,
                self.threshold,
            )
        ):
            raise ValueError("NOT_APPLICABLE gate cannot carry a passing observation")
        if self.status == "NOT_APPLICABLE" and not self.reason:
            raise ValueError("NOT_APPLICABLE gate requires a fixed reason")
        if self.status in {"PASS", "FAIL"} and (
            self.observed is None or self.operator is None or self.threshold is None
        ):
            raise ValueError("applicable gate requires observed/operator/threshold")

    def as_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "observed": self.observed,
            "operator": self.operator,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ExecutionClaim:
    phase: Literal["phase1", "phase2"]
    execution_commit: str
    protocol_sha256: str
    artifact_root: str
    expected_members: int
    expected_modes: tuple[str, ...]
    expected_mode_count: int
    expected_inference_rows_per_mode: int
    trust_binding_rows: int
    _base_commit: str = field(repr=False)
    _study_id: str = field(repr=False)

    def as_record(self) -> dict[str, object]:
        return {
            "record_type": "phase_execution_claim",
            "schema_version": "1.0.0",
            "study_id": self._study_id,
            "development_only": True,
            "selection_eligible": False,
            "release_claim_allowed": False,
            "base_commit": self._base_commit,
            "execution_commit": self.execution_commit,
            "protocol_sha256": self.protocol_sha256,
            "artifact_root": self.artifact_root,
            "payload": {
                "phase": self.phase,
                "expected_members": self.expected_members,
                "expected_modes": list(self.expected_modes),
                "expected_mode_count": self.expected_mode_count,
                "expected_inference_rows_per_mode": self.expected_inference_rows_per_mode,
                "trust_binding_rows": self.trust_binding_rows,
            },
            "record_sha256": _ZERO_SHA256,
        }


def begin_phase_execution(
    *,
    phase: Literal["phase1", "phase2"],
    protocol: StudyProtocolV2,
    execution_commit: str,
    eligible_modes: tuple[str, ...],
) -> ExecutionClaim:
    """Create the exact immutable control claim for one authorized study phase."""

    if phase not in {"phase1", "phase2"}:
        raise StudyArtifactError("phase execution claim phase is invalid")
    if not _is_lower_hex(execution_commit, _SHA1_LENGTH):
        raise StudyArtifactError("execution commit must be a lowercase 40-character SHA")
    if not isinstance(eligible_modes, tuple) or not all(
        isinstance(mode, str) for mode in eligible_modes
    ):
        raise StudyArtifactError("eligible modes must be a tuple of protocol modes")

    protocol_modes = tuple(protocol.phase_1_modes)
    if protocol_modes != _PHASE_1_MODES:
        raise StudyArtifactError("protocol phase modes do not match the frozen study")
    protocol_sha256 = protocol.configuration_sha256
    if not _is_lower_hex(protocol_sha256, _SHA256_LENGTH):
        raise StudyArtifactError("protocol SHA must be a lowercase 64-character SHA")
    base_commit = protocol.base_commit
    if not _is_lower_hex(base_commit, _SHA1_LENGTH):
        raise StudyArtifactError("base commit must be a lowercase 40-character SHA")
    study_id = protocol.document.get("study_id")
    if study_id != _STUDY_ID:
        raise StudyArtifactError("study ID does not match the frozen protocol")

    modes: tuple[str, ...]
    if phase == "phase1":
        if eligible_modes:
            raise StudyArtifactError("phase1 eligible modes must be empty before execution")
        modes = protocol_modes
        expected_members = 108
        inference_rows = 108
        trust_rows = 0
    else:
        if not eligible_modes:
            raise StudyArtifactError("phase2 eligible modes must be nonempty")
        if len(eligible_modes) != len(set(eligible_modes)):
            raise StudyArtifactError("phase2 eligible modes contain a duplicate")
        if any(mode not in protocol_modes for mode in eligible_modes):
            raise StudyArtifactError("phase2 eligible modes contain a non-protocol mode")
        protocol_ordered = tuple(mode for mode in protocol_modes if mode in eligible_modes)
        if eligible_modes != protocol_ordered:
            raise StudyArtifactError("phase2 eligible modes must retain protocol order")
        modes = eligible_modes
        expected_members = 120
        inference_rows = 114
        trust_rows = 6

    artifact_root = protocol.artifact_root.as_posix()
    if not artifact_root:
        raise StudyArtifactError("artifact root is empty")
    return ExecutionClaim(
        phase=phase,
        execution_commit=execution_commit,
        protocol_sha256=protocol_sha256,
        artifact_root=artifact_root,
        expected_members=expected_members,
        expected_modes=modes,
        expected_mode_count=len(modes),
        expected_inference_rows_per_mode=inference_rows,
        trust_binding_rows=trust_rows,
        _base_commit=base_commit,
        _study_id=study_id,
    )


def finalize_study_record(document: Mapping[str, object]) -> dict[str, object]:
    """Return a defensive copy bound by a self-excluding canonical SHA-256."""

    try:
        finalized = deepcopy(dict(document))
        finalized.pop("record_sha256", None)
        _require_finite_json_value(finalized)
        finalized["record_sha256"] = canonical_json_hash(finalized)
    except (TypeError, ValueError, OverflowError) as exc:
        raise StudyArtifactError("study record contains a non-finite or non-JSON value") from exc
    return finalized


def verify_self_hash(document: Mapping[str, object], *, field: str = "record_sha256") -> None:
    """Verify one top-level self-excluding canonical hash binding."""

    declared = document.get(field)
    if not isinstance(declared, str) or not _is_lower_hex(declared, _SHA256_LENGTH):
        raise StudyArtifactError("study record self-hash is missing or malformed")
    projection = deepcopy(dict(document))
    projection.pop(field, None)
    try:
        _require_finite_json_value(projection)
        expected = canonical_json_hash(projection)
    except (TypeError, ValueError, OverflowError) as exc:
        raise StudyArtifactError("study record contains a non-finite or non-JSON value") from exc
    if declared != expected:
        raise StudyArtifactError("study record self-hash does not match")


def load_strict_json_object(payload: bytes) -> dict[str, Any]:
    """Parse one JSON object while rejecting duplicates and every non-finite number."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite JSON number")
        return parsed

    try:
        loaded = json.loads(
            payload,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError) as exc:
        raise StudyArtifactError(f"artifact JSON is malformed or non-finite: {exc}") from exc
    if not isinstance(loaded, dict):
        raise StudyArtifactError("artifact JSON root must be an object")
    return cast(dict[str, Any], loaded)


def validate_study_schema(document: Mapping[str, object]) -> None:
    """Validate the currently registered closed study artifact variants."""

    schema_payload = read_bounded_bytes(
        STUDY_ARTIFACT_SCHEMA_PATH,
        maximum=_MAX_SCHEMA_BYTES,
    )
    schema = load_strict_json_object(schema_payload)
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(document)),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
    except Exception as exc:
        raise StudyArtifactError(f"study artifact schema is invalid: {exc}") from exc
    if errors:
        first = errors[0]
        field_path = ".".join(str(part) for part in first.absolute_path) or "$"
        raise StudyArtifactError(
            f"study artifact failed schema validation at {field_path}: {first.message}"
        )
    _validate_phase_claim_semantics(document)
    _validate_result_semantics(document)


def read_bounded_bytes(path: Path, *, maximum: int) -> bytes:
    """Read stable regular-file bytes without following a final symlink."""

    if maximum < 1:
        raise ValueError("maximum must be positive")
    source_path = _absolute_lexical(path)
    descriptor: int | None = None
    try:
        before = source_path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise StudyArtifactError("input path is a symlink")
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise StudyArtifactError("input path is not a single-link regular file")
        if before.st_size > maximum:
            raise StudyArtifactError("input exceeds byte limit")
        descriptor = os.open(source_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise StudyArtifactError("input changed during validation")
        payload = _read_descriptor_bounded(descriptor, maximum=maximum)
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise StudyArtifactError("input changed during validation")
        return payload
    except StudyArtifactError:
        raise
    except OSError as exc:
        raise StudyArtifactError(f"input could not be read safely: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


class StudyArtifactStore:
    """Root-pinned immutable storage for bounded study evidence."""

    def __init__(
        self,
        root: Path,
        *,
        allowed_root: Path | None = None,
        max_artifact_bytes: int = _DEFAULT_MAX_ARTIFACT_BYTES,
    ) -> None:
        if max_artifact_bytes < 1:
            raise ValueError("artifact byte limit must be positive")
        requested_root = _absolute_lexical(root)
        requested_allowed = _absolute_lexical(allowed_root or requested_root)
        if not requested_root.is_relative_to(requested_allowed):
            raise StudyArtifactError("artifact root escapes allowed root")
        allowed_fd = _open_or_create_absolute_directory(requested_allowed)
        try:
            root_fd = _traverse_directory_fd(
                allowed_fd,
                requested_root.relative_to(requested_allowed).parts,
                create=True,
            )
        finally:
            os.close(allowed_fd)
        try:
            root_metadata = _validated_directory_metadata(root_fd, purpose="artifact root")
        except Exception:
            os.close(root_fd)
            raise
        self._bind_root(
            requested_root=requested_root,
            requested_allowed=requested_allowed,
            max_artifact_bytes=max_artifact_bytes,
            root_fd=root_fd,
            root_metadata=root_metadata,
        )

    @classmethod
    def open_existing(
        cls,
        root: Path,
        *,
        allowed_root: Path | None = None,
        max_artifact_bytes: int = _DEFAULT_MAX_ARTIFACT_BYTES,
    ) -> StudyArtifactStore | None:
        """Open a safely pinned existing root, returning ``None`` only for absence."""

        if max_artifact_bytes < 1:
            raise ValueError("artifact byte limit must be positive")
        requested_root = _absolute_lexical(root)
        requested_allowed = _absolute_lexical(allowed_root or requested_root)
        if not requested_root.is_relative_to(requested_allowed):
            raise StudyArtifactError("artifact root escapes allowed root")
        allowed_fd = _open_existing_absolute_directory(requested_allowed)
        if allowed_fd is None:
            return None
        try:
            root_fd = _traverse_existing_directory_fd(
                allowed_fd,
                requested_root.relative_to(requested_allowed).parts,
            )
        finally:
            os.close(allowed_fd)
        if root_fd is None:
            return None
        try:
            root_metadata = _validated_directory_metadata(root_fd, purpose="artifact root")
            instance = cls.__new__(cls)
        except Exception:
            os.close(root_fd)
            raise
        instance._bind_root(
            requested_root=requested_root,
            requested_allowed=requested_allowed,
            max_artifact_bytes=max_artifact_bytes,
            root_fd=root_fd,
            root_metadata=root_metadata,
        )
        return instance

    def _bind_root(
        self,
        *,
        requested_root: Path,
        requested_allowed: Path,
        max_artifact_bytes: int,
        root_fd: int,
        root_metadata: os.stat_result,
    ) -> None:
        self.root = requested_root
        self.allowed_root = requested_allowed
        self.max_artifact_bytes = max_artifact_bytes
        self._root_fd = root_fd
        self._root_identity = (root_metadata.st_dev, root_metadata.st_ino)
        self._root_lock = Lock()
        try:
            self._root_finalizer = weakref.finalize(self, _close_descriptor, root_fd)
        except Exception:
            os.close(root_fd)
            raise

    def verify_lexical_root_identity(self) -> None:
        """Require the current lexical root to name the pinned root without symlinks."""

        pinned = self._duplicate_root_fd()
        os.close(pinned)
        lexical_fd = _open_existing_absolute_directory(self.root)
        if lexical_fd is None:
            raise StudyArtifactError("lexical artifact root identity is missing")
        try:
            metadata = _validated_directory_metadata(
                lexical_fd,
                purpose="lexical artifact root",
            )
            if (metadata.st_dev, metadata.st_ino) != self._root_identity:
                raise StudyArtifactError("lexical artifact root identity changed")
        finally:
            os.close(lexical_fd)

    def inventory(self) -> tuple[StudyArtifactInventoryEntry, ...]:
        """Return a bounded, deterministic no-follow snapshot of the pinned root."""

        self.verify_lexical_root_identity()
        root_fd = self._duplicate_root_fd()
        entries: list[StudyArtifactInventoryEntry] = []
        try:
            _inventory_directory(
                root_fd,
                relative_parts=(),
                entries=entries,
            )
        except StudyArtifactError:
            raise
        except OSError as exc:
            raise StudyArtifactError(f"artifact inventory is unsafe or changed: {exc}") from exc
        finally:
            os.close(root_fd)
        self.verify_lexical_root_identity()
        return tuple(sorted(entries, key=lambda entry: os.fsencode(entry.path)))

    def close(self) -> None:
        """Close the pinned root descriptor; later operations fail closed."""

        with self._root_lock:
            self._root_finalizer()

    def publish_json(
        self,
        relative_path: str,
        document: Mapping[str, object],
    ) -> StudyArtifactRecord:
        finalized = finalize_study_record(document)
        validate_study_schema(finalized)
        payload = canonical_json_bytes(finalized)
        published = self.publish_bytes(
            relative_path,
            payload,
            media_type="application/json",
        )
        return StudyArtifactRecord(
            path=published.path,
            sha256=published.sha256,
            byte_size=published.byte_size,
            media_type=published.media_type,
            record_sha256=cast(str, finalized["record_sha256"]),
        )

    def publish_bytes(
        self,
        relative_path: str,
        payload: bytes,
        *,
        media_type: str,
    ) -> StudyArtifactRecord:
        normalized = _validate_relative_path(relative_path)
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if len(payload) > self.max_artifact_bytes:
            raise StudyArtifactError("artifact exceeds byte limit")
        if (
            not media_type
            or len(media_type) > 128
            or any(ord(character) < 32 or ord(character) == 127 for character in media_type)
        ):
            raise StudyArtifactError("artifact media type is invalid")

        directory_fd, name = self._prepare_parent_fd(normalized, create=True)
        temporary_name = f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor: int | None = None
        try:
            _reject_existing_target(directory_fd, name)
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            view = memoryview(payload)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise StudyArtifactError("artifact write did not make progress")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                _reject_existing_target(directory_fd, name)
                raise StudyArtifactError("artifact already exists and is immutable") from exc
            os.unlink(temporary_name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except StudyArtifactError:
            raise
        except OSError as exc:
            raise StudyArtifactError(f"artifact could not be published safely: {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
            os.close(directory_fd)

        return StudyArtifactRecord(
            path=normalized,
            sha256=sha256_bytes(payload),
            byte_size=len(payload),
            media_type=media_type,
            record_sha256=None,
        )

    def read_bytes(self, relative_path: str) -> bytes:
        normalized = _validate_relative_path(relative_path)
        directory_fd, name = self._prepare_parent_fd(normalized, create=False)
        descriptor: int | None = None
        try:
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise StudyArtifactError("artifact is missing") from exc
            if stat.S_ISLNK(before.st_mode):
                raise StudyArtifactError("artifact is a symlink")
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise StudyArtifactError("artifact is not a single-link regular file")
            if before.st_size > self.max_artifact_bytes:
                raise StudyArtifactError("artifact exceeds byte limit")
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            opened = os.fstat(descriptor)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise StudyArtifactError("artifact changed during validation")
            payload = _read_descriptor_bounded(
                descriptor,
                maximum=self.max_artifact_bytes,
            )
            after = os.fstat(descriptor)
            if (
                not stat.S_ISREG(after.st_mode)
                or after.st_nlink != 1
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
            ):
                raise StudyArtifactError("artifact changed during validation")
            return payload
        except StudyArtifactError:
            raise
        except OSError as exc:
            raise StudyArtifactError(f"artifact path is unsafe: {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)

    def verify_json(
        self,
        relative_path: str,
        *,
        expected_record_type: str,
    ) -> dict[str, object]:
        verified = self.verify_json_result(
            relative_path,
            expected_record_type=expected_record_type,
        )
        thawed = _thaw_json_value(verified.document)
        if not isinstance(thawed, dict):
            raise AssertionError("verified study JSON document must remain an object")
        return cast(dict[str, object], thawed)

    def verify_json_result(
        self,
        relative_path: str,
        *,
        expected_record_type: str,
    ) -> VerifiedStudyJson:
        """Verify one JSON artifact from one read and retain its immutable evidence."""

        payload = self.read_bytes(relative_path)
        document = load_strict_json_object(payload)
        try:
            canonical = canonical_json_bytes(document)
        except (TypeError, ValueError, OverflowError) as exc:
            raise StudyArtifactError("artifact JSON contains a non-finite value") from exc
        if canonical != payload:
            raise StudyArtifactError("artifact JSON bytes are not canonical")
        verify_self_hash(document)
        validate_study_schema(document)
        if document.get("record_type") != expected_record_type:
            raise StudyArtifactError("artifact record type does not match expectation")
        record_sha256 = cast(str, document["record_sha256"])
        frozen = _freeze_json_value(document)
        if not isinstance(frozen, Mapping):
            raise AssertionError("verified study JSON document must remain an object")
        return VerifiedStudyJson(
            document=cast(Mapping[str, object], frozen),
            raw_bytes=payload,
            raw_sha256=sha256_bytes(payload),
            record_sha256=record_sha256,
        )

    def _prepare_parent_fd(self, relative_path: str, *, create: bool) -> tuple[int, str]:
        pure = PurePosixPath(relative_path)
        current_fd = self._duplicate_root_fd()
        try:
            for part in pure.parts[:-1]:
                next_fd = _open_child_directory(current_fd, part, create=create)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd, pure.name
        except Exception:
            os.close(current_fd)
            raise

    def _duplicate_root_fd(self) -> int:
        with self._root_lock:
            if not self._root_finalizer.alive:
                raise StudyArtifactError("artifact store is closed")
            try:
                duplicate = os.dup(self._root_fd)
            except OSError as exc:
                raise StudyArtifactError("pinned artifact root is invalid") from exc
            if not self._root_finalizer.alive:
                os.close(duplicate)
                raise StudyArtifactError("artifact store is closed")
        try:
            metadata = _validated_directory_metadata(duplicate, purpose="pinned artifact root")
            if (metadata.st_dev, metadata.st_ino) != self._root_identity:
                raise StudyArtifactError("pinned artifact root identity changed")
        except Exception:
            os.close(duplicate)
            raise
        return duplicate


def _validate_phase_claim_semantics(document: Mapping[str, object]) -> None:
    if document.get("record_type") != "phase_execution_claim":
        return
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise StudyArtifactError("phase execution claim payload is invalid")
    modes = payload.get("expected_modes")
    mode_count = payload.get("expected_mode_count")
    if not isinstance(modes, list) or mode_count != len(modes):
        raise StudyArtifactError("phase execution claim mode count is invalid")
    if payload.get("phase") == "phase2":
        selected = tuple(cast(list[str], modes))
        protocol_ordered = tuple(mode for mode in _PHASE_1_MODES if mode in selected)
        if selected != protocol_ordered:
            raise StudyArtifactError("phase2 claim modes do not retain protocol order")


def _validate_result_semantics(document: Mapping[str, object]) -> None:
    record_type = document.get("record_type")
    if record_type not in _RESULT_RECORD_TYPES:
        return
    for field_name in ("artifact_schema_sha256", "implementation_projection_sha256"):
        if document.get(field_name) == _ZERO_SHA256:
            raise StudyArtifactError(f"{record_type} {field_name} must be a real hash")
    upstreams = cast(list[dict[str, object]], document["upstream_artifacts"])
    if any(
        upstream[hash_field] == _ZERO_SHA256
        for upstream in upstreams
        for hash_field in ("raw_sha256", "record_sha256")
    ):
        raise StudyArtifactError(f"{record_type} upstream hashes must be real")
    payload = cast(dict[str, object], document["payload"])
    if record_type == "scope_audit":
        _validate_scope_semantics(payload)
    elif record_type == "diagnostic_result":
        _validate_diagnostic_semantics(payload)
    elif record_type == "feature_oracle":
        _validate_oracle_semantics(payload)
    elif record_type == "development_result":
        _validate_development_semantics(payload)
    else:
        _validate_decision_semantics(payload, upstreams)


def _development_binding_projection() -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (f"e1-v2-development-{group}-{ordinal:03d}", seed_start + ordinal, group)
        for group, count, seed_start in (
            ("clean", 24, 400000),
            ("nuisance", 30, 410000),
            ("defect", 60, 420000),
            ("trust_boundary", 6, 430000),
        )
        for ordinal in range(count)
    )


def _validate_scope_semantics(payload: Mapping[str, object]) -> None:
    bindings = cast(list[dict[str, object]], payload["bindings"])
    actual = tuple(
        (cast(str, binding["case_id"]), cast(int, binding["seed"]), cast(str, binding["group"]))
        for binding in bindings
    )
    if actual != _development_binding_projection():
        raise StudyArtifactError("scope audit binding order or identity is invalid")


def _validate_applicable_gate_semantics(
    gate: Mapping[str, object],
    *,
    name: str,
    denominator: int,
    exclusions: int,
    operator: Literal["ge", "le"],
    threshold: float,
    expected_observed: float,
    ratio: bool,
    context: str,
) -> str:
    if (
        gate["name"] != name
        or gate["denominator"] != denominator
        or gate["exclusions"] != exclusions
        or gate["operator"] != operator
        or gate["threshold"] != threshold
        or gate["reason"] is not None
    ):
        raise StudyArtifactError(f"{context} gate contract is invalid")
    observed = gate["observed"]
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        raise StudyArtifactError(f"{context} gate observation is invalid")
    if observed != expected_observed:
        raise StudyArtifactError(f"{context} gate summary binding is invalid")
    numerator = gate["numerator"]
    if ratio:
        if type(numerator) is not int or not 0 <= numerator <= denominator:
            raise StudyArtifactError(f"{context} gate numerator is invalid")
        if observed != numerator / denominator:
            raise StudyArtifactError(f"{context} gate ratio is invalid")
    elif numerator is not None:
        raise StudyArtifactError(f"{context} statistic gate numerator is invalid")
    passed = observed >= threshold if operator == "ge" else observed <= threshold
    expected_status = "PASS" if passed else "FAIL"
    if gate["status"] != expected_status:
        raise StudyArtifactError(f"{context} gate status is invalid")
    return expected_status


def _validate_diagnostic_semantics(payload: Mapping[str, object]) -> None:
    cases = cast(list[dict[str, object]], payload["cases"])
    expected_cases = tuple(
        (f"e1-v2-development-diagnostic-{ordinal:03d}", 800000 + ordinal)
        for ordinal in range(108)
    )
    actual_cases = tuple(
        (cast(str, case["diagnostic_id"]), cast(int, case["seed"])) for case in cases
    )
    if actual_cases != expected_cases:
        raise StudyArtifactError("diagnostic case order or identity is invalid")

    observations = cast(list[dict[str, object]], payload["observations"])
    expected_observations = tuple(
        (diagnostic_id, seed, mode)
        for diagnostic_id, seed in expected_cases
        for mode in _PHASE_1_MODES
    )
    actual_observations = tuple(
        (
            cast(str, observation["diagnostic_id"]),
            cast(int, observation["seed"]),
            cast(str, observation["mode"]),
        )
        for observation in observations
    )
    if actual_observations != expected_observations:
        raise StudyArtifactError("diagnostic observation order or identity is invalid")

    by_case = {cast(str, case["diagnostic_id"]): case for case in cases}
    for observation in observations:
        diagnostic_id = cast(str, observation["diagnostic_id"])
        case = by_case[diagnostic_id]
        if observation["authoritative_mask_sha256"] != case["authoritative_mask_sha256"]:
            raise StudyArtifactError("diagnostic mask binding is invalid")
        inference = cast(dict[str, object], observation["inference_trace"])
        source_hashes = cast(dict[str, object], inference["source_hashes"])
        if (
            source_hashes["reference_sha256"] != case["reference_sha256"]
            or source_hashes["inspection_sha256"] != case["inspection_sha256"]
        ):
            raise StudyArtifactError("diagnostic inference source binding is invalid")
        if observation["outside_boundary_residual"] != (
            cast(int, observation["total_residual"])
            - cast(int, observation["boundary_residual"])
        ):
            raise StudyArtifactError("diagnostic residual trace is invalid")

    summaries = cast(list[dict[str, object]], payload["mode_summaries"])
    if tuple(summary["mode"] for summary in summaries) != _PHASE_1_MODES:
        raise StudyArtifactError("diagnostic mode-summary order is invalid")
    for summary in summaries:
        gates = cast(list[dict[str, object]], summary["gates"])
        statuses = (
            _validate_applicable_gate_semantics(
                gates[0],
                name="maximum_recall_drop",
                denominator=24,
                exclusions=84,
                operator="le",
                threshold=0.05,
                expected_observed=cast(float, summary["maximum_recall_drop"]),
                ratio=False,
                context="diagnostic maximum-recall-drop",
            ),
            _validate_applicable_gate_semantics(
                gates[1],
                name="median_dice_drop",
                denominator=24,
                exclusions=84,
                operator="le",
                threshold=0.01,
                expected_observed=cast(float, summary["median_dice_drop"]),
                ratio=False,
                context="diagnostic median-dice-drop",
            ),
            _validate_applicable_gate_semantics(
                gates[2],
                name="medium_high_classification_recall",
                denominator=24,
                exclusions=84,
                operator="ge",
                threshold=0.9,
                expected_observed=cast(float, summary["medium_high_classification_recall"]),
                ratio=True,
                context="diagnostic classification-recall",
            ),
        )
        if summary["eligible"] is not all(status == "PASS" for status in statuses):
            raise StudyArtifactError("diagnostic eligible declaration is invalid")
    eligible_modes = tuple(cast(list[str], payload["eligible_modes"]))
    derived_modes = tuple(
        cast(str, summary["mode"]) for summary in summaries if summary["eligible"] is True
    )
    if eligible_modes != derived_modes:
        raise StudyArtifactError("diagnostic eligible-mode declaration is invalid")


def _validate_oracle_semantics(payload: Mapping[str, object]) -> None:
    records = cast(list[dict[str, object]], payload["records"])
    expected = tuple(
        (f"e1-v2-development-defect-{ordinal:03d}", 420000 + ordinal)
        for ordinal in range(60)
    )
    actual = tuple(
        (cast(str, record["case_id"]), cast(int, record["seed"])) for record in records
    )
    if actual != expected:
        raise StudyArtifactError("feature oracle record order or identity is invalid")
    ownership_hashes = cast(dict[str, str], payload["ownership_hashes"])
    allowed_ownership_hashes = frozenset(ownership_hashes.values())
    minimum_winner_pixels = cast(int, payload["minimum_winner_pixels"])
    for record in records:
        status = cast(str, record["status"])
        expected_feature = cast(str, record["expected_feature_id"])
        predicted_feature = record["predicted_feature_id"]
        if status not in {"MAPPED", "UNMAPPED", "AMBIGUOUS"}:
            raise StudyArtifactError("feature oracle status is invalid")
        if expected_feature not in _FEATURE_IDS or (
            predicted_feature is not None and predicted_feature not in _FEATURE_IDS
        ):
            raise StudyArtifactError("feature oracle feature ID is invalid")
        if (status == "MAPPED") is (predicted_feature is None):
            raise StudyArtifactError("feature oracle status/prediction binding is invalid")
        target_owned = cast(int, record["target_owned_pixels"])
        owned = cast(int, record["owned_pixel_count"])
        authoritative = cast(int, record["authoritative_positive_pixels"])
        unmapped = cast(int, record["unmapped_pixel_count"])
        if status == "UNMAPPED" and target_owned >= minimum_winner_pixels:
            raise StudyArtifactError("feature oracle UNMAPPED winner count is invalid")
        if not 0 <= target_owned <= owned <= authoritative:
            raise StudyArtifactError("feature oracle ownership counts are invalid")
        conserved = owned + unmapped == authoritative
        if record["conserved"] is not conserved:
            raise StudyArtifactError("feature oracle conservation declaration is invalid")
        if record["ownership_map_sha256"] not in allowed_ownership_hashes:
            raise StudyArtifactError("feature oracle ownership hash is invalid")
        expected_correct = (
            status == "MAPPED"
            and predicted_feature == expected_feature
            and target_owned >= minimum_winner_pixels
            and conserved
            and record["hash_binding_matches"] is True
        )
        if record["correct"] is not expected_correct:
            raise StudyArtifactError("feature oracle correct-case declaration is invalid")

    correct = sum(record["correct"] is True for record in records)
    ambiguous = sum(record["status"] == "AMBIGUOUS" for record in records)
    null = sum(record["status"] == "UNMAPPED" for record in records)
    wrong = sum(record["status"] == "MAPPED" and record["correct"] is False for record in records)
    declared = (
        payload["correct_cases"],
        payload["ambiguous_cases"],
        payload["null_cases"],
        payload["wrong_cases"],
    )
    if declared != (correct, ambiguous, null, wrong):
        raise StudyArtifactError("feature oracle totals are invalid")
    expected_passed = correct == 60 and ambiguous == 0 and null == 0 and wrong == 0
    if payload["passed"] is not expected_passed:
        raise StudyArtifactError("feature oracle pass declaration is invalid")


def _validate_development_semantics(payload: Mapping[str, object]) -> None:
    bindings = cast(list[dict[str, object]], payload["bindings"])
    expected_projection = _development_binding_projection()
    actual_projection = tuple(
        (cast(str, item["case_id"]), cast(int, item["seed"]), cast(str, item["group"]))
        for item in bindings
    )
    if actual_projection != expected_projection:
        raise StudyArtifactError("development binding order or identity is invalid")
    modes = tuple(cast(list[str], payload["eligible_modes"]))
    if modes != tuple(mode for mode in _PHASE_1_MODES if mode in modes):
        raise StudyArtifactError("development eligible-mode order is invalid")

    inference_bindings = bindings[:114]
    expected_inference = tuple(
        (
            cast(str, binding["case_id"]),
            cast(int, binding["seed"]),
            cast(str, binding["group"]),
            mode,
            cast(str, binding["case_binding_sha256"]),
        )
        for mode in modes
        for binding in inference_bindings
    )
    inference_records = cast(list[dict[str, object]], payload["inference_records"])
    actual_inference = tuple(
        (
            cast(str, record["case_id"]),
            cast(int, record["seed"]),
            cast(str, record["group"]),
            cast(str, record["mode"]),
            cast(str, record["case_binding_sha256"]),
        )
        for record in inference_records
    )
    if actual_inference != expected_inference:
        raise StudyArtifactError("development inference order or count is invalid")
    binding_by_id = {cast(str, binding["case_id"]): binding for binding in bindings}
    for record in inference_records:
        binding = binding_by_id[cast(str, record["case_id"])]
        inference = cast(dict[str, object], record["inference_trace"])
        hashes = cast(dict[str, object], inference["source_hashes"])
        if (
            hashes["reference_sha256"] != binding["reference_sha256"]
            or hashes["inspection_sha256"] != binding["inspection_sha256"]
        ):
            raise StudyArtifactError("development inference source binding is invalid")

    trust_records = cast(list[dict[str, object]], payload["trust_bindings"])
    expected_trust = tuple(
        (
            cast(str, binding["case_id"]),
            cast(int, binding["seed"]),
            cast(str, binding["case_binding_sha256"]),
        )
        for binding in bindings[114:]
    )
    actual_trust = tuple(
        (
            cast(str, record["case_id"]),
            cast(int, record["seed"]),
            cast(str, record["case_binding_sha256"]),
        )
        for record in trust_records
    )
    if actual_trust != expected_trust:
        raise StudyArtifactError("development trust-binding order is invalid")

    summaries = cast(list[dict[str, object]], payload["mode_summaries"])
    if tuple(summary["mode"] for summary in summaries) != modes:
        raise StudyArtifactError("development mode-summary order is invalid")
    for summary in summaries:
        gates = cast(list[dict[str, object]], summary["gates"])
        statuses = (
            _validate_applicable_gate_semantics(
                gates[0],
                name="medium_high_defect_recall",
                denominator=40,
                exclusions=74,
                operator="ge",
                threshold=0.9,
                expected_observed=cast(float, summary["medium_high_recall"]),
                ratio=True,
                context="development defect-recall",
            ),
            _validate_applicable_gate_semantics(
                gates[1],
                name="nuisance_only_false_positive_rate",
                denominator=30,
                exclusions=84,
                operator="le",
                threshold=0.05,
                expected_observed=cast(float, summary["nuisance_false_positive_rate"]),
                ratio=True,
                context="development nuisance-false-positive-rate",
            ),
            _validate_applicable_gate_semantics(
                gates[2],
                name="positive_case_median_dice",
                denominator=60,
                exclusions=54,
                operator="ge",
                threshold=0.7,
                expected_observed=cast(float, summary["positive_median_dice"]),
                ratio=False,
                context="development positive-median-dice",
            ),
            _validate_applicable_gate_semantics(
                gates[3],
                name="affected_feature_mapping_accuracy",
                denominator=60,
                exclusions=54,
                operator="ge",
                threshold=0.95,
                expected_observed=cast(float, summary["feature_mapping_accuracy"]),
                ratio=True,
                context="development feature-mapping-accuracy",
            ),
        )
        if summary["passed_all_gates"] is not all(status == "PASS" for status in statuses):
            raise StudyArtifactError("development passing declaration is invalid")
    passing_modes = tuple(cast(list[str], payload["passing_modes"]))
    derived_passing = tuple(
        cast(str, summary["mode"])
        for summary in summaries
        if summary["passed_all_gates"] is True
    )
    if passing_modes != derived_passing:
        raise StudyArtifactError("development passing-mode declaration is invalid")


def _validate_decision_semantics(
    payload: Mapping[str, object],
    upstreams: list[dict[str, object]],
) -> None:
    present = tuple(cast(list[str], payload["present_paths"]))
    invalid = tuple(cast(list[str], payload["invalid_paths"]))
    if present != tuple(path for path in _PRE_DECISION_PATHS if path in present):
        raise StudyArtifactError("decision present-path inventory order is invalid")
    if invalid != tuple(path for path in _PRE_DECISION_PATHS if path in invalid):
        raise StudyArtifactError("decision invalid-path inventory order is invalid")
    if any(path not in present for path in invalid):
        raise StudyArtifactError("decision invalid path is not present")
    verified_paths = tuple(path for path in present if path not in invalid)
    if payload["present_artifact_count"] != len(present):
        raise StudyArtifactError("decision present-artifact count is invalid")
    if payload["verified_artifact_count"] != len(verified_paths):
        raise StudyArtifactError("decision verified-artifact count is invalid")
    expected_rate = len(verified_paths) / len(present) if present else 0.0
    if payload["study_artifact_verify_rate"] != expected_rate:
        raise StudyArtifactError("decision artifact verification rate is invalid")
    upstream_paths = tuple(cast(str, upstream["path"]) for upstream in upstreams)
    if upstream_paths != verified_paths:
        raise StudyArtifactError("decision upstream inventory is invalid")
    decision = cast(str, payload["decision"])
    reasons = tuple(cast(list[str], payload["reasons"]))
    if decision == "STUDY_INVALID":
        if reasons != ("ARTIFACT_VERIFICATION_FAILED",):
            raise StudyArtifactError("invalid-study decision reason is invalid")
        return
    expected_present, expected_reason = _PERFORMANCE_DECISION_BRANCHES[decision]
    if present != expected_present or invalid:
        raise StudyArtifactError("performance decision inventory is invalid")
    if reasons != (expected_reason,):
        raise StudyArtifactError("performance decision reason is invalid")


def _require_finite_json_value(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON value")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _require_finite_json_value(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _require_finite_json_value(item)


def _read_descriptor_bounded(descriptor: int, *, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > maximum:
        raise StudyArtifactError("input exceeds byte limit")
    return payload


def _inventory_metadata_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _inventory_directory_names(descriptor: int) -> tuple[str, ...]:
    names: list[str] = []
    try:
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                name = entry.name
                if not isinstance(name, str) or len(os.fsencode(name)) > _MAX_DIRECTORY_NAME_BYTES:
                    raise StudyArtifactError("artifact inventory directory name is unsafe")
                names.append(name)
                if len(names) > _MAX_INVENTORY_ENTRIES:
                    raise StudyArtifactError("artifact inventory entry limit exceeded")
    except StudyArtifactError:
        raise
    except OSError as exc:
        raise StudyArtifactError(f"artifact inventory directory is unsafe: {exc}") from exc
    return tuple(names)


def _inventory_kind(mode: int) -> Literal["file", "directory", "symlink", "other"]:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def _inventory_directory(
    directory_fd: int,
    *,
    relative_parts: tuple[str, ...],
    entries: list[StudyArtifactInventoryEntry],
) -> None:
    before = _validated_directory_metadata(directory_fd, purpose="artifact inventory directory")
    before_snapshot = _inventory_metadata_snapshot(before)
    for name in _inventory_directory_names(directory_fd):
        relative = PurePosixPath(*relative_parts, name)
        normalized = _validate_relative_path(relative.as_posix())
        parts = PurePosixPath(normalized).parts
        if len(parts) > _MAX_INVENTORY_DEPTH:
            raise StudyArtifactError("artifact inventory depth limit exceeded")
        try:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise StudyArtifactError("artifact inventory changed during traversal") from exc
        kind = _inventory_kind(metadata.st_mode)
        entries.append(
            StudyArtifactInventoryEntry(
                path=normalized,
                kind=kind,
                byte_size=metadata.st_size,
                link_count=metadata.st_nlink,
            )
        )
        if len(entries) > _MAX_INVENTORY_ENTRIES:
            raise StudyArtifactError("artifact inventory entry limit exceeded")
        if kind != "directory":
            continue
        child_fd: int | None = None
        try:
            child_fd = os.open(name, _directory_open_flags(), dir_fd=directory_fd)
            opened = _validated_directory_metadata(
                child_fd,
                purpose="artifact inventory child directory",
            )
            if (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino):
                raise StudyArtifactError("artifact inventory changed during traversal")
            _inventory_directory(
                child_fd,
                relative_parts=parts,
                entries=entries,
            )
        except StudyArtifactError:
            raise
        except OSError as exc:
            raise StudyArtifactError("artifact inventory changed during traversal") from exc
        finally:
            if child_fd is not None:
                os.close(child_fd)
    after = _validated_directory_metadata(directory_fd, purpose="artifact inventory directory")
    if _inventory_metadata_snapshot(after) != before_snapshot:
        raise StudyArtifactError("artifact inventory directory changed during traversal")


def _validate_relative_path(path: str) -> str:
    if (
        not isinstance(path, str)
        or not path
        or len(path) > 240
        or "\\" in path
        or "\x00" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        raise StudyArtifactError("artifact path is unsafe")
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or pure.as_posix() != path
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise StudyArtifactError("artifact path is unsafe")
    return pure.as_posix()


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _open_existing_absolute_directory(path: Path) -> int | None:
    if not path.is_absolute():
        raise StudyArtifactError("artifact root must be absolute")
    try:
        anchor_fd = os.open(path.anchor, _directory_open_flags())
    except OSError as exc:
        raise StudyArtifactError("artifact root anchor is unsafe") from exc
    try:
        return _traverse_existing_directory_fd(anchor_fd, path.parts[1:])
    finally:
        os.close(anchor_fd)


def _open_or_create_absolute_directory(path: Path) -> int:
    if not path.is_absolute():
        raise StudyArtifactError("artifact root must be absolute")
    try:
        anchor_fd = os.open(path.anchor, _directory_open_flags())
    except OSError as exc:
        raise StudyArtifactError("artifact root anchor is unsafe") from exc
    try:
        return _traverse_directory_fd(anchor_fd, path.parts[1:], create=True)
    finally:
        os.close(anchor_fd)


def _traverse_existing_directory_fd(
    starting_fd: int,
    parts: tuple[str, ...],
) -> int | None:
    try:
        current_fd = os.dup(starting_fd)
    except OSError as exc:
        raise StudyArtifactError("artifact directory descriptor is invalid") from exc
    try:
        _validated_directory_metadata(current_fd, purpose="artifact directory")
        for part in parts:
            next_fd = _open_existing_child_directory(current_fd, part)
            if next_fd is None:
                os.close(current_fd)
                return None
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _traverse_directory_fd(
    starting_fd: int,
    parts: tuple[str, ...],
    *,
    create: bool,
) -> int:
    try:
        current_fd = os.dup(starting_fd)
    except OSError as exc:
        raise StudyArtifactError("artifact directory descriptor is invalid") from exc
    try:
        _validated_directory_metadata(current_fd, purpose="artifact directory")
        for part in parts:
            next_fd = _open_child_directory(current_fd, part, create=create)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_existing_child_directory(parent_fd: int, name: str) -> int | None:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise StudyArtifactError("artifact directory component is unsafe")
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StudyArtifactError(
            "artifact directory component is unsafe or a symlink"
        ) from exc
    try:
        _validated_directory_metadata(descriptor, purpose="artifact directory component")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _open_child_directory(parent_fd: int, name: str, *, create: bool) -> int:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise StudyArtifactError("artifact directory component is unsafe")
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise StudyArtifactError("artifact parent is missing") from None
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise StudyArtifactError("artifact parent cannot be created safely") from exc
        try:
            descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
        except OSError as exc:
            raise StudyArtifactError("artifact directory component is unsafe or a symlink") from exc
    except OSError as exc:
        raise StudyArtifactError("artifact directory component is unsafe or a symlink") from exc
    try:
        _validated_directory_metadata(descriptor, purpose="artifact directory component")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _validated_directory_metadata(descriptor: int, *, purpose: str) -> os.stat_result:
    try:
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise StudyArtifactError(f"{purpose} descriptor is invalid") from exc
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_nlink < 1:
        raise StudyArtifactError(f"{purpose} is invalid")
    return metadata


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _close_descriptor(descriptor: int) -> None:
    with suppress(OSError):
        os.close(descriptor)


def _reject_existing_target(directory_fd: int, name: str) -> None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise StudyArtifactError("artifact destination is a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise StudyArtifactError("artifact destination is not a regular file")
    raise StudyArtifactError("artifact already exists and is immutable")


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _freeze_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    return value


def _thaw_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value
