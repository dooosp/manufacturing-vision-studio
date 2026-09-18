"""CAD byte/region/analysis/review round-trip and bounded synthetic evaluation."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from cad_binding_fixtures import pin_source, write_minimal_cad_export

from manufacturing_vision_studio.adapters import FreeCADExportAdapter
from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import MVSError
from manufacturing_vision_studio.evidence import EvidenceService, payload_inventory_hash
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.registry import CaseRegistry


def build_cad_case(root: Path):
    settings = Settings(data_dir=root / "data")
    registry = CaseRegistry(settings)
    registry.create_case(part_id="USB-REF-ADAPTER", cad_revision="R1", case_id="case-cad")
    source = write_minimal_cad_export(root / "source")
    pin_source(settings, source)
    FreeCADExportAdapter(settings).import_reference(
        registry, "case-cad", source, expected_case_revision=1
    )
    registry.add_inspection(
        "case-cad",
        ImageIngestor(settings).ingest_bytes(
            (source / "reference.png").read_bytes(), filename="unlabeled-smoke.png"
        ),
        expected_case_revision=2,
    )
    result = registry.analyze_case("case-cad", expected_case_revision=3)[0]
    registry.add_disposition(
        "case-cad",
        analysis_id=result["analysis_id"],
        decision="needs_review",
        reviewer_id="synthetic-script-g4",
        rationale="Scripted synthetic disposition; no human approval.",
        reason_codes=["insufficient_evidence"],
        expected_case_revision=4,
    )
    return EvidenceService(registry, settings), source


@pytest.fixture(scope="module")
def cad_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("cad-roundtrip")
    service, source = build_cad_case(root)
    expected_payloads = service.registry.get_cad_reference("case-cad")[1]
    exported = service.export_case("case-cad", expected_case_revision=5)
    raw = exported.path.read_bytes()
    selection = (service.settings.data_dir / "trusted-cad-sources.json").read_bytes()
    shutil.rmtree(source)
    return raw, selection, expected_payloads


def target_service(root: Path, selection: bytes | None):
    settings = Settings(data_dir=root)
    registry = CaseRegistry(settings)
    if selection is not None:
        (root / "trusted-cad-sources.json").write_bytes(selection)
    return EvidenceService(registry, settings)


def test_cad_bundle_roundtrip_preserves_binding_and_unassessed_scope(cad_bundle, tmp_path):
    raw, selection, expected_payloads = cad_bundle
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        for name, data in expected_payloads.items():
            assert archive.read("cad-reference/" + name) == data
        report = json.loads(archive.read("records/evaluation-report.json"))
        assert report["schema_version"] == "1.1.0"
        assert report["evaluation_scope"]["performance_claim"] is False
        assert report["classification_metrics"]["accuracy"] is None
        assert report["dataset"]["positive_count"] is None
        assert report["verdict"] == "inconclusive"
    service = target_service(tmp_path / "restored", selection)
    verified = service.import_bundle(raw)
    assert verified.valid
    detail = service.registry.get_case_detail("case-cad")
    assert detail["case"]["feature_ids"] == [
        f"hole_{g}{i}" for g in ("H", "P") for i in range(1, 5)
    ]
    assert detail["dispositions"][0]["reviewer"]["reviewer_id"] == "synthetic-script-g4"
    assert service.registry.get_cad_reference("case-cad")[1] == expected_payloads
    assert service.export_case("case-cad", expected_case_revision=5).path.read_bytes() == raw


def rewrite_bundle(raw, mutate):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files.pop("bundle-manifest.json"))
    files.pop("bundle-manifest.sha256")
    mutate(files)
    for entry in manifest["artifacts"]:
        data = files[entry["path"]]
        entry.update(sha256=sha256_bytes(data), byte_size=len(data))
    manifest["payload_byte_size"] = sum(len(data) for data in files.values())
    manifest["payload_sha256"] = payload_inventory_hash(manifest["artifacts"])
    manifest["bundle_id"] = "bundle-" + manifest["payload_sha256"][:24]
    files["bundle-manifest.json"] = canonical_json_bytes(manifest)
    files["bundle-manifest.sha256"] = (sha256_bytes(files["bundle-manifest.json"]) + "\n").encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def test_cad_bundle_import_requires_external_selection(cad_bundle, tmp_path):
    raw, _, _ = cad_bundle
    service = target_service(tmp_path / "unselected", None)
    with pytest.raises(MVSError):
        service.import_bundle(raw)
    assert service.registry.list_cases() == []
    assert not any(p.is_file() for p in service.settings.blob_dir.rglob("*"))


def test_rehashed_cad_manifest_cannot_break_case_binding(cad_bundle, tmp_path):
    raw, selection, _ = cad_bundle

    def mutate(files):
        name = "cad-reference/freecad-export-adapter-manifest.json"
        doc = json.loads(files[name])
        doc["export_id"] = "forged-export"
        files[name] = canonical_json_bytes(doc)

    corrupted = rewrite_bundle(raw, mutate)
    with pytest.raises(MVSError):
        target_service(tmp_path / "broken", selection).verify_bundle(corrupted)


def test_coherent_rehash_still_requires_selected_source(cad_bundle, tmp_path):
    raw, selection, _ = cad_bundle

    def mutate(files):
        name = "cad-reference/freecad-export-adapter-manifest.json"
        doc = json.loads(files[name])
        doc["export_id"] = "forged-export"
        files[name] = canonical_json_bytes(doc)
        new_binding = {"export_id": "forged-export", "manifest_sha256": sha256_bytes(files[name])}
        case = json.loads(files["records/inspection-case.json"])
        case["freecad_adapter_binding"] = new_binding
        files["records/inspection-case.json"] = canonical_json_bytes(case)
        analysis_path = next(p for p in files if p.startswith("records/analyses/"))
        analysis = json.loads(files[analysis_path])
        analysis["cad_binding"].update(new_binding)
        files[analysis_path] = canonical_json_bytes(analysis)
        disposition_path = next(p for p in files if p.startswith("records/dispositions/"))
        disposition = json.loads(files[disposition_path])
        disposition["analysis_binding"]["analysis_result_sha256"] = sha256_bytes(
            files[analysis_path]
        )
        files[disposition_path] = canonical_json_bytes(disposition)

    changed = rewrite_bundle(raw, mutate)
    service = target_service(tmp_path / "coherent", selection)
    assert service.verify_bundle(changed).valid  # internal consistency is not source selection
    with pytest.raises(MVSError, match="pinned selection"):
        service.import_bundle(changed)
    assert service.registry.list_cases() == []


def test_fabricated_feature_finding_is_rejected_after_control_rehash(cad_bundle, tmp_path):
    raw, selection, _ = cad_bundle

    def mutate(files):
        path = next(p for p in files if p.startswith("records/analyses/"))
        analysis = json.loads(files[path])
        analysis["completed_output"]["feature_findings"] = [
            {
                "mapping_status": "mapped",
                "feature_id": "hole_H1",
                "anomaly_score": 0.8,
                "mask_fraction": 0.8,
                "mapping_confidence": 1.0,
                "mapping_method": "feature_map_overlap",
            }
        ]
        files[path] = canonical_json_bytes(analysis)
        review_path = next(p for p in files if p.startswith("records/dispositions/"))
        review = json.loads(files[review_path])
        review["analysis_binding"]["analysis_result_sha256"] = sha256_bytes(files[path])
        files[review_path] = canonical_json_bytes(review)

    with pytest.raises(MVSError, match="does not reproduce"):
        target_service(tmp_path / "fabricated", selection).verify_bundle(
            rewrite_bundle(raw, mutate)
        )


def test_bundle_restore_storage_error_rolls_back_all_records(cad_bundle, tmp_path, monkeypatch):
    raw, selection, _ = cad_bundle
    service = target_service(tmp_path / "storage-failure", selection)
    store = service.registry._store_blob
    count = 0

    def failing_store(*args, **kwargs):
        nonlocal count
        value = store(*args, **kwargs)
        count += 1
        if count == 2:
            raise OSError("bundle storage failure")
        return value

    monkeypatch.setattr(service.registry, "_store_blob", failing_store)
    with pytest.raises(OSError, match="bundle storage failure"):
        service.import_bundle(raw)
    assert service.registry.list_cases() == []
    assert not any(p.is_file() for p in service.settings.blob_dir.rglob("*"))


@pytest.mark.parametrize(
    "field,value", [("threshold", 0.5), ("automated_classification", "anomaly")]
)
def test_cad_classification_policy_cannot_be_forged(cad_bundle, tmp_path, field, value):
    raw, selection, _ = cad_bundle

    def mutate(files):
        path = next(p for p in files if p.startswith("records/analyses/"))
        analysis = json.loads(files[path])
        analysis["completed_output"][field] = value
        files[path] = canonical_json_bytes(analysis)
        review_path = next(p for p in files if p.startswith("records/dispositions/"))
        review = json.loads(files[review_path])
        review["analysis_binding"]["analysis_result_sha256"] = sha256_bytes(files[path])
        files[review_path] = canonical_json_bytes(review)

    with pytest.raises(MVSError, match="does not reproduce"):
        target_service(tmp_path / "policy-forgery", selection).verify_bundle(
            rewrite_bundle(raw, mutate)
        )
