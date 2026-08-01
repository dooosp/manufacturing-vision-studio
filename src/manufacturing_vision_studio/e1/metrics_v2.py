"""E1 v2 observation and metric adapter with explicit denominators."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
from PIL import Image

from manufacturing_vision_studio.e1.domain_v2 import E1V2GeneratedCase, EvaluationScope
from manufacturing_vision_studio.e1.metrics import EvaluationObservation, pixel_counts

if TYPE_CHECKING:
    from manufacturing_vision_studio.e1.policy_v2 import E1V2CaseResult

Outcome = Literal["NORMAL", "ANOMALY", "ABSTAIN"]


@dataclass(frozen=True, slots=True)
class E1V2EvaluationObservation:
    """Metric-only offline projection; it is never accepted by runtime policy."""

    case_id: str
    scope: str
    group: str
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
    abstention_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id is required")
        EvaluationScope(self.scope)
        if self.group == "defect" and self.expected_outcome != "ANOMALY":
            raise ValueError("defect observations must expect ANOMALY")
        if self.anomaly_score is not None and not 0 <= self.anomaly_score <= 1:
            raise ValueError("anomaly_score must be within [0, 1]")
        counts = (
            self.truth_positive_pixels,
            self.predicted_positive_pixels,
            self.intersection_pixels,
            self.total_pixels,
        )
        if any(value < 0 for value in counts):
            raise ValueError("pixel counts cannot be negative")
        if self.intersection_pixels > min(
            self.truth_positive_pixels, self.predicted_positive_pixels
        ):
            raise ValueError("intersection cannot exceed either positive mask")

    def as_v1_observation(self) -> EvaluationObservation:
        """Delegate unchanged v1 mathematical primitives through a v2 scope adapter."""

        split = "test" if self.scope == EvaluationScope.RELEASE_TEST.value else self.scope
        if split == EvaluationScope.SMOKE.value:
            split = "development"
        return EvaluationObservation(
            case_id=self.case_id,
            split=split,  # type: ignore[arg-type]
            group=self.group,  # type: ignore[arg-type]
            expected_outcome=self.expected_outcome,
            actual_outcome=self.actual_outcome,
            anomaly_score=self.anomaly_score,
            defect_type=self.defect_type,
            severity=self.severity,
            nuisance_types=self.nuisance_types,
            cad_revision=self.cad_revision,
            view_id=self.view_id,
            truth_positive_pixels=self.truth_positive_pixels,
            predicted_positive_pixels=self.predicted_positive_pixels,
            intersection_pixels=self.intersection_pixels,
            total_pixels=self.total_pixels,
            expected_feature_id=self.expected_feature_id,
            predicted_feature_id=self.predicted_feature_id,
            abstention_reason=self.abstention_reason,
        )


@dataclass(frozen=True, slots=True)
class E1V2MetricSummary:
    nuisance_false_positives: int
    nuisance_denominator: int
    medium_high_defect_false_negatives: int
    medium_high_defect_denominator: int
    feature_mapping_correct: int
    feature_mapping_denominator: int
    positive_case_dice: tuple[float, ...]
    positive_case_iou: tuple[float, ...]


def evaluate_v2_metrics(
    observations: list[E1V2EvaluationObservation],
) -> E1V2MetricSummary:
    """Reduce v2 observations using explicit, independently computed denominators."""

    nuisance = [
        item
        for item in observations
        if item.group == "nuisance" and item.expected_outcome == "NORMAL"
    ]
    medium_high = [
        item
        for item in observations
        if item.group == "defect" and item.severity in {"MEDIUM", "HIGH"}
    ]
    positive = [item for item in observations if item.expected_outcome == "ANOMALY"]
    known_feature = [item for item in positive if item.expected_feature_id is not None]
    dice: list[float] = []
    iou: list[float] = []
    for item in positive:
        dice_denominator = item.truth_positive_pixels + item.predicted_positive_pixels
        union = (
            item.truth_positive_pixels + item.predicted_positive_pixels - item.intersection_pixels
        )
        dice.append(2 * item.intersection_pixels / dice_denominator if dice_denominator else 1.0)
        iou.append(item.intersection_pixels / union if union else 1.0)
    return E1V2MetricSummary(
        nuisance_false_positives=sum(item.actual_outcome != "NORMAL" for item in nuisance),
        nuisance_denominator=len(nuisance),
        medium_high_defect_false_negatives=sum(
            item.actual_outcome != "ANOMALY" for item in medium_high
        ),
        medium_high_defect_denominator=len(medium_high),
        feature_mapping_correct=sum(
            item.predicted_feature_id == item.expected_feature_id for item in known_feature
        ),
        feature_mapping_denominator=len(known_feature),
        positive_case_dice=tuple(dice),
        positive_case_iou=tuple(iou),
    )


def observation_from_case(
    generated: E1V2GeneratedCase,
    result: E1V2CaseResult,
) -> E1V2EvaluationObservation:
    """Join offline truth to a completed truth-free policy result."""

    render_plan = generated.plan._render_plan
    predicted_bytes = result.predicted_mask_bytes
    truth = _mask_array(generated.authoritative_mask_bytes)
    predicted = np.zeros_like(truth) if predicted_bytes is None else _mask_array(predicted_bytes)
    truth_count, predicted_count, intersection, total = pixel_counts(truth, predicted)
    defect = render_plan.defect
    return E1V2EvaluationObservation(
        case_id=generated.plan.case_id,
        scope=generated.plan.scope.value,
        group=generated.plan.group.value,
        expected_outcome=generated.plan.expected_outcome.value,
        actual_outcome=result.actual_outcome,
        anomaly_score=result.anomaly_score,
        defect_type=None if defect is None else defect.defect_type.value,
        severity=None if defect is None else defect.severity.value,
        nuisance_types=tuple(item.nuisance_type.value for item in render_plan.nuisances),
        cad_revision=render_plan.cad_revision.value,
        view_id=render_plan.view_id.value,
        truth_positive_pixels=truth_count,
        predicted_positive_pixels=predicted_count,
        intersection_pixels=intersection,
        total_pixels=total,
        expected_feature_id=None if defect is None else defect.target_feature_id,
        predicted_feature_id=(
            None if result.feature_mapping is None else result.feature_mapping.predicted_feature_id
        ),
        abstention_reason=result.abstention_reason,
    )


def _mask_array(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8) > 0


# Concise aliases for downstream stage code.
V2EvaluationObservation = E1V2EvaluationObservation
V2MetricSummary = E1V2MetricSummary
