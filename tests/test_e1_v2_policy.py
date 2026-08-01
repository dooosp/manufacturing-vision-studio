from __future__ import annotations

import inspect
from dataclasses import fields
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.diagnostics_v2 import (
    _render_diagnostic,
    build_scale_diagnostic_matrix,
)
from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.policy_v2 import (
    E1V2InferenceInput,
    E1V2InferencePolicy,
)
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol
from manufacturing_vision_studio.e1.registration_v2 import register_inspection_for_v2
from manufacturing_vision_studio.model import DeterministicDifferenceModel


def _generated(case_id: str):
    generator = E1V2Generator()
    plan = next(
        plan
        for plan in generator.plan_cases(EvaluationScope.DEVELOPMENT)
        if plan.case_id == case_id
    )
    return generator.generate_case(plan)


def test_runtime_input_has_no_diagnostic_truth_field() -> None:
    signature = inspect.signature(E1V2InferencePolicy.inspect)
    assert tuple(signature.parameters) == ("self", "inference")
    assert {field.name for field in fields(E1V2InferenceInput)} == {
        "reference_bytes",
        "inspection_bytes",
        "reference_sha256",
        "inspection_sha256",
        "part_id",
        "cad_revision",
        "view_id",
    }


def test_projection_validates_hashes_and_canonical_rgb_bytes() -> None:
    generated = _generated("e1-v2-development-clean-000")
    inference = E1V2InferenceInput.from_generated(generated)
    assert inference.reference_sha256 == sha256_bytes(inference.reference_bytes)
    assert inference.inspection_sha256 == sha256_bytes(inference.inspection_bytes)
    mutated = object.__new__(type(generated))
    for field in fields(generated):
        object.__setattr__(mutated, field.name, getattr(generated, field.name))
    object.__setattr__(mutated, "reference_sha256", "0" * 64)
    with pytest.raises(ValueError, match="reference"):
        E1V2InferenceInput.from_generated(mutated)


def test_registration_helper_pins_core_positive_shift_sign_and_crop() -> None:
    image = Image.new("RGB", (512, 384), (3, 5, 7))
    image.putpixel((10, 20), (251, 31, 17))
    payload = encode_png(image, mode="RGB")
    registered = register_inspection_for_v2(payload, shift_x=2, shift_y=-3)
    with Image.open(BytesIO(registered)) as decoded:
        pixels = np.asarray(decoded)
    assert tuple(pixels[23, 8]) == (251, 31, 17)
    assert tuple(pixels[0, 511]) == (3, 5, 7)


def test_identity_case_continues_to_model_and_maps_persisted_final_mask() -> None:
    inference = E1V2InferenceInput.from_generated(_generated("e1-v2-development-clean-000"))
    result = E1V2InferencePolicy(load_e1_v2_protocol(), candidate_id="A").inspect(inference)
    assert result.actual_outcome == "NORMAL"
    assert result.predicted_mask_bytes is not None
    assert result.predicted_mask_sha256 == sha256_bytes(result.predicted_mask_bytes)
    assert result.feature_mapping is not None
    assert result.feature_mapping.final_mask_sha256 == result.predicted_mask_sha256
    assert result.geometry_trace.final_model_registration == result.model_registration
    assert "comparison_shift" not in result.geometry_trace.as_record()
    assert result.postprocessing_inspection_sha256 == result.registered_inspection_sha256


def test_geometry_value_error_becomes_fail_closed_abstain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import manufacturing_vision_studio.e1.policy_v2 as policy_module

    def fail(*_args: object, **_kwargs: object) -> None:
        raise ValueError("bad geometry")

    monkeypatch.setattr(policy_module, "align_largest_component", fail)
    inference = E1V2InferenceInput.from_generated(_generated("e1-v2-development-clean-000"))
    result = E1V2InferencePolicy(load_e1_v2_protocol(), candidate_id="A").inspect(inference)
    assert result.actual_outcome == "ABSTAIN"
    assert result.abstention_reason == "GEOMETRY_INVALID"
    assert result.geometry_trace.alignment.normalization_status == "ABSTAIN"
    assert result.geometry_trace.alignment.status_reason == "GEOMETRY_INVALID"
    assert result.geometry_trace.alignment.abstention_reason == "GEOMETRY_INVALID"
    assert result.feature_mapping is None
    assert result.predicted_mask_bytes is None


def test_policy_passes_exact_core_registration_to_filter_and_final_mask_to_mapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import manufacturing_vision_studio.e1.policy_v2 as policy_module

    protocol = load_e1_v2_protocol()
    plan = build_scale_diagnostic_matrix(protocol)[48]
    inference, _truth, _truth_bytes = _render_diagnostic(plan, protocol)
    model = DeterministicDifferenceModel()
    captured_core_registered: list[bytes] = []
    captured_postfilter_inspection: list[bytes] = []
    captured_mapper_mask: list[bytes] = []
    real_model_inspect = model.inspect
    real_filter = policy_module.filter_structural_residue
    real_mapper = policy_module.map_final_mask

    def recording_model(*args, **kwargs):
        model_result = real_model_inspect(*args, **kwargs)
        captured_core_registered.append(model_result.registered_bytes)
        return model_result

    def recording_filter(mask_bytes, **kwargs):
        captured_postfilter_inspection.append(kwargs["inspection_bytes"])
        return real_filter(mask_bytes, **kwargs)

    def recording_mapper(mask_bytes, ownership, **kwargs):
        captured_mapper_mask.append(mask_bytes)
        return real_mapper(mask_bytes, ownership, **kwargs)

    monkeypatch.setattr(model, "inspect", recording_model)
    monkeypatch.setattr(policy_module, "filter_structural_residue", recording_filter)
    monkeypatch.setattr(policy_module, "map_final_mask", recording_mapper)
    result = E1V2InferencePolicy(protocol, candidate_id="A", model=model).inspect(inference)

    assert result.model_registration is not None
    assert (result.model_registration.dx, result.model_registration.dy) != (0, 0)
    assert result.geometry_trace.pre_normalization_shift != (
        result.geometry_trace.post_normalization_shift
    )
    assert captured_postfilter_inspection == captured_core_registered
    assert sha256_bytes(captured_core_registered[0]) == result.registered_inspection_sha256
    assert captured_mapper_mask == [result.predicted_mask_bytes]
    assert sha256_bytes(captured_mapper_mask[0]) == result.predicted_mask_sha256
    assert result.feature_mapping is not None
    assert result.feature_mapping.final_mask_sha256 == result.predicted_mask_sha256


def test_v2_locked_threshold_is_inclusive() -> None:
    from manufacturing_vision_studio.e1.policy_v2 import classify_v2_score

    assert classify_v2_score(0.0025, 0.0025) == "ANOMALY"
    assert classify_v2_score(0.00249999, 0.0025) == "NORMAL"
