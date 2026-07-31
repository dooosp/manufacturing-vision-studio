"""Load and bind the frozen E1 protocol without process-global caching."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

from manufacturing_vision_studio.canonical import canonical_json_hash
from manufacturing_vision_studio.e1.domain import E1CasePlan, FeatureRegion, ViewId

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_E1_CONFIG_PATH = PROJECT_ROOT / "configs" / "evaluation" / "e1-v1.json"


class E1ProtocolError(ValueError):
    """The checked-in E1 contract is malformed or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class E1Protocol:
    """Validated E1 document and its deterministic generator projection."""

    source_path: Path
    schema_path: Path
    _document: dict[str, Any] = field(repr=False)
    configuration_sha256: str
    generator_configuration_sha256: str

    @property
    def document(self) -> dict[str, Any]:
        """Return a defensive copy so callers cannot mutate the frozen contract."""

        return deepcopy(self._document)

    @property
    def protocol_id(self) -> str:
        return cast(str, self._document["protocol_id"])

    @property
    def protocol_version(self) -> str:
        return cast(str, self._document["protocol_version"])

    @property
    def generator_id(self) -> str:
        return cast(str, self._generator["generator_id"])

    @property
    def generator_version(self) -> str:
        return cast(str, self._generator["generator_version"])

    @property
    def recipe_version(self) -> str:
        return cast(str, self._generator["recipe_version"])

    @property
    def image_size(self) -> tuple[int, int]:
        media = self._object("media")
        return cast(int, media["width_px"]), cast(int, media["height_px"])

    @property
    def split_order(self) -> tuple[str, ...]:
        split_rules = self._object("split_rules")
        return tuple(cast(list[str], split_rules["split_order"]))

    @property
    def exact_mini_case_ids(self) -> tuple[str, ...]:
        profiles = self._object("dataset_profiles")
        selection = _expect_object(profiles.get("mini_selection"), "mini_selection")
        case_ids = selection.get("exact_case_ids")
        if not isinstance(case_ids, list) or not all(isinstance(value, str) for value in case_ids):
            raise E1ProtocolError("mini_selection.exact_case_ids must be a string array")
        return tuple(cast(list[str], case_ids))

    @property
    def _generator(self) -> dict[str, Any]:
        return self._object("generator")

    def section(self, name: str) -> dict[str, Any]:
        """Return a defensive copy of one top-level object."""

        return deepcopy(self._object(name))

    def feature_regions_for_view(self, view_id: ViewId | str) -> dict[str, FeatureRegion]:
        universe = self._object("universe")
        by_view = _expect_object(universe.get("feature_regions_by_view"), "feature regions")
        raw_regions = _expect_object(by_view.get(str(view_id)), f"feature regions for {view_id}")
        regions: dict[str, FeatureRegion] = {}
        for feature_id, raw_box in raw_regions.items():
            if (
                not isinstance(feature_id, str)
                or not isinstance(raw_box, list)
                or len(raw_box) != 4
                or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in raw_box
                )
            ):
                raise E1ProtocolError(f"invalid feature region for {feature_id!r}")
            box = tuple(float(value) for value in raw_box)
            if not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                raise E1ProtocolError(f"feature region is out of bounds for {feature_id!r}")
            regions[feature_id] = cast(FeatureRegion, box)
        return regions

    def case_binding_sha256(
        self,
        plan: E1CasePlan,
        *,
        reference_sha256: str,
        inspection_sha256: str,
        authoritative_mask_sha256: str,
    ) -> str:
        """Hash the frozen per-case leakage/integrity projection."""

        split_rules = self._object("split_rules")
        raw_paths = split_rules.get("case_binding_projection")
        if not isinstance(raw_paths, list) or not all(
            isinstance(path, str) and path for path in raw_paths
        ):
            raise E1ProtocolError("case-binding projection must be a string array")
        paths = cast(list[str], raw_paths)
        values: dict[str, object] = {
            "case_id": plan.case_id,
            "recipe_id": plan.recipe_id,
            "seed_family": plan.seed_family,
            "reference_sha256": reference_sha256,
            "inspection_sha256": inspection_sha256,
            "authoritative_mask_sha256": authoritative_mask_sha256,
            "expected_outcome": plan.expected_outcome.value,
            "defect_id": None if plan.defect is None else plan.defect.defect_id,
        }
        if set(paths) != set(values) or len(paths) != len(values):
            raise E1ProtocolError("unsupported case-binding projection")
        return canonical_json_hash({path: values[path] for path in paths})

    def _object(self, name: str) -> dict[str, Any]:
        return _expect_object(self._document.get(name), name)


def load_e1_protocol(
    path: Path | str = DEFAULT_E1_CONFIG_PATH,
    *,
    schema_path: Path | str | None = None,
) -> E1Protocol:
    """Load, schema-validate, and hash one E1 configuration.

    The function deliberately does not cache. A long-running process must create
    a new protocol/generator instance to observe an explicitly changed config.
    """

    resolved_path = Path(path).expanduser().resolve()
    document = _load_json_object(resolved_path)
    resolved_schema = _resolve_schema_path(resolved_path, document, schema_path)
    schema = _load_json_object(resolved_schema)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    except Exception as exc:
        raise E1ProtocolError(f"E1 configuration failed schema validation: {exc}") from exc

    generator_projection = _generator_configuration_projection(document)
    return E1Protocol(
        source_path=resolved_path,
        schema_path=resolved_schema,
        _document=document,
        configuration_sha256=canonical_json_hash(document),
        generator_configuration_sha256=canonical_json_hash(generator_projection),
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            path.read_bytes(),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise E1ProtocolError(f"E1 JSON could not be loaded from {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise E1ProtocolError(f"E1 JSON root must be an object: {path}")
    return cast(dict[str, Any], parsed)


def _resolve_schema_path(
    config_path: Path,
    document: dict[str, Any],
    schema_path: Path | str | None,
) -> Path:
    if schema_path is not None:
        return Path(schema_path).expanduser().resolve()
    schema_reference = document.get("$schema")
    if not isinstance(schema_reference, str) or not schema_reference:
        raise E1ProtocolError("E1 configuration must declare a local $schema")
    if "://" in schema_reference:
        raise E1ProtocolError("E1 configuration schema must be a local file")
    return (config_path.parent / schema_reference).resolve()


def _generator_configuration_projection(document: dict[str, Any]) -> dict[str, Any]:
    generator = _expect_object(document.get("generator"), "generator")
    projection_contract = _expect_object(
        generator.get("configuration_projection"),
        "generator.configuration_projection",
    )
    if projection_contract.get("canonicalization") != "mvs-canonical-json/v1":
        raise E1ProtocolError("unsupported generator projection canonicalization")
    raw_paths = projection_contract.get("included_paths")
    if (
        not isinstance(raw_paths, list)
        or not raw_paths
        or not all(isinstance(path, str) and path for path in raw_paths)
    ):
        raise E1ProtocolError("generator projection paths must be a non-empty string array")

    projection: dict[str, Any] = {}
    for raw_path in cast(list[str], raw_paths):
        segments = raw_path.split(".")
        if any(not segment for segment in segments):
            raise E1ProtocolError(f"invalid generator projection path: {raw_path}")
        value: Any = document
        for segment in segments:
            if not isinstance(value, dict) or segment not in value:
                raise E1ProtocolError(f"missing generator projection path: {raw_path}")
            value = value[segment]
        destination = projection
        for segment in segments[:-1]:
            existing = destination.setdefault(segment, {})
            if not isinstance(existing, dict):
                raise E1ProtocolError(f"overlapping generator projection path: {raw_path}")
            destination = existing
        destination[segments[-1]] = deepcopy(value)
    return projection


def _expect_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise E1ProtocolError(f"{label} must be an object")
    return cast(dict[str, Any], value)
