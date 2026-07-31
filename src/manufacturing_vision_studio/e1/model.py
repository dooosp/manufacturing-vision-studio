"""Deterministic E1 normalization and localized anomaly scoring."""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.errors import UnsafeInputError


@dataclass(frozen=True, slots=True)
class GeometryNormalization:
    """Auditable correction selected without defect or nuisance truth."""

    inspection_bytes: bytes
    inspection_sha256: str
    applied: bool
    correction_rotation_degrees: float
    correction_scale: float
    comparison_shift_x: int
    comparison_shift_y: int
    baseline_edge_mae: float
    normalized_edge_mae: float

    def as_record(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "correction_rotation_degrees": self.correction_rotation_degrees,
            "correction_scale": self.correction_scale,
            "comparison_shift_x": self.comparison_shift_x,
            "comparison_shift_y": self.comparison_shift_y,
            "baseline_edge_mae": self.baseline_edge_mae,
            "normalized_edge_mae": self.normalized_edge_mae,
            "normalized_inspection_sha256": self.inspection_sha256,
        }


@dataclass(frozen=True, slots=True)
class MaskPostprocessing:
    """Deterministic removal of declared long-thin normalization residue."""

    mask_bytes: bytes
    mask_sha256: str
    removed_component_count: int
    removed_pixel_count: int

    def as_record(self) -> dict[str, object]:
        return {
            "algorithm": "structural_residue_filter_v2",
            "removed_component_count": self.removed_component_count,
            "removed_pixel_count": self.removed_pixel_count,
            "filtered_mask_sha256": self.mask_sha256,
        }


def normalize_supported_geometry(
    reference_bytes: bytes,
    inspection_bytes: bytes,
    *,
    rotation_limit_degrees: float = 1.5,
    scale_delta_limit: float = 0.02,
    apply_improvement_ratio: float = 0.05,
) -> GeometryNormalization:
    """Infer small rotation/scale corrections from edge agreement only.

    The search never receives case labels, generator nuisance parameters, masks,
    or expected features. A correction is applied only when it improves the
    whole-image edge fit by at least the preregistered ratio.
    """

    reference = _decode_rgb(reference_bytes)
    inspection = _decode_rgb(inspection_bytes)
    if reference.size != inspection.size:
        raise UnsafeInputError("E1 image dimensions do not match", code="IMAGE_DIMENSION_MISMATCH")
    reference_foreground = _foreground_signature(reference)
    inspection_foreground = _foreground_signature(inspection)
    shift_x, shift_y = _best_small_shift(
        reference_foreground,
        inspection_foreground,
        limit=12,
    )
    baseline_error = _shifted_mae(
        reference_foreground,
        inspection_foreground,
        shift_x,
        shift_y,
    )
    reference_angle, reference_major, reference_minor = _foreground_moments(reference_foreground)
    inspection_angle, inspection_major, inspection_minor = _foreground_moments(
        inspection_foreground
    )
    best_rotation = max(
        -rotation_limit_degrees,
        min(rotation_limit_degrees, inspection_angle - reference_angle),
    )
    estimated_scale = (reference_major / inspection_major + reference_minor / inspection_minor) / 2
    best_scale = max(1 - scale_delta_limit, min(1 + scale_delta_limit, estimated_scale))
    rotated = inspection.rotate(
        best_rotation,
        resample=Image.Resampling.NEAREST,
        expand=False,
        fillcolor=_corner_color(inspection),
    )
    transformed = _scale_centered(
        rotated,
        factor=best_scale,
        fill=_corner_color(rotated),
        resample=Image.Resampling.NEAREST,
    )
    transformed_foreground = _foreground_signature(transformed)
    normalized_shift_x, normalized_shift_y = _best_small_shift(
        reference_foreground,
        transformed_foreground,
        limit=12,
    )
    best_error = _shifted_mae(
        reference_foreground,
        transformed_foreground,
        normalized_shift_x,
        normalized_shift_y,
    )

    improvement = (baseline_error - best_error) / baseline_error if baseline_error > 0 else 0.0
    applied = improvement >= apply_improvement_ratio and (best_rotation != 0.0 or best_scale != 1.0)
    if applied:
        corrected = inspection.rotate(
            best_rotation,
            resample=Image.Resampling.NEAREST,
            expand=False,
            fillcolor=_corner_color(inspection),
        )
        corrected = _scale_centered(
            corrected,
            factor=best_scale,
            fill=_corner_color(corrected),
            resample=Image.Resampling.NEAREST,
        )
        normalized_bytes = encode_png(corrected, mode="RGB")
    else:
        normalized_bytes = inspection_bytes
        best_rotation = 0.0
        best_scale = 1.0
        best_error = baseline_error
    return GeometryNormalization(
        inspection_bytes=normalized_bytes,
        inspection_sha256=sha256_bytes(normalized_bytes),
        applied=applied,
        correction_rotation_degrees=round(best_rotation, 6),
        correction_scale=round(best_scale, 6),
        comparison_shift_x=shift_x,
        comparison_shift_y=shift_y,
        baseline_edge_mae=round(baseline_error, 8),
        normalized_edge_mae=round(best_error, 8),
    )


def localized_anomaly_score(
    mask_bytes: bytes,
    *,
    window_size_px: int = 64,
    minimum_component_pixels: int = 32,
) -> float:
    """Return max(global density, densest fixed local window density)."""

    try:
        with Image.open(io.BytesIO(mask_bytes)) as image:
            if image.format != "PNG" or image.mode != "L":
                raise UnsafeInputError("Predicted mask is invalid", code="MASK_CORRUPT")
            mask = np.asarray(image, dtype=np.uint8) > 0
    except UnsafeInputError:
        raise
    except (OSError, SyntaxError, ValueError) as exc:
        raise UnsafeInputError("Predicted mask is invalid", code="MASK_CORRUPT") from exc
    height, width = mask.shape
    if not 1 <= window_size_px <= min(width, height):
        raise ValueError("window_size_px must fit within the mask")
    if minimum_component_pixels < 1:
        raise ValueError("minimum_component_pixels must be positive")
    global_density = float(np.count_nonzero(mask) / mask.size)
    coherent_mask = _components_at_least(mask, minimum_component_pixels)
    if not np.any(coherent_mask):
        return round(global_density, 8)
    integral = np.pad(coherent_mask.astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    size = window_size_px
    window_counts = (
        integral[size:, size:]
        - integral[:-size, size:]
        - integral[size:, :-size]
        + integral[:-size, :-size]
    )
    local_density = float(np.max(window_counts) / (size * size))
    return round(max(global_density, local_density), 8)


def filter_structural_residue(
    mask_bytes: bytes,
    *,
    reference_bytes: bytes,
    inspection_bytes: bytes,
    normalization_applied: bool = False,
    long_thin_min_major_px: int = 81,
    long_thin_max_minor_px: int = 12,
    affine_neutral_min_pixels: int = 32,
    affine_neutral_max_abs_luminance_delta: float = 4,
    boundary_horizontal_min_width_px: int = 46,
    boundary_horizontal_max_height_px: int = 16,
    top_boundary_max_y_px: int = 80,
    bottom_boundary_min_y_px: int = 304,
    dark_fixture_max_luminance_delta: float = -60,
) -> MaskPostprocessing:
    """Remove development-characterized affine/fixture residual shapes.

    The filter consumes only the predicted binary mask, normalized source
    pixels, the image-derived normalization-applied flag, and fixed image-space
    bounds. It never receives labels, truth masks, expected features, or case
    nuisance metadata.
    """

    mask = _decode_mask(mask_bytes)
    reference = np.asarray(_decode_rgb(reference_bytes), dtype=np.int16)
    inspection = np.asarray(_decode_rgb(inspection_bytes), dtype=np.int16)
    if reference.shape != inspection.shape or reference.shape[:2] != mask.shape:
        raise UnsafeInputError("Postprocessing image dimensions do not match", code="HASH_MISMATCH")
    filtered = mask.copy()
    removed_components = 0
    removed_pixels = 0
    for component in _connected_components(mask):
        y_values = [point[0] for point in component]
        x_values = [point[1] for point in component]
        width = max(x_values) - min(x_values) + 1
        height = max(y_values) - min(y_values) + 1
        major = max(width, height)
        minor = min(width, height)
        long_thin_affine_residue = (
            normalization_applied
            and major >= long_thin_min_major_px
            and minor <= long_thin_max_minor_px
        )
        boundary_horizontal = (
            width >= boundary_horizontal_min_width_px
            and height <= boundary_horizontal_max_height_px
            and (
                min(y_values) <= top_boundary_max_y_px or max(y_values) >= bottom_boundary_min_y_px
            )
        )
        component_y = np.asarray(y_values, dtype=np.intp)
        component_x = np.asarray(x_values, dtype=np.intp)
        luminance_delta = float(
            np.mean(inspection[component_y, component_x])
            - np.mean(reference[component_y, component_x])
        )
        dark_boundary_fixture = (
            boundary_horizontal and luminance_delta <= dark_fixture_max_luminance_delta
        )
        affine_neutral_residue = (
            normalization_applied
            and len(component) >= affine_neutral_min_pixels
            and abs(luminance_delta) <= affine_neutral_max_abs_luminance_delta
        )
        if long_thin_affine_residue or affine_neutral_residue or dark_boundary_fixture:
            removed_components += 1
            removed_pixels += len(component)
            for y, x in component:
                filtered[y, x] = False
    payload = encode_png(Image.fromarray(np.where(filtered, 255, 0).astype(np.uint8)), mode="L")
    return MaskPostprocessing(
        mask_bytes=payload,
        mask_sha256=sha256_bytes(payload),
        removed_component_count=removed_components,
        removed_pixel_count=removed_pixels,
    )


def _components_at_least(mask: np.ndarray, minimum_pixels: int) -> np.ndarray:
    retained = np.zeros(mask.shape, dtype=bool)
    for component in _connected_components(mask):
        if len(component) >= minimum_pixels:
            for component_y, component_x in component:
                retained[component_y, component_x] = True
    return retained


def _connected_components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    for raw_y, raw_x in np.argwhere(mask):
        y, x = int(raw_y), int(raw_x)
        if visited[y, x]:
            continue
        visited[y, x] = True
        component = [(y, x)]
        stack = [(y, x)]
        while stack:
            current_y, current_x = stack.pop()
            for delta_y in (-1, 0, 1):
                for delta_x in (-1, 0, 1):
                    candidate_y = current_y + delta_y
                    candidate_x = current_x + delta_x
                    if (
                        0 <= candidate_y < height
                        and 0 <= candidate_x < width
                        and mask[candidate_y, candidate_x]
                        and not visited[candidate_y, candidate_x]
                    ):
                        visited[candidate_y, candidate_x] = True
                        component.append((candidate_y, candidate_x))
                        stack.append((candidate_y, candidate_x))
        components.append(component)
    return components


def _decode_mask(mask_bytes: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(mask_bytes)) as image:
            if image.format != "PNG" or image.mode != "L":
                raise UnsafeInputError("Predicted mask is invalid", code="MASK_CORRUPT")
            return (np.asarray(image, dtype=np.uint8) > 0).copy()
    except UnsafeInputError:
        raise
    except (OSError, SyntaxError, ValueError) as exc:
        raise UnsafeInputError("Predicted mask is invalid", code="MASK_CORRUPT") from exc


def _decode_rgb(payload: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.format != "PNG" or image.mode != "RGB":
                raise UnsafeInputError("E1 source image is invalid", code="IMAGE_DECODE_FAILED")
            image.load()
            return image.copy()
    except UnsafeInputError:
        raise
    except (OSError, SyntaxError, ValueError) as exc:
        raise UnsafeInputError("E1 source image is invalid", code="IMAGE_DECODE_FAILED") from exc


def _foreground_signature(image: Image.Image) -> np.ndarray:
    pixels = np.asarray(image, dtype=np.int16)
    border = np.concatenate(
        (
            pixels[:3].reshape(-1, 3),
            pixels[-3:].reshape(-1, 3),
            pixels[:, :3].reshape(-1, 3),
            pixels[:, -3:].reshape(-1, 3),
        )
    )
    background = np.median(border, axis=0)
    distance = np.max(np.abs(pixels - background), axis=2)
    return (distance > 18).astype(np.float32)


def _foreground_moments(mask: np.ndarray) -> tuple[float, float, float]:
    y_coordinates, x_coordinates = np.nonzero(mask)
    if x_coordinates.size < 16:
        raise UnsafeInputError("Part geometry could not be normalized", code="MODEL_ABSTAINED")
    centered = np.stack(
        (
            x_coordinates - np.mean(x_coordinates),
            y_coordinates - np.mean(y_coordinates),
        ),
        axis=1,
    )
    covariance = np.cov(centered, rowvar=False)
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)
    minor = float(np.sqrt(values[order[0]]))
    major = float(np.sqrt(values[order[-1]]))
    vector = vectors[:, order[-1]]
    angle = float(np.degrees(np.arctan2(vector[1], vector[0])))
    if angle > 90:
        angle -= 180
    if angle < -90:
        angle += 180
    return angle, major, minor


def _best_small_shift(
    reference: np.ndarray,
    inspection: np.ndarray,
    *,
    limit: int,
) -> tuple[int, int]:
    candidates = (
        (_shifted_mae(reference, inspection, dx, dy), abs(dx) + abs(dy), dy, dx)
        for dy in range(-limit, limit + 1)
        for dx in range(-limit, limit + 1)
    )
    best = min(candidates)
    return best[3], best[2]


def _shifted_mae(
    reference: np.ndarray,
    inspection: np.ndarray,
    dx: int,
    dy: int,
) -> float:
    height, width = reference.shape
    reference_y0 = max(0, -dy)
    reference_y1 = min(height, height - dy)
    inspection_y0 = reference_y0 + dy
    inspection_y1 = reference_y1 + dy
    reference_x0 = max(0, -dx)
    reference_x1 = min(width, width - dx)
    inspection_x0 = reference_x0 + dx
    inspection_x1 = reference_x1 + dx
    difference = np.abs(
        reference[reference_y0:reference_y1, reference_x0:reference_x1]
        - inspection[inspection_y0:inspection_y1, inspection_x0:inspection_x1]
    )
    return float(np.mean(difference))


def _scale_centered(
    image: Image.Image,
    *,
    factor: float,
    fill: tuple[int, int, int],
    resample: Image.Resampling = Image.Resampling.BILINEAR,
) -> Image.Image:
    width, height = image.size
    scaled_width = max(1, round(width * factor))
    scaled_height = max(1, round(height * factor))
    resized = image.resize((scaled_width, scaled_height), resample)
    output = Image.new("RGB", image.size, fill)
    source_left = max(0, (scaled_width - width) // 2)
    source_top = max(0, (scaled_height - height) // 2)
    crop = resized.crop(
        (
            source_left,
            source_top,
            min(scaled_width, source_left + width),
            min(scaled_height, source_top + height),
        )
    )
    output.paste(crop, ((width - crop.width) // 2, (height - crop.height) // 2))
    return output


def _corner_color(image: Image.Image) -> tuple[int, int, int]:
    pixels = (
        image.getpixel((0, 0)),
        image.getpixel((image.width - 1, 0)),
        image.getpixel((0, image.height - 1)),
        image.getpixel((image.width - 1, image.height - 1)),
    )
    channels = tuple(round(sum(pixel[index] for pixel in pixels) / 4) for index in range(3))
    return channels
