"""Study-owned known-transform normalization and reference-boundary geometry."""

from __future__ import annotations

import io
import math
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png

_IMAGE_SIZE = (512, 384)
_IMAGE_SHAPE = (384, 512)
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_FOREGROUND_THRESHOLD = 18
_BOUNDARY_RADIUS = 3


class ResamplingMode(StrEnum):
    NEAREST = "NEAREST"
    BILINEAR = "BILINEAR"
    BICUBIC = "BICUBIC"


@dataclass(frozen=True, slots=True)
class AppliedAffineTransform:
    scale_factor: float
    rotation_degrees: float
    translation_x: float
    translation_y: float


@dataclass(frozen=True, slots=True)
class CorrectionAffineTransform:
    scale: float
    rotation_degrees: float
    dx: float
    dy: float


@dataclass(frozen=True, slots=True)
class AffineCoefficients:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return self.a, self.b, self.c, self.d, self.e, self.f


@dataclass(frozen=True, slots=True)
class StudyAlignmentObjective:
    value: float
    silhouette_xor_rate: float
    normalized_edge_mae: float
    foreground_iou: float

    def as_record(self) -> dict[str, float]:
        return {
            "value": self.value,
            "silhouette_xor_rate": self.silhouette_xor_rate,
            "normalized_edge_mae": self.normalized_edge_mae,
            "foreground_iou": self.foreground_iou,
        }


@dataclass(frozen=True, slots=True)
class ReferenceBoundaryBand:
    radius: int
    foreground_positive_pixels: int
    boundary_positive_pixels: int
    band_positive_pixels: int
    band_mask_bytes: bytes
    band_mask_sha256: str


@dataclass(frozen=True, slots=True)
class KnownTransformTrace:
    applied_transform: AppliedAffineTransform
    correction: CorrectionAffineTransform
    coefficients: AffineCoefficients
    fill_rgb: tuple[int, int, int]
    resampling: ResamplingMode
    reference_sha256: str
    source_inspection_sha256: str
    normalized_sha256: str
    applied: bool
    objective_before: StudyAlignmentObjective
    objective_after: StudyAlignmentObjective


@dataclass(frozen=True, slots=True)
class KnownTransformResult:
    normalized_bytes: bytes
    normalized_sha256: str
    trace: KnownTransformTrace


def derive_correction(applied: AppliedAffineTransform) -> CorrectionAffineTransform:
    if not math.isfinite(applied.scale_factor) or applied.scale_factor <= 0:
        raise ValueError("scale_factor must be finite and positive")
    angle = math.radians(-applied.rotation_degrees)
    scale = 1.0 / applied.scale_factor
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    dx = -scale * (cos_angle * applied.translation_x - sin_angle * applied.translation_y)
    dy = -scale * (sin_angle * applied.translation_x + cos_angle * applied.translation_y)
    return CorrectionAffineTransform(
        scale=scale,
        rotation_degrees=-applied.rotation_degrees,
        dx=dx,
        dy=dy,
    )


def pillow_output_to_input_coefficients(
    image_size: tuple[int, int], correction: CorrectionAffineTransform
) -> AffineCoefficients:
    center_x = (image_size[0] - 1) / 2.0
    center_y = (image_size[1] - 1) / 2.0
    radians = math.radians(correction.rotation_degrees)
    cosine = math.cos(radians) / correction.scale
    sine = math.sin(radians) / correction.scale
    return AffineCoefficients(
        a=cosine,
        b=sine,
        c=center_x - cosine * (center_x + correction.dx) - sine * (center_y + correction.dy),
        d=-sine,
        e=cosine,
        f=center_y + sine * (center_x + correction.dx) - cosine * (center_y + correction.dy),
    )


def normalize_known_transform(
    reference_bytes: bytes,
    inspection_bytes: bytes,
    *,
    reference_sha256: str,
    inspection_sha256: str,
    applied_transform: AppliedAffineTransform,
    resampling: ResamplingMode,
) -> KnownTransformResult:
    _decode_canonical_rgb(reference_bytes)
    inspection = _decode_canonical_rgb(inspection_bytes)
    correction = derive_correction(applied_transform)
    coefficients = pillow_output_to_input_coefficients(inspection.size, correction)
    fill_rgb = _border_median_rgb(np.asarray(inspection, dtype=np.uint8))
    rendered = inspection.transform(
        inspection.size,
        Image.Transform.AFFINE,
        coefficients.as_tuple(),
        resample=_pillow_resampling(resampling),
        fillcolor=fill_rgb,
    )
    normalized_bytes = encode_png(rendered, mode="RGB")
    normalized_sha256 = sha256_bytes(normalized_bytes)
    objective_before = measure_alignment(reference_bytes, inspection_bytes)
    objective_after = measure_alignment(reference_bytes, normalized_bytes)
    applied = applied_transform != AppliedAffineTransform(1.0, 0.0, 0.0, 0.0)
    trace = KnownTransformTrace(
        applied_transform=applied_transform,
        correction=correction,
        coefficients=coefficients,
        fill_rgb=fill_rgb,
        resampling=resampling,
        reference_sha256=reference_sha256,
        source_inspection_sha256=inspection_sha256,
        normalized_sha256=normalized_sha256,
        applied=applied,
        objective_before=objective_before,
        objective_after=objective_after,
    )
    return KnownTransformResult(normalized_bytes, normalized_sha256, trace)


def reference_boundary_band(reference_bytes: bytes) -> ReferenceBoundaryBand:
    image = _decode_canonical_rgb(reference_bytes)
    pixels = np.asarray(image, dtype=np.uint8)
    foreground = _boundary_foreground_mask(pixels)
    component = _largest_component(foreground)
    if component is None:
        raise ValueError("reference image has no foreground component")
    boundary = _silhouette_edges(component)
    band = _chebyshev_dilate(boundary, radius=_BOUNDARY_RADIUS)
    band_mask_bytes = band.tobytes(order="C")
    return ReferenceBoundaryBand(
        radius=_BOUNDARY_RADIUS,
        foreground_positive_pixels=int(np.count_nonzero(component)),
        boundary_positive_pixels=int(np.count_nonzero(boundary)),
        band_positive_pixels=int(np.count_nonzero(band)),
        band_mask_bytes=band_mask_bytes,
        band_mask_sha256=sha256_bytes(band_mask_bytes),
    )


def measure_alignment(reference_bytes: bytes, inspection_bytes: bytes) -> StudyAlignmentObjective:
    reference = np.asarray(_decode_canonical_rgb(reference_bytes), dtype=np.uint8)
    inspection = np.asarray(_decode_canonical_rgb(inspection_bytes), dtype=np.uint8)
    reference_silhouette = _largest_component(_objective_foreground_mask(reference))
    inspection_silhouette = _largest_component(_objective_foreground_mask(inspection))
    if reference_silhouette is None:
        reference_silhouette = np.zeros(_IMAGE_SHAPE, dtype=np.bool_)
    if inspection_silhouette is None:
        inspection_silhouette = np.zeros(_IMAGE_SHAPE, dtype=np.bool_)
    reference_edges = _silhouette_edges(reference_silhouette)
    inspection_edges = _silhouette_edges(inspection_silhouette)
    xor_rate = float(
        np.count_nonzero(reference_silhouette ^ inspection_silhouette)
        / np.prod(reference_silhouette.shape)
    )
    edge_mae = float(
        np.mean(np.abs(reference_edges.astype(np.int8) - inspection_edges))
    )
    union = int(np.count_nonzero(reference_silhouette | inspection_silhouette))
    intersection = int(np.count_nonzero(reference_silhouette & inspection_silhouette))
    foreground_iou = float(intersection / union) if union else 1.0
    return StudyAlignmentObjective(
        value=0.70 * xor_rate + 0.30 * edge_mae,
        silhouette_xor_rate=xor_rate,
        normalized_edge_mae=edge_mae,
        foreground_iou=foreground_iou,
    )


def _decode_canonical_rgb(payload: bytes) -> Image.Image:
    error = "image must be a maximum 8 MiB canonical one-frame 512x384 RGB PNG"
    if len(payload) > _MAX_IMAGE_BYTES:
        raise ValueError(error)
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if (
                source.format != "PNG"
                or source.mode != "RGB"
                or source.size != _IMAGE_SIZE
                or getattr(source, "n_frames", 1) != 1
                or source.info
            ):
                raise ValueError(error)
            source.load()
            image = source.copy()
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(error) from exc
    if encode_png(image, mode="RGB") != payload:
        raise ValueError(error)
    return image


def _pillow_resampling(resampling: ResamplingMode) -> Image.Resampling:
    return {
        ResamplingMode.NEAREST: Image.Resampling.NEAREST,
        ResamplingMode.BILINEAR: Image.Resampling.BILINEAR,
        ResamplingMode.BICUBIC: Image.Resampling.BICUBIC,
    }[resampling]


def _border_pixels(pixels: np.ndarray) -> np.ndarray:
    return np.concatenate(
        (pixels[0], pixels[-1], pixels[1:-1, 0], pixels[1:-1, -1]), axis=0
    )


def _border_median_rgb(pixels: np.ndarray) -> tuple[int, int, int]:
    values = np.median(_border_pixels(pixels), axis=0).astype(np.uint8)
    return int(values[0]), int(values[1]), int(values[2])


def _boundary_foreground_mask(pixels: np.ndarray) -> np.ndarray:
    median = np.median(_border_pixels(pixels), axis=0).astype(np.uint8)
    difference = np.abs(pixels.astype(np.int16) - median.astype(np.int16))
    return np.max(difference, axis=2) > _FOREGROUND_THRESHOLD


def _objective_foreground_mask(pixels: np.ndarray) -> np.ndarray:
    median = np.median(_border_pixels(pixels).astype(np.float64), axis=0)
    difference = np.abs(pixels.astype(np.float64) - median)
    return np.max(difference, axis=2) > _FOREGROUND_THRESHOLD


def _largest_component(mask: np.ndarray) -> np.ndarray | None:
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
    return selected


def _silhouette_edges(silhouette: np.ndarray) -> np.ndarray:
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


def _chebyshev_dilate(mask: np.ndarray, *, radius: int) -> np.ndarray:
    padded = np.pad(mask, radius, constant_values=False)
    dilated = np.zeros(mask.shape, dtype=np.bool_)
    diameter = 2 * radius + 1
    for y_offset in range(diameter):
        for x_offset in range(diameter):
            dilated |= padded[
                y_offset : y_offset + mask.shape[0],
                x_offset : x_offset + mask.shape[1],
            ]
    return dilated
