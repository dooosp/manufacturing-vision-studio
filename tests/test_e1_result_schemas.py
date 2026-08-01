from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.e1.artifacts import (
    DEFAULT_VOLATILE_FIELDS,
    E1ArtifactError,
    deterministic_projection,
    finalize_case_manifest,
    finalize_evaluation_result,
    finalize_threshold_lock,
    validate_e1_document,
)
from manufacturing_vision_studio.e1.metrics import (
    EvaluationChecks,
    EvaluationObservation,
    evaluate,
)
from manufacturing_vision_studio.e1.protocol import load_e1_protocol

ROOT = Path(__file__).parents[1]
SCHEMA_PATHS = {
    "case-manifest": ROOT / "schemas/e1-case-manifest.v1.json",
    "evaluation-result": ROOT / "schemas/e1-evaluation-result.v1.json",
    "threshold-lock": ROOT / "schemas/e1-threshold-lock.v1.json",
}
PROTOCOL = load_e1_protocol()
PROTOCOL_SHA256 = PROTOCOL.configuration_sha256
GENERATOR_SHA256 = PROTOCOL.generator_configuration_sha256
CODE_SHA = "c" * 40


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _walk_json(value: Any, pointer: str = "") -> list[tuple[str, Any]]:
    walked = [(pointer, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            walked.extend(_walk_json(child, f"{pointer}/{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walked.extend(_walk_json(child, f"{pointer}/{index}"))
    return walked


def _digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def _generator() -> dict[str, Any]:
    return {
        "generator_id": "mvs-e1-generator",
        "generator_version": "1.0.0",
        "generator_configuration_sha256": GENERATOR_SHA256,
    }


def _protocol() -> dict[str, Any]:
    return {
        "protocol_id": "mvs-e1",
        "protocol_version": "1.3.0",
        "protocol_sha256": PROTOCOL_SHA256,
    }


def _case(case_id: str) -> dict[str, Any]:
    _, split, group, ordinal_text = case_id.split("-", 3)
    ordinal = int(ordinal_text)
    expected = (
        "ABSTAIN" if group == "trust_boundary" else ("ANOMALY" if group == "defect" else "NORMAL")
    )
    support = (
        "UNSUPPORTED_OR_ABSTAIN_RANGE" if group == "trust_boundary" else "SUPPORTED_NORMAL_RANGE"
    )
    defect = (
        {
            "defect_id": f"defect:{case_id}",
            "type": "scratch",
            "severity": "MEDIUM",
            "target_feature_id": "top_face",
            "parameters": [
                {"name": "length", "unit": "px", "value": 48},
                {"name": "width", "unit": "px", "value": 4},
            ],
        }
        if group == "defect"
        else None
    )
    nuisance = (
        [
            {
                "type": "translation",
                "parameters": [{"name": "max_abs_shift", "unit": "px", "value": 3}],
            }
        ]
        if group == "nuisance"
        else []
    )
    trust = (
        {
            "scenario_id": f"scenario:{split}:{ordinal:03d}",
            "expected_error_code": "SCHEMA_INVALID",
            "publication_allowed": False,
        }
        if group == "trust_boundary"
        else None
    )
    return {
        "case_id": case_id,
        "profile_membership": ["full", "mini"],
        "split": split,
        "group": group,
        "ordinal": ordinal,
        "seed_family": f"family:{split}:{group}",
        "seed": 100000 + ordinal,
        "recipe_id": f"mvs-e1-recipe-v1/{case_id}",
        "recipe_version": "1.0.0",
        "part_identity": {"part_id": "MVS-E1-PLATE-001", "cad_revision": "rev-A"},
        "view_id": "front",
        "expected_outcome": expected,
        "support_boundary": support,
        "defect": defect,
        "nuisance_profile": nuisance,
        "trust_boundary": trust,
        "generator": _generator(),
        "source_hashes": {
            "reference_sha256": _digest(f"{case_id}:reference"),
            "inspection_sha256": _digest(f"{case_id}:inspection"),
            "authoritative_mask_sha256": _digest(f"{case_id}:mask"),
            "case_binding_sha256": "0" * 64,
        },
    }


def valid_case_manifest() -> dict[str, Any]:
    config = _load_json(ROOT / "configs/evaluation/e1-v1.json")
    case_ids = config["dataset_profiles"]["mini_selection"]["exact_case_ids"]
    cases = [_case(case_id) for case_id in case_ids]
    group_counts = Counter(case["group"] for case in cases)
    split_counts: dict[str, Any] = {}
    for split in ("development", "calibration", "test"):
        selected = [case for case in cases if case["split"] == split]
        groups = Counter(case["group"] for case in selected)
        split_counts[split] = {
            "case_count": len(selected),
            "group_counts": {
                name: groups[name] for name in ("clean", "nuisance", "defect", "trust_boundary")
            },
        }
    document = {
        "schema_version": "1.0.0",
        "manifest_id": "e1-mini-case-manifest-v1",
        "protocol": _protocol(),
        "generator": _generator(),
        "profile": "mini",
        "counts": {
            "case_count": len(cases),
            "inference_case_count": len(cases) - group_counts["trust_boundary"],
            "trust_case_count": group_counts["trust_boundary"],
            "group_counts": {
                name: group_counts[name]
                for name in ("clean", "nuisance", "defect", "trust_boundary")
            },
            "split_counts": split_counts,
        },
        "cases": cases,
        "manifest_sha256": "0" * 64,
    }
    return finalize_case_manifest(document)


def _calibration_gates(*, all_passed: bool = True) -> list[dict[str, Any]]:
    contracts = [
        ("medium_high_defect_recall", "gte", 0.9),
        ("nuisance_only_false_positive_rate", "lte", 0.05),
        ("positive_case_median_dice", "gte", 0.7),
        ("affected_feature_mapping_accuracy", "gte", 0.95),
    ]
    return [
        {
            "gate_id": gate_id,
            "operator": operator,
            "threshold": threshold,
            "observed": 1.0 if operator == "gte" and (all_passed or index > 0) else 0.0,
            "passed": all_passed or index > 0,
            "reason": None if all_passed or index > 0 else "below_threshold",
        }
        for index, (gate_id, operator, threshold) in enumerate(contracts)
    ]


def valid_threshold_lock(*, locked: bool = True) -> dict[str, Any]:
    document = {
        "schema_version": "1.0.0",
        "lock_id": "e1-mini-threshold-lock-v1",
        "protocol": _protocol(),
        "profile": "mini",
        "code_commit_sha": CODE_SHA,
        "dirty_worktree": False,
        "calibration_manifest_sha256": "d" * 64,
        "calibration_result_sha256": "e" * 64,
        "threshold_source_split": "calibration",
        "selection_method": "single_pre_registered_candidate_confirmed_on_calibration",
        "selection_candidates": [0.0025],
        "locked_image_threshold": 0.0025,
        "calibration_gate_results": _calibration_gates(all_passed=locked),
        "lock_status": "LOCKED" if locked else "HOLD",
        "test_execution_allowed": locked,
        "failure_action": "HOLD_WITHOUT_TEST_EXECUTION",
        "threshold_lock_sha256": "0" * 64,
    }
    return finalize_threshold_lock(document)


def _valid_metrics() -> dict[str, Any]:
    observations = [
        EvaluationObservation(
            case_id="positive",
            split="test",
            group="defect",
            expected_outcome="ANOMALY",
            actual_outcome="ANOMALY",
            anomaly_score=0.01,
            defect_type="scratch",
            severity="MEDIUM",
            cad_revision="rev-A",
            view_id="front",
            truth_positive_pixels=20,
            predicted_positive_pixels=20,
            intersection_pixels=20,
            total_pixels=100,
            expected_feature_id="top_face",
            predicted_feature_id="top_face",
        ),
        EvaluationObservation(
            case_id="negative",
            split="test",
            group="nuisance",
            expected_outcome="NORMAL",
            actual_outcome="NORMAL",
            anomaly_score=0.0001,
            nuisance_types=("translation",),
            cad_revision="rev-B",
            view_id="oblique_left",
            total_pixels=100,
        ),
        EvaluationObservation(
            case_id="trust-revision",
            split="test",
            group="trust_boundary",
            expected_outcome="ABSTAIN",
            actual_outcome="ABSTAIN",
            anomaly_score=None,
            expected_abstention_reason="REVISION_MISMATCH",
            abstention_reason="REVISION_MISMATCH",
            trust_scenario="revision_mismatch",
        ),
    ]
    config = _load_json(ROOT / "configs/evaluation/e1-v1.json")
    return evaluate(
        observations,
        EvaluationChecks(1, 1, 0, True, True),
        config["acceptance_gates"],
        bootstrap_replicates=10,
    )


def valid_evaluation_result(*, completed: bool = True) -> dict[str, Any]:
    manifest = valid_case_manifest()
    threshold = valid_threshold_lock(locked=completed)
    metrics = _valid_metrics() if completed else None
    verdict = metrics["verdict"] if metrics is not None else "HOLD"
    document = {
        "schema_version": "1.0.0",
        "result_id": "e1-mini-result-v1",
        "evaluation_run_id": "e1-mini-run-001",
        "generated_at": "2026-07-31T00:00:00Z",
        "duration_ms": 1234,
        "local_absolute_paths": ["/tmp/e1-mini"],
        "evaluation_status": "COMPLETED" if completed else "CALIBRATION_HOLD",
        "profile": "mini",
        "protocol": _protocol(),
        "code": {"code_commit_sha": CODE_SHA, "dirty_worktree": False},
        "generator": _generator(),
        "dataset": {
            "dataset_id": "e1-mini",
            "dataset_version": "1.0.0",
            "dataset_manifest_sha256": manifest["manifest_sha256"],
            "case_count": 48,
            "inference_case_count": 44,
            "trust_case_count": 4,
        },
        "pipeline": {
            "pipeline_id": "e1-normalized-local-difference",
            "pipeline_version": "1.1.0",
        },
        "model": {
            "model_id": "e1-normalized-local-difference",
            "model_version": "1.1.0",
            "model_artifact_sha256": (
                "15d557ed44541d4e3b7f382b9b6ff6a9e510a1924b7b9d86a07c7ba52bcbbc03"
            ),
        },
        "configuration_sha256": (
            "70400090ee420f42470e1b8c539f1145e5a71620ceb57d32b7cf6823ffd8ade0"
        ),
        "threshold": {
            "lock_id": threshold["lock_id"],
            "threshold_lock_sha256": threshold["threshold_lock_sha256"],
            "lock_status": threshold["lock_status"],
            "locked_image_threshold": 0.0025,
            "threshold_source_split": "calibration",
        },
        "execution_environment": {
            "runtime_id": "python-numpy",
            "python_version": "3.12.11",
            "numpy_version": "2.3.1",
            "pillow_version": "11.3.0",
            "platform": "test-platform",
        },
        "metrics": metrics,
        "reproducibility": {
            "repeat_count": 2,
            "equivalent": True,
            "deterministic_projection_sha256s": ["f" * 64, "f" * 64],
            "volatile_fields_excluded": sorted(DEFAULT_VOLATILE_FIELDS),
        },
        "error_gallery": [],
        "exclusions": ["Trust-boundary cases are reported separately."],
        "limitations": ["Synthetic evaluation only; not shop-floor validation."],
        "deterministic_projection_sha256": "0" * 64,
        "result_sha256": "0" * 64,
        "verdict": verdict,
    }
    return finalize_evaluation_result(document)


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_PATHS))
def test_e1_result_schemas_are_strict_local_draft_2020_12(schema_name: str) -> None:
    schema = _load_json(SCHEMA_PATHS[schema_name])
    Draft202012Validator.check_schema(schema)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith(f"/e1-{schema_name}.v1.json")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": "1.0.0"}
    for pointer, value in _walk_json(schema):
        if isinstance(value, dict) and value.get("type") == "object":
            assert value.get("additionalProperties") is False, f"unbounded object at {pointer}"
        if isinstance(value, dict) and "$ref" in value:
            assert value["$ref"].startswith("#/"), f"external ref at {pointer}"


def test_minimal_case_manifest_is_bound_and_rejects_drift() -> None:
    manifest = valid_case_manifest()

    validate_e1_document(manifest, "case-manifest")
    assert manifest["counts"]["case_count"] == 48
    assert len(manifest["cases"]) == 48
    assert all(
        case["source_hashes"]["case_binding_sha256"] != "0" * 64 for case in manifest["cases"]
    )

    unknown = copy.deepcopy(manifest)
    unknown["generator"]["unregistered"] = True
    with pytest.raises(E1ArtifactError, match="does not satisfy") as exc_info:
        validate_e1_document(unknown, "case-manifest")
    assert exc_info.value.code == "SCHEMA_INVALID"

    tampered = copy.deepcopy(manifest)
    tampered["cases"][0]["seed"] += 1
    with pytest.raises(E1ArtifactError) as exc_info:
        validate_e1_document(tampered, "case-manifest")
    assert exc_info.value.code == "HASH_MISMATCH"


def test_case_manifest_requires_frozen_profile_order_and_bindings() -> None:
    manifest = valid_case_manifest()

    reordered = copy.deepcopy(manifest)
    reordered["cases"][0], reordered["cases"][1] = (
        reordered["cases"][1],
        reordered["cases"][0],
    )
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_case_manifest(reordered)
    assert exc_info.value.code == "SCHEMA_INVALID"

    wrong_protocol = copy.deepcopy(manifest)
    wrong_protocol["protocol"]["protocol_sha256"] = "0" * 64
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_case_manifest(wrong_protocol)
    assert exc_info.value.code == "HASH_MISMATCH"

    wrong_generator = copy.deepcopy(manifest)
    wrong_generator["generator"]["generator_configuration_sha256"] = "0" * 64
    for case in wrong_generator["cases"]:
        case["generator"] = copy.deepcopy(wrong_generator["generator"])
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_case_manifest(wrong_generator)
    assert exc_info.value.code == "HASH_MISMATCH"


def test_threshold_lock_requires_exact_order_contract_and_self_hash() -> None:
    lock = valid_threshold_lock()
    validate_e1_document(lock, "threshold-lock")

    reordered = copy.deepcopy(lock)
    reordered["calibration_gate_results"].reverse()
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_threshold_lock(reordered)
    assert exc_info.value.code == "SCHEMA_INVALID"

    tampered = copy.deepcopy(lock)
    tampered["locked_image_threshold"] = 0.1
    with pytest.raises(E1ArtifactError) as exc_info:
        validate_e1_document(tampered, "threshold-lock")
    assert exc_info.value.code == "SCHEMA_INVALID"

    false_claim = copy.deepcopy(lock)
    false_claim["calibration_gate_results"][0]["observed"] = 0.0
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_threshold_lock(false_claim)
    assert exc_info.value.code == "SCHEMA_INVALID"


def test_completed_and_calibration_hold_results_validate() -> None:
    completed = valid_evaluation_result(completed=True)
    hold = valid_evaluation_result(completed=False)

    validate_e1_document(completed, "evaluation-result")
    validate_e1_document(hold, "evaluation-result")
    assert completed["metrics"] is not None
    assert hold["metrics"] is None
    assert hold["verdict"] == "HOLD"


def test_result_projection_excludes_only_declared_volatile_fields() -> None:
    first = valid_evaluation_result()
    changed = copy.deepcopy(first)
    changed["evaluation_run_id"] = "e1-mini-run-999"
    changed["generated_at"] = "2026-08-01T00:00:00Z"
    changed["duration_ms"] = 9999
    changed["local_absolute_paths"] = ["/different/root"]
    second = finalize_evaluation_result(changed)

    assert first["result_sha256"] != second["result_sha256"]
    assert first["deterministic_projection_sha256"] == second["deterministic_projection_sha256"]
    assert deterministic_projection(first).document == deterministic_projection(second).document

    material = copy.deepcopy(first)
    material["code"]["dirty_worktree"] = True
    material = finalize_evaluation_result(material)
    assert material["deterministic_projection_sha256"] != first["deterministic_projection_sha256"]


def test_result_rejects_unknown_nested_field_and_hash_tamper() -> None:
    result = valid_evaluation_result()
    unknown = copy.deepcopy(result)
    unknown["execution_environment"]["hostname"] = "private-host"
    with pytest.raises(E1ArtifactError) as exc_info:
        validate_e1_document(unknown, "evaluation-result")
    assert exc_info.value.code == "SCHEMA_INVALID"

    tampered = copy.deepcopy(result)
    tampered["dataset"]["dataset_id"] = "changed"
    with pytest.raises(E1ArtifactError) as exc_info:
        validate_e1_document(tampered, "evaluation-result")
    assert exc_info.value.code == "HASH_MISMATCH"


def test_result_requires_exact_gate_repeatability_and_profile_contracts() -> None:
    result = valid_evaluation_result()

    duplicate_gate = copy.deepcopy(result)
    duplicate_gate["metrics"]["gates"][1] = copy.deepcopy(duplicate_gate["metrics"]["gates"][0])
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_evaluation_result(duplicate_gate)
    assert exc_info.value.code == "SCHEMA_INVALID"

    false_repeatability = copy.deepcopy(result)
    false_repeatability["reproducibility"]["deterministic_projection_sha256s"][1] = "e" * 64
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_evaluation_result(false_repeatability)
    assert exc_info.value.code == "SCHEMA_INVALID"

    wrong_profile_count = copy.deepcopy(result)
    wrong_profile_count["dataset"]["case_count"] = 480
    with pytest.raises(E1ArtifactError) as exc_info:
        finalize_evaluation_result(wrong_profile_count)
    assert exc_info.value.code == "SCHEMA_INVALID"
