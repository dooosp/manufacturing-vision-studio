from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from manufacturing_vision_studio.e1.metrics import (
    EvaluationChecks,
    EvaluationObservation,
    evaluate,
    pixel_counts,
)

ROOT = Path(__file__).parents[1]


def contracts() -> list[dict[str, object]]:
    config = json.loads((ROOT / "configs/evaluation/e1-v1.json").read_text())
    return config["acceptance_gates"]


def observation(
    case_id: str,
    *,
    expected: str,
    actual: str,
    group: str,
    score: float | None,
    severity: str | None = None,
    defect_type: str | None = None,
    nuisance_types: tuple[str, ...] = (),
    expected_feature: str | None = None,
    predicted_feature: str | None = None,
    truth: int = 0,
    predicted: int = 0,
    intersection: int = 0,
    split: str = "test",
) -> EvaluationObservation:
    return EvaluationObservation(
        case_id=case_id,
        split=split,  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        expected_outcome=expected,  # type: ignore[arg-type]
        actual_outcome=actual,  # type: ignore[arg-type]
        anomaly_score=score,
        severity=severity,
        defect_type=defect_type,
        nuisance_types=nuisance_types,
        cad_revision="rev-A",
        view_id="front",
        truth_positive_pixels=truth,
        predicted_positive_pixels=predicted,
        intersection_pixels=intersection,
        total_pixels=100,
        expected_feature_id=expected_feature,
        predicted_feature_id=predicted_feature,
    )


def test_pixel_counts_requires_same_shape_and_computes_intersection() -> None:
    truth = np.asarray([[0, 255], [255, 0]], dtype=np.uint8)
    predicted = np.asarray([[0, 255], [0, 255]], dtype=np.uint8)

    assert pixel_counts(truth, predicted) == (2, 2, 1, 4)


def test_locked_metrics_and_all_gates_pass_for_exact_predictions() -> None:
    observations: list[EvaluationObservation] = []
    for index in range(4):
        severity = "MEDIUM" if index % 2 == 0 else "HIGH"
        observations.append(
            observation(
                f"positive-{index}",
                expected="ANOMALY",
                actual="ANOMALY",
                group="defect",
                score=0.2 + index / 100,
                severity=severity,
                defect_type="scratch" if index < 2 else "burr",
                expected_feature="top_face" if index < 2 else "top_edge",
                predicted_feature="top_face" if index < 2 else "top_edge",
                truth=20,
                predicted=20,
                intersection=20,
            )
        )
    for index in range(4):
        observations.append(
            observation(
                f"nuisance-{index}",
                expected="NORMAL",
                actual="NORMAL",
                group="nuisance",
                score=0.0001,
                nuisance_types=("translation" if index < 2 else "blur",),
            )
        )
    observations.extend(
        [
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
            EvaluationObservation(
                case_id="trust-hash",
                split="test",
                group="trust_boundary",
                expected_outcome="ABSTAIN",
                actual_outcome="ABSTAIN",
                anomaly_score=None,
                expected_abstention_reason="HASH_MISMATCH",
                abstention_reason="HASH_MISMATCH",
                trust_scenario="hash_mismatch",
            ),
        ]
    )
    checks = EvaluationChecks(
        bundle_attempts=2,
        bundle_successes=2,
        split_hash_overlap=0,
        same_seed_manifest_equivalence=True,
        v0_1_regression=True,
    )

    result = evaluate(observations, checks, contracts(), bootstrap_replicates=100)

    assert result["image_level"]["confusion"] == {
        "true_positive": 4,
        "true_negative": 4,
        "false_positive": 0,
        "false_negative": 0,
        "sample_count": 8,
    }
    assert result["image_level"]["average_precision"]["value"] == 1.0
    assert result["image_level"]["auroc"]["value"] == 1.0
    assert result["pixel_level"]["positive_case_median_dice"]["value"] == 1.0
    assert result["engineering_level"]["affected_feature_mapping_accuracy"]["value"] == 1.0
    assert result["gate_summary"] == {"passed": 10, "total": 10, "all_passed": True}
    assert result["verdict"] == "PASS"


def test_supported_abstentions_count_conservatively_and_hold_gates() -> None:
    observations = [
        observation(
            "positive",
            expected="ANOMALY",
            actual="ABSTAIN",
            group="defect",
            score=None,
            severity="MEDIUM",
            defect_type="scratch",
            expected_feature="top_face",
            truth=20,
        ),
        observation(
            "nuisance",
            expected="NORMAL",
            actual="ABSTAIN",
            group="nuisance",
            score=None,
            nuisance_types=("rotation",),
        ),
    ]
    checks = EvaluationChecks(1, 0, 1, False, False)

    result = evaluate(observations, checks, contracts(), bootstrap_replicates=25)

    assert result["image_level"]["confusion"]["false_negative"] == 1
    assert result["image_level"]["confusion"]["false_positive"] == 1
    assert result["image_level"]["nuisance_only_false_positive_rate"]["value"] == 1.0
    assert result["image_level"]["average_precision"]["value"] is None
    assert result["pixel_level"]["positive_case_median_dice"]["value"] == 0.0
    assert result["verdict"] == "HOLD"
    assert not result["gate_summary"]["all_passed"]


def test_average_precision_is_invariant_to_tied_score_input_order() -> None:
    positive = observation(
        "positive",
        expected="ANOMALY",
        actual="ANOMALY",
        group="defect",
        score=0.5,
        severity="HIGH",
        defect_type="scratch",
        expected_feature="top_face",
        predicted_feature="top_face",
        truth=1,
        predicted=1,
        intersection=1,
    )
    negative = observation(
        "negative",
        expected="NORMAL",
        actual="NORMAL",
        group="clean",
        score=0.5,
    )
    checks = EvaluationChecks(1, 1, 0, True, True)

    first = evaluate([positive, negative], checks, contracts(), bootstrap_replicates=10)
    second = evaluate([negative, positive], checks, contracts(), bootstrap_replicates=10)

    assert first["image_level"]["average_precision"]["value"] == 0.5
    assert second["image_level"]["average_precision"]["value"] == 0.5


def test_calibration_confirmation_can_be_computed_without_test_observations() -> None:
    positive = observation(
        "calibration-positive",
        expected="ANOMALY",
        actual="ANOMALY",
        group="defect",
        score=0.2,
        severity="MEDIUM",
        defect_type="scratch",
        expected_feature="top_face",
        predicted_feature="top_face",
        truth=20,
        predicted=20,
        intersection=20,
        split="calibration",
    )
    negative = observation(
        "calibration-nuisance",
        expected="NORMAL",
        actual="NORMAL",
        group="nuisance",
        score=0.0,
        nuisance_types=("translation",),
        split="calibration",
    )
    checks = EvaluationChecks(1, 1, 0, True, True)
    calibration_gates = contracts()[:4]

    result = evaluate(
        [positive, negative],
        checks,
        calibration_gates,
        evaluation_split="calibration",
        bootstrap_replicates=10,
    )

    assert result["evaluation_split"] == "calibration"
    assert result["image_level"]["confusion"]["sample_count"] == 2
    assert result["gate_summary"] == {"passed": 4, "total": 4, "all_passed": True}
