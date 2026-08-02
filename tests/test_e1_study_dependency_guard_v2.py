from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from manufacturing_vision_studio.e1 import study_retention_v2 as retention_module
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
ORACLE_PATH = Path("src/manufacturing_vision_studio/e1/oracle.py")
DIAGNOSTICS_PATH = Path("src/manufacturing_vision_studio/e1/diagnostics_v2.py")

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
    source_root = PROJECT_ROOT / "src/manufacturing_vision_studio"
    for source in sorted(source_root.rglob("*.py")):
        destination = repo_root / source.relative_to(PROJECT_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
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


@pytest.mark.parametrize(
    "call_name",
    [
        "compare_candidates",
        "load_candidate_selection",
        "repair_candidate_selection_from_preserved_run",
        "select_candidate",
        "FreeCADExportAdapter",
    ],
)
def test_runtime_transitive_forbidden_call_is_rejected(
    tmp_path: Path,
    call_name: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, ORACLE_PATH, f"\nFORBIDDEN_RESULT = {call_name}()\n")

    with pytest.raises(StudyRetentionError, match=call_name):
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


def test_root_lazy_export_is_rejected_fail_closed(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nfrom manufacturing_vision_studio import FreeCADExportAdapter\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match=r"unresolved package symbol import.*FreeCADExportAdapter",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (
            "\nimport manufacturing_vision_studio as mvs\n"
            "PACKAGE_VALUE = mvs.FreeCADExportAdapter\n",
            "runtime package-object import",
        ),
        (
            "\nimport manufacturing_vision_studio\n"
            "PACKAGE_VALUE = manufacturing_vision_studio.FreeCADExportAdapter\n",
            "runtime package-object import",
        ),
        (
            "\nimport manufacturing_vision_studio as mvs\n"
            "PACKAGE_VALUE = getattr(mvs, 'FreeCADExportAdapter')\n",
            "runtime package-object import",
        ),
        (
            "\nimport manufacturing_vision_studio as mvs\n"
            "package_alias = mvs\n"
            "PACKAGE_VALUE = package_alias.FreeCADExportAdapter\n",
            "runtime package-object import",
        ),
        (
            "\nimport manufacturing_vision_studio.e1 as e1_package\n"
            "PACKAGE_VALUE = e1_package.render_e1_case\n",
            "runtime package-object import",
        ),
        (
            "\nimport manufacturing_vision_studio as mvs\n"
            "attribute_name = 'FreeCADExportAdapter'\n"
            "PACKAGE_VALUE = getattr(mvs, attribute_name)\n",
            "runtime package-object import",
        ),
        (
            "\nimport manufacturing_vision_studio as mvs\n"
            "PACKAGE_VALUE = mvs.adapters\n",
            "runtime package-object import",
        ),
    ],
)
def test_package_object_attribute_access_is_rejected_fail_closed(
    tmp_path: Path,
    source: str,
    error: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match=error):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    [
        "\nimport manufacturing_vision_studio\n",
        "\nimport manufacturing_vision_studio as mvs\n",
        "\nimport manufacturing_vision_studio.e1\n",
        "\nimport manufacturing_vision_studio.e1 as e1_package\n",
    ],
)
def test_runtime_package_object_import_is_rejected_at_source(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match="runtime package-object import"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    [
        "\nimport manufacturing_vision_studio.canonical\n",
        "\nfrom manufacturing_vision_studio import canonical\n",
        "\nimport manufacturing_vision_studio.e1.domain\n",
        "\nfrom manufacturing_vision_studio.e1 import domain\n",
    ],
)
def test_explicit_real_submodule_import_uses_normal_closure(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, FEATURE_MAPPING_PATH, source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_type_only_package_and_importlib_imports_remain_type_only(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nfrom typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import manufacturing_vision_studio\n"
        "    import manufacturing_vision_studio as mvs\n"
        "    import manufacturing_vision_studio.e1\n"
        "    import manufacturing_vision_studio.e1 as e1_package\n"
        "    import importlib\n"
        "    from importlib import import_module as type_loader\n",
    )

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert any(
        edge.source == "manufacturing_vision_studio.e1.study_runner_v2"
        and edge.target == "manufacturing_vision_studio"
        and edge.kind == "type_checking"
        for edge in report.edges
    )
    assert any(
        edge.source == "manufacturing_vision_studio.e1.study_runner_v2"
        and edge.target == "manufacturing_vision_studio.e1"
        and edge.kind == "type_checking"
        for edge in report.edges
    )


@pytest.mark.parametrize(
    "source",
    [
        "\nimport importlib\n",
        "\nimport importlib as import_tools\n",
        "\nimport importlib.util\n",
        "\nimport importlib.util as import_tools\n",
        "\nfrom importlib import import_module\n",
        "\nfrom importlib import import_module as load_module\n",
        "\nfrom importlib.resources import files\n",
    ],
)
def test_runtime_importlib_import_is_rejected_at_source(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match="runtime importlib import"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (
            "\nimport manufacturing_vision_studio as mvs\n"
            "package_alias: object = mvs\n"
            "PACKAGE_VALUE = package_alias.FreeCADExportAdapter\n",
            "runtime package-object import",
        ),
        (
            "\nimport manufacturing_vision_studio as mvs\n"
            "package_alias, other = mvs, None\n"
            "PACKAGE_VALUE = package_alias.FreeCADExportAdapter\n",
            "runtime package-object import",
        ),
        (
            "\nimport importlib\n"
            "loader: object = importlib.import_module\n"
            "REFLECTED = loader('manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nimport importlib\n"
            "loader, other = importlib.import_module, None\n"
            "REFLECTED = loader('manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
    ],
)
def test_runtime_loader_source_rejects_annotated_and_tuple_laundering(
    tmp_path: Path,
    source: str,
    error: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match=error):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    [
        "\nLOADER = __import__\n",
        "\nREFLECTED = getattr(__builtins__, '__import__')\n",
        "\nimport builtins\nREFLECTED = getattr(builtins, '__import__')\n",
    ],
)
def test_runtime_builtin_import_symbol_access_is_rejected(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match="runtime __import__"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_real_pep562_initializers_preserve_complete_dependency_closure(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert dict(report.direct_import_allowlist) == dict(protocol.direct_import_allowlist())


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            "\nLAUNDERED_LOADER: object = import_module\n",
        ),
        (
            Path("src/manufacturing_vision_studio/e1/__init__.py"),
            "\nLAUNDERED_LOADER, other = import_module, None\n",
        ),
    ],
)
def test_pep562_initializer_import_module_symbol_cannot_be_laundered(
    tmp_path: Path,
    relative: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, relative, source)

    with pytest.raises(
        StudyRetentionError,
        match="runtime importlib loader symbol access",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (
            "\nimport importlib\n"
            "DYNAMIC_MODULE = importlib.import_module("
            "'manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nfrom importlib import import_module as load_module\n"
            "DYNAMIC_MODULE = load_module('manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nDYNAMIC_MODULE = __import__('manufacturing_vision_studio.adapters')\n",
            "runtime __import__",
        ),
        (
            "\nimport importlib\n"
            "DYNAMIC_MODULE = importlib.import_module("
            "'manufacturing_vision_studio.not_real')\n",
            "runtime importlib import",
        ),
    ],
)
def test_literal_dynamic_package_import_is_rejected(
    tmp_path: Path,
    source: str,
    error: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match=error):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_nonliteral_dynamic_package_import_is_rejected(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nimport importlib\n"
        "def load_dynamic(module_name: str) -> object:\n"
        "    return importlib.import_module(module_name)\n"
        "DYNAMIC_MODULE = load_dynamic('manufacturing_vision_studio.adapters')\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match="runtime importlib import",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (
            "\nimport importlib\n"
            "REFLECTED_MODULE = getattr(importlib, 'import_module')("
            "'manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nimport importlib as import_tools\n"
            "REFLECTED_MODULE = getattr(import_tools, 'import_module')("
            "'manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nimport importlib\n"
            "loader = importlib.import_module\n"
            "REFLECTED_MODULE = loader('manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nimport importlib\n"
            "loader = getattr(importlib, 'import_module')\n"
            "REFLECTED_MODULE = loader('manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nimport importlib\n"
            "loader = importlib.import_module\n"
            "loader_alias = loader\n"
            "REFLECTED_MODULE = loader_alias("
            "'manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nimport importlib\n"
            "loader_name = 'import_module'\n"
            "REFLECTED_MODULE = getattr(importlib, loader_name)("
            "'manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
        (
            "\nimport importlib\n"
            "def load_reflected(module_name: str) -> object:\n"
            "    return getattr(importlib, 'import_module')(module_name)\n"
            "REFLECTED_MODULE = load_reflected("
            "'manufacturing_vision_studio.adapters')\n",
            "runtime importlib import",
        ),
    ],
)
def test_reflective_import_loader_is_rejected_fail_closed(
    tmp_path: Path,
    source: str,
    error: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match=error):
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


def test_scanner_parses_the_exact_bounded_bytes_bound_into_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    oracle_path = repo_root / ORACLE_PATH
    safe_payload = oracle_path.read_bytes()
    forbidden_payload = safe_payload + b"\nFORBIDDEN_RESULT = compare_candidates()\n"
    oracle_path.write_bytes(forbidden_payload)
    original_reader = retention_module.read_bounded_bytes
    swapped = False

    def swap_after_bounded_read(path: Path, *, maximum: int) -> bytes:
        nonlocal swapped
        payload = original_reader(path, maximum=maximum)
        if path == oracle_path and not swapped:
            assert payload == forbidden_payload
            oracle_path.write_bytes(safe_payload)
            swapped = True
        return payload

    monkeypatch.setattr(retention_module, "read_bounded_bytes", swap_after_bounded_read)

    with pytest.raises(StudyRetentionError, match="compare_candidates"):
        scan_study_dependencies(protocol, repo_root=repo_root)
    assert swapped is True


def test_fixture_copy_keeps_repository_source_unchanged(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    original = (PROJECT_ROOT / FEATURE_MAPPING_PATH).read_bytes()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, FEATURE_MAPPING_PATH, "\nFIXTURE_ONLY = True\n")

    assert (PROJECT_ROOT / FEATURE_MAPPING_PATH).read_bytes() == original
    assert (repo_root / FEATURE_MAPPING_PATH).read_bytes() != original


def test_complete_repo_preserves_and_rejects_real_unprojected_modules(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    diagnostics = repo_root / DIAGNOSTICS_PATH
    assert diagnostics.read_bytes() == (PROJECT_ROOT / DIAGNOSTICS_PATH).read_bytes()
    _append(
        repo_root,
        RUNNER_PATH,
        "\nfrom manufacturing_vision_studio.e1 import diagnostics_v2\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match=r"unprojected repository import:.*diagnostics_v2",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)
