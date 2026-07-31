"""Fail-closed E1 inference policy bound to the frozen protocol."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical import canonical_json_hash, sha256_bytes
from manufacturing_vision_studio.e1.domain import E1GeneratedCase
from manufacturing_vision_studio.e1.metrics import EvaluationObservation, pixel_counts
from manufacturing_vision_studio.e1.model import (
    filter_structural_residue,
    localized_anomaly_score,
    normalize_supported_geometry,
)
from manufacturing_vision_studio.e1.oracle import validate_generated_case
from manufacturing_vision_studio.e1.protocol import E1Protocol
from manufacturing_vision_studio.errors import MVSError, UnsafeInputError
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.model import DeterministicDifferenceModel, ModelConfig

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
    global_anomaly_score: float | None
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
    normalization: dict[str, object] | None
    mask_postprocessing: dict[str, object] | None
    source_hashes: dict[str, str]

    def as_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "split": self.split,
            "group": self.group,
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "anomaly_score": self.anomaly_score,
            "global_anomaly_score": self.global_anomaly_score,
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
            "normalization": self.normalization,
            "mask_postprocessing": self.mask_postprocessing,
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
        self.evaluation_pipeline = protocol.section("evaluation_pipeline")
        self.evaluation_configuration = self.evaluation_pipeline["configuration"]
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
            normalization = normalize_supported_geometry(
                generated.reference_bytes,
                generated.inspection_bytes,
                rotation_limit_degrees=float(
                    self.evaluation_configuration["normalization"]["rotation_limit_degrees"]
                ),
                scale_delta_limit=float(
                    self.evaluation_configuration["normalization"]["scale_delta_limit"]
                ),
                apply_improvement_ratio=float(
                    self.evaluation_configuration["normalization"][
                        "minimum_foreground_fit_improvement_ratio"
                    ]
                ),
            )
            reference = self.ingestor.ingest_bytes(
                generated.reference_bytes,
                filename=f"{plan.case_id}-reference.png",
                declared_media_type="image/png",
            )
            inspection = self.ingestor.ingest_bytes(
                normalization.inspection_bytes,
                filename=f"{plan.case_id}-inspection.png",
                declared_media_type="image/png",
            )
            result = self.model.inspect(
                reference,
                inspection,
                feature_regions=self.protocol.feature_regions_for_view(plan.view_id),
            )
            postprocessing_contract = self.evaluation_configuration["mask_postprocessing"]
            postprocessing = filter_structural_residue(
                result.mask_bytes,
                reference_bytes=generated.reference_bytes,
                inspection_bytes=normalization.inspection_bytes,
                normalization_applied=normalization.applied,
                long_thin_min_major_px=int(postprocessing_contract["long_thin_min_major_px"]),
                long_thin_max_minor_px=int(postprocessing_contract["long_thin_max_minor_px"]),
                affine_neutral_min_pixels=int(postprocessing_contract["affine_neutral_min_pixels"]),
                affine_neutral_max_abs_luminance_delta=float(
                    postprocessing_contract["affine_neutral_max_abs_luminance_delta"]
                ),
                boundary_horizontal_min_width_px=int(
                    postprocessing_contract["boundary_horizontal_min_width_px"]
                ),
                boundary_horizontal_max_height_px=int(
                    postprocessing_contract["boundary_horizontal_max_height_px"]
                ),
                top_boundary_max_y_px=int(postprocessing_contract["top_boundary_max_y_px"]),
                bottom_boundary_min_y_px=int(postprocessing_contract["bottom_boundary_min_y_px"]),
                dark_fixture_max_luminance_delta=float(
                    postprocessing_contract["dark_fixture_max_luminance_delta"]
                ),
            )
            truth = _mask_array(generated.authoritative_mask_bytes)
            predicted = _mask_array(postprocessing.mask_bytes)
            truth_count, predicted_count, intersection, total = pixel_counts(truth, predicted)
            if truth_count != truth_validation.positive_pixel_count:
                raise UnsafeInputError(
                    "Validated truth count changed before scoring",
                    code="HASH_MISMATCH",
                )
            scoring = self.evaluation_configuration["scoring"]
            anomaly_score = localized_anomaly_score(
                postprocessing.mask_bytes,
                window_size_px=int(scoring["local_window_size_px"]),
                minimum_component_pixels=int(scoring["minimum_connected_component_pixels"]),
            )
            actual = classify_score(anomaly_score, self.image_threshold)
            expected_feature = None if plan.defect is None else plan.defect.target_feature_id
            minimum_feature_pixels = int(
                self.protocol.section("threshold_selection")["feature_mapping_min_mask_pixels"]
            )
            predicted_feature = (
                result.dominant_feature if predicted_count >= minimum_feature_pixels else None
            )
            return E1CaseResult(
                case_id=plan.case_id,
                split=plan.split.value,
                group=plan.group.value,
                expected_outcome=plan.expected_outcome.value,
                actual_outcome=actual,
                anomaly_score=anomaly_score,
                global_anomaly_score=result.anomaly_score,
                abstention_reason=None,
                predicted_mask_bytes=postprocessing.mask_bytes,
                predicted_mask_sha256=postprocessing.mask_sha256,
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
                normalization=normalization.as_record(),
                mask_postprocessing=postprocessing.as_record(),
                source_hashes={
                    "reference_sha256": generated.reference_sha256,
                    "inspection_sha256": generated.inspection_sha256,
                    "authoritative_mask_sha256": generated.authoritative_mask_sha256,
                    "generator_configuration_sha256": (generated.generator_configuration_sha256),
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
                global_anomaly_score=None,
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
                normalization=None,
                mask_postprocessing=None,
                source_hashes={
                    "reference_sha256": generated.reference_sha256,
                    "inspection_sha256": generated.inspection_sha256,
                    "authoritative_mask_sha256": generated.authoritative_mask_sha256,
                    "generator_configuration_sha256": (generated.generator_configuration_sha256),
                },
            )

    def model_record(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.evaluation_pipeline["pipeline_id"],
            "pipeline_version": self.evaluation_pipeline["pipeline_version"],
            "model_id": self.evaluation_pipeline["model_id"],
            "model_version": self.evaluation_pipeline["model_version"],
            "model_artifact_sha256": self.evaluation_pipeline["model_artifact_sha256"],
            "configuration_sha256": self.evaluation_pipeline["configuration_sha256"],
            "locked_image_threshold": self.image_threshold,
            "threshold_source_split": "calibration",
        }

    def _validate_model_binding(self) -> None:
        baseline = self.protocol.section("baseline")
        pipeline = baseline["pipeline"]
        model = baseline["model"]
        base_matches = (
            self.model.pipeline_id == pipeline["pipeline_id"]
            and self.model.pipeline_version == pipeline["pipeline_version"]
            and self.model.model_name == model["model_id"]
            and self.model.model_version == model["model_version"]
            and self.model.config.config_hash == baseline["configuration_sha256"]
        )
        evaluation_hash_matches = (
            canonical_json_hash(self.evaluation_configuration)
            == self.evaluation_pipeline["configuration_sha256"]
        )
        normalization_contract = self.evaluation_configuration["normalization"]
        postprocessing_contract = self.evaluation_configuration["mask_postprocessing"]
        dependencies_forbidden = (
            normalization_contract["prediction_dependency"] == "forbidden"
            and normalization_contract["nuisance_parameter_dependency"] == "forbidden"
            and postprocessing_contract["normalization_metadata_dependency"] == "allowed"
            and postprocessing_contract["long_thin_requires_normalization_applied"] is True
            and postprocessing_contract["truth_dependency"] == "forbidden"
            and postprocessing_contract["expected_feature_dependency"] == "forbidden"
            and postprocessing_contract["nuisance_parameter_dependency"] == "forbidden"
        )
        if not base_matches or not evaluation_hash_matches or not dependencies_forbidden:
            raise UnsafeInputError(
                "Runtime model does not match the frozen E1 baseline",
                code="UNKNOWN_PIPELINE_VERSION",
                details={
                    "base_matches": base_matches,
                    "evaluation_hash_matches": evaluation_hash_matches,
                    "dependencies_forbidden": dependencies_forbidden,
                },
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
