from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import stat
import warnings
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical import canonical_json_bytes
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import MVSError
from manufacturing_vision_studio.evidence import EvidenceService
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.registry import CaseRegistry

MANIFEST = "bundle-manifest.json"
SIDECAR = "bundle-manifest.sha256"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V010_BUNDLE_SHA256 = "1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rendered_image(*, defect: bool) -> bytes:
    image = Image.new("RGB", (64, 48))
    pixels = image.load()
    assert pixels is not None
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = ((x * 3 + y) % 180, (y * 5 + x) % 180, (x + y * 2) % 180)
    if defect:
        ImageDraw.Draw(image).rectangle((28, 19, 36, 27), fill=(255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def build_disposed_case(root: Path) -> tuple[EvidenceService, CaseRegistry, int]:
    settings = Settings(data_dir=root)
    registry = CaseRegistry(settings)
    ingestor = ImageIngestor(settings)
    registry.create_case(
        part_id="PART-EVIDENCE",
        cad_revision="REV-A",
        case_id="case-evidence",
    )
    registry.add_reference(
        "case-evidence",
        ingestor.ingest_bytes(rendered_image(defect=False), filename="reference.png"),
        source_kind="synthetic_fixture",
        fixture_id="demo-reference",
        expected_case_revision=1,
    )
    registry.add_inspection(
        "case-evidence",
        ingestor.ingest_bytes(rendered_image(defect=True), filename="inspection.png"),
        source_kind="synthetic_fixture",
        fixture_id="demo-defect",
        expected_case_revision=2,
    )
    analysis = registry.analyze_case(
        "case-evidence",
        expected_case_revision=3,
    )[0]
    registry.add_disposition(
        "case-evidence",
        analysis_id=analysis["analysis_id"],
        decision="needs_review",
        reviewer_id="independent-qa",
        rationale="Synthetic evidence reviewed; field validation remains out of scope.",
        reason_codes=["insufficient_evidence"],
        expected_case_revision=4,
    )
    case_revision = registry.get_case_document("case-evidence")["case_revision"]
    assert case_revision == 5
    return EvidenceService(registry, settings), registry, case_revision


@pytest.fixture(scope="module")
def valid_bundle(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    service, _, revision = build_disposed_case(tmp_path_factory.mktemp("valid-bundle"))
    exported = service.export_case("case-evidence", expected_case_revision=revision)
    return exported.path.read_bytes()


def read_archive(bundle: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def write_archive(
    files: dict[str, bytes],
    *,
    modes: dict[str, int] | None = None,
    duplicate: tuple[str, bytes] | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (modes or {}).get(path, stat.S_IFREG | 0o600) << 16
            archive.writestr(info, data)
        if duplicate is not None:
            path, data = duplicate
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(info, data)
    return output.getvalue()


def payload_hash(artifacts: list[dict[str, object]]) -> str:
    projection = {
        "algorithm": "sha256",
        "artifacts": [
            {
                "path": artifact["path"],
                "sha256": artifact["sha256"],
                "byte_size": artifact["byte_size"],
            }
            for artifact in sorted(artifacts, key=lambda item: str(item["path"]))
        ],
    }
    return sha256(canonical_json_bytes(projection))


def reseal(files: dict[str, bytes]) -> bytes:
    manifest = json.loads(files[MANIFEST])
    for artifact in manifest["artifacts"]:
        data = files[artifact["path"]]
        artifact["sha256"] = sha256(data)
        artifact["byte_size"] = len(data)
    manifest["artifact_count"] = len(manifest["artifacts"])
    manifest["payload_byte_size"] = sum(artifact["byte_size"] for artifact in manifest["artifacts"])
    manifest["payload_sha256"] = payload_hash(manifest["artifacts"])
    manifest_bytes = canonical_json_bytes(manifest)
    files[MANIFEST] = manifest_bytes
    files[SIDECAR] = f"{sha256(manifest_bytes)}\n".encode()
    return write_archive(files)


def mutate_hash(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    manifest = json.loads(files[MANIFEST])
    payload_path = next(
        artifact["path"]
        for artifact in manifest["artifacts"]
        if artifact["role"] == "inspection_image"
    )
    files[payload_path] += b"tampered"
    return write_archive(files)


def remove_required_payload(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    manifest = json.loads(files[MANIFEST])
    mask_path = next(
        artifact["path"] for artifact in manifest["artifacts"] if artifact["role"] == "anomaly_mask"
    )
    del files[mask_path]
    return write_archive(files)


def add_traversal(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    files["../../outside/escaped.json"] = b"{}"
    return write_archive(files)


def add_symlink(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    path = "artifacts/linked-mask.png"
    files[path] = b"../../outside"
    return write_archive(files, modes={path: stat.S_IFLNK | 0o777})


def add_fifo(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    path = "artifacts/not-a-file"
    files[path] = b"fifo"
    return write_archive(files, modes={path: stat.S_IFIFO | 0o600})


def duplicate_manifest(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    return write_archive(files, duplicate=(MANIFEST, files[MANIFEST]))


def mutate_manifest_identity(bundle: bytes, field: str, value: str) -> bytes:
    files = read_archive(bundle)
    manifest = json.loads(files[MANIFEST])
    manifest["part_identity"][field] = value
    manifest_bytes = canonical_json_bytes(manifest)
    files[MANIFEST] = manifest_bytes
    files[SIDECAR] = f"{sha256(manifest_bytes)}\n".encode()
    return write_archive(files)


def mutate_pipeline(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    manifest = json.loads(files[MANIFEST])
    analysis_path = next(
        artifact["path"]
        for artifact in manifest["artifacts"]
        if artifact["role"] == "analysis_result"
    )
    analysis = json.loads(files[analysis_path])
    analysis["pipeline"]["pipeline_version"] = "999.0.0"
    files[analysis_path] = canonical_json_bytes(analysis)
    return reseal(files)


def corrupt_mask_with_consistent_outer_hashes(bundle: bytes) -> bytes:
    files = read_archive(bundle)
    manifest = json.loads(files[MANIFEST])
    analysis_path = next(
        artifact["path"]
        for artifact in manifest["artifacts"]
        if artifact["role"] == "analysis_result"
    )
    mask_path = next(
        artifact["path"] for artifact in manifest["artifacts"] if artifact["role"] == "anomaly_mask"
    )
    files[mask_path] = b"not-a-decodable-mask"
    analysis = json.loads(files[analysis_path])
    analysis["completed_output"]["mask"]["sha256"] = sha256(files[mask_path])
    analysis["completed_output"]["mask"]["byte_size"] = len(files[mask_path])
    files[analysis_path] = canonical_json_bytes(analysis)
    return reseal(files)


def assert_import_rejected(bundle: bytes, code: str, root: Path) -> None:
    settings = Settings(data_dir=root)
    registry = CaseRegistry(settings)
    service = EvidenceService(registry, settings)

    with pytest.raises(MVSError) as exc_info:
        service.import_bundle(bundle)

    assert exc_info.value.code == code
    assert registry.list_cases() == []
    assert not any(path.is_file() for path in settings.blob_dir.rglob("*"))


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (mutate_hash, "HASH_MISMATCH"),
        (remove_required_payload, "EVIDENCE_INCOMPLETE"),
        (add_traversal, "UNSAFE_PATH"),
        (add_symlink, "UNSAFE_PATH"),
        (add_fifo, "UNSAFE_PATH"),
        (duplicate_manifest, "DUPLICATE_ARTIFACT_PATH"),
        (mutate_pipeline, "UNKNOWN_PIPELINE_VERSION"),
        (corrupt_mask_with_consistent_outer_hashes, "MASK_CORRUPT"),
    ],
)
def test_adversarial_bundle_is_rejected_before_import_publication(
    mutator: Callable[[bytes], bytes],
    expected_code: str,
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    assert_import_rejected(mutator(valid_bundle), expected_code, tmp_path / "target")


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("part_id", "PART-SUBSTITUTED", "PART_ID_MISMATCH"),
        ("cad_revision", "REV-SUBSTITUTED", "REVISION_MISMATCH"),
    ],
)
def test_manifest_identity_substitution_is_rejected(
    field: str,
    value: str,
    expected_code: str,
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    mutated = mutate_manifest_identity(valid_bundle, field, value)
    assert_import_rejected(mutated, expected_code, tmp_path / "target")


def test_unsupported_manifest_version_is_rejected_without_import(
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    files = read_archive(valid_bundle)
    manifest = json.loads(files[MANIFEST])
    manifest["schema_version"] = "2.0.0"
    manifest_bytes = canonical_json_bytes(manifest)
    files[MANIFEST] = manifest_bytes
    files[SIDECAR] = f"{sha256(manifest_bytes)}\n".encode()

    assert_import_rejected(
        write_archive(files),
        "UNSUPPORTED_SCHEMA_VERSION",
        tmp_path / "target",
    )


def test_noncanonical_manifest_is_rejected_even_with_matching_sidecar(
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    files = read_archive(valid_bundle)
    pretty_manifest = json.dumps(json.loads(files[MANIFEST]), indent=2).encode()
    files[MANIFEST] = pretty_manifest
    files[SIDECAR] = f"{sha256(pretty_manifest)}\n".encode()

    assert_import_rejected(
        write_archive(files),
        "CANONICAL_JSON_MISMATCH",
        tmp_path / "target",
    )


@pytest.mark.parametrize(
    "limit_override",
    [
        {"max_bundle_entries": 9},
        {"max_bundle_member_bytes": 64},
        {"max_bundle_uncompressed_bytes": 100},
    ],
)
def test_archive_resource_limits_are_enforced_before_import(
    limit_override: dict[str, int],
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "target", **limit_override)
    registry = CaseRegistry(settings)

    with pytest.raises(MVSError) as exc_info:
        EvidenceService(registry, settings).import_bundle(valid_bundle)

    assert exc_info.value.code == "BUNDLE_LIMIT_EXCEEDED"
    assert registry.list_cases() == []


def test_compressed_archive_byte_limit_is_enforced(valid_bundle: bytes, tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "target",
        max_bundle_bytes=len(valid_bundle) - 1,
    )
    registry = CaseRegistry(settings)

    with pytest.raises(MVSError) as exc_info:
        EvidenceService(registry, settings).import_bundle(valid_bundle)

    assert exc_info.value.code == "BUNDLE_LIMIT_EXCEEDED"
    assert registry.list_cases() == []


def test_excessive_compression_ratio_is_rejected_before_inventory_trust(
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    files = read_archive(valid_bundle)
    files["artifacts/compression-bomb.txt"] = b"0" * 20_000

    assert_import_rejected(
        write_archive(files),
        "BUNDLE_LIMIT_EXCEEDED",
        tmp_path / "target",
    )


def test_bundle_path_symlink_and_directory_are_rejected(
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "target")
    registry = CaseRegistry(settings)
    service = EvidenceService(registry, settings)
    regular = tmp_path / "bundle.zip"
    regular.write_bytes(valid_bundle)
    symlink = tmp_path / "linked.zip"
    try:
        symlink.symlink_to(regular)
    except OSError as exc:  # pragma: no cover - platform permission guard
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(MVSError) as symlink_error:
        service.verify_bundle(symlink)
    with pytest.raises(MVSError) as directory_error:
        service.verify_bundle(tmp_path)

    assert symlink_error.value.code == "SYMLINK_INPUT"
    assert directory_error.value.code == "NON_REGULAR_INPUT"


def test_complete_bundle_verifies_reimports_and_reexports_equivalent_payloads(
    valid_bundle: bytes,
    tmp_path: Path,
) -> None:
    source_files = read_archive(valid_bundle)
    source_manifest = json.loads(source_files[MANIFEST])
    settings = Settings(data_dir=tmp_path / "target")
    target_registry = CaseRegistry(settings)
    target_service = EvidenceService(target_registry, settings)

    imported = target_service.import_bundle(valid_bundle)
    reexported = target_service.export_case(
        imported.case_id,
        expected_case_revision=imported.case_revision,
    )

    assert imported.valid is True
    assert imported.part_id == "PART-EVIDENCE"
    assert imported.cad_revision == "REV-A"
    assert imported.payload_sha256 == source_manifest["payload_sha256"]
    assert reexported.manifest["payload_sha256"] == source_manifest["payload_sha256"]
    assert {
        (item["path"], item["sha256"], item["byte_size"])
        for item in reexported.manifest["artifacts"]
    } == {
        (item["path"], item["sha256"], item["byte_size"]) for item in source_manifest["artifacts"]
    }
    assert target_registry.get_case_document(imported.case_id)["part_identity"] == {
        "part_id": "PART-EVIDENCE",
        "cad_revision": "REV-A",
    }


def test_published_v010_bundle_remains_verifiable_importable_and_exportable(
    tmp_path: Path,
) -> None:
    release_bundle = REPOSITORY_ROOT / "docs/releases/v0.1.0/evidence-bundle.zip"
    release_bytes = release_bundle.read_bytes()
    assert sha256(release_bytes) == V010_BUNDLE_SHA256

    settings = Settings(data_dir=tmp_path / "published-release-import")
    registry = CaseRegistry(settings)
    service = EvidenceService(registry, settings)

    verified = service.verify_bundle(
        release_bytes,
        expected_part_id="MVS-DEMO-001",
        expected_cad_revision="rev-A",
    )
    imported = service.import_bundle(release_bytes)
    reexported = service.export_case(
        imported.case_id,
        expected_case_revision=imported.case_revision,
    )
    reverified = service.verify_bundle(
        reexported.path,
        expected_part_id="MVS-DEMO-001",
        expected_cad_revision="rev-A",
    )

    assert verified.bundle_sha256 == V010_BUNDLE_SHA256
    assert imported.payload_sha256 == verified.payload_sha256
    assert reexported.path.read_bytes() == release_bytes
    assert reexported.bundle_sha256 == V010_BUNDLE_SHA256
    assert reexported.manifest["payload_sha256"] == verified.payload_sha256
    assert reverified.valid is True
    assert reverified.case_id == imported.case_id
    assert registry.get_case_document(imported.case_id)["status"] == "disposed"


def test_imported_evaluation_snapshot_tamper_fails_closed(tmp_path: Path) -> None:
    release_bytes = (
        REPOSITORY_ROOT / "docs/releases/v0.1.0/evidence-bundle.zip"
    ).read_bytes()
    settings = Settings(data_dir=tmp_path / "published-release-tamper")
    registry = CaseRegistry(settings)
    service = EvidenceService(registry, settings)
    imported = service.import_bundle(release_bytes)
    destination = tmp_path / "must-not-exist.zip"

    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """
            UPDATE imported_evaluation_snapshots
            SET document_json = ?
            WHERE case_id = ? AND case_revision = ?
            """,
            (b"{}", imported.case_id, imported.case_revision),
        )

    with pytest.raises(MVSError) as exc_info:
        service.export_case(
            imported.case_id,
            expected_case_revision=imported.case_revision,
            destination=destination,
        )

    assert exc_info.value.code == "HASH_MISMATCH"
    assert not destination.exists()


def test_export_is_byte_stable_and_evaluation_projection_is_deterministic(tmp_path: Path) -> None:
    service, _, revision = build_disposed_case(tmp_path / "source")

    first = service.export_case("case-evidence", expected_case_revision=revision)
    second = service.export_case("case-evidence", expected_case_revision=revision)
    files = read_archive(first.path.read_bytes())
    evaluation = json.loads(files["records/evaluation-report.json"])

    assert first.path.read_bytes() == second.path.read_bytes()
    assert first.bundle_sha256 == second.bundle_sha256
    assert first.manifest == second.manifest
    assert evaluation["dataset"]["sample_count"] == 1
    assert evaluation["reproducibility"] == {
        "repeat_count": 2,
        "metric_tolerance": 0.0,
        "equivalent": True,
        "run_result_sha256s": [
            evaluation["reproducibility"]["run_result_sha256s"][0],
            evaluation["reproducibility"]["run_result_sha256s"][0],
        ],
    }
    assert "production" in " ".join(evaluation["limitations"]).lower()


def test_incomplete_case_cannot_publish_bundle(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    ingestor = ImageIngestor(settings)
    registry.create_case(part_id="PART-001", cad_revision="A", case_id="case-incomplete")
    registry.add_reference(
        "case-incomplete",
        ingestor.ingest_bytes(rendered_image(defect=False), filename="reference.png"),
        expected_case_revision=1,
    )
    registry.add_inspection(
        "case-incomplete",
        ingestor.ingest_bytes(rendered_image(defect=True), filename="inspection.png"),
        expected_case_revision=2,
    )
    registry.analyze_case("case-incomplete", expected_case_revision=3)

    with pytest.raises(MVSError) as exc_info:
        EvidenceService(registry, settings).export_case(
            "case-incomplete",
            expected_case_revision=4,
        )

    assert exc_info.value.code == "EVIDENCE_INCOMPLETE"
    assert not any(path.is_file() for path in settings.export_dir.rglob("*"))
