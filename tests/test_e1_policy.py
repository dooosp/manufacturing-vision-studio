from __future__ import annotations

import pytest

from manufacturing_vision_studio.e1.policy import classify_score


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, "NORMAL"),
        (0.00249999, "NORMAL"),
        (0.0025, "ANOMALY"),
        (1.0, "ANOMALY"),
    ],
)
def test_locked_threshold_edge_is_inclusive(score: float, expected: str) -> None:
    assert classify_score(score, 0.0025) == expected


@pytest.mark.parametrize(("score", "threshold"), [(-0.1, 0.5), (1.1, 0.5), (0.5, -0.1)])
def test_classification_rejects_invalid_bounds(score: float, threshold: float) -> None:
    with pytest.raises(ValueError, match="within"):
        classify_score(score, threshold)
