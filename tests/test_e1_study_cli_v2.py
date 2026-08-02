from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from manufacturing_vision_studio.e1 import study_cli_v2 as cli_module
from manufacturing_vision_studio.e1.study_cli_v2 import main
from manufacturing_vision_studio.e1.study_runner_v2 import StudyStateError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "argv",
    (
        ["phase1", "--output-root", "/tmp/out"],
        ["phase1", "--mode", "NEAREST"],
        ["phase1", "--seed", "1"],
        ["phase2", "--scope", "development"],
    ),
)
def test_cli_rejects_every_override(argv: list[str]) -> None:
    assert main(argv) == 2


@pytest.mark.parametrize(
    ("command", "method"),
    (
        ("validate-implementation", "validate_implementation"),
        ("phase0", "phase0"),
        ("phase1", "phase1"),
        ("feature-oracle", "feature_oracle"),
        ("phase2", "phase2"),
        ("status", "status"),
        ("finalize", "finalize"),
        ("verify", "verify"),
    ),
)
def test_cli_dispatches_each_fixed_command_once(
    command: str,
    method: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    class FakeRunner:
        def __getattr__(self, name: str) -> object:
            def invoke() -> object:
                calls.append(name)
                return {"ok": True, "method": name}

            return invoke

    constructions = 0

    def build() -> FakeRunner:
        nonlocal constructions
        constructions += 1
        return FakeRunner()

    monkeypatch.setattr(cli_module.study_runner_v2.StudyRunner, "from_default", build)

    exit_code = main([command])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert constructions == 1
    assert calls == [method]
    assert json.loads(captured.out) == {
        "command": command,
        "result": {"ok": True, "method": method},
    }
    assert captured.err == ""


def test_cli_parse_rejection_never_constructs_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden() -> object:
        raise AssertionError("parse rejection cannot construct the runner")

    monkeypatch.setattr(cli_module.study_runner_v2.StudyRunner, "from_default", forbidden)

    assert main(["unknown"]) == 2


def test_cli_operational_failure_has_one_stable_exit_code_and_no_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = SimpleNamespace(
        phase1=lambda: (_ for _ in ()).throw(StudyStateError("packet is invalid"))
    )
    monkeypatch.setattr(
        cli_module.study_runner_v2.StudyRunner,
        "from_default",
        lambda: runner,
    )

    exit_code = main(["phase1"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "study operation failed: packet is invalid\n"
    assert "Traceback" not in captured.err


def test_cli_entry_point_is_exactly_registered() -> None:
    document = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert document["project"]["scripts"]["mvs-e1-study"] == (
        "manufacturing_vision_studio.e1.study_cli_v2:main"
    )


def test_makefile_adds_only_fixed_one_command_study_targets() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    targets = {
        "validate-e1-study-implementation": "validate-implementation",
        "e1-study-phase0": "phase0",
        "e1-study-phase1": "phase1",
        "e1-study-feature-oracle": "feature-oracle",
        "e1-study-phase2": "phase2",
        "e1-study-status": "status",
        "finalize-e1-study": "finalize",
        "verify-e1-study": "verify",
    }
    for target, command in targets.items():
        assert f"\n{target}:\n\tuv run mvs-e1-study {command}\n" in makefile
    assert "\ne1-study:\n" not in makefile
    assert (
        "validate:\n"
        "\tuv run ruff check .\n"
        "\tuv run mypy src\n"
        "\tuv run pytest\n"
        "\tnpm --prefix web run check\n"
        "\tnpm --prefix web run test:e2e\n"
    ) in makefile
