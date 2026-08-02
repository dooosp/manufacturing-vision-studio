from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from manufacturing_vision_studio.e1.study_protocol_v2 import (
    PROJECT_ROOT,
    StudyProtocolV2,
    load_study_protocol_v2,
)
from manufacturing_vision_studio.e1.study_retention_v2 import (
    StudyRetentionError,
    build_study_implementation_projection,
    scan_study_dependencies,
)

RUNNER_PATH = Path("src/manufacturing_vision_studio/e1/study_runner_v2.py")
CLI_PATH = Path("src/manufacturing_vision_studio/e1/study_cli_v2.py")
RETENTION_PATH = Path("src/manufacturing_vision_studio/e1/study_retention_v2.py")
FEATURE_MAPPING_PATH = Path("src/manufacturing_vision_studio/e1/feature_mapping.py")

SYNTHETIC_RUNNER = (
    b"from manufacturing_vision_studio.e1.feature_mapping "
    b"import FeatureMappingResult\n"
    b"from manufacturing_vision_studio.e1.metrics_v2 import E1V2MetricSummary\n"
    b"from manufacturing_vision_studio.e1.study_retention_v2 import RetentionAudit\n"
    b"\nMARKER = (FeatureMappingResult, E1V2MetricSummary, RetentionAudit)\n"
)
SYNTHETIC_CLI = b"""from manufacturing_vision_studio.e1.study_runner_v2 import MARKER

CLI_MARKER = MARKER
"""


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _complete_repo(tmp_path: Path, protocol: StudyProtocolV2) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for relative in protocol.implementation_projection_paths():
        destination = repo_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if Path(relative) == RUNNER_PATH:
            destination.write_bytes(SYNTHETIC_RUNNER)
        elif Path(relative) == CLI_PATH:
            destination.write_bytes(SYNTHETIC_CLI)
        else:
            destination.write_bytes((PROJECT_ROOT / relative).read_bytes())
    _git(repo_root, "init", "-b", "fixture")
    _git(repo_root, "config", "user.name", "Task 6 Test")
    _git(repo_root, "config", "user.email", "task6@example.invalid")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "fixture")
    return repo_root


def _append(repo_root: Path, relative: Path, source: str) -> None:
    path = repo_root / relative
    path.write_text(path.read_text() + source)


def test_real_task_6_checkout_is_missing_only_task_7_roots() -> None:
    with pytest.raises(StudyRetentionError) as raised:
        scan_study_dependencies(load_study_protocol_v2())

    assert str(raised.value) == (
        "missing projected paths: "
        "src/manufacturing_vision_studio/e1/study_cli_v2.py, "
        "src/manufacturing_vision_studio/e1/study_runner_v2.py"
    )


def test_complete_projection_hashes_every_declared_path(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)

    projection = build_study_implementation_projection(protocol, repo_root=repo_root)

    assert len(projection) == 47
    assert tuple(item.path for item in projection) == protocol.implementation_projection_paths()
    assert all(len(item.sha256) == 64 for item in projection)


def test_projection_must_equal_the_protocol_document(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    extra = "zz-task6-extra.txt"
    (repo_root / extra).write_text("tracked but undeclared by the protocol document\n")
    _git(repo_root, "add", extra)
    candidate = replace(
        protocol,
        _implementation_projection_paths=(
            *protocol.implementation_projection_paths(),
            extra,
        ),
    )

    with pytest.raises(StudyRetentionError, match="protocol document"):
        build_study_implementation_projection(candidate, repo_root=repo_root)


def test_dependency_scan_classifies_edges_by_responsibility(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert not report.forbidden_direct_edges
    assert not report.protected_scope_references
    assert dict(report.direct_import_allowlist) == dict(protocol.direct_import_allowlist())
    assert any(
        edge.source.endswith("feature_mapping")
        and edge.target.endswith("oracle")
        and edge.kind == "runtime_transitive"
        for edge in report.edges
    )
    assert any(
        edge.source.endswith("metrics_v2")
        and edge.target.endswith("policy_v2")
        and edge.kind == "type_checking"
        for edge in report.edges
    )


def test_generator_internal_plan_validation_is_permitted(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert report.protected_scope_references == ()


@pytest.mark.parametrize("failure", ["missing", "untracked", "extra", "duplicate", "outside"])
def test_projection_fails_closed_for_every_completeness_violation(
    tmp_path: Path,
    failure: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    candidate = protocol
    if failure == "missing":
        (repo_root / RUNNER_PATH).unlink()
    elif failure == "untracked":
        _git(repo_root, "rm", "--cached", RUNNER_PATH.as_posix())
    elif failure == "extra":
        unreviewed = Path("src/manufacturing_vision_studio/e1/unreviewed.py")
        (repo_root / unreviewed).write_text("MARKER = True\n")
        _git(repo_root, "add", unreviewed.as_posix())
        _append(
            repo_root,
            RUNNER_PATH,
            "\nfrom manufacturing_vision_studio.e1.unreviewed import MARKER\n",
        )
    elif failure == "duplicate":
        paths = protocol.implementation_projection_paths()
        candidate = replace(
            protocol,
            _implementation_projection_paths=(*paths, paths[-1]),
        )
    else:
        candidate = replace(
            protocol,
            _implementation_projection_paths=(
                "../outside.py",
                *protocol.implementation_projection_paths()[1:],
            ),
        )

    with pytest.raises(StudyRetentionError):
        scan_study_dependencies(candidate, repo_root=repo_root)


def test_forbidden_direct_import_is_rejected_even_when_projected(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nfrom manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_retained_direct_import_must_equal_the_module_allowlist(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        CLI_PATH,
        "\nfrom manufacturing_vision_studio.canonical import sha256_bytes\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match=r"direct import allowlist mismatch.*study_cli_v2",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_protected_scope_reference_is_rejected(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nfrom manufacturing_vision_studio.e1.domain_v2 import EvaluationScope\n"
        "PROTECTED = EvaluationScope.CALIBRATION\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match=r"protected scope reference.*CALIBRATION",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_plan_cases_outside_development_provider_is_rejected(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\ndef forbidden(generator: object) -> object:\n"
        "    return generator.plan_cases('development')\n",
    )

    with pytest.raises(StudyRetentionError, match="plan_cases outside DevelopmentCorpusProvider"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_development_provider_allows_only_its_frozen_generator_call(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    truth_path = repo_root / "src/manufacturing_vision_studio/e1/study_truth_v2.py"
    original = truth_path.read_text()
    modified = original.replace(
        "self._generator.plan_cases(EvaluationScope.DEVELOPMENT)",
        "self._other.plan_cases(EvaluationScope.DEVELOPMENT)",
    )
    assert modified != original
    truth_path.write_text(modified)

    with pytest.raises(StudyRetentionError, match="plan_cases outside DevelopmentCorpusProvider"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_performance_root_cannot_reach_freecad_adapter(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        FEATURE_MAPPING_PATH,
        "\nfrom manufacturing_vision_studio.adapters import FreeCADExportAdapter\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match=r"forbidden performance closure.*adapters",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_scanner_does_not_execute_projected_modules(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    sentinel = repo_root / "executed.txt"
    _append(
        repo_root,
        RETENTION_PATH,
        f"\nopen({str(sentinel)!r}, 'w').write('executed')\n",
    )

    scan_study_dependencies(protocol, repo_root=repo_root)

    assert not sentinel.exists()


def test_fixture_copy_keeps_repository_source_unchanged(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    original = (PROJECT_ROOT / FEATURE_MAPPING_PATH).read_bytes()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, FEATURE_MAPPING_PATH, "\nFIXTURE_ONLY = True\n")

    assert (PROJECT_ROOT / FEATURE_MAPPING_PATH).read_bytes() == original
    assert (repo_root / FEATURE_MAPPING_PATH).read_bytes() != original
