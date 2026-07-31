from __future__ import annotations

import io
import math
from collections import Counter
from collections.abc import Callable, Iterable
from typing import TypeVar

import pytest
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.e1 import (
    CadRevision,
    CaseGroup,
    DatasetProfile,
    DatasetSplit,
    DefectType,
    E1CasePlan,
    E1Generator,
    ExpectedOutcome,
    NuisanceType,
    Severity,
    ViewId,
    load_e1_protocol,
    plan_e1_cases,
    select_e1_profile,
    validate_generated_case,
)

_Taxon = TypeVar("_Taxon")


@pytest.fixture(scope="module")
def generator() -> E1Generator:
    return E1Generator()


@pytest.fixture(scope="module")
def plans(generator: E1Generator) -> tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]]:
    return generator.plan_cases("full"), generator.plan_cases("mini")


def test_protocol_projection_and_plan_are_repeatable_and_defensively_loaded() -> None:
    first_protocol = load_e1_protocol()
    second_protocol = load_e1_protocol()

    assert first_protocol.configuration_sha256 == (
        "586cd2cb71a621c9794b5a7f9bc09a3602b80b704cede64f5a46b2296ddb96fd"
    )
    assert first_protocol.generator_configuration_sha256 == (
        "7e05399f8f93769b83196b255724b6be6548c27ad54c2e242c9dc388c2415f09"
    )
    assert first_protocol.configuration_sha256 == second_protocol.configuration_sha256
    assert first_protocol.generator_configuration_sha256 == (
        second_protocol.generator_configuration_sha256
    )
    mutable_copy = first_protocol.document
    mutable_copy["protocol_id"] = "mutated"
    assert first_protocol.protocol_id == "mvs-e1"
    assert plan_e1_cases(first_protocol) == plan_e1_cases(second_protocol)


def test_full_and_mini_plans_have_exact_frozen_membership_and_counts(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    full, mini = plans
    assert len(full) == 480
    assert len(mini) == 48
    assert len({plan.case_id for plan in full}) == 480
    assert len({plan.recipe_id for plan in full}) == 480
    assert tuple(plan.case_id for plan in mini) == generator.protocol.exact_mini_case_ids
    assert select_e1_profile(full, DatasetProfile.MINI, protocol=generator.protocol) == mini
    assert select_e1_profile(full, DatasetProfile.FULL, protocol=generator.protocol) == full
    assert all(
        plan.profile_membership == (DatasetProfile.FULL,)
        for plan in full
        if not plan.included_in_mini
    )
    assert all(
        plan.profile_membership == (DatasetProfile.FULL, DatasetProfile.MINI) for plan in mini
    )

    assert Counter(plan.group for plan in full) == {
        CaseGroup.CLEAN: 96,
        CaseGroup.NUISANCE: 120,
        CaseGroup.DEFECT: 240,
        CaseGroup.TRUST_BOUNDARY: 24,
    }
    assert Counter(plan.group for plan in mini) == {
        CaseGroup.CLEAN: 8,
        CaseGroup.NUISANCE: 12,
        CaseGroup.DEFECT: 24,
        CaseGroup.TRUST_BOUNDARY: 4,
    }
    assert Counter(plan.split for plan in full) == {
        DatasetSplit.DEVELOPMENT: 120,
        DatasetSplit.CALIBRATION: 120,
        DatasetSplit.TEST: 240,
    }
    assert Counter(plan.split for plan in mini) == {
        DatasetSplit.DEVELOPMENT: 12,
        DatasetSplit.CALIBRATION: 12,
        DatasetSplit.TEST: 24,
    }


def test_seed_identity_and_taxonomy_allocations_are_exact(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    full, mini = plans
    seed_blocks = generator.protocol.document["generator"]["seed_blocks"]
    for plan in full:
        block = seed_blocks[plan.split.value][plan.group.value]
        assert plan.seed_family == block["seed_family"]
        assert plan.seed == block["start"] + plan.ordinal
        assert plan.case_id == (f"e1-{plan.split.value}-{plan.group.value}-{plan.ordinal:03d}")

    assert Counter(plan.defect.defect_type for plan in full if plan.defect) == {
        defect_type: 40 for defect_type in DefectType
    }
    assert Counter(plan.defect.defect_type for plan in mini if plan.defect) == {
        defect_type: 4 for defect_type in DefectType
    }
    assert Counter(plan.defect.severity for plan in full if plan.defect) == {
        severity: 80 for severity in Severity
    }
    assert Counter(plan.defect.severity for plan in mini if plan.defect) == {
        severity: 8 for severity in Severity
    }
    assert {(plan.defect.defect_type, plan.defect.severity) for plan in mini if plan.defect} == {
        (defect_type, severity) for defect_type in DefectType for severity in Severity
    }
    assert Counter(nuisance.nuisance_type for plan in full for nuisance in plan.nuisances) == {
        NuisanceType.TRANSLATION: 14,
        NuisanceType.ROTATION: 14,
        NuisanceType.SCALE: 14,
        NuisanceType.EXPOSURE: 13,
        NuisanceType.DIRECTIONAL_SHADING: 13,
        NuisanceType.GAUSSIAN_BLUR: 13,
        NuisanceType.SENSOR_NOISE: 13,
        NuisanceType.JPEG_COMPRESSION: 13,
        NuisanceType.BACKGROUND_FIXTURE: 13,
    }
    assert Counter(nuisance.nuisance_type for plan in mini for nuisance in plan.nuisances) == {
        NuisanceType.TRANSLATION: 2,
        NuisanceType.ROTATION: 2,
        NuisanceType.SCALE: 2,
        NuisanceType.EXPOSURE: 1,
        NuisanceType.DIRECTIONAL_SHADING: 1,
        NuisanceType.GAUSSIAN_BLUR: 1,
        NuisanceType.SENSOR_NOISE: 1,
        NuisanceType.JPEG_COMPRESSION: 1,
        NuisanceType.BACKGROUND_FIXTURE: 1,
    }
    assert all(len(plan.nuisances) == 1 for plan in full if plan.group is CaseGroup.NUISANCE)
    assert all(not plan.nuisances for plan in full if plan.group is not CaseGroup.NUISANCE)


def test_nuisance_values_stay_inside_supported_ranges_and_mini_strata(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    full, mini = plans
    nuisance_documents = {
        item["type"]: item for item in generator.protocol.document["taxonomies"]["nuisances"]
    }
    for plan in full:
        for nuisance in plan.nuisances:
            parameter_documents = {
                item["name"]: item
                for item in nuisance_documents[nuisance.nuisance_type.value]["parameters"]
            }
            for parameter in nuisance.parameters:
                supported = parameter_documents[parameter.name]["supported_normal_range"]
                assert supported["minimum"] <= parameter.value <= supported["maximum"]

    actual_by_split = {
        split: tuple(
            plan.nuisances[0].nuisance_type.value
            for plan in mini
            if plan.split is split and plan.group is CaseGroup.NUISANCE
        )
        for split in DatasetSplit
    }
    assert actual_by_split == {
        DatasetSplit.DEVELOPMENT: ("translation", "rotation", "scale"),
        DatasetSplit.CALIBRATION: ("exposure", "directional_shading", "gaussian_blur"),
        DatasetSplit.TEST: (
            "translation",
            "rotation",
            "scale",
            "sensor_noise",
            "jpeg_compression",
            "background_fixture",
        ),
    }


def test_mini_clean_cases_cover_every_revision_view_pair(
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    _, mini = plans
    pairs = {(plan.cad_revision, plan.view_id) for plan in mini if plan.group is CaseGroup.CLEAN}
    assert pairs == {(revision, view) for revision in CadRevision for view in ViewId}


def test_two_revisions_and_three_views_render_distinct_canonical_clean_images(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    _, mini = plans
    selected: dict[tuple[CadRevision, ViewId], E1CasePlan] = {}
    for plan in mini:
        if plan.group is CaseGroup.CLEAN:
            selected.setdefault((plan.cad_revision, plan.view_id), plan)
    generated = [generator.generate_case(selected[pair]) for pair in sorted(selected)]

    assert len({item.reference_sha256 for item in generated}) == 6
    assert len({item.case_binding_sha256 for item in generated}) == 6
    for item in generated:
        assert item.reference_bytes == item.inspection_bytes
        assert item.reference_sha256 == item.inspection_sha256
        assert item.authoritative_mask_sha256 == (
            "52838448a95f6ca6b9ecf370fbb8682c72a0a89d916756077c67c392076badbc"
        )
        validation = validate_generated_case(item, generator.protocol)
        assert validation.is_empty
        with Image.open(io.BytesIO(item.reference_bytes)) as image:
            assert image.format == "PNG"
            assert image.mode == "RGB"
            assert image.size == (512, 384)
            assert image.info == {}

    first = generator.generate_case(mini[0])
    assert first.reference_sha256 == (
        "04873dda64c8f7c4f7ad2da4cb0d2a545d7196bdabca559857b6eb3302999e6b"
    )
    assert first.case_binding_sha256 == (
        "19c3f9708ba38d2206c417630dc32bcbd0e222a46dff29d3e1cbe49c584cd81f"
    )


def test_all_defect_recipes_emit_nonempty_feature_bound_independent_masks(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    _, mini = plans
    selected = _first_plan_by_taxon(
        (plan for plan in mini if plan.defect is not None),
        lambda plan: plan.defect.defect_type if plan.defect else None,
    )
    mask_hashes = set()
    for defect_type in DefectType:
        plan = selected[defect_type]
        generated = generator.generate_case(plan)
        validation = validate_generated_case(generated, generator.protocol)
        assert generated.reference_bytes != generated.inspection_bytes
        assert validation.positive_pixel_count > 0
        assert validation.target_feature_overlap_pixels is not None
        assert validation.target_feature_overlap_pixels > 0
        mask_hashes.add(generated.authoritative_mask_sha256)
        with Image.open(io.BytesIO(generated.authoritative_mask_bytes)) as mask:
            assert mask.format == "PNG"
            assert mask.mode == "L"
            assert mask.size == (512, 384)
            mask_values = (
                mask.get_flattened_data() if hasattr(mask, "get_flattened_data") else mask.getdata()
            )
            assert set(mask_values) <= {0, 255}
    assert len(mask_hashes) == len(DefectType)


def test_top_face_truth_is_exclusive_of_holes_and_edge_features(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    _, mini = plans
    top_face_plans = [
        plan
        for plan in mini
        if plan.defect and plan.defect.defect_type in {DefectType.SCRATCH, DefectType.STAIN}
    ]
    for plan in top_face_plans:
        generated = generator.generate_case(plan)
        regions = generator.protocol.feature_regions_for_view(plan.view_id)
        with Image.open(io.BytesIO(generated.authoritative_mask_bytes)) as mask:
            pixels = mask.load()
            assert pixels is not None
            for feature_id in ("hole_left", "hole_right", "top_edge", "bottom_edge"):
                left, top, right, bottom = regions[feature_id]
                box = (
                    math.floor(left * mask.width),
                    math.floor(top * mask.height),
                    math.ceil(right * mask.width),
                    math.ceil(bottom * mask.height),
                )
                assert all(
                    pixels[x, y] == 0 for y in range(box[1], box[3]) for x in range(box[0], box[2])
                )


def test_all_nuisance_recipes_are_deterministic_normal_cases_with_empty_truth(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    _, mini = plans
    selected = _first_plan_by_taxon(
        (plan for plan in mini if plan.nuisances),
        lambda plan: plan.nuisances[0].nuisance_type,
    )
    for nuisance_type in NuisanceType:
        plan = selected[nuisance_type]
        first = generator.generate_case(plan)
        second = generator.generate_case(plan)
        assert first == second
        assert first.reference_bytes != first.inspection_bytes
        assert first.authoritative_mask_sha256 == (
            "52838448a95f6ca6b9ecf370fbb8682c72a0a89d916756077c67c392076badbc"
        )
        assert first.plan.expected_outcome is ExpectedOutcome.NORMAL
        assert validate_generated_case(first, generator.protocol).is_empty


def test_trust_plans_generate_pristine_sources_and_keep_mutation_out_of_oracle(
    generator: E1Generator,
    plans: tuple[tuple[E1CasePlan, ...], tuple[E1CasePlan, ...]],
) -> None:
    full, mini = plans
    trust = [plan for plan in full if plan.group is CaseGroup.TRUST_BOUNDARY]
    assert len(trust) == 24
    assert {plan.trust_boundary.scenario_id for plan in mini if plan.trust_boundary} == {
        "revision_mismatch",
        "split_hash_overlap",
        "incomplete_evidence_bundle",
        "unsupported_view_or_extreme_nuisance",
    }
    generated = generator.generate_case(trust[0])
    assert generated.reference_bytes == generated.inspection_bytes
    assert validate_generated_case(generated, generator.protocol).is_empty
    assert generated.plan.expected_outcome is ExpectedOutcome.ABSTAIN
    assert generated.plan.trust_boundary is not None
    assert not generated.plan.trust_boundary.publication_allowed
    assert generated.reference_sha256 == sha256_bytes(generated.reference_bytes)


def _first_plan_by_taxon(
    plans: Iterable[E1CasePlan],
    key: Callable[[E1CasePlan], _Taxon],
) -> dict[_Taxon, E1CasePlan]:
    selected: dict[_Taxon, E1CasePlan] = {}
    for plan in plans:
        selected.setdefault(key(plan), plan)
    return selected
