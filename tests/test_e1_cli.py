from __future__ import annotations

import pytest

from manufacturing_vision_studio.cli import _require_e1_pass


def test_require_e1_pass_accepts_only_pass_verdict() -> None:
    _require_e1_pass({"verdict": "PASS"})

    for result in ({"verdict": "HOLD"}, {"verdict": "UNKNOWN"}, {}):
        with pytest.raises(SystemExit) as exc_info:
            _require_e1_pass(result)
        assert exc_info.value.code == 1
