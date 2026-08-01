from __future__ import annotations

import inspect
import math
from io import BytesIO

import numpy as np
import pytest
from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.geometry import (
    AlignmentCandidate,
    AlignmentObjective,
    AlignmentResult,
    AlignmentStatus,
    GeometryConfig,
    _component_geometry,
    _resolve_candidates,
    align_largest_component,
    alignment_objective,
    apply_correction,
    geometry_config_from_document,
    largest_component_silhouette,
)
from manufacturing_vision_studio.e1.geometry_search import align_coarse_to_fine
from manufacturing_vision_studio.e1.model import (
    filter_structural_residue,
    localized_anomaly_score,
)
from manufacturing_vision_studio.e1.policy import E1InferencePolicy, classify_score
from manufacturing_vision_studio.e1.protocol import load_e1_protocol
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol


def _png(image: Image.Image) -> bytes:
    return encode_png(image, mode="RGB")


def _plate(*, scale: float = 1.0, dx: int = 0, dy: int = 0) -> bytes:
    image = Image.new("RGB", (512, 384), (20, 30, 40))
    draw = ImageDraw.Draw(image)
    width = round(240 * scale)
    height = round(160 * scale)
    cx, cy = 256 + dx, 192 + dy
    draw.rectangle(
        (cx - width // 2, cy - height // 2, cx + width // 2, cy + height // 2),
        fill=(180, 170, 160),
    )
    draw.ellipse((cx - 75, cy - 25, cx - 35, cy + 15), fill=(20, 30, 40))
    return _png(image)


def _config() -> GeometryConfig:
    return geometry_config_from_document(load_e1_v2_protocol().document)


def test_silhouette_uses_only_largest_component() -> None:
    image = np.full((384, 512, 3), (20, 30, 40), dtype=np.uint8)
    image[100:280, 120:390] = (180, 170, 160)
    image[10:30, 10:30] = (220, 20, 20)
    silhouette = largest_component_silhouette(image, chebyshev_threshold=18)
    assert silhouette[190, 250]
    assert not silhouette[20, 20]


def test_equal_area_component_tie_uses_topmost_then_leftmost() -> None:
    image = np.zeros((384, 512, 3), dtype=np.uint8)
    image[20:40, 80:100] = 255
    image[60:80, 10:30] = 255
    silhouette = largest_component_silhouette(image, chebyshev_threshold=18)
    assert silhouette[30, 90]
    assert not silhouette[70, 20]


def test_alignment_objective_uses_preregistered_weights_and_full_canvas() -> None:
    reference = np.zeros((4, 4), dtype=np.bool_)
    candidate = reference.copy()
    candidate[0, 0] = True
    reference_edges = np.zeros_like(reference)
    candidate_edges = candidate.copy()
    objective = alignment_objective(reference, candidate, reference_edges, candidate_edges)
    assert objective.silhouette_xor_rate == pytest.approx(1 / 16)
    assert objective.normalized_edge_mae == pytest.approx(1 / 16)
    assert objective.value == pytest.approx(
        0.70 * objective.silhouette_xor_rate + 0.30 * objective.normalized_edge_mae
    )


def test_transform_translation_sign_and_border_fill_are_canonical() -> None:
    image = Image.new("RGB", (512, 384), (3, 5, 7))
    image.putpixel((100, 100), (251, 31, 17))
    transformed = apply_correction(_png(image), rotation=0.0, scale=1.0, dx=2, dy=-3)
    with Image.open(BytesIO(transformed)) as decoded:
        pixels = np.asarray(decoded)
        assert decoded.mode == "RGB"
        assert decoded.size == (512, 384)
        assert tuple(pixels[97, 102]) == (251, 31, 17)
        assert tuple(pixels[383, 0]) == (3, 5, 7)
    assert transformed == apply_correction(_png(image), rotation=0.0, scale=1.0, dx=2, dy=-3)


def test_asymmetric_rotation_scale_translation_matches_fixed_golden_hash() -> None:
    image = Image.new("RGB", (512, 384), (3, 5, 7))
    draw = ImageDraw.Draw(image)
    draw.polygon(((61, 47), (146, 52), (139, 119), (79, 103)), fill=(241, 31, 17))
    draw.rectangle((303, 211, 337, 265), fill=(19, 227, 83))
    draw.ellipse((410, 66, 435, 101), fill=(71, 89, 251))
    image.putpixel((252, 190), (255, 255, 0))

    transformed = apply_correction(
        _png(image), rotation=1.0, scale=1.01, dx=2, dy=-3
    )

    assert sha256_bytes(transformed) == (
        "4e20f17fb053e70eb44c254f7393e9ade6d39048db7f00b61692ad1d135141d7"
    )


def test_geometry_config_is_strictly_parsed_from_protocol_document() -> None:
    document = load_e1_v2_protocol().document
    config = geometry_config_from_document(document)
    assert config.image_size == (512, 384)
    assert config.correction_scale_bounds == pytest.approx((1 / 1.02, 1 / 0.98))
    document["geometry"]["foreground_threshold"] = 19
    with pytest.raises(ValueError, match="foreground_threshold"):
        geometry_config_from_document(document)


def test_runtime_alignment_signature_has_no_truth_or_case_inputs() -> None:
    assert tuple(inspect.signature(align_largest_component).parameters) == (
        "reference_bytes",
        "inspection_bytes",
        "config",
    )
    forbidden = {"case", "seed", "expected", "feature", "defect", "truth", "mask", "nuisance"}
    assert forbidden.isdisjoint(inspect.signature(align_largest_component).parameters)


@pytest.mark.parametrize(
    "observed_scale",
    [0.98, 0.985, 0.99, 1.005, 1.01, 1.015, 1.02],
)
def test_candidate_a_reduces_scale_objective(observed_scale: float) -> None:
    reference = _plate()
    inspection = apply_correction(
        reference, rotation=0.0, scale=observed_scale, dx=0, dy=0
    )
    result = align_largest_component(reference, inspection, _config())
    assert result.status is AlignmentStatus.APPLIED
    assert result.trace.candidates_evaluated <= 225
    assert result.trace.candidate_pixels_evaluated <= 44_236_800
    assert result.trace.objective_after < result.trace.objective_before
    assert 1 / 1.02 <= result.trace.correction_scale <= 1 / 0.98


def test_candidate_a_is_byte_deterministic() -> None:
    first = align_largest_component(_plate(), _plate(scale=1.015, dx=2), _config())
    second = align_largest_component(_plate(), _plate(scale=1.015, dx=2), _config())
    assert first == second


def test_identity_is_non_abstaining_and_preserves_original_bytes() -> None:
    payload = _plate()
    result = align_largest_component(payload, payload, _config())
    assert result.status is AlignmentStatus.IDENTITY
    assert result.trace.status_reason == "IDENTITY_BASELINE"
    assert result.trace.abstention_reason is None
    assert result.inspection_bytes == payload


def test_identity_remeasures_post_shift_on_preserved_original_pixels() -> None:
    generator = E1V2Generator()
    plan = next(
        plan
        for plan in generator.plan_cases(EvaluationScope.DEVELOPMENT)
        if plan.case_id == "e1-v2-development-defect-002"
    )
    case = generator.generate_case(plan)
    result = align_largest_component(case.reference_bytes, case.inspection_bytes, _config())
    reference_mask = largest_component_silhouette(
        _decode_rgb(case.reference_bytes), chebyshev_threshold=18
    )
    inspection_mask = largest_component_silhouette(
        _decode_rgb(case.inspection_bytes), chebyshev_threshold=18
    )
    reference_y, reference_x = np.nonzero(reference_mask)
    inspection_y, inspection_x = np.nonzero(inspection_mask)

    assert result.status is AlignmentStatus.IDENTITY
    assert result.trace.post_normalization_shift_x == pytest.approx(
        np.median(reference_x) - np.median(inspection_x)
    )
    assert result.trace.post_normalization_shift_y == pytest.approx(
        np.median(reference_y) - np.median(inspection_y)
    )


def test_candidate_a_rejects_initial_translation_outside_bound() -> None:
    inspection = _plate(dx=13)
    result = align_largest_component(_plate(), inspection, _config())
    assert result.status is AlignmentStatus.ABSTAIN
    assert result.trace.abstention_reason == "TRANSLATION_OUT_OF_RANGE"
    assert result.inspection_bytes == inspection


def test_candidate_a_accepts_translation_at_each_bound() -> None:
    for dx, dy in ((12, 0), (-12, 0), (0, 12), (0, -12)):
        result = align_largest_component(_plate(), _plate(dx=dx, dy=dy), _config())
        assert result.status is not AlignmentStatus.ABSTAIN
        assert abs(result.trace.pre_normalization_shift_x) <= 12
        assert abs(result.trace.pre_normalization_shift_y) <= 12


def test_tiny_foreground_abstains_fail_closed() -> None:
    image = Image.new("RGB", (512, 384), (0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 20, 25, 25), fill=(255, 255, 255))
    inspection = _png(image)
    result = align_largest_component(inspection, inspection, _config())
    assert result.status is AlignmentStatus.ABSTAIN
    assert result.trace.abstention_reason == "INSUFFICIENT_FOREGROUND"
    assert result.inspection_bytes == inspection


def test_malformed_or_noncanonical_input_fails_as_insufficient_foreground() -> None:
    result = align_largest_component(b"not-png", _plate(), _config())
    assert result.status is AlignmentStatus.ABSTAIN
    assert result.trace.abstention_reason == "INSUFFICIENT_FOREGROUND"


def test_low_eigengap_falls_back_to_zero_rotation() -> None:
    image = Image.new("RGB", (512, 384), (10, 20, 30))
    ImageDraw.Draw(image).ellipse((156, 92, 356, 292), fill=(180, 170, 160))
    payload = _png(image)
    result = align_largest_component(payload, payload, _config())
    assert result.trace.observed_rotation_degrees == 0.0
    assert result.trace.correction_rotation_degrees == 0.0


def test_scale_bound_alone_is_serialized_without_boundary_abstention() -> None:
    result = align_largest_component(_plate(), _plate(scale=0.98), _config())
    assert result.status is AlignmentStatus.APPLIED
    assert result.trace.at_scale_bound
    assert not result.trace.at_rotation_bound
    assert result.trace.as_record()["at_scale_bound"] is True


def test_simultaneous_rotation_and_scale_bounds_abstain() -> None:
    reference = _plate()
    inspection = apply_correction(
        reference, rotation=1.5, scale=1.02, dx=0, dy=0
    )
    result = align_largest_component(reference, inspection, _config())
    assert result.status is AlignmentStatus.ABSTAIN
    assert result.trace.abstention_reason == "BOUNDARY_OPTIMUM"
    assert result.trace.at_rotation_bound
    assert result.trace.at_scale_bound
    assert result.inspection_bytes == inspection


@pytest.mark.parametrize(
    ("confidence_case", "best_value", "expected_status"),
    [
        (
            "below",
            math.nextafter(0.5347946707193266, math.inf),
            AlignmentStatus.ABSTAIN,
        ),
        ("exact", 0.5347946707193266, AlignmentStatus.APPLIED),
        (
            "above",
            math.nextafter(0.5347946707193266, -math.inf),
            AlignmentStatus.APPLIED,
        ),
    ],
)
def test_relative_confidence_gap_boundary_uses_distinct_rendered_runner_up(
    confidence_case: str,
    best_value: float,
    expected_status: AlignmentStatus,
) -> None:
    reference_payload = _plate()
    raw_best = _decode_rgb(reference_payload).tobytes()
    raw_second = bytearray(raw_best)
    raw_second[0] ^= 1
    reference_mask = largest_component_silhouette(
        _decode_rgb(reference_payload), chebyshev_threshold=18
    )
    reference_geometry = _component_geometry(reference_mask, _config())
    assert reference_geometry is not None
    second_value = 0.5401966370902289
    candidates = [
        AlignmentCandidate(
            0.0,
            1.0,
            0.0,
            0.0,
            AlignmentObjective(best_value, best_value, 0.0, 1.0),
            raw_best,
            sha256_bytes(raw_best),
        ),
        AlignmentCandidate(
            0.0,
            1.001,
            0.0,
            0.0,
            AlignmentObjective(second_value, second_value, 0.0, 1.0),
            bytes(raw_second),
            sha256_bytes(bytes(raw_second)),
        ),
    ]
    assert candidates[0].inspection_sha256 != candidates[1].inspection_sha256
    expected_gap = (second_value - best_value) / second_value
    if confidence_case == "below":
        assert expected_gap < 0.01
    elif confidence_case == "exact":
        assert expected_gap == 0.01
    else:
        assert expected_gap > 0.01

    result = _resolve_candidates(
        reference_payload,
        candidates,
        AlignmentObjective(1.0, 1.0, 0.0, 0.0),
        _config(),
        pre_shift=(0.0, 0.0),
        observed=(0.0, 1.0),
        counts=(2, 0, 0, 2 * 512 * 384),
        search_size=None,
        reference_geometry=reference_geometry,
        identity_post_shift=(0.0, 0.0),
    )

    assert result.status is expected_status
    assert result.trace.confidence_gap == expected_gap
    if expected_status is AlignmentStatus.ABSTAIN:
        assert result.trace.abstention_reason == "AMBIGUOUS_ALIGNMENT"
        assert result.inspection_bytes == reference_payload
    else:
        assert result.trace.abstention_reason is None


def test_post_normalization_shift_is_remeasured_from_corrected_pixels() -> None:
    reference = _plate()
    result = align_largest_component(reference, _plate(scale=0.98, dx=1, dy=1), _config())
    reference_mask = largest_component_silhouette(
        _decode_rgb(reference), chebyshev_threshold=18
    )
    corrected_mask = largest_component_silhouette(
        _decode_rgb(result.inspection_bytes), chebyshev_threshold=18
    )
    reference_y, reference_x = np.nonzero(reference_mask)
    corrected_y, corrected_x = np.nonzero(corrected_mask)
    assert result.trace.post_normalization_shift_x == pytest.approx(
        np.median(reference_x) - np.median(corrected_x)
    )
    assert result.trace.post_normalization_shift_y == pytest.approx(
        np.median(reference_y) - np.median(corrected_y)
    )


def test_development_diagnostic_defects_are_preserved_after_image_only_alignment() -> None:
    generator = E1V2Generator()
    downstream = E1InferencePolicy(load_e1_protocol())
    plans = generator.plan_cases(EvaluationScope.DEVELOPMENT)
    # Fixed medium/high scratch, stain, edge-chip, burr, blocked-hole, and
    # hole-deviation diagnostics spanning both revisions and all views.
    ordinals = (6, 1, 2, 21, 4, 5)
    cases = [
        generator.generate_case(
            next(plan for plan in plans if plan.case_id.endswith(f"defect-{ordinal:03d}"))
        )
        for ordinal in ordinals
    ]
    candidate_metrics: list[tuple[list[float], list[float], int]] = []
    for align in (align_largest_component, align_coarse_to_fine):
        recall_drops: list[float] = []
        dice_drops: list[float] = []
        classified = 0
        for case in cases:
            result = align(case.reference_bytes, case.inspection_bytes, _config())
            # Authoritative truth is accessed only after inference returns.
            truth = _decode_mask(case.authoritative_mask_bytes)
            reference = _decode_rgb(case.reference_bytes)
            identity = _decode_rgb(case.inspection_bytes)
            corrected = _decode_rgb(result.inspection_bytes)
            identity_difference = np.any(reference != identity, axis=2)
            corrected_difference = np.any(reference != corrected, axis=2)
            identity_recall = _recall(identity_difference, truth)
            corrected_recall = _recall(corrected_difference, truth)
            recall_drops.append(identity_recall - corrected_recall)
            dice_drops.append(
                _dice(identity_difference, truth) - _dice(corrected_difference, truth)
            )
            if result.status is not AlignmentStatus.ABSTAIN:
                classified += (
                    _classify_with_downstream_model(
                        downstream,
                        case.reference_bytes,
                        result,
                    )
                    == "ANOMALY"
                )
        candidate_metrics.append((recall_drops, dice_drops, classified))
    for recall_drops, dice_drops, classified in candidate_metrics:
        assert max(recall_drops) <= 0.05
        assert float(np.median(dice_drops)) <= 0.01
        assert classified / len(cases) >= 0.90


def _decode_rgb(payload: bytes) -> np.ndarray:
    with Image.open(BytesIO(payload)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _decode_mask(payload: bytes) -> np.ndarray:
    with Image.open(BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8) > 0


def _recall(predicted: np.ndarray, truth: np.ndarray) -> float:
    return float(np.count_nonzero(predicted & truth) / np.count_nonzero(truth))


def _dice(predicted: np.ndarray, truth: np.ndarray) -> float:
    denominator = np.count_nonzero(predicted) + np.count_nonzero(truth)
    return float(2 * np.count_nonzero(predicted & truth) / denominator)


def _classify_with_downstream_model(
    policy: E1InferencePolicy,
    reference_bytes: bytes,
    alignment_result: AlignmentResult,
) -> str:
    inspection_bytes = alignment_result.inspection_bytes
    reference = policy.ingestor.ingest_bytes(
        reference_bytes,
        filename="diagnostic-reference.png",
        declared_media_type="image/png",
    )
    inspection = policy.ingestor.ingest_bytes(
        inspection_bytes,
        filename="diagnostic-inspection.png",
        declared_media_type="image/png",
    )
    model_result = policy.model.inspect(reference, inspection)
    contract = policy.evaluation_configuration["mask_postprocessing"]
    postprocessing = filter_structural_residue(
        model_result.mask_bytes,
        reference_bytes=reference_bytes,
        inspection_bytes=inspection_bytes,
        normalization_applied=alignment_result.status is AlignmentStatus.APPLIED,
        long_thin_min_major_px=int(contract["long_thin_min_major_px"]),
        long_thin_max_minor_px=int(contract["long_thin_max_minor_px"]),
        affine_neutral_min_pixels=int(contract["affine_neutral_min_pixels"]),
        affine_neutral_max_abs_luminance_delta=float(
            contract["affine_neutral_max_abs_luminance_delta"]
        ),
        boundary_horizontal_min_width_px=int(contract["boundary_horizontal_min_width_px"]),
        boundary_horizontal_max_height_px=int(contract["boundary_horizontal_max_height_px"]),
        top_boundary_max_y_px=int(contract["top_boundary_max_y_px"]),
        bottom_boundary_min_y_px=int(contract["bottom_boundary_min_y_px"]),
        dark_fixture_max_luminance_delta=float(contract["dark_fixture_max_luminance_delta"]),
    )
    scoring = policy.evaluation_configuration["scoring"]
    score = localized_anomaly_score(
        postprocessing.mask_bytes,
        window_size_px=int(scoring["local_window_size_px"]),
        minimum_component_pixels=int(scoring["minimum_connected_component_pixels"]),
    )
    return classify_score(score, policy.image_threshold)
