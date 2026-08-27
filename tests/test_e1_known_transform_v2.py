from __future__ import annotations

import io
from dataclasses import astuple
from hashlib import sha256

import numpy as np
import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.geometry import (
    _inverse_affine,
    alignment_objective,
    largest_component_silhouette,
    silhouette_edges,
)
from manufacturing_vision_studio.e1.known_transform_v2 import (
    AffineCoefficients,
    AppliedAffineTransform,
    CorrectionAffineTransform,
    ResamplingMode,
    StudyAlignmentObjective,
    derive_correction,
    measure_alignment,
    normalize_known_transform,
    pillow_output_to_input_coefficients,
    reference_boundary_band,
)

_IMAGE_SIZE = (512, 384)


@pytest.fixture
def asymmetric_png() -> bytes:
    image = Image.new("RGB", _IMAGE_SIZE, (17, 23, 31))
    draw = ImageDraw.Draw(image)
    draw.polygon(((52, 44), (177, 61), (155, 161), (76, 139)), fill=(231, 37, 19))
    draw.rectangle((246, 89, 313, 137), fill=(29, 211, 83))
    draw.ellipse((355, 217, 411, 295), fill=(61, 97, 239))
    draw.polygon(((192, 257), (270, 243), (286, 328), (214, 311)), fill=(241, 197, 41))
    return encode_png(image, mode="RGB")


@pytest.fixture
def transformed_fixture(asymmetric_png: bytes) -> tuple[bytes, bytes]:
    applied = AppliedAffineTransform(1.08, 7.5, 9.0, -4.0)
    with Image.open(io.BytesIO(asymmetric_png)) as source:
        inspection = source.transform(
            source.size,
            Image.Transform.AFFINE,
            _inverse_affine(
                source.size,
                applied.rotation_degrees,
                applied.scale_factor,
                applied.translation_x,
                applied.translation_y,
            ),
            resample=Image.Resampling.NEAREST,
            fillcolor=(17, 23, 31),
        )
    return asymmetric_png, encode_png(inspection, mode="RGB")


def retained_geometry_objective(
    reference_bytes: bytes, inspection_bytes: bytes
) -> StudyAlignmentObjective:
    reference = _decode_rgb(reference_bytes)
    inspection = _decode_rgb(inspection_bytes)
    reference_silhouette = largest_component_silhouette(reference, chebyshev_threshold=18)
    inspection_silhouette = largest_component_silhouette(inspection, chebyshev_threshold=18)
    retained = alignment_objective(
        reference_silhouette,
        inspection_silhouette,
        silhouette_edges(reference_silhouette),
        silhouette_edges(inspection_silhouette),
    )
    return StudyAlignmentObjective(
        value=retained.value,
        silhouette_xor_rate=retained.silhouette_xor_rate,
        normalized_edge_mae=retained.normalized_edge_mae,
        foreground_iou=retained.foreground_iou,
    )


def test_known_transform_uses_single_inverse() -> None:
    applied = AppliedAffineTransform(
        scale_factor=1.08,
        rotation_degrees=7.5,
        translation_x=9.0,
        translation_y=-4.0,
    )

    correction = derive_correction(applied)

    assert correction.scale == pytest.approx(0.9259259259259258)
    assert correction.rotation_degrees == pytest.approx(-7.5)
    assert correction.dx == pytest.approx(-7.778610169892672)
    assert correction.dy == pytest.approx(4.759736273588616)


@pytest.mark.parametrize("scale_factor", [0.0, -1.0, float("inf"), float("nan")])
def test_correction_rejects_nonpositive_or_nonfinite_scale(scale_factor: float) -> None:
    with pytest.raises(ValueError, match="scale_factor must be finite and positive"):
        derive_correction(AppliedAffineTransform(scale_factor, 0.0, 0.0, 0.0))


def test_output_to_input_coefficients_match_frozen_pillow_convention() -> None:
    correction = CorrectionAffineTransform(
        scale=0.9259259259259258,
        rotation_degrees=-7.5,
        dx=-7.778610169892672,
        dy=4.759736273588616,
    )

    coefficients = pillow_output_to_input_coefficients(_IMAGE_SIZE, correction)

    assert coefficients == AffineCoefficients(
        a=pytest.approx(1.0707604502837154),
        b=pytest.approx(-0.14096828759765573),
        c=pytest.approx(17.91613202746177),
        d=pytest.approx(0.14096828759765573),
        e=pytest.approx(1.0707604502837154),
        f=pytest.approx(-53.56802371053254),
    )
    assert astuple(coefficients) == pytest.approx(
        _inverse_affine(
            _IMAGE_SIZE,
            correction.rotation_degrees,
            correction.scale,
            correction.dx,
            correction.dy,
        )
    )


def test_nearest_normalization_matches_retained_affine_bytes(
    transformed_fixture: tuple[bytes, bytes],
) -> None:
    reference, inspection = transformed_fixture
    applied = AppliedAffineTransform(1.08, 7.5, 9.0, -4.0)
    correction = derive_correction(applied)
    with Image.open(io.BytesIO(inspection)) as source:
        expected_image = source.transform(
            source.size,
            Image.Transform.AFFINE,
            _inverse_affine(
                source.size,
                correction.rotation_degrees,
                correction.scale,
                correction.dx,
                correction.dy,
            ),
            resample=Image.Resampling.NEAREST,
            fillcolor=(17, 23, 31),
        )
    expected = encode_png(expected_image, mode="RGB")

    result = normalize_known_transform(
        reference,
        inspection,
        reference_sha256=sha256_bytes(reference),
        inspection_sha256=sha256_bytes(inspection),
        applied_transform=applied,
        resampling=ResamplingMode.NEAREST,
    )

    assert result.normalized_bytes == expected
    assert result.normalized_sha256 == sha256_bytes(expected)
    assert result.trace.normalized_sha256 == result.normalized_sha256
    assert result.trace.applied is True


def test_asymmetric_fixture_detects_wrong_inverse_order_and_double_inverse(
    transformed_fixture: tuple[bytes, bytes],
) -> None:
    reference, inspection = transformed_fixture
    applied = AppliedAffineTransform(1.08, 7.5, 9.0, -4.0)
    correction = derive_correction(applied)
    result = normalize_known_transform(
        reference,
        inspection,
        reference_sha256=sha256_bytes(reference),
        inspection_sha256=sha256_bytes(inspection),
        applied_transform=applied,
        resampling=ResamplingMode.NEAREST,
    )
    with Image.open(io.BytesIO(inspection)) as source:
        wrong_order = source.transform(
            source.size,
            Image.Transform.AFFINE,
            _inverse_affine(
                source.size,
                correction.rotation_degrees,
                correction.scale,
                -applied.translation_x,
                -applied.translation_y,
            ),
            resample=Image.Resampling.NEAREST,
            fillcolor=(17, 23, 31),
        )
        double_inverse = source.transform(
            source.size,
            Image.Transform.AFFINE,
            _inverse_affine(
                source.size,
                applied.rotation_degrees,
                applied.scale_factor,
                applied.translation_x,
                applied.translation_y,
            ),
            resample=Image.Resampling.NEAREST,
            fillcolor=(17, 23, 31),
        )

    assert result.normalized_bytes != encode_png(wrong_order, mode="RGB")
    assert result.normalized_bytes != encode_png(double_inverse, mode="RGB")


def test_all_modes_share_coefficients_and_border_fill(asymmetric_png: bytes) -> None:
    results = tuple(
        normalize_known_transform(
            asymmetric_png,
            asymmetric_png,
            reference_sha256=sha256_bytes(asymmetric_png),
            inspection_sha256=sha256_bytes(asymmetric_png),
            applied_transform=AppliedAffineTransform(1.0, 0.0, 0.0, 0.0),
            resampling=mode,
        )
        for mode in ResamplingMode
    )

    assert len({result.trace.coefficients for result in results}) == 1
    assert {result.trace.fill_rgb for result in results} == {(17, 23, 31)}
    assert {result.normalized_bytes for result in results} == {asymmetric_png}
    assert all(result.trace.applied is False for result in results)


def test_normalization_rejects_reference_hash_mismatch(asymmetric_png: bytes) -> None:
    with pytest.raises(ValueError, match="reference SHA-256 does not match bytes"):
        normalize_known_transform(
            asymmetric_png,
            asymmetric_png,
            reference_sha256="0" * 64,
            inspection_sha256=sha256_bytes(asymmetric_png),
            applied_transform=AppliedAffineTransform(1.0, 0.0, 0.0, 0.0),
            resampling=ResamplingMode.NEAREST,
        )


def test_normalization_rejects_inspection_hash_mismatch(asymmetric_png: bytes) -> None:
    with pytest.raises(ValueError, match="inspection SHA-256 does not match bytes"):
        normalize_known_transform(
            asymmetric_png,
            asymmetric_png,
            reference_sha256=sha256_bytes(asymmetric_png),
            inspection_sha256="f" * 64,
            applied_transform=AppliedAffineTransform(1.0, 0.0, 0.0, 0.0),
            resampling=ResamplingMode.NEAREST,
        )


def test_border_fill_counts_each_corner_once() -> None:
    pixels = np.zeros((384, 512, 3), dtype=np.uint8)
    border_coordinates = [
        *((0, x) for x in range(512)),
        *((383, x) for x in range(512)),
        *((y, 0) for y in range(1, 383)),
        *((y, 511) for y in range(1, 383)),
    ]
    for index, (y, x) in enumerate(border_coordinates):
        pixels[y, x] = 0 if index < 894 else 200
    pixels[100:280, 120:390] = 120
    payload = encode_png(Image.fromarray(pixels, mode="RGB"), mode="RGB")

    result = normalize_known_transform(
        payload,
        payload,
        reference_sha256=sha256_bytes(payload),
        inspection_sha256=sha256_bytes(payload),
        applied_transform=AppliedAffineTransform(1.0, 0.0, 2.0, 0.0),
        resampling=ResamplingMode.NEAREST,
    )

    assert result.trace.fill_rgb == (100, 100, 100)


@pytest.mark.parametrize(
    "kind", ["oversized", "wrong_size", "wrong_mode", "metadata", "frames", "noncanonical"]
)
def test_normalization_rejects_noncanonical_inputs(kind: str, asymmetric_png: bytes) -> None:
    invalid = _invalid_png(kind, asymmetric_png)

    with pytest.raises(ValueError, match="canonical one-frame 512x384 RGB PNG"):
        normalize_known_transform(
            invalid,
            asymmetric_png,
            reference_sha256=sha256_bytes(invalid),
            inspection_sha256=sha256_bytes(asymmetric_png),
            applied_transform=AppliedAffineTransform(1.0, 0.0, 0.0, 0.0),
            resampling=ResamplingMode.NEAREST,
        )


def test_reference_boundary_band_matches_exact_three_pixel_rule() -> None:
    pixels = np.full((384, 512, 3), 240, dtype=np.uint8)
    pixels[40:340, 80:430] = 20
    reference = encode_png(Image.fromarray(pixels, mode="RGB"), mode="RGB")

    band = reference_boundary_band(reference)
    mask = np.frombuffer(band.band_mask_bytes, dtype=np.bool_).reshape((384, 512))

    assert band.radius == 3
    assert band.foreground_positive_pixels == 105_000
    assert band.boundary_positive_pixels == 1_296
    assert band.band_positive_pixels == 9_072
    assert np.count_nonzero(mask) == 9_072
    assert mask[37, 77]
    assert mask[342, 432]
    assert not mask[36, 76]
    assert not mask[44, 84]
    assert band.band_mask_sha256 == sha256(band.band_mask_bytes).hexdigest()


def test_boundary_uses_outside_image_neighbors_and_clips_dilation() -> None:
    pixels = np.full((384, 512, 3), 240, dtype=np.uint8)
    pixels[:10, :10] = 20
    reference = encode_png(Image.fromarray(pixels, mode="RGB"), mode="RGB")

    band = reference_boundary_band(reference)
    mask = np.frombuffer(band.band_mask_bytes, dtype=np.bool_).reshape((384, 512))

    assert band.foreground_positive_pixels == 100
    assert band.boundary_positive_pixels == 36
    assert band.band_positive_pixels == 165
    assert mask[0, 5]
    assert mask[12, 12]
    assert not mask[13, 13]
    assert not mask[4, 4]


def test_equal_area_component_tie_uses_topmost_then_leftmost() -> None:
    pixels = np.full((384, 512, 3), 240, dtype=np.uint8)
    pixels[20:40, 80:100] = 20
    pixels[60:80, 10:30] = 20
    reference = encode_png(Image.fromarray(pixels, mode="RGB"), mode="RGB")

    band = reference_boundary_band(reference)
    mask = np.frombuffer(band.band_mask_bytes, dtype=np.bool_).reshape((384, 512))

    assert band.foreground_positive_pixels == 400
    assert mask[20, 80]
    assert not mask[60, 10]


def test_reference_boundary_rejects_missing_foreground() -> None:
    reference = encode_png(Image.new("RGB", _IMAGE_SIZE, (31, 37, 41)), mode="RGB")

    with pytest.raises(ValueError, match="foreground component"):
        reference_boundary_band(reference)


def test_alignment_components_match_frozen_geometry_on_fixture(
    transformed_fixture: tuple[bytes, bytes],
) -> None:
    reference, inspection = transformed_fixture

    study = measure_alignment(reference, inspection)
    retained = retained_geometry_objective(reference, inspection)

    assert study.as_record() == retained.as_record()


def test_normalization_trace_records_complete_before_and_after_objectives(
    transformed_fixture: tuple[bytes, bytes],
) -> None:
    reference, inspection = transformed_fixture
    result = normalize_known_transform(
        reference,
        inspection,
        reference_sha256=sha256_bytes(reference),
        inspection_sha256=sha256_bytes(inspection),
        applied_transform=AppliedAffineTransform(1.08, 7.5, 9.0, -4.0),
        resampling=ResamplingMode.NEAREST,
    )

    assert result.trace.objective_before.as_record() == measure_alignment(
        reference, inspection
    ).as_record()
    assert result.trace.objective_after.as_record() == measure_alignment(
        reference, result.normalized_bytes
    ).as_record()
    assert result.trace.objective_after.value < result.trace.objective_before.value


def _decode_rgb(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8).copy()


def _invalid_png(kind: str, canonical: bytes) -> bytes:
    if kind == "oversized":
        return canonical + b"x" * (8 * 1024 * 1024)
    if kind == "wrong_size":
        return encode_png(Image.new("RGB", (511, 384)), mode="RGB")
    if kind == "wrong_mode":
        return encode_png(Image.new("L", _IMAGE_SIZE), mode="L")
    buffer = io.BytesIO()
    if kind == "metadata":
        info = PngImagePlugin.PngInfo()
        info.add_text("source", "test")
        Image.new("RGB", _IMAGE_SIZE).save(buffer, format="PNG", pnginfo=info)
    elif kind == "frames":
        Image.new("RGB", _IMAGE_SIZE).save(
            buffer,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", _IMAGE_SIZE, (1, 2, 3))],
        )
    elif kind == "noncanonical":
        Image.new("RGB", _IMAGE_SIZE).save(buffer, format="PNG")
    else:
        raise AssertionError(f"unknown invalid fixture: {kind}")
    return buffer.getvalue()
