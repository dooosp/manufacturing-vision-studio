"""Deterministic E1 v2 planning with read-only v1 rendering primitives."""

from __future__ import annotations

from dataclasses import replace

from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain import (
    CaseGroup,
    DatasetProfile,
    DatasetSplit,
    E1CasePlan,
)
from manufacturing_vision_studio.e1.domain_v2 import (
    E1V2CasePlan,
    E1V2GeneratedCase,
    EvaluationScope,
)
from manufacturing_vision_studio.e1.generator import E1Generator, _apply_nuisance, _render_pristine
from manufacturing_vision_studio.e1.oracle import geometry_for_case, render_defect_truth
from manufacturing_vision_studio.e1.protocol_v2 import (
    E1V2Protocol,
    E1V2ProtocolError,
    load_e1_v2_protocol,
)


class E1V2Generator:
    """Plan the v2 scopes; only caller-selected members are rendered."""

    def __init__(self, protocol: E1V2Protocol | None = None) -> None:
        self.protocol = protocol or load_e1_v2_protocol()
        self._v1_generator = E1Generator()
        self._plans: dict[EvaluationScope, tuple[E1V2CasePlan, ...]] = {}

    def plan_cases(self, scope: EvaluationScope | str) -> tuple[E1V2CasePlan, ...]:
        resolved = EvaluationScope(scope)
        if resolved not in self._plans:
            self._plans[resolved] = self._build_scope_plan(resolved)
        return self._plans[resolved]

    def generate_case(self, plan: E1V2CasePlan) -> E1V2GeneratedCase:
        if plan not in self.plan_cases(plan.scope):
            raise E1V2ProtocolError("case plan is not part of this v2 generator contract")
        render_plan = plan._render_plan
        v1_protocol = self._v1_generator.protocol
        width, height = v1_protocol.image_size
        geometry = geometry_for_case(
            render_plan.cad_revision,
            render_plan.view_id,
            image_size=(width, height),
            feature_regions=self.protocol.feature_ownership(
                render_plan.cad_revision, render_plan.view_id
            ).feature_boxes,
        )
        reference = _render_pristine(render_plan, geometry)
        mask = Image.new("L", (width, height), 0)
        if render_plan.group is CaseGroup.DEFECT:
            if render_plan.defect is None:
                raise E1V2ProtocolError("v2 defect plan is missing truth")
            inspection, mask = render_defect_truth(
                reference,
                render_plan.defect,
                seed=render_plan.seed,
                geometry=geometry,
            )
        elif render_plan.group is CaseGroup.NUISANCE:
            inspection = reference.copy()
            for nuisance in render_plan.nuisances:
                inspection = _apply_nuisance(inspection, nuisance, render_plan.seed, geometry)
        else:
            inspection = reference.copy()
        reference_bytes = encode_png(reference, mode="RGB")
        inspection_bytes = encode_png(inspection, mode="RGB")
        mask_bytes = encode_png(mask, mode="L")
        reference_sha256 = sha256_bytes(reference_bytes)
        inspection_sha256 = sha256_bytes(inspection_bytes)
        authoritative_mask_sha256 = sha256_bytes(mask_bytes)
        case_binding_sha256 = self.protocol.case_binding_sha256(
            scope=plan.scope,
            case_id=plan.case_id,
            recipe_id=plan.recipe_id,
            seed_family=plan.seed_family,
            seed=plan.seed,
            reference_sha256=reference_sha256,
            inspection_sha256=inspection_sha256,
            authoritative_mask_sha256=authoritative_mask_sha256,
            expected_outcome=plan.expected_outcome.value,
            defect_id=plan.defect_id,
        )
        return E1V2GeneratedCase(
            plan=plan,
            reference_bytes=reference_bytes,
            inspection_bytes=inspection_bytes,
            authoritative_mask_bytes=mask_bytes,
            reference_sha256=reference_sha256,
            inspection_sha256=inspection_sha256,
            authoritative_mask_sha256=authoritative_mask_sha256,
            case_binding_sha256=case_binding_sha256,
        )

    def _build_scope_plan(self, scope: EvaluationScope) -> tuple[E1V2CasePlan, ...]:
        templates = self._templates_for_scope(scope)
        plans: list[E1V2CasePlan] = []
        for group in CaseGroup:
            seed_family, start, count = self.protocol.seed_block(scope, group)
            if count != self.protocol.scope_group_count(scope, group):
                raise E1V2ProtocolError(
                    f"scope/seed count mismatch for {scope.value}/{group.value}"
                )
            if len(templates[group]) < count:
                raise E1V2ProtocolError(
                    f"v1 render templates are insufficient for {scope.value}/{group.value}"
                )
            for ordinal in range(count):
                case_id = self.protocol.case_id_format.format(
                    scope=scope.value,
                    group=group.value,
                    ordinal=ordinal,
                )
                template = templates[group][ordinal]
                defect = template.defect
                if defect is not None:
                    defect = replace(defect, defect_id=f"{case_id}-truth-001")
                render_plan = replace(
                    template,
                    case_id=case_id,
                    profile_membership=(DatasetProfile.FULL,),
                    seed_family=seed_family,
                    seed=start + ordinal,
                    recipe_id=f"mvs-e1-recipe-v2/{case_id}",
                    recipe_version=self.protocol.recipe_version,
                    defect=defect,
                )
                plans.append(
                    E1V2CasePlan(
                        scope=scope,
                        case_id=case_id,
                        recipe_id=render_plan.recipe_id,
                        seed_family=seed_family,
                        seed=start + ordinal,
                        group=group,
                        ordinal=ordinal,
                        expected_outcome=render_plan.expected_outcome,
                        defect_id=None if defect is None else defect.defect_id,
                        _render_plan=render_plan,
                    )
                )
        expected = self.protocol.scope_counts[scope]
        if len(plans) != expected or len({plan.case_id for plan in plans}) != expected:
            raise E1V2ProtocolError(f"v2 scope membership is invalid for {scope.value}")
        return tuple(plans)

    def _templates_for_scope(
        self, scope: EvaluationScope
    ) -> dict[CaseGroup, tuple[E1CasePlan, ...]]:
        source_split = {
            EvaluationScope.DEVELOPMENT: DatasetSplit.DEVELOPMENT,
            EvaluationScope.SMOKE: DatasetSplit.DEVELOPMENT,
            EvaluationScope.CALIBRATION: DatasetSplit.CALIBRATION,
            EvaluationScope.RELEASE_TEST: DatasetSplit.TEST,
        }[scope]
        full = self._v1_generator.plan_cases(DatasetProfile.FULL)
        return {
            group: tuple(
                plan for plan in full if plan.split is source_split and plan.group is group
            )
            for group in CaseGroup
        }
