from __future__ import annotations

import io

from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.model import (
    filter_structural_residue,
    localized_anomaly_score,
    normalize_supported_geometry,
)


def source_image() -> Image.Image:
    image = Image.new("RGB", (128, 96), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 108, 76), fill=(180, 190, 200), outline=(30, 30, 30), width=3)
    draw.ellipse((35, 35, 55, 55), fill=(50, 50, 50))
    return image


def test_geometry_normalization_is_identity_for_equal_images() -> None:
    payload = encode_png(source_image(), mode="RGB")

    result = normalize_supported_geometry(payload, payload)

    assert result.applied is False
    assert result.inspection_bytes == payload
    assert result.correction_rotation_degrees == 0
    assert result.correction_scale == 1


def test_geometry_normalization_improves_supported_rotation() -> None:
    reference = source_image()
    inspection = reference.rotate(
        1.2,
        resample=Image.Resampling.NEAREST,
        fillcolor=(240, 240, 240),
    )

    result = normalize_supported_geometry(
        encode_png(reference, mode="RGB"),
        encode_png(inspection, mode="RGB"),
    )

    assert result.applied is True
    assert -1.5 <= result.correction_rotation_degrees <= -0.7
    assert result.normalized_edge_mae < result.baseline_edge_mae


def test_localized_score_detects_small_concentrated_mask() -> None:
    mask = Image.new("L", (128, 96), 0)
    ImageDraw.Draw(mask).rectangle((30, 30, 39, 39), fill=255)
    payload = encode_png(mask, mode="L")

    score = localized_anomaly_score(payload, window_size_px=32)

    assert score == 100 / (32 * 32)


def test_localized_score_does_not_amplify_sparse_registration_residue() -> None:
    mask = Image.new("L", (128, 96), 0)
    draw = ImageDraw.Draw(mask)
    for index in range(20):
        draw.point((index * 5 + 2, (index * 7) % 90 + 2), fill=255)
    payload = encode_png(mask, mode="L")

    score = localized_anomaly_score(payload, window_size_px=32)

    assert score == round(20 / (128 * 96), 8)


def test_localized_score_rejects_non_l_mask() -> None:
    payload = encode_png(source_image(), mode="RGB")

    try:
        localized_anomaly_score(payload)
    except Exception as exc:
        assert getattr(exc, "code", None) == "MASK_CORRUPT"
    else:  # pragma: no cover - fail explicitly without importing pytest
        raise AssertionError("RGB mask should fail")


def test_structural_residue_filter_removes_long_thin_lines_but_keeps_defect() -> None:
    mask = Image.new("L", (512, 384), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((100, 60, 180, 70), fill=255)
    draw.rectangle((220, 160, 276, 172), fill=255)

    reference = Image.new("RGB", (512, 384), (190, 190, 190))
    inspection = reference.copy()
    ImageDraw.Draw(inspection).rectangle((100, 60, 180, 70), fill=(100, 100, 100))
    ImageDraw.Draw(inspection).rectangle((220, 160, 276, 172), fill=(240, 240, 240))
    filtered = filter_structural_residue(
        encode_png(mask, mode="L"),
        reference_bytes=encode_png(reference, mode="RGB"),
        inspection_bytes=encode_png(inspection, mode="RGB"),
        normalization_applied=True,
    )

    with Image.open(io.BytesIO(filtered.mask_bytes)) as image:
        assert image.getpixel((120, 65)) == 0
        assert image.getpixel((240, 163)) == 255
    assert filtered.removed_component_count == 1
    assert filtered.removed_pixel_count == 81 * 11


def test_structural_residue_filter_preserves_high_burr_like_boundary_change() -> None:
    mask = Image.new("L", (512, 384), 0)
    ImageDraw.Draw(mask).rectangle((220, 56, 276, 69), fill=255)
    reference = Image.new("RGB", (512, 384), (190, 190, 190))
    inspection = reference.copy()
    ImageDraw.Draw(inspection).rectangle((220, 56, 276, 69), fill=(151, 151, 151))

    filtered = filter_structural_residue(
        encode_png(mask, mode="L"),
        reference_bytes=encode_png(reference, mode="RGB"),
        inspection_bytes=encode_png(inspection, mode="RGB"),
    )

    with Image.open(io.BytesIO(filtered.mask_bytes)) as image:
        assert image.getpixel((240, 62)) == 255
    assert filtered.removed_component_count == 0
    assert filtered.as_record()["algorithm"] == "structural_residue_filter_v2"


def test_structural_residue_filter_removes_neutral_residue_only_after_normalization() -> None:
    mask = Image.new("L", (128, 96), 0)
    ImageDraw.Draw(mask).rectangle((40, 20, 42, 56), fill=255)
    source = Image.new("RGB", (128, 96), (190, 190, 190))
    payload = encode_png(mask, mode="L")
    source_payload = encode_png(source, mode="RGB")

    retained = filter_structural_residue(
        payload,
        reference_bytes=source_payload,
        inspection_bytes=source_payload,
        normalization_applied=False,
    )
    removed = filter_structural_residue(
        payload,
        reference_bytes=source_payload,
        inspection_bytes=source_payload,
        normalization_applied=True,
    )

    assert retained.removed_pixel_count == 0
    assert removed.removed_pixel_count == 3 * 37
