"""Versioned deterministic registration and image-difference model."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from typing import ClassVar, Protocol

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical import canonical_json_hash, sha256_bytes
from manufacturing_vision_studio.errors import UnsafeInputError
from manufacturing_vision_studio.images import IngestedImage

FeatureRegions = dict[str, tuple[float, float, float, float]]

DEFAULT_FEATURE_REGIONS: FeatureRegions = {
    "top_face": (0.10, 0.14, 0.90, 0.86),
    "hole_left": (0.20, 0.32, 0.39, 0.68),
    "hole_right": (0.61, 0.32, 0.80, 0.68),
    "top_edge": (0.10, 0.12, 0.90, 0.25),
    "bottom_edge": (0.10, 0.75, 0.90, 0.88),
}


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """All values affecting an inspection result."""

    registration_max_shift: int = 12
    difference_threshold: int = 32
    registration_sample_stride: int = 4

    def __post_init__(self) -> None:
        if not 0 <= self.registration_max_shift <= 32:
            raise ValueError("registration_max_shift must be between 0 and 32")
        if not 1 <= self.difference_threshold <= 255:
            raise ValueError("difference_threshold must be between 1 and 255")
        if not 1 <= self.registration_sample_stride <= 16:
            raise ValueError("registration_sample_stride must be between 1 and 16")

    @property
    def config_hash(self) -> str:
        return canonical_json_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class Registration:
    dx: int
    dy: int
    mean_absolute_error: float


@dataclass(frozen=True, slots=True)
class FeatureScore:
    feature_id: str
    anomaly_pixels: int
    region_pixels: int
    anomaly_fraction: float


@dataclass(frozen=True, slots=True)
class InspectionResult:
    interface_version: str
    pipeline_id: str
    pipeline_version: str
    model_name: str
    model_version: str
    config_hash: str
    reference_sha256: str
    inspection_sha256: str
    reference_pixel_sha256: str
    inspection_pixel_sha256: str
    anomaly_score: float
    anomaly_pixels: int
    total_pixels: int
    registration: Registration
    mask_bytes: bytes
    mask_sha256: str
    registered_bytes: bytes
    registered_sha256: str
    feature_scores: tuple[FeatureScore, ...]
    dominant_feature: str | None

    def as_record(self) -> dict[str, object]:
        return {
            "interface_version": self.interface_version,
            "pipeline_id": self.pipeline_id,
            "pipeline_version": self.pipeline_version,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "config_hash": self.config_hash,
            "source_hashes": {
                "reference_sha256": self.reference_sha256,
                "inspection_sha256": self.inspection_sha256,
                "reference_pixel_sha256": self.reference_pixel_sha256,
                "inspection_pixel_sha256": self.inspection_pixel_sha256,
            },
            "anomaly_score": self.anomaly_score,
            "anomaly_pixels": self.anomaly_pixels,
            "total_pixels": self.total_pixels,
            "registration": asdict(self.registration),
            "mask_sha256": self.mask_sha256,
            "registered_sha256": self.registered_sha256,
            "feature_scores": [asdict(score) for score in self.feature_scores],
            "dominant_feature": self.dominant_feature,
        }


class VisionModel(Protocol):
    interface_version: str
    pipeline_id: str
    pipeline_version: str
    model_name: str
    model_version: str

    def inspect(
        self,
        reference: IngestedImage,
        inspection: IngestedImage,
        *,
        feature_regions: FeatureRegions | None = None,
    ) -> InspectionResult: ...


class DeterministicDifferenceModel:
    """Transparent baseline model intended only for the deterministic demo."""

    interface_version: ClassVar[str] = "mvs.vision-model/v1"
    pipeline_id: ClassVar[str] = "registered-difference"
    pipeline_version: ClassVar[str] = "1.0.0"
    model_name: ClassVar[str] = "registered-absolute-difference"
    model_version: ClassVar[str] = "1.0.0"

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()

    def inspect(
        self,
        reference: IngestedImage,
        inspection: IngestedImage,
        *,
        feature_regions: FeatureRegions | None = None,
    ) -> InspectionResult:
        if (reference.width, reference.height) != (inspection.width, inspection.height):
            raise UnsafeInputError(
                "Reference and inspection dimensions must match",
                code="IMAGE_DIMENSION_MISMATCH",
                details={
                    "reference": [reference.width, reference.height],
                    "inspection": [inspection.width, inspection.height],
                },
            )

        regions = DEFAULT_FEATURE_REGIONS if feature_regions is None else feature_regions
        _validate_feature_regions(regions)
        reference_array = reference.as_array()
        inspection_array = inspection.as_array()
        dx, dy, registration_error = self._register(reference_array, inspection_array)
        registered = _align_to_reference(reference_array, inspection_array, dx=dx, dy=dy)
        absolute_difference = np.abs(reference_array.astype(np.int16) - registered.astype(np.int16))
        mask = np.max(absolute_difference, axis=2) >= self.config.difference_threshold
        anomaly_pixels = int(np.count_nonzero(mask))
        total_pixels = int(mask.size)
        anomaly_score = round(anomaly_pixels / total_pixels, 8)
        feature_scores = _map_features(mask, regions)
        candidates = [score for score in feature_scores if score.anomaly_pixels > 0]
        dominant = (
            min(
                candidates,
                key=lambda score: (
                    -score.anomaly_fraction,
                    -score.anomaly_pixels,
                    score.feature_id,
                ),
            ).feature_id
            if candidates
            else None
        )

        mask_bytes = _encode_png(np.where(mask, 255, 0).astype(np.uint8), mode="L")
        registered_bytes = _encode_png(registered, mode="RGB")
        return InspectionResult(
            interface_version=self.interface_version,
            pipeline_id=self.pipeline_id,
            pipeline_version=self.pipeline_version,
            model_name=self.model_name,
            model_version=self.model_version,
            config_hash=self.config.config_hash,
            reference_sha256=reference.original_sha256,
            inspection_sha256=inspection.original_sha256,
            reference_pixel_sha256=reference.pixel_sha256,
            inspection_pixel_sha256=inspection.pixel_sha256,
            anomaly_score=anomaly_score,
            anomaly_pixels=anomaly_pixels,
            total_pixels=total_pixels,
            registration=Registration(dx=dx, dy=dy, mean_absolute_error=registration_error),
            mask_bytes=mask_bytes,
            mask_sha256=sha256_bytes(mask_bytes),
            registered_bytes=registered_bytes,
            registered_sha256=sha256_bytes(registered_bytes),
            feature_scores=feature_scores,
            dominant_feature=dominant,
        )

    def _register(
        self,
        reference: np.ndarray,
        inspection: np.ndarray,
    ) -> tuple[int, int, float]:
        reference_gray = np.mean(reference.astype(np.float32), axis=2)
        inspection_gray = np.mean(inspection.astype(np.float32), axis=2)
        height, width = reference_gray.shape
        stride = self.config.registration_sample_stride
        best: tuple[float, int, int, int] | None = None
        max_dx = min(self.config.registration_max_shift, width - 1)
        max_dy = min(self.config.registration_max_shift, height - 1)
        for dy in range(-max_dy, max_dy + 1):
            reference_y0 = max(0, -dy)
            reference_y1 = min(height, height - dy)
            inspection_y0 = reference_y0 + dy
            inspection_y1 = reference_y1 + dy
            for dx in range(
                -max_dx,
                max_dx + 1,
            ):
                reference_x0 = max(0, -dx)
                reference_x1 = min(width, width - dx)
                inspection_x0 = reference_x0 + dx
                inspection_x1 = reference_x1 + dx
                reference_view = reference_gray[
                    reference_y0:reference_y1:stride,
                    reference_x0:reference_x1:stride,
                ]
                inspection_view = inspection_gray[
                    inspection_y0:inspection_y1:stride,
                    inspection_x0:inspection_x1:stride,
                ]
                error = float(np.mean(np.abs(reference_view - inspection_view)))
                candidate = (error, abs(dx) + abs(dy), dy, dx)
                if best is None or candidate < best:
                    best = candidate
        if best is None:  # dimensions are validated, so this is defensive only
            raise UnsafeInputError("Registration could not be computed", code="MODEL_ABSTAINED")
        return best[3], best[2], round(best[0], 8)


def _align_to_reference(
    reference: np.ndarray,
    inspection: np.ndarray,
    *,
    dx: int,
    dy: int,
) -> np.ndarray:
    height, width, _ = reference.shape
    aligned = reference.copy()
    reference_y0 = max(0, -dy)
    reference_y1 = min(height, height - dy)
    inspection_y0 = reference_y0 + dy
    inspection_y1 = reference_y1 + dy
    reference_x0 = max(0, -dx)
    reference_x1 = min(width, width - dx)
    inspection_x0 = reference_x0 + dx
    inspection_x1 = reference_x1 + dx
    aligned[reference_y0:reference_y1, reference_x0:reference_x1] = inspection[
        inspection_y0:inspection_y1,
        inspection_x0:inspection_x1,
    ]
    return aligned


def _validate_feature_regions(regions: FeatureRegions) -> None:
    if not regions:
        raise UnsafeInputError("At least one feature region is required", code="SCHEMA_INVALID")
    for feature_id, bounds in regions.items():
        if not feature_id or len(feature_id) > 80 or len(bounds) != 4:
            raise UnsafeInputError("Feature region is malformed", code="SCHEMA_INVALID")
        x0, y0, x1, y1 = bounds
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise UnsafeInputError("Feature bounds must be normalized", code="SCHEMA_INVALID")


def _map_features(mask: np.ndarray, regions: FeatureRegions) -> tuple[FeatureScore, ...]:
    height, width = mask.shape
    results: list[FeatureScore] = []
    for feature_id in sorted(regions):
        x0, y0, x1, y1 = regions[feature_id]
        left = max(0, min(width - 1, round(x0 * width)))
        right = max(left + 1, min(width, round(x1 * width)))
        top = max(0, min(height - 1, round(y0 * height)))
        bottom = max(top + 1, min(height, round(y1 * height)))
        region = mask[top:bottom, left:right]
        anomaly_pixels = int(np.count_nonzero(region))
        region_pixels = int(region.size)
        results.append(
            FeatureScore(
                feature_id=feature_id,
                anomaly_pixels=anomaly_pixels,
                region_pixels=region_pixels,
                anomaly_fraction=round(anomaly_pixels / region_pixels, 8),
            )
        )
    return tuple(results)


def _encode_png(array: np.ndarray, *, mode: str) -> bytes:
    output = io.BytesIO()
    Image.fromarray(array, mode=mode).save(
        output,
        format="PNG",
        optimize=False,
        compress_level=9,
    )
    return output.getvalue()
