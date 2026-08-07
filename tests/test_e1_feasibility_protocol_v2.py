"""Behavioral contracts for the immutable E1 feasibility-study inputs."""

# ruff: noqa: E402, I001

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from export_e1_feasibility_matrix import matrix_projection
from manufacturing_vision_studio.e1 import study_protocol_v2 as protocol_module
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    DEFAULT_STUDY_PROTOCOL_PATH,
    PROJECT_ROOT as STUDY_PROJECT_ROOT,
    STUDY_SCHEMA_PATH,
    StudyProtocolError,
    load_frozen_diagnostic_matrix,
    load_study_protocol_v2,
)

MAX_STUDY_INPUT_BYTES = 4 * 1024 * 1024
EXPECTED_ARTIFACT_ROOT_IDENTITY = "docs/evaluation/results/e1-feasibility-study"
EXPECTED_RAW_DATA_ROOT_IDENTITY = "data/e1-feasibility-study"

EXPECTED_IMPLEMENTATION_PROJECTION = (
    "Makefile",
    "configs/evaluation/e1-feasibility-diagnostic-108.json",
    "configs/evaluation/e1-feasibility-study.v1.json",
    "configs/evaluation/e1-v1-history-integrity.json",
    "configs/evaluation/e1-v1.json",
    "configs/evaluation/e1-v2-candidate-selection.json",
    "configs/evaluation/e1-v2.json",
    "pyproject.toml",
    "schemas/e1-candidate-selection.v2.json",
    "schemas/e1-case-manifest.v1.json",
    "schemas/e1-evaluation-protocol.v1.json",
    "schemas/e1-evaluation-protocol.v2.json",
    "schemas/e1-evaluation-result.v1.json",
    "schemas/e1-feasibility-study-artifact.v1.json",
    "schemas/e1-feasibility-study-config.v1.json",
    "schemas/e1-threshold-lock.v1.json",
    "src/manufacturing_vision_studio/__init__.py",
    "src/manufacturing_vision_studio/adapters.py",
    "src/manufacturing_vision_studio/canonical.py",
    "src/manufacturing_vision_studio/canonical_png.py",
    "src/manufacturing_vision_studio/config.py",
    "src/manufacturing_vision_studio/e1/__init__.py",
    "src/manufacturing_vision_studio/e1/domain.py",
    "src/manufacturing_vision_studio/e1/domain_v2.py",
    "src/manufacturing_vision_studio/e1/feature_mapping.py",
    "src/manufacturing_vision_studio/e1/generator.py",
    "src/manufacturing_vision_studio/e1/generator_v2.py",
    "src/manufacturing_vision_studio/e1/known_transform_v2.py",
    "src/manufacturing_vision_studio/e1/metrics.py",
    "src/manufacturing_vision_studio/e1/metrics_v2.py",
    "src/manufacturing_vision_studio/e1/model.py",
    "src/manufacturing_vision_studio/e1/oracle.py",
    "src/manufacturing_vision_studio/e1/policy_v2.py",
    "src/manufacturing_vision_studio/e1/protocol.py",
    "src/manufacturing_vision_studio/e1/protocol_v2.py",
    "src/manufacturing_vision_studio/e1/study_artifacts_v2.py",
    "src/manufacturing_vision_studio/e1/study_cli_v2.py",
    "src/manufacturing_vision_studio/e1/study_inference_v2.py",
    "src/manufacturing_vision_studio/e1/study_protocol_v2.py",
    "src/manufacturing_vision_studio/e1/study_retention_v2.py",
    "src/manufacturing_vision_studio/e1/study_runner_v2.py",
    "src/manufacturing_vision_studio/e1/study_truth_v2.py",
    "src/manufacturing_vision_studio/errors.py",
    "src/manufacturing_vision_studio/evidence.py",
    "src/manufacturing_vision_studio/images.py",
    "src/manufacturing_vision_studio/model.py",
    "src/manufacturing_vision_studio/registry.py",
)

EXPECTED_DIRECT_IMPORT_ALLOWLIST = {
    "known_transform_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.canonical_png",
    ),
    "study_artifacts_v2": ("manufacturing_vision_studio.canonical",),
    "study_cli_v2": (),
    "study_inference_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.e1.domain",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.model",
        "manufacturing_vision_studio.e1.protocol_v2",
        "manufacturing_vision_studio.errors",
        "manufacturing_vision_studio.images",
        "manufacturing_vision_studio.model",
    ),
    "study_protocol_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.e1.domain",
    ),
    "study_retention_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.e1.protocol_v2",
    ),
    "study_runner_v2": (
        "manufacturing_vision_studio.canonical_png",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.metrics_v2",
        "manufacturing_vision_studio.e1.protocol_v2",
    ),
    "study_truth_v2": (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.canonical_png",
        "manufacturing_vision_studio.e1.domain",
        "manufacturing_vision_studio.e1.domain_v2",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.generator",
        "manufacturing_vision_studio.e1.generator_v2",
        "manufacturing_vision_studio.e1.metrics_v2",
        "manufacturing_vision_studio.e1.oracle",
        "manufacturing_vision_studio.e1.protocol_v2",
    ),
}


def walk_schema_nodes(value: object) -> Iterator[Mapping[str, object]]:
    """Yield each object-shaped schema node, regardless of nesting location."""

    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_schema_nodes(child)


def expand_declared_seed_blocks(blocks: Mapping[str, object]) -> set[int]:
    """Expand only explicit checked seed starts and counts."""

    seeds: set[int] = set()
    for scope in blocks.values():
        assert isinstance(scope, Mapping)
        for block in scope.values():
            assert isinstance(block, Mapping)
            start = block["start"]
            count = block["count"]
            assert isinstance(start, int) and not isinstance(start, bool)
            assert isinstance(count, int) and not isinstance(count, bool)
            seeds.update(range(start, start + count))
    return seeds


def test_study_protocol_pins_base_commit_modes_and_hashes() -> None:
    """Catch a study configuration that silently changes its frozen experiment boundary."""

    protocol = load_study_protocol_v2()
    assert protocol.base_commit == "9fd6d0c600206083fde4fafc874e0226b5df60b3"
    assert protocol.phase_1_modes == ("NEAREST", "BILINEAR", "BICUBIC")
    assert protocol.phase_2_counts == {
        "clean": 24,
        "nuisance": 30,
        "defect": 60,
        "trust_boundary": 6,
        "total": 120,
    }
    assert protocol.source_hashes["candidate_a_raw_sha256"] == (
        "ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84"
    )
    assert protocol.source_hashes["candidate_b_raw_sha256"] == (
        "983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029"
    )
    assert protocol.source_hashes["selection_raw_sha256"] == (
        "92d3a2f86645a4d0fc33cfc39b769c6d2c4234383c7f132e803c449c7a66f2f3"
    )
    assert protocol.source_hashes["selection_record_sha256"] == (
        "3d4aa7e95240ed2bd4c018fb0762fdf788f919069cfbb935fd228de4b67dc2fe"
    )


def test_study_protocol_separates_portable_path_identity_from_runtime_paths() -> None:
    """Catch a protocol that exposes checkout-specific paths as portable evidence identity."""

    protocol = load_study_protocol_v2()

    assert protocol.artifact_root_identity == EXPECTED_ARTIFACT_ROOT_IDENTITY
    assert protocol.raw_data_root_identity == EXPECTED_RAW_DATA_ROOT_IDENTITY
    assert protocol.artifact_root == STUDY_PROJECT_ROOT / EXPECTED_ARTIFACT_ROOT_IDENTITY
    assert protocol.raw_data_root == STUDY_PROJECT_ROOT / EXPECTED_RAW_DATA_ROOT_IDENTITY


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("artifact_root", "docs/evaluation/results/alternate-e1-study"),
        ("raw_data_root", "data/alternate-e1-study"),
    ),
)
def test_study_protocol_schema_rejects_valid_relative_path_drift(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    """Catch a config schema that permits another otherwise-safe relative study path."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        paths = document["paths"]
        assert isinstance(paths, dict)
        paths[field] = replacement
        config_path.write_text(json.dumps(document))

        with pytest.raises(StudyProtocolError):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("artifact_root", "docs/evaluation/results/alternate-e1-study"),
        ("raw_data_root", "data/alternate-e1-study"),
    ),
)
def test_study_protocol_semantics_reject_path_drift_even_with_relaxed_schema(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    """Catch removal of the production semantic pin behind the config schema."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        paths = document["paths"]
        assert isinstance(paths, dict)
        paths[field] = replacement
        config_path.write_text(json.dumps(document))

        schema_path = fixture_dir / "schema.json"
        schema = json.loads(STUDY_SCHEMA_PATH.read_text())
        schema_paths = schema["properties"]["paths"]["properties"]
        schema_paths[field] = {"type": "string", "minLength": 1}
        schema_path.write_text(json.dumps(schema))

        with pytest.raises(StudyProtocolError, match="path"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_study_protocol_pins_immutable_ownership_map_hashes() -> None:
    """Catch missing or mutable revision/view ownership-map identity bindings."""

    protocol = load_study_protocol_v2()
    assert protocol.ownership_map_hashes == {
        "rev-A/front": "eadc490b04f8240e8356b3e20e75db08d79dfc5e27af180574d707836b3b776f",
        "rev-A/oblique_left": ("2d2a52ecae44ccae98455180211aaf528078707948dbf83f792223c550d3a074"),
        "rev-A/oblique_right": ("8c42a88c3ffdf3dda10b073665b6d7a565ddde54a7a7450ba3c0f4782be14477"),
        "rev-B/front": "5f69348a9ce7b646054dce02f95a0ff8ebd420c641ab40f414b0afa645ef49bc",
        "rev-B/oblique_left": ("1fb2f752d738a7bf595f8cae97860452a3a8628ea5cb3eec4347d1f42fe43b8b"),
        "rev-B/oblique_right": ("373337ec46da320dbbcdf0ffa14c22794db05208cd9491e5b272e0d34169830d"),
    }
    with pytest.raises(TypeError):
        protocol.ownership_map_hashes["rev-A/front"] = "0" * 64  # type: ignore[index]
    detached = protocol.document
    detached["ownership_map_hashes"]["rev-A/front"] = "0" * 64
    assert protocol.ownership_map_hashes["rev-A/front"] != "0" * 64


def test_truth_layer_direct_import_allowlist_is_complete_and_sorted() -> None:
    """Catch a dependency guard that rejects Task 4's explicitly retained imports."""

    truth_imports = load_study_protocol_v2().direct_import_allowlist()["study_truth_v2"]
    assert truth_imports == (
        "manufacturing_vision_studio.canonical",
        "manufacturing_vision_studio.canonical_png",
        "manufacturing_vision_studio.e1.domain",
        "manufacturing_vision_studio.e1.domain_v2",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.generator",
        "manufacturing_vision_studio.e1.generator_v2",
        "manufacturing_vision_studio.e1.metrics_v2",
        "manufacturing_vision_studio.e1.oracle",
        "manufacturing_vision_studio.e1.protocol_v2",
    )


def test_study_protocol_pins_complete_sorted_implementation_projection() -> None:
    """Catch a dependency audit whose declared repository scope is incomplete or reordered."""

    projection = load_study_protocol_v2().implementation_projection_paths()
    assert len(projection) == 47
    assert projection == EXPECTED_IMPLEMENTATION_PROJECTION


def test_study_protocol_pins_all_sorted_direct_import_allowlists() -> None:
    """Catch retained-module permissions that drift from the reviewed dependency boundary."""

    allowlist = load_study_protocol_v2().direct_import_allowlist()
    assert dict(allowlist) == EXPECTED_DIRECT_IMPORT_ALLOWLIST


def test_study_schema_requires_unique_projection_and_allowlist_entries() -> None:
    """Catch schema rules that admit duplicate dependency declarations."""

    schema = json.loads(STUDY_SCHEMA_PATH.read_text())
    properties = schema["properties"]
    assert properties["implementation_projection_paths"]["uniqueItems"] is True
    allowlist_properties = properties["direct_import_allowlist"]["properties"]
    assert set(allowlist_properties) == set(EXPECTED_DIRECT_IMPORT_ALLOWLIST)
    assert all(value["uniqueItems"] is True for value in allowlist_properties.values())


@pytest.mark.parametrize("mutation", ["duplicate", "reordered", "missing", "extra"])
def test_protocol_rejects_implementation_projection_mutations(
    tmp_path: Path, mutation: str
) -> None:
    """Catch dependency projection entries that are duplicated, reordered, removed, or added."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        projection = document["implementation_projection_paths"]
        assert isinstance(projection, list)
        if mutation == "duplicate":
            projection.insert(1, projection[0])
        elif mutation == "reordered":
            projection[0], projection[1] = projection[1], projection[0]
        elif mutation == "missing":
            projection.pop()
        else:
            projection.append("src/manufacturing_vision_studio/e1/unreviewed.py")
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


@pytest.mark.parametrize("mutation", ["duplicate", "reordered", "missing", "extra"])
def test_protocol_rejects_direct_import_allowlist_mutations(
    tmp_path: Path, mutation: str
) -> None:
    """Catch retained imports that are duplicated, reordered, removed, or added."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        allowlists = document["direct_import_allowlist"]
        assert isinstance(allowlists, dict)
        imports = allowlists["study_inference_v2"]
        assert isinstance(imports, list)
        if mutation == "duplicate":
            imports.insert(1, imports[0])
        elif mutation == "reordered":
            imports[0], imports[1] = imports[1], imports[0]
        elif mutation == "missing":
            imports.pop()
        else:
            imports.append("manufacturing_vision_studio.e1.unreviewed")
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


@pytest.mark.parametrize("allowlist_name", tuple(EXPECTED_DIRECT_IMPORT_ALLOWLIST))
def test_protocol_rejects_extra_entry_in_every_direct_import_allowlist(
    tmp_path: Path, allowlist_name: str
) -> None:
    """Catch a loader that pins only some retained-module allowlists."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        allowlists = document["direct_import_allowlist"]
        assert isinstance(allowlists, dict)
        imports = allowlists[allowlist_name]
        assert isinstance(imports, list)
        imports.append("manufacturing_vision_studio.e1.unreviewed")
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_protocol_rejects_missing_ownership_map_key(tmp_path: Path) -> None:
    """Catch a schema mutation that stops requiring one frozen ownership layout."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        del document["ownership_map_hashes"]["rev-B/oblique_right"]
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_protocol_rejects_wrong_valid_format_ownership_map_hash(tmp_path: Path) -> None:
    """Catch removal of semantic equality checking for frozen ownership-map hashes."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        document["ownership_map_hashes"]["rev-B/oblique_right"] = "0" * 64
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError, match="ownership-map hashes changed"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_schema_requires_exactly_the_six_frozen_ownership_map_keys() -> None:
    """Catch schema drift that adds, drops, or renames a frozen ownership layout key."""

    schema = json.loads(STUDY_SCHEMA_PATH.read_text())
    ownership_schema = schema["properties"]["ownership_map_hashes"]
    assert set(ownership_schema["required"]) == {
        "rev-A/front",
        "rev-A/oblique_left",
        "rev-A/oblique_right",
        "rev-B/front",
        "rev-B/oblique_left",
        "rev-B/oblique_right",
    }


def test_frozen_diagnostic_matrix_has_exact_ids_and_seed_block() -> None:
    """Catch an incomplete, reordered, or colliding diagnostic snapshot."""

    matrix = load_frozen_diagnostic_matrix()
    assert len(matrix) == 108
    assert matrix[0].diagnostic_id == "e1-v2-development-diagnostic-000"
    assert matrix[-1].diagnostic_id == "e1-v2-development-diagnostic-107"
    assert tuple(plan.seed for plan in matrix[:3]) == (800000, 800001, 800002)
    assert {plan.seed for plan in matrix} == set(range(800000, 800108))


def test_frozen_matrix_matches_the_historical_builder_only_in_test_code() -> None:
    """Catch a checked matrix whose concrete truth differs from its historical source."""

    expected = matrix_projection()
    actual = [plan.as_record() for plan in load_frozen_diagnostic_matrix()]
    assert actual == expected


def test_diagnostic_seeds_do_not_overlap_any_declared_evaluation_block() -> None:
    """Catch diagnostics that contaminate a declared E1 v2 evaluation seed block."""

    e1 = load_e1_v2_protocol()
    diagnostic = {row.seed for row in load_frozen_diagnostic_matrix()}
    declared = expand_declared_seed_blocks(e1.document["generator"]["seed_blocks"])
    assert diagnostic.isdisjoint(declared)


def test_every_object_schema_is_closed() -> None:
    """Catch an open schema object that could silently admit unreviewed fields."""

    schema = json.loads(STUDY_SCHEMA_PATH.read_text())
    for node in walk_schema_nodes(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False


@pytest.mark.parametrize(
    "payload",
    [b'{"schema_version":"1.0.0","schema_version":"1.0.0"}', b'{"x":NaN}'],
)
def test_strict_loader_rejects_duplicate_and_nonfinite_json(tmp_path: Path, payload: bytes) -> None:
    """Catch unsafe JSON forms before schema validation can normalize them."""

    path = tmp_path / "invalid.json"
    path.write_bytes(payload)
    with pytest.raises(StudyProtocolError):
        load_study_protocol_v2(path)


def test_strict_loader_rejects_oversized_config(tmp_path: Path) -> None:
    """Catch a config stream that exceeds the fixed loader input limit."""

    path = tmp_path / "oversized-config.json"
    path.write_bytes(b"{}" + (b" " * MAX_STUDY_INPUT_BYTES))

    with pytest.raises(StudyProtocolError, match="exceeds"):
        load_study_protocol_v2(path)


def test_strict_loader_rejects_oversized_schema(tmp_path: Path) -> None:
    """Catch a local schema stream that exceeds the fixed loader input limit."""

    fixture_dir = _project_local_fixture_dir(tmp_path)
    try:
        config_path = fixture_dir / "config.json"
        schema_path = fixture_dir / "schema.json"
        config_path.write_text('{"$schema":"schema.json"}')
        schema_path.write_bytes(b"{}" + (b" " * MAX_STUDY_INPUT_BYTES))
        with pytest.raises(StudyProtocolError, match="exceeds"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_matrix_loader_rejects_oversized_matrix(tmp_path: Path) -> None:
    """Catch a frozen matrix stream that exceeds the fixed loader input limit."""

    path = tmp_path / "oversized-matrix.json"
    path.write_bytes(b"{}" + (b" " * MAX_STUDY_INPUT_BYTES))
    with pytest.raises(StudyProtocolError, match="exceeds"):
        load_frozen_diagnostic_matrix(path)


def test_protocol_loader_rejects_oversized_retained_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch retained evidence that could otherwise be read without a byte bound."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    oversized = tmp_path / "oversized.raw.txt"
    oversized.write_bytes(b"x" * (MAX_STUDY_INPUT_BYTES + 1))
    snapshots = document["negative_result_snapshots"]
    assert isinstance(snapshots, list)
    canonical = STUDY_PROJECT_ROOT / snapshots[0]["checked_in_path"]
    original_reader = protocol_module._read_bounded_bytes

    def redirect(path: Path) -> bytes:
        return original_reader(oversized if path == canonical else path)

    monkeypatch.setattr(protocol_module, "_read_bounded_bytes", redirect)
    try:
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError, match="exceeds"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_protocol_rejects_negative_snapshot_original_path_drift(tmp_path: Path) -> None:
    """Catch provenance paths that remain sibling-prefixed but are not canonical."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        snapshots = document["negative_result_snapshots"]
        assert isinstance(snapshots, list)
        snapshots[0]["original_sibling_path"] = (
            "/Users/jangtaeho/manufacturing-vision-studio-e1-v2/forged-report.md"
        )
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError, match="snapshot identity changed"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_protocol_rejects_negative_snapshot_checked_in_path_alias(tmp_path: Path) -> None:
    """Catch byte-identical local aliases substituted for canonical retained evidence."""

    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        snapshots = document["negative_result_snapshots"]
        assert isinstance(snapshots, list)
        canonical = STUDY_PROJECT_ROOT / snapshots[0]["checked_in_path"]
        alias = fixture_dir / "byte-identical-report.raw.txt"
        alias.write_bytes(canonical.read_bytes())
        snapshots[0]["checked_in_path"] = alias.relative_to(STUDY_PROJECT_ROOT).as_posix()
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError, match="snapshot identity changed"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def _project_local_fixture_dir(tmp_path: Path) -> Path:
    fixture_dir = STUDY_PROJECT_ROOT / "tmp" / "e1-protocol-tests" / tmp_path.name
    fixture_dir.mkdir(parents=True)
    return fixture_dir


def _project_local_protocol_copy(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    fixture_dir = _project_local_fixture_dir(tmp_path)
    config_path = fixture_dir / "config.json"
    schema_path = fixture_dir / "schema.json"
    document: dict[str, object] = json.loads(DEFAULT_STUDY_PROTOCOL_PATH.read_text())
    document["$schema"] = "schema.json"
    config_path.write_text(json.dumps(document))
    schema_path.write_bytes(STUDY_SCHEMA_PATH.read_bytes())
    return fixture_dir, config_path, document
