"""Closed CAD view profile and immutable byte binding, independent of persistence."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.errors import EvidenceError
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.schema_validation import validate_document

PROFILE = "coolgear-plate-top/v1"
MANIFEST = "freecad-export-adapter-manifest.json"
PAYLOAD_NAMES = (MANIFEST, "reference.png", "feature-map.json", "cad-metadata.json")
FEATURE_IDS = tuple(f"hole_{group}{i}" for group in ("H", "P") for i in range(1, 5))
TRANSFORM = [[10, 0, 50], [0, -10, 790], [0, 0, 1]]


def _reject(message: str) -> NoReturn:
    raise EvidenceError(message, code="SCHEMA_INVALID")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("Duplicate CAD JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    _reject(f"Non-finite CAD JSON number: {value}")


def json_object(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise EvidenceError("Malformed CAD JSON", code="SCHEMA_INVALID") from exc
    if not isinstance(value, dict):
        _reject("CAD JSON must be an object")
    return dict(value)


@dataclass(frozen=True, slots=True)
class CadFeatureBinding:
    manifest_sha256: str
    source_manifest_sha256: str
    feature_map_sha256: str
    metadata_sha256: str
    reference_pixel_sha256: str
    reference_sha256: str
    part_id: str
    cad_revision: str
    export_id: str
    source_kind: str
    feature_regions: tuple[tuple[str, float, float, float, float], ...]

    def regions(self) -> dict[str, tuple[float, float, float, float]]:
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in self.feature_regions}

    def case_binding(self) -> dict[str, str]:
        return {"export_id": self.export_id, "manifest_sha256": self.manifest_sha256}


def validate_cad_binding(
    manifest_bytes: bytes,
    artifacts: Mapping[str, bytes],
    *,
    expected_source: Mapping[str, str] | None = None,
) -> CadFeatureBinding:
    """Validate one snapshot; external expected digests supply trust, hashes alone do not."""
    manifest = json_object(manifest_bytes)
    validate_document(manifest, "freecad-export-adapter-manifest")
    expected_roles = {
        "reference.png": "reference_render",
        "feature-map.json": "feature_map",
        "cad-metadata.json": "cad_metadata",
    }
    if set(artifacts) != set(expected_roles) or len(manifest["artifacts"]) != 3:
        _reject("CAD profile requires exactly three named payloads")
    seen: set[str] = set()
    for entry in manifest["artifacts"]:
        name = entry["relative_path"]
        media = "image/png" if name == "reference.png" else "application/json"
        if (
            name in seen
            or name not in expected_roles
            or entry["role"] != expected_roles[name]
            or entry["media_type"] != media
        ):
            _reject("CAD artifact role/path mismatch")
        seen.add(name)
        data = artifacts[name]
        if len(data) != entry["byte_size"] or sha256_bytes(data) != entry["sha256"]:
            raise EvidenceError("CAD artifact bytes mismatch", code="HASH_MISMATCH")
    feature_map = json_object(artifacts["feature-map.json"])
    metadata = json_object(artifacts["cad-metadata.json"])
    if set(feature_map) != {"profile", "features"} or feature_map["profile"] != PROFILE:
        _reject("Unknown CAD feature profile")
    required = {
        "profile",
        "part_identity",
        "source_kind",
        "source_manifest_sha256",
        "width_px",
        "height_px",
        "units",
        "cad_to_pixel",
    }
    optional = {
        "source_manifest_payload",
        "source_manifest_base64",
        "source_commit",
        "config_sha256",
        "model_sha256",
        "producer_commit",
        "producer_source_sha256",
        "freecad_version",
        "holes",
        "physical_test",
        "manufacturing_release",
        "installed_load_rating_N",
        "fastening_torque_Nm",
    }
    if not required <= metadata.keys() or set(metadata) - required - optional:
        _reject("CAD metadata fields do not match profile")
    if (
        metadata["profile"] != PROFILE
        or metadata["units"] != "mm"
        or metadata["width_px"] != 1520
        or metadata["height_px"] != 840
        or metadata["cad_to_pixel"] != TRANSFORM
    ):
        _reject("Unsupported CAD view or units")
    if metadata["source_kind"] not in {"native_freecad", "synthetic_contract_fixture"}:
        _reject("Unknown CAD source kind")
    if metadata["part_identity"] != manifest["part_identity"]:
        _reject("CAD metadata identity mismatch")
    if metadata["source_manifest_sha256"] != manifest["source_manifest_sha256"]:
        _reject("CAD upstream manifest mismatch")
    if "source_manifest_base64" in metadata:
        try:
            upstream_bytes = base64.b64decode(metadata["source_manifest_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise EvidenceError("Malformed upstream bytes", code="SCHEMA_INVALID") from exc
        upstream = json_object(upstream_bytes)
    elif metadata["source_kind"] == "synthetic_contract_fixture":
        upstream_bytes = (
            json.dumps(metadata.get("source_manifest_payload"), sort_keys=True, indent=2) + "\n"
        ).encode()
        upstream = json_object(upstream_bytes)
    else:
        _reject("Native CAD requires actual upstream manifest bytes")
        raise AssertionError("unreachable")
    if sha256_bytes(upstream_bytes) != manifest["source_manifest_sha256"]:
        raise EvidenceError("Upstream manifest bytes mismatch", code="HASH_MISMATCH")
    if metadata["source_kind"] == "native_freecad":
        if (
            metadata.get("physical_test") != "not_tested"
            or metadata.get("manufacturing_release") is not False
            or metadata.get("installed_load_rating_N") is not None
            or metadata.get("fastening_torque_Nm") is not None
        ):
            _reject("Unsupported physical qualification claim")
        if (
            upstream.get("input", {}).get("sha256") != metadata.get("config_sha256")
            or upstream.get("repo", {}).get("head_sha") != metadata.get("source_commit")
            or not any(
                e.get("sha256") == metadata.get("model_sha256")
                and e.get("kind") in {"model.brep", "model.step"}
                for e in upstream.get("outputs", [])
            )
        ):
            _reject("Native CAD provenance does not match upstream")
    features = manifest["features"]
    ids = [row["feature_id"] for row in features]
    if sorted(ids) != list(FEATURE_IDS):
        _reject("CAD profile requires eight unique H/P features")
    if features != feature_map["features"]:
        _reject("CAD manifest/feature-map mismatch")
    regions = []
    for feature in sorted(features, key=lambda item: item["feature_id"]):
        if feature["feature_type"] != "hole":
            _reject("CAD profile accepts hole features only")
        region = feature["normalized_region"]
        bounds = tuple(region[k] for k in ("x_min", "y_min", "x_max", "y_max"))
        if any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
            for v in bounds
        ) or not (0 <= bounds[0] < bounds[2] <= 1 and 0 <= bounds[1] < bounds[3] <= 1):
            _reject("CAD ROI must be finite and positive within image")
        if round(bounds[0] * 1520) >= round(bounds[2] * 1520) or round(bounds[1] * 840) >= round(
            bounds[3] * 840
        ):
            _reject("CAD ROI must have positive pixel area")
        regions.append((feature["feature_id"], *bounds))
    image = ImageIngestor().ingest_bytes(artifacts["reference.png"], filename="reference.png")
    if (image.width, image.height) != (1520, 840):
        _reject("CAD reference dimensions do not match view")
    hashes = {
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "feature_map_sha256": sha256_bytes(artifacts["feature-map.json"]),
        "metadata_sha256": sha256_bytes(artifacts["cad-metadata.json"]),
        "reference_sha256": image.original_sha256,
    }
    for key, expected in (expected_source or {}).items():
        if hashes.get(key, metadata.get(key)) != expected:
            raise EvidenceError("CAD source differs from pinned expectation", code="HASH_MISMATCH")
    return CadFeatureBinding(
        **hashes,
        reference_pixel_sha256=image.pixel_sha256,
        part_id=manifest["part_identity"]["part_id"],
        cad_revision=manifest["part_identity"]["cad_revision"],
        export_id=manifest["export_id"],
        source_kind=metadata["source_kind"],
        feature_regions=tuple(regions),
    )
