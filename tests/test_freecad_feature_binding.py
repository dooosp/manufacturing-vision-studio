import json
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest
from cad_binding_fixtures import json_bytes, write_minimal_cad_export


def test_imported_feature_ids_reach_case(tmp_path):
    from cad_binding_fixtures import write_minimal_cad_export

    from manufacturing_vision_studio.adapters import FreeCADExportAdapter
    from manufacturing_vision_studio.config import Settings
    from manufacturing_vision_studio.registry import CaseRegistry

    settings = Settings(data_dir=tmp_path / "registry")
    registry = CaseRegistry(settings)
    registry.create_case(part_id="USB-REF-ADAPTER", cad_revision="R1", case_id="case-r1")
    source = write_minimal_cad_export(tmp_path / "source")
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
