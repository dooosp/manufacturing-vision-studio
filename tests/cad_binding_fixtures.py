import json
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def write_minimal_cad_export(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=False)
    identity = {"part_id": "USB-REF-ADAPTER", "cad_revision": "R1"}
    points = [
        ("H1", 29, 24.4, 2),
        ("H2", 29, 49.6, 2),
        ("H3", 113, 24.4, 2),
        ("H4", 113, 49.6, 2),
        ("P1", 12, 12, 2.75),
        ("P2", 12, 62, 2.75),
        ("P3", 130, 12, 2.75),
        ("P4", 130, 62, 2.75),
    ]
    image = Image.new("RGB", (1520, 840), "black")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((50, 50, 1470, 790), fill=(180, 180, 180))
    features = []
    for name, x, y, radius in points:
        u, v = 10 * (x + 5), 10 * (79 - y)
        r, margin = 10 * radius, 10 * (radius + 1)
        drawing.ellipse((u - r, v - r, u + r, v + r), fill="black")
        features.append(
            {
                "feature_id": "hole_" + name,
                "display_name": name,
                "feature_type": "hole",
                "normalized_region": {
                    "x_min": (u - margin) / 1520,
                    "y_min": (v - margin) / 840,
                    "x_max": (u + margin) / 1520,
                    "y_max": (v + margin) / 840,
                },
            }
        )
    image.save(root / "reference.png", format="PNG", compress_level=9)
    upstream = {"kind": "synthetic_contract_fixture", **identity}
    upstream_hash = sha256(json_bytes(upstream)).hexdigest()
    feature_map = {"profile": "coolgear-plate-top/v1", "features": features}
    metadata = {
        "profile": "coolgear-plate-top/v1",
        "part_identity": identity,
        "source_kind": "synthetic_contract_fixture",
        "source_manifest_payload": upstream,
        "source_manifest_sha256": upstream_hash,
        "width_px": 1520,
        "height_px": 840,
        "units": "mm",
        "cad_to_pixel": [[10, 0, 50], [0, -10, 790], [0, 0, 1]],
    }
    (root / "feature-map.json").write_bytes(json_bytes(feature_map))
    (root / "cad-metadata.json").write_bytes(json_bytes(metadata))
    artifacts = []
    for name, role, media in [
        ("reference.png", "reference_render", "image/png"),
        ("feature-map.json", "feature_map", "application/json"),
        ("cad-metadata.json", "cad_metadata", "application/json"),
    ]:
        data = (root / name).read_bytes()
        artifacts.append(
            {
                "artifact_id": role,
                "role": role,
                "relative_path": name,
                "media_type": media,
                "sha256": sha256(data).hexdigest(),
                "byte_size": len(data),
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "adapter_id": "freecad-automation-read-only-export",
        "adapter_version": "1.0.0",
        "export_id": "fixture-coolgear-r1",
        "producer": {
            "system_id": "freecad-automation",
            "system_version": "1.1.0",
            "export_schema_version": "1.0.0",
            "exported_at": "2026-09-18T00:00:00Z",
        },
        "part_identity": identity,
        "source_manifest_sha256": upstream_hash,
        "adapter_policy": {
            "access_mode": "read_only",
            "copy_on_import": True,
            "allow_external_paths": False,
            "allow_symlinks": False,
            "execute_freecad": False,
        },
        "features": features,
        "artifacts": artifacts,
        "limitations": ["Synthetic contract fixture; no native CAD or physical test."],
    }
    (root / "freecad-export-adapter-manifest.json").write_bytes(json_bytes(manifest))
    return root
