import json
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest
from cad_binding_fixtures import json_bytes, pin_source, write_minimal_cad_export


def test_imported_feature_ids_reach_case(tmp_path):
    from cad_binding_fixtures import write_minimal_cad_export

    from manufacturing_vision_studio.adapters import FreeCADExportAdapter
    from manufacturing_vision_studio.config import Settings
    from manufacturing_vision_studio.registry import CaseRegistry

    settings = Settings(data_dir=tmp_path / "registry")
    registry = CaseRegistry(settings)
    registry.create_case(part_id="USB-REF-ADAPTER", cad_revision="R1", case_id="case-r1")
    source = write_minimal_cad_export(tmp_path / "source")
    pin_source(settings, source)
    detail = FreeCADExportAdapter(settings).import_reference(
        registry, "case-r1", source, expected_case_revision=1
    )
    expected = [f"hole_{group}{i}" for group in ("H", "P") for i in range(1, 5)]
    assert detail["case"]["feature_ids"] == expected
    assert detail["case"]["freecad_adapter_binding"]["manifest_sha256"]


def read_payloads(root: Path):
    return (root / "freecad-export-adapter-manifest.json").read_bytes(), {
        name: (root / name).read_bytes()
        for name in ["reference.png", "feature-map.json", "cad-metadata.json"]
    }


def rehash(manifest, artifacts):
    for entry in manifest["artifacts"]:
        data = artifacts[entry["relative_path"]]
        entry["sha256"] = sha256(data).hexdigest()
        entry["byte_size"] = len(data)
    return json_bytes(manifest)


def test_contract_binding_is_immutable_and_keeps_source_hash(tmp_path):
    from manufacturing_vision_studio.cad_binding import validate_cad_binding

    raw, artifacts = read_payloads(write_minimal_cad_export(tmp_path / "source"))
    result = validate_cad_binding(raw, artifacts)
    assert result.feature_regions[0][0] == "hole_H1"
    assert len(result.feature_regions) == 8
    assert result.manifest_sha256 == sha256(raw).hexdigest()
    assert result.source_manifest_sha256 == json.loads(raw)["source_manifest_sha256"]
    assert result.manifest_sha256 != result.source_manifest_sha256
    with pytest.raises(FrozenInstanceError):
        result.cad_revision = "R2"


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "inverted",
        "nan",
        "outside",
        "feature_mismatch",
        "metadata_part",
        "metadata_revision",
        "hash",
        "size",
        "unknown_profile",
        "view",
        "source_hash",
        "rehash_different_source",
        "duplicate_json_key",
        "image_size",
        "zero_pixel_area",
    ],
)
def test_contract_rejects_invalid_bindings(tmp_path, change):
    from manufacturing_vision_studio.cad_binding import validate_cad_binding
    from manufacturing_vision_studio.errors import MVSError

    raw, artifacts = read_payloads(write_minimal_cad_export(tmp_path / "source"))
    manifest = json.loads(raw)
    feature_map = json.loads(artifacts["feature-map.json"])
    metadata = json.loads(artifacts["cad-metadata.json"])
    expected = {"source_manifest_sha256": manifest["source_manifest_sha256"]}
    if change == "duplicate":
        manifest["features"][1]["feature_id"] = "hole_H1"
    elif change == "inverted":
        manifest["features"][0]["normalized_region"]["x_min"] = 0.9
    elif change == "nan":
        manifest["features"][0]["normalized_region"]["x_min"] = float("nan")
    elif change == "outside":
        manifest["features"][0]["normalized_region"]["x_min"] = -0.1
    elif change == "feature_mismatch":
        feature_map["features"][0]["normalized_region"]["x_min"] += 0.001
    elif change == "metadata_part":
        metadata["part_identity"]["part_id"] = "wrong-part"
    elif change == "metadata_revision":
        metadata["part_identity"]["cad_revision"] = "R2"
    elif change == "unknown_profile":
        metadata["profile"] = "unknown/v1"
    elif change == "view":
        metadata["cad_to_pixel"][1][1] = 10
    elif change == "source_hash":
        metadata["source_manifest_sha256"] = "0" * 64
    elif change == "rehash_different_source":
        metadata["source_manifest_payload"]["kind"] = "other-source"
        new_hash = sha256(json_bytes(metadata["source_manifest_payload"])).hexdigest()
        metadata["source_manifest_sha256"] = new_hash
        manifest["source_manifest_sha256"] = new_hash
    elif change == "image_size":
        import io

        from PIL import Image

        out = io.BytesIO()
        Image.new("RGB", (64, 48)).save(out, format="PNG")
        artifacts["reference.png"] = out.getvalue()
    if change in {"duplicate", "inverted", "nan", "outside"}:
        feature_map["features"] = manifest["features"]
    if change == "zero_pixel_area":
        manifest["features"][0]["normalized_region"].update(x_min=0.1, x_max=0.10000000001)
        feature_map["features"] = manifest["features"]
    artifacts["feature-map.json"] = json_bytes(feature_map)
    artifacts["cad-metadata.json"] = json_bytes(metadata)
    raw = rehash(manifest, artifacts)
    if change == "hash":
        artifacts["cad-metadata.json"] += b" "
    elif change == "size":
        manifest["artifacts"][0]["byte_size"] += 1
        raw = json_bytes(manifest)
    elif change == "duplicate_json_key":
        raw = raw.replace(
            b'"schema_version": "1.0.0"', b'"schema_version":"1.0.0", "schema_version":"1.0.0"'
        )
    with pytest.raises(MVSError):
        validate_cad_binding(raw, artifacts, expected_source=expected)


def test_contract_model_restores_half_open_pixel_regions(tmp_path):
    from manufacturing_vision_studio.cad_binding import validate_cad_binding
    from manufacturing_vision_studio.images import ImageIngestor
    from manufacturing_vision_studio.model import DeterministicDifferenceModel

    raw, artifacts = read_payloads(write_minimal_cad_export(tmp_path / "source"))
    binding = validate_cad_binding(raw, artifacts)
    image = ImageIngestor().ingest_bytes(artifacts["reference.png"], filename="reference.png")
    result = DeterministicDifferenceModel().inspect(image, image, feature_regions=binding.regions())
    assert [(x.feature_id, x.region_pixels, x.anomaly_pixels) for x in result.feature_scores] == [
        ("hole_H1", 3600, 0),
        ("hole_H2", 3600, 0),
        ("hole_H3", 3600, 0),
        ("hole_H4", 3600, 0),
        ("hole_P1", 5776, 0),
        ("hole_P2", 5776, 0),
        ("hole_P3", 5776, 0),
        ("hole_P4", 5776, 0),
    ]
    assert sha256(Path("tests/fixtures/cad-binding/profile-v1.json").read_bytes()).hexdigest() == (
        "8227681470be0754e3c1b17d5e1f4d1d3c2fd5afe947013c06172aeabe4f5045"
    )


def setup_import(tmp_path, *, pin=True):
    from manufacturing_vision_studio.adapters import FreeCADExportAdapter
    from manufacturing_vision_studio.config import Settings
    from manufacturing_vision_studio.registry import CaseRegistry

    settings = Settings(data_dir=tmp_path / "registry")
    registry = CaseRegistry(settings)
    registry.create_case(part_id="USB-REF-ADAPTER", cad_revision="R1", case_id="case-r1")
    source = write_minimal_cad_export(tmp_path / "source")
    if pin:
        pin_source(settings, source)
    return registry, FreeCADExportAdapter(settings), source


def test_analysis_and_repeat_receive_actual_regions(tmp_path):
    import io

    from PIL import Image, ImageDraw

    from manufacturing_vision_studio.images import ImageIngestor
    from manufacturing_vision_studio.model import DeterministicDifferenceModel

    registry, adapter, source = setup_import(tmp_path)
    adapter.import_reference(registry, "case-r1", source, expected_case_revision=1)
    with Image.open(source / "reference.png") as image:
        ImageDraw.Draw(image).ellipse((320, 526, 360, 566), fill=(180, 180, 180))
        out = io.BytesIO()
        image.save(out, format="PNG")
    registry.add_inspection(
        "case-r1",
        ImageIngestor().ingest_bytes(out.getvalue(), filename="sample.png"),
        expected_case_revision=2,
    )
    calls = []

    class ObservedModel(DeterministicDifferenceModel):
        def inspect(self, reference, inspection, *, feature_regions=None):
            assert feature_regions is not None, "CAD regions lost before model invocation"
            calls.append(tuple(sorted(feature_regions)))
            return super().inspect(reference, inspection, feature_regions=feature_regions)

    analysis = registry.analyze_case("case-r1", model=ObservedModel(), expected_case_revision=3)[0]
    expected = tuple(f"hole_{g}{i}" for g in ("H", "P") for i in range(1, 5))
    assert calls == [expected, expected]
    assert analysis["schema_version"] == "1.1.0"
    assert analysis["cad_binding"]["manifest_sha256"] == pin_source(registry.settings, source)
    assert [x["feature_id"] for x in analysis["completed_output"]["feature_findings"]] == [
        "hole_H1"
    ]
    from manufacturing_vision_studio.schema_validation import validate_document

    validate_document(analysis, "analysis-result")
    assert registry.analyze_case("case-r1", model=ObservedModel(), expected_case_revision=4) == [
        analysis
    ]
    assert len(calls) == 2


@pytest.mark.parametrize(
    "failure",
    [
        "unselected",
        "stale",
        "rehashed_roi",
        "rehashed_metadata",
        "part",
        "revision",
        "source_changed",
    ],
)
def test_cad_import_failures_leave_case_and_blobs_unchanged(tmp_path, monkeypatch, failure):
    from manufacturing_vision_studio.errors import MVSError

    registry, adapter, source = setup_import(tmp_path, pin=failure != "unselected")
    before = registry.get_case_detail("case-r1")
    manifest_path = source / "freecad-export-adapter-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    artifacts = read_payloads(source)[1]
    if failure == "rehashed_roi":
        manifest["features"][0]["normalized_region"]["x_min"] += 0.001
        fmap = json.loads(artifacts["feature-map.json"])
        fmap["features"] = manifest["features"]
        artifacts["feature-map.json"] = json_bytes(fmap)
    elif failure in {"rehashed_metadata", "part", "revision"}:
        metadata = json.loads(artifacts["cad-metadata.json"])
        if failure == "rehashed_metadata":
            metadata["source_manifest_payload"]["kind"] = "different-source"
            h = sha256(json_bytes(metadata["source_manifest_payload"])).hexdigest()
            metadata["source_manifest_sha256"] = manifest["source_manifest_sha256"] = h
        else:
            field = "part_id" if failure == "part" else "cad_revision"
            metadata["part_identity"][field] = manifest["part_identity"][field] = "OTHER"
        artifacts["cad-metadata.json"] = json_bytes(metadata)
    if failure in {"rehashed_roi", "rehashed_metadata", "part", "revision"}:
        for name, data in artifacts.items():
            (source / name).write_bytes(data)
        manifest_path.write_bytes(rehash(manifest, artifacts))
    if failure == "source_changed":
        validate = adapter.validate

        def mutate_after_validation(*args, **kwargs):
            result = validate(*args, **kwargs)
            (source / "feature-map.json").write_bytes(b"changed after validation")
            return result

        monkeypatch.setattr(adapter, "validate", mutate_after_validation)
    with pytest.raises(MVSError):
        adapter.import_reference(
            registry, "case-r1", source, expected_case_revision=2 if failure == "stale" else 1
        )
    assert registry.get_case_detail("case-r1") == before
    assert list(registry.settings.blob_dir.rglob("*")) == []


def test_cad_blob_failure_rolls_back_reference_binding_and_revision(tmp_path, monkeypatch):
    registry, adapter, source = setup_import(tmp_path)
    before = registry.get_case_detail("case-r1")
    store = registry._store_blob
    calls = 0

    def fail_after_write(*args, **kwargs):
        nonlocal calls
        result = store(*args, **kwargs)
        calls += 1
        if calls == 3:
            raise OSError("simulated storage failure")
        return result

    monkeypatch.setattr(registry, "_store_blob", fail_after_write)
    with pytest.raises(OSError, match="simulated storage failure"):
        adapter.import_reference(registry, "case-r1", source, expected_case_revision=1)
    assert registry.get_case_detail("case-r1") == before
    assert not any(p.is_file() for p in registry.settings.blob_dir.rglob("*"))


def test_missing_cad_binding_never_falls_back_to_demo(tmp_path):
    from manufacturing_vision_studio.errors import MVSError

    registry, adapter, source = setup_import(tmp_path)
    adapter.import_reference(registry, "case-r1", source, expected_case_revision=1)
    with registry._connect() as connection:
        connection.execute("DELETE FROM cad_bindings WHERE case_id = 'case-r1'")
    with pytest.raises(MVSError, match="binding"):
        registry.get_case_detail("case-r1")


def test_cad_reference_cannot_be_replaced(tmp_path):
    from manufacturing_vision_studio.errors import MVSError

    registry, adapter, source = setup_import(tmp_path)
    detail = adapter.import_reference(registry, "case-r1", source, expected_case_revision=1)
    before = {str(p): p.read_bytes() for p in registry.settings.blob_dir.rglob("*") if p.is_file()}
    with pytest.raises(MVSError):
        adapter.import_reference(registry, "case-r1", source, expected_case_revision=2)
    assert registry.get_case_detail("case-r1") == detail
    assert {
        str(p): p.read_bytes() for p in registry.settings.blob_dir.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize("field", ["cad_binding", "configuration_sha256", "reference_image_sha256"])
def test_cached_cad_analysis_rejects_mismatched_binding(tmp_path, field):
    from manufacturing_vision_studio.canonical import canonical_json_bytes
    from manufacturing_vision_studio.errors import MVSError
    from manufacturing_vision_studio.images import ImageIngestor

    registry, adapter, source = setup_import(tmp_path)
    adapter.import_reference(registry, "case-r1", source, expected_case_revision=1)
    registry.add_inspection(
        "case-r1",
        ImageIngestor().ingest_bytes(
            (source / "reference.png").read_bytes(), filename="sample.png"
        ),
        expected_case_revision=2,
    )
    document = registry.analyze_case("case-r1", expected_case_revision=3)[0]
    if field == "cad_binding":
        document["cad_binding"]["manifest_sha256"] = "0" * 64
    elif field == "reference_image_sha256":
        document["input_binding"][field] = "0" * 64
    else:
        document[field] = "0" * 64
    payload = canonical_json_bytes(document)
    with registry._connect() as connection:
        connection.execute(
            "UPDATE analyses SET document_json = ?, document_sha256 = ?",
            (payload, sha256(payload).hexdigest()),
        )
    with pytest.raises(MVSError, match="binding"):
        registry.analyze_case("case-r1", expected_case_revision=4)


def test_corrupt_preserved_cad_payload_fails_before_using_demo_regions(tmp_path):
    from manufacturing_vision_studio.errors import MVSError

    registry, adapter, source = setup_import(tmp_path)
    adapter.import_reference(registry, "case-r1", source, expected_case_revision=1)
    payload = next(registry.settings.blob_dir.rglob("*.cad-feature-map.json"))
    payload.write_bytes(b"corrupt")
    with pytest.raises(MVSError, match="hash"):
        registry.get_case_detail("case-r1")


@pytest.mark.parametrize("version", [[], {}])
def test_contract_reader_rejects_malformed_version_as_domain_error(version):
    from manufacturing_vision_studio.errors import MVSError
    from manufacturing_vision_studio.schema_validation import validate_document

    with pytest.raises(MVSError):
        validate_document({"schema_version": version}, "analysis-result")
