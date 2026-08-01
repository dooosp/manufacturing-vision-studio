from __future__ import annotations

from hashlib import sha256

import pytest

from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.overlap_v2 import build_overlap_proof, verify_overlap_proof
from manufacturing_vision_studio.e1.protocol_v2 import E1V2ProtocolError


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _member(scope: EvaluationScope, ordinal: int, *, empty_mask: bool = False) -> dict[str, object]:
    stem = f"{scope.value}-{ordinal}"
    return {
        "scope": scope.value,
        "case_id": f"e1-v2-{stem}",
        "recipe_id": f"recipe/{stem}",
        "seed_family": f"family-{scope.value}",
        "seed": 900_000 + ordinal + list(EvaluationScope).index(scope) * 100,
        "reference_sha256": _digest(f"reference-{stem}"),
        "inspection_sha256": _digest(f"inspection-{stem}"),
        "authoritative_mask_sha256": (
            _digest("empty-mask") if empty_mask else _digest(f"mask-{stem}")
        ),
        "case_binding_sha256": _digest(f"binding-{stem}"),
        "expected_outcome": "NORMAL" if empty_mask else "ANOMALY",
        "defect_id": None if empty_mask else f"defect-{stem}",
        "group": "clean" if empty_mask else "defect",
    }


def _scope_cases() -> dict[EvaluationScope, list[dict[str, object]]]:
    return {
        scope: [_member(scope, 0, empty_mask=True), _member(scope, 1)] for scope in EvaluationScope
    }


def _retired_membership() -> list[dict[str, object]]:
    return [
        {
            **_member(EvaluationScope.DEVELOPMENT, 99),
            "case_id": "e1-calibration-clean-000",
            "recipe_id": "mvs-e1-recipe-v1/e1-calibration-clean-000",
            "seed_family": "e1-cal-clean-v1",
            "seed": 200000,
        }
    ]


def test_fabricated_disjoint_membership_and_retired_set_have_zero_overlap() -> None:
    """Expected repeated negative empty masks must not conceal a real leak."""
    proof = build_overlap_proof(_scope_cases(), _retired_membership())

    verify_overlap_proof(proof)
    assert proof["all_pairwise_zero"] is True
    assert proof["retired_v1_release_overlap_count"] == 0
    assert proof["raw_empty_authoritative_mask_duplicates"] > 0


def test_overlap_verifier_recomputes_instead_of_trusting_reported_zero() -> None:
    """A forged zero counter must fail when member hashes now overlap."""
    proof = build_overlap_proof(_scope_cases(), _retired_membership())
    proof["pairs"][0]["case_binding_overlap_count"] = 0
    proof["pairs"][0]["left_members"][0]["case_binding_sha256"] = proof["pairs"][0][
        "right_members"
    ][0]["case_binding_sha256"]

    with pytest.raises(E1V2ProtocolError, match="overlap"):
        verify_overlap_proof(proof)
