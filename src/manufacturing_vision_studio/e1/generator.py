"""Deterministic planning and rendering for the frozen E1 synthetic corpus."""

from __future__ import annotations

import hashlib
import io
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain import (
    CadRevision,
    CaseGroup,
    DatasetProfile,
    DatasetSplit,
    DefectSpec,
    DefectType,
    E1CasePlan,
    E1GeneratedCase,
    ExpectedOutcome,
    NuisanceSpec,
    NuisanceType,
    RecipeParameter,
    Severity,
    SupportBoundary,
    TrustBoundarySpec,
    ViewId,
)
from manufacturing_vision_studio.e1.oracle import (
    E1RenderGeometry,
    geometry_for_case,
    render_defect_truth,
    validate_generated_case,
)
from manufacturing_vision_studio.e1.protocol import E1Protocol, E1ProtocolError, load_e1_protocol


@dataclass(frozen=True, slots=True)
class _DefectAssignment:
    document: dict[str, Any]
    severity: Severity
    target_feature_id: str


class E1Generator:
    """Stateless-byte generator backed by one explicitly loaded frozen config."""

    def __init__(self, protocol: E1Protocol | None = None) -> None:
        self.protocol = protocol or load_e1_protocol()
        self._full_plan: tuple[E1CasePlan, ...] | None = None

    def plan_cases(
        self,
        profile: DatasetProfile | str = DatasetProfile.FULL,
    ) -> tuple[E1CasePlan, ...]:
        """Return the exact full plan or the frozen strict mini subset."""

        resolved_profile = DatasetProfile(profile)
        if self._full_plan is None:
            self._full_plan = self._build_full_plan()
        if resolved_profile is DatasetProfile.FULL:
            return self._full_plan
        return tuple(plan for plan in self._full_plan if plan.included_in_mini)

    def generate_case(self, plan: E1CasePlan) -> E1GeneratedCase:
        """Render one pristine case; trust mutations remain a runner concern."""

        if plan not in self.plan_cases(DatasetProfile.FULL):
            raise E1ProtocolError("case plan is not part of this generator contract")
        width, height = self.protocol.image_size
        feature_regions = self.protocol.feature_regions_for_view(plan.view_id)
        geometry = geometry_for_case(
            plan.cad_revision,
            plan.view_id,
            image_size=(width, height),
            feature_regions=feature_regions,
        )
        reference = _render_pristine(plan, geometry)
        mask = Image.new("L", (width, height), 0)
        if plan.group is CaseGroup.DEFECT:
            if plan.defect is None:  # dataclass validation makes this defensive
                raise E1ProtocolError("defect case is missing defect truth")
            inspection, mask = render_defect_truth(
                reference,
                plan.defect,
                seed=plan.seed,
                geometry=geometry,
            )
        elif plan.group is CaseGroup.NUISANCE:
            inspection = reference.copy()
            for nuisance in plan.nuisances:
                inspection = _apply_nuisance(inspection, nuisance, plan.seed, geometry)
        else:
            # Trust cases expose a valid pristine source. The runner creates the
            # declared malformed/omitted stimulus separately and must not replace
            # valid generator truth with corrupt bytes.
            inspection = reference.copy()

        reference_bytes = encode_png(reference, mode="RGB")
        inspection_bytes = encode_png(inspection, mode="RGB")
        mask_bytes = encode_png(mask, mode="L")
        reference_sha256 = sha256_bytes(reference_bytes)
        inspection_sha256 = sha256_bytes(inspection_bytes)
        mask_sha256 = sha256_bytes(mask_bytes)
        case_binding_sha256 = self.protocol.case_binding_sha256(
            plan,
            reference_sha256=reference_sha256,
            inspection_sha256=inspection_sha256,
            authoritative_mask_sha256=mask_sha256,
        )
        generated = E1GeneratedCase(
            plan=plan,
            generator_id=self.protocol.generator_id,
            generator_version=self.protocol.generator_version,
            generator_configuration_sha256=self.protocol.generator_configuration_sha256,
            reference_bytes=reference_bytes,
            inspection_bytes=inspection_bytes,
            authoritative_mask_bytes=mask_bytes,
            reference_sha256=reference_sha256,
            inspection_sha256=inspection_sha256,
            authoritative_mask_sha256=mask_sha256,
            case_binding_sha256=case_binding_sha256,
        )
        validate_generated_case(generated, self.protocol)
        return generated

    def iter_generated_cases(
        self,
        profile: DatasetProfile | str = DatasetProfile.FULL,
    ) -> Iterator[E1GeneratedCase]:
        """Yield cases one at a time so the 480-case corpus stays memory-bounded."""

        for plan in self.plan_cases(profile):
            yield self.generate_case(plan)

    def _build_full_plan(self) -> tuple[E1CasePlan, ...]:
        document = self.protocol.document
        generator = _object(document, "generator")
        profiles = _object(document, "dataset_profiles")
        composition = _object(profiles, "split_composition")
        universe = _object(document, "universe")
        taxonomies = _object(document, "taxonomies")
        seed_blocks = _object(generator, "seed_blocks")
        case_id_format = _string(generator, "case_id_format")
        split_order = tuple(DatasetSplit(value) for value in self.protocol.split_order)
        if split_order != (
            DatasetSplit.DEVELOPMENT,
            DatasetSplit.CALIBRATION,
            DatasetSplit.TEST,
        ):
            raise E1ProtocolError("E1 split order is not the frozen canonical order")

        part_id, revisions = _part_universe(universe)
        views = tuple(ViewId(value) for value in _string_list(universe, "views"))
        if len(revisions) != 2 or len(views) != 3:
            raise E1ProtocolError("E1 requires exactly two revisions and three views")
        mini_ids = set(self.protocol.exact_mini_case_ids)
        clean_identities = _mini_clean_identity_overrides(
            self.protocol.exact_mini_case_ids,
            revisions,
            views,
        )
        defect_assignments = _defect_assignments(document, case_id_format, split_order)
        nuisance_assignments = _nuisance_assignments(document, case_id_format, split_order)
        trust_by_split = _trust_documents_by_split(taxonomies, split_order)

        plans: list[E1CasePlan] = []
        for split in split_order:
            split_name = split.value
            split_composition = _object(composition, split_name)
            group_counts = _object(split_composition, "group_counts")
            split_seed_blocks = _object(seed_blocks, split_name)
            for group in CaseGroup:
                count = _integer(group_counts, group.value)
                block = _object(split_seed_blocks, group.value)
                if _integer(block, "count") != count:
                    raise E1ProtocolError(f"seed block count disagrees for {split_name}/{group}")
                start = _integer(block, "start")
                seed_family = _string(block, "seed_family")
                for ordinal in range(count):
                    case_id = case_id_format.format(
                        split=split_name,
                        group=group.value,
                        ordinal=ordinal,
                    )
                    profiles_for_case = (
                        (DatasetProfile.FULL, DatasetProfile.MINI)
                        if case_id in mini_ids
                        else (DatasetProfile.FULL,)
                    )
                    revision, view = clean_identities.get(
                        case_id,
                        _stable_identity(case_id, revisions, views),
                    )
                    defect: DefectSpec | None = None
                    nuisances: tuple[NuisanceSpec, ...] = ()
                    trust: TrustBoundarySpec | None = None
                    expected = ExpectedOutcome.NORMAL
                    boundary = SupportBoundary.SUPPORTED_NORMAL_RANGE
                    if group is CaseGroup.DEFECT:
                        assignment = defect_assignments[(split, ordinal)]
                        defect_type = DefectType(_string(assignment.document, "type"))
                        defect = DefectSpec(
                            defect_id=f"{case_id}-truth-001",
                            defect_type=defect_type,
                            severity=assignment.severity,
                            target_feature_id=assignment.target_feature_id,
                            parameters=_defect_parameters(
                                assignment.document,
                                assignment.severity,
                            ),
                        )
                        expected = ExpectedOutcome.ANOMALY
                    elif group is CaseGroup.NUISANCE:
                        nuisance_document = nuisance_assignments[(split, ordinal)]
                        nuisance_type = NuisanceType(_string(nuisance_document, "type"))
                        nuisances = (
                            NuisanceSpec(
                                nuisance_type=nuisance_type,
                                parameters=_nuisance_parameters(
                                    nuisance_document,
                                    start + ordinal,
                                    case_id,
                                ),
                            ),
                        )
                    elif group is CaseGroup.TRUST_BOUNDARY:
                        trust_document = trust_by_split[split][ordinal]
                        trust = TrustBoundarySpec(
                            scenario_id=_string(trust_document, "scenario_id"),
                            expected_error_code=_string(trust_document, "expected_error_code"),
                            publication_allowed=_boolean(trust_document, "publication_allowed"),
                        )
                        expected = ExpectedOutcome.ABSTAIN
                        boundary = SupportBoundary.UNSUPPORTED_OR_ABSTAIN_RANGE

                    plans.append(
                        E1CasePlan(
                            case_id=case_id,
                            profile_membership=profiles_for_case,
                            split=split,
                            group=group,
                            ordinal=ordinal,
                            seed_family=seed_family,
                            seed=start + ordinal,
                            recipe_id=f"mvs-e1-recipe-v1/{case_id}",
                            recipe_version=self.protocol.recipe_version,
                            part_id=part_id,
                            cad_revision=revision,
                            view_id=view,
                            expected_outcome=expected,
                            support_boundary=boundary,
                            defect=defect,
                            nuisances=nuisances,
                            trust_boundary=trust,
                        )
                    )

        full = tuple(plans)
        _validate_plan_contract(full, document, self.protocol.exact_mini_case_ids)
        return full


def plan_e1_full(protocol: E1Protocol | None = None) -> tuple[E1CasePlan, ...]:
    """Convenience API for the exact 480-case canonical plan."""

    return E1Generator(protocol).plan_cases(DatasetProfile.FULL)


def plan_e1_cases(
    protocol: E1Protocol | None = None,
    profile: DatasetProfile | str = DatasetProfile.FULL,
) -> tuple[E1CasePlan, ...]:
    """Public planner API for either frozen profile."""

    return E1Generator(protocol).plan_cases(profile)


def select_e1_profile(
    full_cases: Iterable[E1CasePlan],
    profile: DatasetProfile | str,
    *,
    protocol: E1Protocol | None = None,
) -> tuple[E1CasePlan, ...]:
    """Select full or exact mini membership without re-planning case identities."""

    resolved = DatasetProfile(profile)
    cases = tuple(full_cases)
    if resolved is DatasetProfile.FULL:
        return cases
    loaded = protocol or load_e1_protocol()
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise E1ProtocolError("full plan contains duplicate case IDs")
    try:
        selected = tuple(by_id[case_id] for case_id in loaded.exact_mini_case_ids)
    except KeyError as exc:
        raise E1ProtocolError(f"full plan is missing frozen mini case {exc.args[0]}") from exc
    if any(not case.included_in_mini for case in selected):
        raise E1ProtocolError("frozen mini case is missing mini profile membership")
    return selected


def render_e1_case(
    plan: E1CasePlan,
    protocol: E1Protocol | None = None,
) -> E1GeneratedCase:
    """Convenience API for rendering one contract-owned case."""

    return E1Generator(protocol).generate_case(plan)


def _defect_assignments(
    document: dict[str, Any],
    case_id_format: str,
    split_order: tuple[DatasetSplit, ...],
) -> dict[tuple[DatasetSplit, int], _DefectAssignment]:
    taxonomies = _object(document, "taxonomies")
    defects = _object_list(taxonomies, "defects")
    severities = tuple(
        Severity(_string(item, "severity")) for item in _object_list(taxonomies, "severities")
    )
    profiles = _object(document, "dataset_profiles")
    mini = _object(profiles, "mini_selection")
    mini_splits = _object(mini, "split_counts")
    selected_severities: dict[tuple[DatasetSplit, int], Severity] = {}
    type_documents: dict[tuple[DatasetSplit, int], dict[str, Any]] = {}

    for split_index, split in enumerate(split_order):
        required = {
            _string(item, "type"): _integer(_object(item, "split_counts"), split.value)
            for item in defects
        }
        mini_count = _integer(_object(_object(mini_splits, split.value), "group_counts"), "defect")
        if mini_count % len(defects):
            raise E1ProtocolError("mini defect quota must allocate whole defect-type cycles")
        ordered_types = defects * (mini_count // len(defects))
        remaining = required.copy()
        allocation: list[dict[str, Any]] = []
        for occurrence, item in enumerate(ordered_types):
            defect_type = _string(item, "type")
            if remaining[defect_type] <= 0:
                raise E1ProtocolError("mini defect quota exceeds split allocation")
            remaining[defect_type] -= 1
            allocation.append(item)
            type_index = next(index for index, candidate in enumerate(defects) if candidate is item)
            cycle_index = occurrence // len(defects)
            selected_severities[(split, occurrence)] = severities[
                (type_index + split_index + cycle_index) % len(severities)
            ]
        while any(value > 0 for value in remaining.values()):
            for item in defects:
                defect_type = _string(item, "type")
                if remaining[defect_type] > 0:
                    allocation.append(item)
                    remaining[defect_type] -= 1
        for ordinal, item in enumerate(allocation):
            type_documents[(split, ordinal)] = item

    target_counts = {
        Severity(_string(item, "severity")): _integer(item, "full_case_count")
        for item in _object_list(taxonomies, "severities")
    }
    fixed_counts = Counter(selected_severities.values())
    remaining_quota = {
        severity: target_counts[severity] - fixed_counts[severity] for severity in severities
    }
    assigned_counts = fixed_counts.copy()
    assignments: dict[tuple[DatasetSplit, int], _DefectAssignment] = {}
    for split in split_order:
        ordinals = sorted(ordinal for candidate, ordinal in type_documents if candidate is split)
        feature_occurrences: Counter[str] = Counter()
        for ordinal in ordinals:
            document_for_case = type_documents[(split, ordinal)]
            severity = selected_severities.get((split, ordinal))
            if severity is None:
                best_remaining = max(remaining_quota.values())
                candidates = [
                    item for item in severities if remaining_quota[item] == best_remaining
                ]
                case_id = case_id_format.format(
                    split=split.value,
                    group=CaseGroup.DEFECT.value,
                    ordinal=ordinal,
                )
                severity = candidates[_digest_index(case_id, "severity-tie", len(candidates))]
                remaining_quota[severity] -= 1
                assigned_counts[severity] += 1
            eligible = _string_list(document_for_case, "eligible_feature_ids")
            defect_type = _string(document_for_case, "type")
            occurrence = feature_occurrences[defect_type]
            feature_occurrences[defect_type] += 1
            target = eligible[occurrence % len(eligible)]
            assignments[(split, ordinal)] = _DefectAssignment(
                document=document_for_case,
                severity=severity,
                target_feature_id=target,
            )
    if assigned_counts != Counter(target_counts):
        raise E1ProtocolError("defect severity assignment does not match frozen totals")
    return assignments


def _nuisance_assignments(
    document: dict[str, Any],
    case_id_format: str,
    split_order: tuple[DatasetSplit, ...],
) -> dict[tuple[DatasetSplit, int], dict[str, Any]]:
    del case_id_format  # case ordinals are the frozen allocation key
    taxonomies = _object(document, "taxonomies")
    cardinality = _object(taxonomies, "nuisance_case_cardinality")
    if _integer(cardinality, "primary_nuisance_per_case") != 1 or _boolean(
        cardinality, "combined_nuisances_generated"
    ):
        raise E1ProtocolError("E1 v1 requires exactly one primary nuisance per case")
    nuisances = _object_list(taxonomies, "nuisances")
    by_type = {_string(item, "type"): item for item in nuisances}
    profiles = _object(document, "dataset_profiles")
    strata = _object(
        _object(_object(profiles, "mini_selection"), "strata"), "nuisance_types_by_split"
    )
    assignments: dict[tuple[DatasetSplit, int], dict[str, Any]] = {}
    for split in split_order:
        required = {
            nuisance_type: _integer(_object(item, "split_counts"), split.value)
            for nuisance_type, item in by_type.items()
        }
        priority = _string_list(strata, split.value)
        allocation: list[dict[str, Any]] = []
        for nuisance_type in priority:
            if nuisance_type not in by_type or required[nuisance_type] <= 0:
                raise E1ProtocolError(f"invalid mini nuisance stratum: {nuisance_type}")
            allocation.append(by_type[nuisance_type])
            required[nuisance_type] -= 1
        while any(value > 0 for value in required.values()):
            for nuisance_type, item in by_type.items():
                if required[nuisance_type] > 0:
                    allocation.append(item)
                    required[nuisance_type] -= 1
        for ordinal, item in enumerate(allocation):
            assignments[(split, ordinal)] = item
    return assignments


def _trust_documents_by_split(
    taxonomies: dict[str, Any],
    split_order: tuple[DatasetSplit, ...],
) -> dict[DatasetSplit, tuple[dict[str, Any], ...]]:
    trust_cases = _object_list(taxonomies, "trust_boundary_cases")
    return {
        split: tuple(item for item in trust_cases if _string(item, "split") == split.value)
        for split in split_order
    }


def _mini_clean_identity_overrides(
    mini_case_ids: tuple[str, ...],
    revisions: tuple[CadRevision, ...],
    views: tuple[ViewId, ...],
) -> dict[str, tuple[CadRevision, ViewId]]:
    clean_ids = [case_id for case_id in mini_case_ids if "-clean-" in case_id]
    pairs = tuple((revision, view) for revision in revisions for view in views)
    if len(clean_ids) < len(pairs):
        raise E1ProtocolError("mini clean cases cannot cover every revision/view pair")
    return {case_id: pairs[index % len(pairs)] for index, case_id in enumerate(clean_ids)}


def _stable_identity(
    case_id: str,
    revisions: tuple[CadRevision, ...],
    views: tuple[ViewId, ...],
) -> tuple[CadRevision, ViewId]:
    return (
        revisions[_digest_index(case_id, "revision", len(revisions))],
        views[_digest_index(case_id, "view", len(views))],
    )


def _defect_parameters(
    defect_document: dict[str, Any],
    severity: Severity,
) -> tuple[RecipeParameter, ...]:
    parameters = []
    for item in _object_list(defect_document, "severity_parameters"):
        value = item.get(severity.value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise E1ProtocolError("defect severity parameter must be numeric")
        parameters.append(
            RecipeParameter(
                name=_string(item, "name"),
                unit=_string(item, "unit"),
                value=value,
            )
        )
    return tuple(sorted(parameters, key=lambda item: item.name))


def _nuisance_parameters(
    nuisance_document: dict[str, Any],
    seed: int,
    case_id: str,
) -> tuple[RecipeParameter, ...]:
    parameters = []
    for item in _object_list(nuisance_document, "parameters"):
        supported = _object(item, "supported_normal_range")
        minimum = _number(supported, "minimum")
        maximum = _number(supported, "maximum")
        if minimum > maximum:
            raise E1ProtocolError("nuisance supported range is reversed")
        label = f"{case_id}:{_string(item, 'name')}"
        fraction = _digest_fraction(seed, label)
        if isinstance(supported["minimum"], int) and isinstance(supported["maximum"], int):
            integer_minimum = math.ceil(minimum)
            if integer_minimum == 0 and maximum >= 1:
                integer_minimum = 1
            integer_maximum = math.floor(maximum)
            span = integer_maximum - integer_minimum + 1
            value: int | float = integer_minimum + min(span - 1, math.floor(fraction * span))
        else:
            lower = minimum if minimum > 0 else maximum * 0.25
            value = round(lower + (maximum - lower) * fraction, 6)
            if value == -0.0:
                value = 0.0
        parameters.append(
            RecipeParameter(
                name=_string(item, "name"),
                unit=_string(item, "unit"),
                value=value,
            )
        )
    return tuple(sorted(parameters, key=lambda item: item.name))


def _part_universe(universe: dict[str, Any]) -> tuple[str, tuple[CadRevision, ...]]:
    parts = _object_list(universe, "parts")
    if len(parts) != 1:
        raise E1ProtocolError("E1 v1 requires exactly one synthetic part")
    part = parts[0]
    revisions = tuple(
        CadRevision(_string(item, "cad_revision")) for item in _object_list(part, "revisions")
    )
    return _string(part, "part_id"), revisions


def _validate_plan_contract(
    plans: tuple[E1CasePlan, ...],
    document: dict[str, Any],
    exact_mini_ids: tuple[str, ...],
) -> None:
    profiles = _object(document, "dataset_profiles")
    full_contract = _object(profiles, "full")
    mini_contract = _object(profiles, "mini")
    if len(plans) != _integer(full_contract, "case_count"):
        raise E1ProtocolError("full plan count does not match the frozen contract")
    case_ids = tuple(plan.case_id for plan in plans)
    if len(case_ids) != len(set(case_ids)):
        raise E1ProtocolError("full plan contains duplicate case IDs")
    recipe_ids = tuple(plan.recipe_id for plan in plans)
    if len(recipe_ids) != len(set(recipe_ids)):
        raise E1ProtocolError("recipe IDs must be unique and split-specific")
    mini = tuple(plan for plan in plans if plan.included_in_mini)
    if tuple(plan.case_id for plan in mini) != exact_mini_ids:
        raise E1ProtocolError("mini plan is not the frozen exact membership in canonical order")
    if len(mini) != _integer(mini_contract, "case_count") or len(mini) >= len(plans):
        raise E1ProtocolError("mini must be an exact strict 48-case subset")

    _validate_group_counts(plans, _object(full_contract, "group_counts"))
    _validate_group_counts(mini, _object(mini_contract, "group_counts"))
    composition = _object(profiles, "split_composition")
    mini_composition = _object(_object(profiles, "mini_selection"), "split_counts")
    for split in DatasetSplit:
        full_split = tuple(plan for plan in plans if plan.split is split)
        mini_split = tuple(plan for plan in mini if plan.split is split)
        full_split_contract = _object(composition, split.value)
        mini_split_contract = _object(mini_composition, split.value)
        if len(full_split) != _integer(full_split_contract, "case_count"):
            raise E1ProtocolError(f"full split count mismatch: {split.value}")
        if len(mini_split) != _integer(mini_split_contract, "case_count"):
            raise E1ProtocolError(f"mini split count mismatch: {split.value}")
        _validate_group_counts(full_split, _object(full_split_contract, "group_counts"))
        _validate_group_counts(mini_split, _object(mini_split_contract, "group_counts"))

    taxonomies = _object(document, "taxonomies")
    full_defects = Counter(
        plan.defect.defect_type.value for plan in plans if plan.defect is not None
    )
    mini_defects = Counter(
        plan.defect.defect_type.value for plan in mini if plan.defect is not None
    )
    for item in _object_list(taxonomies, "defects"):
        defect_type = _string(item, "type")
        if full_defects[defect_type] != _integer(item, "full_case_count"):
            raise E1ProtocolError(f"full defect count mismatch: {defect_type}")
        if mini_defects[defect_type] != _integer(item, "mini_case_count"):
            raise E1ProtocolError(f"mini defect count mismatch: {defect_type}")
    full_severities = Counter(
        plan.defect.severity.value for plan in plans if plan.defect is not None
    )
    mini_severities = Counter(
        plan.defect.severity.value for plan in mini if plan.defect is not None
    )
    for item in _object_list(taxonomies, "severities"):
        severity = _string(item, "severity")
        if full_severities[severity] != _integer(item, "full_case_count"):
            raise E1ProtocolError(f"full severity count mismatch: {severity}")
        if mini_severities[severity] != _integer(item, "mini_case_count"):
            raise E1ProtocolError(f"mini severity count mismatch: {severity}")
    full_nuisances = Counter(
        nuisance.nuisance_type.value for plan in plans for nuisance in plan.nuisances
    )
    mini_nuisances = Counter(
        nuisance.nuisance_type.value for plan in mini for nuisance in plan.nuisances
    )
    for item in _object_list(taxonomies, "nuisances"):
        nuisance_type = _string(item, "type")
        if full_nuisances[nuisance_type] != _integer(item, "full_case_count"):
            raise E1ProtocolError(f"full nuisance count mismatch: {nuisance_type}")
        if mini_nuisances[nuisance_type] != _integer(item, "mini_case_count"):
            raise E1ProtocolError(f"mini nuisance count mismatch: {nuisance_type}")

    if {plan.cad_revision for plan in mini} != set(CadRevision):
        raise E1ProtocolError("mini does not cover both revisions")
    if {plan.view_id for plan in mini} != set(ViewId):
        raise E1ProtocolError("mini does not cover all views")
    mini_pairs = {
        (plan.defect.defect_type, plan.defect.severity) for plan in mini if plan.defect is not None
    }
    if mini_pairs != {(defect, severity) for defect in DefectType for severity in Severity}:
        raise E1ProtocolError("mini does not cover every defect-type/severity pair")
    mini_strata = _object(_object(profiles, "mini_selection"), "strata")
    expected_trust = set(_string_list(mini_strata, "trust_scenario_ids"))
    actual_trust = {
        plan.trust_boundary.scenario_id for plan in mini if plan.trust_boundary is not None
    }
    if actual_trust != expected_trust:
        raise E1ProtocolError("mini trust scenarios do not match frozen strata")


def _validate_group_counts(
    plans: Iterable[E1CasePlan],
    expected: dict[str, Any],
) -> None:
    actual = Counter(plan.group.value for plan in plans)
    for group in CaseGroup:
        if actual[group.value] != _integer(expected, group.value):
            raise E1ProtocolError(f"group count mismatch: {group.value}")


def _render_pristine(plan: E1CasePlan, geometry: E1RenderGeometry) -> Image.Image:
    image = Image.new("RGB", (geometry.width, geometry.height), geometry.background)
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = geometry.plate_box
    radius = max(8, round(20 * min(geometry.width / 512, geometry.height / 384)))
    shadow_offset = max(4, round(8 * geometry.width / 512))
    draw.rounded_rectangle(
        (left + shadow_offset, top + shadow_offset, right + shadow_offset, bottom + shadow_offset),
        radius=radius,
        fill=(171, 179, 186),
    )
    draw.rounded_rectangle(
        geometry.plate_box,
        radius=radius,
        fill=geometry.plate_fill,
        outline=(78, 88, 96),
        width=max(2, round(4 * geometry.width / 512)),
    )
    line_step = max(6, round(13 * geometry.height / 384))
    for line_index, y in enumerate(range(top + line_step, bottom - line_step // 2, line_step)):
        delta = _digest_index(plan.case_id, f"texture:{line_index}", 7) - 3
        shade = max(0, min(255, 202 + delta))
        draw.line(
            (left + 15, y, right - 15, y),
            fill=(shade, min(255, shade + 4), min(255, shade + 7)),
        )
    _draw_hole(draw, geometry.left_hole_center, geometry.hole_radius, geometry.background)
    _draw_hole(draw, geometry.right_hole_center, geometry.hole_radius, geometry.background)
    draw.rounded_rectangle(
        geometry.slot_box,
        radius=max(6, round(20 * geometry.width / 512)),
        fill=(133, 143, 151),
        outline=(69, 78, 85),
        width=max(2, round(4 * geometry.width / 512)),
    )
    # A tiny generator-owned lot texture guarantees case-unique reference bytes
    # without altering part/revision identity or relying on metadata.
    marker_x = left + 24 + _digest_index(plan.case_id, "lot-marker-x", max(1, right - left - 48))
    marker_y = top + 24 + _digest_index(plan.case_id, "lot-marker-y", max(1, bottom - top - 48))
    marker_shade = 184 + _digest_index(plan.case_id, "lot-marker-shade", 8)
    draw.rectangle((marker_x, marker_y, marker_x + 1, marker_y + 1), fill=(marker_shade,) * 3)
    return image


def _draw_hole(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    radius: int,
    background: tuple[int, int, int],
) -> None:
    center_x, center_y = center
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=(57, 65, 72),
        outline=(24, 29, 33),
        width=5,
    )
    inner = max(2, radius - 11)
    draw.ellipse(
        (center_x - inner, center_y - inner, center_x + inner, center_y + inner),
        fill=background,
        outline=(121, 130, 137),
        width=3,
    )


def _apply_nuisance(
    image: Image.Image,
    nuisance: NuisanceSpec,
    seed: int,
    geometry: E1RenderGeometry,
) -> Image.Image:
    values = {parameter.name: float(parameter.value) for parameter in nuisance.parameters}
    nuisance_type = nuisance.nuisance_type
    if nuisance_type is NuisanceType.TRANSLATION:
        magnitude = round(_required_value(values, "max_abs_shift"))
        dx = magnitude * (1 if _digest_bit(seed, "translation-x-sign") else -1)
        dy_magnitude = max(1, magnitude // 2)
        dy = dy_magnitude * (1 if _digest_bit(seed, "translation-y-sign") else -1)
        return _translate_image(image, dx=dx, dy=dy, fill=geometry.background)
    if nuisance_type is NuisanceType.ROTATION:
        angle = _required_value(values, "max_abs_rotation")
        if not _digest_bit(seed, "rotation-sign"):
            angle = -angle
        return image.rotate(
            angle,
            resample=Image.Resampling.NEAREST,
            expand=False,
            fillcolor=geometry.background,
        )
    if nuisance_type is NuisanceType.SCALE:
        delta = _required_value(values, "max_abs_scale_delta")
        factor = 1 + delta if _digest_bit(seed, "scale-sign") else 1 - delta
        return _scale_image(image, factor=factor, fill=geometry.background)
    if nuisance_type is NuisanceType.EXPOSURE:
        delta = _required_value(values, "max_abs_rgb_gain_delta")
        gain = 1 + delta if _digest_bit(seed, "exposure-sign") else 1 - delta
        pixels = np.asarray(image, dtype=np.uint8).astype(np.float64)
        return Image.fromarray(np.clip(np.rint(pixels * gain), 0, 255).astype(np.uint8), "RGB")
    if nuisance_type is NuisanceType.DIRECTIONAL_SHADING:
        amplitude = _required_value(values, "gradient_amplitude")
        pixels = np.asarray(image, dtype=np.uint8).astype(np.float64)
        if _digest_bit(seed, "shading-axis"):
            gradient = np.linspace(-amplitude, amplitude, geometry.width, dtype=np.float64)[
                None, :, None
            ]
        else:
            gradient = np.linspace(-amplitude, amplitude, geometry.height, dtype=np.float64)[
                :, None, None
            ]
        return Image.fromarray(
            np.clip(np.rint(pixels * (1 + gradient)), 0, 255).astype(np.uint8),
            "RGB",
        )
    if nuisance_type is NuisanceType.GAUSSIAN_BLUR:
        sigma = _required_value(values, "sigma")
        return image.filter(ImageFilter.GaussianBlur(radius=sigma))
    if nuisance_type is NuisanceType.SENSOR_NOISE:
        deviation = _required_value(values, "rgb_standard_deviation")
        return _sensor_noise(image, deviation=deviation, seed=seed)
    if nuisance_type is NuisanceType.JPEG_COMPRESSION:
        loss = round(_required_value(values, "quality_loss_from_100"))
        buffer = io.BytesIO()
        image.save(
            buffer,
            format="JPEG",
            quality=100 - loss,
            subsampling=0,
            optimize=False,
            progressive=False,
        )
        with Image.open(io.BytesIO(buffer.getvalue())) as decoded:
            decoded.load()
            return decoded.convert("RGB")
    if nuisance_type is NuisanceType.BACKGROUND_FIXTURE:
        fraction = _required_value(values, "part_occlusion_fraction")
        output = image.copy()
        draw = ImageDraw.Draw(output)
        left, top, right, bottom = geometry.plate_box
        area = max(1, round((right - left) * (bottom - top) * fraction))
        depth = max(1, min(6, round(math.sqrt(area / 4))))
        length = max(1, min(right - left, math.ceil(area / depth)))
        from_left = _digest_bit(seed, "fixture-side")
        x0 = left if from_left else right - length
        draw.rectangle((x0, top - depth, x0 + length, top + depth), fill=(112, 118, 124))
        return output
    raise E1ProtocolError(f"unsupported nuisance recipe: {nuisance_type}")


def _translate_image(
    image: Image.Image,
    *,
    dx: int,
    dy: int,
    fill: tuple[int, int, int],
) -> Image.Image:
    output = Image.new("RGB", image.size, fill)
    width, height = image.size
    source_left = max(0, -dx)
    source_top = max(0, -dy)
    source_right = min(width, width - dx)
    source_bottom = min(height, height - dy)
    if source_left < source_right and source_top < source_bottom:
        crop = image.crop((source_left, source_top, source_right, source_bottom))
        output.paste(crop, (max(0, dx), max(0, dy)))
    return output


def _scale_image(
    image: Image.Image,
    *,
    factor: float,
    fill: tuple[int, int, int],
) -> Image.Image:
    width, height = image.size
    scaled_width = max(1, round(width * factor))
    scaled_height = max(1, round(height * factor))
    resized = image.resize((scaled_width, scaled_height), resample=Image.Resampling.NEAREST)
    output = Image.new("RGB", image.size, fill)
    source_left = max(0, (scaled_width - width) // 2)
    source_top = max(0, (scaled_height - height) // 2)
    crop = resized.crop(
        (
            source_left,
            source_top,
            min(scaled_width, source_left + width),
            min(scaled_height, source_top + height),
        )
    )
    output.paste(crop, ((width - crop.width) // 2, (height - crop.height) // 2))
    return output


def _sensor_noise(image: Image.Image, *, deviation: float, seed: int) -> Image.Image:
    pixels = np.asarray(image, dtype=np.uint8)
    sample_count = pixels.size
    raw = hashlib.shake_256(f"mvs-e1-sensor-noise-v1\0{seed}".encode()).digest(sample_count * 6)
    samples = np.frombuffer(raw, dtype=np.uint8).reshape(sample_count, 6).astype(np.float64)
    normalish = (samples.sum(axis=1) - 6 * 127.5) / math.sqrt(6 * (255**2 - 1) / 12)
    noise = np.rint(normalish.reshape(pixels.shape) * deviation)
    return Image.fromarray(
        np.clip(pixels.astype(np.float64) + noise, 0, 255).astype(np.uint8),
        "RGB",
    )


def _required_value(values: Mapping[str, float], name: str) -> float:
    value = values.get(name)
    if value is None or not math.isfinite(value) or value < 0:
        raise E1ProtocolError(f"invalid nuisance parameter: {name}")
    return value


def _digest_index(identity: str, label: str, size: int) -> int:
    if size <= 0:
        raise ValueError("digest choice size must be positive")
    payload = f"mvs-e1-planner-v1\0{identity}\0{label}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % size


def _digest_fraction(seed: int, label: str) -> float:
    payload = f"mvs-e1-parameter-v1\0{seed}\0{label}".encode()
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return value / (2**64 - 1)


def _digest_bit(seed: int, label: str) -> bool:
    return bool(_digest_index(str(seed), label, 2))


def _object(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise E1ProtocolError(f"{key} must be an object")
    return cast(dict[str, Any], value)


def _object_list(container: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = container.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise E1ProtocolError(f"{key} must be an object array")
    return cast(list[dict[str, Any]], value)


def _string(container: dict[str, Any], key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise E1ProtocolError(f"{key} must be a non-empty string")
    return value


def _string_list(container: dict[str, Any], key: str) -> list[str]:
    value = container.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise E1ProtocolError(f"{key} must be a non-empty string array")
    return cast(list[str], value)


def _integer(container: dict[str, Any], key: str) -> int:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise E1ProtocolError(f"{key} must be an integer")
    return value


def _number(container: dict[str, Any], key: str) -> float:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise E1ProtocolError(f"{key} must be numeric")
    return float(value)


def _boolean(container: dict[str, Any], key: str) -> bool:
    value = container.get(key)
    if not isinstance(value, bool):
        raise E1ProtocolError(f"{key} must be boolean")
    return value
