"""Test-only exporter for the frozen historical E1 v2 diagnostic matrix."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from manufacturing_vision_studio.canonical import canonical_json_bytes
from manufacturing_vision_studio.e1.diagnostics_v2 import build_scale_diagnostic_matrix
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol

MATRIX_PATH = PROJECT_ROOT / "configs" / "evaluation" / "e1-feasibility-diagnostic-108.json"


def matrix_projection() -> list[dict[str, object]]:
    """Project the preserved historical builder into checked data for tests only."""

    protocol = load_e1_v2_protocol()
    return [
        {
            "diagnostic_id": row.diagnostic_id,
            "seed": row.seed,
            "combination": row.combination,
            "cad_revision": row.cad_revision.value,
            "view_id": row.view_id.value,
            **row.diagnostic_truth_record(),
        }
        for row in build_scale_diagnostic_matrix(protocol)
    ]


def _matrix_bytes() -> bytes:
    return canonical_json_bytes(
        {"record_type": "e1_feasibility_diagnostic_matrix_v1", "rows": matrix_projection()}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = _matrix_bytes()
    if args.write:
        MATRIX_PATH.write_bytes(expected)
        return 0
    if MATRIX_PATH.read_bytes() != expected:
        raise SystemExit(
            "frozen E1 feasibility diagnostic matrix differs from historical projection"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
