"""Runtime validation against the repository's normative JSON Schemas."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from manufacturing_vision_studio.errors import EvidenceError


def schema_directory() -> Path:
    configured = os.environ.get("MVS_SCHEMA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "schemas" / "v1"


def load_schema(name: str) -> dict[str, Any]:
    path = schema_directory() / f"{name}.schema.json"
    try:
        parsed = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(
            "Required schema is unavailable",
            code="SCHEMA_INVALID",
            details={"schema": name},
        ) from exc
    if not isinstance(parsed, dict):
        raise EvidenceError(
            "Required schema is malformed",
            code="SCHEMA_INVALID",
            details={"schema": name},
        )
    return parsed


def validate_document(document: dict[str, Any], schema_name: str) -> None:
    if document.get("schema_version") != "1.0.0":
        raise EvidenceError(
            "Document schema version is unsupported",
            code="UNSUPPORTED_SCHEMA_VERSION",
            details={"schema": schema_name},
        )
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        field = ".".join(str(part) for part in first.absolute_path) or "$"
        raise EvidenceError(
            "Document does not satisfy its schema",
            code="SCHEMA_INVALID",
            details={"schema": schema_name, "field": field},
        )


def schema_id(schema_name: str) -> str:
    identifier = load_schema(schema_name).get("$id")
    if not isinstance(identifier, str):
        raise EvidenceError(
            "Schema identifier is missing",
            code="SCHEMA_INVALID",
            details={"schema": schema_name},
        )
    return identifier
