from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from manufacturing_vision_studio.canonical import canonical_json_bytes, canonical_json_hash
from manufacturing_vision_studio.e1.diagnostics_v2 import (
    CandidateEvaluationRecord,
    _restore_exact_frozen_bound,
    build_scale_diagnostic_matrix,
    compare_candidates,
    declared_evaluation_seeds,
    implementation_projection_paths,
    load_candidate_selection,
    run_development_trust_audit,
    run_v0_1_baseline_audit,
    select_candidate,
    verify_dependency_guard,
    verify_determinism_evidence,
    write_candidate_selection,
)
from manufacturing_vision_studio.e1.domain import CadRevision, ViewId
from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol


def test_scale_matrix_covers_revisions_views_and_preregistered_scales() -> None:
    plans = build_scale_diagnostic_matrix(load_e1_v2_protocol())
    assert len(plans) == 108
    assert [plan.seed for plan in plans] == list(range(800000, 800108))
    evaluation_seeds = declared_evaluation_seeds(load_e1_v2_protocol())
    assert not ({plan.seed for plan in plans} & evaluation_seeds)
    primary = [plan for plan in plans if plan.combination == "scale_only"]
    assert {(p.cad_revision, p.view_id, p.scale_delta) for p in primary} == {
        (revision, view, scale)
        for revision in CadRevision
        for view in ViewId
        for scale in (-0.020, -0.015, -0.010, -0.005, 0.005, 0.010, 0.015, 0.020)
    }


def test_combined_diagnostics_are_endpoint_balanced_and_defects_rotate() -> None:
    plans = build_scale_diagnostic_matrix(load_e1_v2_protocol())
    assert Counter(plan.combination for plan in plans) == {
        "scale_only": 48,
        "scale_translation": 12,
        "scale_rotation": 12,
        "scale_exposure": 12,
        "scale_medium_defect": 12,
        "scale_high_defect": 12,
    }
    for combination in (
        "scale_translation",
        "scale_rotation",
        "scale_exposure",
        "scale_medium_defect",
        "scale_high_defect",
    ):
        block = [plan for plan in plans if plan.combination == combination]
        assert {(p.cad_revision, p.view_id, p.scale_delta) for p in block} == {
            (revision, view, scale)
            for revision in CadRevision
            for view in ViewId
            for scale in (-0.02, 0.02)
        }
    for severity in ("MEDIUM", "HIGH"):
        block = [plan for plan in plans if plan.defect_severity == severity]
        assert Counter(plan.defect_type for plan in block) == {
            "blocked_hole": 2,
            "burr": 2,
            "edge_chip": 2,
            "hole_geometry_deviation": 2,
            "scratch": 2,
            "stain": 2,
        }


def _candidate(candidate_id: str, **overrides: object) -> CandidateEvaluationRecord:
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "determinism_verified": True,
        "dependency_guard_passed": True,
        "work_cap_passed": True,
        "development_gates_passed": True,
        "medium_high_defect_recall": 1.0,
        "trust_verified": True,
        "v0_1_regression_verified": True,
        "maximum_diagnostic_truth_recall_drop": 0.0,
        "diagnostic_median_dice_drop": 0.0,
        "development_nuisance_false_positives": 0,
        "medium_high_defect_false_negatives": 0,
        "affected_feature_mapping_errors": 0,
        "positive_case_median_dice": 1.0,
        "median_post_normalization_objective": 0.0,
        "worst_case_candidate_pixels": 1,
    }
    values.update(overrides)
    return CandidateEvaluationRecord(**values)  # type: ignore[arg-type]


def test_selection_rejects_work_cap_or_gate_failure_before_ranking() -> None:
    record = select_candidate(
        [
            _candidate("A", work_cap_passed=False),
            _candidate("B", development_nuisance_false_positives=1),
        ]
    )
    assert record.selected_candidate_id == "B"
    assert record.candidates[0].rejection_reasons == ("WORK_CAP_EXCEEDED",)


def test_selection_tie_prefers_candidate_a_and_runtime_is_not_ranked() -> None:
    record = select_candidate(
        [
            _candidate("B", runtime_p95_ns=1),
            _candidate("A", runtime_p95_ns=10**18),
        ]
    )
    assert record.selected_candidate_id == "A"


def test_implementation_projection_is_sorted_duplicate_free_and_cycle_free() -> None:
    paths = implementation_projection_paths()
    assert paths == tuple(sorted(set(paths)))
    assert "src/manufacturing_vision_studio/e1/policy_v2.py" in paths
    assert "src/manufacturing_vision_studio/e1/model.py" in paths
    assert "src/manufacturing_vision_studio/model.py" in paths
    assert "schemas/e1-candidate-selection.v2.json" in paths
    assert "configs/evaluation/e1-v2-candidate-selection.json" not in paths
    assert not any(path.startswith("tests/") for path in paths)


def test_projection_binds_every_history_integrity_input_and_executable_gate() -> None:
    paths = set(implementation_projection_paths())
    assert {
        "configs/evaluation/e1-v1-history-integrity.json",
        "schemas/e1-case-manifest.v1.json",
        "schemas/e1-evaluation-result.v1.json",
        "schemas/e1-threshold-lock.v1.json",
        "docs/evaluation/results/e1-mini-v0.2.0-hold.json",
        "docs/evaluation/results/e1-full-v0.2.0-hold.json",
        "docs/releases/v0.2.0/E1_HOLD.md",
        "docs/releases/v0.1.0/evidence-bundle.zip",
        "docs/evaluation/results/v0.1.0-synthetic.json",
        "src/manufacturing_vision_studio/e1/baseline.py",
        "src/manufacturing_vision_studio/e1/trust_boundaries.py",
    } <= paths


def test_dependency_guard_fails_when_one_required_binding_is_absent() -> None:
    paths = implementation_projection_paths()
    incomplete = tuple((path, "0" * 64) for path in paths[1:])
    evidence = verify_dependency_guard(incomplete)
    assert evidence["passed"] is False
    assert paths[0] in evidence["missing_paths"]


def test_determinism_requires_two_complete_case_projections() -> None:
    one_run = (({"case_id": "case-001", "result_sha256": "a" * 64},),)
    evidence = verify_determinism_evidence(one_run, expected_case_ids=("case-001",))
    assert evidence == {
        "passed": False,
        "protocol": "two_complete_ordered_result_projections_v2",
        "run_count": 1,
        "expected_case_count": 1,
        "reason": "TWO_COMPLETE_RUNS_REQUIRED",
        "projection_sha256": [],
    }


def test_bound_recovery_requires_flag_and_one_unique_8_decimal_match() -> None:
    lower = 1 / 1.02
    restored, evidence = _restore_exact_frozen_bound(
        0.98039216,
        boundary_flag=True,
        bounds=(lower, 1 / 0.98),
        identifiers=("lower", "upper"),
        representations=("1/1.02", "1/0.98"),
    )
    assert restored == lower
    assert evidence is not None
    assert evidence["bound_identifier"] == "lower"
    unchanged, absent = _restore_exact_frozen_bound(
        0.98039216,
        boundary_flag=False,
        bounds=(lower, 1 / 0.98),
        identifiers=("lower", "upper"),
        representations=("1/1.02", "1/0.98"),
    )
    assert unchanged == 0.98039216
    assert absent is None
    with pytest.raises(ValueError, match="unique frozen bound"):
        _restore_exact_frozen_bound(
            1.0,
            boundary_flag=True,
            bounds=(1.000000001, 1.000000002),
            identifiers=("lower", "upper"),
            representations=("lower", "upper"),
        )


def test_development_trust_audit_runs_real_fail_closed_handlers(tmp_path) -> None:
    generator = E1V2Generator()
    plans = generator.plan_cases(EvaluationScope.DEVELOPMENT)
    report = run_development_trust_audit(plans, tmp_path / "trust")
    assert report["scenario_count"] == 6
    assert report["publication_count"] == 0
    assert report["all_passed"] is True
    assert [item["actual_error_code"] for item in report["results"]] == [
        "REVISION_MISMATCH",
        "SCHEMA_INVALID",
        "SCHEMA_INVALID",
        "MISSING_REFERENCE",
        "IMAGE_DECODE_FAILED",
        "UNSAFE_PATH",
    ]


@pytest.mark.parametrize("variable", ["MVS_DATA_DIR", "MVS_SCHEMA_DIR"])
def test_baseline_audit_rejects_path_overrides(monkeypatch, variable) -> None:
    monkeypatch.setenv(variable, "/tmp/untrusted-audit-override")
    with pytest.raises(ValueError, match="rejects environment overrides"):
        run_v0_1_baseline_audit()


def test_checked_hold_record_contains_fresh_checkout_audit_evidence() -> None:
    record = load_candidate_selection("configs/evaluation/e1-v2-candidate-selection.json")
    evidence = record.audit_evidence
    assert evidence["provenance"]["comparison_rerun"] is False
    assert evidence["provenance"]["original_record_sha256"] == (
        "f2a257a731d991ceba74f791e24a15e983fd806734af2ea973fc5808daab7280"
    )
    assert evidence["provenance"]["repository_snapshot_containing_execution_projection"] == (
        "8d636717a1b04267933b214a3121acfb93182e46"
    )
    assert evidence["provenance"]["candidate_artifact_sha256"] == {
        "A": "ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84",
        "B": "983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029",
    }
    assert len(evidence["comparison_inputs"]["development"]) == 120
    assert len(evidence["comparison_inputs"]["diagnostic"]) == 108
    for candidate_id in ("A", "B"):
        audit = evidence["candidate_evidence"][candidate_id]
        assert audit["benchmark"]["samples"] == 108
        assert audit["operation_counts"]["total_candidate_pixels_evaluated"] > 0
        assert len(audit["diagnostic_geometry"]) == 108
        assert {
            "silhouette_xor_rate_before",
            "silhouette_xor_rate_after",
            "normalized_edge_mae_before",
            "normalized_edge_mae_after",
        } <= set(audit["diagnostic_geometry"][0])
    restored = evidence["candidate_evidence"]["B"]["diagnostic_geometry"][7]
    assert restored["derivation"] == "recorded_transform_with_exact_frozen_bound_restoration"
    assert restored["bound_restorations"] == [
        {
            "serialized_value": 0.98039216,
            "restored_exact_value": 1 / 1.02,
            "restored_exact_representation": "1/1.02",
            "bound_identifier": "correction_scale_bounds.lower",
            "configuration_path": "configs/evaluation/e1-v2.json",
            "configuration_sha256": (
                "1cb3f58c6b743d48aa1f2fd8e294d899dcf3e1a8c9022646d011b8c2b657ae68"
            ),
        }
    ]
    for candidate in record.candidates:
        assert candidate.determinism_verified is False
        assert candidate.dependency_guard_passed is False
        assert candidate.trust_verified is False
        assert candidate.v0_1_regression_verified is False
        assert candidate.rejection_reasons[:3] == (
            "DETERMINISM_NOT_VERIFIED",
            "DEPENDENCY_GUARD_FAILED",
            "V0_1_REGRESSION_NOT_VERIFIED",
        )


def test_selection_loader_recomputes_hash_projection_and_semantics(tmp_path) -> None:
    checked = load_candidate_selection(
        "configs/evaluation/e1-v2-candidate-selection.json"
    )
    path = tmp_path / "selection.json"
    write_candidate_selection(path, checked)
    loaded = load_candidate_selection(path)
    assert loaded == checked
    assert loaded.selected_candidate_id is None
    assert loaded.outcome == "HOLD"
    assert loaded.record_sha256
    assert loaded.implementation_projection_sha256


def test_selection_loader_rejects_runtime_independent_semantic_tampering(tmp_path) -> None:
    import json

    path = tmp_path / "selection.json"
    document = json.loads(Path("configs/evaluation/e1-v2-candidate-selection.json").read_text())
    document["selected_candidate_id"] = "B"
    selfless = {key: value for key, value in document.items() if key != "record_sha256"}
    document["record_sha256"] = canonical_json_hash(selfless)
    path.write_bytes(canonical_json_bytes(document) + b"\n")
    with pytest.raises(ValueError, match="semantic ranking"):
        load_candidate_selection(path)


def test_selection_loader_rejects_embedded_artifact_tampering(tmp_path) -> None:
    import json

    document = json.loads(Path("configs/evaluation/e1-v2-candidate-selection.json").read_text())
    envelope = document["audit_evidence"]["provenance"]["embedded_candidate_artifacts"]["A"]
    payload = envelope["payload_base64"]
    envelope["payload_base64"] = ("A" if payload[0] != "A" else "B") + payload[1:]
    selfless = {key: value for key, value in document.items() if key != "record_sha256"}
    document["record_sha256"] = canonical_json_hash(selfless)
    path = tmp_path / "embedded-tamper.json"
    path.write_bytes(canonical_json_bytes(document) + b"\n")
    with pytest.raises(ValueError, match="compressed binding"):
        load_candidate_selection(path)


def test_selection_loader_recomputes_operation_count_evidence(tmp_path) -> None:
    import json

    document = json.loads(Path("configs/evaluation/e1-v2-candidate-selection.json").read_text())
    counts = document["audit_evidence"]["candidate_evidence"]["A"]["operation_counts"]
    counts["total_candidate_pixels_evaluated"] += 1
    selfless = {key: value for key, value in document.items() if key != "record_sha256"}
    document["record_sha256"] = canonical_json_hash(selfless)
    path = tmp_path / "operation-tamper.json"
    path.write_bytes(canonical_json_bytes(document) + b"\n")
    with pytest.raises(ValueError, match="operation-count"):
        load_candidate_selection(path)


def test_selection_loader_recomputes_current_trust_audit(tmp_path) -> None:
    import json

    document = json.loads(Path("configs/evaluation/e1-v2-candidate-selection.json").read_text())
    trust = document["audit_evidence"]["current_audits"]["trust"]
    trust["results"][0]["actual_error_code"] = "FAKE_CODE"
    selfless = {key: value for key, value in document.items() if key != "record_sha256"}
    document["record_sha256"] = canonical_json_hash(selfless)
    path = tmp_path / "trust-tamper.json"
    path.write_bytes(canonical_json_bytes(document) + b"\n")
    with pytest.raises(ValueError, match="current trust audit changed"):
        load_candidate_selection(path)


def test_selection_loader_recomputes_current_history_audit(tmp_path) -> None:
    import json

    document = json.loads(Path("configs/evaluation/e1-v2-candidate-selection.json").read_text())
    history = document["audit_evidence"]["current_audits"]["history"]
    history["artifact_count"] += 1
    selfless = {key: value for key, value in document.items() if key != "record_sha256"}
    document["record_sha256"] = canonical_json_hash(selfless)
    path = tmp_path / "history-tamper.json"
    path.write_bytes(canonical_json_bytes(document) + b"\n")
    with pytest.raises(ValueError, match="current history audit changed"):
        load_candidate_selection(path)


def test_comparison_plans_only_explicit_development_and_separate_diagnostic(
    monkeypatch, tmp_path
) -> None:
    import manufacturing_vision_studio.e1.diagnostics_v2 as diagnostics

    planned: list[object] = []

    class FakeGenerator:
        def __init__(self, protocol) -> None:
            self.protocol = protocol

        def plan_cases(self, scope):
            planned.append(scope)
            return ("development-case",)

    monkeypatch.setattr(diagnostics, "E1V2Generator", FakeGenerator)
    monkeypatch.setattr(diagnostics, "build_scale_diagnostic_matrix", lambda _protocol: ())
    monkeypatch.setattr(
        diagnostics,
        "run_development_trust_audit",
        lambda *_args: {"all_passed": True, "results": []},
    )
    monkeypatch.setattr(
        diagnostics,
        "run_v0_1_baseline_audit",
        lambda: {"v0_1_regression": True},
    )
    monkeypatch.setattr(diagnostics, "_build_fresh_comparison_audit", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        diagnostics,
        "_evaluate_candidate",
        lambda candidate_id, **_kwargs: _candidate(candidate_id),
    )
    record = compare_candidates(tmp_path, protocol=load_e1_v2_protocol())
    assert [str(item) for item in planned] == ["development"]
    assert record.selected_candidate_id == "A"
    assert (tmp_path / "e1-v2-candidate-selection.json").is_file()
