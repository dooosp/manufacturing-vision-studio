"""Canonical, immutable artifact controls for the development-only E1 study."""

from __future__ import annotations

import json
import math
import os
import stat
import uuid
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
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
_SHA1_LENGTH = 40
_SHA256_LENGTH = 64
_ZERO_SHA256 = "0" * _SHA256_LENGTH
_STUDY_ID = "e1-feasibility-separability"
_PHASE_1_MODES = ("NEAREST", "BILINEAR", "BICUBIC")


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
        _ensure_directory_without_symlinks(requested_allowed)
        _ensure_directory_without_symlinks(requested_root)
        self.root = requested_root.resolve(strict=True)
        self.allowed_root = requested_allowed.resolve(strict=True)
        if not self.root.is_relative_to(self.allowed_root):
            raise StudyArtifactError("artifact root escapes allowed root")
        self.max_artifact_bytes = max_artifact_bytes

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

        parent, name = self._prepare_parent(normalized, create=True)
        directory_fd = _open_directory(parent)
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
        parent, name = self._prepare_parent(normalized, create=False)
        directory_fd = _open_directory(parent)
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
        return cast(dict[str, object], document)

    def _prepare_parent(self, relative_path: str, *, create: bool) -> tuple[Path, str]:
        pure = PurePosixPath(relative_path)
        current = self.root
        for part in pure.parts[:-1]:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                if not create:
                    raise StudyArtifactError("artifact parent is missing") from None
                try:
                    current.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise StudyArtifactError("artifact parent cannot be created safely") from exc
                metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise StudyArtifactError("artifact path contains a symlink")
            if not stat.S_ISDIR(metadata.st_mode):
                raise StudyArtifactError("artifact parent is not a directory")
            try:
                resolved = current.resolve(strict=True)
            except OSError as exc:
                raise StudyArtifactError("artifact parent cannot be resolved safely") from exc
            if not resolved.is_relative_to(self.root):
                raise StudyArtifactError("artifact path escapes root")
        return current, pure.name


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


def _ensure_directory_without_symlinks(path: Path) -> None:
    if not path.is_absolute():
        raise StudyArtifactError("artifact root must be absolute")
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
                raise StudyArtifactError("artifact root cannot be created safely") from exc
            metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise StudyArtifactError("artifact root contains a symlink")
        if not stat.S_ISDIR(metadata.st_mode):
            raise StudyArtifactError("artifact root parent is not a directory")


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StudyArtifactError("artifact directory is unsafe or a symlink") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise StudyArtifactError("artifact parent is not a directory")
    return descriptor


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
