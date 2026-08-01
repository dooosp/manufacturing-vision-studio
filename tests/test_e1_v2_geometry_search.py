from __future__ import annotations

import inspect

from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.geometry import AlignmentStatus, geometry_config_from_document
from manufacturing_vision_studio.e1.geometry_search import align_coarse_to_fine
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol


def _plate() -> bytes:
    image = Image.new("RGB", (512, 384), (20, 30, 40))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((135, 105, 380, 275), radius=19, fill=(180, 170, 160))
    draw.ellipse((180, 155, 225, 200), fill=(20, 30, 40))
    draw.rectangle((290, 165, 350, 190), fill=(20, 30, 40))
    return encode_png(image, mode="RGB")


def _config():
    return geometry_config_from_document(load_e1_v2_protocol().document)


def test_candidate_b_obeys_search_caps_and_grid() -> None:
    payload = _plate()
    result = align_coarse_to_fine(payload, payload, _config())
    assert result.status is AlignmentStatus.IDENTITY
    assert result.trace.coarse_candidates_evaluated <= 1575
    assert result.trace.refine_candidates_evaluated <= 81
    assert result.trace.candidate_pixels_evaluated <= 35_278_848
    assert result.trace.search_size == (128, 96)


def test_candidate_b_reduces_combined_scale_rotation_translation() -> None:
    reference = _plate()
    inspection = __import__(
        "manufacturing_vision_studio.e1.geometry", fromlist=["apply_correction"]
    ).apply_correction(reference, rotation=1.0, scale=1.015, dx=2, dy=-2)
    result = align_coarse_to_fine(reference, inspection, _config())
    assert result.status is AlignmentStatus.APPLIED
    assert result.trace.objective_after < result.trace.objective_before
    assert abs(result.trace.correction_rotation_degrees) <= 1.5
    assert 1 / 1.02 <= result.trace.correction_scale <= 1 / 0.98
    assert abs(result.trace.correction_dx) <= 12
    assert abs(result.trace.correction_dy) <= 12


def test_candidate_b_is_byte_deterministic_and_leakage_free() -> None:
    payload = _plate()
    first = align_coarse_to_fine(payload, payload, _config())
    second = align_coarse_to_fine(payload, payload, _config())
    assert first == second
    assert tuple(inspect.signature(align_coarse_to_fine).parameters) == (
        "reference_bytes",
        "inspection_bytes",
        "config",
    )
