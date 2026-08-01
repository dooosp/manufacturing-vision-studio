"""Deterministic image-only geometry primitives and Candidate A alignment."""

from __future__ import annotations

import io
import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png

_WIDTH = 512
_HEIGHT = 384
_SCALE_MIN = 1 / 1.02
_SCALE_MAX = 1 / 0.98


class AlignmentStatus(StrEnum):
    APPLIED = "APPLIED"
    IDENTITY = "IDENTITY"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True, slots=True)
class GeometryConfig:
    image_size: tuple[int, int] = (_WIDTH, _HEIGHT)
    foreground_threshold: int = 18
    connectivity: int = 8
    minimum_component_pixels: int = 512
    trim_tail_fraction: float = 0.01
    pca_eigengap_minimum: float = 0.05
    silhouette_weight: float = 0.70
    edge_weight: float = 0.30
    rotation_bounds_degrees: tuple[float, float] = (-1.5, 1.5)
    correction_scale_bounds: tuple[float, float] = (_SCALE_MIN, _SCALE_MAX)
    translation_bound_pixels: int = 12
    minimum_improvement_ratio: float = 0.05
    minimum_confidence_gap: float = 0.01
    candidate_a_rotation_offsets: tuple[float, ...] = (-0.5, 0.0, 0.5)
    candidate_a_scale_offsets: tuple[float, ...] = (-0.004, 0.0, 0.004)
    candidate_a_translation_offsets: tuple[int, ...] = (-2, -1, 0, 1, 2)
    candidate_a_cap: int = 225
    candidate_a_pixel_cap: int = 44_236_800
    downsample_block_size: int = 4
    downsample_majority_pixels: int = 8
    search_size: tuple[int, int] = (128, 96)
    coarse_rotations: tuple[float, ...] = (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5)
    coarse_scales: tuple[float, ...] = (
        _SCALE_MIN,
        0.985,
        0.990,
        0.995,
        1.000,
        1.005,
        1.010,
        1.015,
        _SCALE_MAX,
    )
    coarse_translation_offsets: tuple[int, ...] = (-4, -2, 0, 2, 4)
    coarse_candidate_cap: int = 1_575
    refine_rotation_offsets: tuple[float, ...] = (-0.25, 0.0, 0.25)
    refine_scale_offsets: tuple[float, ...] = (-0.002, 0.0, 0.002)
    refine_translation_offsets: tuple[int, ...] = (-1, 0, 1)
    refine_candidate_cap: int = 81
    candidate_b_pixel_cap: int = 35_278_848


@dataclass(frozen=True, slots=True)
class AlignmentObjective:
    value: float
    silhouette_xor_rate: float
    normalized_edge_mae: float
    foreground_iou: float


@dataclass(frozen=True, slots=True)
class AlignmentCandidate:
    correction_rotation_degrees: float
    correction_scale: float
    correction_dx: float
    correction_dy: float
    objective: AlignmentObjective
    inspection_bytes: bytes
    inspection_sha256: str


@dataclass(frozen=True, slots=True)
class AlignmentTrace:
    pre_normalization_shift_x: float = 0.0
    pre_normalization_shift_y: float = 0.0
    observed_rotation_degrees: float = 0.0
    observed_scale_ratio: float = 1.0
    correction_rotation_degrees: float = 0.0
    correction_scale: float = 1.0
    correction_dx: float = 0.0
    correction_dy: float = 0.0
    post_normalization_shift_x: float = 0.0
    post_normalization_shift_y: float = 0.0
    objective_before: float = 0.0
    objective_after: float = 0.0
    objective_improvement_ratio: float = 0.0
    foreground_iou_before: float = 1.0
    foreground_iou_after: float = 1.0
    confidence_gap: float = 0.0
    at_scale_bound: bool = False
    at_rotation_bound: bool = False
    normalization_status: str = AlignmentStatus.ABSTAIN.value
    status_reason: str = "INSUFFICIENT_FOREGROUND"
    abstention_reason: str | None = "INSUFFICIENT_FOREGROUND"
    candidates_evaluated: int = 0
    coarse_candidates_evaluated: int = 0
    refine_candidates_evaluated: int = 0
    candidate_pixels_evaluated: int = 0
    search_size: tuple[int, int] | None = None

    def as_record(self) -> dict[str, object]:
        return {
            "pre_normalization_shift_x": _rounded(self.pre_normalization_shift_x),
            "pre_normalization_shift_y": _rounded(self.pre_normalization_shift_y),
            "observed_rotation_degrees": _rounded(self.observed_rotation_degrees),
            "observed_scale_ratio": _rounded(self.observed_scale_ratio),
            "correction_rotation_degrees": _rounded(self.correction_rotation_degrees),
            "correction_scale": _rounded(self.correction_scale),
            "correction_dx": _rounded(self.correction_dx),
            "correction_dy": _rounded(self.correction_dy),
            "post_normalization_shift_x": _rounded(self.post_normalization_shift_x),
            "post_normalization_shift_y": _rounded(self.post_normalization_shift_y),
            "objective_before": _rounded(self.objective_before),
            "objective_after": _rounded(self.objective_after),
            "objective_improvement_ratio": _rounded(self.objective_improvement_ratio),
            "foreground_iou_before": _rounded(self.foreground_iou_before),
            "foreground_iou_after": _rounded(self.foreground_iou_after),
            "confidence_gap": _rounded(self.confidence_gap),
            "at_scale_bound": self.at_scale_bound,
            "at_rotation_bound": self.at_rotation_bound,
            "normalization_status": self.normalization_status,
            "status_reason": self.status_reason,
            "abstention_reason": self.abstention_reason,
            "candidates_evaluated": self.candidates_evaluated,
            "coarse_candidates_evaluated": self.coarse_candidates_evaluated,
            "refine_candidates_evaluated": self.refine_candidates_evaluated,
            "candidate_pixels_evaluated": self.candidate_pixels_evaluated,
            "search_size": list(self.search_size) if self.search_size is not None else None,
        }


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    status: AlignmentStatus
    inspection_bytes: bytes
    inspection_sha256: str
    trace: AlignmentTrace
    candidate: AlignmentCandidate | None = None


@dataclass(frozen=True, slots=True)
class _ComponentGeometry:
    silhouette: np.ndarray
    area: int
    min_y: int
    min_x: int
    max_y: int
    max_x: int
    robust_width: int
    robust_height: int
    median_x: float
    median_y: float
    angle_degrees: float
    eigengap_ratio: float


def geometry_config_from_document(document: Mapping[str, Any]) -> GeometryConfig:
    """Parse the frozen geometry section without coupling to protocol internals."""

    raw = document.get("geometry")
    if not isinstance(raw, Mapping):
        raise ValueError("geometry section is required")
    expected = _expected_geometry_document()
    if set(raw) != set(expected):
        raise ValueError("geometry section keys do not match the frozen protocol")
    for key, expected_value in expected.items():
        if raw.get(key) != expected_value:
            raise ValueError(f"geometry.{key} does not match the frozen protocol")
    candidate_a = raw["candidate_a"]
    candidate_b = raw["candidate_b"]
    assert isinstance(candidate_a, Mapping) and isinstance(candidate_b, Mapping)
    return GeometryConfig(
        image_size=tuple(raw["image_size"]),
        rotation_bounds_degrees=tuple(raw["rotation_bounds_degrees"]),
        correction_scale_bounds=tuple(raw["correction_scale_bounds"]),
        candidate_a_rotation_offsets=tuple(candidate_a["rotation_offsets_degrees"]),
        candidate_a_scale_offsets=tuple(candidate_a["scale_offsets"]),
        candidate_a_translation_offsets=tuple(candidate_a["translation_offsets_pixels"]),
        coarse_rotations=tuple(candidate_b["coarse_rotation_degrees"]),
        coarse_scales=tuple(candidate_b["coarse_scales"]),
        coarse_translation_offsets=tuple(candidate_b["coarse_translation_offsets_pixels"]),
        refine_rotation_offsets=tuple(candidate_b["refine_rotation_offsets_degrees"]),
        refine_scale_offsets=tuple(candidate_b["refine_scale_offsets"]),
        refine_translation_offsets=tuple(candidate_b["refine_translation_offsets_pixels"]),
    )


def largest_component_silhouette(
    image: np.ndarray, *, chebyshev_threshold: int = 18
) -> np.ndarray:
    """Extract the deterministically selected 8-connected foreground component."""

    if image.shape != (_HEIGHT, _WIDTH, 3) or image.dtype != np.uint8:
        raise ValueError("geometry image must be a 512x384 uint8 RGB array")
    foreground = _foreground_mask(image, chebyshev_threshold)
    component = _largest_component(foreground)
    return np.zeros(foreground.shape, dtype=np.bool_) if component is None else component[0]


def silhouette_edges(silhouette: np.ndarray) -> np.ndarray:
    if silhouette.ndim != 2 or silhouette.dtype != np.bool_:
        raise ValueError("silhouette must be a two-dimensional boolean array")
    padded = np.pad(silhouette, 1, constant_values=False)
    interior = np.ones(silhouette.shape, dtype=np.bool_)
    for y_offset in range(3):
        for x_offset in range(3):
            if y_offset == 1 and x_offset == 1:
                continue
            interior &= padded[
                y_offset : y_offset + silhouette.shape[0],
                x_offset : x_offset + silhouette.shape[1],
            ]
    return silhouette & ~interior


def alignment_objective(
    reference_silhouette: np.ndarray,
    candidate_silhouette: np.ndarray,
    reference_edges: np.ndarray,
    candidate_edges: np.ndarray,
) -> AlignmentObjective:
    shape = reference_silhouette.shape
    if (
        candidate_silhouette.shape != shape
        or reference_edges.shape != shape
        or candidate_edges.shape != shape
    ):
        raise ValueError("alignment canvases must have identical shapes")
    xor_rate = float(np.count_nonzero(reference_silhouette ^ candidate_silhouette) / np.prod(shape))
    edge_mae = float(np.mean(np.abs(reference_edges.astype(np.int8) - candidate_edges)))
    union = int(np.count_nonzero(reference_silhouette | candidate_silhouette))
    intersection = int(np.count_nonzero(reference_silhouette & candidate_silhouette))
    iou = float(intersection / union) if union else 1.0
    return AlignmentObjective(0.70 * xor_rate + 0.30 * edge_mae, xor_rate, edge_mae, iou)


def apply_correction(
    inspection_bytes: bytes,
    *,
    rotation: float,
    scale: float,
    dx: float,
    dy: float,
) -> bytes:
    """Render an inspection-to-reference correction as canonical RGB PNG bytes."""

    image = _decode_canonical_rgb(inspection_bytes)
    rendered = _render_image(image, rotation, scale, dx, dy, _border_median_rgb(image))
    return encode_png(rendered, mode="RGB")


def align_largest_component(
    reference_bytes: bytes,
    inspection_bytes: bytes,
    config: GeometryConfig,
) -> AlignmentResult:
    """Candidate A: robust component estimate followed by at most 225 refinements."""

    prepared = _prepare(reference_bytes, inspection_bytes, config)
    if isinstance(prepared, AlignmentResult):
        return prepared
    _reference_image, inspection_image, reference_geometry, inspection_geometry, before = prepared
    initial = _component_estimate(reference_geometry, inspection_geometry, config)
    rotation, scale, dx, dy, observed_rotation, observed_scale = initial
    if abs(dx) > config.translation_bound_pixels or abs(dy) > config.translation_bound_pixels:
        return _abstain(
            inspection_bytes,
            "TRANSLATION_OUT_OF_RANGE",
            pre_shift=(dx, dy),
            observed=(observed_rotation, observed_scale),
            before=before,
        )
    if before.value == 0.0:
        return _identity(
            inspection_bytes,
            before,
            pre_shift=(dx, dy),
            observed=(observed_rotation, observed_scale),
        )
    transforms: set[tuple[float, float, float, float]] = set()
    for rotation_offset in config.candidate_a_rotation_offsets:
        candidate_rotation = _clamp(
            rotation + rotation_offset,
            *config.rotation_bounds_degrees,
        )
        for scale_offset in config.candidate_a_scale_offsets:
            candidate_scale = _clamp(scale + scale_offset, *config.correction_scale_bounds)
            for y_offset in config.candidate_a_translation_offsets:
                candidate_dy = dy + y_offset
                if abs(candidate_dy) > config.translation_bound_pixels:
                    continue
                for x_offset in config.candidate_a_translation_offsets:
                    candidate_dx = dx + x_offset
                    if abs(candidate_dx) <= config.translation_bound_pixels:
                        transforms.add(
                            _normalized_transform(
                                candidate_rotation,
                                candidate_scale,
                                candidate_dx,
                                candidate_dy,
                            )
                        )
    candidates = _evaluate_full_candidates(
        transforms,
        inspection_image,
        inspection_geometry.silhouette,
        reference_geometry.silhouette,
        config,
    )
    if len(candidates) > config.candidate_a_cap:
        raise AssertionError("Candidate A exceeded its frozen candidate cap")
    pixels = len(candidates) * _WIDTH * _HEIGHT
    if pixels > config.candidate_a_pixel_cap:
        raise AssertionError("Candidate A exceeded its frozen candidate-pixel cap")
    return _resolve_candidates(
        inspection_bytes,
        candidates,
        before,
        config,
        pre_shift=(dx, dy),
        observed=(observed_rotation, observed_scale),
        counts=(len(candidates), 0, 0, pixels),
        search_size=None,
        reference_geometry=reference_geometry,
    )


def _prepare(
    reference_bytes: bytes,
    inspection_bytes: bytes,
    config: GeometryConfig,
) -> (
    tuple[Image.Image, Image.Image, _ComponentGeometry, _ComponentGeometry, AlignmentObjective]
    | AlignmentResult
):
    if config != GeometryConfig():
        raise ValueError("GeometryConfig must match the frozen v2 protocol")
    try:
        reference_image = _decode_canonical_rgb(reference_bytes)
        inspection_image = _decode_canonical_rgb(inspection_bytes)
        reference_silhouette = largest_component_silhouette(
            np.asarray(reference_image), chebyshev_threshold=config.foreground_threshold
        )
        inspection_silhouette = largest_component_silhouette(
            np.asarray(inspection_image), chebyshev_threshold=config.foreground_threshold
        )
        reference_geometry = _component_geometry(reference_silhouette, config)
        inspection_geometry = _component_geometry(inspection_silhouette, config)
    except (OSError, SyntaxError, ValueError):
        return _abstain(inspection_bytes, "INSUFFICIENT_FOREGROUND")
    if (
        reference_geometry is None
        or inspection_geometry is None
        or reference_geometry.area < config.minimum_component_pixels
        or inspection_geometry.area < config.minimum_component_pixels
    ):
        return _abstain(inspection_bytes, "INSUFFICIENT_FOREGROUND")
    before = alignment_objective(
        reference_silhouette,
        inspection_silhouette,
        silhouette_edges(reference_silhouette),
        silhouette_edges(inspection_silhouette),
    )
    return reference_image, inspection_image, reference_geometry, inspection_geometry, before


def _component_estimate(
    reference: _ComponentGeometry,
    inspection: _ComponentGeometry,
    config: GeometryConfig,
) -> tuple[float, float, float, float, float, float]:
    scale = float(
        np.median(
            np.asarray(
                [
                    reference.robust_width / inspection.robust_width,
                    reference.robust_height / inspection.robust_height,
                ],
                dtype=np.float64,
            )
        )
    )
    observed_scale = float(
        np.median(
            np.asarray(
                [
                    inspection.robust_width / reference.robust_width,
                    inspection.robust_height / reference.robust_height,
                ],
                dtype=np.float64,
            )
        )
    )
    if (
        reference.eigengap_ratio < config.pca_eigengap_minimum
        or inspection.eigengap_ratio < config.pca_eigengap_minimum
    ):
        rotation = 0.0
        observed_rotation = 0.0
    else:
        rotation = _wrap_angle(reference.angle_degrees - inspection.angle_degrees)
        observed_rotation = _wrap_angle(inspection.angle_degrees - reference.angle_degrees)
    transformed_x, transformed_y = _transform_point(
        inspection.median_x,
        inspection.median_y,
        rotation,
        scale,
    )
    dx = reference.median_x - transformed_x
    dy = reference.median_y - transformed_y
    return rotation, scale, dx, dy, observed_rotation, observed_scale


def _evaluate_full_candidates(
    transforms: set[tuple[float, float, float, float]],
    inspection_image: Image.Image,
    inspection_silhouette: np.ndarray,
    reference_silhouette: np.ndarray,
    config: GeometryConfig,
) -> list[AlignmentCandidate]:
    reference_edges = silhouette_edges(reference_silhouette)
    fill = _border_median_rgb(inspection_image)
    seen_hashes: set[str] = set()
    candidates: list[AlignmentCandidate] = []
    ordered = sorted(transforms, key=lambda item: _parameter_tie(*item))
    for rotation, scale, dx, dy in ordered:
        rendered = _render_image(inspection_image, rotation, scale, dx, dy, fill)
        rendered_sha = sha256_bytes(rendered.tobytes())
        if rendered_sha in seen_hashes:
            continue
        seen_hashes.add(rendered_sha)
        candidate_silhouette = _render_silhouette(
            inspection_silhouette, rotation, scale, dx, dy
        )
        objective = alignment_objective(
            reference_silhouette,
            candidate_silhouette,
            reference_edges,
            silhouette_edges(candidate_silhouette),
        )
        # Keep raw pixels during search; canonical PNG encoding is intentionally
        # deferred until the single winning transform is known.
        payload = rendered.tobytes()
        candidates.append(
            AlignmentCandidate(
                rotation,
                scale,
                dx,
                dy,
                objective,
                payload,
                rendered_sha,
            )
        )
    return candidates


def _resolve_candidates(
    original_bytes: bytes,
    candidates: list[AlignmentCandidate],
    before: AlignmentObjective,
    config: GeometryConfig,
    *,
    pre_shift: tuple[float, float],
    observed: tuple[float, float],
    counts: tuple[int, int, int, int],
    search_size: tuple[int, int] | None,
    reference_geometry: _ComponentGeometry,
) -> AlignmentResult:
    if not candidates:
        return _abstain(
            original_bytes,
            "AMBIGUOUS_ALIGNMENT",
            pre_shift=pre_shift,
            observed=observed,
            before=before,
            counts=counts,
            search_size=search_size,
        )
    candidates.sort(key=_candidate_tie)
    best = candidates[0]
    improvement = (before.value - best.objective.value) / max(before.value, 1e-12)
    if improvement < config.minimum_improvement_ratio:
        return _identity(
            original_bytes,
            before,
            pre_shift=pre_shift,
            observed=observed,
            counts=counts,
            search_size=search_size,
        )
    if len(candidates) < 2:
        gap = 0.0
    else:
        second = candidates[1]
        gap = (second.objective.value - best.objective.value) / max(
            second.objective.value, 1e-12
        )
    at_rotation = best.correction_rotation_degrees in config.rotation_bounds_degrees
    at_scale = best.correction_scale in config.correction_scale_bounds
    candidate_array = np.frombuffer(best.inspection_bytes, dtype=np.uint8).reshape(
        config.image_size[1], config.image_size[0], 3
    )
    corrected_geometry = _component_geometry(
        largest_component_silhouette(
            candidate_array, chebyshev_threshold=config.foreground_threshold
        ),
        config,
    )
    post_shift = (
        (0.0, 0.0)
        if corrected_geometry is None
        else (
            reference_geometry.median_x - corrected_geometry.median_x,
            reference_geometry.median_y - corrected_geometry.median_y,
        )
    )
    base_trace = _trace_for_candidate(
        best,
        before,
        improvement,
        gap,
        pre_shift,
        observed,
        counts,
        search_size,
        at_rotation,
        at_scale,
        post_shift,
    )
    if gap < config.minimum_confidence_gap:
        trace = _replace_trace_status(base_trace, AlignmentStatus.ABSTAIN, "AMBIGUOUS_ALIGNMENT")
        return AlignmentResult(
            AlignmentStatus.ABSTAIN,
            original_bytes,
            sha256_bytes(original_bytes),
            trace,
        )
    if at_rotation and at_scale:
        trace = _replace_trace_status(base_trace, AlignmentStatus.ABSTAIN, "BOUNDARY_OPTIMUM")
        return AlignmentResult(
            AlignmentStatus.ABSTAIN,
            original_bytes,
            sha256_bytes(original_bytes),
            trace,
        )
    canonical_payload = encode_png(
        Image.frombytes("RGB", config.image_size, best.inspection_bytes), mode="RGB"
    )
    best = AlignmentCandidate(
        best.correction_rotation_degrees,
        best.correction_scale,
        best.correction_dx,
        best.correction_dy,
        best.objective,
        canonical_payload,
        sha256_bytes(canonical_payload),
    )
    trace = _replace_trace_status(base_trace, AlignmentStatus.APPLIED, "APPLIED_ALIGNMENT")
    return AlignmentResult(
        AlignmentStatus.APPLIED,
        best.inspection_bytes,
        best.inspection_sha256,
        trace,
        best,
    )


def _trace_for_candidate(
    candidate: AlignmentCandidate,
    before: AlignmentObjective,
    improvement: float,
    gap: float,
    pre_shift: tuple[float, float],
    observed: tuple[float, float],
    counts: tuple[int, int, int, int],
    search_size: tuple[int, int] | None,
    at_rotation: bool,
    at_scale: bool,
    post_shift: tuple[float, float],
) -> AlignmentTrace:
    return AlignmentTrace(
        pre_normalization_shift_x=pre_shift[0],
        pre_normalization_shift_y=pre_shift[1],
        observed_rotation_degrees=observed[0],
        observed_scale_ratio=observed[1],
        correction_rotation_degrees=candidate.correction_rotation_degrees,
        correction_scale=candidate.correction_scale,
        correction_dx=candidate.correction_dx,
        correction_dy=candidate.correction_dy,
        post_normalization_shift_x=post_shift[0],
        post_normalization_shift_y=post_shift[1],
        objective_before=before.value,
        objective_after=candidate.objective.value,
        objective_improvement_ratio=improvement,
        foreground_iou_before=before.foreground_iou,
        foreground_iou_after=candidate.objective.foreground_iou,
        confidence_gap=gap,
        at_scale_bound=at_scale,
        at_rotation_bound=at_rotation,
        candidates_evaluated=counts[0],
        coarse_candidates_evaluated=counts[1],
        refine_candidates_evaluated=counts[2],
        candidate_pixels_evaluated=counts[3],
        search_size=search_size,
    )


def _replace_trace_status(
    trace: AlignmentTrace, status: AlignmentStatus, reason: str
) -> AlignmentTrace:
    values = {field: getattr(trace, field) for field in trace.__dataclass_fields__}
    values["normalization_status"] = status.value
    values["status_reason"] = reason
    values["abstention_reason"] = reason if status is AlignmentStatus.ABSTAIN else None
    return AlignmentTrace(**values)


def _identity(
    original_bytes: bytes,
    before: AlignmentObjective,
    *,
    pre_shift: tuple[float, float],
    observed: tuple[float, float],
    counts: tuple[int, int, int, int] = (0, 0, 0, 0),
    search_size: tuple[int, int] | None = None,
) -> AlignmentResult:
    trace = AlignmentTrace(
        pre_normalization_shift_x=pre_shift[0],
        pre_normalization_shift_y=pre_shift[1],
        observed_rotation_degrees=observed[0],
        observed_scale_ratio=observed[1],
        post_normalization_shift_x=pre_shift[0],
        post_normalization_shift_y=pre_shift[1],
        objective_before=before.value,
        objective_after=before.value,
        foreground_iou_before=before.foreground_iou,
        foreground_iou_after=before.foreground_iou,
        normalization_status=AlignmentStatus.IDENTITY.value,
        status_reason="IDENTITY_BASELINE",
        abstention_reason=None,
        candidates_evaluated=counts[0],
        coarse_candidates_evaluated=counts[1],
        refine_candidates_evaluated=counts[2],
        candidate_pixels_evaluated=counts[3],
        search_size=search_size,
    )
    return AlignmentResult(
        AlignmentStatus.IDENTITY,
        original_bytes,
        sha256_bytes(original_bytes),
        trace,
    )


def _abstain(
    original_bytes: bytes,
    reason: str,
    *,
    pre_shift: tuple[float, float] = (0.0, 0.0),
    observed: tuple[float, float] = (0.0, 1.0),
    before: AlignmentObjective | None = None,
    counts: tuple[int, int, int, int] = (0, 0, 0, 0),
    search_size: tuple[int, int] | None = None,
) -> AlignmentResult:
    objective = before.value if before is not None else 0.0
    iou = before.foreground_iou if before is not None else 0.0
    trace = AlignmentTrace(
        pre_normalization_shift_x=pre_shift[0],
        pre_normalization_shift_y=pre_shift[1],
        observed_rotation_degrees=observed[0],
        observed_scale_ratio=observed[1],
        objective_before=objective,
        objective_after=objective,
        foreground_iou_before=iou,
        foreground_iou_after=iou,
        normalization_status=AlignmentStatus.ABSTAIN.value,
        status_reason=reason,
        abstention_reason=reason,
        candidates_evaluated=counts[0],
        coarse_candidates_evaluated=counts[1],
        refine_candidates_evaluated=counts[2],
        candidate_pixels_evaluated=counts[3],
        search_size=search_size,
    )
    return AlignmentResult(
        AlignmentStatus.ABSTAIN,
        original_bytes,
        sha256_bytes(original_bytes),
        trace,
    )


def _decode_canonical_rgb(payload: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if source.format != "PNG" or source.mode != "RGB" or source.size != (_WIDTH, _HEIGHT):
                raise ValueError("geometry input must be a canonical 512x384 RGB PNG")
            image = source.copy()
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError("geometry input must be a canonical 512x384 RGB PNG") from exc
    if encode_png(image, mode="RGB") != payload:
        raise ValueError("geometry input PNG bytes are not canonical")
    return image


def _foreground_mask(image: np.ndarray, threshold: int) -> np.ndarray:
    border = np.concatenate(
        (image[0], image[-1], image[1:-1, 0], image[1:-1, -1]),
        axis=0,
    )
    median = np.median(border.astype(np.float64), axis=0)
    return np.max(np.abs(image.astype(np.float64) - median), axis=2) > threshold


def _largest_component(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    visited = np.zeros(mask.shape, dtype=np.bool_)
    components: list[tuple[tuple[int, int, int, int, int], np.ndarray, np.ndarray]] = []
    height, width = mask.shape
    for start_y, start_x in zip(*np.nonzero(mask), strict=True):
        if visited[start_y, start_x]:
            continue
        queue: deque[tuple[int, int]] = deque([(int(start_y), int(start_x))])
        visited[start_y, start_x] = True
        y_values: list[int] = []
        x_values: list[int] = []
        while queue:
            y, x = queue.popleft()
            y_values.append(y)
            x_values.append(x)
            for next_y in range(max(0, y - 1), min(height, y + 2)):
                for next_x in range(max(0, x - 1), min(width, x + 2)):
                    if mask[next_y, next_x] and not visited[next_y, next_x]:
                        visited[next_y, next_x] = True
                        queue.append((next_y, next_x))
        ys = np.asarray(y_values, dtype=np.int32)
        xs = np.asarray(x_values, dtype=np.int32)
        key = (-len(y_values), int(ys.min()), int(xs.min()), int(ys.max()), int(xs.max()))
        components.append((key, ys, xs))
    if not components:
        return None
    _, ys, xs = min(components, key=lambda item: item[0])
    selected = np.zeros(mask.shape, dtype=np.bool_)
    selected[ys, xs] = True
    return selected, ys, xs


def _component_geometry(
    silhouette: np.ndarray, config: GeometryConfig
) -> _ComponentGeometry | None:
    selected = _largest_component(silhouette)
    if selected is None:
        return None
    mask, ys, xs = selected
    area = len(xs)
    trim = math.floor(config.trim_tail_fraction * area)
    sorted_x = np.sort(xs)
    sorted_y = np.sort(ys)
    retained_x = sorted_x[trim : area - trim] if trim else sorted_x
    retained_y = sorted_y[trim : area - trim] if trim else sorted_y
    robust_width = int(retained_x[-1] - retained_x[0] + 1)
    robust_height = int(retained_y[-1] - retained_y[0] + 1)
    centered_x = xs.astype(np.float64) - float(np.mean(xs))
    centered_y = ys.astype(np.float64) - float(np.mean(ys))
    covariance_xx = float(np.mean(centered_x * centered_x))
    covariance_yy = float(np.mean(centered_y * centered_y))
    covariance_xy = float(np.mean(centered_x * centered_y))
    root = math.hypot(covariance_xx - covariance_yy, 2.0 * covariance_xy)
    major = (covariance_xx + covariance_yy + root) / 2.0
    minor = (covariance_xx + covariance_yy - root) / 2.0
    gap = (major - minor) / max(major, 1.0)
    angle = _wrap_angle(
        math.degrees(0.5 * math.atan2(2 * covariance_xy, covariance_xx - covariance_yy))
    )
    return _ComponentGeometry(
        mask,
        area,
        int(ys.min()),
        int(xs.min()),
        int(ys.max()),
        int(xs.max()),
        robust_width,
        robust_height,
        float(np.median(xs)),
        float(np.median(ys)),
        angle,
        gap,
    )


def _render_image(
    image: Image.Image,
    rotation: float,
    scale: float,
    dx: float,
    dy: float,
    fill: tuple[int, int, int],
) -> Image.Image:
    return image.transform(
        image.size,
        Image.Transform.AFFINE,
        _inverse_affine(image.size, rotation, scale, dx, dy),
        resample=Image.Resampling.NEAREST,
        fillcolor=fill,
    )


def _render_silhouette(
    silhouette: np.ndarray, rotation: float, scale: float, dx: float, dy: float
) -> np.ndarray:
    source = Image.fromarray(np.where(silhouette, 255, 0).astype(np.uint8), mode="L")
    rendered = source.transform(
        source.size,
        Image.Transform.AFFINE,
        _inverse_affine(source.size, rotation, scale, dx, dy),
        resample=Image.Resampling.NEAREST,
        fillcolor=0,
    )
    return np.asarray(rendered, dtype=np.uint8) > 0


def _inverse_affine(
    size: tuple[int, int], rotation: float, scale: float, dx: float, dy: float
) -> tuple[float, float, float, float, float, float]:
    width, height = size
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    radians = math.radians(rotation)
    cosine = math.cos(radians) / scale
    sine = math.sin(radians) / scale
    a = cosine
    b = sine
    c = center_x - cosine * (center_x + dx) - sine * (center_y + dy)
    d = -sine
    e = cosine
    f = center_y + sine * (center_x + dx) - cosine * (center_y + dy)
    return a, b, c, d, e, f


def _transform_point(x: float, y: float, rotation: float, scale: float) -> tuple[float, float]:
    center_x = (_WIDTH - 1) / 2.0
    center_y = (_HEIGHT - 1) / 2.0
    radians = math.radians(rotation)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    relative_x = x - center_x
    relative_y = y - center_y
    return (
        center_x + scale * (cosine * relative_x - sine * relative_y),
        center_y + scale * (sine * relative_x + cosine * relative_y),
    )


def _border_median_rgb(image: Image.Image) -> tuple[int, int, int]:
    pixels = np.asarray(image, dtype=np.uint8)
    border = np.concatenate(
        (pixels[0], pixels[-1], pixels[1:-1, 0], pixels[1:-1, -1]), axis=0
    )
    values = np.median(border, axis=0).astype(np.uint8)
    return int(values[0]), int(values[1]), int(values[2])


def _candidate_tie(candidate: AlignmentCandidate) -> tuple[float, ...]:
    return (
        candidate.objective.value,
        *_parameter_tie(
            candidate.correction_rotation_degrees,
            candidate.correction_scale,
            candidate.correction_dx,
            candidate.correction_dy,
        ),
    )


def _parameter_tie(rotation: float, scale: float, dx: float, dy: float) -> tuple[float, ...]:
    return (abs(rotation), abs(scale - 1), abs(dy) + abs(dx), rotation, scale, dy, dx)


def _normalized_transform(
    rotation: float, scale: float, dx: float, dy: float
) -> tuple[float, float, float, float]:
    return tuple(0.0 if value == 0 else float(value) for value in (rotation, scale, dx, dy))  # type: ignore[return-value]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _wrap_angle(value: float) -> float:
    return (value + 90.0) % 180.0 - 90.0


def _rounded(value: float) -> float:
    return round(value, 8)


def _expected_geometry_document() -> dict[str, object]:
    return {
        "algorithm": "bounded_image_geometry_v2",
        "image_size": [512, 384],
        "foreground_threshold": 18,
        "connectivity": 8,
        "minimum_component_pixels": 512,
        "trim_tail_fraction": 0.01,
        "pca_eigengap_minimum": 0.05,
        "silhouette_weight": 0.70,
        "edge_weight": 0.30,
        "rotation_bounds_degrees": [-1.5, 1.5],
        "correction_scale_bounds": [_SCALE_MIN, _SCALE_MAX],
        "translation_bound_pixels": 12,
        "minimum_improvement_ratio": 0.05,
        "minimum_confidence_gap": 0.01,
        "candidate_a": {
            "rotation_offsets_degrees": [-0.5, 0.0, 0.5],
            "scale_offsets": [-0.004, 0.0, 0.004],
            "translation_offsets_pixels": [-2, -1, 0, 1, 2],
            "candidate_cap": 225,
            "candidate_pixel_cap": 44_236_800,
        },
        "candidate_b": {
            "downsample_block_size": 4,
            "downsample_majority_pixels": 8,
            "search_size": [128, 96],
            "coarse_rotation_degrees": [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5],
            "coarse_scales": [_SCALE_MIN, 0.985, 0.990, 0.995, 1.0, 1.005, 1.01, 1.015, _SCALE_MAX],
            "coarse_translation_offsets_pixels": [-4, -2, 0, 2, 4],
            "coarse_candidate_cap": 1_575,
            "refine_rotation_offsets_degrees": [-0.25, 0.0, 0.25],
            "refine_scale_offsets": [-0.002, 0.0, 0.002],
            "refine_translation_offsets_pixels": [-1, 0, 1],
            "refine_candidate_cap": 81,
            "candidate_pixel_cap": 35_278_848,
        },
    }
