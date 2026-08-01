"""Frozen E1 metric formulas, uncertainty estimates, slices, and release gates."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any, Literal, cast

import numpy as np

Outcome = Literal["NORMAL", "ANOMALY", "ABSTAIN"]
Split = Literal["development", "calibration", "test"]
Group = Literal["clean", "nuisance", "defect", "trust_boundary"]


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    """One deterministic E1 case reduced to metric-relevant facts."""

    case_id: str
    split: Split
    group: Group
    expected_outcome: Outcome
    actual_outcome: Outcome
    anomaly_score: float | None
    defect_type: str | None = None
    severity: str | None = None
    nuisance_types: tuple[str, ...] = ()
    cad_revision: str = ""
    view_id: str = ""
    truth_positive_pixels: int = 0
    predicted_positive_pixels: int = 0
    intersection_pixels: int = 0
    total_pixels: int = 0
    expected_feature_id: str | None = None
    predicted_feature_id: str | None = None
    part_binding_correct: bool = True
    revision_binding_correct: bool = True
    expected_abstention_reason: str | None = None
    abstention_reason: str | None = None
    trust_scenario: str | None = None
    published: bool = False

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id is required")
        if self.group == "defect" and self.expected_outcome != "ANOMALY":
            raise ValueError("defect observations must expect ANOMALY")
        if self.group == "trust_boundary" and self.expected_outcome != "ABSTAIN":
            raise ValueError("trust-boundary observations must expect ABSTAIN")
        if self.anomaly_score is not None and not 0 <= self.anomaly_score <= 1:
            raise ValueError("anomaly_score must be within [0, 1]")
        pixel_counts = (
            self.truth_positive_pixels,
            self.predicted_positive_pixels,
            self.intersection_pixels,
            self.total_pixels,
        )
        if any(value < 0 for value in pixel_counts):
            raise ValueError("pixel counts cannot be negative")
        if self.intersection_pixels > min(
            self.truth_positive_pixels,
            self.predicted_positive_pixels,
        ):
            raise ValueError("intersection cannot exceed either positive mask")
        if max(self.truth_positive_pixels, self.predicted_positive_pixels) > self.total_pixels:
            raise ValueError("positive mask counts cannot exceed total pixels")


@dataclass(frozen=True, slots=True)
class EvaluationChecks:
    """Suite-level checks that are not reducible to one inference observation."""

    bundle_attempts: int
    bundle_successes: int
    split_hash_overlap: int
    same_seed_manifest_equivalence: bool
    v0_1_regression: bool

    def __post_init__(self) -> None:
        if self.bundle_attempts <= 0:
            raise ValueError("bundle_attempts must be positive")
        if not 0 <= self.bundle_successes <= self.bundle_attempts:
            raise ValueError("bundle_successes must be within attempted bundles")
        if self.split_hash_overlap < 0:
            raise ValueError("split_hash_overlap cannot be negative")


def pixel_counts(truth: np.ndarray, predicted: np.ndarray) -> tuple[int, int, int, int]:
    """Return truth-positive, predicted-positive, intersection, and total counts."""

    if truth.shape != predicted.shape or truth.ndim != 2:
        raise ValueError("truth and predicted masks must be same-size 2D arrays")
    truth_mask = truth.astype(bool)
    predicted_mask = predicted.astype(bool)
    return (
        int(np.count_nonzero(truth_mask)),
        int(np.count_nonzero(predicted_mask)),
        int(np.count_nonzero(truth_mask & predicted_mask)),
        int(truth_mask.size),
    )


def evaluate(
    observations: list[EvaluationObservation],
    checks: EvaluationChecks,
    gate_contracts: list[dict[str, Any]],
    *,
    evaluation_split: Split = "test",
    bootstrap_seed: int = 424242,
    bootstrap_replicates: int = 10_000,
) -> dict[str, Any]:
    """Compute the complete preregistered E1 metric and gate projection."""

    if not observations:
        raise ValueError("at least one observation is required")
    case_ids = [item.case_id for item in observations]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")

    test_inference = [
        item
        for item in observations
        if item.split == evaluation_split and item.group != "trust_boundary"
    ]
    test_positive = [item for item in test_inference if item.expected_outcome == "ANOMALY"]
    test_negative = [item for item in test_inference if item.expected_outcome == "NORMAL"]
    test_nuisance = [item for item in test_negative if item.group == "nuisance"]
    trust = [item for item in observations if item.group == "trust_boundary"]

    tp = sum(item.actual_outcome == "ANOMALY" for item in test_positive)
    fn = len(test_positive) - tp
    tn = sum(item.actual_outcome == "NORMAL" for item in test_negative)
    fp = len(test_negative) - tn
    confusion = {
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "sample_count": len(test_inference),
    }

    precision = _proportion_metric(tp, tp + fp)
    recall = _proportion_metric(tp, tp + fn)
    specificity = _proportion_metric(tn, tn + fp)
    f1_value = _f1(precision["value"], recall["value"])
    f1 = _scalar_metric(f1_value, reason="precision_or_recall_undefined")
    nuisance_failures = sum(item.actual_outcome != "NORMAL" for item in test_nuisance)
    nuisance_fpr = _proportion_metric(nuisance_failures, len(test_nuisance))

    scored = [item for item in test_inference if item.anomaly_score is not None]
    labels = np.asarray(
        [1 if item.expected_outcome == "ANOMALY" else 0 for item in scored],
        dtype=np.uint8,
    )
    scores = np.asarray([cast(float, item.anomaly_score) for item in scored], dtype=np.float64)
    average_precision = _ranking_metric(labels, scores, "average_precision")
    auroc = _ranking_metric(labels, scores, "auroc")
    if average_precision["value"] is not None:
        average_precision["confidence_interval"] = _ranking_bootstrap_interval(
            labels,
            scores,
            metric="average_precision",
            seed=bootstrap_seed,
            replicates=bootstrap_replicates,
        )
    if auroc["value"] is not None:
        auroc["confidence_interval"] = _ranking_bootstrap_interval(
            labels,
            scores,
            metric="auroc",
            seed=bootstrap_seed + 1,
            replicates=bootstrap_replicates,
        )

    positive_pixel_records = [_pixel_record(item) for item in test_positive]
    dice_values = [cast(float, record["dice"]) for record in positive_pixel_records]
    iou_values = [cast(float, record["iou"]) for record in positive_pixel_records]
    median_dice = _scalar_metric(median(dice_values) if dice_values else None, "no_positive_cases")
    median_iou = _scalar_metric(median(iou_values) if iou_values else None, "no_positive_cases")
    if dice_values:
        dice_by_defect: dict[str, list[float]] = defaultdict(list)
        for item, value in zip(test_positive, dice_values, strict=True):
            dice_by_defect[item.defect_type or "unknown"].append(value)
        median_dice["confidence_interval"] = _stratified_median_bootstrap_interval(
            dice_by_defect,
            seed=bootstrap_seed + 2,
            replicates=bootstrap_replicates,
        )

    truth_pixels = sum(item.truth_positive_pixels for item in test_positive)
    predicted_pixels = sum(item.predicted_positive_pixels for item in test_positive)
    intersection_pixels = sum(item.intersection_pixels for item in test_positive)
    mask_precision = _proportion_metric(intersection_pixels, predicted_pixels)
    mask_recall = _proportion_metric(intersection_pixels, truth_pixels)
    empty_truth = [item for item in test_inference if item.truth_positive_pixels == 0]
    empty_correct = sum(item.predicted_positive_pixels == 0 for item in empty_truth)
    empty_accuracy = _proportion_metric(empty_correct, len(empty_truth))

    known_feature = [item for item in test_positive if item.expected_feature_id is not None]
    feature_correct = sum(
        item.predicted_feature_id == item.expected_feature_id for item in known_feature
    )
    feature_accuracy = _proportion_metric(feature_correct, len(known_feature))
    part_accuracy = _proportion_metric(
        sum(item.part_binding_correct for item in test_inference),
        len(test_inference),
    )
    revision_accuracy = _proportion_metric(
        sum(item.revision_binding_correct for item in test_inference),
        len(test_inference),
    )
    abstention_correct = sum(
        item.actual_outcome == "ABSTAIN"
        and item.abstention_reason == item.expected_abstention_reason
        and not item.published
        for item in trust
    )
    abstention_accuracy = _proportion_metric(abstention_correct, len(trust))
    revision_publications = sum(
        item.published and item.trust_scenario == "revision_mismatch" for item in trust
    )
    invalid_publications = sum(
        item.published and item.trust_scenario != "revision_mismatch" for item in trust
    )
    bundle_rate = _proportion_metric(checks.bundle_successes, checks.bundle_attempts)

    slices = {
        "recall_by_severity": _recall_slices(test_positive, "severity"),
        "recall_by_defect_type": _recall_slices(test_positive, "defect_type"),
        "nuisance_false_positive_rate": _nuisance_slices(test_nuisance),
        "classification_accuracy_by_revision": _accuracy_slices(test_inference, "cad_revision"),
        "classification_accuracy_by_view": _accuracy_slices(test_inference, "view_id"),
        "trust_boundary_scenario": _trust_slices(trust),
    }
    metric_projection = {
        "image_level": {
            "confusion": confusion,
            "precision": precision,
            "recall": recall,
            "specificity": specificity,
            "f1": f1,
            "average_precision": average_precision,
            "auroc": auroc,
            "score_coverage": {
                "scored": len(scored),
                "total": len(test_inference),
                "excluded": len(test_inference) - len(scored),
            },
            "nuisance_only_false_positive_rate": nuisance_fpr,
        },
        "pixel_level": {
            "positive_case_median_dice": median_dice,
            "positive_case_median_iou": median_iou,
            "mask_precision": mask_precision,
            "mask_recall": mask_recall,
            "empty_mask_accuracy": empty_accuracy,
            "positive_case_distribution": positive_pixel_records,
        },
        "engineering_level": {
            "affected_feature_mapping_accuracy": feature_accuracy,
            "part_binding_accuracy": part_accuracy,
            "revision_binding_accuracy": revision_accuracy,
            "abstention_correctness": abstention_accuracy,
        },
        "trust_boundary": {
            "revision_mismatch_publication_count": revision_publications,
            "corrupted_evidence_publication_count": invalid_publications,
            "bundle_verify_reimport_rate": bundle_rate,
            "dataset_split_hash_overlap": checks.split_hash_overlap,
            "same_seed_manifest_equivalence": checks.same_seed_manifest_equivalence,
            "v0_1_regression": checks.v0_1_regression,
        },
        "slices": slices,
    }
    gates = _evaluate_gates(metric_projection, gate_contracts)
    return {
        "evaluation_split": evaluation_split,
        **metric_projection,
        "gates": gates,
        "gate_summary": {
            "passed": sum(gate["passed"] for gate in gates),
            "total": len(gates),
            "all_passed": bool(gates) and all(gate["passed"] for gate in gates),
        },
        "verdict": "PASS" if gates and all(gate["passed"] for gate in gates) else "HOLD",
    }


def _pixel_record(item: EvaluationObservation) -> dict[str, Any]:
    union = item.truth_positive_pixels + item.predicted_positive_pixels - item.intersection_pixels
    dice_denominator = item.truth_positive_pixels + item.predicted_positive_pixels
    return {
        "case_id": item.case_id,
        "defect_type": item.defect_type,
        "severity": item.severity,
        "iou": item.intersection_pixels / union if union else 1.0,
        "dice": 2 * item.intersection_pixels / dice_denominator if dice_denominator else 1.0,
        "truth_positive_pixels": item.truth_positive_pixels,
        "predicted_positive_pixels": item.predicted_positive_pixels,
        "intersection_pixels": item.intersection_pixels,
    }


def _proportion_metric(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {
            "value": None,
            "reason": "zero_denominator",
            "numerator": numerator,
            "denominator": denominator,
            "confidence_interval": None,
        }
    value = numerator / denominator
    return {
        "value": value,
        "reason": None,
        "numerator": numerator,
        "denominator": denominator,
        "confidence_interval": _wilson_interval(numerator, denominator),
    }


def _scalar_metric(value: float | None, reason: str) -> dict[str, Any]:
    return {"value": value, "reason": None if value is not None else reason}


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _ranking_metric(labels: np.ndarray, scores: np.ndarray, metric: str) -> dict[str, Any]:
    positives = int(np.count_nonzero(labels == 1))
    negatives = int(np.count_nonzero(labels == 0))
    if positives == 0 or negatives == 0:
        return {
            "value": None,
            "reason": "both_classes_required",
            "positive_count": positives,
            "negative_count": negatives,
        }
    value = (
        _average_precision(labels, scores)
        if metric == "average_precision"
        else _auroc(labels, scores)
    )
    return {
        "value": value,
        "reason": None,
        "positive_count": positives,
        "negative_count": negatives,
    }


def _average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(-scores, kind="stable")
    ordered_labels = labels[order]
    ordered_scores = scores[order]
    positive_count = int(np.count_nonzero(ordered_labels == 1))
    if positive_count == 0:
        return 0.0
    true_positives = 0
    observed = 0
    average_precision = 0.0
    start = 0
    while start < ordered_labels.size:
        end = start + 1
        while end < ordered_labels.size and ordered_scores[end] == ordered_scores[start]:
            end += 1
        positives_at_threshold = int(np.count_nonzero(ordered_labels[start:end] == 1))
        true_positives += positives_at_threshold
        observed += end - start
        average_precision += (positives_at_threshold / positive_count) * (true_positives / observed)
        start = end
    return average_precision


def _auroc(labels: np.ndarray, scores: np.ndarray) -> float:
    positive_scores = scores[labels == 1]
    negative_scores = scores[labels == 0]
    comparisons = positive_scores[:, None] - negative_scores[None, :]
    wins = np.count_nonzero(comparisons > 0)
    ties = np.count_nonzero(comparisons == 0)
    return float((wins + 0.5 * ties) / comparisons.size)


def _ranking_bootstrap_interval(
    labels: np.ndarray,
    scores: np.ndarray,
    *,
    metric: str,
    seed: int,
    replicates: int,
) -> list[float]:
    rng = np.random.default_rng(seed)
    positive_scores = scores[labels == 1]
    negative_scores = scores[labels == 0]
    values = np.empty(replicates, dtype=np.float64)
    for index in range(replicates):
        sampled_positive = rng.choice(positive_scores, size=positive_scores.size, replace=True)
        sampled_negative = rng.choice(negative_scores, size=negative_scores.size, replace=True)
        sampled_scores = np.concatenate((sampled_positive, sampled_negative))
        sampled_labels = np.concatenate(
            (
                np.ones(sampled_positive.size, dtype=np.uint8),
                np.zeros(sampled_negative.size, dtype=np.uint8),
            )
        )
        values[index] = (
            _average_precision(sampled_labels, sampled_scores)
            if metric == "average_precision"
            else _auroc(sampled_labels, sampled_scores)
        )
    return [float(value) for value in np.quantile(values, [0.025, 0.975])]


def _stratified_median_bootstrap_interval(
    values_by_stratum: dict[str, list[float]],
    *,
    seed: int,
    replicates: int,
) -> list[float]:
    rng = np.random.default_rng(seed)
    arrays = [
        np.asarray(values, dtype=np.float64) for _, values in sorted(values_by_stratum.items())
    ]
    medians = np.empty(replicates, dtype=np.float64)
    for index in range(replicates):
        sample = np.concatenate(
            [rng.choice(values, size=values.size, replace=True) for values in arrays]
        )
        medians[index] = float(np.median(sample))
    return [float(value) for value in np.quantile(medians, [0.025, 0.975])]


def _recall_slices(
    observations: list[EvaluationObservation],
    attribute: Literal["severity", "defect_type"],
) -> dict[str, Any]:
    grouped: dict[str, list[EvaluationObservation]] = defaultdict(list)
    for item in observations:
        grouped[cast(str | None, getattr(item, attribute)) or "unknown"].append(item)
    return {
        name: _proportion_metric(
            sum(item.actual_outcome == "ANOMALY" for item in items),
            len(items),
        )
        for name, items in sorted(grouped.items())
    }


def _nuisance_slices(observations: list[EvaluationObservation]) -> dict[str, Any]:
    grouped: dict[str, list[EvaluationObservation]] = defaultdict(list)
    for item in observations:
        for nuisance_type in item.nuisance_types or ("unclassified",):
            grouped[nuisance_type].append(item)
    return {
        name: _proportion_metric(
            sum(item.actual_outcome != "NORMAL" for item in items),
            len(items),
        )
        for name, items in sorted(grouped.items())
    }


def _accuracy_slices(
    observations: list[EvaluationObservation],
    attribute: Literal["cad_revision", "view_id"],
) -> dict[str, Any]:
    grouped: dict[str, list[EvaluationObservation]] = defaultdict(list)
    for item in observations:
        grouped[cast(str, getattr(item, attribute)) or "unknown"].append(item)
    return {
        name: _proportion_metric(
            sum(item.actual_outcome == item.expected_outcome for item in items),
            len(items),
        )
        for name, items in sorted(grouped.items())
    }


def _trust_slices(observations: list[EvaluationObservation]) -> dict[str, Any]:
    return {
        item.trust_scenario or item.case_id: {
            "case_id": item.case_id,
            "expected_error_code": item.expected_abstention_reason,
            "observed_error_code": item.abstention_reason,
            "abstained": item.actual_outcome == "ABSTAIN",
            "published": item.published,
            "passed": item.actual_outcome == "ABSTAIN"
            and item.abstention_reason == item.expected_abstention_reason
            and not item.published,
        }
        for item in sorted(observations, key=lambda value: value.trust_scenario or value.case_id)
    }


def _evaluate_gates(
    projection: dict[str, Any],
    contracts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    medium_high = [
        item
        for severity, item in projection["slices"]["recall_by_severity"].items()
        if severity in {"MEDIUM", "HIGH"}
    ]
    medium_high_numerator = sum(item["numerator"] for item in medium_high)
    medium_high_denominator = sum(item["denominator"] for item in medium_high)
    values: dict[str, Any] = {
        "medium_high_defect_recall": (
            medium_high_numerator / medium_high_denominator if medium_high_denominator else None
        ),
        "nuisance_only_false_positive_rate": projection["image_level"][
            "nuisance_only_false_positive_rate"
        ]["value"],
        "positive_case_median_dice": projection["pixel_level"]["positive_case_median_dice"][
            "value"
        ],
        "affected_feature_mapping_accuracy": projection["engineering_level"][
            "affected_feature_mapping_accuracy"
        ]["value"],
        "revision_mismatch_publication_count": projection["trust_boundary"][
            "revision_mismatch_publication_count"
        ],
        "corrupted_evidence_publication_count": projection["trust_boundary"][
            "corrupted_evidence_publication_count"
        ],
        "bundle_verify_reimport_rate": projection["trust_boundary"]["bundle_verify_reimport_rate"][
            "value"
        ],
        "dataset_split_hash_overlap": projection["trust_boundary"]["dataset_split_hash_overlap"],
        "same_seed_manifest_equivalence": projection["trust_boundary"][
            "same_seed_manifest_equivalence"
        ],
        "v0_1_regression": projection["trust_boundary"]["v0_1_regression"],
    }
    results = []
    for contract in contracts:
        gate_id = cast(str, contract["gate_id"])
        observed = values.get(gate_id)
        threshold = contract["threshold"]
        operator = contract["operator"]
        passed = _gate_passes(observed, operator, threshold)
        results.append(
            {
                "gate_id": gate_id,
                "scope": contract["scope"],
                "operator": operator,
                "threshold": threshold,
                "observed": observed,
                "passed": passed,
                "reason": None if observed is not None else "metric_undefined",
            }
        )
    return results


def _gate_passes(observed: Any, operator: str, threshold: Any) -> bool:
    if observed is None:
        return False
    if operator == "gte":
        return bool(observed >= threshold)
    if operator == "lte":
        return bool(observed <= threshold)
    if operator == "eq":
        return bool(observed == threshold)
    if operator == "is_true":
        return observed is True and threshold is True
    raise ValueError(f"unsupported gate operator: {operator}")
