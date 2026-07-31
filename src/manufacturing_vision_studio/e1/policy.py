"""Fail-closed E1 inference policy bound to the frozen protocol."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.e1.domain import E1GeneratedCase
from manufacturing_vision_studio.e1.metrics import EvaluationObservation, pixel_counts
from manufacturing_vision_studio.e1.oracle import validate_generated_case
from manufacturing_vision_studio.e1.protocol import E1Protocol
from manufacturing_vision_studio.errors import MVSError, UnsafeInputError
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.model import DeterministicDifferenceModel, ModelConfig
from manufacturing_vision_studio.registry import MODEL_ARTIFACT_SHA256

ActualOutcome = Literal["NORMAL", "ANOMALY", "ABSTAIN"]


@dataclass(frozen=True, slots=True)
class E1CaseResult:
    """One supported E1 inference result with source and model bindings."""

    case_id: str
    split: str
    group: str
    expected_outcome: str
    actual_outcome: ActualOutcome
    anomaly_score: float | None
    abstention_reason: str | None
    predicted_mask_bytes: bytes | None
    predicted_mask_sha256: str | None
    truth_positive_pixels: int
    predicted_positive_pixels: int
    intersection_pixels: int
    total_pixels: int
    expected_feature_id: str | None
    predicted_feature_id: str | None
    registration: dict[str, int | float] | None
    source_hashes: dict[str, str]

    def as_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "group": self.group,
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "anomaly_score": self.anomaly_score,
            "abstention_reason": self.abstention_reason,
            "predicted_mask_sha256": self.predicted_mask_sha256,
            "pixel_counts": {
                "truth_positive": self.truth_positive_pixels,
                "predicted_positive": self.predicted_positive_pixels,
                "intersection": self.intersection_pixels,
                "total": self.total_pixels,
            },
            "feature_mapping": {
                "expected_feature_id": self.expected_feature_id,
                "predicted_feature_id": self.predicted_feature_id,
            },
            "registration": self.registration,
            "source_hashes": dict(sorted(self.source_hashes.items())),
        }

    def as_observation(self, generated: E1GeneratedCase) -> EvaluationObservation:
        defect = generated.plan.defect
        return EvaluationObservation(
            case_id=self.case_id,
            split=generated.plan.split.value,
            group=generated.plan.group.value,
            expected_outcome=generated.plan.expected_outcome.value,
            actual_outcome=self.actual_outcome,
            anomaly_score=self.anomaly_score,
            defect_type=None if defect is None else defect.defect_type.value,
            severity=None if defect is None else defect.severity.value,
            nuisance_types=tuple(item.nuisance_type.value for item in generated.plan.nuisances),
            cad_revision=generated.plan.cad_revision.value,
            view_id=generated.plan.view_id.value,
            truth_positive_pixels=self.truth_positive_pixels,
            predicted_positive_pixels=self.predicted_positive_pixels,
            intersection_pixels=self.intersection_pixels,
            total_pixels=self.total_pixels,
            expected_feature_id=self.expected_feature_id,
            predicted_feature_id=self.predicted_feature_id,
            part_binding_correct=True,
            revision_binding_correct=True,
            abstention_reason=self.abstention_reason,
            published=False,
        )


class E1InferencePolicy:
    """Run only protocol-approved inputs through the pinned deterministic model."""

    def __init__(
        self,
        protocol: E1Protocol,
        *,
        model: DeterministicDifferenceModel | None = None,
        ingestor: ImageIngestor | None = None,
    ) -> None:
        threshold = protocol.section("threshold_selection")
        self.protocol = protocol
        self.image_threshold = float(threshold["locked_image_threshold"])
        self.model = model or DeterministicDifferenceModel(
            ModelConfig(
                registration_max_shift=int(threshold["registration_max_shift_px"]),
                difference_threshold=int(threshold["pixel_difference_threshold"]),
                registration_sample_stride=int(threshold["registration_sample_stride"]),
            )
        )
        self.ingestor = ingestor or ImageIngestor()
        self._validate_model_binding()

    def inspect(self, generated: E1GeneratedCase) -> E1CaseResult:
        """Validate truth and source bytes before producing a result."""

        plan = generated.plan
        if plan.group.value == "trust_boundary":
            raise UnsafeInputError(
                "Trust-boundary stimuli require the dedicated executor",
                code="NORMALIZATION_NOT_APPROVED",
            )
        try:
            truth_validation = validate_generated_case(generated, self.protocol)
            reference = self.ingestor.ingest_bytes(
                generated.reference_bytes,
                filename=f"{plan.case_id}-reference.png",
                declared_media_type="image/png",
            )
            inspection = self.ingestor.ingest_bytes(
                generated.inspection_bytes,
                filename=f"{plan.case_id}-inspection.png",
                declared_media_type="image/png",
            )
            result = self.model.inspect(
                reference,
                inspection,
                feature_regions=self.protocol.feature_regions_for_view(plan.view_id),
            )
            truth = _mask_array(generated.authoritative_mask_bytes)
            predicted = _mask_array(result.mask_bytes)
            truth_count, predicted_count, intersection, total = pixel_counts(truth, predicted)
            if truth_count != truth_validation.positive_pixel_count:
                raise UnsafeInputError(
                    "Validated truth count changed before scoring",
                    code="HASH_MISMATCH",
                )
            actual = classify_score(result.anomaly_score, self.image_threshold)
            expected_feature = None if plan.defect is None else plan.defect.target_feature_id
            minimum_feature_pixels = int(
                self.protocol.section("threshold_selection")[
                    "feature_mapping_min_mask_pixels"
                ]
            )
            predicted_feature = (
                result.dominant_feature
                if predicted_count >= minimum_feature_pixels
                else None
            )
            return E1CaseResult(
                case_id=plan.case_id,
                split=plan.split.value,
                group=plan.group.value,
                expected_outcome=plan.expected_outcome.value,
                actual_outcome=actual,
                anomaly_score=result.anomaly_score,
                abstention_reason=None,
                predicted_mask_bytes=result.mask_bytes,
                predicted_mask_sha256=result.mask_sha256,
                truth_positive_pixels=truth_count,
                predicted_positive_pixels=predicted_count,
                intersection_pixels=intersection,
                total_pixels=total,
                expected_feature_id=expected_feature,
                predicted_feature_id=predicted_feature,
                registration={
                    "dx": result.registration.dx,
                    "dy": result.registration.dy,
                    "mean_absolute_error": result.registration.mean_absolute_error,
                },
                source_hashes={
                    "reference_sha256": generated.reference_sha256,
                    "inspection_sha256": generated.inspection_sha256,
                    "authoritative_mask_sha256": generated.authoritative_mask_sha256,
                    "generator_configuration_sha256": (
                        generated.generator_configuration_sha256
                    ),
                },
            )
        except MVSError as exc:
            total_pixels = self.protocol.image_size[0] * self.protocol.image_size[1]
            return E1CaseResult(
                case_id=plan.case_id,
                split=plan.split.value,
                group=plan.group.value,
                expected_outcome=plan.expected_outcome.value,
                actual_outcome="ABSTAIN",
                anomaly_score=None,
                abstention_reason=exc.code,
                predicted_mask_bytes=None,
                predicted_mask_sha256=None,
                truth_positive_pixels=0,
                predicted_positive_pixels=0,
                intersection_pixels=0,
                total_pixels=total_pixels,
                expected_feature_id=(
                    None if plan.defect is None else plan.defect.target_feature_id
                ),
                predicted_feature_id=None,
                registration=None,
                source_hashes={
                    "reference_sha256": generated.reference_sha256,
                    "inspection_sha256": generated.inspection_sha256,
                    "authoritative_mask_sha256": generated.authoritative_mask_sha256,
                    "generator_configuration_sha256": (
                        generated.generator_configuration_sha256
                    ),
                },
            )

    def model_record(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.model.pipeline_id,
            "pipeline_version": self.model.pipeline_version,
            "model_id": self.model.model_name,
            "model_version": self.model.model_version,
            "model_artifact_sha256": MODEL_ARTIFACT_SHA256,
            "configuration_sha256": self.model.config.config_hash,
            "locked_image_threshold": self.image_threshold,
            "threshold_source_split": "calibration",
        }

    def _validate_model_binding(self) -> None:
        baseline = self.protocol.section("baseline")
        pipeline = baseline["pipeline"]
        model = baseline["model"]
        observed = self.model_record()
        expected = {
            "pipeline_id": pipeline["pipeline_id"],
            "pipeline_version": pipeline["pipeline_version"],
            "model_id": model["model_id"],
            "model_version": model["model_version"],
            "model_artifact_sha256": model["model_artifact_sha256"],
            "configuration_sha256": baseline["configuration_sha256"],
            "locked_image_threshold": baseline["locked_image_threshold"],
            "threshold_source_split": "calibration",
        }
        if observed != expected:
            raise UnsafeInputError(
                "Runtime model does not match the frozen E1 baseline",
                code="UNKNOWN_PIPELINE_VERSION",
                details={"expected": expected, "observed": observed},
            )


def classify_score(score: float, threshold: float) -> Literal["NORMAL", "ANOMALY"]:
    """The exact threshold is anomalous; this edge is part of the lock contract."""

    if not 0 <= score <= 1 or not 0 <= threshold <= 1:
        raise ValueError("score and threshold must be within [0, 1]")
    return "ANOMALY" if score >= threshold else "NORMAL"


def _mask_array(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        if image.mode != "L":
            raise UnsafeInputError("E1 mask must use L mode", code="MASK_CORRUPT")
        return np.asarray(image, dtype=np.uint8).copy()


def source_binding_sha256(result: E1CaseResult) -> str:
    """Expose a compact source binding for logs without retaining input bytes."""

    return sha256_bytes("\0".join(result.source_hashes.values()).encode())
