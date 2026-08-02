"""Fixed, override-free command line surface for the E1 feasibility study."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from manufacturing_vision_studio.e1 import study_runner_v2

_OPERATIONAL_ERROR = 1
_COMMANDS = (
    "validate-implementation",
    "phase0",
    "phase1",
    "feature-oracle",
    "phase2",
    "status",
    "finalize",
    "verify",
)


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one protocol-fixed command and return a stable process status."""

    parser = argparse.ArgumentParser(
        prog="mvs-e1-study",
        description="Run or inspect the sealed E1 feasibility study",
        add_help=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in _COMMANDS:
        subparsers.add_parser(command, add_help=False)
    try:
        namespace = parser.parse_args(argv)
    except SystemExit:
        return 2

    command = cast(str, namespace.command)
    operations: Mapping[
        str,
        Callable[[study_runner_v2.StudyRunner], object],
    ] = {
        "validate-implementation": lambda runner: runner.validate_implementation(),
        "phase0": lambda runner: runner.phase0(),
        "phase1": lambda runner: runner.phase1(),
        "feature-oracle": lambda runner: runner.feature_oracle(),
        "phase2": lambda runner: runner.phase2(),
        "status": lambda runner: runner.status(),
        "finalize": lambda runner: runner.finalize(),
        "verify": lambda runner: runner.verify(),
    }
    try:
        runner = study_runner_v2.StudyRunner.from_default()
        result = operations[command](runner)
        output = {"command": command, "result": _json_value(result)}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"study operation failed: {exc}", file=sys.stderr)
        return _OPERATIONAL_ERROR
    return 0


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
            if not field.name.startswith("_")
        }
    raise TypeError(f"study command returned unsupported output: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
