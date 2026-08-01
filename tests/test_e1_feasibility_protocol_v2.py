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


def test_protocol_loader_rejects_oversized_retained_snapshot(tmp_path: Path) -> None:
    """Catch retained evidence that could otherwise be read without a byte bound."""

    fixture_dir = _project_local_fixture_dir(tmp_path)
    try:
        config_path = fixture_dir / "config.json"
        schema_path = fixture_dir / "schema.json"
        snapshot_path = fixture_dir / "oversized.raw.txt"
        document = json.loads(DEFAULT_STUDY_PROTOCOL_PATH.read_text())
        document["$schema"] = "schema.json"
        document["negative_result_snapshots"][0]["checked_in_path"] = (
            fixture_dir.relative_to(STUDY_PROJECT_ROOT) / snapshot_path.name
        ).as_posix()
        config_path.write_text(json.dumps(document))
        schema_path.write_bytes(STUDY_SCHEMA_PATH.read_bytes())
        snapshot_path.write_bytes(b"x" * (MAX_STUDY_INPUT_BYTES + 1))
        with pytest.raises(StudyProtocolError, match="exceeds"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def _project_local_fixture_dir(tmp_path: Path) -> Path:
    fixture_dir = STUDY_PROJECT_ROOT / "tmp" / "e1-protocol-tests" / tmp_path.name
    fixture_dir.mkdir(parents=True)
    return fixture_dir
