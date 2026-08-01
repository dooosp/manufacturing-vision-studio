"""Independent E1 defect truth rendering and fail-closed mask validation."""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain import (
    AuthoritativeMaskValidation,
    CadRevision,
    DefectSpec,
    DefectType,
    E1CasePlan,
    E1GeneratedCase,
    FeatureRegion,
    ViewId,
)
from manufacturing_vision_studio.e1.protocol import E1Protocol
from manufacturing_vision_studio.errors import UnsafeInputError


@dataclass(frozen=True, slots=True)
class E1RenderGeometry:
    """Pixel geometry shared by the pristine renderer and truth operations."""

    width: int
    height: int
    plate_box: tuple[int, int, int, int]
    left_hole_center: tuple[int, int]
    right_hole_center: tuple[int, int]
    hole_radius: int
    slot_box: tuple[int, int, int, int]
    background: tuple[int, int, int]
    plate_fill: tuple[int, int, int]
    feature_regions: tuple[tuple[str, FeatureRegion], ...]

    def feature_region(self, feature_id: str) -> FeatureRegion:
        for candidate, region in self.feature_regions:
            if candidate == feature_id:
                return region
        raise UnsafeInputError(
            "Defect target feature is not registered",
            code="SCHEMA_INVALID",
            details={"feature_id": feature_id},
        )

    def feature_box(self, feature_id: str) -> tuple[int, int, int, int]:
        left, top, right, bottom = self.feature_region(feature_id)
        return (
            math.floor(left * self.width),
            math.floor(top * self.height),
            math.ceil(right * self.width),
            math.ceil(bottom * self.height),
        )

    def hole_center(self, feature_id: str) -> tuple[int, int]:
        if feature_id == "hole_left":
            return self.left_hole_center
        if feature_id == "hole_right":
            return self.right_hole_center
        raise UnsafeInputError(
            "Defect target is not a hole",
            code="SCHEMA_INVALID",
            details={"feature_id": feature_id},
        )


def geometry_for_case(
    cad_revision: CadRevision,
    view_id: ViewId,
    *,
    image_size: tuple[int, int],
    feature_regions: Mapping[str, FeatureRegion],
) -> E1RenderGeometry:
    """Resolve recipe-v1 geometry for the two revisions and three views."""

    width, height = image_size
    if width < 128 or height < 96:
        raise UnsafeInputError("E1 image dimensions are too small", code="SCHEMA_INVALID")

    scale_x = width / 512
    scale_y = height / 384
    view_geometry = {
        ViewId.FRONT: ((52, 64, 460, 320), (156, 192), (356, 192), (229, 126, 283, 258)),
        ViewId.OBLIQUE_LEFT: (
            (61, 68, 451, 316),
            (171, 196),
            (350, 187),
            (235, 126, 287, 254),
        ),
        ViewId.OBLIQUE_RIGHT: (
            (61, 68, 451, 316),
            (162, 187),
            (341, 196),
            (225, 126, 277, 254),
        ),
    }
    plate, left_hole, right_hole, slot = view_geometry[view_id]
    if cad_revision is CadRevision.REV_B:
        right_hole = (right_hole[0] + 4, right_hole[1])

    def point(value: tuple[int, int]) -> tuple[int, int]:
        return round(value[0] * scale_x), round(value[1] * scale_y)

    def box(value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return (
            round(value[0] * scale_x),
            round(value[1] * scale_y),
            round(value[2] * scale_x),
            round(value[3] * scale_y),
        )

    backgrounds = {
        ViewId.FRONT: (238, 241, 244),
        ViewId.OBLIQUE_LEFT: (235, 239, 243),
        ViewId.OBLIQUE_RIGHT: (240, 242, 245),
    }
    plate_fills = {
        ViewId.FRONT: (195, 203, 210),
        ViewId.OBLIQUE_LEFT: (191, 201, 209),
        ViewId.OBLIQUE_RIGHT: (199, 206, 212),
    }
    return E1RenderGeometry(
        width=width,
        height=height,
        plate_box=box(plate),
        left_hole_center=point(left_hole),
        right_hole_center=point(right_hole),
        hole_radius=max(8, round(39 * min(scale_x, scale_y))),
        slot_box=box(slot),
        background=backgrounds[view_id],
        plate_fill=plate_fills[view_id],
        feature_regions=tuple(sorted(feature_regions.items())),
    )


def render_defect_truth(
    pristine: Image.Image,
    defect: DefectSpec,
    *,
    seed: int,
    geometry: E1RenderGeometry,
) -> tuple[Image.Image, Image.Image]:
    """Apply one defect and draw its independent binary truth in the same operation."""

    if pristine.mode != "RGB" or pristine.size != (geometry.width, geometry.height):
        raise UnsafeInputError("Pristine E1 image geometry is invalid", code="SCHEMA_INVALID")
    inspection = pristine.copy()
    mask = Image.new("L", pristine.size, 0)
    image_draw = ImageDraw.Draw(inspection)
    mask_draw = ImageDraw.Draw(mask)
    parameters = {parameter.name: parameter.value for parameter in defect.parameters}

    if defect.defect_type is DefectType.SCRATCH:
        _draw_scratch(image_draw, mask_draw, defect, parameters, seed, geometry)
    elif defect.defect_type is DefectType.STAIN:
        _draw_stain(image_draw, mask_draw, defect, parameters, seed, geometry)
    elif defect.defect_type is DefectType.EDGE_CHIP:
        _draw_edge_chip(image_draw, mask_draw, defect, parameters, seed, geometry)
    elif defect.defect_type is DefectType.BURR:
        _draw_burr(image_draw, mask_draw, defect, parameters, seed, geometry)
    elif defect.defect_type is DefectType.BLOCKED_HOLE:
        _draw_blocked_hole(inspection, mask, defect, parameters, seed, geometry)
    elif defect.defect_type is DefectType.HOLE_GEOMETRY_DEVIATION:
        _draw_hole_deviation(image_draw, mask_draw, defect, parameters, seed, geometry)
    else:  # pragma: no cover - enum exhaustiveness is defensive
        raise UnsafeInputError("Unknown E1 defect recipe", code="SCHEMA_INVALID")

    mask_values = (
        mask.get_flattened_data() if hasattr(mask, "get_flattened_data") else mask.getdata()
    )
    values = set(mask_values)
    if not values.issubset({0, 255}) or 255 not in values:
        raise UnsafeInputError("Defect recipe emitted invalid truth", code="MASK_CORRUPT")
    if defect.target_feature_id == "top_face":
        _assert_top_face_exclusive(mask, geometry)
    return inspection, mask


def validate_authoritative_truth(
    plan: E1CasePlan,
    mask_png: bytes,
    declared_sha256: str,
    *,
    image_size: tuple[int, int],
    feature_regions: Mapping[str, FeatureRegion],
) -> AuthoritativeMaskValidation:
    """Validate truth without accepting or consulting any model prediction."""

    return validate_authoritative_mask(
        mask_png,
        declared_sha256=declared_sha256,
        expected_size=image_size,
        expected_non_empty=plan.defect is not None,
        target_feature_id=None if plan.defect is None else plan.defect.target_feature_id,
        feature_regions=feature_regions,
    )


def validate_authoritative_mask(
    mask_png: bytes,
    *,
    declared_sha256: str,
    expected_size: tuple[int, int],
    expected_non_empty: bool,
    target_feature_id: str | None = None,
    feature_regions: Mapping[str, FeatureRegion] | None = None,
) -> AuthoritativeMaskValidation:
    """Fail closed on hash, container, geometry, binary, or semantic mask errors."""

    actual_sha256 = sha256_bytes(mask_png)
    if actual_sha256 != declared_sha256:
        raise UnsafeInputError(
            "Authoritative mask hash does not match",
            code="HASH_MISMATCH",
            details={"declared": declared_sha256, "actual": actual_sha256},
        )
    pixels = _decode_canonical_png(mask_png, mode="L", expected_size=expected_size, mask=True)
    unique_values = set(int(value) for value in np.unique(pixels))
    if not unique_values.issubset({0, 255}):
        raise UnsafeInputError(
            "Authoritative mask must contain only 0 and 255",
            code="MASK_CORRUPT",
            details={"values": sorted(unique_values)},
        )
    positive_pixels = int(np.count_nonzero(pixels == 255))
    if expected_non_empty and positive_pixels == 0:
        raise UnsafeInputError("Positive truth mask is empty", code="MASK_CORRUPT")
    if not expected_non_empty and positive_pixels != 0:
        raise UnsafeInputError("Negative truth mask is not empty", code="MASK_CORRUPT")

    overlap: int | None = None
    if target_feature_id is not None:
        if feature_regions is None or target_feature_id not in feature_regions:
            raise UnsafeInputError(
                "Authoritative mask target feature is unknown",
                code="SCHEMA_INVALID",
                details={"feature_id": target_feature_id},
            )
        overlap = _feature_overlap(pixels, feature_regions[target_feature_id])
        if overlap < 1:
            raise UnsafeInputError(
                "Authoritative mask does not overlap its target feature",
                code="MASK_CORRUPT",
                details={"feature_id": target_feature_id},
            )
    return AuthoritativeMaskValidation(
        sha256=actual_sha256,
        width=expected_size[0],
        height=expected_size[1],
        positive_pixel_count=positive_pixels,
        target_feature_overlap_pixels=overlap,
    )


def validate_generated_case(
    generated: E1GeneratedCase,
    protocol: E1Protocol,
) -> AuthoritativeMaskValidation:
    """Validate all generated source hashes and canonical image/mask contracts."""

    if (
        generated.generator_id != protocol.generator_id
        or generated.generator_version != protocol.generator_version
        or generated.generator_configuration_sha256 != protocol.generator_configuration_sha256
    ):
        raise UnsafeInputError(
            "Generated case has the wrong generator binding", code="HASH_MISMATCH"
        )
    bindings = (
        ("reference", generated.reference_bytes, generated.reference_sha256),
        ("inspection", generated.inspection_bytes, generated.inspection_sha256),
    )
    for label, payload, declared in bindings:
        actual = sha256_bytes(payload)
        if actual != declared:
            raise UnsafeInputError(
                f"Generated {label} hash does not match",
                code="HASH_MISMATCH",
                details={"declared": declared, "actual": actual},
            )
        _decode_canonical_png(payload, mode="RGB", expected_size=protocol.image_size, mask=False)
    expected_case_binding = protocol.case_binding_sha256(
        generated.plan,
        reference_sha256=generated.reference_sha256,
        inspection_sha256=generated.inspection_sha256,
        authoritative_mask_sha256=generated.authoritative_mask_sha256,
    )
    if generated.case_binding_sha256 != expected_case_binding:
        raise UnsafeInputError("Generated case binding does not match", code="HASH_MISMATCH")
    regions = protocol.feature_regions_for_view(generated.plan.view_id)
    return validate_authoritative_truth(
        generated.plan,
        generated.authoritative_mask_bytes,
        generated.authoritative_mask_sha256,
        image_size=protocol.image_size,
        feature_regions=regions,
    )


def _decode_canonical_png(
    payload: bytes,
    *,
    mode: str,
    expected_size: tuple[int, int],
    mask: bool,
) -> np.ndarray:
    code = "MASK_CORRUPT" if mask else "IMAGE_DECODE_FAILED"
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if (
                image.format != "PNG"
                or image.mode != mode
                or image.size != expected_size
                or getattr(image, "n_frames", 1) != 1
                or image.info
            ):
                raise UnsafeInputError("Generated PNG metadata is invalid", code=code)
            image.load()
            canonical = encode_png(image, mode=mode)
            if canonical != payload:
                raise UnsafeInputError("Generated PNG is not canonical", code=code)
            return np.asarray(image, dtype=np.uint8).copy()
    except UnsafeInputError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UnsafeInputError("Generated PNG could not be decoded", code=code) from exc


def _feature_overlap(pixels: np.ndarray, region: FeatureRegion) -> int:
    height, width = pixels.shape
    left = max(0, min(width, math.floor(region[0] * width)))
    top = max(0, min(height, math.floor(region[1] * height)))
    right = max(0, min(width, math.ceil(region[2] * width)))
    bottom = max(0, min(height, math.ceil(region[3] * height)))
    if left >= right or top >= bottom:
        raise UnsafeInputError("Target feature region is invalid", code="SCHEMA_INVALID")
    return int(np.count_nonzero(pixels[top:bottom, left:right] == 255))


def _draw_scratch(
    image_draw: ImageDraw.ImageDraw,
    mask_draw: ImageDraw.ImageDraw,
    defect: DefectSpec,
    parameters: Mapping[str, int | float],
    seed: int,
    geometry: E1RenderGeometry,
) -> None:
    length = _integer_parameter(parameters, "length")
    width = _integer_parameter(parameters, "width")
    left, top, right, bottom = _exclusive_top_face_box(geometry, margin=width + 2)
    center_x = _bounded_coordinate(seed, "scratch-x", left, right)
    center_y = _bounded_coordinate(
        seed,
        "scratch-y",
        top + length // 2,
        bottom - length // 2,
    )
    dx = max(3, min((right - left) // 3, length // 8))
    if not _digest_bit(seed, "scratch-slope"):
        dx = -dx
    start = (center_x - dx // 2, center_y - length // 2)
    end = (center_x + dx // 2, center_y + length // 2)
    image_draw.line((start, end), fill=(86, 51, 44), width=width)
    mask_draw.line((start, end), fill=255, width=width)


def _draw_stain(
    image_draw: ImageDraw.ImageDraw,
    mask_draw: ImageDraw.ImageDraw,
    defect: DefectSpec,
    parameters: Mapping[str, int | float],
    seed: int,
    geometry: E1RenderGeometry,
) -> None:
    radius = _integer_parameter(parameters, "radius")
    delta = _integer_parameter(parameters, "rgb_delta")
    left, top, right, bottom = _exclusive_top_face_box(geometry, margin=radius + 2)
    center_x = _bounded_coordinate(seed, "stain-x", left + radius, right - radius)
    center_y = _bounded_coordinate(seed, "stain-y", top + radius, bottom - radius)
    box = (center_x - radius, center_y - radius, center_x + radius, center_y + radius)
    color = (
        max(0, geometry.plate_fill[0] - delta),
        max(0, geometry.plate_fill[1] - delta),
        max(0, geometry.plate_fill[2] - delta),
    )
    image_draw.ellipse(box, fill=color)
    mask_draw.ellipse(box, fill=255)


def _draw_edge_chip(
    image_draw: ImageDraw.ImageDraw,
    mask_draw: ImageDraw.ImageDraw,
    defect: DefectSpec,
    parameters: Mapping[str, int | float],
    seed: int,
    geometry: E1RenderGeometry,
) -> None:
    depth = _integer_parameter(parameters, "depth")
    length = _integer_parameter(parameters, "length")
    plate_left, plate_top, plate_right, plate_bottom = geometry.plate_box
    center_x = _bounded_coordinate(
        seed,
        "chip-x",
        plate_left + length // 2 + 20,
        plate_right - length // 2 - 20,
    )
    if defect.target_feature_id == "top_edge":
        box = (center_x - length // 2, plate_top - 1, center_x + length // 2, plate_top + depth)
    else:
        box = (
            center_x - length // 2,
            plate_bottom - depth,
            center_x + length // 2,
            plate_bottom + 1,
        )
    image_draw.rectangle(box, fill=geometry.background)
    mask_draw.rectangle(box, fill=255)


def _draw_burr(
    image_draw: ImageDraw.ImageDraw,
    mask_draw: ImageDraw.ImageDraw,
    defect: DefectSpec,
    parameters: Mapping[str, int | float],
    seed: int,
    geometry: E1RenderGeometry,
) -> None:
    height = _integer_parameter(parameters, "height")
    length = _integer_parameter(parameters, "length")
    plate_left, plate_top, plate_right, plate_bottom = geometry.plate_box
    center_x = _bounded_coordinate(
        seed,
        "burr-x",
        plate_left + length // 2 + 20,
        plate_right - length // 2 - 20,
    )
    if defect.target_feature_id == "top_edge":
        points = (
            (center_x - length // 2, plate_top + 1),
            (center_x - length // 3, plate_top - height),
            (center_x + length // 2, plate_top + 1),
        )
    else:
        points = (
            (center_x - length // 2, plate_bottom - 1),
            (center_x + length // 3, plate_bottom + height),
            (center_x + length // 2, plate_bottom - 1),
        )
    image_draw.polygon(points, fill=(151, 160, 167))
    mask_draw.polygon(points, fill=255)


def _draw_blocked_hole(
    inspection: Image.Image,
    mask: Image.Image,
    defect: DefectSpec,
    parameters: Mapping[str, int | float],
    seed: int,
    geometry: E1RenderGeometry,
) -> None:
    fraction = _float_parameter(parameters, "occlusion_fraction")
    center_x, center_y = geometry.hole_center(defect.target_feature_id)
    radius = geometry.hole_radius
    hole_mask = Image.new("L", inspection.size, 0)
    ImageDraw.Draw(hole_mask).ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=255,
    )
    block = Image.new("L", inspection.size, 0)
    width = max(1, round(2 * radius * fraction))
    from_left = _digest_bit(seed, "blocked-hole-side")
    if from_left:
        box = (center_x - radius, center_y - radius, center_x - radius + width, center_y + radius)
    else:
        box = (center_x + radius - width, center_y - radius, center_x + radius, center_y + radius)
    ImageDraw.Draw(block).rectangle(box, fill=255)
    truth = ImageChops.multiply(hole_mask, block)
    inspection.paste(geometry.plate_fill, mask=truth)
    mask.paste(255, mask=truth)


def _draw_hole_deviation(
    image_draw: ImageDraw.ImageDraw,
    mask_draw: ImageDraw.ImageDraw,
    defect: DefectSpec,
    parameters: Mapping[str, int | float],
    seed: int,
    geometry: E1RenderGeometry,
) -> None:
    offset = _integer_parameter(parameters, "center_offset")
    diameter_delta = _integer_parameter(parameters, "diameter_delta")
    center_x, center_y = geometry.hole_center(defect.target_feature_id)
    radius = geometry.hole_radius
    old_box = (center_x - radius, center_y - radius, center_x + radius, center_y + radius)
    image_draw.ellipse(old_box, fill=geometry.plate_fill)
    mask_draw.ellipse(old_box, fill=255)

    direction = _digest_index(seed, "hole-deviation-direction", 4)
    dx, dy = ((offset, 0), (-offset, 0), (0, offset), (0, -offset))[direction]
    new_radius = max(
        4,
        radius
        + (diameter_delta if _digest_bit(seed, "hole-diameter-sign") else -diameter_delta) // 2,
    )
    new_center = center_x + dx, center_y + dy
    new_box = (
        new_center[0] - new_radius,
        new_center[1] - new_radius,
        new_center[0] + new_radius,
        new_center[1] + new_radius,
    )
    image_draw.ellipse(new_box, fill=(57, 65, 72), outline=(24, 29, 33), width=5)
    inner = max(2, new_radius - 11)
    image_draw.ellipse(
        (
            new_center[0] - inner,
            new_center[1] - inner,
            new_center[0] + inner,
            new_center[1] + inner,
        ),
        fill=geometry.background,
        outline=(121, 130, 137),
        width=3,
    )
    mask_draw.ellipse(new_box, fill=255)


def _integer_parameter(parameters: Mapping[str, int | float], name: str) -> int:
    value = parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise UnsafeInputError(f"Invalid defect parameter: {name}", code="SCHEMA_INVALID")
    return max(1, round(float(value)))


def _float_parameter(parameters: Mapping[str, int | float], name: str) -> float:
    value = parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise UnsafeInputError(f"Invalid defect parameter: {name}", code="SCHEMA_INVALID")
    return float(value)


def _exclusive_top_face_box(
    geometry: E1RenderGeometry,
    *,
    margin: int,
) -> tuple[int, int, int, int]:
    top_face = geometry.feature_box("top_face")
    left_hole = geometry.feature_box("hole_left")
    right_hole = geometry.feature_box("hole_right")
    top_edge = geometry.feature_box("top_edge")
    bottom_edge = geometry.feature_box("bottom_edge")
    box = (
        max(top_face[0], left_hole[2] + margin),
        max(top_face[1], top_edge[3] + margin),
        min(top_face[2], right_hole[0] - margin),
        min(top_face[3], bottom_edge[1] - margin),
    )
    if box[0] >= box[2] or box[1] >= box[3]:
        raise UnsafeInputError(
            "Top-face recipe has no feature-exclusive placement region",
            code="SCHEMA_INVALID",
        )
    return box


def _assert_top_face_exclusive(mask: Image.Image, geometry: E1RenderGeometry) -> None:
    pixels = np.asarray(mask, dtype=np.uint8)
    for feature_id in ("hole_left", "hole_right", "top_edge", "bottom_edge"):
        left, top, right, bottom = geometry.feature_box(feature_id)
        if np.any(pixels[top:bottom, left:right] == 255):
            raise UnsafeInputError(
                "Top-face truth overlaps a subordinate feature",
                code="MASK_CORRUPT",
                details={"overlapping_feature_id": feature_id},
            )


def _bounded_coordinate(seed: int, label: str, minimum: int, maximum: int) -> int:
    if minimum > maximum:
        return (minimum + maximum) // 2
    return minimum + _digest_index(seed, label, maximum - minimum + 1)


def _digest_index(seed: int, label: str, size: int) -> int:
    if size <= 0:
        raise ValueError("digest choice size must be positive")
    payload = f"mvs-e1-recipe-v1\0{seed}\0{label}".encode()
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return value % size


def _digest_bit(seed: int, label: str) -> bool:
    return bool(_digest_index(seed, label, 2))
