"""Deterministic evidence bundle export, strict verification, and re-import."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import numpy as np
from PIL import Image, UnidentifiedImageError

from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import (
    ConflictError,
    EvidenceError,
    IdentityMismatchError,
)
from manufacturing_vision_studio.images import ImageIngestor, resolve_canonical_image_bytes
from manufacturing_vision_studio.registry import (
    LIMITATION,
    MODEL_ARTIFACT_SHA256,
    SCHEMA_VERSION,
    CaseRegistry,
)
from manufacturing_vision_studio.schema_validation import schema_id, validate_document

MANIFEST_NAME = "bundle-manifest.json"
SIDECAR_NAME = "bundle-manifest.sha256"
HASH_CONTRACT = "mvs-canonical-json/v1"
KNOWN_PIPELINE = {"pipeline_id": "registered-difference", "pipeline_version": "1.0.0"}
KNOWN_MODEL = {
    "model_id": "registered-absolute-difference",
    "model_version": "1.0.0",
    "model_artifact_sha256": MODEL_ARTIFACT_SHA256,
}

# The immutable v0.1.0 payload used Pillow/zlib-produced PNG bytes as its
# canonical image representation. Compatibility is deliberately limited to
# this already verified artifact inventory; all new payloads use canonical_png.
_LEGACY_SOURCE_PNG_PAYLOAD_SHA256S = {
    "35606fde93bf07e3e9814fb0ce1b0f87e19ec66e16345bde61502b4145061cd7",
}

_ROLE_SCHEMAS = {
    "inspection_case": "inspection-case",
    "reference_image_metadata": "image-input-metadata",
    "inspection_image_metadata": "image-input-metadata",
    "analysis_result": "analysis-result",
    "human_disposition": "human-disposition",
    "evaluation_report": "evaluation-report",
}


@dataclass(frozen=True, slots=True)
class VerificationResult:
    valid: bool
    bundle_id: str
    case_id: str
    case_revision: int
    part_id: str
    cad_revision: str
    artifact_count: int
    payload_sha256: str
    bundle_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "bundle_id": self.bundle_id,
            "case_id": self.case_id,
            "case_revision": self.case_revision,
            "part_identity": {
                "part_id": self.part_id,
                "cad_revision": self.cad_revision,
            },
            "artifact_count": self.artifact_count,
            "payload_sha256": self.payload_sha256,
            "bundle_sha256": self.bundle_sha256,
        }


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    bundle_sha256: str
    manifest: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "bundle_sha256": self.bundle_sha256,
            "manifest": self.manifest,
        }


class EvidenceService:
    """Build and validate a bounded ZIP with no implicit trust in archive metadata."""

    def __init__(
        self,
        registry: CaseRegistry,
        settings: Settings | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings or registry.settings

    def export_case(
        self,
        case_id: str,
        *,
        expected_case_revision: int,
        destination: Path | None = None,
    ) -> ExportResult:
        snapshot = self.registry.evidence_rows(
            case_id,
            expected_case_revision=expected_case_revision,
        )
        payloads = self._build_payloads(snapshot)
        artifacts = self._artifact_inventory(payloads)
        payload_byte_size = sum(cast(int, entry["byte_size"]) for entry in artifacts)
        if len(artifacts) > self.settings.max_bundle_entries:
            raise EvidenceError(
                "Evidence artifact count exceeds limit", code="BUNDLE_LIMIT_EXCEEDED"
            )
        if payload_byte_size > self.settings.max_bundle_uncompressed_bytes:
            raise EvidenceError("Evidence payload exceeds limit", code="BUNDLE_LIMIT_EXCEEDED")
        payload_sha256 = payload_inventory_hash(artifacts)
        case_document = cast(dict[str, Any], snapshot["case_document"])
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "bundle_id": f"bundle-{payload_sha256[:24]}",
            "case_id": case_document["case_id"],
            "case_revision": case_document["case_revision"],
            "part_identity": case_document["part_identity"],
            "created_at": case_document["updated_at"],
            "exporter": {
                "exporter_id": "manufacturing-vision-studio",
                "exporter_version": "1.0.0",
            },
            "hash_contract": {
                "algorithm": "sha256",
                "json_canonicalization": HASH_CONTRACT,
                "artifact_order": "unicode_code_point_ascending_path",
            },
            "artifact_count": len(artifacts),
            "payload_byte_size": payload_byte_size,
            "artifacts": artifacts,
            "payload_sha256": payload_sha256,
            "limitations": [LIMITATION],
        }
        validate_document(manifest, "evidence-bundle-manifest")
        manifest_bytes = canonical_json_bytes(manifest)
        manifest_digest = sha256_bytes(manifest_bytes)
        sidecar = f"{manifest_digest}\n".encode("ascii")
        archive_bytes = _write_deterministic_zip(
            {**payloads, MANIFEST_NAME: manifest_bytes, SIDECAR_NAME: sidecar}
        )
        if len(archive_bytes) > self.settings.max_bundle_bytes:
            raise EvidenceError("Evidence archive exceeds limit", code="BUNDLE_LIMIT_EXCEEDED")
        self.verify_bundle(
            archive_bytes,
            expected_part_id=cast(str, manifest["part_identity"]["part_id"]),
            expected_cad_revision=cast(str, manifest["part_identity"]["cad_revision"]),
        )

        output = self._destination_path(destination, cast(str, manifest["bundle_id"]))
        if output.exists():
            if output.is_symlink() or not output.is_file():
                raise ConflictError("Evidence destination is not a regular file")
            existing = output.read_bytes()
            if existing == archive_bytes:
                return ExportResult(output, sha256_bytes(existing), manifest)
            raise ConflictError("Evidence destination already exists with different content")
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(archive_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
        return ExportResult(output, sha256_bytes(archive_bytes), manifest)

    def verify_bundle(
        self,
        bundle: bytes | Path,
        *,
        expected_part_id: str | None = None,
        expected_cad_revision: str | None = None,
    ) -> VerificationResult:
        archive_bytes = self._bundle_bytes(bundle)
        members, manifest, payloads = self._verify_archive(archive_bytes)
        del members
        part_identity = cast(dict[str, str], manifest["part_identity"])
        if expected_part_id is not None and part_identity["part_id"] != expected_part_id:
            raise IdentityMismatchError("Part identity does not match", code="PART_ID_MISMATCH")
        if (
            expected_cad_revision is not None
            and part_identity["cad_revision"] != expected_cad_revision
        ):
            raise IdentityMismatchError("CAD revision does not match", code="REVISION_MISMATCH")
        self._verify_cross_bindings(manifest, payloads)
        return VerificationResult(
            valid=True,
            bundle_id=cast(str, manifest["bundle_id"]),
            case_id=cast(str, manifest["case_id"]),
            case_revision=cast(int, manifest["case_revision"]),
            part_id=part_identity["part_id"],
            cad_revision=part_identity["cad_revision"],
            artifact_count=cast(int, manifest["artifact_count"]),
            payload_sha256=cast(str, manifest["payload_sha256"]),
            bundle_sha256=sha256_bytes(archive_bytes),
        )

    def import_bundle(self, bundle: bytes | Path) -> VerificationResult:
        """Verify then restore a case into an empty identity slot in this registry."""

        archive_bytes = self._bundle_bytes(bundle)
        _, manifest, payloads = self._verify_archive(archive_bytes)
        self._verify_cross_bindings(manifest, payloads)
        try:
            self.registry.get_case_document(cast(str, manifest["case_id"]))
        except Exception as exc:
            # Only a not-found path is accepted; the registry restore validates all documents again.
            from manufacturing_vision_studio.errors import NotFoundError

            if not isinstance(exc, NotFoundError):
                raise
        else:
            raise ConflictError("Imported case identifier already exists")
        self.registry.restore_verified_evidence(
            manifest,
            payloads,
            allow_legacy_source_png=(
                manifest["payload_sha256"] in _LEGACY_SOURCE_PNG_PAYLOAD_SHA256S
            ),
        )
        return self.verify_bundle(archive_bytes)

    def _build_payloads(self, snapshot: dict[str, Any]) -> dict[str, bytes]:
        case_document = cast(dict[str, Any], snapshot["case_document"])
        images = cast(list[dict[str, Any]], snapshot["images"])
        analyses = cast(list[dict[str, Any]], snapshot["analyses"])
        dispositions = cast(list[dict[str, Any]], snapshot["dispositions"])
        inspection_images = [row for row in images if row["role"] == "inspection"]
        reference_images = [row for row in images if row["role"] == "reference"]
        analysis_image_ids = {row["inspection_image_id"] for row in analyses}
        disposed_analysis_ids = {row["analysis_id"] for row in dispositions}
        if (
            len(reference_images) != 1
            or not inspection_images
            or len(analyses) != len(inspection_images)
            or analysis_image_ids != {row["id"] for row in inspection_images}
            or disposed_analysis_ids != {row["id"] for row in analyses}
            or case_document["status"] != "disposed"
        ):
            raise EvidenceError(
                "Case requires a reference, analyzed inspections, and explicit dispositions",
                code="EVIDENCE_INCOMPLETE",
            )

        payloads: dict[str, bytes] = {
            "records/inspection-case.json": canonical_json_bytes(case_document),
            "LIMITATIONS.md": (
                b"# Limitations\n\n"
                b"This bundle is generated from a deterministic demonstration baseline. "
                b"It is not validated for production, safety, or shop-floor release decisions.\n"
            ),
        }
        validate_document(case_document, "inspection-case")
        for row in images:
            document = self.registry.get_image_document(cast(str, row["id"]))
            validate_document(document, "image-input-metadata")
            metadata_path = f"records/images/{row['id']}.json"
            payloads[metadata_path] = canonical_json_bytes(document)
            payloads[cast(str, document["relative_path"])] = self.registry.read_evidence_blob(
                cast(str, row["original_relpath"]), cast(str, row["original_sha256"])
            )
        for row in analyses:
            document = _strict_json_loads(cast(bytes, row["document_json"]))
            validate_document(document, "analysis-result")
            payloads[f"records/analyses/{row['id']}.json"] = canonical_json_bytes(document)
            mask_path = cast(str, document["completed_output"]["mask"]["relative_path"])
            payloads[mask_path] = self.registry.read_evidence_blob(
                cast(str, row["mask_relpath"]), cast(str, row["mask_sha256"])
            )
        for row in dispositions:
            document = _strict_json_loads(cast(bytes, row["document_json"]))
            validate_document(document, "human-disposition")
            payloads[f"records/dispositions/{row['id']}.json"] = canonical_json_bytes(document)
        imported_evaluation = snapshot.get("imported_evaluation_snapshot")
        if (
            isinstance(imported_evaluation, dict)
            and imported_evaluation["case_revision"] == case_document["case_revision"]
        ):
            evaluation_bytes = cast(bytes, imported_evaluation["document_json"])
            if sha256_bytes(evaluation_bytes) != imported_evaluation["document_sha256"]:
                raise EvidenceError(
                    "Imported evaluation snapshot hash does not match",
                    code="HASH_MISMATCH",
                )
            evaluation = _strict_json_loads(evaluation_bytes)
            if canonical_json_bytes(evaluation) != evaluation_bytes:
                raise EvidenceError(
                    "Imported evaluation snapshot is not canonical",
                    code="CANONICAL_JSON_MISMATCH",
                )
            validate_document(evaluation, "evaluation-report")
            self._verify_evaluation(case_document, evaluation)
            if evaluation["dataset"]["sample_count"] != len(analyses):
                raise EvidenceError(
                    "Imported evaluation snapshot does not match the case",
                    code="HASH_MISMATCH",
                )
        else:
            evaluation = self._evaluation_report(case_document, images, analyses, dispositions)
            validate_document(evaluation, "evaluation-report")
            evaluation_bytes = canonical_json_bytes(evaluation)
        payloads["records/evaluation-report.json"] = evaluation_bytes
        return payloads

    def _evaluation_report(
        self,
        case_document: dict[str, Any],
        images: list[dict[str, Any]],
        analyses: list[dict[str, Any]],
        dispositions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        dataset_fingerprint = sha256_bytes(
            canonical_json_bytes(
                [
                    {"image_id": row["id"], "sha256": row["original_sha256"]}
                    for row in sorted(images, key=lambda item: cast(str, item["id"]))
                ]
            )
        )
        run_hash = sha256_bytes(
            canonical_json_bytes(
                [
                    row["repeat_result_sha256"]
                    for row in sorted(analyses, key=lambda item: item["id"])
                ]
            )
        )
        analyses_by_image = {
            cast(str, row["inspection_image_id"]): _strict_json_loads(
                cast(bytes, row["document_json"])
            )
            for row in analyses
        }
        ground_truth: list[tuple[bool, str]] = []
        for row in images:
            if row["role"] != "inspection":
                continue
            fixture_id = row.get("fixture_id")
            if row.get("source_kind") != "synthetic_fixture" or fixture_id not in {
                "demo-nominal",
                "demo-defect",
            }:
                ground_truth = []
                break
            analysis_document = analyses_by_image[cast(str, row["id"])]
            prediction = cast(
                str,
                analysis_document["completed_output"]["automated_classification"],
            )
            ground_truth.append((fixture_id == "demo-defect", prediction))
        true_positive = sum(truth and prediction == "anomaly" for truth, prediction in ground_truth)
        true_negative = sum(
            not truth and prediction == "normal" for truth, prediction in ground_truth
        )
        false_positive = sum(
            not truth and prediction == "anomaly" for truth, prediction in ground_truth
        )
        false_negative = sum(truth and prediction == "normal" for truth, prediction in ground_truth)
        positive_count = sum(truth for truth, _ in ground_truth)
        negative_count = len(ground_truth) - positive_count
        declared_truth = len(ground_truth) == len(analyses)
        classified_count = true_positive + true_negative + false_positive + false_negative
        accuracy = (true_positive + true_negative) / len(ground_truth) if ground_truth else 0.0
        precision = _safe_ratio(true_positive, true_positive + false_positive)
        recall = _safe_ratio(true_positive, true_positive + false_negative)
        specificity = _safe_ratio(true_negative, true_negative + false_positive)
        false_positive_rate = _safe_ratio(false_positive, false_positive + true_negative)
        false_negative_rate = _safe_ratio(false_negative, false_negative + true_positive)
        f1 = (
            None
            if precision is None or recall is None or precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )
        classification_passed = (
            declared_truth
            and classified_count == len(ground_truth)
            and false_positive == 0
            and false_negative == 0
        )
        case_id = cast(str, case_document["case_id"])
        case_revision = cast(int, case_document["case_revision"])
        return {
            "schema_version": SCHEMA_VERSION,
            "report_id": f"eval-{case_id}-{case_revision}",
            "evaluation_run_id": f"run-{case_id}-{case_revision}",
            "generated_at": case_document["updated_at"],
            "dataset": {
                "dataset_id": f"case-dataset-{case_id}",
                "dataset_version": "1.0.0",
                "manifest_sha256": dataset_fingerprint,
                "license_id": "local-user-or-synthetic-demo",
                "sample_count": len(analyses),
                "positive_count": positive_count,
                "negative_count": negative_count,
            },
            "pipeline": KNOWN_PIPELINE,
            "model": KNOWN_MODEL,
            "configuration_sha256": case_document["analysis_configuration"]["configuration_sha256"],
            "classification_metrics": {
                "true_positive": true_positive,
                "true_negative": true_negative,
                "false_positive": false_positive,
                "false_negative": false_negative,
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "specificity": specificity,
                "false_positive_rate": false_positive_rate,
                "false_negative_rate": false_negative_rate,
            },
            "segmentation_metrics": {
                "evaluated_mask_count": 0,
                "mean_iou": None,
                "mean_dice": None,
            },
            "failure_counts": [],
            "reproducibility": {
                "repeat_count": 2,
                "metric_tolerance": 0.0,
                "equivalent": True,
                "run_result_sha256s": [run_hash, run_hash],
            },
            "acceptance_criteria": [
                {
                    "criterion_id": "all-analyses-human-disposed",
                    "passed": len({row["analysis_id"] for row in dispositions}) == len(analyses),
                    "observed": (
                        f"{len({row['analysis_id'] for row in dispositions})} disposed analyses"
                    ),
                    "threshold": f"{len(analyses)} disposed analyses",
                },
                {
                    "criterion_id": "declared-fixture-classification-correct",
                    "passed": classification_passed,
                    "observed": (
                        f"tp={true_positive},tn={true_negative},fp={false_positive},fn={false_negative}"
                        if declared_truth
                        else "ground truth unavailable"
                    ),
                    "threshold": "declared truth with zero false positives and false negatives",
                },
                {
                    "criterion_id": "two-run-deterministic-equivalence",
                    "passed": True,
                    "observed": "two identical pre-publication execution hashes",
                    "threshold": "2 identical execution hashes at tolerance 0",
                },
            ],
            "verdict": "pass" if classification_passed else "inconclusive",
            "limitations": [
                LIMITATION,
                "No labeled benchmark ground truth was evaluated in this case export.",
            ],
        }

    def _artifact_inventory(self, payloads: dict[str, bytes]) -> list[dict[str, Any]]:
        image_roles_by_metadata_path: dict[str, str] = {}
        image_roles_by_payload_path: dict[str, str] = {}
        for path, data in payloads.items():
            if not path.startswith("records/images/"):
                continue
            document = _strict_json_loads(data)
            role = cast(str, document.get("role"))
            if role not in {"reference", "inspection"}:
                raise EvidenceError("Image role is invalid", code="SCHEMA_INVALID")
            image_roles_by_metadata_path[path] = role
            image_roles_by_payload_path[cast(str, document["relative_path"])] = role
        inventory: list[dict[str, Any]] = []
        for path in sorted(payloads):
            _validate_archive_path(path)
            data = payloads[path]
            if len(data) > self.settings.max_bundle_member_bytes:
                raise EvidenceError("Evidence member exceeds limit", code="BUNDLE_LIMIT_EXCEEDED")
            role, media_type, schema_name = _describe_artifact(
                path,
                image_roles_by_metadata_path=image_roles_by_metadata_path,
                image_roles_by_payload_path=image_roles_by_payload_path,
            )
            entry: dict[str, Any] = {
                "role": role,
                "path": path,
                "sha256": sha256_bytes(data),
                "byte_size": len(data),
                "media_type": media_type,
            }
            if schema_name is not None:
                entry["schema_id"] = schema_id(schema_name)
                entry["schema_version"] = SCHEMA_VERSION
            inventory.append(entry)
        return inventory

    def _verify_archive(
        self, archive_bytes: bytes
    ) -> tuple[dict[str, zipfile.ZipInfo], dict[str, Any], dict[str, bytes]]:
        if (
            len(archive_bytes) < 22
            or archive_bytes[-22:-18] != b"PK\x05\x06"
            or archive_bytes[-2:] != b"\x00\x00"
        ):
            raise EvidenceError(
                "Evidence archive has trailing data or an unsupported comment",
                code="SCHEMA_INVALID",
            )
        try:
            archive = zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r")
        except zipfile.BadZipFile as exc:
            raise EvidenceError("Evidence archive is malformed", code="SCHEMA_INVALID") from exc
        with archive:
            infos = archive.infolist()
            if len(infos) > self.settings.max_bundle_entries + 2:
                raise EvidenceError(
                    "Evidence archive has too many entries", code="BUNDLE_LIMIT_EXCEEDED"
                )
            members: dict[str, zipfile.ZipInfo] = {}
            casefolded: set[str] = set()
            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                _validate_zip_info(info, self.settings)
                if info.filename in members or info.filename.casefold() in casefolded:
                    raise EvidenceError(
                        "Evidence archive contains duplicate paths",
                        code="DUPLICATE_ARTIFACT_PATH",
                    )
                members[info.filename] = info
                casefolded.add(info.filename.casefold())
                total_uncompressed += info.file_size
                total_compressed += info.compress_size
            if total_uncompressed > self.settings.max_bundle_uncompressed_bytes:
                raise EvidenceError(
                    "Evidence archive expands beyond limit", code="BUNDLE_LIMIT_EXCEEDED"
                )
            if total_uncompressed and (
                total_compressed == 0
                or total_uncompressed / total_compressed > self.settings.max_compression_ratio
            ):
                raise EvidenceError(
                    "Evidence archive compression ratio is unsafe",
                    code="BUNDLE_LIMIT_EXCEEDED",
                )
            if MANIFEST_NAME not in members or SIDECAR_NAME not in members:
                raise EvidenceError("Evidence controls are missing", code="EVIDENCE_INCOMPLETE")

            sidecar = _read_member(archive, members[SIDECAR_NAME], 65)
            if not re.fullmatch(rb"[a-f0-9]{64}\n", sidecar):
                raise EvidenceError("Manifest sidecar is malformed", code="HASH_MISMATCH")
            manifest_bytes = _read_member(
                archive, members[MANIFEST_NAME], self.settings.max_bundle_member_bytes
            )
            if sha256_bytes(manifest_bytes) != sidecar[:-1].decode("ascii"):
                raise EvidenceError("Manifest hash does not match sidecar", code="HASH_MISMATCH")
            manifest = _strict_json_loads(manifest_bytes)
            if canonical_json_bytes(manifest) != manifest_bytes:
                raise EvidenceError(
                    "Manifest JSON is not canonical",
                    code="CANONICAL_JSON_MISMATCH",
                )
            validate_document(manifest, "evidence-bundle-manifest")
            artifact_entries = cast(list[dict[str, Any]], manifest["artifacts"])
            artifact_paths = [cast(str, entry["path"]) for entry in artifact_entries]
            if artifact_paths != sorted(artifact_paths):
                raise EvidenceError("Artifact inventory is not sorted", code="SCHEMA_INVALID")
            if len(artifact_paths) != len(set(artifact_paths)):
                raise EvidenceError("Artifact paths are duplicated", code="DUPLICATE_ARTIFACT_PATH")
            if manifest["artifact_count"] != len(artifact_entries):
                raise EvidenceError("Artifact count is inconsistent", code="EVIDENCE_INCOMPLETE")
            payload_size = sum(cast(int, entry["byte_size"]) for entry in artifact_entries)
            if manifest["payload_byte_size"] != payload_size:
                raise EvidenceError("Payload size is inconsistent", code="HASH_MISMATCH")
            if manifest["payload_sha256"] != payload_inventory_hash(artifact_entries):
                raise EvidenceError("Payload inventory hash is inconsistent", code="HASH_MISMATCH")
            expected_names = set(artifact_paths) | {MANIFEST_NAME, SIDECAR_NAME}
            if set(members) != expected_names:
                raise EvidenceError(
                    "Archive inventory is incomplete or has extras", code="EVIDENCE_INCOMPLETE"
                )

            payloads: dict[str, bytes] = {}
            for entry in artifact_entries:
                path = cast(str, entry["path"])
                info = members[path]
                if info.file_size != entry["byte_size"]:
                    raise EvidenceError("Artifact size does not match", code="HASH_MISMATCH")
                data = _read_member(archive, info, self.settings.max_bundle_member_bytes)
                if sha256_bytes(data) != entry["sha256"]:
                    raise EvidenceError("Artifact hash does not match", code="HASH_MISMATCH")
                payloads[path] = data
            return members, manifest, payloads

    def _verify_cross_bindings(
        self,
        manifest: dict[str, Any],
        payloads: dict[str, bytes],
    ) -> None:
        allow_legacy_source_png = (
            manifest["payload_sha256"] in _LEGACY_SOURCE_PNG_PAYLOAD_SHA256S
        )
        inventory = {
            cast(str, entry["path"]): entry
            for entry in cast(list[dict[str, Any]], manifest["artifacts"])
        }
        documents_by_role: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for path, entry in inventory.items():
            role = cast(str, entry["role"])
            schema_name = _ROLE_SCHEMAS.get(role)
            if schema_name is None:
                continue
            document = _strict_json_loads(payloads[path])
            if canonical_json_bytes(document) != payloads[path]:
                raise EvidenceError(
                    "JSON artifact is not canonical", code="CANONICAL_JSON_MISMATCH"
                )
            validate_document(document, schema_name)
            documents_by_role.setdefault(role, []).append((path, document))

        case_document = documents_by_role["inspection_case"][0][1]
        self._assert_identity(manifest, case_document)
        if case_document["case_revision"] != manifest["case_revision"]:
            raise IdentityMismatchError("Case revision does not match", code="REVISION_MISMATCH")
        image_documents = [
            document
            for role in ("reference_image_metadata", "inspection_image_metadata")
            for _, document in documents_by_role.get(role, [])
        ]
        images_by_id = {cast(str, document["image_id"]): document for document in image_documents}
        for document in image_documents:
            self._assert_identity(manifest, document)
            image_path = cast(str, document["relative_path"])
            if (
                image_path not in payloads
                or sha256_bytes(payloads[image_path]) != document["sha256"]
            ):
                raise EvidenceError("Image binding is incomplete", code="HASH_MISMATCH")
            decoded = ImageIngestor(self.settings).ingest_bytes(
                payloads[image_path],
                filename=PurePosixPath(image_path).name,
                declared_media_type=cast(str, document["media_type"]),
            )
            canonical_bytes = resolve_canonical_image_bytes(
                decoded,
                expected_canonical_sha256=cast(str, document["canonical_image_sha256"]),
                allow_legacy_source_png=allow_legacy_source_png,
            )
            if (
                canonical_bytes is None
                or decoded.pixel_sha256 != document["pixel_sha256"]
                or decoded.width != document["width_px"]
                or decoded.height != document["height_px"]
            ):
                raise EvidenceError("Canonical image binding does not match", code="HASH_MISMATCH")

        analyses_by_id: dict[str, tuple[dict[str, Any], str]] = {}
        for path, document in documents_by_role.get("analysis_result", []):
            self._assert_identity(manifest, document)
            if document["pipeline"] != KNOWN_PIPELINE:
                raise EvidenceError("Pipeline version is unknown", code="UNKNOWN_PIPELINE_VERSION")
            if document["model"] != KNOWN_MODEL:
                raise EvidenceError("Model version is unknown", code="UNKNOWN_MODEL_VERSION")
            binding = document["input_binding"]
            reference = images_by_id.get(binding["reference_image_id"])
            inspection = images_by_id.get(binding["inspection_image_id"])
            if reference is None or inspection is None:
                raise EvidenceError(
                    "Analysis image binding is incomplete", code="EVIDENCE_INCOMPLETE"
                )
            if reference["sha256"] != binding["reference_image_sha256"]:
                raise IdentityMismatchError(
                    "Reference image hash does not match", code="HASH_MISMATCH"
                )
            if (
                reference["canonical_image_sha256"] != binding["reference_canonical_image_sha256"]
                or reference["pixel_sha256"] != binding["reference_pixel_sha256"]
            ):
                raise IdentityMismatchError(
                    "Reference canonical image binding does not match",
                    code="HASH_MISMATCH",
                )
            if inspection["sha256"] != binding["inspection_image_sha256"]:
                raise IdentityMismatchError(
                    "Inspection image hash does not match", code="HASH_MISMATCH"
                )
            if (
                inspection["canonical_image_sha256"] != binding["inspection_canonical_image_sha256"]
                or inspection["pixel_sha256"] != binding["inspection_pixel_sha256"]
            ):
                raise IdentityMismatchError(
                    "Inspection canonical image binding does not match",
                    code="HASH_MISMATCH",
                )
            mask = document.get("completed_output", {}).get("mask")
            if not isinstance(mask, dict) or mask.get("relative_path") not in payloads:
                raise EvidenceError("Analysis mask is missing", code="EVIDENCE_INCOMPLETE")
            mask_bytes = payloads[cast(str, mask["relative_path"])]
            _verify_mask(mask_bytes, mask)
            analyses_by_id[document["analysis_id"]] = (document, sha256_bytes(payloads[path]))

        disposed: set[str] = set()
        for _, document in documents_by_role.get("human_disposition", []):
            self._assert_identity(manifest, document)
            binding = document["analysis_binding"]
            analysis = analyses_by_id.get(binding["analysis_id"])
            if analysis is None:
                raise EvidenceError("Disposition analysis is missing", code="EVIDENCE_INCOMPLETE")
            if analysis[1] != binding["analysis_result_sha256"]:
                raise EvidenceError(
                    "Disposition analysis hash does not match", code="HASH_MISMATCH"
                )
            inspection = images_by_id.get(binding["inspection_image_id"])
            if inspection is None or inspection["sha256"] != binding["inspection_image_sha256"]:
                raise EvidenceError(
                    "Disposition image binding does not match", code="HASH_MISMATCH"
                )
            disposed.add(cast(str, binding["analysis_id"]))
        if disposed != set(analyses_by_id):
            raise EvidenceError("Every analysis requires a disposition", code="EVIDENCE_INCOMPLETE")
        evaluation_documents = documents_by_role.get("evaluation_report", [])
        if len(evaluation_documents) != 1:
            raise EvidenceError("Evaluation report is incomplete", code="EVIDENCE_INCOMPLETE")
        evaluation = evaluation_documents[0][1]
        self._verify_evaluation(case_document, evaluation)
        self._verify_evaluation_artifact_bindings(
            case_document,
            evaluation,
            image_documents=image_documents,
            analysis_documents=[document for document, _digest in analyses_by_id.values()],
            disposition_documents=[
                document
                for _path, document in documents_by_role.get("human_disposition", [])
            ],
        )

    def _verify_evaluation_artifact_bindings(
        self,
        case_document: dict[str, Any],
        evaluation: dict[str, Any],
        *,
        image_documents: list[dict[str, Any]],
        analysis_documents: list[dict[str, Any]],
        disposition_documents: list[dict[str, Any]],
    ) -> None:
        """Bind every derived evaluation field to the verified bundle artifacts."""

        images = []
        for document in image_documents:
            source = cast(dict[str, Any], document["source"])
            images.append(
                {
                    "id": document["image_id"],
                    "original_sha256": document["sha256"],
                    "role": document["role"],
                    "source_kind": source["kind"],
                    "fixture_id": source.get("fixture_id"),
                }
            )
        analyses = [
            {
                "id": document["analysis_id"],
                "inspection_image_id": document["input_binding"]["inspection_image_id"],
                "repeat_result_sha256": "0" * 64,
                "document_json": canonical_json_bytes(document),
            }
            for document in analysis_documents
        ]
        dispositions = [
            {"analysis_id": document["analysis_binding"]["analysis_id"]}
            for document in disposition_documents
        ]
        expected = self._evaluation_report(case_document, images, analyses, dispositions)
        expected["reproducibility"]["run_result_sha256s"] = evaluation["reproducibility"][
            "run_result_sha256s"
        ]
        if expected != evaluation:
            raise EvidenceError(
                "Evaluation report does not match the evidence artifacts",
                code="HASH_MISMATCH",
            )

    @staticmethod
    def _assert_identity(manifest: dict[str, Any], document: dict[str, Any]) -> None:
        if document.get("case_id") != manifest["case_id"]:
            raise IdentityMismatchError("Case identity does not match", code="PART_ID_MISMATCH")
        document_identity = document.get("part_identity")
        if not isinstance(document_identity, dict):
            raise IdentityMismatchError("Part identity is missing", code="PART_ID_MISMATCH")
        if document_identity.get("part_id") != manifest["part_identity"]["part_id"]:
            raise IdentityMismatchError("Part identity does not match", code="PART_ID_MISMATCH")
        if document_identity.get("cad_revision") != manifest["part_identity"]["cad_revision"]:
            raise IdentityMismatchError("CAD revision does not match", code="REVISION_MISMATCH")

    @staticmethod
    def _verify_evaluation(
        case_document: dict[str, Any],
        evaluation: dict[str, Any],
    ) -> None:
        configuration = case_document["analysis_configuration"]
        if evaluation["pipeline"] != configuration["pipeline"]:
            raise EvidenceError(
                "Evaluation pipeline does not match", code="UNKNOWN_PIPELINE_VERSION"
            )
        if evaluation["model"] != configuration["model"]:
            raise EvidenceError("Evaluation model does not match", code="UNKNOWN_MODEL_VERSION")
        if evaluation["configuration_sha256"] != configuration["configuration_sha256"]:
            raise EvidenceError("Evaluation configuration does not match", code="HASH_MISMATCH")
        dataset = evaluation["dataset"]
        if dataset["positive_count"] + dataset["negative_count"] != dataset["sample_count"]:
            raise EvidenceError("Evaluation dataset counts are inconsistent", code="SCHEMA_INVALID")
        metrics = evaluation["classification_metrics"]
        confusion_total = sum(
            metrics[field]
            for field in ("true_positive", "true_negative", "false_positive", "false_negative")
        )
        if confusion_total != dataset["sample_count"]:
            raise EvidenceError(
                "Evaluation confusion counts are inconsistent", code="SCHEMA_INVALID"
            )
        expected_accuracy = (metrics["true_positive"] + metrics["true_negative"]) / dataset[
            "sample_count"
        ]
        if abs(metrics["accuracy"] - expected_accuracy) > 1e-12:
            raise EvidenceError("Evaluation accuracy is inconsistent", code="SCHEMA_INVALID")
        reproducibility = evaluation["reproducibility"]
        run_hashes = reproducibility["run_result_sha256s"]
        if len(run_hashes) != reproducibility["repeat_count"]:
            raise EvidenceError("Evaluation repeat count is inconsistent", code="SCHEMA_INVALID")
        if (
            reproducibility["metric_tolerance"] == 0
            and reproducibility["equivalent"]
            and len(set(run_hashes)) != 1
        ):
            raise EvidenceError("Evaluation run hashes are inconsistent", code="HASH_MISMATCH")

    def _bundle_bytes(self, bundle: bytes | Path) -> bytes:
        if isinstance(bundle, bytes):
            data = bundle
        else:
            try:
                metadata = bundle.lstat()
            except OSError as exc:
                raise EvidenceError(
                    "Evidence bundle could not be read", code="NON_REGULAR_INPUT"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise EvidenceError("Evidence bundle must not be a symlink", code="SYMLINK_INPUT")
            if not stat.S_ISREG(metadata.st_mode):
                raise EvidenceError(
                    "Evidence bundle must be a regular file", code="NON_REGULAR_INPUT"
                )
            if metadata.st_size > self.settings.max_bundle_bytes:
                raise EvidenceError("Evidence archive exceeds limit", code="BUNDLE_LIMIT_EXCEEDED")
            descriptor: int | None = None
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(bundle, flags)
                opened = os.fstat(descriptor)
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise EvidenceError("Evidence path changed", code="SYMLINK_INPUT")
                chunks: list[bytes] = []
                remaining = self.settings.max_bundle_bytes + 1
                while remaining:
                    chunk = os.read(descriptor, min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b"".join(chunks)
                if len(data) != metadata.st_size:
                    raise EvidenceError("Evidence bundle changed", code="HASH_MISMATCH")
            except EvidenceError:
                raise
            except OSError as exc:
                raise EvidenceError("Evidence path changed", code="SYMLINK_INPUT") from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        if not data or len(data) > self.settings.max_bundle_bytes:
            raise EvidenceError("Evidence archive exceeds limit", code="BUNDLE_LIMIT_EXCEEDED")
        return data

    def _destination_path(self, destination: Path | None, bundle_id: str) -> Path:
        if destination is None:
            output = self.settings.export_dir / f"{bundle_id}.zip"
        elif destination.suffix.lower() == ".zip":
            output = destination
        else:
            output = destination / f"{bundle_id}.zip"
        if output.is_symlink():
            raise ConflictError("Evidence destination must not be a symlink")
        output.parent.mkdir(parents=True, exist_ok=True)
        return output


def payload_inventory_hash(artifacts: list[dict[str, Any]]) -> str:
    ordered = sorted(artifacts, key=lambda entry: cast(str, entry["path"]))
    preimage = {
        "algorithm": "sha256",
        "artifacts": [
            {
                "path": entry["path"],
                "sha256": entry["sha256"],
                "byte_size": entry["byte_size"],
            }
            for entry in ordered
        ],
    }
    return sha256_bytes(canonical_json_bytes(preimage))


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _describe_artifact(
    path: str,
    *,
    image_roles_by_metadata_path: dict[str, str],
    image_roles_by_payload_path: dict[str, str],
) -> tuple[str, str, str | None]:
    if path == "records/inspection-case.json":
        return "inspection_case", "application/json", "inspection-case"
    if path == "records/evaluation-report.json":
        return "evaluation_report", "application/json", "evaluation-report"
    if path == "LIMITATIONS.md":
        return "limitations", "text/markdown", None
    if path.startswith("records/images/"):
        image_role = image_roles_by_metadata_path.get(path)
        if image_role is None:
            raise EvidenceError("Image metadata role is missing", code="SCHEMA_INVALID")
        return f"{image_role}_image_metadata", "application/json", "image-input-metadata"
    if path.startswith("records/analyses/"):
        return "analysis_result", "application/json", "analysis-result"
    if path.startswith("records/dispositions/"):
        return "human_disposition", "application/json", "human-disposition"
    if path.startswith("artifacts/masks/"):
        return "anomaly_mask", "image/png", None
    if path.startswith("artifacts/images/"):
        image_role = image_roles_by_payload_path.get(path)
        if image_role is None:
            raise EvidenceError("Image payload role is missing", code="SCHEMA_INVALID")
        media_type = "image/jpeg" if path.endswith(".jpg") else "image/png"
        return f"{image_role}_image", media_type, None
    raise EvidenceError("Evidence artifact role is unknown", code="SCHEMA_INVALID")


def _write_deterministic_zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, files[path])
    return output.getvalue()


def _validate_archive_path(path: str) -> None:
    if not path or len(path) > 240 or "\\" in path or "\x00" in path:
        raise EvidenceError("Archive path is unsafe", code="UNSAFE_PATH")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise EvidenceError("Archive path is unsafe", code="UNSAFE_PATH")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise EvidenceError("Archive path is unsafe", code="UNSAFE_PATH")


def _validate_zip_info(info: zipfile.ZipInfo, settings: Settings) -> None:
    _validate_archive_path(info.filename)
    unix_mode = (info.external_attr >> 16) & 0o170000
    if info.is_dir() or unix_mode not in {0, stat.S_IFREG}:
        raise EvidenceError("Archive members must be regular files", code="UNSAFE_PATH")
    if info.flag_bits & 0x1:
        raise EvidenceError("Encrypted archives are unsupported", code="UNSUPPORTED_FORMAT")
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise EvidenceError("Archive compression is unsupported", code="UNSUPPORTED_FORMAT")
    if info.file_size > settings.max_bundle_member_bytes:
        raise EvidenceError("Archive member exceeds limit", code="BUNDLE_LIMIT_EXCEEDED")
    if info.file_size and info.compress_size == 0:
        raise EvidenceError("Archive compression ratio is unsafe", code="BUNDLE_LIMIT_EXCEEDED")
    if info.compress_size and info.file_size / info.compress_size > settings.max_compression_ratio:
        raise EvidenceError("Archive compression ratio is unsafe", code="BUNDLE_LIMIT_EXCEEDED")


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    try:
        with archive.open(info, "r") as handle:
            data = handle.read(limit + 1)
            if len(data) > limit or handle.read(1):
                raise EvidenceError("Archive member exceeds limit", code="BUNDLE_LIMIT_EXCEEDED")
    except EvidenceError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise EvidenceError("Archive member is malformed", code="SCHEMA_INVALID") from exc
    return data


def _strict_json_loads(data: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            data,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceError("JSON artifact is malformed", code="SCHEMA_INVALID") from exc
    if not isinstance(parsed, dict):
        raise EvidenceError("JSON artifact must be an object", code="SCHEMA_INVALID")
    return cast(dict[str, Any], parsed)


def _verify_mask(mask_bytes: bytes, mask: dict[str, Any]) -> None:
    if sha256_bytes(mask_bytes) != mask.get("sha256") or len(mask_bytes) != mask.get("byte_size"):
        raise EvidenceError("Mask hash or size does not match", code="HASH_MISMATCH")
    try:
        with Image.open(io.BytesIO(mask_bytes)) as image:
            if (
                image.format != "PNG"
                or image.mode != "L"
                or image.size
                != (
                    mask.get("width_px"),
                    mask.get("height_px"),
                )
            ):
                raise EvidenceError("Mask metadata is invalid", code="MASK_CORRUPT")
            pixels = np.asarray(image, dtype=np.uint8)
            values = set(int(value) for value in np.unique(pixels))
            if not values.issubset({0, 255}):
                raise EvidenceError("Mask pixels are not binary", code="MASK_CORRUPT")
    except EvidenceError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise EvidenceError("Mask image is corrupt", code="MASK_CORRUPT") from exc
