from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

SCHEMA_DIR = Path(__file__).parents[1] / "schemas" / "v1"
EXPECTED_SCHEMAS = {
    "analysis-result.schema.json",
    "evaluation-report.schema.json",
    "evidence-bundle-manifest.schema.json",
    "freecad-export-adapter-manifest.schema.json",
    "human-disposition.schema.json",
    "image-input-metadata.schema.json",
    "inspection-case.schema.json",
}


def load_schema(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def walk_json(value: Any, pointer: str = "") -> list[tuple[str, Any]]:
    walked = [(pointer, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            walked.extend(walk_json(child, f"{pointer}/{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walked.extend(walk_json(child, f"{pointer}/{index}"))
    return walked


def test_all_required_v1_schema_contracts_are_present() -> None:
    actual = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}

    assert actual == EXPECTED_SCHEMAS


@pytest.mark.parametrize("schema_name", sorted(EXPECTED_SCHEMAS))
def test_v1_schemas_are_strict_and_version_pinned(schema_name: str) -> None:
    schema = load_schema(SCHEMA_DIR / schema_name)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "schema_version" in schema["required"]
    assert schema["properties"]["schema_version"] == {"const": "1.0.0"}

    for pointer, value in walk_json(schema):
        if isinstance(value, dict) and value.get("type") == "object":
            assert value.get("additionalProperties") is False, (
                f"unbounded object at {schema_name}#{pointer}"
            )
        if isinstance(value, dict) and "$ref" in value:
            assert value["$ref"].startswith("#/")


def test_evidence_bundle_schema_requires_every_evidence_class() -> None:
    schema = load_schema(SCHEMA_DIR / "evidence-bundle-manifest.schema.json")
    required = set(schema["required"])

    assert {
        "schema_version",
        "bundle_id",
        "case_id",
        "case_revision",
        "part_identity",
        "created_at",
        "exporter",
        "hash_contract",
        "artifact_count",
        "payload_byte_size",
        "artifacts",
        "payload_sha256",
        "limitations",
    } <= required

    artifact_schema = schema["properties"]["artifacts"]["items"]
    assert {"path", "sha256", "byte_size", "media_type"} <= set(artifact_schema["required"])

    required_roles = {
        rule["properties"]["artifacts"]["contains"]["properties"]["role"]["const"]
        for rule in schema["allOf"]
    }
    assert {
        "inspection_case",
        "reference_image_metadata",
        "reference_image",
        "inspection_image_metadata",
        "inspection_image",
        "analysis_result",
        "anomaly_mask",
        "human_disposition",
        "evaluation_report",
        "limitations",
    } <= required_roles
