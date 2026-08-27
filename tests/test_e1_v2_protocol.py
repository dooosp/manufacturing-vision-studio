from __future__ import annotations

from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol


def test_v2_protocol_pins_versions_counts_and_seed_blocks() -> None:
    """A version or seed-range drift must fail before corpus planning begins."""
    protocol = load_e1_v2_protocol()

    assert protocol.protocol_version == "2.0.0"
    assert protocol.dataset_version == "2.0.0"
    assert protocol.pipeline_version == "1.2.0"
    assert protocol.model_version == "1.2.0"
    assert protocol.scope_counts == {
        EvaluationScope.DEVELOPMENT: 120,
        EvaluationScope.SMOKE: 48,
        EvaluationScope.CALIBRATION: 120,
        EvaluationScope.RELEASE_TEST: 240,
    }
    assert protocol.seed_starts == {
        "development": (400000, 410000, 420000, 430000),
        "smoke": (440000, 450000, 460000, 470000),
        "calibration": (500000, 510000, 520000, 530000),
        "release_test": (700000, 710000, 720000, 730000),
    }
