from __future__ import annotations

import inspect
from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.geometry import (
    AlignmentStatus,
    apply_correction,
    geometry_config_from_document,
)
from manufacturing_vision_studio.e1.geometry_search import (
    _evaluate_coarse_grid,
    align_coarse_to_fine,
)
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
    config = _config()
    assert (
        len(config.coarse_rotations)
        * len(config.coarse_scales)
        * len(config.coarse_translation_offsets) ** 2
        == 1_575
    )
    assert (
        config.coarse_candidate_cap * 128 * 96
        + config.refine_candidate_cap * 512 * 384
        == config.candidate_b_pixel_cap
        == 35_278_848
    )
    reference = _plate()
    inspection = apply_correction(
        reference, rotation=0.8, scale=1.01, dx=2, dy=-2
    )
    result = align_coarse_to_fine(reference, inspection, config)
    assert result.trace.coarse_candidates_evaluated > 0
    assert result.trace.refine_candidates_evaluated > 0
    assert result.trace.coarse_candidates_evaluated <= 1_575
    assert result.trace.refine_candidates_evaluated <= 81
    assert result.trace.candidate_pixels_evaluated <= 35_278_848
    assert result.trace.search_size == (128, 96)
    assert result.trace.candidates_evaluated == (
        result.trace.coarse_candidates_evaluated
        + result.trace.refine_candidates_evaluated
    )
    assert result.trace.candidate_pixels_evaluated == (
        result.trace.coarse_candidates_evaluated * 128 * 96
        + result.trace.refine_candidates_evaluated * 512 * 384
    )


def test_candidate_b_divides_full_resolution_translation_by_four_on_coarse_grid() -> None:
    inspection = np.zeros((96, 128), dtype=np.bool_)
    inspection[30:50, 40:60] = True
    inspection[31:35, 60:64] = True
    reference = np.zeros_like(inspection)
    reference[:-1, 1:] = inspection[1:, :-1]
    config = replace(
        _config(),
        coarse_rotations=(0.0,),
        coarse_scales=(1.0,),
        coarse_translation_offsets=(0,),
    )
    candidates = _evaluate_coarse_grid(
        reference,
        inspection,
        initial_dx=4.0,
        initial_dy=-4.0,
        config=config,
    )

    assert len(candidates) == 1
    assert candidates[0].dx == 4.0
    assert candidates[0].dy == -4.0
    assert candidates[0].objective.value == 0.0


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
