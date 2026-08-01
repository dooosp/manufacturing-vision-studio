from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.e1 import trust_boundaries
from manufacturing_vision_studio.e1.protocol import load_e1_protocol
from manufacturing_vision_studio.e1.trust_boundaries import (
    run_trust_boundary_suite,
    validate_e1_case_manifest,
    validate_supplemental_hardlink_input,
)
from manufacturing_vision_studio.errors import MVSError

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "evaluation" / "e1-v1.json"


def _config_trust_cases() -> list[dict[str, Any]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return config["taxonomies"]["trust_boundary_cases"]


def test_all_frozen_trust_boundaries_abstain_with_exact_codes_and_no_publication(
    tmp_path: Path,
) -> None:
    report = run_trust_boundary_suite(tmp_path / "trust-suite")
    expected = _config_trust_cases()

    assert len(report.results) == 24
    assert [result.scenario_id for result in report.results] == [
        case["scenario_id"] for case in expected
    ]
    assert [result.split for result in report.results] == [case["split"] for case in expected]
    assert [result.expected_error_code for result in report.results] == [
        case["expected_error_code"] for case in expected
    ]
    assert all(result.expected_outcome == "ABSTAIN" for result in report.results)
    assert all(result.actual_outcome == "ABSTAIN" for result in report.results)
    assert all(result.actual_error_code == result.expected_error_code for result in report.results)
    assert all(result.publication_count == 0 for result in report.results)
    assert all(result.passed for result in report.results)
    assert report.publication_count == 0
    assert report.all_passed is True

    record = report.as_record()
    assert record["scenario_count"] == 24
    assert record["publication_count"] == 0
    assert record["all_passed"] is True


def test_suite_is_bound_to_the_checked_in_protocol_and_golden_bundle(tmp_path: Path) -> None:
    protocol = load_e1_protocol()

    report = run_trust_boundary_suite(
        tmp_path / "explicit-protocol",
        protocol=protocol,
        golden_bundle_path=ROOT / "docs" / "releases" / "v0.1.0" / "evidence-bundle.zip",
    )

    assert report.all_passed
    assert {result.scenario_id for result in report.results} == {
        case["scenario_id"] for case in _config_trust_cases()
    }


def test_trust_manifest_fixture_uses_nested_case_binding() -> None:
    protocol = load_e1_protocol()
    manifest = trust_boundaries._base_manifest(protocol)

    assert "case_binding_sha256" not in manifest
    assert manifest["source_hashes"]["case_binding_sha256"]
    validate_e1_case_manifest(manifest, protocol)

    legacy_shape = deepcopy(manifest)
    legacy_shape["case_binding_sha256"] = legacy_shape["source_hashes"].pop("case_binding_sha256")
    with pytest.raises(MVSError) as exc_info:
        validate_e1_case_manifest(legacy_shape, protocol)

    assert exc_info.value.code == "HASH_MISMATCH"


def test_hardlink_is_a_separate_supplemental_fail_closed_check(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    linked = tmp_path / "linked.png"
    source.write_bytes(b"content-is-not-read-after-hardlink-preflight")
    try:
        os.link(source, linked)
    except OSError as exc:  # pragma: no cover - platform-specific permission guard
        pytest.skip(f"hardlink creation is unavailable: {exc}")

    with pytest.raises(MVSError) as exc_info:
        validate_supplemental_hardlink_input(
            linked,
            settings=Settings(data_dir=tmp_path / "data"),
        )

    assert exc_info.value.code == "NON_REGULAR_INPUT"
