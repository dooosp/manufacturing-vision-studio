from __future__ import annotations

from manufacturing_vision_studio.e1.baseline import evaluate_v0_1_baseline
from manufacturing_vision_studio.e1.protocol import load_e1_protocol


def test_published_v010_is_an_executable_e1_gate() -> None:
    result = evaluate_v0_1_baseline(load_e1_protocol())

    assert result.bundle_attempts == 1
    assert result.bundle_successes == 1
    assert result.v0_1_regression is True
    assert all(check["passed"] for check in result.checks)
