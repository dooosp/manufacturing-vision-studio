from __future__ import annotations

from manufacturing_vision_studio.e1.metrics_v2 import (
    E1V2EvaluationObservation,
    evaluate_v2_metrics,
)


def _observation(**overrides: object) -> E1V2EvaluationObservation:
    values: dict[str, object] = {
        "case_id": "case",
        "scope": "development",
        "group": "defect",
        "expected_outcome": "ANOMALY",
        "actual_outcome": "ANOMALY",
        "anomaly_score": 0.5,
        "severity": "MEDIUM",
        "truth_positive_pixels": 10,
        "predicted_positive_pixels": 10,
        "intersection_pixels": 10,
        "total_pixels": 100,
        "expected_feature_id": "top_face",
        "predicted_feature_id": "top_face",
    }
    values.update(overrides)
    return E1V2EvaluationObservation(**values)  # type: ignore[arg-type]


def test_null_positive_mapping_stays_in_denominator_without_changing_pixel_math() -> None:
    metrics = evaluate_v2_metrics(
        [
            _observation(
                predicted_feature_id=None,
                predicted_positive_pixels=5,
                intersection_pixels=5,
            )
        ]
    )
    assert metrics.feature_mapping_correct == 0
    assert metrics.feature_mapping_denominator == 1
    assert metrics.positive_case_dice == (2 * 5 / 15,)
    assert metrics.positive_case_iou == (5 / 10,)


def test_supported_nuisance_abstain_is_a_false_positive() -> None:
    metrics = evaluate_v2_metrics(
        [
            _observation(
                group="nuisance",
                expected_outcome="NORMAL",
                actual_outcome="ABSTAIN",
                anomaly_score=None,
                severity=None,
                truth_positive_pixels=0,
                predicted_positive_pixels=0,
                intersection_pixels=0,
                expected_feature_id=None,
                predicted_feature_id=None,
            )
        ]
    )
    assert metrics.nuisance_false_positives == 1
    assert metrics.nuisance_denominator == 1


def test_supported_medium_defect_abstain_is_a_false_negative() -> None:
    metrics = evaluate_v2_metrics(
        [_observation(actual_outcome="ABSTAIN", anomaly_score=None, predicted_feature_id=None)]
    )
    assert metrics.medium_high_defect_false_negatives == 1
    assert metrics.medium_high_defect_denominator == 1
