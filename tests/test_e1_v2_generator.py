from __future__ import annotations

from dataclasses import replace

import pytest

from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (EvaluationScope.DEVELOPMENT, 120),
        (EvaluationScope.SMOKE, 48),
    ],
)
def test_v2_planner_has_exact_scope_counts(
    scope: EvaluationScope,
    expected: int,
) -> None:
    """A changed scope allocation must not silently change corpus membership."""
    plans = E1V2Generator().plan_cases(scope)

    assert len(plans) == expected
    assert {plan.scope for plan in plans} == {scope}
    assert len({plan.case_id for plan in plans}) == expected


def test_v2_same_plan_renders_identical_case_bytes() -> None:
    """A deterministic plan must reproduce its complete source-byte identity."""
    generator = E1V2Generator()
    plan = generator.plan_cases(EvaluationScope.SMOKE)[0]

    first = generator.generate_case(plan)
    second = generator.generate_case(plan)

    assert first.reference_sha256 == second.reference_sha256
    assert first.inspection_sha256 == second.inspection_sha256
    assert first.authoritative_mask_sha256 == second.authoritative_mask_sha256
    assert first.case_binding_sha256 == second.case_binding_sha256


def test_v2_generator_rejects_an_unregistered_plan() -> None:
    """Replacing a plan identity must not permit rendering outside the contract."""
    generator = E1V2Generator()
    plan = generator.plan_cases(EvaluationScope.SMOKE)[0]

    with pytest.raises(ValueError, match="contract"):
        generator.generate_case(replace(plan, case_id="e1-v2-smoke-clean-999"))
