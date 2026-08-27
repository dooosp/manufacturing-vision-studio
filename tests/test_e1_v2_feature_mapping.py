"""Final-mask feature ownership and mapping contracts."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain import CadRevision, CaseGroup, ViewId
from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.feature_mapping import build_ownership_map, map_final_mask
from manufacturing_vision_studio.e1.generator import _render_pristine
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.oracle import geometry_for_case, render_defect_truth
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol
from manufacturing_vision_studio.errors import UnsafeInputError

EXPECTED_OWNERSHIP_HASHES = {
    (
        CadRevision.REV_A,
        ViewId.FRONT,
    ): "eadc490b04f8240e8356b3e20e75db08d79dfc5e27af180574d707836b3b776f",
    (
        CadRevision.REV_A,
        ViewId.OBLIQUE_LEFT,
    ): "2d2a52ecae44ccae98455180211aaf528078707948dbf83f792223c550d3a074",
    (
        CadRevision.REV_A,
        ViewId.OBLIQUE_RIGHT,
    ): "8c42a88c3ffdf3dda10b073665b6d7a565ddde54a7a7450ba3c0f4782be14477",
    (
        CadRevision.REV_B,
        ViewId.FRONT,
    ): "5f69348a9ce7b646054dce02f95a0ff8ebd420c641ab40f414b0afa645ef49bc",
    (
        CadRevision.REV_B,
        ViewId.OBLIQUE_LEFT,
    ): "1fb2f752d738a7bf595f8cae97860452a3a8628ea5cb3eec4347d1f42fe43b8b",
    (
        CadRevision.REV_B,
        ViewId.OBLIQUE_RIGHT,
    ): "373337ec46da320dbbcdf0ffa14c22794db05208cd9491e5b272e0d34169830d",
}


def test_protocol_uses_the_preregistered_ownership_hash_algorithm() -> None:
    """Changing the hash header algorithm would invalidate independent verification."""

    config = load_e1_v2_protocol().feature_ownership(CadRevision.REV_A, ViewId.FRONT)

    assert config.algorithm == "exclusive_half_open_boxes_v2"


def hole_over_face_coordinate(revision: CadRevision, view: ViewId) -> tuple[int, int]:
    del revision
    return {
        ViewId.FRONT: (156, 192),
        ViewId.OBLIQUE_LEFT: (171, 196),
        ViewId.OBLIQUE_RIGHT: (162, 187),
    }[view]


def edge_over_face_coordinate(revision: CadRevision, view: ViewId) -> tuple[int, int]:
    del revision
    return {
        ViewId.FRONT: (256, 64),
        ViewId.OBLIQUE_LEFT: (256, 68),
        ViewId.OBLIQUE_RIGHT: (256, 68),
    }[view]


@pytest.mark.parametrize("revision", [CadRevision.REV_A, CadRevision.REV_B])
@pytest.mark.parametrize("view", list(ViewId))
def test_ownership_is_exclusive_and_uses_the_protocol_geometry(
    revision: CadRevision,
    view: ViewId,
) -> None:
    """Removing priority or changing a revision/view box must fail this contract."""

    protocol = load_e1_v2_protocol()
    ownership = build_ownership_map(protocol.feature_ownership(revision, view), (512, 384))

    assert ownership.labels.shape == (384, 512)
    assert ownership.ownership_map_sha256 == EXPECTED_OWNERSHIP_HASHES[(revision, view)]
    assert set(np.unique(ownership.labels)) <= {0, 1, 2, 3, 4, 5}
    assert ownership.label_at(*hole_over_face_coordinate(revision, view)) == "hole_left"
    assert ownership.label_at(*edge_over_face_coordinate(revision, view)) == "top_edge"


def test_revision_b_right_hole_layout_differs_from_revision_a() -> None:
    """Dropping the declared +4 px revision geometry must change the map."""

    protocol = load_e1_v2_protocol()
    rev_a = build_ownership_map(protocol.feature_ownership("rev-A", "front"), (512, 384))
    rev_b = build_ownership_map(protocol.feature_ownership("rev-B", "front"), (512, 384))

    assert rev_a.ownership_map_sha256 != rev_b.ownership_map_sha256


@pytest.mark.parametrize("revision", list(CadRevision))
@pytest.mark.parametrize("view", list(ViewId))
def test_generator_and_ownership_use_the_same_v2_feature_boxes(
    revision: CadRevision,
    view: ViewId,
) -> None:
    """Passing legacy v1 regions to the generator must fail for rev-B top-face truth."""

    generator = E1V2Generator()
    protocol = generator.protocol
    ownership_config = protocol.feature_ownership(revision, view)
    plan = next(
        candidate
        for scope in (EvaluationScope.DEVELOPMENT, EvaluationScope.SMOKE)
        for candidate in generator.plan_cases(scope)
        if candidate.group is CaseGroup.DEFECT
        and candidate._render_plan.cad_revision is revision
        and candidate._render_plan.view_id is view
        and candidate._render_plan.defect is not None
        and candidate._render_plan.defect.target_feature_id == "top_face"
    )
    render_plan = plan._render_plan
    geometry = geometry_for_case(
        revision,
        view,
        image_size=(512, 384),
        feature_regions=ownership_config.feature_boxes,
    )
    reference = _render_pristine(render_plan, geometry)
    _, expected_mask = render_defect_truth(
        reference,
        render_plan.defect,
        seed=render_plan.seed,
        geometry=geometry,
    )

    generated = generator.generate_case(plan)
    ownership = build_ownership_map(ownership_config, (512, 384))

    assert dict(geometry.feature_regions) == dict(ownership_config.feature_boxes)
    assert generated.authoritative_mask_bytes == png(np.asarray(expected_mask, dtype=np.uint8))
    assert ownership.label_at(*hole_over_face_coordinate(revision, view)) == "hole_left"


def front_rev_a_ownership():
    return build_ownership_map(
        load_e1_v2_protocol().feature_ownership("rev-A", "front"), (512, 384)
    )


def png(mask: np.ndarray) -> bytes:
    return encode_png(Image.fromarray(mask, mode="L"), mode="L")


def empty_mask() -> np.ndarray:
    return np.zeros((384, 512), dtype=np.uint8)


def mask_for(feature_id: str, *, pixels: int | None = None) -> np.ndarray:
    ownership = front_rev_a_ownership()
    code = ownership.config.feature_ids.index(feature_id) + 1
    coordinates = np.argwhere(ownership.labels == code)
    selected = coordinates if pixels is None else coordinates[:pixels]
    mask = empty_mask()
    mask[selected[:, 0], selected[:, 1]] = 255
    return mask


def mask_outside_all_owners(pixels: int) -> np.ndarray:
    ownership = front_rev_a_ownership()
    coordinates = np.argwhere(ownership.labels == 0)[:pixels]
    mask = empty_mask()
    mask[coordinates[:, 0], coordinates[:, 1]] = 255
    return mask


def mask_with_owner_counts(hole_left: int, top_face: int) -> np.ndarray:
    return mask_for("hole_left", pixels=hole_left) | mask_for("top_face", pixels=top_face)


def mask_with_ratio(winner: str, winner_pixels: int, runner: str, runner_pixels: int) -> np.ndarray:
    return mask_for(winner, pixels=winner_pixels) | mask_for(runner, pixels=runner_pixels)


def test_mapping_uses_only_pixels_present_in_final_mask() -> None:
    """Consulting the pre-filter mask instead of the final mask would pick bottom_edge."""

    raw_mask = mask_for("bottom_edge") | mask_for("top_face", pixels=20)
    final_mask = raw_mask & ~mask_for("bottom_edge")

    result = map_final_mask(png(final_mask), front_rev_a_ownership())

    assert result.predicted_feature_id == "top_face"
    assert result.final_mask_sha256 == sha256_bytes(png(final_mask))


@pytest.mark.parametrize(
    ("mask", "reason"),
    [
        (empty_mask(), "NO_OWNED_PIXELS"),
        (mask_outside_all_owners(20), "NO_OWNED_PIXELS"),
        (mask_with_owner_counts(7, 0), "INSUFFICIENT_MAPPED_PIXELS"),
        (mask_with_owner_counts(5, 4), "INSUFFICIENT_MAPPED_PIXELS"),
        (mask_with_ratio("hole_left", 20, "top_face", 20), "AMBIGUOUS_FEATURE"),
        (mask_with_ratio("hole_left", 100, "top_face", 91), "AMBIGUOUS_FEATURE"),
    ],
)
def test_null_and_ambiguous_mapping(mask: np.ndarray, reason: str) -> None:
    """Removing a null or ambiguity branch must not publish a feature winner."""

    result = map_final_mask(png(mask), front_rev_a_ownership())

    assert result.predicted_feature_id is None
    assert result.reason == reason


def test_mapping_keeps_one_owner_per_final_pixel_and_exact_margin_maps() -> None:
    """Changing integer margin arithmetic or double-counting overlaps breaks the trace."""

    mask = mask_with_ratio("hole_left", 100, "top_face", 90) | mask_outside_all_owners(3)
    result = map_final_mask(png(mask), front_rev_a_ownership())

    assert result.predicted_feature_id == "hole_left"
    assert result.owner_pixel_counts == {
        "bottom_edge": 0,
        "hole_left": 100,
        "hole_right": 0,
        "top_edge": 0,
        "top_face": 90,
    }
    assert result.winner_owned_pixel_count == 100
    assert result.winner_margin == 0.10
    assert result.as_record()["winner_margin"] == "0.10000000"
    assert (
        result.owned_pixel_count + result.unmapped_pixel_count == result.final_positive_pixel_count
    )


def test_eight_pixels_can_win_over_a_runner_up_and_mapping_is_repeatable() -> None:
    """Changing the eight-pixel boundary or trace hashing must fail this test."""

    payload = png(mask_with_ratio("hole_left", 8, "top_face", 1))
    first = map_final_mask(payload, front_rev_a_ownership())
    second = map_final_mask(payload, front_rev_a_ownership())

    assert first.predicted_feature_id == "hole_left"
    assert first.winner_owned_pixel_count == 8
    assert first == second


def test_bottom_edge_scale_residual_remains_owned_by_bottom_edge() -> None:
    """A residual crossing unmapped background must not erase a clear bottom-edge winner."""

    mask = mask_for("bottom_edge", pixels=20) | mask_outside_all_owners(9)
    result = map_final_mask(png(mask), front_rev_a_ownership())

    assert result.predicted_feature_id == "bottom_edge"
    assert result.owner_pixel_counts["bottom_edge"] == 20
    assert result.unmapped_pixel_count == 9


def test_offline_development_and_smoke_truth_maps_to_declared_feature() -> None:
    """A drifted renderer or owner layout must fail against real non-release truth masks."""

    generator = E1V2Generator()
    for scope in (EvaluationScope.DEVELOPMENT, EvaluationScope.SMOKE):
        for plan in generator.plan_cases(scope):
            if plan.group is not CaseGroup.DEFECT:
                continue
            generated = generator.generate_case(plan)
            render_plan = plan._render_plan
            assert render_plan.defect is not None
            ownership = build_ownership_map(
                generator.protocol.feature_ownership(render_plan.cad_revision, render_plan.view_id),
                (512, 384),
            )
            result = map_final_mask(generated.authoritative_mask_bytes, ownership)

            assert result.owner_pixel_counts[render_plan.defect.target_feature_id] >= 8
            assert result.predicted_feature_id == render_plan.defect.target_feature_id


@pytest.mark.parametrize("payload", [b"not-a-png", b"\x89PNG\r\n\x1a\n"])
def test_corrupt_final_masks_fail_closed(payload: bytes) -> None:
    """Accepting undecodable final-mask bytes would make feature evidence unverifiable."""

    with pytest.raises(UnsafeInputError, match="could not be decoded") as error:
        map_final_mask(payload, front_rev_a_ownership())

    assert error.value.code == "MASK_CORRUPT"


def test_non_binary_but_canonical_final_mask_fails_closed() -> None:
    """Treating arbitrary grayscale values as positive would undermine binary mask evidence."""

    mask = empty_mask()
    mask[100, 100] = 127

    with pytest.raises(UnsafeInputError, match="only 0 and 255") as error:
        map_final_mask(png(mask), front_rev_a_ownership())

    assert error.value.code == "MASK_CORRUPT"
