from __future__ import annotations

import json
from pathlib import Path

import pytest

from manufacturing_vision_studio.canonical import canonical_json_hash
from manufacturing_vision_studio.e1.protocol_v2 import (
    E1V2ProtocolError,
    load_retired_v1_release_membership,
    verify_e1_v1_history,
)


def test_v1_history_and_retirement_artifacts_fail_on_mutation(tmp_path: Path) -> None:
    """Historical release membership must be self-authenticating and immutable."""
    assert verify_e1_v1_history()["verdict"] == "HOLD"
    retired = load_retired_v1_release_membership()
    assert retired.calibration_member_count == 120
    assert retired.mini_test_member_count == 24

    tampered_path = tmp_path / "retired.json"
    document = json.loads(retired.source_path.read_text(encoding="utf-8"))
    document["members"][0]["case_id"] = "tampered"
    tampered_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(E1V2ProtocolError, match="retired"):
        load_retired_v1_release_membership(tampered_path)


def test_retired_membership_rejects_a_rehashed_protocol_id_tamper(tmp_path: Path) -> None:
    """The retired set must remain bound to the exact v1 protocol identity."""
    retired = load_retired_v1_release_membership()
    document = json.loads(retired.source_path.read_text(encoding="utf-8"))
    document["v1_protocol_id"] = "tampered-e1"
    document["membership_sha256"] = canonical_json_hash(
        {key: value for key, value in document.items() if key != "membership_sha256"}
    )
    tampered_path = tmp_path / "retired-rehashed.json"
    tampered_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(E1V2ProtocolError, match="retired"):
        load_retired_v1_release_membership(tampered_path)
