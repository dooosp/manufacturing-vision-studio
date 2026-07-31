"""Bounded optional dataset and read-only FreeCAD export adapters."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import (
    EvidenceError,
    IdentityMismatchError,
    UnsafeInputError,
)
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.registry import CaseRegistry
from manufacturing_vision_studio.schema_validation import validate_document

MVTEC_LICENSE_ID = "CC-BY-NC-SA-4.0"
MVTEC_LIMITATION = "MVTec AD is optional non-commercial benchmark data and is never bundled."


@dataclass(frozen=True, slots=True)
class MVTecSample:
    category: str
    split: str
    defect_type: str
    image_relative_path: str
    image_sha256: str
    mask_relative_path: str | None
    mask_sha256: str | None


@dataclass(frozen=True, slots=True)
class MVTecSummary:
    dataset_id: str
    category: str
    split: str
    sample_count: int
    dataset_sha256: str
    license_id: str
    limitations: tuple[str, ...]
    samples: tuple[MVTecSample, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "category": self.category,
            "split": self.split,
            "sample_count": self.sample_count,
            "dataset_sha256": self.dataset_sha256,
            "license_id": self.license_id,
            "limitations": list(self.limitations),
            "samples": [
                {
                    "category": sample.category,
                    "split": sample.split,
                    "defect_type": sample.defect_type,
                    "image_relative_path": sample.image_relative_path,
                    "image_sha256": sample.image_sha256,
                    "mask_relative_path": sample.mask_relative_path,
                    "mask_sha256": sample.mask_sha256,
                }
                for sample in self.samples
            ],
        }


class MVTecADAdapter:
    """Read a caller-obtained MVTec AD directory without downloading or copying it."""

    def __init__(
        self,
        dataset_root: Path,
        *,
        noncommercial_license_acknowledged: bool,
        settings: Settings | None = None,
    ) -> None:
        if not noncommercial_license_acknowledged:
            raise UnsafeInputError(
                "The MVTec AD non-commercial license acknowledgement is required",
                code="SCHEMA_INVALID",
            )
        self.root = _pin_read_only_root(dataset_root)
        self.settings = settings or Settings.from_env()
        self.ingestor = ImageIngestor(self.settings)

    def scan(
        self,
        category: str,
        *,
        split: str = "test",
        max_samples: int = 1000,
    ) -> MVTecSummary:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", category):
            raise UnsafeInputError("MVTec category is malformed", code="SCHEMA_INVALID")
        if split not in {"train", "test"}:
            raise UnsafeInputError("MVTec split must be train or test", code="SCHEMA_INVALID")
        if not 1 <= max_samples <= 10_000:
            raise UnsafeInputError("MVTec sample limit is invalid", code="SCHEMA_INVALID")
        split_root = _safe_existing_directory(self.root, PurePosixPath(category) / split)
        candidates = sorted(
            path for path in split_root.glob("*/*.png") if path.is_file() and not path.is_symlink()
        )
        if not candidates:
            raise EvidenceError(
                "MVTec category contains no PNG samples", code="EVIDENCE_INCOMPLETE"
            )
        if len(candidates) > max_samples:
            raise EvidenceError("MVTec sample count exceeds limit", code="INPUT_TOO_LARGE")

        samples: list[MVTecSample] = []
        for image_path in candidates:
            _assert_no_symlink_components(self.root, image_path)
            relative = image_path.relative_to(self.root).as_posix()
            ingested = self.ingestor.ingest_path(image_path, allowed_root=self.root)
            defect_type = image_path.parent.name
            mask_relative: str | None = None
            mask_sha256: str | None = None
            if split == "test" and defect_type != "good":
                mask_candidate = (
                    self.root
                    / category
                    / "ground_truth"
                    / defect_type
                    / f"{image_path.stem}_mask.png"
                )
                _assert_no_symlink_components(self.root, mask_candidate)
                if not mask_candidate.is_file():
                    raise EvidenceError(
                        "MVTec defect sample is missing its mask",
                        code="EVIDENCE_INCOMPLETE",
                    )
                mask = self.ingestor.ingest_path(mask_candidate, allowed_root=self.root)
                mask_relative = mask_candidate.relative_to(self.root).as_posix()
                mask_sha256 = mask.original_sha256
            samples.append(
                MVTecSample(
                    category=category,
                    split=split,
                    defect_type=defect_type,
                    image_relative_path=relative,
                    image_sha256=ingested.original_sha256,
                    mask_relative_path=mask_relative,
                    mask_sha256=mask_sha256,
                )
            )
        fingerprint_projection = [
            {
                "image_relative_path": sample.image_relative_path,
                "image_sha256": sample.image_sha256,
                "mask_relative_path": sample.mask_relative_path,
                "mask_sha256": sample.mask_sha256,
            }
            for sample in samples
        ]
        return MVTecSummary(
            dataset_id=f"mvtec-ad-{category}",
            category=category,
            split=split,
            sample_count=len(samples),
            dataset_sha256=sha256_bytes(canonical_json_bytes(fingerprint_projection)),
            license_id=MVTEC_LICENSE_ID,
            limitations=(MVTEC_LIMITATION,),
            samples=tuple(samples),
        )


@dataclass(frozen=True, slots=True)
class ValidatedFreeCADExport:
    manifest: dict[str, Any]
    manifest_sha256: str
    artifacts: dict[str, bytes]

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": True,
            "export_id": self.manifest["export_id"],
            "part_identity": self.manifest["part_identity"],
            "manifest_sha256": self.manifest_sha256,
            "artifact_count": len(self.artifacts),
            "limitations": self.manifest["limitations"],
        }


class FreeCADExportAdapter:
    """Validate inert FreeCAD Automation exports without executing or writing upstream."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def validate(
        self,
        source_root: Path,
        *,
        manifest_relative_path: str = "freecad-export-adapter-manifest.json",
        expected_part_id: str | None = None,
        expected_cad_revision: str | None = None,
    ) -> ValidatedFreeCADExport:
        root = _pin_read_only_root(source_root)
        manifest_path = _safe_regular_file(root, manifest_relative_path)
        manifest_bytes = _bounded_regular_read(manifest_path, self.settings.max_bundle_member_bytes)
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceError("FreeCAD manifest is malformed", code="SCHEMA_INVALID") from exc
        if not isinstance(manifest, dict):
            raise EvidenceError("FreeCAD manifest must be an object", code="SCHEMA_INVALID")
        document = cast(dict[str, Any], manifest)
        validate_document(document, "freecad-export-adapter-manifest")
        identity = cast(dict[str, str], document["part_identity"])
        if expected_part_id is not None and identity["part_id"] != expected_part_id:
            raise IdentityMismatchError(
                "FreeCAD part identity does not match", code="PART_ID_MISMATCH"
            )
        if expected_cad_revision is not None and identity["cad_revision"] != expected_cad_revision:
            raise IdentityMismatchError(
                "FreeCAD CAD revision does not match", code="REVISION_MISMATCH"
            )

        artifacts: dict[str, bytes] = {}
        seen: set[str] = set()
        for entry in cast(list[dict[str, Any]], document["artifacts"]):
            relative_path = cast(str, entry["relative_path"])
            if relative_path in seen:
                raise EvidenceError(
                    "FreeCAD artifact path is duplicated", code="DUPLICATE_ARTIFACT_PATH"
                )
            seen.add(relative_path)
            path = _safe_regular_file(root, relative_path)
            data = _bounded_regular_read(path, self.settings.max_bundle_member_bytes)
            if len(data) != entry["byte_size"] or sha256_bytes(data) != entry["sha256"]:
                raise EvidenceError("FreeCAD artifact hash does not match", code="HASH_MISMATCH")
            if entry["media_type"] == "image/png":
                ImageIngestor(self.settings).ingest_bytes(
                    data,
                    filename=path.name,
                    declared_media_type="image/png",
                )
            else:
                try:
                    parsed = json.loads(data)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise EvidenceError(
                        "FreeCAD JSON artifact is malformed",
                        code="SCHEMA_INVALID",
                    ) from exc
                if not isinstance(parsed, (dict, list)):
                    raise EvidenceError(
                        "FreeCAD JSON artifact must be structured",
                        code="SCHEMA_INVALID",
                    )
            artifacts[relative_path] = data
        return ValidatedFreeCADExport(
            manifest=document,
            manifest_sha256=sha256_bytes(manifest_bytes),
            artifacts=artifacts,
        )

    def import_reference(
        self,
        registry: CaseRegistry,
        case_id: str,
        source_root: Path,
        *,
        expected_case_revision: int,
        manifest_relative_path: str = "freecad-export-adapter-manifest.json",
    ) -> dict[str, Any]:
        case_document = registry.get_case_document(case_id)
        identity = cast(dict[str, str], case_document["part_identity"])
        validated = self.validate(
            source_root,
            manifest_relative_path=manifest_relative_path,
            expected_part_id=identity["part_id"],
            expected_cad_revision=identity["cad_revision"],
        )
        render_entries = [
            entry
            for entry in cast(list[dict[str, Any]], validated.manifest["artifacts"])
            if entry["role"] == "reference_render"
        ]
        if len(render_entries) != 1:
            raise EvidenceError(
                "FreeCAD import requires exactly one reference render",
                code="EVIDENCE_INCOMPLETE",
            )
        render = render_entries[0]
        data = validated.artifacts[cast(str, render["relative_path"])]
        image = ImageIngestor(self.settings).ingest_bytes(
            data,
            filename=Path(cast(str, render["relative_path"])).name,
            declared_media_type="image/png",
        )
        registry.add_reference(
            case_id,
            image,
            source_kind="freecad_export",
            freecad_export_id=cast(str, validated.manifest["export_id"]),
            expected_case_revision=expected_case_revision,
        )
        return registry.get_case_detail(case_id)


def _pin_read_only_root(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UnsafeInputError(
            "Selected input root is unavailable", code="NON_REGULAR_INPUT"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise UnsafeInputError("Selected input root must not be a symlink", code="SYMLINK_INPUT")
    if not stat.S_ISDIR(metadata.st_mode):
        raise UnsafeInputError("Selected input root must be a directory", code="NON_REGULAR_INPUT")
    return path.resolve()


def _safe_existing_directory(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    _assert_no_symlink_components(root, candidate)
    if not candidate.is_dir():
        raise EvidenceError("Expected dataset directory is missing", code="EVIDENCE_INCOMPLETE")
    return candidate


def _safe_regular_file(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if (
        not relative_path
        or pure.is_absolute()
        or "\\" in relative_path
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise UnsafeInputError("Input artifact path is unsafe", code="UNSAFE_PATH")
    candidate = root.joinpath(*pure.parts)
    _assert_no_symlink_components(root, candidate)
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise EvidenceError("Input artifact is missing", code="EVIDENCE_INCOMPLETE") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise UnsafeInputError("Input artifact must not be a symlink", code="SYMLINK_INPUT")
    if not stat.S_ISREG(metadata.st_mode):
        raise UnsafeInputError("Input artifact must be a regular file", code="NON_REGULAR_INPUT")
    return candidate


def _assert_no_symlink_components(root: Path, candidate: Path) -> None:
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeInputError("Input path escapes selected root", code="UNSAFE_PATH") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeInputError("Input path contains a symlink", code="SYMLINK_INPUT")


def _bounded_regular_read(path: Path, limit: int) -> bytes:
    metadata = path.lstat()
    if metadata.st_size > limit:
        raise UnsafeInputError("Input artifact exceeds byte limit", code="INPUT_TOO_LARGE")
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise UnsafeInputError("Input artifact changed during validation", code="SYMLINK_INPUT")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except UnsafeInputError:
        raise
    except OSError as exc:
        raise UnsafeInputError(
            "Input artifact changed during validation", code="SYMLINK_INPUT"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(data) > limit:
        raise UnsafeInputError("Input artifact exceeds byte limit", code="INPUT_TOO_LARGE")
    if len(data) != metadata.st_size:
        raise UnsafeInputError("Input artifact changed during validation", code="HASH_MISMATCH")
    return data
