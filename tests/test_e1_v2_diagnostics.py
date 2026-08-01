from __future__ import annotations

from collections import Counter

import pytest

from manufacturing_vision_studio.e1.diagnostics_v2 import (
    CandidateEvaluationRecord,
    build_scale_diagnostic_matrix,
    compare_candidates,
    finalize_candidate_selection,
    implementation_projection_paths,
    load_candidate_selection,
    select_candidate,
    write_candidate_selection,
)
from manufacturing_vision_studio.e1.domain import CadRevision, ViewId
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol


def test_scale_matrix_covers_revisions_views_and_preregistered_scales() -> None:
    plans = build_scale_diagnostic_matrix(load_e1_v2_protocol())
    assert len(plans) == 108
    assert [plan.seed for plan in plans] == list(range(800000, 800108))
    evaluation_seeds = {
        plan.seed
        for scope in ("development", "smoke", "calibration", "release_test")
        for plan in E1V2Generator().plan_cases(scope)
    }
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
        "deterministic": True,
        "dependency_guard_passed": True,
        "work_cap_passed": True,
        "development_gates_passed": True,
        "medium_high_defect_recall": 1.0,
        "trust_passed": True,
        "v0_1_regression_passed": True,
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


def test_selection_loader_recomputes_hash_projection_and_semantics(tmp_path) -> None:
    finalized = finalize_candidate_selection(
        [_candidate("B", development_nuisance_false_positives=1), _candidate("A")],
        load_e1_v2_protocol(),
    )
    path = tmp_path / "selection.json"
    write_candidate_selection(path, finalized)
    loaded = load_candidate_selection(path)
    assert loaded == finalized
    assert loaded.selected_candidate_id == "A"
    assert loaded.record_sha256
    assert loaded.implementation_projection_sha256


def test_selection_loader_rejects_runtime_independent_semantic_tampering(tmp_path) -> None:
    import json

    finalized = finalize_candidate_selection(
        [_candidate("A"), _candidate("B", development_nuisance_false_positives=1)],
        load_e1_v2_protocol(),
    )
    path = tmp_path / "selection.json"
    write_candidate_selection(path, finalized)
    document = json.loads(path.read_text())
    document["selected_candidate_id"] = "B"
    document["record_sha256"] = "0" * 64
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
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
        "_evaluate_candidate",
        lambda candidate_id, **_kwargs: _candidate(candidate_id),
    )
    record = compare_candidates(tmp_path, protocol=load_e1_v2_protocol())
    assert [str(item) for item in planned] == ["development"]
    assert record.selected_candidate_id == "A"
    assert (tmp_path / "e1-v2-candidate-selection.json").is_file()
