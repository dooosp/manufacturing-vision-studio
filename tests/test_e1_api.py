from __future__ import annotations

import copy
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from manufacturing_vision_studio.api import create_app
from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.e1.artifacts import (
    DEFAULT_VOLATILE_FIELDS,
    E1ArtifactStore,
    finalize_case_manifest,
    finalize_evaluation_result,
    finalize_threshold_lock,
)
from manufacturing_vision_studio.e1.metrics import (
    EvaluationChecks,
    EvaluationObservation,
    evaluate,
)
from manufacturing_vision_studio.e1.runner import _render_overlay

ROOT = Path(__file__).parents[1]
CONFIG = json.loads((ROOT / "configs" / "evaluation" / "e1-v1.json").read_text(encoding="utf-8"))
CODE_SHA = "c" * 40
PNG_BYTES = encode_png(Image.new("RGB", (1, 1), (128, 128, 128)), mode="RGB")


@dataclass(frozen=True)
class FakeProtocol:
    protocol_id: str
    protocol_version: str
    configuration_sha256: str
    generator_id: str
    generator_version: str
    generator_configuration_sha256: str
    exact_mini_case_ids: tuple[str, ...]
    _document: dict[str, Any]

    @property
    def document(self) -> dict[str, Any]:
        return copy.deepcopy(self._document)


FAKE_PROTOCOL = FakeProtocol(
    protocol_id="mvs-e1",
    protocol_version="1.3.0",
    configuration_sha256=sha256_bytes(b"mvs-e1-protocol-1.3.0"),
    generator_id="mvs-e1-generator",
    generator_version="1.0.0",
    generator_configuration_sha256=sha256_bytes(b"mvs-e1-generator-1.0.0"),
    exact_mini_case_ids=tuple(CONFIG["dataset_profiles"]["mini_selection"]["exact_case_ids"]),
    _document={"dataset_profiles": copy.deepcopy(CONFIG["dataset_profiles"])},
)


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def _generator() -> dict[str, Any]:
    return {
        "generator_id": FAKE_PROTOCOL.generator_id,
        "generator_version": FAKE_PROTOCOL.generator_version,
        "generator_configuration_sha256": FAKE_PROTOCOL.generator_configuration_sha256,
    }


def _protocol() -> dict[str, Any]:
    return {
        "protocol_id": FAKE_PROTOCOL.protocol_id,
        "protocol_version": FAKE_PROTOCOL.protocol_version,
        "protocol_sha256": FAKE_PROTOCOL.configuration_sha256,
    }


def _mini_case_ids() -> set[str]:
    return set(FAKE_PROTOCOL.exact_mini_case_ids)


def _case(case_id: str) -> dict[str, Any]:
    _, split, group, ordinal_text = case_id.split("-", 3)
    ordinal = int(ordinal_text)
    expected_outcome = (
        "ABSTAIN" if group == "trust_boundary" else "ANOMALY" if group == "defect" else "NORMAL"
    )
    support_boundary = (
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
    nuisance_profile = (
        [
            {
                "type": "translation",
                "parameters": [{"name": "max_abs_shift", "unit": "px", "value": 3}],
            }
        ]
        if group == "nuisance"
        else []
    )
    trust_boundary = (
        {
            "scenario_id": f"scenario:{split}:{ordinal:03d}",
            "expected_error_code": "SCHEMA_INVALID",
            "publication_allowed": False,
        }
        if group == "trust_boundary"
        else None
    )
    profile_membership = ["full", "mini"] if case_id in _mini_case_ids() else ["full"]
    return {
        "case_id": case_id,
        "profile_membership": profile_membership,
        "split": split,
        "group": group,
        "ordinal": ordinal,
        "seed_family": f"family:{split}:{group}",
        "seed": 100000 + ordinal,
        "recipe_id": f"mvs-e1-recipe-v1/{case_id}",
        "recipe_version": "1.0.0",
        "part_identity": {"part_id": "MVS-E1-PLATE-001", "cad_revision": "rev-A"},
        "view_id": "front",
        "expected_outcome": expected_outcome,
        "support_boundary": support_boundary,
        "defect": defect,
        "nuisance_profile": nuisance_profile,
        "trust_boundary": trust_boundary,
        "generator": _generator(),
        "source_hashes": {
            "reference_sha256": _digest(f"{case_id}:reference"),
            "inspection_sha256": _digest(f"{case_id}:inspection"),
            "authoritative_mask_sha256": _digest(f"{case_id}:mask"),
            "case_binding_sha256": "0" * 64,
        },
    }


def _case_ids(profile: str) -> list[str]:
    if profile == "mini":
        return list(FAKE_PROTOCOL.exact_mini_case_ids)
    composition = FAKE_PROTOCOL.document["dataset_profiles"]["split_composition"]
    case_ids: list[str] = []
    for split in ("development", "calibration", "test"):
        groups = composition[split]["group_counts"]
        for group in ("clean", "nuisance", "defect", "trust_boundary"):
            case_ids.extend(f"e1-{split}-{group}-{ordinal:03d}" for ordinal in range(groups[group]))
    return case_ids


def _manifest(profile: str) -> dict[str, Any]:
    cases = [_case(case_id) for case_id in _case_ids(profile)]
    group_counts = Counter(case["group"] for case in cases)
    split_counts: dict[str, Any] = {}
    for split in ("development", "calibration", "test"):
        selected = [case for case in cases if case["split"] == split]
        split_groups = Counter(case["group"] for case in selected)
        split_counts[split] = {
            "case_count": len(selected),
            "group_counts": {
                name: split_groups[name]
                for name in ("clean", "nuisance", "defect", "trust_boundary")
            },
        }
    document = {
        "schema_version": "1.0.0",
        "manifest_id": f"e1-{profile}-case-manifest-v1",
        "protocol": _protocol(),
        "generator": _generator(),
        "profile": profile,
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


def _threshold_lock(
    profile: str,
    *,
    locked: bool = True,
    manifest_sha256: str = "d" * 64,
    calibration_result_sha256: str = "e" * 64,
) -> dict[str, Any]:
    document = {
        "schema_version": "1.0.0",
        "lock_id": f"e1-{profile}-threshold-lock-v1",
        "protocol": _protocol(),
        "profile": profile,
        "code_commit_sha": CODE_SHA,
        "dirty_worktree": False,
        "calibration_manifest_sha256": manifest_sha256,
        "calibration_result_sha256": calibration_result_sha256,
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


def _metrics(profile: str) -> dict[str, Any]:
    observations: list[EvaluationObservation] = []
    for case_id in _case_ids(profile):
        case = _case(case_id)
        if case["group"] == "trust_boundary":
            trust = case["trust_boundary"]
            assert isinstance(trust, dict)
            observations.append(
                EvaluationObservation(
                    case_id=case_id,
                    split=case["split"],
                    group="trust_boundary",
                    expected_outcome="ABSTAIN",
                    actual_outcome="ABSTAIN",
                    anomaly_score=None,
                    cad_revision=case["part_identity"]["cad_revision"],
                    view_id=case["view_id"],
                    expected_abstention_reason=trust["expected_error_code"],
                    abstention_reason=trust["expected_error_code"],
                    trust_scenario=trust["scenario_id"],
                    published=False,
                )
            )
            continue
        if case["split"] != "test":
            continue
        defect = case["defect"]
        is_defect = isinstance(defect, dict)
        observations.append(
            EvaluationObservation(
                case_id=case_id,
                split="test",
                group=case["group"],
                expected_outcome=case["expected_outcome"],
                actual_outcome="ANOMALY" if is_defect else "NORMAL",
                anomaly_score=0.01 if is_defect else 0.0001,
                defect_type=defect["type"] if is_defect else None,
                severity=defect["severity"] if is_defect else None,
                nuisance_types=tuple(nuisance["type"] for nuisance in case["nuisance_profile"]),
                cad_revision=case["part_identity"]["cad_revision"],
                view_id=case["view_id"],
                truth_positive_pixels=20 if is_defect else 0,
                predicted_positive_pixels=20 if is_defect else 0,
                intersection_pixels=20 if is_defect else 0,
                total_pixels=100,
                expected_feature_id=defect["target_feature_id"] if is_defect else None,
                predicted_feature_id=defect["target_feature_id"] if is_defect else None,
            )
        )
    return evaluate(
        observations,
        EvaluationChecks(1, 1, 0, True, True),
        CONFIG["acceptance_gates"],
        bootstrap_replicates=10,
    )


def _result(profile: str) -> dict[str, Any]:
    manifest = _manifest(profile)
    threshold = _threshold_lock(profile)
    metrics = _metrics(profile)
    case_id = _case_ids(profile)[0]
    png_sha256 = sha256_bytes(PNG_BYTES)
    error_gallery = [
        {
            "case_id": case_id,
            "category": "low_dice",
            "part_identity": {"part_id": "MVS-E1-PLATE-001", "cad_revision": "rev-A"},
            "score": 0.2,
            "threshold": 0.0025,
            "expected_feature_id": "top_face",
            "predicted_feature_id": "top_face",
            "failure_reason": "Dice below review target.",
            "source_hashes": {
                "reference_sha256": png_sha256,
                "inspection_sha256": png_sha256,
                "authoritative_mask_sha256": png_sha256,
                "predicted_mask_sha256": png_sha256,
            },
            "assets": {
                "reference_image_url": (
                    f"/api/v1/e1/evaluation/assets/{profile}/{case_id}/reference.png"
                ),
                "inspection_image_url": (
                    f"/api/v1/e1/evaluation/assets/{profile}/{case_id}/inspection.png"
                ),
                "authoritative_mask_url": (
                    f"/api/v1/e1/evaluation/assets/{profile}/{case_id}/authoritative-mask.png"
                ),
                "predicted_mask_url": (
                    f"/api/v1/e1/evaluation/assets/{profile}/{case_id}/predicted-mask.png"
                ),
                "overlay_url": (f"/api/v1/e1/evaluation/assets/{profile}/{case_id}/overlay.png"),
            },
        }
    ]
    document = {
        "schema_version": "1.0.0",
        "result_id": f"e1-{profile}-result-v1",
        "evaluation_run_id": f"e1-{profile}-run-001",
        "generated_at": "2026-07-31T00:00:00Z",
        "duration_ms": 1234,
        "local_absolute_paths": [f"/tmp/e1-{profile}"],
        "evaluation_status": "COMPLETED",
        "profile": profile,
        "protocol": _protocol(),
        "code": {"code_commit_sha": CODE_SHA, "dirty_worktree": False},
        "generator": _generator(),
        "dataset": {
            "dataset_id": f"e1-{profile}",
            "dataset_version": "1.0.0",
            "dataset_manifest_sha256": manifest["manifest_sha256"],
            "case_count": manifest["counts"]["case_count"],
            "inference_case_count": manifest["counts"]["inference_case_count"],
            "trust_case_count": manifest["counts"]["trust_case_count"],
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
        "error_gallery": error_gallery,
        "exclusions": ["Trust-boundary cases are reported separately."],
        "limitations": ["Synthetic evaluation only; not shop-floor validation."],
        "deterministic_projection_sha256": "0" * 64,
        "result_sha256": "0" * 64,
        "verdict": metrics["verdict"],
    }
    return finalize_evaluation_result(document)


def _inventory_payload_sha256(artifacts: list[dict[str, Any]]) -> str:
    projection = {
        "algorithm": "sha256",
        "artifacts": [
            {
                "path": artifact["path"],
                "sha256": artifact["sha256"],
                "byte_size": artifact["byte_size"],
                "media_type": artifact["media_type"],
            }
            for artifact in artifacts
        ],
    }
    return canonical_json_hash(projection)


def _calibration_result(profile: str, manifest: dict[str, Any]) -> dict[str, Any]:
    cases = [
        case
        for case in manifest["cases"]
        if case["split"] == "calibration" and case["group"] != "trust_boundary"
    ]
    gates = _calibration_gates()
    return {
        "schema_version": "1.0.0",
        "calibration_id": f"e1-{profile}-calibration-v1",
        "protocol": _protocol(),
        "profile": profile,
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "evaluation_split": "calibration",
        "threshold_candidate": 0.0025,
        "observation_count": len(cases),
        "case_results": [
            {
                "case_id": case["case_id"],
                "split": "calibration",
                "group": case["group"],
                "expected_outcome": case["expected_outcome"],
                "source_hashes": {
                    **case["source_hashes"],
                    "generator_configuration_sha256": case["generator"][
                        "generator_configuration_sha256"
                    ],
                },
            }
            for case in cases
        ],
        "metrics": {
            "evaluation_split": "calibration",
            "gate_summary": {"passed": 4, "total": 4, "all_passed": True},
            "gates": gates,
        },
    }


def _assert_error_envelope(response: Any, code: str) -> dict[str, Any]:
    payload = response.json()
    assert payload["error"]["code"] == code
    return payload


def _publish_snapshot(
    settings: Settings,
    *,
    profile: str = "mini",
    result_document: dict[str, Any] | None = None,
    validated_result: bool = True,
) -> tuple[Path, dict[str, Any], str]:
    data_root = settings.data_dir
    profile_root = data_root / "e1-evaluation" / profile
    data_root.mkdir(parents=True, exist_ok=True)
    profile_root.mkdir(parents=True, exist_ok=True)
    store = E1ArtifactStore(profile_root, allowed_root=data_root)

    manifest = _manifest(profile)
    full_manifest = _manifest("full")
    calibration = _calibration_result(profile, manifest)
    calibration_record = store.write_json("calibration-result.json", calibration)
    threshold = _threshold_lock(
        profile,
        manifest_sha256=manifest["manifest_sha256"],
        calibration_result_sha256=calibration_record.sha256,
    )
    result = copy.deepcopy(result_document or _result(profile))
    if validated_result:
        result["threshold"] = {
            "lock_id": threshold["lock_id"],
            "threshold_lock_sha256": threshold["threshold_lock_sha256"],
            "lock_status": threshold["lock_status"],
            "locked_image_threshold": threshold["locked_image_threshold"],
            "threshold_source_split": threshold["threshold_source_split"],
        }
        result["reproducibility"]["deterministic_projection_sha256s"] = [
            full_manifest["manifest_sha256"],
            full_manifest["manifest_sha256"],
        ]
        result = finalize_evaluation_result(result)
    gallery_case_id = result["error_gallery"][0]["case_id"]
    asset_payloads = {
        f"assets/{gallery_case_id}/reference.png": PNG_BYTES,
        f"assets/{gallery_case_id}/inspection.png": PNG_BYTES,
        f"assets/{gallery_case_id}/authoritative-mask.png": PNG_BYTES,
        f"assets/{gallery_case_id}/predicted-mask.png": PNG_BYTES,
        f"assets/{gallery_case_id}/overlay.png": _render_overlay(
            PNG_BYTES,
            PNG_BYTES,
            PNG_BYTES,
        ),
    }

    store.write_json("manifest.json", manifest, schema_name="case-manifest")
    store.write_json(
        "repeatability/full-manifest-run-1.json",
        full_manifest,
        schema_name="case-manifest",
    )
    store.write_json(
        "repeatability/full-manifest-run-2.json",
        full_manifest,
        schema_name="case-manifest",
    )
    store.write_json("threshold-lock.json", threshold, schema_name="threshold-lock")
    if validated_result:
        store.write_json("result.json", result, schema_name="evaluation-result")
    else:
        store.write_bytes("result.json", canonical_json_bytes(result))
    for asset_path, payload in asset_payloads.items():
        store.write_bytes(asset_path, payload)
    members = [
        "manifest.json",
        "calibration-result.json",
        "repeatability/full-manifest-run-1.json",
        "repeatability/full-manifest-run-2.json",
        "threshold-lock.json",
        "result.json",
        *asset_payloads,
    ]
    store.write_inventory("inventory.json", members)
    return profile_root, result, gallery_case_id


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture(autouse=True)
def patch_e1_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "manufacturing_vision_studio.e1.artifacts.load_e1_protocol",
        lambda: FAKE_PROTOCOL,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_latest_evaluation_returns_fully_verified_public_result(
    client: TestClient,
    settings: Settings,
) -> None:
    _publish_snapshot(settings)

    response = client.get("/api/v1/e1/evaluation/latest?profile=mini")

    assert response.status_code == 200
    payload = response.json()
    case_id = payload["error_gallery"][0]["case_id"]
    assert payload["profile"] == "mini"
    assert payload["result_sha256"]
    assert "local_absolute_paths" not in payload
    assert payload["error_gallery"][0]["assets"] == {
        "reference_image_url": f"/api/v1/e1/evaluation/assets/mini/{case_id}/reference.png",
        "inspection_image_url": f"/api/v1/e1/evaluation/assets/mini/{case_id}/inspection.png",
        "authoritative_mask_url": (
            f"/api/v1/e1/evaluation/assets/mini/{case_id}/authoritative-mask.png"
        ),
        "predicted_mask_url": f"/api/v1/e1/evaluation/assets/mini/{case_id}/predicted-mask.png",
        "overlay_url": f"/api/v1/e1/evaluation/assets/mini/{case_id}/overlay.png",
    }


def test_latest_evaluation_rejects_malformed_asset_url_without_rewriting_it(
    client: TestClient,
    settings: Settings,
) -> None:
    result = _result("mini")
    malformed = "/api/v1/e1/gallery/not-the-declared-route/reference.png"
    result["error_gallery"][0]["assets"]["reference_image_url"] = malformed
    profile_root, _, _ = _publish_snapshot(settings, result_document=result)

    response = client.get("/api/v1/e1/evaluation/latest?profile=mini")

    assert response.status_code == 422
    _assert_error_envelope(response, "SCHEMA_INVALID")
    stored = E1ArtifactStore(profile_root).read_json("result.json")
    assert stored["error_gallery"][0]["assets"]["reference_image_url"] == malformed


def test_latest_evaluation_rejects_wrong_profile_counts(
    client: TestClient,
    settings: Settings,
) -> None:
    result = _result("mini")
    result["dataset"]["case_count"] = 47
    _publish_snapshot(settings, result_document=result, validated_result=False)

    response = client.get("/api/v1/e1/evaluation/latest?profile=mini")

    assert response.status_code == 422
    _assert_error_envelope(response, "SCHEMA_INVALID")


def test_latest_evaluation_rejects_verified_artifacts_for_another_profile(
    client: TestClient,
    settings: Settings,
) -> None:
    full_root, _, _ = _publish_snapshot(settings, profile="full")
    mini_root = full_root.parent / "mini"
    full_root.rename(mini_root)

    response = client.get("/api/v1/e1/evaluation/latest?profile=mini")

    assert response.status_code == 422
    _assert_error_envelope(response, "SCHEMA_INVALID")


def test_latest_evaluation_rejects_tampered_inventory(
    client: TestClient,
    settings: Settings,
) -> None:
    profile_root, _, _ = _publish_snapshot(settings)
    inventory = json.loads((profile_root / "inventory.json").read_text(encoding="utf-8"))
    inventory["payload_sha256"] = "0" * 64
    (profile_root / "inventory.json").write_bytes(canonical_json_bytes(inventory))

    response = client.get("/api/v1/e1/evaluation/latest?profile=mini")

    assert response.status_code == 422
    _assert_error_envelope(response, "HASH_MISMATCH")


def test_latest_evaluation_rejects_incomplete_but_self_consistent_inventory(
    client: TestClient,
    settings: Settings,
) -> None:
    profile_root, _, _ = _publish_snapshot(settings)
    store = E1ArtifactStore(profile_root, allowed_root=settings.data_dir)
    members = [
        record.path
        for record in store.verify_inventory("inventory.json")
        if record.path != "calibration-result.json"
    ]
    store.write_json("inventory.json", store.build_inventory(members), replace=True)

    response = client.get("/api/v1/e1/evaluation/latest?profile=mini")

    assert response.status_code == 422
    _assert_error_envelope(response, "EVIDENCE_INCOMPLETE")


def test_asset_endpoint_serves_verified_png_with_no_store(
    client: TestClient,
    settings: Settings,
) -> None:
    _, result, case_id = _publish_snapshot(settings)

    response = client.get(f"/api/v1/e1/evaluation/assets/mini/{case_id}/reference.png")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG_BYTES
    assert result["error_gallery"][0]["assets"]["reference_image_url"].endswith("reference.png")


def test_asset_endpoint_rejects_path_attack_and_missing_member(
    client: TestClient,
    settings: Settings,
) -> None:
    _, _, case_id = _publish_snapshot(settings)

    traversal = client.get("/api/v1/e1/evaluation/assets/mini/%2e%2e/reference.png")
    missing = client.get(f"/api/v1/e1/evaluation/assets/mini/{case_id}/missing.png")

    assert traversal.status_code == 422
    _assert_error_envelope(traversal, "UNSAFE_PATH")
    assert missing.status_code == 404
    _assert_error_envelope(missing, "RESOURCE_NOT_FOUND")


def test_asset_endpoint_rejects_inventoried_but_undeclared_png(
    client: TestClient,
    settings: Settings,
) -> None:
    profile_root, _, case_id = _publish_snapshot(settings)
    store = E1ArtifactStore(profile_root, allowed_root=settings.data_dir)
    members = [record.path for record in store.verify_inventory("inventory.json")]
    undeclared = f"assets/{case_id}/undeclared.png"
    store.write_bytes(undeclared, PNG_BYTES)
    store.write_json(
        "inventory.json",
        store.build_inventory([*members, undeclared]),
        replace=True,
    )

    response = client.get(f"/api/v1/e1/evaluation/assets/mini/{case_id}/undeclared.png")

    assert response.status_code == 404
    _assert_error_envelope(response, "RESOURCE_NOT_FOUND")


def test_asset_endpoint_rejects_multiply_linked_declared_png(
    client: TestClient,
    settings: Settings,
) -> None:
    profile_root, _, case_id = _publish_snapshot(settings)
    target = profile_root / "assets" / case_id / "reference.png"
    second_name = profile_root / "hardlink-source.png"
    second_name.write_bytes(PNG_BYTES)
    target.unlink()
    os.link(second_name, target)

    response = client.get(f"/api/v1/e1/evaluation/assets/mini/{case_id}/reference.png")

    assert response.status_code == 422
    _assert_error_envelope(response, "NON_REGULAR_INPUT")


def test_asset_endpoint_rejects_hash_bound_fake_png_bytes(
    client: TestClient,
    settings: Settings,
) -> None:
    profile_root, _, case_id = _publish_snapshot(settings)
    store = E1ArtifactStore(profile_root, allowed_root=settings.data_dir)
    members = [record.path for record in store.verify_inventory("inventory.json")]
    fake_png = b"not actually a PNG"
    asset_path = f"assets/{case_id}/reference.png"
    store.write_bytes(asset_path, fake_png, replace=True)
    result = store.read_json("result.json", schema_name="evaluation-result")
    result["error_gallery"][0]["source_hashes"]["reference_sha256"] = sha256_bytes(fake_png)
    store.write_json(
        "result.json",
        finalize_evaluation_result(result),
        schema_name="evaluation-result",
        replace=True,
    )
    store.write_json("inventory.json", store.build_inventory(members), replace=True)

    response = client.get(f"/api/v1/e1/evaluation/assets/mini/{case_id}/reference.png")

    assert response.status_code == 422
    _assert_error_envelope(response, "IMAGE_DECODE_FAILED")


@pytest.mark.parametrize(
    ("entry_name", "expected_code"),
    [
        ("symlink.png", "SYMLINK_INPUT"),
        ("directory.png", "NON_REGULAR_INPUT"),
    ],
)
def test_asset_endpoint_rejects_symlink_and_nonregular_inventory_members(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
    entry_name: str,
    expected_code: str,
) -> None:
    profile_root, _, case_id = _publish_snapshot(settings)
    asset_dir = profile_root / "assets" / case_id
    target_path = asset_dir / entry_name

    if expected_code == "SYMLINK_INPUT":
        outside = tmp_path / "outside.png"
        outside.write_bytes(PNG_BYTES)
        target_path.symlink_to(outside)
    else:
        target_path.mkdir()

    store = E1ArtifactStore(profile_root, allowed_root=settings.data_dir)
    artifacts = [
        {
            "path": path,
            "sha256": sha256_bytes(store.read_bytes(path)),
            "byte_size": len(store.read_bytes(path)),
            "media_type": "application/json",
        }
        for path in ("manifest.json", "result.json", "threshold-lock.json")
    ]
    artifacts.append(
        {
            "path": f"assets/{case_id}/{entry_name}",
            "sha256": sha256_bytes(PNG_BYTES),
            "byte_size": len(PNG_BYTES),
            "media_type": "image/png",
        }
    )
    artifacts = sorted(artifacts, key=lambda artifact: artifact["path"])
    inventory = {
        "schema_version": "1.0.0",
        "hash_contract": "mvs-canonical-json/v1",
        "artifact_count": len(artifacts),
        "payload_byte_size": sum(artifact["byte_size"] for artifact in artifacts),
        "artifacts": artifacts,
        "payload_sha256": _inventory_payload_sha256(artifacts),
    }
    (profile_root / "inventory.json").write_bytes(canonical_json_bytes(inventory))

    response = client.get(f"/api/v1/e1/evaluation/assets/mini/{case_id}/{entry_name}")

    assert response.status_code == 422
    _assert_error_envelope(response, expected_code)


def test_missing_runtime_is_404_without_creating_e1_runtime_dirs(settings: Settings) -> None:
    app = create_app(settings)
    runtime_root = settings.data_dir / "e1-evaluation"
    assert not runtime_root.exists()
    client = TestClient(app)

    response = client.get("/api/v1/e1/evaluation/latest?profile=full")

    assert response.status_code == 404
    _assert_error_envelope(response, "RESOURCE_NOT_FOUND")
    assert not runtime_root.exists()
