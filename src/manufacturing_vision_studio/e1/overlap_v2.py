"""Canonical, recomputable E1 v2 corpus-overlap proofs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import cast

from manufacturing_vision_studio.canonical import canonical_json_hash
from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.protocol_v2 import E1V2ProtocolError

_REQUIRED = (
    "case_id",
    "recipe_id",
    "seed_family",
    "seed",
    "reference_sha256",
    "inspection_sha256",
    "authoritative_mask_sha256",
    "case_binding_sha256",
    "expected_outcome",
    "defect_id",
    "group",
)
_IDENTITY_KEYS = (
    "case_id",
    "recipe_id",
    "seed_family_seed",
    "reference_sha256",
    "inspection_sha256",
    "case_binding_sha256",
    "nonempty_authoritative_mask_sha256",
)


def build_overlap_proof(
    scope_cases: Mapping[EvaluationScope, Sequence[Mapping[str, object]]],
    retired_v1_cases: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build a report whose counters can be recomputed from included members."""
    normalized = {
        scope: _normalize_members(scope_cases.get(scope), scope=scope.value, require_sources=True)
        for scope in EvaluationScope
    }
    retired = _normalize_members(retired_v1_cases, scope=None, require_sources=False)
    pairs = [
        _pair_record(left, right, normalized[left], normalized[right])
        for left, right in combinations(EvaluationScope, 2)
    ]
    retired_pairs = [
        _retired_pair_record(scope, normalized[scope], retired)
        for scope in (EvaluationScope.CALIBRATION, EvaluationScope.RELEASE_TEST)
    ]
    raw_empty_duplicates = _raw_empty_duplicate_count(normalized)
    all_pairwise_zero = all(_pair_is_zero(pair) for pair in pairs) and all(
        _pair_is_zero(pair) for pair in retired_pairs
    )
    document: dict[str, object] = {
        "schema_version": "1.0.0",
        "scope_order": [scope.value for scope in EvaluationScope],
        "pairs": pairs,
        "retired_v1_pairs": retired_pairs,
        "all_pairwise_zero": all_pairwise_zero,
        "retired_v1_release_overlap_count": sum(_total_overlap(pair) for pair in retired_pairs),
        "raw_empty_authoritative_mask_duplicates": raw_empty_duplicates,
    }
    document["proof_sha256"] = canonical_json_hash(document)
    return document


def verify_overlap_proof(document: Mapping[str, object]) -> None:
    """Fail closed if raw membership, counters, or the final hash is forged."""
    if document.get("schema_version") != "1.0.0":
        raise E1V2ProtocolError("overlap proof schema version is invalid")
    pairs = document.get("pairs")
    retired_pairs = document.get("retired_v1_pairs")
    if not isinstance(pairs, list) or not isinstance(retired_pairs, list):
        raise E1V2ProtocolError("overlap proof pairs are invalid")
    expected_pairs = list(combinations(EvaluationScope, 2))
    if len(pairs) != len(expected_pairs) or len(retired_pairs) != 2:
        raise E1V2ProtocolError("overlap proof pair coverage is incomplete")
    recomputed_pairs: list[dict[str, object]] = []
    all_members: dict[EvaluationScope, list[dict[str, object]]] = {}
    for pair, (left, right) in zip(pairs, expected_pairs, strict=True):
        if not isinstance(pair, Mapping):
            raise E1V2ProtocolError("overlap proof pair is invalid")
        left_members = _normalize_members(
            pair.get("left_members"), scope=left.value, require_sources=True
        )
        right_members = _normalize_members(
            pair.get("right_members"), scope=right.value, require_sources=True
        )
        recomputed = _pair_record(left, right, left_members, right_members)
        _require_pair_equal(pair, recomputed)
        _record_scope_members(all_members, left, left_members)
        _record_scope_members(all_members, right, right_members)
        recomputed_pairs.append(recomputed)
    recomputed_retired: list[dict[str, object]] = []
    retired_scopes = (EvaluationScope.CALIBRATION, EvaluationScope.RELEASE_TEST)
    for pair, scope in zip(retired_pairs, retired_scopes, strict=True):
        if not isinstance(pair, Mapping):
            raise E1V2ProtocolError("retired overlap proof pair is invalid")
        left_members = _normalize_members(
            pair.get("left_members"), scope=scope.value, require_sources=True
        )
        retired_members = _normalize_members(
            pair.get("retired_members"), scope=None, require_sources=False
        )
        recomputed = _retired_pair_record(scope, left_members, retired_members)
        _require_pair_equal(pair, recomputed)
        _record_scope_members(all_members, scope, left_members)
        recomputed_retired.append(recomputed)
    if set(all_members) != set(EvaluationScope):
        raise E1V2ProtocolError("overlap proof lacks v2 scope members")
    _ensure_cross_pair_members_consistent(pairs, all_members)
    expected_empty_duplicates = _raw_empty_duplicate_count(all_members)
    if document.get("raw_empty_authoritative_mask_duplicates") != expected_empty_duplicates:
        raise E1V2ProtocolError("overlap proof empty-mask count does not recompute")
    expected_all_zero = all(_pair_is_zero(pair) for pair in recomputed_pairs) and all(
        _pair_is_zero(pair) for pair in recomputed_retired
    )
    if document.get("all_pairwise_zero") is not expected_all_zero:
        raise E1V2ProtocolError("overlap proof zero claim does not recompute")
    expected_retired_count = sum(_total_overlap(pair) for pair in recomputed_retired)
    if document.get("retired_v1_release_overlap_count") != expected_retired_count:
        raise E1V2ProtocolError("overlap proof retired count does not recompute")
    projection = {key: value for key, value in document.items() if key != "proof_sha256"}
    if document.get("proof_sha256") != canonical_json_hash(projection):
        raise E1V2ProtocolError("overlap proof hash does not recompute")


def _pair_record(
    left: EvaluationScope,
    right: EvaluationScope,
    left_members: list[dict[str, object]],
    right_members: list[dict[str, object]],
) -> dict[str, object]:
    counts = _overlap_counts(left_members, right_members)
    return {
        "left_scope": left.value,
        "right_scope": right.value,
        "left_members": left_members,
        "right_members": right_members,
        **{f"{key}_overlap_count": value for key, value in counts.items()},
    }


def _retired_pair_record(
    scope: EvaluationScope,
    left_members: list[dict[str, object]],
    retired_members: list[dict[str, object]],
) -> dict[str, object]:
    counts = _overlap_counts(left_members, retired_members)
    return {
        "left_scope": scope.value,
        "right_scope": "retired_v1_release_membership",
        "left_members": left_members,
        "retired_members": retired_members,
        **{f"{key}_overlap_count": value for key, value in counts.items()},
    }


def _normalize_members(
    raw_members: object,
    *,
    scope: str | None,
    require_sources: bool,
) -> list[dict[str, object]]:
    if not isinstance(raw_members, Sequence) or isinstance(raw_members, (str, bytes)):
        raise E1V2ProtocolError("overlap members must be a sequence")
    members: list[dict[str, object]] = []
    seen: dict[str, set[object]] = {key: set() for key in _IDENTITY_KEYS}
    for raw in raw_members:
        if not isinstance(raw, Mapping):
            raise E1V2ProtocolError("overlap member must be an object")
        member = dict(raw)
        required = (
            _REQUIRED
            if require_sources
            else (*_REQUIRED[:4], "expected_outcome", "defect_id", "group")
        )
        if any(key not in member for key in required):
            raise E1V2ProtocolError("overlap member lacks a required identity")
        if scope is not None and member.get("scope") != scope:
            raise E1V2ProtocolError("overlap member scope is invalid")
        if not isinstance(member["case_id"], str) or not isinstance(member["recipe_id"], str):
            raise E1V2ProtocolError("overlap member IDs must be strings")
        if isinstance(member["seed"], bool) or not isinstance(member["seed"], int):
            raise E1V2ProtocolError("overlap member seed must be an integer")
        if require_sources and not all(isinstance(member[key], str) for key in _REQUIRED[4:8]):
            raise E1V2ProtocolError("overlap member source hashes must be strings")
        if member.get("authoritative_mask_sha256", False):
            _validate_empty_mask_policy(member)
        for key in _IDENTITY_KEYS:
            identity = _member_identity(member, key)
            if identity is not None:
                if identity in seen[key]:
                    raise E1V2ProtocolError("overlap members contain duplicate identities")
                seen[key].add(identity)
        members.append(member)
    return sorted(members, key=lambda item: cast(str, item["case_id"]))


def _validate_empty_mask_policy(member: Mapping[str, object]) -> None:
    # A raw digest alone cannot prove emptiness. Empty-mask sharing is therefore
    # counted only among the two explicitly negative groups; non-empty masks are
    # enforced as a leak key below.
    if member.get("defect_id") is None and member.get("group") not in {
        "clean",
        "nuisance",
        "trust_boundary",
    }:
        raise E1V2ProtocolError("overlap member has invalid negative mask declaration")


def _member_identity(member: Mapping[str, object], key: str) -> object | None:
    if key == "seed_family_seed":
        return member["seed_family"], member["seed"]
    if key == "nonempty_authoritative_mask_sha256":
        if member.get("group") in {"clean", "nuisance"} and member.get("defect_id") is None:
            return None
        return member.get("authoritative_mask_sha256")
    return member.get(key)


def _overlap_counts(
    left: Sequence[Mapping[str, object]], right: Sequence[Mapping[str, object]]
) -> dict[str, int]:
    return {
        key: len(
            {identity for member in left if (identity := _member_identity(member, key)) is not None}
            & {
                identity
                for member in right
                if (identity := _member_identity(member, key)) is not None
            }
        )
        for key in _IDENTITY_KEYS
    }


def _pair_is_zero(pair: Mapping[str, object]) -> bool:
    return all(pair.get(f"{key}_overlap_count") == 0 for key in _IDENTITY_KEYS)


def _total_overlap(pair: Mapping[str, object]) -> int:
    return sum(cast(int, pair[f"{key}_overlap_count"]) for key in _IDENTITY_KEYS)


def _raw_empty_duplicate_count(
    scope_members: Mapping[EvaluationScope, Sequence[Mapping[str, object]]],
) -> int:
    masks: list[str] = []
    for members in scope_members.values():
        for member in members:
            if member.get("group") in {"clean", "nuisance"} and member.get("defect_id") is None:
                digest = member.get("authoritative_mask_sha256")
                if isinstance(digest, str):
                    masks.append(digest)
    return len(masks) - len(set(masks))


def _require_pair_equal(actual: Mapping[str, object], expected: Mapping[str, object]) -> None:
    if any(actual.get(key) != value for key, value in expected.items()):
        raise E1V2ProtocolError("overlap proof counters or members do not recompute")


def _record_scope_members(
    target: dict[EvaluationScope, list[dict[str, object]]],
    scope: EvaluationScope,
    members: list[dict[str, object]],
) -> None:
    existing = target.setdefault(scope, members)
    if existing != members:
        raise E1V2ProtocolError("overlap proof scope members disagree across pairs")


def _ensure_cross_pair_members_consistent(
    pairs: Sequence[object], all_members: Mapping[EvaluationScope, Sequence[Mapping[str, object]]]
) -> None:
    del pairs
    for scope, members in all_members.items():
        _normalize_members(members, scope=scope.value, require_sources=True)
