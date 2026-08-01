"""Config-driven E1 trust-boundary execution with real fail-closed validators."""

from __future__ import annotations

import io
import json
import re
import stat
import zipfile
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.e1.oracle import validate_authoritative_mask
from manufacturing_vision_studio.e1.protocol import E1Protocol, E1ProtocolError, load_e1_protocol
from manufacturing_vision_studio.errors import MVSError, UnsafeInputError
from manufacturing_vision_studio.evidence import (
    MANIFEST_NAME,
    SIDECAR_NAME,
    EvidenceService,
    payload_inventory_hash,
)
from manufacturing_vision_studio.images import ImageIngestor, IngestedImage
from manufacturing_vision_studio.registry import CaseRegistry

Outcome = Literal["NORMAL", "ANOMALY", "ABSTAIN"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLDEN_BUNDLE_PATH = PROJECT_ROOT / "docs" / "releases" / "v0.1.0" / "evidence-bundle.zip"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CASE_ID_PATTERN = re.compile(
    r"^e1-(development|calibration|test)-(clean|nuisance|defect|trust_boundary)-[0-9]{3}$"
)


@dataclass(frozen=True, slots=True)
class TrustBoundaryScenario:
    """One frozen trust-boundary expectation loaded from the E1 protocol."""

    scenario_id: str
    split: str
    expected_outcome: Outcome
    expected_error_code: str
    publication_allowed: bool
    included_in_mini: bool


@dataclass(frozen=True, slots=True)
class TrustBoundaryResult:
    """Observed fail-closed result for one adversarial scenario."""

    scenario_id: str
    split: str
    expected_outcome: Outcome
    actual_outcome: Outcome
    expected_error_code: str
    actual_error_code: str | None
    publication_count: int
    passed: bool

    def as_record(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "split": self.split,
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "expected_error_code": self.expected_error_code,
            "actual_error_code": self.actual_error_code,
            "publication_count": self.publication_count,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class TrustBoundaryReport:
    """Complete E1 trust-boundary projection, excluding supplemental hardlink checks."""

    results: tuple[TrustBoundaryResult, ...]

    @property
    def publication_count(self) -> int:
        return sum(result.publication_count for result in self.results)

    @property
    def all_passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    def as_record(self) -> dict[str, object]:
        return {
            "scenario_count": len(self.results),
            "publication_count": self.publication_count,
            "all_passed": self.all_passed,
            "results": [result.as_record() for result in self.results],
        }


@dataclass(frozen=True, slots=True)
class _ScenarioContext:
    protocol: E1Protocol
    scenario: TrustBoundaryScenario
    root: Path
    golden_bundle: bytes


ScenarioHandler = Callable[[_ScenarioContext], None]


def run_trust_boundary_suite(
    work_root: Path | str,
    *,
    protocol: E1Protocol | None = None,
    golden_bundle_path: Path | str = DEFAULT_GOLDEN_BUNDLE_PATH,
) -> TrustBoundaryReport:
    """Execute every frozen trust scenario and record the actual validator error.

    Publication is attempted only if a boundary validator returns successfully.
    Consequently a missed validation is visible as one publication rather than
    being converted into a synthetic abstention result.
    """

    active_protocol = protocol or load_e1_protocol()
    scenarios = _load_scenarios(active_protocol)
    configured_ids = {scenario.scenario_id for scenario in scenarios}
    handler_ids = set(_SCENARIO_HANDLERS)
    if configured_ids != handler_ids:
        raise E1ProtocolError(
            "trust-boundary handlers do not match the frozen config: "
            f"missing={sorted(configured_ids - handler_ids)!r}, "
            f"extra={sorted(handler_ids - configured_ids)!r}"
        )

    root = Path(work_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    golden_path = Path(golden_bundle_path).expanduser().resolve()
    try:
        golden_bundle = golden_path.read_bytes()
    except OSError as exc:
        raise E1ProtocolError(f"golden v0.1 bundle could not be read: {golden_path}") from exc
    expected_golden_sha256 = _required_string(
        active_protocol.section("baseline"), "bundle_sha256", "baseline"
    )
    if sha256_bytes(golden_bundle) != expected_golden_sha256:
        raise E1ProtocolError("golden v0.1 bundle hash does not match the frozen baseline")

    results: list[TrustBoundaryResult] = []
    for scenario in scenarios:
        scenario_root = root / scenario.scenario_id
        scenario_root.mkdir(parents=True, exist_ok=False)
        context = _ScenarioContext(
            protocol=active_protocol,
            scenario=scenario,
            root=scenario_root,
            golden_bundle=golden_bundle,
        )
        publication_count = 0
        actual_outcome: Outcome
        actual_error_code: str | None
        try:
            _SCENARIO_HANDLERS[scenario.scenario_id](context)
        except MVSError as exc:
            actual_outcome = "ABSTAIN"
            actual_error_code = exc.code
        else:
            # A boundary validator that accepts the adversarial stimulus reaches
            # the publication step and must make the trust gate fail visibly.
            publication_count = 1
            actual_outcome = "NORMAL"
            actual_error_code = None

        passed = (
            scenario.expected_outcome == "ABSTAIN"
            and actual_outcome == scenario.expected_outcome
            and actual_error_code == scenario.expected_error_code
            and publication_count == 0
            and not scenario.publication_allowed
        )
        results.append(
            TrustBoundaryResult(
                scenario_id=scenario.scenario_id,
                split=scenario.split,
                expected_outcome=scenario.expected_outcome,
                actual_outcome=actual_outcome,
                expected_error_code=scenario.expected_error_code,
                actual_error_code=actual_error_code,
                publication_count=publication_count,
                passed=passed,
            )
        )
    return TrustBoundaryReport(tuple(results))


def validate_e1_case_manifest(
    manifest: Mapping[str, Any],
    protocol: E1Protocol,
    *,
    expected_part_id: str | None = None,
    expected_cad_revision: str | None = None,
) -> None:
    """Validate one E1 case identity, source binding, and support boundary."""

    case_id = _input_required_string(manifest, "case_id", "case manifest")
    match = _CASE_ID_PATTERN.fullmatch(case_id)
    if match is None:
        raise UnsafeInputError("E1 case identifier is malformed", code="SCHEMA_INVALID")
    split = _input_required_string(manifest, "split", "case manifest")
    group = _input_required_string(manifest, "group", "case manifest")
    if split not in protocol.split_order or split != match.group(1) or group != match.group(2):
        raise UnsafeInputError("E1 case split or group binding is invalid", code="SCHEMA_INVALID")

    _input_required_string(manifest, "recipe_id", "case manifest")
    _input_required_string(manifest, "seed_family", "case manifest")
    part_identity = _input_required_mapping(manifest, "part_identity", "case manifest")
    part_id = _input_required_string(part_identity, "part_id", "part identity")
    cad_revision = _input_required_string(part_identity, "cad_revision", "part identity")
    allowed_parts = _allowed_part_revisions(protocol)
    if part_id not in allowed_parts or (
        expected_part_id is not None and part_id != expected_part_id
    ):
        raise UnsafeInputError("E1 part identity does not match", code="PART_ID_MISMATCH")
    if cad_revision not in allowed_parts[part_id] or (
        expected_cad_revision is not None and cad_revision != expected_cad_revision
    ):
        raise UnsafeInputError("E1 CAD revision does not match", code="REVISION_MISMATCH")

    universe = protocol.section("universe")
    views = _string_set(universe.get("views"), "universe.views")
    view_id = _input_required_string(manifest, "view_id", "case manifest")
    if view_id not in views:
        raise UnsafeInputError(
            "E1 view is outside the approved normalization contract",
            code="NORMALIZATION_NOT_APPROVED",
        )

    source_hashes = _input_required_mapping(manifest, "source_hashes", "case manifest")
    reference_sha256 = source_hashes.get("reference_sha256")
    if not isinstance(reference_sha256, str) or not reference_sha256:
        raise UnsafeInputError("E1 reference image is missing", code="MISSING_REFERENCE")
    for field in (
        "reference_sha256",
        "inspection_sha256",
        "authoritative_mask_sha256",
    ):
        value = source_hashes.get(field)
        if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
            raise UnsafeInputError("E1 source hash is malformed", code="HASH_MISMATCH")

    generator = _input_required_mapping(manifest, "generator", "case manifest")
    if generator.get("generator_id") != protocol.generator_id or (
        generator.get("generator_version") != protocol.generator_version
    ):
        raise UnsafeInputError("E1 generator identity does not match", code="HASH_MISMATCH")
    if generator.get("generator_configuration_sha256") != protocol.generator_configuration_sha256:
        raise UnsafeInputError("E1 generator configuration does not match", code="HASH_MISMATCH")

    pipeline = _input_required_mapping(manifest, "pipeline", "case manifest")
    evaluation_pipeline = protocol.section("evaluation_pipeline")
    expected_pipeline = {
        "pipeline_id": evaluation_pipeline["pipeline_id"],
        "pipeline_version": evaluation_pipeline["pipeline_version"],
    }
    if pipeline != expected_pipeline:
        raise UnsafeInputError("E1 pipeline version is unknown", code="UNKNOWN_PIPELINE_VERSION")

    feature_ids = _string_set(universe.get("feature_ids"), "universe.feature_ids")
    defect = manifest.get("defect")
    if defect is not None:
        defect_record = _input_mapping(defect, "case defect")
        target_feature = _input_required_string(defect_record, "target_feature_id", "case defect")
        if target_feature not in feature_ids:
            raise UnsafeInputError("E1 target feature is unknown", code="SCHEMA_INVALID")
    if group == "defect" and defect is None:
        raise UnsafeInputError("E1 defect truth is missing", code="SCHEMA_INVALID")
    if group != "defect" and defect is not None:
        raise UnsafeInputError("E1 non-defect case carries defect truth", code="SCHEMA_INVALID")

    nuisance_profile = manifest.get("nuisance_profile", [])
    if not isinstance(nuisance_profile, list):
        raise UnsafeInputError("E1 nuisance profile is malformed", code="SCHEMA_INVALID")
    cardinality = protocol.section("taxonomies").get("nuisance_case_cardinality")
    cardinality_record = _mapping(cardinality, "nuisance cardinality")
    expected_primary = cardinality_record.get("primary_nuisance_per_case")
    expected_count = expected_primary if group == "nuisance" else 0
    if not isinstance(expected_count, int) or len(nuisance_profile) != expected_count:
        raise UnsafeInputError("E1 nuisance cardinality is invalid", code="SCHEMA_INVALID")
    _validate_supported_nuisances(nuisance_profile, protocol)

    declared_binding = source_hashes.get("case_binding_sha256")
    if not isinstance(declared_binding, str) or declared_binding != case_binding_sha256(
        manifest, protocol
    ):
        raise UnsafeInputError("E1 case binding hash does not match", code="HASH_MISMATCH")


def validate_e1_manifest_set(
    manifests: Sequence[Mapping[str, Any]],
    protocol: E1Protocol,
) -> None:
    """Reject duplicate case IDs and leak-key overlap across dataset splits."""

    case_ids: set[str] = set()
    leak_owners: dict[tuple[str, str], str] = {}
    leak_keys = _string_sequence(protocol.section("split_rules").get("leak_keys"), "leak keys")
    for manifest in manifests:
        validate_e1_case_manifest(manifest, protocol)
        case_id = _input_required_string(manifest, "case_id", "case manifest")
        if case_id in case_ids:
            raise UnsafeInputError("E1 case identifiers are duplicated", code="SCHEMA_INVALID")
        case_ids.add(case_id)
        split = _input_required_string(manifest, "split", "case manifest")
        for key in leak_keys:
            value = _leak_value(manifest, protocol, key)
            owner_key = (key, value)
            previous_split = leak_owners.get(owner_key)
            if previous_split is not None and previous_split != split:
                raise UnsafeInputError(
                    "E1 split leak key overlaps another split",
                    code="SCHEMA_INVALID",
                    details={"key": key, "splits": [previous_split, split]},
                )
            leak_owners[owner_key] = split


def case_binding_sha256(manifest: Mapping[str, Any], protocol: E1Protocol) -> str:
    """Hash the frozen case-binding projection without trusting a declared digest."""

    fields = _string_sequence(
        protocol.section("split_rules").get("case_binding_projection"),
        "case binding projection",
    )
    source_hashes = manifest.get("source_hashes")
    source_record = source_hashes if isinstance(source_hashes, Mapping) else {}
    defect = manifest.get("defect")
    defect_record = defect if isinstance(defect, Mapping) else {}
    projection: dict[str, Any] = {}
    for field in fields:
        if field in {
            "reference_sha256",
            "inspection_sha256",
            "authoritative_mask_sha256",
        }:
            projection[field] = source_record.get(field)
        elif field == "defect_id":
            projection[field] = defect_record.get(field)
        else:
            projection[field] = manifest.get(field)
    return canonical_json_hash(projection)


def validate_supplemental_hardlink_input(
    path: Path,
    *,
    settings: Settings | None = None,
) -> IngestedImage:
    """Apply the supplemental E1 hardlink policy before ordinary ingestion."""

    try:
        metadata = path.expanduser().lstat()
    except OSError as exc:
        raise UnsafeInputError(
            "Hardlink input could not be inspected", code="NON_REGULAR_INPUT"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise UnsafeInputError(
            "Multiply linked inputs are outside the portable E1 contract",
            code="NON_REGULAR_INPUT",
        )
    return ImageIngestor(settings).ingest_path(path)


def _load_scenarios(protocol: E1Protocol) -> tuple[TrustBoundaryScenario, ...]:
    raw_cases = protocol.section("taxonomies").get("trust_boundary_cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 24:
        raise E1ProtocolError("E1 must define exactly 24 trust-boundary cases")
    scenarios: list[TrustBoundaryScenario] = []
    seen: set[str] = set()
    for raw_case in raw_cases:
        case = _mapping(raw_case, "trust-boundary case")
        scenario_id = _required_string(case, "scenario_id", "trust-boundary case")
        split = _required_string(case, "split", "trust-boundary case")
        outcome = _required_string(case, "expected_outcome", "trust-boundary case")
        error_code = _required_string(case, "expected_error_code", "trust-boundary case")
        publication_allowed = case.get("publication_allowed")
        included_in_mini = case.get("included_in_mini")
        if scenario_id in seen or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", scenario_id):
            raise E1ProtocolError("trust-boundary scenario IDs must be unique identifiers")
        if split not in protocol.split_order or outcome != "ABSTAIN":
            raise E1ProtocolError("trust-boundary split/outcome is invalid")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error_code):
            raise E1ProtocolError("trust-boundary error code is invalid")
        if publication_allowed is not False or not isinstance(included_in_mini, bool):
            raise E1ProtocolError("trust-boundary publication/profile contract is invalid")
        seen.add(scenario_id)
        scenarios.append(
            TrustBoundaryScenario(
                scenario_id=scenario_id,
                split=split,
                expected_outcome="ABSTAIN",
                expected_error_code=error_code,
                publication_allowed=False,
                included_in_mini=included_in_mini,
            )
        )
    return tuple(scenarios)


def _base_manifest(protocol: E1Protocol, *, split: str = "development") -> dict[str, Any]:
    part = _mapping(protocol.section("universe")["parts"][0], "E1 part")
    revision = _mapping(cast(list[Any], part["revisions"])[0], "E1 revision")
    case_id = f"e1-{split}-clean-000"
    source_hashes = {
        "reference_sha256": sha256_bytes(f"{case_id}:reference".encode()),
        "inspection_sha256": sha256_bytes(f"{case_id}:inspection".encode()),
        "authoritative_mask_sha256": sha256_bytes(f"{case_id}:empty-mask".encode()),
    }
    manifest: dict[str, Any] = {
        "case_id": case_id,
        "split": split,
        "group": "clean",
        "recipe_id": f"e1-{split}-clean-recipe-v1",
        "seed_family": f"e1-{split}-clean-v1",
        "part_identity": {
            "part_id": part["part_id"],
            "cad_revision": revision["cad_revision"],
        },
        "view_id": "front",
        "expected_outcome": "NORMAL",
        "support_boundary": "SUPPORTED_NORMAL_RANGE",
        "defect": None,
        "nuisance_profile": [],
        "generator": {
            "generator_id": protocol.generator_id,
            "generator_version": protocol.generator_version,
            "generator_configuration_sha256": protocol.generator_configuration_sha256,
        },
        "pipeline": {
            "pipeline_id": protocol.section("evaluation_pipeline")["pipeline_id"],
            "pipeline_version": protocol.section("evaluation_pipeline")[
                "pipeline_version"
            ],
        },
        "source_hashes": source_hashes,
    }
    _refresh_case_binding(manifest, protocol)
    return manifest


def _refresh_case_binding(manifest: dict[str, Any], protocol: E1Protocol) -> None:
    source_hashes = _input_required_mapping(manifest, "source_hashes", "case manifest")
    source_hashes["case_binding_sha256"] = case_binding_sha256(manifest, protocol)


def _handle_revision_mismatch(context: _ScenarioContext) -> None:
    manifest = _base_manifest(context.protocol)
    part_identity = cast(dict[str, Any], manifest["part_identity"])
    expected_part_id = cast(str, part_identity["part_id"])
    expected_revision = cast(str, part_identity["cad_revision"])
    allowed_revisions = sorted(_allowed_part_revisions(context.protocol)[expected_part_id])
    mismatched_revision = next(
        revision for revision in allowed_revisions if revision != expected_revision
    )
    part_identity["cad_revision"] = mismatched_revision
    _refresh_case_binding(manifest, context.protocol)
    validate_e1_case_manifest(
        manifest,
        context.protocol,
        expected_part_id=expected_part_id,
        expected_cad_revision=expected_revision,
    )


def _handle_unknown_feature(context: _ScenarioContext) -> None:
    manifest = _base_manifest(context.protocol)
    manifest.update(
        {
            "case_id": "e1-development-defect-999",
            "group": "defect",
            "expected_outcome": "ANOMALY",
            "defect": {
                "defect_id": "unknown-feature-defect",
                "target_feature_id": "feature-not-registered",
            },
        }
    )
    _refresh_case_binding(manifest, context.protocol)
    validate_e1_case_manifest(manifest, context.protocol)


def _handle_duplicate_case_id(context: _ScenarioContext) -> None:
    first = _base_manifest(context.protocol)
    second = deepcopy(first)
    validate_e1_manifest_set((first, second), context.protocol)


def _handle_missing_reference(context: _ScenarioContext) -> None:
    manifest = _base_manifest(context.protocol)
    del manifest["source_hashes"]["reference_sha256"]
    _refresh_case_binding(manifest, context.protocol)
    validate_e1_case_manifest(manifest, context.protocol)


def _handle_malformed_image(context: _ScenarioContext) -> None:
    ImageIngestor(Settings(data_dir=context.root / "image-data")).ingest_bytes(
        b"not-an-image",
        filename="inspection.png",
    )


def _handle_path_traversal(context: _ScenarioContext) -> None:
    ImageIngestor(Settings(data_dir=context.root / "image-data")).ingest_bytes(
        _valid_rgb_png(),
        filename="../inspection.png",
    )


def _handle_part_identity_mismatch(context: _ScenarioContext) -> None:
    manifest = _base_manifest(context.protocol, split="calibration")
    part_identity = cast(dict[str, Any], manifest["part_identity"])
    expected_part_id = cast(str, part_identity["part_id"])
    part_identity["part_id"] = f"{expected_part_id}-SUBSTITUTED"
    _refresh_case_binding(manifest, context.protocol)
    validate_e1_case_manifest(
        manifest,
        context.protocol,
        expected_part_id=expected_part_id,
    )


def _handle_authoritative_mask_dimension_mismatch(context: _ScenarioContext) -> None:
    mask = encode_png(Image.new("L", (8, 8), 0), mode="L")
    validate_authoritative_mask(
        mask,
        declared_sha256=sha256_bytes(mask),
        expected_size=context.protocol.image_size,
        expected_non_empty=False,
    )


def _handle_unknown_pipeline_version(context: _ScenarioContext) -> None:
    valid = _build_current_bundle(context.root / "source")
    mutated = _mutate_pipeline(valid)
    _exercise_bundle_rejection(valid, mutated, context.root / "target")


def _handle_split_hash_overlap(context: _ScenarioContext) -> None:
    development = _base_manifest(context.protocol, split="development")
    test = deepcopy(development)
    test.update(
        {
            "case_id": "e1-test-clean-999",
            "split": "test",
            "recipe_id": "e1-test-clean-recipe-v1",
            "seed_family": "e1-test-clean-v1",
        }
    )
    # Source hashes deliberately remain identical across the two splits.
    _refresh_case_binding(test, context.protocol)
    validate_e1_manifest_set((development, test), context.protocol)


def _handle_missing_disposition(context: _ScenarioContext) -> None:
    valid = _build_current_bundle(context.root / "source")
    mutated = _remove_dispositions(valid)
    _exercise_bundle_rejection(valid, mutated, context.root / "target")


def _handle_symlink_input(context: _ScenarioContext) -> None:
    target = context.root / "regular.png"
    target.write_bytes(_valid_rgb_png())
    linked = context.root / "linked.png"
    linked.symlink_to(target.name)
    ImageIngestor(Settings(data_dir=context.root / "image-data")).ingest_path(
        linked,
        allowed_root=context.root,
    )


def _handle_authoritative_mask_corrupt_bytes(context: _ScenarioContext) -> None:
    mask = b"not-a-png-mask"
    validate_authoritative_mask(
        mask,
        declared_sha256=sha256_bytes(mask),
        expected_size=context.protocol.image_size,
        expected_non_empty=True,
    )


def _handle_authoritative_mask_non_binary(context: _ScenarioContext) -> None:
    mask_image = Image.new("L", context.protocol.image_size, 0)
    mask_image.putpixel((0, 0), 127)
    mask = encode_png(mask_image, mode="L")
    validate_authoritative_mask(
        mask,
        declared_sha256=sha256_bytes(mask),
        expected_size=context.protocol.image_size,
        expected_non_empty=True,
    )


def _handle_authoritative_mask_unexpected_empty(context: _ScenarioContext) -> None:
    mask = encode_png(Image.new("L", context.protocol.image_size, 0), mode="L")
    validate_authoritative_mask(
        mask,
        declared_sha256=sha256_bytes(mask),
        expected_size=context.protocol.image_size,
        expected_non_empty=True,
    )


def _handle_hash_mismatch(context: _ScenarioContext) -> None:
    mask = encode_png(Image.new("L", context.protocol.image_size, 0), mode="L")
    validate_authoritative_mask(
        mask,
        declared_sha256="0" * 64,
        expected_size=context.protocol.image_size,
        expected_non_empty=False,
    )


def _handle_oversized_image(context: _ScenarioContext) -> None:
    settings = Settings(data_dir=context.root / "image-data", max_image_bytes=8)
    ImageIngestor(settings).ingest_bytes(_valid_rgb_png(), filename="inspection.png")


def _handle_non_regular_input(context: _ScenarioContext) -> None:
    directory = context.root / "not-a-file"
    directory.mkdir()
    ImageIngestor(Settings(data_dir=context.root / "image-data")).ingest_path(
        directory,
        allowed_root=context.root,
    )


def _handle_incomplete_evidence_bundle(context: _ScenarioContext) -> None:
    mutated = _remove_one_payload_without_resealing(context.golden_bundle, role="anomaly_mask")
    _exercise_bundle_rejection(context.golden_bundle, mutated, context.root / "target")


def _handle_modified_bundle_reimport(context: _ScenarioContext) -> None:
    mutated = _modify_one_payload_without_resealing(context.golden_bundle, role="inspection_image")
    _exercise_bundle_rejection(context.golden_bundle, mutated, context.root / "target")


def _handle_invalid_utf8_json(context: _ScenarioContext) -> None:
    mutated = _replace_first_json_artifact(
        context.golden_bundle,
        b'{"schema_version":"1.0.0","invalid":"\xff"}',
    )
    _exercise_bundle_rejection(context.golden_bundle, mutated, context.root / "target")


def _handle_duplicate_json_keys(context: _ScenarioContext) -> None:
    mutated = _replace_first_json_artifact(
        context.golden_bundle,
        b'{"schema_version":"1.0.0","schema_version":"1.0.0"}',
    )
    _exercise_bundle_rejection(context.golden_bundle, mutated, context.root / "target")


def _handle_wrong_schema_version(context: _ScenarioContext) -> None:
    files = _read_archive(context.golden_bundle)
    manifest = _json_object(files[MANIFEST_NAME], "bundle manifest")
    path = _first_artifact_path(manifest, role="analysis_result")
    document = _json_object(files[path], "analysis result")
    document["schema_version"] = "2.0.0"
    files[path] = canonical_json_bytes(document)
    mutated = _reseal_archive(files)
    _exercise_bundle_rejection(context.golden_bundle, mutated, context.root / "target")


def _handle_unsupported_view_or_extreme_nuisance(context: _ScenarioContext) -> None:
    manifest = _base_manifest(context.protocol, split="test")
    manifest.update(
        {
            "case_id": "e1-test-nuisance-999",
            "group": "nuisance",
            "expected_outcome": "NORMAL",
            "nuisance_profile": [
                {
                    "type": "translation",
                    "parameters": [
                        {"name": "max_abs_shift", "unit": "px", "value": 48},
                    ],
                }
            ],
        }
    )
    _refresh_case_binding(manifest, context.protocol)
    validate_e1_case_manifest(manifest, context.protocol)


_SCENARIO_HANDLERS: dict[str, ScenarioHandler] = {
    "revision_mismatch": _handle_revision_mismatch,
    "unknown_feature": _handle_unknown_feature,
    "duplicate_case_id": _handle_duplicate_case_id,
    "missing_reference": _handle_missing_reference,
    "malformed_image": _handle_malformed_image,
    "path_traversal": _handle_path_traversal,
    "part_identity_mismatch": _handle_part_identity_mismatch,
    "authoritative_mask_dimension_mismatch": _handle_authoritative_mask_dimension_mismatch,
    "unknown_pipeline_version": _handle_unknown_pipeline_version,
    "split_hash_overlap": _handle_split_hash_overlap,
    "missing_disposition": _handle_missing_disposition,
    "symlink_input": _handle_symlink_input,
    "authoritative_mask_corrupt_bytes": _handle_authoritative_mask_corrupt_bytes,
    "authoritative_mask_non_binary": _handle_authoritative_mask_non_binary,
    "authoritative_mask_unexpected_empty": _handle_authoritative_mask_unexpected_empty,
    "hash_mismatch": _handle_hash_mismatch,
    "oversized_image": _handle_oversized_image,
    "non_regular_input": _handle_non_regular_input,
    "incomplete_evidence_bundle": _handle_incomplete_evidence_bundle,
    "modified_bundle_reimport": _handle_modified_bundle_reimport,
    "invalid_utf8_json": _handle_invalid_utf8_json,
    "duplicate_json_keys": _handle_duplicate_json_keys,
    "wrong_schema_version": _handle_wrong_schema_version,
    "unsupported_view_or_extreme_nuisance": _handle_unsupported_view_or_extreme_nuisance,
}


def _validate_supported_nuisances(entries: list[Any], protocol: E1Protocol) -> None:
    contracts: dict[str, dict[str, Any]] = {}
    raw_contracts = protocol.section("taxonomies").get("nuisances")
    if not isinstance(raw_contracts, list):
        raise E1ProtocolError("nuisance taxonomy is malformed")
    for raw_contract in raw_contracts:
        contract = _mapping(raw_contract, "nuisance contract")
        contracts[_required_string(contract, "type", "nuisance contract")] = contract

    seen: set[str] = set()
    for raw_entry in entries:
        entry = _input_mapping(raw_entry, "nuisance entry")
        nuisance_type = _input_required_string(entry, "type", "nuisance entry")
        if nuisance_type in seen or nuisance_type not in contracts:
            raise UnsafeInputError("E1 nuisance type is invalid", code="SCHEMA_INVALID")
        seen.add(nuisance_type)
        raw_parameters = entry.get("parameters")
        if not isinstance(raw_parameters, list):
            raise UnsafeInputError("E1 nuisance parameters are malformed", code="SCHEMA_INVALID")
        supplied: dict[str, int | float] = {}
        for raw_parameter in raw_parameters:
            parameter = _input_mapping(raw_parameter, "nuisance parameter")
            name = _input_required_string(parameter, "name", "nuisance parameter")
            value = parameter.get("value")
            if name in supplied or isinstance(value, bool) or not isinstance(value, (int, float)):
                raise UnsafeInputError("E1 nuisance parameter is invalid", code="SCHEMA_INVALID")
            supplied[name] = value

        expected: dict[str, dict[str, Any]] = {}
        contract_parameters = contracts[nuisance_type].get("parameters")
        if not isinstance(contract_parameters, list):
            raise E1ProtocolError("nuisance parameter contract is malformed")
        for raw_parameter in contract_parameters:
            parameter = _mapping(raw_parameter, "nuisance parameter contract")
            expected[_required_string(parameter, "name", "nuisance parameter contract")] = parameter
        if supplied.keys() != expected.keys():
            raise UnsafeInputError("E1 nuisance parameter set is invalid", code="SCHEMA_INVALID")
        for name, value in supplied.items():
            supported = _required_mapping(expected[name], "supported_normal_range", "nuisance")
            minimum = supported.get("minimum")
            maximum = supported.get("maximum")
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, (int, float))
                or not isinstance(maximum, (int, float))
            ):
                raise E1ProtocolError("supported nuisance range is malformed")
            if not minimum <= value <= maximum:
                raise UnsafeInputError(
                    "E1 nuisance is outside the approved normalization range",
                    code="NORMALIZATION_NOT_APPROVED",
                    details={"type": nuisance_type, "parameter": name, "value": value},
                )


def _allowed_part_revisions(protocol: E1Protocol) -> dict[str, set[str]]:
    raw_parts = protocol.section("universe").get("parts")
    if not isinstance(raw_parts, list):
        raise E1ProtocolError("E1 part universe is malformed")
    result: dict[str, set[str]] = {}
    for raw_part in raw_parts:
        part = _mapping(raw_part, "E1 part")
        part_id = _required_string(part, "part_id", "E1 part")
        raw_revisions = part.get("revisions")
        if not isinstance(raw_revisions, list):
            raise E1ProtocolError("E1 revision universe is malformed")
        result[part_id] = {
            _required_string(_mapping(revision, "E1 revision"), "cad_revision", "E1 revision")
            for revision in raw_revisions
        }
    return result


def _leak_value(manifest: Mapping[str, Any], protocol: E1Protocol, key: str) -> str:
    if key == "case_binding_sha256":
        source_hashes = _input_required_mapping(manifest, "source_hashes", "case manifest")
        return _input_required_string(source_hashes, key, "source hashes")
    if key in {"reference_sha256", "inspection_sha256", "authoritative_mask_sha256"}:
        source_hashes = _input_required_mapping(manifest, "source_hashes", "case manifest")
        return _input_required_string(source_hashes, key, "source hashes")
    return _input_required_string(manifest, key, "case manifest")


def _valid_rgb_png(*, defect: bool = False) -> bytes:
    image = Image.new("RGB", (64, 48), (196, 204, 211))
    draw = ImageDraw.Draw(image)
    draw.rectangle((6, 8, 58, 40), outline=(70, 80, 88), width=2)
    draw.ellipse((12, 17, 24, 29), fill=(45, 53, 60))
    draw.ellipse((40, 17, 52, 29), fill=(45, 53, 60))
    if defect:
        draw.rectangle((29, 20, 36, 27), fill=(255, 255, 255))
    return encode_png(image, mode="RGB")


def _build_current_bundle(root: Path) -> bytes:
    settings = Settings(data_dir=root)
    registry = CaseRegistry(settings)
    ingestor = ImageIngestor(settings)
    case_id = "case-e1-trust-fixture"
    registry.create_case(part_id="MVS-E1-PLATE-001", cad_revision="rev-A", case_id=case_id)
    registry.add_reference(
        case_id,
        ingestor.ingest_bytes(_valid_rgb_png(), filename="reference.png"),
        source_kind="synthetic_fixture",
        fixture_id="e1-trust-reference",
        expected_case_revision=1,
    )
    registry.add_inspection(
        case_id,
        ingestor.ingest_bytes(_valid_rgb_png(), filename="nominal.png"),
        source_kind="synthetic_fixture",
        fixture_id="demo-nominal",
        expected_case_revision=2,
    )
    registry.add_inspection(
        case_id,
        ingestor.ingest_bytes(_valid_rgb_png(defect=True), filename="inspection.png"),
        source_kind="synthetic_fixture",
        fixture_id="demo-defect",
        expected_case_revision=3,
    )
    analyses = registry.analyze_case(case_id, expected_case_revision=4)
    for analysis in analyses:
        current_revision = cast(int, registry.get_case_document(case_id)["case_revision"])
        registry.add_disposition(
            case_id,
            analysis_id=cast(str, analysis["analysis_id"]),
            decision="needs_review",
            reviewer_id="e1-trust-validator",
            rationale="Deterministic synthetic trust-boundary fixture.",
            reason_codes=["insufficient_evidence"],
            expected_case_revision=current_revision,
        )
    revision = cast(int, registry.get_case_document(case_id)["case_revision"])
    exported = EvidenceService(registry, settings).export_case(
        case_id,
        expected_case_revision=revision,
    )
    return exported.path.read_bytes()


def _exercise_bundle_rejection(valid: bytes, mutated: bytes, target_root: Path) -> None:
    settings = Settings(data_dir=target_root)
    registry = CaseRegistry(settings)
    service = EvidenceService(registry, settings)
    service.verify_bundle(valid)
    try:
        service.import_bundle(mutated)
    except MVSError:
        if registry.list_cases() or any(path.is_file() for path in settings.blob_dir.rglob("*")):
            raise RuntimeError("rejected evidence published partial registry state") from None
        raise


def _read_archive(bundle: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
            return {info.filename: archive.read(info) for info in archive.infolist()}
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise E1ProtocolError("trusted fixture archive could not be read") from exc


def _write_archive(files: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, files[path])
    return output.getvalue()


def _reseal_archive(files: dict[str, bytes]) -> bytes:
    manifest = _json_object(files[MANIFEST_NAME], "bundle manifest")
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise E1ProtocolError("trusted fixture artifact inventory is malformed")
    artifacts = cast(list[dict[str, Any]], raw_artifacts)
    for artifact in artifacts:
        path = _required_string(artifact, "path", "bundle artifact")
        data = files[path]
        artifact["sha256"] = sha256_bytes(data)
        artifact["byte_size"] = len(data)
    manifest["artifact_count"] = len(artifacts)
    manifest["payload_byte_size"] = sum(cast(int, artifact["byte_size"]) for artifact in artifacts)
    manifest["payload_sha256"] = payload_inventory_hash(artifacts)
    manifest_bytes = canonical_json_bytes(manifest)
    files[MANIFEST_NAME] = manifest_bytes
    files[SIDECAR_NAME] = f"{sha256_bytes(manifest_bytes)}\n".encode("ascii")
    return _write_archive(files)


def _remove_dispositions(bundle: bytes) -> bytes:
    files = _read_archive(bundle)
    manifest = _json_object(files[MANIFEST_NAME], "bundle manifest")
    artifacts = cast(list[dict[str, Any]], manifest["artifacts"])
    dispositions = [
        artifact for artifact in artifacts if artifact.get("role") == "human_disposition"
    ]
    if len(dispositions) < 2:
        raise E1ProtocolError("trusted fixture has no disposition artifact")
    removed = dispositions[0]
    del files[cast(str, removed["path"])]
    manifest["artifacts"] = [artifact for artifact in artifacts if artifact is not removed]
    files[MANIFEST_NAME] = canonical_json_bytes(manifest)
    return _reseal_archive(files)


def _mutate_pipeline(bundle: bytes) -> bytes:
    files = _read_archive(bundle)
    manifest = _json_object(files[MANIFEST_NAME], "bundle manifest")
    path = _first_artifact_path(manifest, role="analysis_result")
    analysis = _json_object(files[path], "analysis result")
    pipeline = _required_mapping(analysis, "pipeline", "analysis result")
    pipeline["pipeline_version"] = "999.0.0"
    files[path] = canonical_json_bytes(analysis)
    return _reseal_archive(files)


def _remove_one_payload_without_resealing(bundle: bytes, *, role: str) -> bytes:
    files = _read_archive(bundle)
    manifest = _json_object(files[MANIFEST_NAME], "bundle manifest")
    del files[_first_artifact_path(manifest, role=role)]
    return _write_archive(files)


def _modify_one_payload_without_resealing(bundle: bytes, *, role: str) -> bytes:
    files = _read_archive(bundle)
    manifest = _json_object(files[MANIFEST_NAME], "bundle manifest")
    path = _first_artifact_path(manifest, role=role)
    files[path] += b"e1-tampered"
    return _write_archive(files)


def _replace_first_json_artifact(bundle: bytes, replacement: bytes) -> bytes:
    files = _read_archive(bundle)
    manifest = _json_object(files[MANIFEST_NAME], "bundle manifest")
    path = _first_artifact_path(manifest, role="analysis_result")
    files[path] = replacement
    return _reseal_archive(files)


def _first_artifact_path(manifest: Mapping[str, Any], *, role: str) -> str:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise E1ProtocolError("trusted fixture artifact inventory is malformed")
    for raw_artifact in artifacts:
        artifact = _mapping(raw_artifact, "bundle artifact")
        if artifact.get("role") == role:
            return _required_string(artifact, "path", "bundle artifact")
    raise E1ProtocolError(f"trusted fixture has no {role} artifact")


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise E1ProtocolError(f"{label} is not valid JSON") from exc
    return _mapping(parsed, label)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise E1ProtocolError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _input_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UnsafeInputError(f"{label} must be an object", code="SCHEMA_INVALID")
    return cast(dict[str, Any], value)


def _input_required_mapping(value: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    return _input_mapping(value.get(key), f"{label}.{key}")


def _input_required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate:
        raise UnsafeInputError(f"{label}.{key} must be a non-empty string", code="SCHEMA_INVALID")
    return candidate


def _required_mapping(value: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    return _mapping(value.get(key), f"{label}.{key}")


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate:
        raise E1ProtocolError(f"{label}.{key} must be a non-empty string")
    return candidate


def _string_sequence(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise E1ProtocolError(f"{label} must be a non-empty string array")
    return tuple(cast(list[str], value))


def _string_set(value: Any, label: str) -> set[str]:
    return set(_string_sequence(value, label))
