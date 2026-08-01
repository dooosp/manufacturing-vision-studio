"""Verify immutable E1 v1 public history without ignored runtime artifacts."""

from __future__ import annotations

import json

from manufacturing_vision_studio.e1.protocol_v2 import verify_e1_v1_history


def main() -> int:
    print(json.dumps(verify_e1_v1_history(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
