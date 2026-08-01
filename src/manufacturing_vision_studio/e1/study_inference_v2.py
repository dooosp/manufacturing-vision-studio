"""Truth-free retained inference composition for the E1 feasibility study."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.e1.domain import CadRevision, ViewId
from manufacturing_vision_studio.e1.feature_mapping import (
    FeatureMappingResult,
    build_ownership_map,
    map_final_mask,
)
from manufacturing_vision_studio.e1.known_transform_v2 import (
    KnownTransformResult,
    KnownTransformTrace,
)
from manufacturing_vision_studio.e1.model import (
    MaskPostprocessing,
    filter_structural_residue,
    localized_anomaly_score,
)
from manufacturing_vision_studio.e1.protocol_v2 import E1V2Protocol
from manufacturing_vision_studio.e1.study_protocol_v2 import StudyProtocolV2
from manufacturing_vision_studio.errors import MVSError
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.model import (
    DeterministicDifferenceModel,
    InspectionResult,
    ModelConfig,
)

_IMAGE_SIZE = (512, 384)
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_STUDY_THRESHOLD = 0.0025


def validate_canonical_rgb_png(
    payload: bytes,
    expected_sha256: str,
    *,
    label: str,
) -> None:
    """Validate one exact byte-canonical study RGB PNG and its source digest."""

    error = f"{label} is not a canonical 512x384 RGB PNG"
    if len(payload) > _MAX_IMAGE_BYTES:
        raise ValueError(error)
    try:
        image = ImageIngestor().ingest_bytes(
            payload,
            filename=f"e1-study-{label}.png",
            declared_media_type="image/png",
        )
    except MVSError as exc:
        raise ValueError(error) from exc
    if (
        image.source_format != "PNG"
        or (image.width, image.height) != _IMAGE_SIZE
        or image.original_bytes != image.canonical_bytes
    ):
        raise ValueError(error)
    if image.original_sha256 != expected_sha256:
        raise ValueError(f"{label} SHA-256 does not match bytes")


@dataclass(frozen=True, slots=True)
class StudyInferenceInput:
    """The complete study inference surface after truth has been discarded."""

    reference_bytes: bytes
    inspection_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    part_id: str
    cad_revision: CadRevision
    view_id: ViewId
    normalized: KnownTransformResult

    def __post_init__(self) -> None:
        if not self.part_id:
            raise ValueError("part_id is required")
        if self.normalized.trace.reference_sha256 != self.reference_sha256:
            raise ValueError("normalizer reference hash does not match input")
        if self.normalized.trace.source_inspection_sha256 != self.inspection_sha256:
            raise ValueError("normalizer source inspection hash does not match input")
        if sha256_bytes(self.normalized.normalized_bytes) != self.normalized.normalized_sha256:
            raise ValueError("normalized output hash does not match bytes")
        if self.normalized.trace.normalized_sha256 != self.normalized.normalized_sha256:
            raise ValueError("normalizer trace normalized hash does not match output")
        validate_canonical_rgb_png(
            self.reference_bytes,
            self.reference_sha256,
            label="reference",
        )
        validate_canonical_rgb_png(
            self.inspection_bytes,
            self.inspection_sha256,
            label="inspection",
        )
        validate_canonical_rgb_png(
            self.normalized.normalized_bytes,
            self.normalized.normalized_sha256,
            label="normalized inspection",
        )


@dataclass(frozen=True, slots=True)
class StudyModelRegistration:
    dx: int
    dy: int
    mean_absolute_error: float

    def as_record(self) -> dict[str, int | float]:
        return {
            "dx": self.dx,
            "dy": self.dy,
            "mean_absolute_error": self.mean_absolute_error,
        }


@dataclass(frozen=True, slots=True)
class StudyInferenceResult:
    actual_outcome: Literal["NORMAL", "ANOMALY"]
    anomaly_score: float
    global_anomaly_score: float
    predicted_mask_bytes: bytes
    predicted_mask_sha256: str
    registered_inspection_sha256: str
    feature_mapping: FeatureMappingResult
    model_registration: StudyModelRegistration
    mask_postprocessing: MaskPostprocessing
    transform_trace: KnownTransformTrace
    source_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_hashes",
            MappingProxyType(dict(sorted(self.source_hashes.items()))),
        )

    def as_record(self) -> dict[str, Any]:
        return _sorted_record(
            {
                "actual_outcome": self.actual_outcome,
                "anomaly_score": self.anomaly_score,
                "feature_mapping": self.feature_mapping.as_record(),
                "global_anomaly_score": self.global_anomaly_score,
                "mask_postprocessing": self.mask_postprocessing.as_record(),
                "model_registration": self.model_registration.as_record(),
                "predicted_mask_sha256": self.predicted_mask_sha256,
                "registered_inspection_sha256": self.registered_inspection_sha256,
                "source_hashes": dict(self.source_hashes),
                "transform_trace": _transform_trace_record(self.transform_trace),
            }
        )


class StudyInferenceAdapter:
    """Compose the retained downstream pipeline after known-transform normalization."""

    def __init__(
        self,
        study_protocol: StudyProtocolV2,
        e1_protocol: E1V2Protocol,
        *,
        model: DeterministicDifferenceModel | None = None,
        ingestor: ImageIngestor | None = None,
    ) -> None:
        self.study_protocol = study_protocol
        self.e1_protocol = e1_protocol
        self.model = model or DeterministicDifferenceModel(ModelConfig())
        self.ingestor = ingestor or ImageIngestor()

    def inspect(self, inference: StudyInferenceInput) -> StudyInferenceResult:
        reference = self.ingestor.ingest_bytes(
            inference.reference_bytes,
            filename="e1-study-reference.png",
            declared_media_type="image/png",
        )
        inspection = self.ingestor.ingest_bytes(
            inference.normalized.normalized_bytes,
            filename="e1-study-inspection.png",
            declared_media_type="image/png",
        )
        model_result = self.model.inspect(reference, inspection)
        postprocessing = filter_structural_residue(
            model_result.mask_bytes,
            reference_bytes=inference.reference_bytes,
            inspection_bytes=model_result.registered_bytes,
            normalization_applied=inference.normalized.trace.applied,
        )
        ownership = build_ownership_map(
            self.e1_protocol.feature_ownership(
                inference.cad_revision,
                inference.view_id,
            ),
            _IMAGE_SIZE,
        )
        mapping = map_final_mask(postprocessing.mask_bytes, ownership)
        score = localized_anomaly_score(postprocessing.mask_bytes)
        return build_study_result(
            inference=inference,
            model_result=model_result,
            postprocessing=postprocessing,
            feature_mapping=mapping,
            actual_outcome=classify_study_score(score, _STUDY_THRESHOLD),
            anomaly_score=score,
        )


def classify_study_score(
    score: float,
    threshold: float,
) -> Literal["NORMAL", "ANOMALY"]:
    if not 0 <= score <= 1 or not 0 <= threshold <= 1:
        raise ValueError("score and threshold must be within [0, 1]")
    return "ANOMALY" if score >= threshold else "NORMAL"


def build_study_result(
    *,
    inference: StudyInferenceInput,
    model_result: InspectionResult,
    postprocessing: MaskPostprocessing,
    feature_mapping: FeatureMappingResult,
    actual_outcome: Literal["NORMAL", "ANOMALY"],
    anomaly_score: float,
) -> StudyInferenceResult:
    registration = StudyModelRegistration(
        dx=model_result.registration.dx,
        dy=model_result.registration.dy,
        mean_absolute_error=model_result.registration.mean_absolute_error,
    )
    return StudyInferenceResult(
        actual_outcome=actual_outcome,
        anomaly_score=anomaly_score,
        global_anomaly_score=model_result.anomaly_score,
        predicted_mask_bytes=postprocessing.mask_bytes,
        predicted_mask_sha256=postprocessing.mask_sha256,
        registered_inspection_sha256=model_result.registered_sha256,
        feature_mapping=feature_mapping,
        model_registration=registration,
        mask_postprocessing=postprocessing,
        transform_trace=inference.normalized.trace,
        source_hashes={
            "inspection_sha256": inference.inspection_sha256,
            "normalized_inspection_sha256": inference.normalized.normalized_sha256,
            "reference_sha256": inference.reference_sha256,
        },
    )


def _transform_trace_record(trace: KnownTransformTrace) -> dict[str, object]:
    return {
        "applied": trace.applied,
        "applied_transform": {
            "rotation_degrees": trace.applied_transform.rotation_degrees,
            "scale_factor": trace.applied_transform.scale_factor,
            "translation_x": trace.applied_transform.translation_x,
            "translation_y": trace.applied_transform.translation_y,
        },
        "coefficients": {
            "a": trace.coefficients.a,
            "b": trace.coefficients.b,
            "c": trace.coefficients.c,
            "d": trace.coefficients.d,
            "e": trace.coefficients.e,
            "f": trace.coefficients.f,
        },
        "correction": {
            "dx": trace.correction.dx,
            "dy": trace.correction.dy,
            "rotation_degrees": trace.correction.rotation_degrees,
            "scale": trace.correction.scale,
        },
        "fill_rgb": trace.fill_rgb,
        "normalized_sha256": trace.normalized_sha256,
        "objective_after": trace.objective_after.as_record(),
        "objective_before": trace.objective_before.as_record(),
        "reference_sha256": trace.reference_sha256,
        "resampling": trace.resampling.value,
        "source_inspection_sha256": trace.source_inspection_sha256,
    }


def _sorted_record(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted_record(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return tuple(_sorted_record(item) for item in value)
    if isinstance(value, list):
        return [_sorted_record(item) for item in value]
    return value
