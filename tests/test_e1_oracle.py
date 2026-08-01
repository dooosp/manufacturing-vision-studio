from __future__ import annotations

import inspect
import io
from dataclasses import replace

import pytest
from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1 import (
    CaseGroup,
    E1Generator,
    validate_authoritative_mask,
    validate_authoritative_truth,
    validate_generated_case,
)
from manufacturing_vision_studio.errors import UnsafeInputError


@pytest.fixture(scope="module")
def generated_cases() -> tuple[E1Generator, object, object]:
    generator = E1Generator()
    full = generator.plan_cases("full")
    positive_plan = next(plan for plan in full if plan.group is CaseGroup.DEFECT)
    negative_plan = next(plan for plan in full if plan.group is CaseGroup.CLEAN)
    return (
        generator,
        generator.generate_case(positive_plan),
        generator.generate_case(negative_plan),
    )


def test_oracle_signature_has_no_prediction_or_model_input() -> None:
    parameters = inspect.signature(validate_authoritative_truth).parameters
    assert tuple(parameters) == (
        "plan",
        "mask_png",
        "declared_sha256",
        "image_size",
        "feature_regions",
    )
    assert all("prediction" not in name and "model" not in name for name in parameters)


def test_generated_positive_and_negative_truth_validate(generated_cases: tuple) -> None:
    generator, positive, negative = generated_cases

    positive_validation = validate_generated_case(positive, generator.protocol)
    negative_validation = validate_generated_case(negative, generator.protocol)

    assert positive_validation.positive_pixel_count > 0
    assert positive_validation.target_feature_overlap_pixels is not None
    assert positive_validation.target_feature_overlap_pixels > 0
    assert not positive_validation.is_empty
    assert negative_validation.is_empty
    assert negative_validation.target_feature_overlap_pixels is None


def test_mask_hash_mismatch_fails_before_decode(generated_cases: tuple) -> None:
    _, positive, _ = generated_cases

    with pytest.raises(UnsafeInputError) as exc_info:
        validate_authoritative_mask(
            positive.authoritative_mask_bytes + b"tamper",
            declared_sha256=positive.authoritative_mask_sha256,
            expected_size=(512, 384),
            expected_non_empty=True,
        )

    assert exc_info.value.code == "HASH_MISMATCH"


@pytest.mark.parametrize("payload", [b"not-a-png", b"\x89PNG\r\n\x1a\ntruncated"])
def test_corrupt_mask_with_matching_hash_fails_closed(payload: bytes) -> None:
    with pytest.raises(UnsafeInputError) as exc_info:
        validate_authoritative_mask(
            payload,
            declared_sha256=sha256_bytes(payload),
            expected_size=(512, 384),
            expected_non_empty=False,
        )

    assert exc_info.value.code == "MASK_CORRUPT"


def test_non_binary_mask_is_rejected_even_with_valid_canonical_png() -> None:
    payload = encode_png(Image.new("L", (512, 384), 1), mode="L")

    with pytest.raises(UnsafeInputError) as exc_info:
        validate_authoritative_mask(
            payload,
            declared_sha256=sha256_bytes(payload),
            expected_size=(512, 384),
            expected_non_empty=True,
        )

    assert exc_info.value.code == "MASK_CORRUPT"


def test_mask_dimension_mismatch_is_rejected() -> None:
    payload = encode_png(Image.new("L", (511, 384), 0), mode="L")

    with pytest.raises(UnsafeInputError) as exc_info:
        validate_authoritative_mask(
            payload,
            declared_sha256=sha256_bytes(payload),
            expected_size=(512, 384),
            expected_non_empty=False,
        )

    assert exc_info.value.code == "MASK_CORRUPT"


def test_positive_empty_and_negative_nonempty_masks_are_both_rejected(
    generated_cases: tuple,
) -> None:
    _, positive, negative = generated_cases

    with pytest.raises(UnsafeInputError) as positive_error:
        validate_authoritative_mask(
            negative.authoritative_mask_bytes,
            declared_sha256=negative.authoritative_mask_sha256,
            expected_size=(512, 384),
            expected_non_empty=True,
        )
    with pytest.raises(UnsafeInputError) as negative_error:
        validate_authoritative_mask(
            positive.authoritative_mask_bytes,
            declared_sha256=positive.authoritative_mask_sha256,
            expected_size=(512, 384),
            expected_non_empty=False,
        )

    assert positive_error.value.code == "MASK_CORRUPT"
    assert negative_error.value.code == "MASK_CORRUPT"


def test_feature_binding_requires_at_least_one_truth_pixel_in_target(
    generated_cases: tuple,
) -> None:
    _, positive, _ = generated_cases

    with pytest.raises(UnsafeInputError) as exc_info:
        validate_authoritative_mask(
            positive.authoritative_mask_bytes,
            declared_sha256=positive.authoritative_mask_sha256,
            expected_size=(512, 384),
            expected_non_empty=True,
            target_feature_id="deliberately_wrong",
            feature_regions={"deliberately_wrong": (0.0, 0.0, 0.01, 0.01)},
        )

    assert exc_info.value.code == "MASK_CORRUPT"


def test_unknown_target_feature_is_a_schema_failure(generated_cases: tuple) -> None:
    _, positive, _ = generated_cases

    with pytest.raises(UnsafeInputError) as exc_info:
        validate_authoritative_mask(
            positive.authoritative_mask_bytes,
            declared_sha256=positive.authoritative_mask_sha256,
            expected_size=(512, 384),
            expected_non_empty=True,
            target_feature_id="unknown",
            feature_regions={},
        )

    assert exc_info.value.code == "SCHEMA_INVALID"


def test_noncanonical_and_trailing_byte_pngs_are_rejected() -> None:
    image = Image.new("L", (512, 384), 0)
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=1, optimize=False)
    noncanonical = output.getvalue()
    canonical = encode_png(image, mode="L")
    assert noncanonical != canonical

    for payload in (noncanonical, canonical + b"trailing"):
        with pytest.raises(UnsafeInputError) as exc_info:
            validate_authoritative_mask(
                payload,
                declared_sha256=sha256_bytes(payload),
                expected_size=(512, 384),
                expected_non_empty=False,
            )
        assert exc_info.value.code == "MASK_CORRUPT"


def test_case_binding_and_source_hash_tampering_fail_closed(generated_cases: tuple) -> None:
    generator, positive, _ = generated_cases
    bad_binding = replace(positive, case_binding_sha256="0" * 64)
    bad_reference = replace(positive, reference_sha256="0" * 64)

    with pytest.raises(UnsafeInputError) as binding_error:
        validate_generated_case(bad_binding, generator.protocol)
    with pytest.raises(UnsafeInputError) as reference_error:
        validate_generated_case(bad_reference, generator.protocol)

    assert binding_error.value.code == "HASH_MISMATCH"
    assert reference_error.value.code == "HASH_MISMATCH"


def test_direct_drawn_mask_can_be_validated_without_an_inspection_image() -> None:
    mask = Image.new("L", (512, 384), 0)
    ImageDraw.Draw(mask).rectangle((240, 140, 260, 180), fill=255)
    payload = encode_png(mask, mode="L")

    validation = validate_authoritative_mask(
        payload,
        declared_sha256=sha256_bytes(payload),
        expected_size=(512, 384),
        expected_non_empty=True,
        target_feature_id="top_face",
        feature_regions={"top_face": (0.1, 0.14, 0.9, 0.86)},
    )

    assert validation.positive_pixel_count == 861
    assert validation.target_feature_overlap_pixels == 861
