from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _PROJECT_ROOT / ".github/workflows/ci.yml"
_CHECKOUT_ACTION = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
_SETUP_NODE_ACTION = "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444"


def _workflow() -> dict[str, Any]:
    document = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return cast(dict[str, Any], document)


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    matching = [step for step in steps if isinstance(step, dict) and step.get("name") == name]
    assert len(matching) == 1, f"expected one {name!r} step, got {len(matching)}"
    return cast(dict[str, Any], matching[0])


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nset -eu\n{body}", encoding="utf-8")
    path.chmod(0o755)


def test_python_checkout_preserves_historical_tags_and_blobs() -> None:
    python_job = cast(dict[str, Any], _workflow()["jobs"]["python"])
    checkout = _step(python_job, "Check out repository")
    inputs = cast(dict[str, Any], checkout["with"])

    assert checkout["uses"] == _CHECKOUT_ACTION
    assert inputs.get("persist-credentials") is False
    assert inputs.get("fetch-depth") == 0
    assert "filter" not in inputs
    assert "sparse-checkout" not in inputs


def test_python_setup_provisions_reviewed_account_local_toolchain(
    tmp_path: Path,
) -> None:
    python_job = cast(dict[str, Any], _workflow()["jobs"]["python"])
    setup_node = _step(python_job, "Set up Node.js")
    setup_node_inputs = cast(dict[str, Any], setup_node["with"])
    install_step = _step(python_job, "Install locked Python environment")

    assert setup_node["uses"] == _SETUP_NODE_ACTION
    assert setup_node_inputs.get("node-version") == "${{ env.NODE_VERSION }}"
    assert setup_node_inputs.get("package-manager-cache") is False

    account_home = tmp_path / "account-home"
    poison_home = tmp_path / "poison-home"
    python_scripts = tmp_path / "python-scripts"
    fake_bin = tmp_path / "fake-bin"
    node_prefix = tmp_path / "toolcache/node/22.0.0/x64"
    invocation_dir = tmp_path / "invocations"
    github_path = tmp_path / "github-path"
    invocation_dir.mkdir()
    python_scripts.mkdir()
    (node_prefix / "share").mkdir(parents=True)
    (node_prefix / "share/node-distribution-marker").write_text(
        "complete distribution\n",
        encoding="utf-8",
    )

    _write_executable(
        fake_bin / "python",
        """
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
  exit 0
fi
if [ "${1:-}" = "-c" ]; then
  case "${2:-}" in
    *pwd.getpwuid*) printf '%s\\n' "${FAKE_ACCOUNT_HOME}" ;;
    *sysconfig.get_path*) printf '%s\\n' "${FAKE_PYTHON_SCRIPTS}/uv" ;;
    *) exit 91 ;;
  esac
  exit 0
fi
exit 92
""",
    )
    _write_executable(
        python_scripts / "uv",
        'printf \'%s\\n\' "$0" > "${FAKE_INVOCATION_DIR}/uv"\n',
    )
    _write_executable(
        node_prefix / "bin/node",
        'printf \'%s\\n\' "$0" > "${FAKE_INVOCATION_DIR}/node"\n',
    )
    npm_cli = node_prefix / "lib/node_modules/npm/bin/npm-cli.js"
    _write_executable(
        npm_cli,
        'printf \'%s\\n\' "$0" > "${FAKE_INVOCATION_DIR}/npm"\n',
    )
    (node_prefix / "bin/npm").symlink_to("../lib/node_modules/npm/bin/npm-cli.js")

    environment = {
        **os.environ,
        "FAKE_ACCOUNT_HOME": account_home.as_posix(),
        "FAKE_INVOCATION_DIR": invocation_dir.as_posix(),
        "FAKE_PYTHON_SCRIPTS": python_scripts.as_posix(),
        "GITHUB_PATH": github_path.as_posix(),
        "HOME": poison_home.as_posix(),
        "PATH": f"{fake_bin.as_posix()}:{(node_prefix / 'bin').as_posix()}:/usr/bin:/bin",
        "RUNNER_TOOL_CACHE": (tmp_path / "toolcache").as_posix(),
        "UV_VERSION": "0.10.12",
    }
    completed = subprocess.run(
        ("bash", "-euo", "pipefail", "-c", cast(str, install_step["run"])),
        cwd=_PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    reviewed_root = account_home / ".local"
    reviewed_bin = reviewed_root / "bin"
    assert (reviewed_root / "share/node-distribution-marker").read_text(
        encoding="utf-8"
    ) == "complete distribution\n"
    assert (reviewed_bin / "npm").is_symlink()
    assert (reviewed_bin / "npm").resolve() == (
        reviewed_root / "lib/node_modules/npm/bin/npm-cli.js"
    )
    for name in ("uv", "node", "npm"):
        executable = reviewed_bin / name
        assert executable.is_file()
        assert os.access(executable, os.X_OK)

    assert github_path.read_text(encoding="utf-8") == f"{reviewed_bin.as_posix()}\n"
    assert {
        name: (invocation_dir / name).read_text(encoding="utf-8").strip()
        for name in ("uv", "node", "npm")
    } == {name: os.fspath(reviewed_bin / name) for name in ("uv", "node", "npm")}
