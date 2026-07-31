"""SQLite case registry and content-addressed local object store."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from PIL import __version__ as pillow_version

from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import (
    ConflictError,
    IdentityMismatchError,
    NotFoundError,
    UnsafeInputError,
)
from manufacturing_vision_studio.images import ImageIngestor, IngestedImage
from manufacturing_vision_studio.model import (
    DEFAULT_FEATURE_REGIONS,
    DeterministicDifferenceModel,
    InspectionResult,
)

SCHEMA_VERSION = "1.0.0"
LIMITATION = "Synthetic demo baseline only; not validated for production inspection."
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DECISIONS = {"accept", "reject", "needs_review", "model_error"}
REASON_CODES = {
    "visual_confirmation",
    "score_below_threshold",
    "score_above_threshold",
    "critical_feature_affected",
    "insufficient_evidence",
    "incorrect_mask",
    "incorrect_feature_mapping",
    "incorrect_classification",
    "other",
}
MODEL_ARTIFACT_SHA256 = sha256_bytes(
    b"manufacturing-vision-studio:registered-absolute-difference:1.0.0"
)


class CaseRegistry:
    """Persist immutable inputs/results and revisioned case state in SQLite."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.settings.prepare()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.settings.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    part_id TEXT NOT NULL,
                    cad_revision TEXT NOT NULL,
                    case_revision INTEGER NOT NULL DEFAULT 1,
                    locale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('reference', 'inspection')),
                    filename TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    fixture_id TEXT,
                    freecad_export_id TEXT,
                    media_type TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    original_sha256 TEXT NOT NULL,
                    canonical_sha256 TEXT NOT NULL,
                    pixel_sha256 TEXT NOT NULL,
                    original_size INTEGER NOT NULL,
                    canonical_size INTEGER NOT NULL,
                    original_relpath TEXT NOT NULL,
                    canonical_relpath TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_reference_per_case
                    ON images(case_id) WHERE role = 'reference';
                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    case_revision INTEGER NOT NULL,
                    reference_image_id TEXT NOT NULL REFERENCES images(id),
                    inspection_image_id TEXT NOT NULL REFERENCES images(id),
                    document_json BLOB NOT NULL,
                    document_sha256 TEXT NOT NULL,
                    registration_json BLOB NOT NULL,
                    mask_sha256 TEXT NOT NULL,
                    mask_size INTEGER NOT NULL,
                    mask_relpath TEXT NOT NULL,
                    registered_sha256 TEXT NOT NULL,
                    registered_size INTEGER NOT NULL,
                    registered_relpath TEXT NOT NULL,
                    repeat_result_sha256 TEXT NOT NULL,
                    produced_at TEXT NOT NULL,
                    UNIQUE(case_id, inspection_image_id)
                );
                CREATE TABLE IF NOT EXISTS dispositions (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    case_revision INTEGER NOT NULL,
                    disposition_revision INTEGER NOT NULL,
                    document_json BLOB NOT NULL,
                    document_sha256 TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(analysis_id, disposition_revision)
                );
                """
            )
            image_columns = {
                cast(str, row["name"])
                for row in connection.execute("PRAGMA table_info(images)").fetchall()
            }
            if "freecad_export_id" not in image_columns:
                connection.execute("ALTER TABLE images ADD COLUMN freecad_export_id TEXT")
            analysis_columns = {
                cast(str, row["name"])
                for row in connection.execute("PRAGMA table_info(analyses)").fetchall()
            }
            if "repeat_result_sha256" not in analysis_columns:
                connection.execute(
                    "ALTER TABLE analyses ADD COLUMN repeat_result_sha256 TEXT NOT NULL DEFAULT ''"
                )
            connection.commit()

    def create_case(
        self,
        *,
        part_id: str,
        cad_revision: str,
        locale: str = "en",
        case_id: str | None = None,
    ) -> dict[str, Any]:
        _validate_identifier(part_id, "part_id")
        _validate_identifier(cad_revision, "cad_revision")
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", locale):
            raise UnsafeInputError("Locale is malformed", code="SCHEMA_INVALID")
        identifier = case_id or f"case-{uuid.uuid4().hex[:16]}"
        _validate_identifier(identifier, "case_id")
        now = _timestamp()
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO cases(
                        id, part_id, cad_revision, case_revision, locale, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (identifier, part_id, cad_revision, locale, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Case identifier already exists") from exc
        return self.get_case_detail(identifier)

    def list_cases(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT id FROM cases ORDER BY created_at, id").fetchall()
        return [self.get_case_detail(cast(str, row["id"])) for row in rows]

    def get_case_detail(self, case_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            case_row = self._case_row(connection, case_id)
            image_rows = connection.execute(
                "SELECT * FROM images WHERE case_id = ? ORDER BY ingested_at, id", (case_id,)
            ).fetchall()
            analysis_rows = connection.execute(
                "SELECT * FROM analyses WHERE case_id = ? ORDER BY produced_at, id", (case_id,)
            ).fetchall()
            disposition_rows = connection.execute(
                "SELECT * FROM dispositions WHERE case_id = ? ORDER BY recorded_at, id", (case_id,)
            ).fetchall()
        images = [self._image_document(row, case_row) for row in image_rows]
        analyses = [_decode_canonical_json(row["document_json"]) for row in analysis_rows]
        dispositions = [_decode_canonical_json(row["document_json"]) for row in disposition_rows]
        return {
            "case": self._case_document(case_row, image_rows, analysis_rows, disposition_rows),
            "locale": case_row["locale"],
            "images": images,
            "analyses": analyses,
            "dispositions": dispositions,
        }

    def get_case_document(self, case_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.get_case_detail(case_id)["case"])

    def add_reference(
        self,
        case_id: str,
        image: IngestedImage,
        *,
        source_kind: Literal["upload", "synthetic_fixture", "freecad_export"] = "upload",
        fixture_id: str | None = None,
        freecad_export_id: str | None = None,
        expected_case_revision: int,
    ) -> dict[str, Any]:
        return self._add_image(
            case_id,
            image,
            role="reference",
            source_kind=source_kind,
            fixture_id=fixture_id,
            freecad_export_id=freecad_export_id,
            expected_case_revision=expected_case_revision,
        )

    def add_inspection(
        self,
        case_id: str,
        image: IngestedImage,
        *,
        source_kind: Literal["upload", "synthetic_fixture", "freecad_export"] = "upload",
        fixture_id: str | None = None,
        freecad_export_id: str | None = None,
        expected_case_revision: int,
    ) -> dict[str, Any]:
        return self._add_image(
            case_id,
            image,
            role="inspection",
            source_kind=source_kind,
            fixture_id=fixture_id,
            freecad_export_id=freecad_export_id,
            expected_case_revision=expected_case_revision,
        )

    def _add_image(
        self,
        case_id: str,
        image: IngestedImage,
        *,
        role: Literal["reference", "inspection"],
        source_kind: str,
        fixture_id: str | None,
        freecad_export_id: str | None,
        expected_case_revision: int,
    ) -> dict[str, Any]:
        if source_kind not in {"upload", "synthetic_fixture", "freecad_export"}:
            raise UnsafeInputError("Image source kind is invalid", code="SCHEMA_INVALID")
        if source_kind == "synthetic_fixture":
            if fixture_id is None:
                raise UnsafeInputError(
                    "Synthetic source requires fixture_id", code="SCHEMA_INVALID"
                )
            _validate_identifier(fixture_id, "fixture_id")
        if source_kind == "freecad_export":
            if freecad_export_id is None:
                raise UnsafeInputError(
                    "FreeCAD source requires freecad_export_id",
                    code="SCHEMA_INVALID",
                )
            _validate_identifier(freecad_export_id, "freecad_export_id")
        image_id = f"img-{uuid.uuid4().hex[:16]}"
        original_suffix = ".png" if image.source_format == "PNG" else ".jpg"
        now = _timestamp()
        created_blobs: list[Path] = []
        try:
            with self._transaction() as connection:
                case_row = self._case_row(connection, case_id)
                self._assert_expected_revision(case_row, expected_case_revision)
                if role == "reference":
                    existing_reference = connection.execute(
                        "SELECT 1 FROM images WHERE case_id = ? AND role = 'reference'",
                        (case_id,),
                    ).fetchone()
                    if existing_reference is not None:
                        raise ConflictError("Case already has a reference image")
                count = cast(
                    int,
                    connection.execute(
                        "SELECT COUNT(*) FROM images WHERE case_id = ? AND role = 'inspection'",
                        (case_id,),
                    ).fetchone()[0],
                )
                if role == "inspection" and count >= self.settings.max_images_per_case:
                    raise UnsafeInputError(
                        "Case image limit exceeded",
                        code="INPUT_TOO_LARGE",
                        details={"limit": self.settings.max_images_per_case},
                    )
                original_path = self._store_blob(
                    image.original_bytes,
                    image.original_sha256,
                    original_suffix,
                    created_paths=created_blobs,
                )
                canonical_path = self._store_blob(
                    image.canonical_bytes,
                    image.canonical_sha256,
                    ".normalized.png",
                    created_paths=created_blobs,
                )
                next_revision = cast(int, case_row["case_revision"]) + 1
                connection.execute(
                    """
                    INSERT INTO images(
                        id, case_id, role, filename, source_kind, fixture_id,
                        freecad_export_id, media_type, source_format, width, height,
                        original_sha256, canonical_sha256,
                        pixel_sha256, original_size, canonical_size, original_relpath,
                        canonical_relpath, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        image_id,
                        case_id,
                        role,
                        image.filename,
                        source_kind,
                        fixture_id,
                        freecad_export_id,
                        image.media_type,
                        image.source_format,
                        image.width,
                        image.height,
                        image.original_sha256,
                        image.canonical_sha256,
                        image.pixel_sha256,
                        len(image.original_bytes),
                        len(image.canonical_bytes),
                        original_path,
                        canonical_path,
                        now,
                    ),
                )
                self._bump_case(connection, case_id, next_revision, now)
        except sqlite3.IntegrityError as exc:
            self._remove_created_blobs(created_blobs)
            if role == "reference":
                raise ConflictError("Case already has a reference image") from exc
            raise ConflictError("Image could not be recorded") from exc
        except Exception:
            self._remove_created_blobs(created_blobs)
            raise
        return self.get_image_document(image_id)

    def get_image_document(self, image_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
            if row is None:
                raise NotFoundError("Image was not found")
            case_row = self._case_row(connection, cast(str, row["case_id"]))
        return self._image_document(row, case_row)

    def get_image_bytes(self, image_id: str, *, canonical: bool = False) -> tuple[bytes, str]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if row is None:
            raise NotFoundError("Image was not found")
        column = "canonical_relpath" if canonical else "original_relpath"
        digest_column = "canonical_sha256" if canonical else "original_sha256"
        data = self._read_blob(cast(str, row[column]), cast(str, row[digest_column]))
        media_type = "image/png" if canonical else cast(str, row["media_type"])
        return data, media_type

    def get_analysis_artifact(self, analysis_id: str, role: str) -> tuple[bytes, str]:
        if role not in {"mask", "registered"}:
            raise NotFoundError("Analysis artifact was not found")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("Analysis was not found")
        data = self._read_blob(cast(str, row[f"{role}_relpath"]), cast(str, row[f"{role}_sha256"]))
        return data, "image/png"

    def analyze_case(
        self,
        case_id: str,
        *,
        model: DeterministicDifferenceModel | None = None,
        image_id: str | None = None,
        expected_case_revision: int,
    ) -> list[dict[str, Any]]:
        active_model = model or DeterministicDifferenceModel()
        if (
            active_model.interface_version != DeterministicDifferenceModel.interface_version
            or active_model.pipeline_id != DeterministicDifferenceModel.pipeline_id
            or active_model.pipeline_version != DeterministicDifferenceModel.pipeline_version
        ):
            raise UnsafeInputError(
                "Pipeline version is not allowed",
                code="UNKNOWN_PIPELINE_VERSION",
            )
        if (
            active_model.model_name != DeterministicDifferenceModel.model_name
            or active_model.model_version != DeterministicDifferenceModel.model_version
        ):
            raise UnsafeInputError("Model version is not allowed", code="UNKNOWN_MODEL_VERSION")
        authoritative_config_hash = DeterministicDifferenceModel().config.config_hash
        if active_model.config.config_hash != authoritative_config_hash:
            raise UnsafeInputError(
                "Model configuration does not match the case configuration",
                code="HASH_MISMATCH",
            )
        with closing(self._connect()) as connection:
            case_row = self._case_row(connection, case_id)
            self._assert_expected_revision(case_row, expected_case_revision)
            reference_row = connection.execute(
                "SELECT * FROM images WHERE case_id = ? AND role = 'reference'", (case_id,)
            ).fetchone()
            if reference_row is None:
                raise UnsafeInputError("Case has no reference image", code="MISSING_REFERENCE")
            if image_id is None:
                inspection_rows = connection.execute(
                    """
                    SELECT * FROM images
                    WHERE case_id = ? AND role = 'inspection'
                    ORDER BY ingested_at, id
                    """,
                    (case_id,),
                ).fetchall()
            else:
                inspection_rows = connection.execute(
                    "SELECT * FROM images WHERE case_id = ? AND role = 'inspection' AND id = ?",
                    (case_id, image_id),
                ).fetchall()
        if not inspection_rows:
            raise UnsafeInputError("Case has no matching inspection images", code="SCHEMA_INVALID")
        reference = self._ingested_from_row(reference_row)
        documents: list[dict[str, Any]] = []
        for inspection_row in inspection_rows:
            existing = self._analysis_for_image(case_id, cast(str, inspection_row["id"]))
            if existing is not None:
                documents.append(existing)
                continue
            inspection = self._ingested_from_row(inspection_row)
            result = active_model.inspect(reference, inspection)
            repeat_result = active_model.inspect(reference, inspection)
            if (
                canonical_json_bytes(result.as_record())
                != canonical_json_bytes(repeat_result.as_record())
                or result.mask_bytes != repeat_result.mask_bytes
                or result.registered_bytes != repeat_result.registered_bytes
            ):
                raise UnsafeInputError(
                    "Repeated deterministic model executions differed",
                    code="MODEL_ABSTAINED",
                )
            documents.append(
                self._record_analysis(
                    case_row,
                    reference_row,
                    inspection_row,
                    result,
                    expected_case_revision=cast(int, case_row["case_revision"]),
                )
            )
            case_row = self._get_case_row(case_id)
        return documents

    def add_disposition(
        self,
        case_id: str,
        *,
        analysis_id: str,
        decision: str,
        reviewer_id: str,
        rationale: str,
        reason_codes: list[str],
        reviewer_display_name: str | None = None,
        expected_case_revision: int,
    ) -> dict[str, Any]:
        if decision not in DECISIONS:
            raise UnsafeInputError("Disposition decision is invalid", code="SCHEMA_INVALID")
        _validate_identifier(reviewer_id, "reviewer_id")
        if not 1 <= len(rationale) <= 2000:
            raise UnsafeInputError("Disposition rationale is required", code="SCHEMA_INVALID")
        if not 1 <= len(reason_codes) <= 16 or len(set(reason_codes)) != len(reason_codes):
            raise UnsafeInputError("Disposition reason codes are invalid", code="SCHEMA_INVALID")
        if not set(reason_codes).issubset(REASON_CODES):
            raise UnsafeInputError("Disposition reason code is unsupported", code="SCHEMA_INVALID")
        if reviewer_display_name is not None and not 1 <= len(reviewer_display_name) <= 128:
            raise UnsafeInputError("Reviewer display name is invalid", code="SCHEMA_INVALID")

        with self._transaction() as connection:
            case_row = self._case_row(connection, case_id)
            self._assert_expected_revision(case_row, expected_case_revision)
            analysis_row = connection.execute(
                "SELECT * FROM analyses WHERE id = ? AND case_id = ?", (analysis_id, case_id)
            ).fetchone()
            if analysis_row is None:
                raise NotFoundError("Analysis was not found for this case")
            inspection_row = connection.execute(
                "SELECT * FROM images WHERE id = ?", (analysis_row["inspection_image_id"],)
            ).fetchone()
            if inspection_row is None:
                raise UnsafeInputError("Analysis input is missing", code="EVIDENCE_INCOMPLETE")
            previous = connection.execute(
                """
                SELECT * FROM dispositions WHERE analysis_id = ?
                ORDER BY disposition_revision DESC LIMIT 1
                """,
                (analysis_id,),
            ).fetchone()
            disposition_revision = (
                1 if previous is None else cast(int, previous["disposition_revision"]) + 1
            )
            case_revision = cast(int, case_row["case_revision"]) + 1
            disposition_id = f"disp-{uuid.uuid4().hex[:16]}"
            recorded_at = _timestamp()
            reviewer: dict[str, str] = {"reviewer_id": reviewer_id}
            if reviewer_display_name is not None:
                reviewer["display_name"] = reviewer_display_name
            document: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "disposition_id": disposition_id,
                "disposition_revision": disposition_revision,
                "case_id": case_id,
                "case_revision": case_revision,
                "part_identity": self._part_identity(case_row),
                "analysis_binding": {
                    "analysis_id": analysis_id,
                    "analysis_result_sha256": analysis_row["document_sha256"],
                    "inspection_image_id": inspection_row["id"],
                    "inspection_image_sha256": inspection_row["original_sha256"],
                },
                "decision": decision,
                "reviewer": reviewer,
                "reason_codes": reason_codes,
                "rationale": rationale,
                "recorded_at": recorded_at,
                "supersedes_disposition_id": None if previous is None else previous["id"],
                "scope_acknowledgement": "demo_only_not_production_validated",
            }
            payload = canonical_json_bytes(document)
            connection.execute(
                """
                INSERT INTO dispositions(
                    id, analysis_id, case_id, case_revision, disposition_revision,
                    document_json, document_sha256, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    disposition_id,
                    analysis_id,
                    case_id,
                    case_revision,
                    disposition_revision,
                    payload,
                    sha256_bytes(payload),
                    recorded_at,
                ),
            )
            self._bump_case(connection, case_id, case_revision, recorded_at)
        return document

    def reset(self) -> None:
        """Delete local demo state. This is only called by the explicit reset command/endpoint."""

        with self._transaction() as connection:
            connection.execute("DELETE FROM cases")
        for root in (self.settings.blob_dir, self.settings.export_dir):
            resolved = root.resolve()
            if not resolved.is_relative_to(self.settings.data_dir.resolve()):
                raise RuntimeError("Refusing to clear storage outside data_dir")
            if resolved.is_symlink():
                raise RuntimeError("Refusing to clear symlinked storage")
            if resolved.exists():
                shutil.rmtree(resolved)
            resolved.mkdir(parents=True, exist_ok=True)

    def evidence_rows(
        self,
        case_id: str,
        *,
        expected_case_revision: int,
    ) -> dict[str, Any]:
        """Return internal immutable rows for the evidence service."""

        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            case_row = self._case_row(connection, case_id)
            self._assert_expected_revision(case_row, expected_case_revision)
            images = connection.execute(
                "SELECT * FROM images WHERE case_id = ? ORDER BY role DESC, ingested_at, id",
                (case_id,),
            ).fetchall()
            analyses = connection.execute(
                "SELECT * FROM analyses WHERE case_id = ? ORDER BY produced_at, id", (case_id,)
            ).fetchall()
            dispositions = connection.execute(
                "SELECT * FROM dispositions WHERE case_id = ? ORDER BY recorded_at, id", (case_id,)
            ).fetchall()
        return {
            "case_row": dict(case_row),
            "case_document": self._case_document(case_row, images, analyses, dispositions),
            "images": [dict(row) for row in images],
            "analyses": [dict(row) for row in analyses],
            "dispositions": [dict(row) for row in dispositions],
        }

    def assert_case_revision(self, case_id: str, expected_case_revision: int) -> None:
        """Compare a caller's optimistic-concurrency token inside a read transaction."""

        with self._transaction() as connection:
            case_row = self._case_row(connection, case_id)
            self._assert_expected_revision(case_row, expected_case_revision)

    def restore_verified_evidence(
        self,
        manifest: dict[str, Any],
        payloads: dict[str, bytes],
    ) -> dict[str, Any]:
        """Atomically restore documents and bytes already verified by EvidenceService."""

        role_paths: dict[str, list[str]] = {}
        for entry in cast(list[dict[str, Any]], manifest["artifacts"]):
            role_paths.setdefault(cast(str, entry["role"]), []).append(cast(str, entry["path"]))
        case_document = _decode_canonical_json(payloads[role_paths["inspection_case"][0]])
        image_documents = [
            _decode_canonical_json(payloads[path])
            for role in ("reference_image_metadata", "inspection_image_metadata")
            for path in role_paths.get(role, [])
        ]
        analysis_documents = [
            _decode_canonical_json(payloads[path]) for path in role_paths.get("analysis_result", [])
        ]
        disposition_documents = [
            _decode_canonical_json(payloads[path])
            for path in role_paths.get("human_disposition", [])
        ]

        ingestor = ImageIngestor(self.settings)
        ingested_images: dict[str, IngestedImage] = {}
        for document in image_documents:
            source = cast(dict[str, Any], document["source"])
            suffix = "jpg" if document["media_type"] == "image/jpeg" else "png"
            filename = cast(
                str,
                source.get("original_filename") or f"{document['image_id']}.{suffix}",
            )
            image = ingestor.ingest_bytes(
                payloads[cast(str, document["relative_path"])],
                filename=filename,
                declared_media_type=cast(str, document["media_type"]),
            )
            if (
                image.original_sha256 != document["sha256"]
                or image.canonical_sha256 != document["canonical_image_sha256"]
                or image.pixel_sha256 != document["pixel_sha256"]
                or image.width != document["width_px"]
                or image.height != document["height_px"]
            ):
                raise UnsafeInputError("Imported image hashes do not match", code="HASH_MISMATCH")
            ingested_images[cast(str, document["image_id"])] = image

        reference_documents = [doc for doc in image_documents if doc["role"] == "reference"]
        if len(reference_documents) != 1:
            raise UnsafeInputError(
                "Imported reference is incomplete",
                code="EVIDENCE_INCOMPLETE",
            )
        reference_id = cast(str, reference_documents[0]["image_id"])
        model = DeterministicDifferenceModel()
        results: dict[str, InspectionResult] = {}
        for document in analysis_documents:
            binding = cast(dict[str, Any], document["input_binding"])
            inspection_id = cast(str, binding["inspection_image_id"])
            result = model.inspect(ingested_images[reference_id], ingested_images[inspection_id])
            completed = cast(dict[str, Any], document["completed_output"])
            mask = cast(dict[str, Any], completed["mask"])
            if (
                result.config_hash != document["configuration_sha256"]
                or result.mask_sha256 != mask["sha256"]
                or result.mask_bytes != payloads[cast(str, mask["relative_path"])]
                or result.anomaly_score != completed["anomaly_score"]
            ):
                raise UnsafeInputError(
                    "Imported analysis does not reproduce",
                    code="HASH_MISMATCH",
                )
            results[cast(str, document["analysis_id"])] = result

        case_id = cast(str, case_document["case_id"])
        created_blobs: list[Path] = []
        try:
            with self._transaction() as connection:
                if connection.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone():
                    raise ConflictError("Imported case identifier already exists")
                identity = cast(dict[str, str], case_document["part_identity"])
                connection.execute(
                    """
                    INSERT INTO cases(
                        id, part_id, cad_revision, case_revision, locale, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'en', ?, ?)
                    """,
                    (
                        case_id,
                        identity["part_id"],
                        identity["cad_revision"],
                        case_document["case_revision"],
                        case_document["created_at"],
                        case_document["updated_at"],
                    ),
                )
                for document in image_documents:
                    image_id = cast(str, document["image_id"])
                    image = ingested_images[image_id]
                    source = cast(dict[str, Any], document["source"])
                    suffix = ".png" if image.source_format == "PNG" else ".jpg"
                    original_path = self._store_blob(
                        image.original_bytes,
                        image.original_sha256,
                        suffix,
                        created_paths=created_blobs,
                    )
                    canonical_path = self._store_blob(
                        image.canonical_bytes,
                        image.canonical_sha256,
                        ".normalized.png",
                        created_paths=created_blobs,
                    )
                    filename = cast(
                        str,
                        source.get("original_filename") or f"{image_id}{suffix}",
                    )
                    connection.execute(
                        """
                        INSERT INTO images(
                            id, case_id, role, filename, source_kind, fixture_id,
                            freecad_export_id, media_type, source_format, width, height,
                            original_sha256, canonical_sha256, pixel_sha256, original_size,
                            canonical_size, original_relpath, canonical_relpath, ingested_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            image_id,
                            case_id,
                            document["role"],
                            filename,
                            source["kind"],
                            source.get("fixture_id"),
                            source.get("freecad_export_id"),
                            image.media_type,
                            image.source_format,
                            image.width,
                            image.height,
                            image.original_sha256,
                            image.canonical_sha256,
                            image.pixel_sha256,
                            len(image.original_bytes),
                            len(image.canonical_bytes),
                            original_path,
                            canonical_path,
                            document["ingested_at"],
                        ),
                    )
                for document in analysis_documents:
                    analysis_id = cast(str, document["analysis_id"])
                    result = results[analysis_id]
                    mask_path = self._store_blob(
                        result.mask_bytes,
                        result.mask_sha256,
                        ".mask.png",
                        created_paths=created_blobs,
                    )
                    registered_path = self._store_blob(
                        result.registered_bytes,
                        result.registered_sha256,
                        ".registered.png",
                        created_paths=created_blobs,
                    )
                    payload = canonical_json_bytes(document)
                    binding = cast(dict[str, Any], document["input_binding"])
                    connection.execute(
                        """
                        INSERT INTO analyses(
                            id, case_id, case_revision, reference_image_id,
                            inspection_image_id, document_json, document_sha256,
                            registration_json, mask_sha256, mask_size, mask_relpath,
                            registered_sha256, registered_size, registered_relpath,
                            repeat_result_sha256, produced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            analysis_id,
                            case_id,
                            document["case_revision"],
                            binding["reference_image_id"],
                            binding["inspection_image_id"],
                            payload,
                            sha256_bytes(payload),
                            canonical_json_bytes(
                                {
                                    "dx": result.registration.dx,
                                    "dy": result.registration.dy,
                                    "mean_absolute_error": result.registration.mean_absolute_error,
                                }
                            ),
                            result.mask_sha256,
                            len(result.mask_bytes),
                            mask_path,
                            result.registered_sha256,
                            len(result.registered_bytes),
                            registered_path,
                            sha256_bytes(canonical_json_bytes(result.as_record())),
                            document["produced_at"],
                        ),
                    )
                for document in disposition_documents:
                    payload = canonical_json_bytes(document)
                    binding = cast(dict[str, Any], document["analysis_binding"])
                    connection.execute(
                        """
                        INSERT INTO dispositions(
                            id, analysis_id, case_id, case_revision, disposition_revision,
                            document_json, document_sha256, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document["disposition_id"],
                            binding["analysis_id"],
                            case_id,
                            document["case_revision"],
                            document["disposition_revision"],
                            payload,
                            sha256_bytes(payload),
                            document["recorded_at"],
                        ),
                    )
        except Exception:
            self._remove_created_blobs(created_blobs)
            raise
        return self.get_case_detail(case_id)

    def read_evidence_blob(self, relative_path: str, expected_sha256: str) -> bytes:
        return self._read_blob(relative_path, expected_sha256)

    def _record_analysis(
        self,
        stale_case_row: sqlite3.Row,
        reference_row: sqlite3.Row,
        inspection_row: sqlite3.Row,
        result: InspectionResult,
        *,
        expected_case_revision: int,
    ) -> dict[str, Any]:
        analysis_id = f"analysis-{uuid.uuid4().hex[:16]}"
        produced_at = _timestamp()
        created_blobs: list[Path] = []
        try:
            with self._transaction() as connection:
                case_row = self._case_row(connection, cast(str, stale_case_row["id"]))
                self._assert_expected_revision(case_row, expected_case_revision)
                existing = connection.execute(
                    """
                    SELECT document_json FROM analyses
                    WHERE case_id = ? AND inspection_image_id = ?
                    """,
                    (case_row["id"], inspection_row["id"]),
                ).fetchone()
                if existing is not None:
                    return _decode_canonical_json(existing["document_json"])
                mask_path = self._store_blob(
                    result.mask_bytes,
                    result.mask_sha256,
                    ".mask.png",
                    created_paths=created_blobs,
                )
                registered_path = self._store_blob(
                    result.registered_bytes,
                    result.registered_sha256,
                    ".registered.png",
                    created_paths=created_blobs,
                )
                case_revision = cast(int, case_row["case_revision"]) + 1
                document = self._analysis_document(
                    analysis_id=analysis_id,
                    case_row=case_row,
                    case_revision=case_revision,
                    reference_row=reference_row,
                    inspection_row=inspection_row,
                    result=result,
                    produced_at=produced_at,
                )
                payload = canonical_json_bytes(document)
                registration_payload = canonical_json_bytes(
                    {
                        "dx": result.registration.dx,
                        "dy": result.registration.dy,
                        "mean_absolute_error": result.registration.mean_absolute_error,
                    }
                )
                connection.execute(
                    """
                    INSERT INTO analyses(
                        id, case_id, case_revision, reference_image_id, inspection_image_id,
                        document_json, document_sha256, registration_json, mask_sha256,
                        mask_size, mask_relpath, registered_sha256, registered_size,
                        registered_relpath, repeat_result_sha256, produced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        case_row["id"],
                        case_revision,
                        reference_row["id"],
                        inspection_row["id"],
                        payload,
                        sha256_bytes(payload),
                        registration_payload,
                        result.mask_sha256,
                        len(result.mask_bytes),
                        mask_path,
                        result.registered_sha256,
                        len(result.registered_bytes),
                        registered_path,
                        sha256_bytes(canonical_json_bytes(result.as_record())),
                        produced_at,
                    ),
                )
                self._bump_case(connection, cast(str, case_row["id"]), case_revision, produced_at)
        except Exception:
            self._remove_created_blobs(created_blobs)
            raise
        return document

    def _analysis_document(
        self,
        *,
        analysis_id: str,
        case_row: sqlite3.Row,
        case_revision: int,
        reference_row: sqlite3.Row,
        inspection_row: sqlite3.Row,
        result: InspectionResult,
        produced_at: str,
    ) -> dict[str, Any]:
        anomaly_threshold = 0.0025
        classification = "anomaly" if result.anomaly_score >= anomaly_threshold else "normal"
        normalization_parameters = {
            "method": "none",
            "source_width_px": inspection_row["width"],
            "source_height_px": inspection_row["height"],
            "target_width_px": reference_row["width"],
            "target_height_px": reference_row["height"],
        }
        feature_findings: list[dict[str, Any]] = [
            {
                "mapping_status": "mapped",
                "feature_id": score.feature_id,
                "anomaly_score": score.anomaly_fraction,
                "mask_fraction": score.anomaly_fraction,
                "mapping_confidence": 1.0,
                "mapping_method": "feature_map_overlap",
            }
            for score in result.feature_scores
            if score.anomaly_pixels > 0
        ]
        if result.anomaly_pixels > 0 and not feature_findings:
            feature_findings.append(
                {
                    "mapping_status": "unmapped",
                    "feature_id": None,
                    "anomaly_score": result.anomaly_score,
                    "mask_fraction": result.anomaly_score,
                    "mapping_confidence": 0.0,
                    "mapping_method": "unmapped",
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "analysis_id": analysis_id,
            "case_id": case_row["id"],
            "case_revision": case_revision,
            "part_identity": self._part_identity(case_row),
            "input_binding": {
                "reference_image_id": reference_row["id"],
                "reference_image_sha256": reference_row["original_sha256"],
                "reference_canonical_image_sha256": reference_row["canonical_sha256"],
                "reference_pixel_sha256": reference_row["pixel_sha256"],
                "inspection_image_id": inspection_row["id"],
                "inspection_image_sha256": inspection_row["original_sha256"],
                "inspection_canonical_image_sha256": inspection_row["canonical_sha256"],
                "inspection_pixel_sha256": inspection_row["pixel_sha256"],
                "normalization": {
                    "method": "none",
                    "authorization": "not_required",
                    **normalization_parameters,
                    "parameters_sha256": sha256_bytes(
                        canonical_json_bytes(normalization_parameters)
                    ),
                },
            },
            "pipeline": {
                "pipeline_id": result.pipeline_id,
                "pipeline_version": result.pipeline_version,
            },
            "model": {
                "model_id": result.model_name,
                "model_version": result.model_version,
                "model_artifact_sha256": MODEL_ARTIFACT_SHA256,
            },
            "configuration_sha256": result.config_hash,
            "execution": {
                "runtime_id": "python-numpy",
                "runtime_version": f"{sys.version_info.major}.{sys.version_info.minor}",
                "deterministic": True,
                "random_seed": None,
            },
            "result_status": "completed",
            "completed_output": {
                "anomaly_score": result.anomaly_score,
                "threshold": anomaly_threshold,
                "automated_classification": classification,
                "mask": {
                    "relative_path": f"artifacts/masks/{analysis_id}.png",
                    "media_type": "image/png",
                    "sha256": result.mask_sha256,
                    "byte_size": len(result.mask_bytes),
                    "width_px": inspection_row["width"],
                    "height_px": inspection_row["height"],
                    "pixel_encoding": "uint8-binary-0-255",
                },
                "feature_findings": feature_findings,
            },
            "produced_at": produced_at,
            "warnings": [],
            "limitations": [LIMITATION],
        }

    def _analysis_for_image(self, case_id: str, image_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT document_json FROM analyses WHERE case_id = ? AND inspection_image_id = ?",
                (case_id, image_id),
            ).fetchone()
        return None if row is None else _decode_canonical_json(row["document_json"])

    def _case_document(
        self,
        case_row: sqlite3.Row,
        image_rows: list[sqlite3.Row],
        analysis_rows: list[sqlite3.Row],
        disposition_rows: list[sqlite3.Row],
    ) -> dict[str, Any]:
        reference_ids = [row["id"] for row in image_rows if row["role"] == "reference"]
        inspection_ids = [row["id"] for row in image_rows if row["role"] == "inspection"]
        latest_disposed_analyses = {row["analysis_id"] for row in disposition_rows}
        if not reference_ids or not inspection_ids:
            status = "draft"
        elif not analysis_rows:
            status = "ready"
        elif len(latest_disposed_analyses) >= len(analysis_rows) and len(analysis_rows) == len(
            inspection_ids
        ):
            status = "disposed"
        else:
            status = "analyzed"
        config = DeterministicDifferenceModel().config
        return {
            "schema_version": SCHEMA_VERSION,
            "case_id": case_row["id"],
            "case_revision": case_row["case_revision"],
            "status": status,
            "part_identity": self._part_identity(case_row),
            "reference_image_id": reference_ids[0] if reference_ids else None,
            "inspection_image_ids": inspection_ids,
            "analysis_configuration": {
                "pipeline": {
                    "pipeline_id": "registered-difference",
                    "pipeline_version": "1.0.0",
                },
                "model": {
                    "model_id": DeterministicDifferenceModel.model_name,
                    "model_version": DeterministicDifferenceModel.model_version,
                    "model_artifact_sha256": MODEL_ARTIFACT_SHA256,
                },
                "configuration_sha256": config.config_hash,
                "normalization_policy": "reject_mismatch",
            },
            "feature_ids": sorted(DEFAULT_FEATURE_REGIONS),
            "created_at": case_row["created_at"],
            "updated_at": case_row["updated_at"],
            "limitations": [LIMITATION],
        }

    def _image_document(self, row: sqlite3.Row, case_row: sqlite3.Row) -> dict[str, Any]:
        source: dict[str, str] = {"kind": cast(str, row["source_kind"])}
        if row["source_kind"] == "synthetic_fixture":
            source["fixture_id"] = cast(str, row["fixture_id"])
        elif row["source_kind"] == "freecad_export":
            source["freecad_export_id"] = cast(str, row["freecad_export_id"])
        else:
            source["original_filename"] = cast(str, row["filename"])
        suffix = "png" if row["source_format"] == "PNG" else "jpg"
        return {
            "schema_version": SCHEMA_VERSION,
            "image_id": row["id"],
            "case_id": row["case_id"],
            "part_identity": self._part_identity(case_row),
            "role": row["role"],
            "relative_path": f"artifacts/images/{row['id']}.source.{suffix}",
            "media_type": row["media_type"],
            "sha256": row["original_sha256"],
            "canonical_image_sha256": row["canonical_sha256"],
            "pixel_sha256": row["pixel_sha256"],
            "byte_size": row["original_size"],
            "width_px": row["width"],
            "height_px": row["height"],
            "pixel_count": cast(int, row["width"]) * cast(int, row["height"]),
            "channels": 3,
            "bit_depth": 8,
            "decoder": {
                "decoder_id": "pillow",
                "decoder_version": pillow_version,
                "orientation_policy": "exif_transpose_then_strip_metadata",
                "canonical_color_mode": "RGB8",
            },
            "ingested_at": row["ingested_at"],
            "source": source,
        }

    def _ingested_from_row(self, row: sqlite3.Row) -> IngestedImage:
        original = self._read_blob(
            cast(str, row["original_relpath"]), cast(str, row["original_sha256"])
        )
        canonical = self._read_blob(
            cast(str, row["canonical_relpath"]), cast(str, row["canonical_sha256"])
        )
        return IngestedImage(
            original_bytes=original,
            canonical_bytes=canonical,
            original_sha256=cast(str, row["original_sha256"]),
            canonical_sha256=cast(str, row["canonical_sha256"]),
            pixel_sha256=cast(str, row["pixel_sha256"]),
            width=cast(int, row["width"]),
            height=cast(int, row["height"]),
            source_format=cast(str, row["source_format"]),
            media_type=cast(str, row["media_type"]),
            filename=cast(str, row["filename"]),
        )

    def _store_blob(
        self,
        data: bytes,
        digest: str,
        suffix: str,
        *,
        created_paths: list[Path] | None = None,
    ) -> str:
        if sha256_bytes(data) != digest:
            raise UnsafeInputError("Blob hash does not match content", code="HASH_MISMATCH")
        relative = Path(digest[:2]) / f"{digest}{suffix}"
        destination = self._safe_blob_path(relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_symlink() or sha256_bytes(destination.read_bytes()) != digest:
                raise ConflictError("Content-addressed storage conflict")
            return relative.as_posix()
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            if created_paths is not None:
                created_paths.append(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return relative.as_posix()

    @staticmethod
    def _remove_created_blobs(paths: list[Path]) -> None:
        for path in reversed(paths):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass

    def _read_blob(self, relative_path: str, expected_sha256: str) -> bytes:
        path = self._safe_blob_path(relative_path)
        if path.is_symlink() or not path.is_file():
            raise UnsafeInputError("Evidence artifact is missing", code="EVIDENCE_INCOMPLETE")
        data = path.read_bytes()
        if sha256_bytes(data) != expected_sha256:
            raise UnsafeInputError("Evidence artifact hash mismatch", code="HASH_MISMATCH")
        return data

    def _safe_blob_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if (
            candidate.is_absolute()
            or not candidate.parts
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise UnsafeInputError("Unsafe storage path", code="UNSAFE_PATH")
        root = self.settings.blob_dir.resolve()
        destination = (root / candidate).resolve()
        if not destination.is_relative_to(root):
            raise UnsafeInputError("Unsafe storage path", code="UNSAFE_PATH")
        return destination

    def _case_row(self, connection: sqlite3.Connection, case_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise NotFoundError("Case was not found")
        return row

    def _get_case_row(self, case_id: str) -> sqlite3.Row:
        with closing(self._connect()) as connection:
            return self._case_row(connection, case_id)

    @staticmethod
    def _part_identity(case_row: sqlite3.Row) -> dict[str, str]:
        return {
            "part_id": cast(str, case_row["part_id"]),
            "cad_revision": cast(str, case_row["cad_revision"]),
        }

    @staticmethod
    def _bump_case(
        connection: sqlite3.Connection,
        case_id: str,
        case_revision: int,
        updated_at: str,
    ) -> None:
        connection.execute(
            "UPDATE cases SET case_revision = ?, updated_at = ? WHERE id = ?",
            (case_revision, updated_at, case_id),
        )

    @staticmethod
    def _assert_expected_revision(case_row: sqlite3.Row, expected: int) -> None:
        if isinstance(expected, bool) or expected < 1:
            raise UnsafeInputError("Expected case revision is invalid", code="SCHEMA_INVALID")
        actual = cast(int, case_row["case_revision"])
        if expected != actual:
            raise IdentityMismatchError(
                "Case revision does not match",
                code="REVISION_MISMATCH",
                details={
                    "case_id": case_row["id"],
                    "expected_case_revision": expected,
                    "actual_case_revision": actual,
                },
            )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_identifier(value: str, field: str) -> None:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise UnsafeInputError(f"{field} is malformed", code="SCHEMA_INVALID")


def _decode_canonical_json(data: bytes | str) -> dict[str, Any]:
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise UnsafeInputError("Stored document is malformed", code="SCHEMA_INVALID")
    return cast(dict[str, Any], parsed)
