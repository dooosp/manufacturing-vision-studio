from __future__ import annotations

import os
import pwd
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.e1 import protocol_v2 as legacy_protocol_module
from manufacturing_vision_studio.e1 import study_retention_v2 as retention_module
from manufacturing_vision_studio.e1.study_artifacts_v2 import (
    StudyArtifactStore,
    finalize_study_record,
    load_strict_json_object,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    PROJECT_ROOT,
    StudyProtocolV2,
    load_study_protocol_v2,
)
from manufacturing_vision_studio.e1.study_retention_v2 import (
    StudyRetentionError,
    build_study_implementation_projection,
    run_retention_audit,
    verify_historical_hold,
    verify_implementation_validation,
    verify_retention_audit,
)

EXPECTED_COMMANDS = (
    ("ruff", ("uv", "run", "ruff", "check", ".")),
    ("mypy", ("uv", "run", "mypy", "src")),
    ("v0_1_regression", ("uv", "run", "pytest", "-q", "tests/test_e1_baseline.py")),
    ("pytest", ("uv", "run", "pytest", "-q")),
    ("web_check", ("npm", "--prefix", "web", "run", "check")),
    ("playwright", ("npm", "--prefix", "web", "run", "test:e2e")),
)
EXPECTED_COMMAND_TIMEOUTS = (300, 300, 600, 1800, 600, 900)
_ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
_ACCOUNT_LOCAL_BIN = _ACCOUNT_HOME / ".local/bin"
_ACCOUNT_UV = (_ACCOUNT_LOCAL_BIN / "uv").as_posix()
_HOMEBREW_NPM = "/opt/homebrew/bin/npm"
EXPECTED_EXECUTABLE_LOOKUP_PATHS = (
    _ACCOUNT_UV,
    _ACCOUNT_UV,
    _ACCOUNT_UV,
    _ACCOUNT_UV,
    _HOMEBREW_NPM,
    _HOMEBREW_NPM,
)
EXPECTED_SANITIZED_ENVIRONMENT = {
    "HOME": "/tmp/e1-study-home",
    "PATH": (
        f"{_ACCOUNT_LOCAL_BIN.as_posix()}:/opt/homebrew/bin:"
        "/usr/bin:/bin:/usr/sbin:/sbin"
    ),
    "TMPDIR": "/tmp/e1-study",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "TERM": "dumb",
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "PYTHONHASHSEED": "0",
    "PYTHONUTF8": "1",
    "PYTHONNOUSERSITE": "1",
    "UV_NO_CONFIG": "1",
    "NPM_CONFIG_USERCONFIG": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}
EXPECTED_CONTROLS = (
    ("bundle_verify_reimport_rate", "STUDY_PUBLISHES_NO_BUNDLE"),
    ("dataset_split_hash_overlap", "PROTECTED_SPLIT_MEMBERS_NOT_ENUMERATED"),
    ("same_seed_manifest_equivalence", "FULL_TWO_RUN_EQUIVALENCE_NOT_AUTHORIZED"),
    ("revision_mismatch_publication_count", "STUDY_HAS_NO_RUNTIME_PUBLICATION_PATH"),
    ("corrupted_evidence_publication_count", "STUDY_HAS_NO_RUNTIME_PUBLICATION_PATH"),
)
EXPECTED_RETAINED_PATHS = (
    "retained-inputs/candidate-a.json",
    "retained-inputs/candidate-b.json",
    "retained-inputs/task-4-report.md",
    "retained-inputs/sdd-progress.md",
)
EXPECTED_CLASSIFICATIONS = {
    "Retain": (
        "development diagnostic matrix",
        "split guards",
        "canonical metric calculations",
        "truth-erasing runtime input",
        "final-mask ownership mapping",
        "v1 history verification",
        "Task 4 negative evidence",
    ),
    "Isolate": (
        "Candidate A/B search and normalization",
        "candidate ranking",
        "candidate selection loader",
        "candidate work caps",
        "candidate-specific benchmarking and constants",
    ),
    "Re-review": (
        "candidate-coupled protocol fields",
        "legacy development-template planning",
        "ownership assumptions",
        "any source whose change would invalidate the historical implementation projection",
    ),
}
V1_HISTORY_RELATIVE_PATH = Path(
    "configs/evaluation/e1-v1-history-integrity.json"
)
V1_HISTORY_REVISIONS = (
    ("v0.1.0^{tag}", "67bd8af8d6bfdbcb5ff2654fd37b797dc7c75f3d"),
    ("v0.1.0^{commit}", "cf7b9ac37d0533f656068199d3275410cf8cc2f8"),
    (
        "2f87b885b29c12468effea927279d27424eaa340^{commit}",
        "2f87b885b29c12468effea927279d27424eaa340",
    ),
)


@dataclass(slots=True)
class RetentionFixture:
    repo_root: Path
    protocol: StudyProtocolV2
    store: StudyArtifactStore
    base_commit: str
    execution_commit: str
    evidence_commit: str
    validation_record: dict[str, object]
    source_payloads: dict[str, bytes]


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _copy_v1_history_tree(repo_root: Path) -> dict[str, object]:
    source_path = PROJECT_ROOT / V1_HISTORY_RELATIVE_PATH
    document = load_strict_json_object(source_path.read_bytes())
    _write(repo_root / V1_HISTORY_RELATIVE_PATH, source_path.read_bytes())
    artifacts = cast(list[object], document["artifacts"])
    for raw_artifact in artifacts:
        artifact = cast(dict[str, object], raw_artifact)
        relative = Path(cast(str, artifact["path"]))
        _write(repo_root / relative, (PROJECT_ROOT / relative).read_bytes())
    return document


def _stub_v1_history_git(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    identities = dict(V1_HISTORY_REVISIONS)

    def run_git(_root: Path, *args: str) -> str:
        calls.append(args)
        assert args[:1] == ("rev-parse",)
        return identities[args[1]]

    monkeypatch.setattr(retention_module, "_run_git", run_git)
    return calls


def _copy_projection(repo_root: Path, protocol: StudyProtocolV2) -> None:
    runner = (
        b"import manufacturing_vision_studio.canonical_png as canonical_png, "
        b"manufacturing_vision_studio.e1.feature_mapping as feature_mapping, "
        b"manufacturing_vision_studio.e1.metrics_v2 as metrics_v2, "
        b"manufacturing_vision_studio.e1.protocol_v2 as protocol_v2\n"
        b"from manufacturing_vision_studio.e1.study_retention_v2 import RetentionAudit\n"
        b"MARKER = (canonical_png, feature_mapping, metrics_v2, protocol_v2, RetentionAudit)\n"
    )
    cli = (
        b"from manufacturing_vision_studio.e1.study_runner_v2 import MARKER\n"
        b"CLI_MARKER = MARKER\n"
    )
    for relative in protocol.implementation_projection_paths():
        destination = repo_root / relative
        if relative.endswith("study_runner_v2.py"):
            payload = runner
        elif relative.endswith("study_cli_v2.py"):
            payload = cli
        elif relative == "configs/evaluation/e1-feasibility-study.v1.json":
            payload = canonical_json_bytes(protocol.document)
        else:
            payload = (PROJECT_ROOT / relative).read_bytes()
        _write(destination, payload)


def _audited_validation_commands() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "argv": list(argv),
            "executable_lookup_path": EXPECTED_EXECUTABLE_LOOKUP_PATHS[ordinal],
            "exit_code": 0,
            "stdout_sha256": sha256_bytes(f"{name}-stdout".encode()),
            "stderr_sha256": sha256_bytes(f"{name}-stderr".encode()),
            "started_at_utc": "2026-08-01T00:00:00Z",
            "ended_at_utc": "2026-08-01T00:00:01Z",
            "cwd": ".",
            "shell": False,
            "timeout_seconds": EXPECTED_COMMAND_TIMEOUTS[ordinal],
            "output_limit_bytes": 4_194_304,
            "timed_out": False,
            "stdout_byte_count": 0,
            "stderr_byte_count": 0,
            "sanitized_environment": dict(EXPECTED_SANITIZED_ENVIRONMENT),
        }
        for ordinal, (name, argv) in enumerate(EXPECTED_COMMANDS)
    ]


def _set_validation_executable_contract(
    commands: list[dict[str, object]],
    *,
    uv_lookup_path: str,
    npm_lookup_path: str,
    environment_path: str,
) -> None:
    for ordinal, command in enumerate(commands):
        command["executable_lookup_path"] = (
            uv_lookup_path if ordinal < 4 else npm_lookup_path
        )
        environment = cast(dict[str, object], command["sanitized_environment"])
        environment["PATH"] = environment_path


def _validation_document(
    protocol: StudyProtocolV2,
    *,
    execution_commit: str,
    repo_root: Path,
) -> dict[str, object]:
    projection = build_study_implementation_projection(protocol, repo_root=repo_root)
    projection_sha256 = canonical_json_hash([entry.as_record() for entry in projection])
    mode_hashes = {
        mode: sha256_bytes(f"fixture-{mode}".encode())
        for mode in ("NEAREST", "BILINEAR", "BICUBIC")
    }
    return {
        "record_type": "implementation_validation",
        "schema_version": "1.0.0",
        "study_id": "e1-feasibility-separability",
        "development_only": True,
        "selection_eligible": False,
        "release_claim_allowed": False,
        "base_commit": protocol.base_commit,
        "execution_commit": execution_commit,
        "protocol_sha256": protocol.configuration_sha256,
        "artifact_root": protocol.artifact_root_identity,
        "artifact_schema_sha256": sha256_bytes(
            (repo_root / "schemas/e1-feasibility-study-artifact.v1.json").read_bytes()
        ),
        "implementation_projection_sha256": projection_sha256,
        "upstream_artifacts": [],
        "payload": {
            "worktree_clean": True,
            "commands": _audited_validation_commands(),
            "determinism_control": {
                "first_projection": mode_hashes,
                "second_projection": dict(mode_hashes),
                "passed": True,
            },
            "not_applicable_controls": [
                {
                    "name": name,
                    "status": "NOT_APPLICABLE",
                    "numerator": None,
                    "denominator": None,
                    "observed": None,
                    "operator": None,
                    "threshold": None,
                    "reason": reason,
                }
                for name, reason in EXPECTED_CONTROLS
            ],
            "passed": True,
        },
        "record_sha256": "0" * 64,
    }


def _build_retention_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> RetentionFixture:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "fixture")
    _git(repo_root, "config", "user.name", "Task 6 Test")
    _git(repo_root, "config", "user.email", "task6@example.invalid")
    _write(repo_root / ".base", b"base\n")
    _git(repo_root, "add", ".base")
    _git(repo_root, "commit", "-m", "base")
    base_commit = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "branch", "codex/e1-v2-scale-feature-remediation", base_commit)

    source_payloads = {
        "candidate_a": b'{"candidate":"A","outcome":"HOLD"}',
        "candidate_b": b'{"candidate":"B","outcome":"HOLD"}',
        "task_4_report": b"Task 4 retained report\n",
        "sdd_progress": b"Task 4 retained progress\n",
    }
    real = load_study_protocol_v2()
    document = real.document
    document["base_commit"] = base_commit
    source_hashes = dict(real.source_hashes)
    source_hashes.update(
        {
            "candidate_a_raw_sha256": sha256_bytes(source_payloads["candidate_a"]),
            "candidate_b_raw_sha256": sha256_bytes(source_payloads["candidate_b"]),
            "task4_report_raw_sha256": sha256_bytes(source_payloads["task_4_report"]),
            "task4_progress_ledger_raw_sha256": sha256_bytes(
                source_payloads["sdd_progress"]
            ),
        }
    )
    document["source_hashes"] = source_hashes
    protocol = replace(
        real,
        source_path=repo_root / "configs/evaluation/e1-feasibility-study.v1.json",
        schema_path=repo_root / "schemas/e1-feasibility-study-config.v1.json",
        _document=document,
        configuration_sha256=canonical_json_hash(document),
        artifact_root=repo_root / "artifacts",
        raw_data_root=repo_root / "raw",
        source_hashes=MappingProxyType(source_hashes),
    )
    _copy_projection(repo_root, protocol)
    _write(
        repo_root / "data/e1-v2-development/candidate-a.json",
        source_payloads["candidate_a"],
    )
    _write(
        repo_root / "data/e1-v2-development/candidate-b.json",
        source_payloads["candidate_b"],
    )
    _write(
        repo_root / "docs/evaluation/negative-results/e1-v2-task4-report.raw.txt",
        source_payloads["task_4_report"],
    )
    _write(
        repo_root
        / "docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt",
        source_payloads["sdd_progress"],
    )
    _write(repo_root / "lineage-source.txt", b"tracked before execution\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "implementation")
    execution_commit = _git(repo_root, "rev-parse", "HEAD")

    store = StudyArtifactStore(protocol.artifact_root, allowed_root=repo_root)
    store.publish_json(
        "implementation-validation.json",
        _validation_document(protocol, execution_commit=execution_commit, repo_root=repo_root),
    )
    validation_record = store.verify_json(
        "implementation-validation.json",
        expected_record_type="implementation_validation",
    )
    _git(repo_root, "add", "artifacts/implementation-validation.json")
    _git(repo_root, "commit", "-m", "validation evidence")
    evidence_commit = _git(repo_root, "rev-parse", "HEAD")
    monkeypatch.setattr(
        retention_module,
        "_verify_e1_v1_history_local",
        lambda _root: {"verdict": "HOLD", "artifact_count": 9},
        raising=False,
    )
    return RetentionFixture(
        repo_root=repo_root,
        protocol=protocol,
        store=store,
        base_commit=base_commit,
        execution_commit=execution_commit,
        evidence_commit=evidence_commit,
        validation_record=validation_record,
        source_payloads=source_payloads,
    )


@pytest.fixture
def retention_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[RetentionFixture]:
    fixture = _build_retention_fixture(tmp_path, monkeypatch)
    try:
        yield fixture
    finally:
        fixture.store.close()


def _rewrite_json(path: Path, document: dict[str, object]) -> None:
    path.write_bytes(canonical_json_bytes(finalize_study_record(document)))


def _validation_path(fixture: RetentionFixture) -> Path:
    return fixture.protocol.artifact_root / "implementation-validation.json"


def _retention_path(fixture: RetentionFixture) -> Path:
    return fixture.protocol.artifact_root / "retention-audit.json"


def test_control_plane_git_ignores_inherited_path_config_and_loader_poison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch Git subprocesses that inherit authority-changing host state."""

    fake_git = tmp_path / "git"
    fake_git.write_text(
        """#!/bin/sh
set -eu
[ "$PATH" = "/usr/bin:/bin:/usr/sbin:/sbin" ]
[ "${GIT_CONFIG_NOSYSTEM:-}" = "1" ]
[ "${GIT_CONFIG_GLOBAL:-}" = "/dev/null" ]
[ "${GIT_OPTIONAL_LOCKS:-}" = "0" ]
for name in GIT_DIR GIT_WORK_TREE GIT_EXTERNAL_DIFF GIT_CONFIG_SYSTEM \
  GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0 GIT_PAGER PAGER LESS LV \
  DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH LD_PRELOAD LD_LIBRARY_PATH; do
  eval 'test -z "${'"$name"'+x}"'
done
printf '%s\\n' "$PWD"
printf '%s\\n' "$*"
""",
        encoding="utf-8",
    )
    fake_git.chmod(0o700)
    poison = {
        "PATH": "/poison/bin",
        "GIT_DIR": "/poison/git-dir",
        "GIT_WORK_TREE": "/poison/work-tree",
        "GIT_EXTERNAL_DIFF": "/poison/external-diff",
        "GIT_CONFIG_SYSTEM": "/poison/system-config",
        "GIT_CONFIG_GLOBAL": "/poison/global-config",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "/poison/hooks",
        "GIT_PAGER": "/poison/pager",
        "PAGER": "/poison/pager",
        "LESS": "-RFX",
        "LV": "-c",
        "DYLD_INSERT_LIBRARIES": "/poison/injected.dylib",
        "DYLD_LIBRARY_PATH": "/poison/dylibs",
        "LD_PRELOAD": "/poison/injected.so",
        "LD_LIBRARY_PATH": "/poison/libs",
    }
    for name, value in poison.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        retention_module,
        "_resolve_system_git_executable",
        lambda: fake_git,
        raising=False,
    )

    literal = "rev-parse;touch-should-never-run"
    output = retention_module._run_git(tmp_path, literal)

    assert output.splitlines() == [
        os.fspath(tmp_path),
        f"--no-pager -c core.fsmonitor=false {literal}",
    ]


def test_control_plane_git_disables_repository_fsmonitor(
    tmp_path: Path,
) -> None:
    """Catch repository config that executes a program during read-only status."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "fixture")
    _git(repo_root, "config", "user.name", "Git Control Test")
    _git(repo_root, "config", "user.email", "git-control@example.invalid")
    _write(repo_root / "tracked.txt", b"tracked\n")
    _git(repo_root, "add", "tracked.txt")
    _git(repo_root, "commit", "-m", "base")
    sentinel = tmp_path / "fsmonitor-ran"
    fsmonitor = tmp_path / "fsmonitor.sh"
    fsmonitor.write_text(
        f"#!/bin/sh\ntouch {sentinel!s}\nexit 1\n",
        encoding="utf-8",
    )
    fsmonitor.chmod(0o700)
    _git(repo_root, "config", "core.fsmonitor", os.fspath(fsmonitor))

    assert retention_module._git_status_paths(repo_root) == ()
    assert not sentinel.exists()


def test_projection_and_lineage_route_every_git_call_through_sanitized_helper(
    retention_fixture: RetentionFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch one-off tracked/status/ancestry calls that bypass the helper."""

    malformed_config = tmp_path / "malformed.gitconfig"
    malformed_config.write_text("this is not valid git config\n", encoding="utf-8")
    poison = {
        "PATH": "/poison/bin",
        "GIT_DIR": "/poison/git-dir",
        "GIT_WORK_TREE": "/poison/work-tree",
        "GIT_EXTERNAL_DIFF": "/poison/external-diff",
        "GIT_CONFIG_SYSTEM": os.fspath(malformed_config),
        "GIT_CONFIG_GLOBAL": os.fspath(malformed_config),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "/poison/hooks",
        "GIT_PAGER": "/poison/pager",
        "PAGER": "/poison/pager",
        "DYLD_INSERT_LIBRARIES": "/poison/injected.dylib",
        "DYLD_LIBRARY_PATH": "/poison/dylibs",
        "LD_PRELOAD": "/poison/injected.so",
        "LD_LIBRARY_PATH": "/poison/libs",
    }
    for name, value in poison.items():
        monkeypatch.setenv(name, value)

    projection = build_study_implementation_projection(
        retention_fixture.protocol,
        repo_root=retention_fixture.repo_root,
    )
    evidence_commit = retention_module._verify_git_lineage(
        retention_fixture.protocol,
        repo_root=retention_fixture.repo_root,
        execution_commit=retention_fixture.execution_commit,
        evidence_commit=None,
        require_clean=True,
    )

    assert len(projection) == 47
    assert evidence_commit == retention_fixture.evidence_commit


def test_real_historical_selection_and_v1_history_are_hold() -> None:
    audit = verify_historical_hold(load_study_protocol_v2())

    assert audit.selection_raw_sha256 == (
        "92d3a2f86645a4d0fc33cfc39b769c6d2c4234383c7f132e803c449c7a66f2f3"
    )
    assert audit.selection_record_sha256 == (
        "3d4aa7e95240ed2bd4c018fb0762fdf788f919069cfbb935fd228de4b67dc2fe"
    )
    assert audit.outcome == "HOLD"
    assert audit.selected_candidate_id is None
    assert audit.v1_history_outcome == "HOLD"
    assert audit.v1_history_artifact_count == 9


def test_retention_local_v1_history_matches_legacy_public_verifier() -> None:
    assert retention_module._verify_e1_v1_history_local(PROJECT_ROOT) == (
        legacy_protocol_module.verify_e1_v1_history()
    )


def test_retention_local_v1_history_ignores_poisoned_legacy_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def poisoned_verifier(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("legacy public verifier must not be called")

    monkeypatch.setattr(
        legacy_protocol_module,
        "verify_e1_v1_history",
        poisoned_verifier,
    )

    assert retention_module._verify_e1_v1_history_local(PROJECT_ROOT) == {
        "verdict": "HOLD",
        "artifact_count": 9,
    }


def test_retention_local_v1_history_rejects_artifact_hash_tamper(
    tmp_path: Path,
) -> None:
    document = _copy_v1_history_tree(tmp_path)
    first = cast(dict[str, object], cast(list[object], document["artifacts"])[0])
    artifact_path = tmp_path / cast(str, first["path"])
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")

    with pytest.raises(StudyRetentionError, match="hash mismatch"):
        retention_module._verify_e1_v1_history_local(tmp_path)


def test_retention_local_v1_history_rejects_expected_field_tamper(
    tmp_path: Path,
) -> None:
    document = _copy_v1_history_tree(tmp_path)
    first = cast(dict[str, object], cast(list[object], document["artifacts"])[0])
    artifact_path = tmp_path / cast(str, first["path"])
    artifact = load_strict_json_object(artifact_path.read_bytes())
    artifact["status"] = "poisoned"
    payload = canonical_json_bytes(artifact)
    artifact_path.write_bytes(payload)
    first["sha256"] = sha256_bytes(payload)
    (tmp_path / V1_HISTORY_RELATIVE_PATH).write_bytes(canonical_json_bytes(document))

    with pytest.raises(StudyRetentionError, match="identity mismatch"):
        retention_module._verify_e1_v1_history_local(tmp_path)


def test_retention_local_v1_history_uses_exact_revision_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copy_v1_history_tree(tmp_path)
    calls = _stub_v1_history_git(monkeypatch)

    assert retention_module._verify_e1_v1_history_local(tmp_path) == {
        "verdict": "HOLD",
        "artifact_count": 9,
    }
    assert calls == [("rev-parse", revision) for revision, _ in V1_HISTORY_REVISIONS]


def test_historical_hold_rejects_semantic_selection_tamper(
    retention_fixture: RetentionFixture,
) -> None:
    selection_path = (
        retention_fixture.repo_root / "configs/evaluation/e1-v2-candidate-selection.json"
    )
    document = load_strict_json_object(selection_path.read_bytes())
    document["outcome"] = "SELECTED"
    document["selected_candidate_id"] = "A"
    tampered = finalize_study_record(document)
    payload = canonical_json_bytes(tampered)
    selection_path.write_bytes(payload)
    source_hashes = dict(retention_fixture.protocol.source_hashes)
    source_hashes["selection_raw_sha256"] = sha256_bytes(payload)
    source_hashes["selection_record_sha256"] = cast(str, tampered["record_sha256"])
    protocol = replace(
        retention_fixture.protocol,
        source_hashes=MappingProxyType(source_hashes),
    )

    with pytest.raises(StudyRetentionError, match="HOLD/null"):
        verify_historical_hold(protocol, repo_root=retention_fixture.repo_root)


def test_historical_hold_requires_all_nine_v1_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _copy_v1_history_tree(tmp_path)
    cast(list[object], document["artifacts"]).pop()
    (tmp_path / V1_HISTORY_RELATIVE_PATH).write_bytes(canonical_json_bytes(document))
    _stub_v1_history_git(monkeypatch)

    with pytest.raises(StudyRetentionError, match="nine"):
        retention_module._verify_e1_v1_history_local(tmp_path)


def test_historical_hold_routes_exact_git_identities_through_sanitized_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch retained v1 history falling back to ambient protocol Git."""

    _copy_v1_history_tree(tmp_path)
    fake_git = tmp_path / "git"
    fake_git.write_text(
        """#!/bin/sh
set -eu
[ "$PATH" = "/usr/bin:/bin:/usr/sbin:/sbin" ]
[ "${GIT_CONFIG_NOSYSTEM:-}" = "1" ]
[ "${GIT_CONFIG_GLOBAL:-}" = "/dev/null" ]
[ "${GIT_OPTIONAL_LOCKS:-}" = "0" ]
last=""
for argument in "$@"; do last="$argument"; done
case "$last" in
  --show-toplevel) printf '%s\\n' "$PWD" ;;
  'v0.1.0^{tag}')
    printf '%s\\n' '67bd8af8d6bfdbcb5ff2654fd37b797dc7c75f3d'
    ;;
  'v0.1.0^{commit}')
    printf '%s\\n' 'cf7b9ac37d0533f656068199d3275410cf8cc2f8'
    ;;
  '2f87b885b29c12468effea927279d27424eaa340^{commit}')
    printf '%s\\n' '2f87b885b29c12468effea927279d27424eaa340'
    ;;
  *) exit 91 ;;
esac
""",
        encoding="utf-8",
    )
    fake_git.chmod(0o700)
    monkeypatch.setattr(
        retention_module,
        "_resolve_system_git_executable",
        lambda: fake_git,
    )
    for name, value in {
        "PATH": "/poison/bin",
        "GIT_DIR": "/poison/git-dir",
        "GIT_WORK_TREE": "/poison/work-tree",
        "GIT_CONFIG_GLOBAL": "/poison/global-config",
        "DYLD_INSERT_LIBRARIES": "/poison/injected.dylib",
        "LD_PRELOAD": "/poison/injected.so",
    }.items():
        monkeypatch.setenv(name, value)
    assert retention_module._verify_e1_v1_history_local(tmp_path) == {
        "verdict": "HOLD",
        "artifact_count": 9,
    }


def test_implementation_validation_is_read_only_and_semantically_verified(
    retention_fixture: RetentionFixture,
) -> None:
    verified = verify_implementation_validation(
        retention_fixture.protocol,
        retention_fixture.store,
        repo_root=retention_fixture.repo_root,
    )

    assert verified.execution_commit == retention_fixture.execution_commit
    assert tuple(command.name for command in verified.commands) == tuple(
        name for name, _ in EXPECTED_COMMANDS
    )
    assert verified.first_projection == verified.second_projection
    assert verified.passed is True
    assert verified.raw_sha256 == sha256_bytes(_validation_path(retention_fixture).read_bytes())


def test_validation_evidence_uses_portable_artifact_root_identity(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch validation evidence that serializes its temporary runtime store path."""

    verified = verify_implementation_validation(
        retention_fixture.protocol,
        retention_fixture.store,
        repo_root=retention_fixture.repo_root,
    )

    assert retention_fixture.protocol.artifact_root_identity == (
        "docs/evaluation/results/e1-feasibility-study"
    )
    assert verified.artifact_root == retention_fixture.protocol.artifact_root_identity


def test_implementation_validation_rejects_self_consistent_unreviewed_executable_roots(
    retention_fixture: RetentionFixture,
) -> None:
    document = load_strict_json_object(_validation_path(retention_fixture).read_bytes())
    payload = cast(dict[str, object], document["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    _set_validation_executable_contract(
        commands,
        uv_lookup_path="/tmp/unreviewed-tools/uv",
        npm_lookup_path="/tmp/unreviewed-tools/npm",
        environment_path=(
            "/tmp/unreviewed-tools:/usr/bin:/bin:/usr/sbin:/sbin"
        ),
    )
    _rewrite_json(_validation_path(retention_fixture), document)

    with pytest.raises(StudyRetentionError, match="reviewed executable root"):
        verify_implementation_validation(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_task_7a_fix1_validation_command_audit_contract_returns_verified_metadata() -> None:
    commands = retention_module._verify_validation_commands(_audited_validation_commands())

    assert tuple(command.timeout_seconds for command in commands) == EXPECTED_COMMAND_TIMEOUTS
    assert commands[0].cwd == "."
    assert commands[0].shell is False
    assert commands[0].output_limit_bytes == 4_194_304
    assert commands[0].timed_out is False
    assert commands[0].stdout_byte_count == 0
    assert commands[0].stderr_byte_count == 0
    assert tuple(command.executable_lookup_path for command in commands) == (
        EXPECTED_EXECUTABLE_LOOKUP_PATHS
    )
    assert dict(commands[0].sanitized_environment) == EXPECTED_SANITIZED_ENVIRONMENT
    with pytest.raises(TypeError):
        cast(dict[str, str], commands[0].sanitized_environment)["LANG"] = "poisoned"


@pytest.mark.parametrize(
    "variant",
    [
        "wrong_timeout_for_ordinal",
        "missing_environment_key",
        "extra_environment_key",
        "poisoned_fixed_environment",
        "relative_home",
        "control_path",
        "bad_path_suffix",
        "cwd",
        "shell",
        "output_limit",
        "timed_out",
        "boolean_byte_count",
        "overflow_byte_count",
    ],
)
def test_task_7a_fix1_validation_command_audit_contract_rejects_semantic_tamper(
    variant: str,
) -> None:
    commands = _audited_validation_commands()
    command = commands[0]
    environment = cast(dict[str, object], command["sanitized_environment"])
    if variant == "wrong_timeout_for_ordinal":
        command["timeout_seconds"] = 600
    elif variant == "missing_environment_key":
        environment.pop("HOME")
    elif variant == "extra_environment_key":
        environment["PYTEST_ADDOPTS"] = "-x"
    elif variant == "poisoned_fixed_environment":
        environment["LANG"] = "en_US.UTF-8"
    elif variant == "relative_home":
        environment["HOME"] = "relative/home"
    elif variant == "control_path":
        environment["PATH"] = "/opt/e1\npoisoned:/usr/bin:/bin:/usr/sbin:/sbin"
    elif variant == "bad_path_suffix":
        environment["PATH"] = "/opt/e1-study/bin"
    elif variant == "cwd":
        command["cwd"] = "/tmp"
    elif variant == "shell":
        command["shell"] = True
    elif variant == "output_limit":
        command["output_limit_bytes"] = 1024
    elif variant == "timed_out":
        command["timed_out"] = True
    elif variant == "boolean_byte_count":
        command["stdout_byte_count"] = True
    else:
        command["stderr_byte_count"] = 4_194_305

    with pytest.raises(StudyRetentionError, match=r"validation command|environment|byte count"):
        retention_module._verify_validation_commands(commands)


def test_task_7a_fix2_validation_commands_reject_unbound_path_prefix() -> None:
    commands = _audited_validation_commands()
    for command in commands:
        environment = cast(dict[str, object], command["sanitized_environment"])
        current_path = environment["PATH"]
        assert isinstance(current_path, str)
        environment["PATH"] = f"/tmp/evil-bin:{current_path}"

    with pytest.raises(StudyRetentionError, match="environment PATH"):
        retention_module._verify_validation_commands(commands)


@pytest.mark.parametrize(
    ("uv_lookup_path", "npm_lookup_path", "environment_path"),
    [
        (
            _ACCOUNT_UV,
            _HOMEBREW_NPM,
            (
                f"{_ACCOUNT_LOCAL_BIN.as_posix()}:/opt/homebrew/bin:"
                "/usr/bin:/bin:/usr/sbin:/sbin"
            ),
        ),
        (
            "/usr/local/bin/uv",
            "/usr/local/bin/npm",
            "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ),
        (
            "/usr/bin/uv",
            "/bin/npm",
            "/usr/bin:/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ),
    ],
    ids=("account-homebrew", "usr-local", "system-roots"),
)
def test_task_7a_fix2_validation_commands_accept_bound_executable_paths(
    uv_lookup_path: str,
    npm_lookup_path: str,
    environment_path: str,
) -> None:
    commands = _audited_validation_commands()
    _set_validation_executable_contract(
        commands,
        uv_lookup_path=uv_lookup_path,
        npm_lookup_path=npm_lookup_path,
        environment_path=environment_path,
    )

    verified = retention_module._verify_validation_commands(commands)

    assert tuple(command.executable_lookup_path for command in verified) == (
        uv_lookup_path,
        uv_lookup_path,
        uv_lookup_path,
        uv_lookup_path,
        npm_lookup_path,
        npm_lookup_path,
    )
    assert all(
        dict(command.sanitized_environment) == dict(verified[0].sanitized_environment)
        for command in verified
    )


@pytest.mark.parametrize(
    "variant",
    [
        "missing_lookup_path",
        "empty_lookup_path",
        "relative_lookup_path",
        "control_lookup_path",
        "colon_lookup_path",
        "empty_component_lookup_path",
        "dot_component_lookup_path",
        "dot_dot_component_lookup_path",
        "nested_reviewed_root",
        "wrong_basename",
        "one_uv_lookup_drift",
        "one_npm_lookup_drift",
        "extra_path_prefix",
        "missing_uv_parent",
        "reordered_dynamic_parents",
        "uv_parent_substitution",
        "npm_parent_substitution",
        "fixed_suffix_drift",
        "one_command_path_drift",
        "one_command_home_drift",
        "one_command_tmpdir_drift",
    ],
)
def test_task_7a_fix2_validation_commands_reject_executable_environment_drift(
    variant: str,
) -> None:
    commands = _audited_validation_commands()
    if variant == "missing_lookup_path":
        commands[0].pop("executable_lookup_path")
    elif variant == "empty_lookup_path":
        commands[0]["executable_lookup_path"] = ""
    elif variant == "relative_lookup_path":
        commands[0]["executable_lookup_path"] = "opt/e1-study/uv/bin/uv"
    elif variant == "control_lookup_path":
        commands[0]["executable_lookup_path"] = "/opt/e1-study/uv\n/bin/uv"
    elif variant == "colon_lookup_path":
        commands[0]["executable_lookup_path"] = "/opt/e1-study:shadow/uv"
    elif variant == "empty_component_lookup_path":
        commands[0]["executable_lookup_path"] = "/opt/e1-study//bin/uv"
    elif variant == "dot_component_lookup_path":
        commands[0]["executable_lookup_path"] = "/opt/e1-study/./bin/uv"
    elif variant == "dot_dot_component_lookup_path":
        commands[0]["executable_lookup_path"] = "/opt/e1-study/tools/../bin/uv"
    elif variant == "nested_reviewed_root":
        commands[0]["executable_lookup_path"] = "/opt/homebrew/bin/nested/uv"
    elif variant == "wrong_basename":
        commands[0]["executable_lookup_path"] = (
            _ACCOUNT_LOCAL_BIN / "npm"
        ).as_posix()
    elif variant == "one_uv_lookup_drift":
        commands[1]["executable_lookup_path"] = "/usr/local/bin/uv"
    elif variant == "one_npm_lookup_drift":
        commands[5]["executable_lookup_path"] = "/usr/local/bin/npm"
    elif variant == "extra_path_prefix":
        for command in commands:
            environment = cast(dict[str, object], command["sanitized_environment"])
            environment["PATH"] = f"/tmp/evil-bin:{EXPECTED_SANITIZED_ENVIRONMENT['PATH']}"
    elif variant == "missing_uv_parent":
        for command in commands:
            environment = cast(dict[str, object], command["sanitized_environment"])
            environment["PATH"] = (
                "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            )
    elif variant == "reordered_dynamic_parents":
        for command in commands:
            environment = cast(dict[str, object], command["sanitized_environment"])
            environment["PATH"] = (
                f"/opt/homebrew/bin:{_ACCOUNT_LOCAL_BIN.as_posix()}:"
                "/usr/bin:/bin:/usr/sbin:/sbin"
            )
    elif variant == "uv_parent_substitution":
        for command in commands:
            environment = cast(dict[str, object], command["sanitized_environment"])
            environment["PATH"] = (
                "/tmp/substitute:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            )
    elif variant == "npm_parent_substitution":
        for command in commands:
            environment = cast(dict[str, object], command["sanitized_environment"])
            environment["PATH"] = (
                f"{_ACCOUNT_LOCAL_BIN.as_posix()}:/tmp/substitute:"
                "/usr/bin:/bin:/usr/sbin:/sbin"
            )
    elif variant == "fixed_suffix_drift":
        for command in commands:
            environment = cast(dict[str, object], command["sanitized_environment"])
            environment["PATH"] = (
                f"{_ACCOUNT_LOCAL_BIN.as_posix()}:/opt/homebrew/bin:"
                "/usr/bin:/bin:/usr/sbin:/usr/local/sbin"
            )
    elif variant == "one_command_path_drift":
        environment = cast(dict[str, object], commands[2]["sanitized_environment"])
        environment["PATH"] = f"/tmp/evil-bin:{EXPECTED_SANITIZED_ENVIRONMENT['PATH']}"
    elif variant == "one_command_home_drift":
        environment = cast(dict[str, object], commands[2]["sanitized_environment"])
        environment["HOME"] = "/tmp/other-home"
    else:
        environment = cast(dict[str, object], commands[2]["sanitized_environment"])
        environment["TMPDIR"] = "/tmp/other-tmpdir"

    with pytest.raises(
        StudyRetentionError,
        match=r"executable lookup path|environment PATH|environments",
    ):
        retention_module._verify_validation_commands(commands)


def _reverse_first_command_time(document: dict[str, object]) -> None:
    payload = cast(dict[str, object], document["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    commands[0]["ended_at_utc"] = "2026-07-31T23:59:59Z"


def _change_second_determinism_projection(document: dict[str, object]) -> None:
    payload = cast(dict[str, object], document["payload"])
    control = cast(dict[str, object], payload["determinism_control"])
    second = cast(dict[str, object], control["second_projection"])
    second["NEAREST"] = sha256_bytes(b"different")


def _change_first_not_applicable_reason(document: dict[str, object]) -> None:
    payload = cast(dict[str, object], document["payload"])
    controls = cast(list[dict[str, object]], payload["not_applicable_controls"])
    controls[0]["reason"] = "WRONG"


def _replace_schema_hash_with_filler(document: dict[str, object]) -> None:
    document["artifact_schema_sha256"] = "0" * 64


@pytest.mark.parametrize(
    "mutate,error",
    [
        (_reverse_first_command_time, "command time range"),
        (_change_second_determinism_projection, "determinism"),
        (_change_first_not_applicable_reason, "NOT_APPLICABLE"),
        (_replace_schema_hash_with_filler, "zero or filler"),
    ],
)
def test_implementation_validation_rejects_semantic_tamper(
    retention_fixture: RetentionFixture,
    mutate: Callable[[dict[str, object]], object],
    error: str,
) -> None:
    document = load_strict_json_object(_validation_path(retention_fixture).read_bytes())
    mutate(document)
    _rewrite_json(_validation_path(retention_fixture), document)

    with pytest.raises(StudyRetentionError, match=error):
        verify_implementation_validation(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_phase0_copies_all_four_raw_inputs_without_rerunning_candidates(
    retention_fixture: RetentionFixture,
) -> None:
    audit = run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )

    assert tuple(item.path for item in audit.retained_inputs) == EXPECTED_RETAINED_PATHS
    assert all(item.source_sha256 == item.copied_sha256 for item in audit.retained_inputs)
    assert tuple(item.byte_size for item in audit.retained_inputs) == tuple(
        len(payload) for payload in retention_fixture.source_payloads.values()
    )
    assert audit.evidence_commit == retention_fixture.evidence_commit
    assert retention_fixture.store.read_bytes("retained-inputs/candidate-a.json") == (
        retention_fixture.source_payloads["candidate_a"]
    )


def test_retention_record_binds_projection_dependency_seed_and_classifications(
    retention_fixture: RetentionFixture,
) -> None:
    audit = run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )

    assert audit.implementation_projection_sha256 == audit.dependency_report.projection_sha256
    assert audit.seed_disjointness.diagnostic_seed_start == 800000
    assert audit.seed_disjointness.diagnostic_seed_end == 800107
    assert audit.seed_disjointness.diagnostic_seed_count == 108
    assert audit.seed_disjointness.declared_evaluation_seed_count == 528
    assert audit.seed_disjointness.overlap_count == 0
    assert audit.seed_disjointness.overlap_seeds == ()
    assert audit.classifications.as_mapping() == EXPECTED_CLASSIFICATIONS
    stored = retention_fixture.store.verify_json(
        "retention-audit.json",
        expected_record_type="retention_audit",
    )
    assert stored == finalize_study_record(audit.as_record())


def test_retention_evidence_uses_portable_artifact_root_identity(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch a retention envelope that records its temporary runtime store path."""

    audit = run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )

    assert retention_fixture.protocol.artifact_root_identity == (
        "docs/evaluation/results/e1-feasibility-study"
    )
    assert audit.artifact_root == retention_fixture.protocol.artifact_root_identity
    stored = retention_fixture.store.verify_json(
        "retention-audit.json",
        expected_record_type="retention_audit",
    )
    assert stored["artifact_root"] == retention_fixture.protocol.artifact_root_identity


def test_run_retention_requires_validation_execution_commit_match(
    retention_fixture: RetentionFixture,
) -> None:
    with pytest.raises(StudyRetentionError, match="execution commit"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit="f" * 40,
            repo_root=retention_fixture.repo_root,
        )
    assert not (retention_fixture.protocol.artifact_root / "retention-audit.json").exists()


def test_run_retention_preflights_all_sources_before_any_copy(
    retention_fixture: RetentionFixture,
) -> None:
    (
        retention_fixture.repo_root
        / "docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt"
    ).unlink()

    with pytest.raises(StudyRetentionError, match="retained input"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )
    assert not any(
        (retention_fixture.protocol.artifact_root / path).exists()
        for path in EXPECTED_RETAINED_PATHS
    )


def test_run_retention_preflights_all_destinations_before_any_copy(
    retention_fixture: RetentionFixture,
) -> None:
    retention_fixture.store.publish_bytes(
        "retained-inputs/candidate-b.json",
        b"pre-existing immutable artifact",
        media_type="application/json",
    )
    _git(retention_fixture.repo_root, "add", "artifacts/retained-inputs/candidate-b.json")
    _git(retention_fixture.repo_root, "commit", "-m", "partial retained evidence")

    with pytest.raises(StudyRetentionError, match="already exists"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )
    assert not (
        retention_fixture.protocol.artifact_root / "retained-inputs/candidate-a.json"
    ).exists()


def test_run_retention_rejects_non_evidence_git_lineage(
    retention_fixture: RetentionFixture,
) -> None:
    _write(retention_fixture.repo_root / "unrelated.txt", b"not evidence\n")
    _git(retention_fixture.repo_root, "add", "unrelated.txt")
    _git(retention_fixture.repo_root, "commit", "-m", "unrelated change")

    with pytest.raises(StudyRetentionError, match="evidence-only lineage"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )


def test_run_retention_preserves_committed_rename_source_identity(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch a rename whose non-artifact source is hidden by its artifact destination."""

    destination = "artifacts/renamed-lineage-source.txt"
    _git(
        retention_fixture.repo_root,
        "mv",
        "lineage-source.txt",
        destination,
    )
    _git(retention_fixture.repo_root, "commit", "-m", "rename source into evidence")

    with pytest.raises(StudyRetentionError, match="non-artifact paths"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )


def test_run_retention_preserves_committed_copy_source_identity(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch a copy whose non-artifact source is hidden by its artifact destination."""

    source = retention_fixture.repo_root / "lineage-source.txt"
    destination = retention_fixture.protocol.artifact_root / "copied-lineage-source.txt"
    _write(destination, source.read_bytes())
    _git(
        retention_fixture.repo_root,
        "add",
        "artifacts/copied-lineage-source.txt",
    )
    _git(retention_fixture.repo_root, "commit", "-m", "copy source into evidence")

    with pytest.raises(StudyRetentionError, match="non-artifact paths"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )


def test_run_retention_rejects_fixed_source_copied_to_wrong_artifact_destination(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch copy authorization that checks a retained source without its destination."""

    source = (
        retention_fixture.repo_root / "data/e1-v2-development/candidate-a.json"
    )
    destination = retention_fixture.protocol.artifact_root / "wrong-candidate-a.json"
    _write(destination, source.read_bytes())
    _git(retention_fixture.repo_root, "add", "artifacts/wrong-candidate-a.json")
    _git(retention_fixture.repo_root, "commit", "-m", "copy fixed source wrongly")

    with pytest.raises(StudyRetentionError, match="non-artifact paths"):
        retention_module._verify_git_lineage(
            retention_fixture.protocol,
            repo_root=retention_fixture.repo_root,
            execution_commit=retention_fixture.execution_commit,
            evidence_commit=None,
            require_clean=True,
            allow_retained_input_copies=True,
        )


def test_git_lineage_rejects_wrong_source_copied_to_fixed_retained_destination(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch copy authorization that checks a retained destination without its source."""

    source = retention_fixture.repo_root / "lineage-source.txt"
    destination = (
        retention_fixture.protocol.artifact_root / "retained-inputs/candidate-a.json"
    )
    _write(destination, source.read_bytes())
    _git(
        retention_fixture.repo_root,
        "add",
        "artifacts/retained-inputs/candidate-a.json",
    )
    _git(retention_fixture.repo_root, "commit", "-m", "copy wrong source to fixed path")

    with pytest.raises(StudyRetentionError, match="non-artifact paths"):
        retention_module._verify_git_lineage(
            retention_fixture.protocol,
            repo_root=retention_fixture.repo_root,
            execution_commit=retention_fixture.execution_commit,
            evidence_commit=None,
            require_clean=True,
            allow_retained_input_copies=True,
        )


def test_git_lineage_never_exempts_fixed_retained_pair_rename(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch retained-copy authorization that accidentally admits an exact rename."""

    source = "data/e1-v2-development/candidate-a.json"
    destination = "artifacts/retained-inputs/candidate-a.json"
    (retention_fixture.repo_root / destination).parent.mkdir(parents=True, exist_ok=True)
    _git(retention_fixture.repo_root, "mv", source, destination)
    _git(retention_fixture.repo_root, "commit", "-m", "rename fixed retained pair")

    with pytest.raises(StudyRetentionError, match="non-artifact paths"):
        retention_module._verify_git_lineage(
            retention_fixture.protocol,
            repo_root=retention_fixture.repo_root,
            execution_commit=retention_fixture.execution_commit,
            evidence_commit=None,
            require_clean=True,
            allow_retained_input_copies=True,
        )


@pytest.mark.parametrize("change", ("modified", "deleted"))
def test_run_retention_rejects_committed_modify_and_delete_statuses(
    retention_fixture: RetentionFixture,
    change: str,
) -> None:
    """Catch name-status parsing that drops an ordinary modified or deleted path."""

    source = retention_fixture.repo_root / "lineage-source.txt"
    if change == "modified":
        source.write_bytes(b"modified outside evidence root\n")
    else:
        source.unlink()
    _git(retention_fixture.repo_root, "add", "-A", "lineage-source.txt")
    _git(retention_fixture.repo_root, "commit", "-m", f"{change} source")

    with pytest.raises(StudyRetentionError, match="non-artifact paths"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )


@pytest.mark.parametrize(
    "relative",
    (
        "committed -> artifacts/forged.json",
        'committed"quote.txt',
        "committed\ttab.txt",
        "committed\nnewline.txt",
    ),
)
def test_run_retention_rejects_committed_special_non_artifact_paths(
    retention_fixture: RetentionFixture,
    relative: str,
) -> None:
    """Catch NUL parsing that alters an added non-artifact path's raw identity."""

    _write(retention_fixture.repo_root / relative, b"committed outside evidence root\n")
    _git(retention_fixture.repo_root, "add", "--", relative)
    _git(retention_fixture.repo_root, "commit", "-m", "add special source")

    with pytest.raises(StudyRetentionError, match="non-artifact paths"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )


def test_verify_retention_preserves_dirty_rename_source_identity(
    retention_fixture: RetentionFixture,
) -> None:
    """Catch porcelain parsing that keeps only the destination of a staged rename."""

    run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    _git(
        retention_fixture.repo_root,
        "mv",
        "lineage-source.txt",
        "artifacts/renamed-lineage-source.txt",
    )

    with pytest.raises(StudyRetentionError, match="dirty non-artifact paths"):
        verify_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


@pytest.mark.parametrize(
    "relative",
    (
        "outside -> artifacts/forged.json",
        'outside"quote.txt',
        "outside\ttab.txt",
        "outside\nnewline.txt",
    ),
)
def test_verify_retention_rejects_dirty_special_non_artifact_paths(
    retention_fixture: RetentionFixture,
    relative: str,
) -> None:
    """Catch human-oriented Git parsing that quotes, splits, or redirects a path."""

    run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    _write(retention_fixture.repo_root / relative, b"dirty outside evidence root\n")

    with pytest.raises(StudyRetentionError, match="dirty non-artifact paths"):
        verify_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_run_retention_requires_frozen_source_branch(
    retention_fixture: RetentionFixture,
) -> None:
    _git(
        retention_fixture.repo_root,
        "branch",
        "-f",
        "codex/e1-v2-scale-feature-remediation",
        retention_fixture.execution_commit,
    )

    with pytest.raises(StudyRetentionError, match="source branch"):
        run_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            execution_commit=retention_fixture.execution_commit,
            repo_root=retention_fixture.repo_root,
        )


def test_verify_retention_rechecks_every_copy_and_source(
    retention_fixture: RetentionFixture,
) -> None:
    run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    copied = retention_fixture.protocol.artifact_root / "retained-inputs/candidate-b.json"
    copied.write_bytes(b"tampered copy")

    with pytest.raises(StudyRetentionError, match="retained copy"):
        verify_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_verify_retention_rechecks_current_source_hash(
    retention_fixture: RetentionFixture,
) -> None:
    run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    source = retention_fixture.repo_root / "data/e1-v2-development/candidate-a.json"
    source.write_bytes(b"tampered source")

    with pytest.raises(StudyRetentionError, match="source hash"):
        verify_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_verify_retention_rejects_upstream_raw_tamper(
    retention_fixture: RetentionFixture,
) -> None:
    run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    validation = load_strict_json_object(_validation_path(retention_fixture).read_bytes())
    payload = cast(dict[str, object], validation["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    commands[0]["stdout_sha256"] = sha256_bytes(b"semantically valid change")
    _rewrite_json(_validation_path(retention_fixture), validation)

    with pytest.raises(StudyRetentionError, match="upstream raw hash"):
        verify_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_verify_retention_rejects_upstream_self_hash_tamper(
    retention_fixture: RetentionFixture,
) -> None:
    run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    retention = load_strict_json_object(_retention_path(retention_fixture).read_bytes())
    upstream = cast(list[dict[str, object]], retention["upstream_artifacts"])[0]
    upstream["record_sha256"] = sha256_bytes(b"wrong upstream self hash")
    _rewrite_json(_retention_path(retention_fixture), retention)

    with pytest.raises(StudyRetentionError, match="upstream self-hash"):
        verify_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_verify_retention_rejects_current_projection_tamper(
    retention_fixture: RetentionFixture,
) -> None:
    run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    projected = retention_fixture.repo_root / "src/manufacturing_vision_studio/e1/model.py"
    projected.write_text(projected.read_text() + "\n# tampered\n")

    with pytest.raises(StudyRetentionError, match="implementation projection"):
        verify_retention_audit(
            retention_fixture.protocol,
            retention_fixture.store,
            repo_root=retention_fixture.repo_root,
        )


def test_retention_reverification_accepts_later_artifact_only_commit(
    retention_fixture: RetentionFixture,
) -> None:
    original = run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
        repo_root=retention_fixture.repo_root,
    )
    _git(retention_fixture.repo_root, "add", "artifacts")
    _git(retention_fixture.repo_root, "commit", "-m", "retention evidence")

    verified = verify_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        repo_root=retention_fixture.repo_root,
    )

    assert verified == original
    assert verified.evidence_commit == retention_fixture.evidence_commit
