from __future__ import annotations

import json
from pathlib import Path

import pytest

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
