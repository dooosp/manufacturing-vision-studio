from __future__ import annotations

from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.model import (
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
