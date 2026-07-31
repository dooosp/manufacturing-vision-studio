from __future__ import annotations

import math

import pytest

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)


def test_canonical_json_is_sorted_compact_utf8_and_byte_stable() -> None:
    value = {"z": 1, "nested": {"b": None, "a": True}, "a": "한글"}
    expected = '{"a":"한글","nested":{"a":true,"b":null},"z":1}'.encode()

    assert canonical_json_bytes(value) == expected
    assert canonical_json_bytes(value) == canonical_json_bytes(value)
    assert canonical_json_hash(value) == (
        "29cde28bf546525208e87799bdf34ee75f76336f2ca1982462dbce2b26e78c33"
    )
    assert canonical_json_hash(value) == sha256_bytes(expected)


def test_project_canonical_profile_preserves_json_number_kind() -> None:
    # mvs-canonical-json/v1 deliberately keeps Python JSON's numeric spelling;
    # it is a project profile and does not claim RFC 8785/JCS conformance.
    assert canonical_json_bytes({"whole": 1.0, "negative_zero": -0.0}) == (
        b'{"negative_zero":-0.0,"whole":1.0}'
    )


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_canonical_json_rejects_non_finite_numbers(non_finite: float) -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"unsafe_metric": non_finite})
