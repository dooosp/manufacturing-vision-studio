from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
import warnings
from dataclasses import replace
from pathlib import Path

import pytest

from manufacturing_vision_studio.e1 import study_artifacts_v2 as artifacts_module
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
    b"import manufacturing_vision_studio.canonical_png as canonical_png, "
    b"manufacturing_vision_studio.e1.feature_mapping as feature_mapping, "
    b"manufacturing_vision_studio.e1.metrics_v2 as metrics_v2, "
    b"manufacturing_vision_studio.e1.protocol_v2 as protocol_v2\n"
    b"from manufacturing_vision_studio.e1.study_retention_v2 import RetentionAudit\n"
    b"MARKER = (canonical_png, feature_mapping, metrics_v2, protocol_v2, RetentionAudit)\n"
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


def _complete_repo(
    tmp_path: Path,
    protocol: StudyProtocolV2,
    *,
    preserve_real_cli: bool = False,
) -> Path:
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
        elif Path(relative) == CLI_PATH and not preserve_real_cli:
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


def _compiled_source(source: str) -> str:
    compile(source, "<dependency-guard-fixture>", "exec", dont_inherit=True)
    return source


def _execute_source(source: str, namespace: dict[str, object]) -> None:
    code = compile(source, "<dependency-guard-runtime-trace>", "exec", dont_inherit=True)
    exec(code, namespace)


def _compile_without_emitting_warnings(source: str) -> object:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SyntaxWarning)
        code = compile(source, "<dependency-guard-warning-fixture>", "exec", dont_inherit=True)
    assert [warning.category for warning in caught] == [SyntaxWarning]
    return code


def test_real_task_7_checkout_has_the_exact_reviewed_dependency_closure() -> None:
    protocol = load_study_protocol_v2()

    projection = build_study_implementation_projection(protocol)
    report = scan_study_dependencies(protocol)

    assert len(projection) == 47
    assert tuple(entry.path for entry in projection) == (
        protocol.implementation_projection_paths()
    )
    assert report.forbidden_direct_edges == ()
    assert report.protected_scope_references == ()
    allowlist = dict(report.direct_import_allowlist)
    assert allowlist["study_runner_v2"] == (
        "manufacturing_vision_studio.canonical_png",
        "manufacturing_vision_studio.e1.feature_mapping",
        "manufacturing_vision_studio.e1.metrics_v2",
        "manufacturing_vision_studio.e1.protocol_v2",
    )
    assert allowlist["study_cli_v2"] == ()

    study_modules = {
        f"manufacturing_vision_studio.e1.{name}"
        for name in protocol.direct_import_allowlist()
    }
    orchestration_roots = {
        "manufacturing_vision_studio.e1.study_cli_v2",
        "manufacturing_vision_studio.e1.study_runner_v2",
    }
    internal_runtime_edges = {
        (edge.source, edge.target)
        for edge in report.edges
        if edge.kind != "type_checking"
        and edge.source in orchestration_roots
        and edge.target in study_modules
    }
    assert internal_runtime_edges == {
        (
            "manufacturing_vision_studio.e1.study_cli_v2",
            "manufacturing_vision_studio.e1.study_runner_v2",
        ),
        (
            "manufacturing_vision_studio.e1.study_runner_v2",
            "manufacturing_vision_studio.e1.known_transform_v2",
        ),
        (
            "manufacturing_vision_studio.e1.study_runner_v2",
            "manufacturing_vision_studio.e1.study_artifacts_v2",
        ),
        (
            "manufacturing_vision_studio.e1.study_runner_v2",
            "manufacturing_vision_studio.e1.study_inference_v2",
        ),
        (
            "manufacturing_vision_studio.e1.study_runner_v2",
            "manufacturing_vision_studio.e1.study_protocol_v2",
        ),
        (
            "manufacturing_vision_studio.e1.study_runner_v2",
            "manufacturing_vision_studio.e1.study_retention_v2",
        ),
        (
            "manufacturing_vision_studio.e1.study_runner_v2",
            "manufacturing_vision_studio.e1.study_truth_v2",
        ),
    }
    assert all(source != target for source, target in internal_runtime_edges)
    assert not any(
        reverse in internal_runtime_edges
        for reverse in ((target, source) for source, target in internal_runtime_edges)
    )


@pytest.mark.parametrize(
    "module_order",
    [
        ("study_cli_v2", "study_runner_v2"),
        ("study_runner_v2", "study_cli_v2"),
    ],
)
def test_real_task_7_import_order_keeps_forbidden_modules_and_exports_out(
    module_order: tuple[str, str],
) -> None:
    source = f"""
        import importlib
        import sys
        import manufacturing_vision_studio.e1 as package

        exports_before = tuple(package.__all__)
        first = importlib.import_module(
            "manufacturing_vision_studio.e1.{module_order[0]}"
        )
        second = importlib.import_module(
            "manufacturing_vision_studio.e1.{module_order[1]}"
        )
        runner = importlib.import_module(
            "manufacturing_vision_studio.e1.study_runner_v2"
        )
        cli = importlib.import_module(
            "manufacturing_vision_studio.e1.study_cli_v2"
        )
        assert first is sys.modules[first.__name__]
        assert second is sys.modules[second.__name__]
        assert cli.study_runner_v2 is runner

        forbidden_prefixes = {(
            "manufacturing_vision_studio.adapters",
            "manufacturing_vision_studio.api",
            "manufacturing_vision_studio.cli",
            "manufacturing_vision_studio.e1.baseline",
            "manufacturing_vision_studio.e1.diagnostics_v2",
            "manufacturing_vision_studio.e1.geometry",
            "manufacturing_vision_studio.e1.geometry_search",
            "manufacturing_vision_studio.e1.overlap_v2",
            "manufacturing_vision_studio.e1.policy",
            "manufacturing_vision_studio.e1.policy_v2",
            "manufacturing_vision_studio.e1.runner",
            "manufacturing_vision_studio.e1.trust_boundaries",
        )!r}
        loaded_forbidden = {{
            name
            for name in sys.modules
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            )
        }}
        assert not loaded_forbidden, loaded_forbidden
        assert tuple(package.__all__) == exports_before
        assert {{
            "StudyRunner",
            "main",
            "study_cli_v2",
            "study_runner_v2",
        }}.isdisjoint(package.__all__)
    """
    result = subprocess.run(
        (sys.executable, "-c", textwrap.dedent(source)),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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


def test_runtime_cycle_between_study_owned_modules_is_rejected(tmp_path: Path) -> None:
    """Catch a runtime back-edge that makes study orchestration import-order dependent."""

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RETENTION_PATH,
        "\nfrom manufacturing_vision_studio.e1.study_runner_v2 import MARKER\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match=r"runtime cycle among study-owned modules:.*study_retention_v2.*study_runner_v2",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_type_checking_cycle_between_study_owned_modules_is_allowed(
    tmp_path: Path,
) -> None:
    """Catch cycle detection that mistakes a type-only edge for runtime execution."""

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RETENTION_PATH,
        "\nfrom typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.study_runner_v2 import MARKER\n",
    )

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert any(
        edge.source == "manufacturing_vision_studio.e1.study_retention_v2"
        and edge.target == "manufacturing_vision_studio.e1.study_runner_v2"
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


@pytest.mark.parametrize(
    ("source", "error"),
    (
        (
            "from manufacturing_vision_studio.adapters import *\n",
            r"direct import allowlist mismatch.*study_runner_v2.*adapters",
        ),
        (
            "from manufacturing_vision_studio.not_real import *\n",
            "unresolved wildcard package import",
        ),
    ),
)
def test_wildcard_import_records_its_source_or_fails_closed(
    tmp_path: Path,
    source: str,
    error: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match=error):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_type_checking_unresolved_project_wildcard_fails_closed(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + _compiled_source(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from manufacturing_vision_studio.not_real import *\n"
        ),
    )

    with pytest.raises(
        StudyRetentionError,
        match="unresolved wildcard package import",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_wildcard_shadowed_name_does_not_fall_back_to_builtin(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, FEATURE_MAPPING_PATH, "\nimport sys\nlen = sys\n")
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + _compiled_source(
            "from manufacturing_vision_studio.e1.feature_mapping import *\n"
            "REGISTRY = len.modules\n"
        ),
    )

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_wildcard_shadow_preserves_sensitive_builtin_capability(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + _compiled_source(
            "from manufacturing_vision_studio.e1.feature_mapping import *\n"
            "RESULT = eval('1 + 1')\n"
        ),
    )

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_unresolved_project_import_fails_closed(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n" + _compiled_source("import manufacturing_vision_studio.not_real\n"),
    )

    with pytest.raises(StudyRetentionError, match="unresolved project import"):
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
    (
        "from typing import TYPE_CHECKING\n"
        "def guarded(TYPE_CHECKING: bool) -> None:\n"
        "    if TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "import typing as typing_alias\n"
        "typing_alias = object()\n"
        "if typing_alias.TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "from typing import TYPE_CHECKING\n"
        "flag = object()\n"
        "if flag:\n"
        "    TYPE_CHECKING = True\n"
        "if TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "from typing import TYPE_CHECKING\n"
        "def outer() -> None:\n"
        "    runtime_guard = TYPE_CHECKING\n"
        "    def inner() -> None:\n"
        "        nonlocal runtime_guard\n"
        "        runtime_guard = True\n"
        "        if runtime_guard:\n"
        "            from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    ),
)
def test_ambiguous_type_checking_bindings_are_runtime_code(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_late_bound_nonlocal_resolves_to_enclosing_function_scope(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\ndef outer() -> None:\n"
        "    def inner() -> None:\n"
        "        nonlocal late_bound\n"
        "        late_bound = object()\n"
        "    late_bound = object()\n",
    )

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: deferred-effect",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_nonlocal_skips_intermediate_function_without_binding(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nfrom typing import TYPE_CHECKING\n"
        "def outer() -> None:\n"
        "    outer_guard = TYPE_CHECKING\n"
        "    def intermediate() -> None:\n"
        "        def inner() -> None:\n"
        "            nonlocal outer_guard\n"
        "            if outer_guard:\n"
        "                from manufacturing_vision_studio.e1.policy_v2 "
        "import E1V2Policy\n",
    )

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert any(
        edge.source == "manufacturing_vision_studio.e1.study_runner_v2"
        and edge.target == "manufacturing_vision_studio.e1.policy_v2"
        and edge.kind == "type_checking"
        for edge in report.edges
    )


def test_class_body_resolves_outer_alias_before_class_name_binding(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nimport typing as T\n"
        "class T:\n"
        "    if T.TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    )

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert any(
        edge.source == "manufacturing_vision_studio.e1.study_runner_v2"
        and edge.target == "manufacturing_vision_studio.e1.policy_v2"
        and edge.kind == "type_checking"
        for edge in report.edges
    )


def test_try_body_rebinding_reaches_exception_handler(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nimport typing as typing_alias\n"
        "try:\n"
        "    typing_alias = object()\n"
        "    raise RuntimeError\n"
        "except RuntimeError:\n"
        "    if typing_alias.TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_starred_destructuring_shadows_type_checking_alias(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nimport typing as typing_alias\n"
        "head, *typing_alias = (None, None)\n"
        "if typing_alias.TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import typing as typing_alias\n"
        "def invalidate() -> None:\n"
        "    global typing_alias\n"
        "    del typing_alias\n"
        "    if typing_alias.TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "from typing import TYPE_CHECKING\n"
        "def outer() -> None:\n"
        "    guard = TYPE_CHECKING\n"
        "    def invalidate() -> None:\n"
        "        nonlocal guard\n"
        "        del guard\n"
        "        if guard:\n"
        "            from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    ),
)
def test_declaration_aware_delete_invalidates_type_checking_alias(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: deferred-effect",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


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
    ("case_id", "source"),
    [
        ("direct-loader-name", "\nLOADER = __import__\n"),
        ("reflected-builtins-getattr", "\nREFLECTED = getattr(__builtins__, '__import__')\n"),
        (
            "literal-builtins-getattr",
            "\nimport builtins\nREFLECTED = getattr(builtins, '__import__')\n",
        ),
        (
            "literal-builtins-dict-import",
            "\nimport builtins\n"
            "REFLECTED = builtins.__dict__['__import__']\n"
            "DYNAMIC = REFLECTED('manufacturing_vision_studio.adapters')\n",
        ),
        (
            "builtins-alias-dict-import",
            "\nimport builtins as b\n"
            "REFLECTED = b.__dict__['__import__']\n"
            "DYNAMIC = REFLECTED('manufacturing_vision_studio.adapters')\n",
        ),
        (
            "from-builtins-import-alias",
            "\nfrom builtins import __import__ as loader\n"
            "DYNAMIC = loader('manufacturing_vision_studio.adapters')\n",
        ),
        (
            "attribute-builtins-dict-import",
            "\nREFLECTED = __builtins__.__dict__['__import__']\n",
        ),
        (
            "implicit-builtins-dict-import",
            "\nREFLECTED = __builtins__['__import__']\n"
            "DYNAMIC = REFLECTED('manufacturing_vision_studio.adapters')\n",
        ),
    ],
    ids=lambda case: case if isinstance(case, str) else None,
)
def test_runtime_builtin_import_symbol_access_is_rejected(
    tmp_path: Path,
    case_id: str,
    source: str,
) -> None:
    del case_id
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match="runtime __import__"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (
            "\nexec('import manufacturing_vision_studio.adapters')\n",
            "runtime executable code",
        ),
        (
            "\neval('__import__(\\'manufacturing_vision_studio.adapters\\')')\n",
            "runtime executable code",
        ),
        (
            "\nimport runpy\n"
            "DYNAMIC_MODULE = runpy.run_module('manufacturing_vision_studio.adapters')\n",
            "runtime runpy loader",
        ),
        (
            "\nfrom runpy import run_path as load_path\n"
            "DYNAMIC_MODULE = load_path('tmp/module.py')\n",
            "runtime runpy loader",
        ),
    ],
)
def test_runtime_exec_eval_and_runpy_surfaces_are_rejected(
    tmp_path: Path,
    source: str,
    error: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, source)

    with pytest.raises(StudyRetentionError, match=error):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_shadowed_type_checking_is_treated_as_runtime_code(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\nfrom typing import TYPE_CHECKING\n"
        "TYPE_CHECKING = True\n"
        "if TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_real_pep562_initializers_preserve_complete_dependency_closure(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)

    report = scan_study_dependencies(protocol, repo_root=repo_root)

    assert dict(report.direct_import_allowlist) == dict(protocol.direct_import_allowlist())


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    (
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            "from importlib import import_module",
            "from importlib import import_module as load_module",
        ),
        (
            Path("src/manufacturing_vision_studio/e1/__init__.py"),
            "value = getattr(import_module(module_name), attribute_name)",
            "value = getattr(import_module(module_name), attribute_name)\n"
            "    import_module(module_name)",
        ),
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            '"manufacturing_vision_studio.registry", "CaseRegistry"',
            '"manufacturing_vision_studio.not_projected", "CaseRegistry"',
        ),
        (
            Path("src/manufacturing_vision_studio/e1/__init__.py"),
            "return sorted(set(globals()) | set(__all__))",
            "globals()\n    return sorted(set(globals()) | set(__all__))",
        ),
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            'f"module {__name__!r} has no attribute {name!r}"',
            'f"module {__name__!r} has no attribute {name!r}: {len(name)!r}"',
        ),
        (
            Path("src/manufacturing_vision_studio/e1/__init__.py"),
            'f"module {__name__!r} has no attribute {name!r}"',
            'f"module {name!r} has no attribute {name!r}"',
        ),
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            'f"module {__name__!r} has no attribute {name!r}"',
            'f"module {__name__!r} has no attribute {name!s}"',
        ),
        (
            Path("src/manufacturing_vision_studio/e1/__init__.py"),
            'f"module {__name__!r} has no attribute {name!r}"',
            'f"module {__name__!r} has no attribute {name!r:>10}"',
        ),
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            'f"module {__name__!r} has no attribute {name!r}"',
            'f"module {__name__!r} does not have attribute {name!r}"',
        ),
    ),
)
def test_pep562_initializer_requires_exact_capability_structure(
    tmp_path: Path,
    relative: Path,
    old: str,
    new: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    path = repo_root / relative
    source = path.read_text()
    changed = source.replace(old, new, 1)
    assert changed != source
    path.write_text(changed)

    with pytest.raises(StudyRetentionError, match="initializer capability structure"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_pep562_lazy_target_must_be_projected_not_merely_repository_known(
    tmp_path: Path,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    path = repo_root / "src/manufacturing_vision_studio/__init__.py"
    source = path.read_text()
    changed = source.replace(
        '"manufacturing_vision_studio.registry", "CaseRegistry"',
        '"manufacturing_vision_studio.api", "CaseRegistry"',
        1,
    )
    assert changed != source
    path.write_text(_compiled_source(changed))

    with pytest.raises(StudyRetentionError, match="lazy target is not projected"):
        scan_study_dependencies(protocol, repo_root=repo_root)


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
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            "\ndef laundered_loader() -> object:\n"
            "    return import_module\n",
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


def test_projection_rejects_intermediate_parent_swap_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A returned projection must never bind a hash from an outside parent."""

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    source_path = repo_root / "src/manufacturing_vision_studio/registry.py"
    original_parent = source_path.parent
    outside_parent = tmp_path / "outside-evaluation"
    outside_parent.mkdir()
    outside_payload = b'{"outside_parent_swap_marker":true}\n'
    (outside_parent / source_path.name).write_bytes(outside_payload)
    original_absolute = artifacts_module._absolute_lexical
    swapped = False

    def swap_parent_after_normalization(path: Path) -> Path:
        nonlocal swapped
        absolute = original_absolute(path)
        if absolute == source_path and not swapped:
            original_parent.rename(repo_root / "src/manufacturing_vision_studio-pinned")
            original_parent.symlink_to(outside_parent, target_is_directory=True)
            swapped = True
        return absolute

    monkeypatch.setattr(
        artifacts_module,
        "_absolute_lexical",
        swap_parent_after_normalization,
    )

    try:
        projection = build_study_implementation_projection(protocol, repo_root=repo_root)
    except StudyRetentionError:
        pass
    else:
        assert dict((entry.path, entry.sha256) for entry in projection)[
            "src/manufacturing_vision_studio/registry.py"
        ] != retention_module.sha256_bytes(outside_payload)
    assert swapped is True


@pytest.mark.parametrize(
    ("source", "expected_category"),
    (
        (
            "import sys as carrier\n"
            "EMPTY = [(carrier := carrier.stdout) for _ in (0,) if False]\n"
            "REGISTRY = carrier.modules\n",
            "import-registry",
        ),
        (
            "import sys as carrier\n"
            "HEAP = [item for _ in (0,) if False "
            "for item in (0,) if (carrier := carrier.stdout)]\n"
            "REGISTRY = carrier.modules\n",
            "import-registry",
        ),
        (
            "import sys as carrier\n"
            "DEFERRED = ((carrier := carrier.stdout) for _ in (0,))\n"
            "REGISTRY = carrier.modules\n",
            "deferred-effect",
        ),
        (
            "import sys as carrier\n"
            "EMPTY = [(carrier := carrier.stdout) for _ in ()]\n"
            "REGISTRY = carrier.modules\n",
            "import-registry",
        ),
    ),
)
def test_nonexecuted_comprehension_paths_preserve_sys_authority(
    tmp_path: Path,
    source: str,
    expected_category: str,
) -> None:
    if expected_category == "deferred-effect":
        namespace: dict[str, object] = {}
        exec(_compiled_source(source), namespace)
        assert namespace["carrier"] is sys

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match=rf"source capability rejected: {expected_category}",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_dormant_function_global_rebinding_preserves_sys_authority(tmp_path: Path) -> None:
    source = _compiled_source(
        "import sys as carrier\n"
        "def deferred() -> None:\n"
        "    global carrier\n"
        "    carrier = carrier.stdout\n"
        "REGISTRY = carrier.modules\n"
    )
    namespace: dict[str, object] = {}
    exec(source, namespace)
    assert namespace["carrier"] is sys

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)
    with pytest.raises(StudyRetentionError, match="source capability rejected: deferred-effect"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import sys\nfor carrier in (sys,):\n    REGISTRY = carrier.modules\n",
        "import sys\nmatch sys:\n    case carrier:\n        REGISTRY = carrier.modules\n",
    ),
)
def test_loop_and_match_bindings_preserve_sys_authority(tmp_path: Path, source: str) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_async_for_unknown_target_rejects_sensitive_access(tmp_path: Path) -> None:
    source = _compiled_source(
        "async def inspect(source: object) -> None:\n"
        "    async for carrier in source:\n"
        "        REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "runtime_assertion"),
    (
        (
            "SAFE = lambda _=(eval := 0): eval\n",
            lambda namespace: namespace["SAFE"]() == 0,
        ),
        (
            "import sys as carrier\n"
            "SAFE = ((False and object()) or (carrier := carrier.stdout))\n"
            "WRITE = getattr(carrier, 'write')\n",
            lambda namespace: namespace["SAFE"] is sys.stdout
            and callable(namespace["WRITE"]),
        ),
    ),
)
def test_ordered_expression_effects_keep_safe_sources_allowed(
    tmp_path: Path,
    source: str,
    runtime_assertion: object,
) -> None:
    source = _compiled_source(source)
    namespace: dict[str, object] = {}
    exec(source, namespace)
    assert callable(runtime_assertion)
    assert runtime_assertion(namespace)

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)
    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("control_id", "source"),
    (
        (
            "direct-sys-stdout",
            "import sys\nSAFE = sys.stdout\n",
        ),
        (
            "from-sys-stdout",
            "from sys import stdout\nSAFE = stdout\n",
        ),
        (
            "wrappers-and-comprehension-target",
            "import sys\n"
            "SAFE_LAMBDA = lambda value=sys.stdout: value\n"
            "SAFE_LIST = [sys.stdout]\n"
            "SAFE_SET = {sys.stdout}\n"
            "SAFE_DICT = {'output': sys.stdout}\n"
            "SAFE_GEN = (value for value in (sys.stdout,))\n"
            "SAFE_COMP = [value for value in (sys.stdout,)]\n",
        ),
        (
            "executed-walrus",
            "import sys as carrier\n"
            "SAFE = (carrier := carrier.stdout)\n"
            "WRITE = getattr(carrier, 'write')\n",
        ),
        (
            "literal-getattr-hasattr",
            "import sys\n"
            "WRITE = getattr(sys.stdout, 'write')\n"
            "HAS_WRITE = hasattr(sys.stdout, 'write')\n",
        ),
        (
            "regex-sensitive-strings",
            "import re\n"
            "PATTERN = re.compile('import_module|__import__|sys[.]modules')\n"
            "WORDS = ('exec', 'eval', 'compile', 'globals')\n",
        ),
    ),
)
def test_mandatory_safe_source_controls_remain_allowed(
    tmp_path: Path,
    control_id: str,
    source: str,
) -> None:
    del control_id
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    scan_study_dependencies(protocol, repo_root=repo_root)


def _nested_expression(family: str, depth: int) -> str:
    expression = "object()"
    for index in range(depth):
        if family == "dunder-call":
            expression = f"({expression}).__getattribute__('x')"
        elif family == "alternating-boolop":
            expression = (
                f"({expression} and True)"
                if index % 2
                else f"(False or {expression})"
            )
        elif family == "ifexp":
            expression = f"({expression} if True else object())"
        elif family == "lambda-default-body":
            expression = (
                f"(lambda value={expression}: "
                "(value if True else object()))"
            )
        elif family == "list-comprehension":
            expression = f"[item for item in ({expression},)]"
        elif family == "set-comprehension":
            expression = f"{{item for item in ({expression},)}}"
        elif family == "dict-comprehension":
            expression = f"{{item: item for item in ({expression},)}}"
        elif family == "false-filter":
            expression = f"[item for item in ({expression},) if False]"
        elif family == "later-nested-generators":
            expression = (
                f"[later for item in ({expression},) "
                "for later in (item,)]"
            )
        elif family == "genexpr":
            expression = f"(value for value in ({expression},))"
        elif family == "wrapper-container":
            expression = (
                f"[{expression}]",
                f"({expression},)",
                f"{{{expression}}}",
                f"{{'value': {expression}}}",
            )[index % 4]
        elif family == "match-guard":
            expression = (
                f"({expression} and True)"
                if index % 2
                else f"(False or {expression})"
            )
        else:
            raise AssertionError(f"unknown fixture family: {family}")
    if family == "match-guard":
        return (
            "VALUE = None\n"
            "match object():\n"
            f"    case captured if {expression}:\n"
            "        VALUE = captured\n"
        )
    return f"VALUE = {expression}\n"


def _statement_complexity_source(family: str, depth: int) -> str:
    if family == "try-except-finally":
        unit = (
            "try:\n"
            "    VALUE = object()\n"
            "except Exception:\n"
            "    VALUE = object()\n"
            "finally:\n"
            "    VALUE = object()\n"
        )
        return "VALUE = None\n" + unit * depth
    if family == "except-star":
        unit = (
            "try:\n"
            "    raise ExceptionGroup('group', [ValueError()])\n"
            "except* ValueError:\n"
            "    VALUE = object()\n"
        )
        return "VALUE = None\n" + unit * depth
    if family == "for":
        unit = "for item in (0,):\n    VALUE = object()\n"
        return "VALUE = None\n" + unit * depth
    if family == "async-for":
        body = "".join(
            "    async for item in source:\n"
            "        VALUE = object()\n"
            for _ in range(depth)
        )
        return "async def probe(source: object) -> None:\n" + body
    if family == "diamond-joins":
        diamonds = "".join(
            "if object():\n"
            "    alias = str\n"
            "else:\n"
            "    alias = bytes\n"
            for _ in range(depth)
        )
        return (
            "alias = len\n"
            + diamonds
            + "def deferred() -> object:\n"
            "    return alias\n"
            "alias = tuple\n"
        )
    raise AssertionError(f"unknown fixture family: {family}")


def _assert_canonical_complexity_bounds(
    tree: ast.Module,
    stats: retention_module._AnalysisStats,
    *,
    maximum_bindings: int,
    maximum_frames: int,
    straight_line: bool,
) -> None:
    height = max(1, 1 + 67 * maximum_bindings + maximum_frames)

    assert stats.computed_height_bound == height
    assert stats.max_updates_per_program_point <= height
    assert stats.worklist_pops <= stats.program_points * (height + 1)
    assert stats.transfer_steps <= stats.program_points * (height + 1)
    if straight_line:
        syntax_nodes = len(tuple(ast.walk(tree)))
        assert stats.expression_transfers <= 2 * syntax_nodes
        assert stats.transfer_steps <= 2 * syntax_nodes


@pytest.mark.parametrize("depth", (1, 2, 4, 8, 16, 32, 64))
@pytest.mark.parametrize(
    ("family", "maximum_bindings", "maximum_frames"),
    (
        ("dunder-call", 1, 1),
        ("alternating-boolop", 1, 1),
        ("ifexp", 1, 1),
        ("lambda-default-body", 2, 2),
        ("list-comprehension", 2, 2),
        ("set-comprehension", 2, 2),
        ("dict-comprehension", 2, 2),
        ("false-filter", 2, 2),
        ("later-nested-generators", 3, 2),
        ("genexpr", 2, 2),
        ("wrapper-container", 1, 1),
        ("match-guard", 2, 1),
    ),
)
def test_structural_expression_families_obey_the_canonical_complexity_bound(
    family: str,
    maximum_bindings: int,
    maximum_frames: int,
    depth: int,
) -> None:
    tree, result = _analyze_source(_nested_expression(family, depth))
    stats = result.stats

    assert isinstance(stats, retention_module._AnalysisStats)
    _assert_canonical_complexity_bounds(
        tree,
        stats,
        maximum_bindings=maximum_bindings,
        maximum_frames=maximum_frames,
        straight_line=True,
    )
    if family == "match-guard":
        assert stats.pattern_transfers > 0


@pytest.mark.parametrize("depth", (1, 2, 4, 8, 16, 32, 64))
@pytest.mark.parametrize(
    ("family", "maximum_bindings", "maximum_frames"),
    (
        ("try-except-finally", 1, 1),
        ("except-star", 1, 1),
        ("for", 2, 1),
        ("async-for", 4, 2),
        ("diamond-joins", 2, 2),
    ),
)
def test_statement_and_join_families_obey_the_canonical_complexity_bound(
    family: str,
    maximum_bindings: int,
    maximum_frames: int,
    depth: int,
) -> None:
    tree, result = _analyze_source(_statement_complexity_source(family, depth))
    stats = result.stats

    assert isinstance(stats, retention_module._AnalysisStats)
    _assert_canonical_complexity_bounds(
        tree,
        stats,
        maximum_bindings=maximum_bindings,
        maximum_frames=maximum_frames,
        straight_line=False,
    )
    assert stats.statement_transfers > 0
    if family in {"for", "async-for", "diamond-joins"}:
        assert stats.worklist_pops > 0


@pytest.mark.parametrize(
    ("relative", "position"),
    (
        (Path("src/manufacturing_vision_studio/__init__.py"), "early"),
        (Path("src/manufacturing_vision_studio/__init__.py"), "late"),
        (Path("src/manufacturing_vision_studio/e1/__init__.py"), "early"),
        (Path("src/manufacturing_vision_studio/e1/__init__.py"), "late"),
    ),
)
def test_exact_initializer_rejects_import_module_rebinding(
    tmp_path: Path,
    relative: Path,
    position: str,
) -> None:
    rebind = "class Fake:\n    Thing = 7\n\n\nimport_module = lambda module_name: Fake\n"
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    path = repo_root / relative
    source = path.read_text()
    if position == "early":
        import_boundary = "from typing import TYPE_CHECKING, Any\n"
        source = source.replace(import_boundary, import_boundary + "\n" + rebind, 1)
    else:
        source += "\n" + rebind
    path.write_text(_compiled_source(source))

    with pytest.raises(StudyRetentionError, match="initializer capability structure"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    ("getattr = lambda value, name: 'spoofed'\n", "_json_value = lambda value: 'spoofed'\n"),
)
def test_real_cli_namespace_reflection_bindings_are_rejected(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol, preserve_real_cli=True)
    _append(repo_root, CLI_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: namespace-reflection",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "name",
    ("fields", "is_dataclass", "getattr", "isinstance", "type", "_json_value"),
)
def test_cli_dataclass_exception_rejects_local_shadow_at_protected_call(
    tmp_path: Path,
    name: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol, preserve_real_cli=True)
    path = repo_root / CLI_PATH
    source = path.read_text()
    original = "if value is None or isinstance(value, (bool, int, float, str)):"
    replacement = (
        f"if ({name} := len) and "
        "(value is None or isinstance(value, (bool, int, float, str))):"
    )
    changed = source.replace(original, replacement, 1)
    assert changed != source
    path.write_text(_compiled_source(changed))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: namespace-reflection",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


_COMPLETED_MODULE_REBIND_KINDS = (
    "assignment",
    "annotated-assignment",
    "augmented-assignment",
    "deletion",
    "import-alias",
    "star-import",
    "conditional",
    "loop-target",
    "match-target",
    "with-target",
    "exception-target",
    "function-definition",
    "class-definition",
    "decorated-definition",
    "second-function-definition",
    "deferred-outer-write",
)


def _completed_module_rebind_source(name: str, kind: str) -> str:
    safe_name = name.strip("_") or "binding"
    if kind == "assignment":
        return f"{name} = object()\n"
    if kind == "annotated-assignment":
        return f"{name}: object = object()\n"
    if kind == "augmented-assignment":
        return f"{name} += ()\n"
    if kind == "deletion":
        return f"del {name}\n"
    if kind == "import-alias":
        return f"from types import SimpleNamespace as {name}\n"
    if kind == "star-import":
        return "from math import *\n"
    if kind == "conditional":
        return f"if object():\n    {name} = object()\n"
    if kind == "loop-target":
        return f"for {name} in (object(),):\n    pass\n"
    if kind == "match-target":
        return f"match object():\n    case {name}:\n        pass\n"
    if kind == "with-target":
        return (
            "from contextlib import nullcontext\n"
            f"with nullcontext() as {name}:\n"
            "    pass\n"
        )
    if kind == "exception-target":
        return (
            "try:\n"
            "    raise Exception\n"
            f"except Exception as {name}:\n"
            "    pass\n"
        )
    if kind == "function-definition":
        return f"def {name}(*args: object) -> object:\n    return args\n"
    if kind == "class-definition":
        return f"class {name}:\n    pass\n"
    if kind == "decorated-definition":
        return (
            f"def _decorate_{safe_name}(value: object) -> object:\n"
            "    return value\n"
            f"@_decorate_{safe_name}\n"
            f"def {name}(*args: object) -> object:\n"
            "    return args\n"
        )
    if kind == "second-function-definition":
        return (
            f"def {name}(*args: object) -> object:\n"
            "    return args\n"
            f"def {name}(*args: object) -> object:\n"
            "    return args\n"
        )
    if kind == "deferred-outer-write":
        return (
            f"def _write_{safe_name}() -> None:\n"
            f"    global {name}\n"
            f"    {name} = object()\n"
        )
    raise AssertionError(f"unknown completed-module mutation: {kind}")


@pytest.mark.parametrize(
    "name",
    (
        "import_module",
        "getattr",
        "globals",
        "KeyError",
        "AttributeError",
        "sorted",
        "set",
        "_LAZY_EXPORTS",
        "__all__",
        "__getattr__",
        "__dir__",
    ),
)
@pytest.mark.parametrize(
    "relative",
    (
        Path("src/manufacturing_vision_studio/__init__.py"),
        Path("src/manufacturing_vision_studio/e1/__init__.py"),
    ),
    ids=("root", "e1"),
)
@pytest.mark.parametrize("kind", _COMPLETED_MODULE_REBIND_KINDS)
def test_pep562_exception_rejects_completed_module_binding_mutations(
    tmp_path: Path,
    name: str,
    relative: Path,
    kind: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    source = _compiled_source(_completed_module_rebind_source(name, kind))
    _append(
        repo_root,
        relative,
        "\n" + source,
    )

    with pytest.raises(StudyRetentionError, match="initializer capability structure"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "name",
    ("fields", "is_dataclass", "getattr", "isinstance", "type", "_json_value"),
)
@pytest.mark.parametrize("kind", _COMPLETED_MODULE_REBIND_KINDS)
def test_cli_dataclass_exception_rejects_completed_module_binding_mutations(
    tmp_path: Path,
    name: str,
    kind: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol, preserve_real_cli=True)
    source = _compiled_source(_completed_module_rebind_source(name, kind))
    _append(repo_root, CLI_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: namespace-reflection",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("relative", "preserve_real_cli", "name"),
    (
        *(
            (
                Path("src/manufacturing_vision_studio/__init__.py"),
                False,
                name,
            )
            for name in (
                "import_module",
                "getattr",
                "globals",
                "KeyError",
                "AttributeError",
                "sorted",
                "set",
                "_LAZY_EXPORTS",
                "__all__",
                "__getattr__",
                "__dir__",
            )
        ),
        *(
            (CLI_PATH, True, name)
            for name in (
                "fields",
                "is_dataclass",
                "getattr",
                "isinstance",
                "type",
                "_json_value",
            )
        ),
    ),
)
def test_unrelated_nested_local_shadow_preserves_exact_module_identity(
    tmp_path: Path,
    relative: Path,
    preserve_real_cli: bool,
    name: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(
        tmp_path,
        protocol,
        preserve_real_cli=preserve_real_cli,
    )
    source = _compiled_source(
        "def unrelated_local_shadow() -> None:\n"
        f"    {name} = object()\n"
    )
    _append(repo_root, relative, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_assignment_target_expressions_are_transferred(tmp_path: Path) -> None:
    source = (
        "sink = {}\n"
        "sink[__import__('manufacturing_vision_studio.e1.policy_v2')] = 1\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match="source capability rejected: dynamic-import"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_scope_declarations_apply_to_the_complete_function_body(
    tmp_path: Path,
) -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "def deferred(flag: bool) -> None:\n"
        "    if flag:\n"
        "        global TYPE_CHECKING\n"
        "    TYPE_CHECKING = False\n"
        "    if TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match="source capability rejected: deferred-effect"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_loop_else_receives_normal_exhaustion_state(tmp_path: Path) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "for marker in ('iteration',):\n"
            "    trace.append(marker)\n"
            "else:\n"
            "    trace.append(f'else:{marker}')\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == ["iteration", "else:iteration"]

    source = _compiled_source(
        "import sys\n"
        "carrier = sys.stdout\n"
        "for carrier in (sys,):\n"
        "    pass\n"
        "else:\n"
        "    REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_failed_match_guard_effect_reaches_later_cases(tmp_path: Path) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "carrier = 'before'\n"
            "match 1:\n"
            "    case 1 if (trace.append('guard') or (carrier := 'guard')) == 'no':\n"
            "        trace.append('first')\n"
            "    case _:\n"
            "        trace.append(f'second:{carrier}')\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == ["guard", "second:guard"]

    source = _compiled_source(
        "import sys\n"
        "carrier = sys.stdout\n"
        "match 1:\n"
        "    case 1 if ((carrier := sys) and False):\n"
        "        pass\n"
        "    case _:\n"
        "        REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_except_star_handlers_preserve_prior_handler_effects(tmp_path: Path) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "carrier = 'before'\n"
            "try:\n"
            "    raise ExceptionGroup('group', [ValueError(), TypeError()])\n"
            "except* ValueError:\n"
            "    trace.append('value')\n"
            "    carrier = 'value-handler'\n"
            "except* TypeError:\n"
            "    trace.append(f'type:{carrier}')\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == ["value", "type:value-handler"]

    source = _compiled_source(
        "import sys\n"
        "carrier = sys.stdout\n"
        "try:\n"
        "    raise ExceptionGroup('group', [ValueError(), TypeError()])\n"
        "except* ValueError:\n"
        "    carrier = sys\n"
        "except* TypeError:\n"
        "    REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_exception_target_is_unbound_after_handler(tmp_path: Path) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "problem = 'outer'\n"
            "try:\n"
            "    raise RuntimeError('handled')\n"
            "except RuntimeError as problem:\n"
            "    trace.append(type(problem).__name__)\n"
            "try:\n"
            "    problem\n"
            "except NameError:\n"
            "    trace.append('unbound')\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == ["RuntimeError", "unbound"]

    binding_source = _compiled_source(
        "from typing import TYPE_CHECKING\n"
        "try:\n"
        "    raise RuntimeError('handled')\n"
        "except RuntimeError as TYPE_CHECKING:\n"
        "    if TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    cleanup_source = _compiled_source(
        "from typing import TYPE_CHECKING\n"
        "try:\n"
        "    raise RuntimeError('handled')\n"
        "except RuntimeError as TYPE_CHECKING:\n"
        "    pass\n"
        "if TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    binding_fixture = tmp_path / "handler-binding"
    binding_fixture.mkdir()
    binding_repo = _complete_repo(binding_fixture, protocol)
    _append(binding_repo, RUNNER_PATH, "\n" + binding_source)

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=binding_repo)

    cleanup_fixture = tmp_path / "handler-cleanup"
    cleanup_fixture.mkdir()
    cleanup_repo = _complete_repo(cleanup_fixture, protocol)
    _append(cleanup_repo, RUNNER_PATH, "\n" + cleanup_source)

    scan_study_dependencies(protocol, repo_root=cleanup_repo)


def test_with_target_preserves_context_capability_provenance(tmp_path: Path) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "class Context:\n"
            "    def __enter__(self):\n"
            "        trace.append('enter')\n"
            "        return 'entered-value'\n"
            "    def __exit__(self, *_args):\n"
            "        trace.append('exit')\n"
            "with Context() as carrier:\n"
            "    trace.append(carrier)\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == ["enter", "entered-value", "exit"]

    retained_source = _compiled_source(
        "import sys\n"
        "with sys as carrier:\n"
        "    derived = carrier.stdout\n"
        "    SAFE = derived.modules\n"
    )
    incomplete_source = _compiled_source(
        "def inspect_context(context: object) -> None:\n"
        "    with context as carrier:\n"
        "        derived = carrier.stdout\n"
        "        REGISTRY = derived.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + retained_source)

    scan_study_dependencies(protocol, repo_root=repo_root)

    _append(repo_root, RUNNER_PATH, "\n" + incomplete_source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_future_annotations_do_not_commit_runtime_named_expression_effects(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "from __future__ import annotations\n"
        "import sys as carrier\n"
        "def observed(value: [(carrier := carrier.stdout) for _ in (0,)]) -> None:\n"
        "    pass\n"
        "REGISTRY = carrier.modules\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["carrier"] is sys

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    runner = repo_root / RUNNER_PATH
    runner.write_text(source + "\n" + runner.read_text())

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_nonfuture_annotations_follow_python_312_definition_order(
    tmp_path: Path,
) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "def mark(label):\n"
            "    trace.append(label)\n"
            "    return object()\n"
            "def decorate(label):\n"
            "    trace.append(f'eval:{label}')\n"
            "    def apply(function):\n"
            "        trace.append(f'apply:{label}')\n"
            "        return function\n"
            "    return apply\n"
            "@decorate('outer')\n"
            "@decorate('inner')\n"
            "def observed(\n"
            "    positional: mark('annotation:positional') = mark('default:positional'),\n"
            "    *,\n"
            "    keyword: mark('annotation:keyword') = mark('default:keyword'),\n"
            ") -> mark('annotation:return'):\n"
            "    pass\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == [
        "eval:outer",
        "eval:inner",
        "default:positional",
        "default:keyword",
        "annotation:positional",
        "annotation:keyword",
        "annotation:return",
        "apply:inner",
        "apply:outer",
    ]

    runtime_state_source = _compiled_source(
        "import sys\n"
        "carrier = sys\n"
        "def observed(value: (carrier := carrier.stdout) = (carrier := sys)) -> None:\n"
        "    pass\n"
    )
    namespace = {}
    _execute_source(runtime_state_source, namespace)
    assert namespace["carrier"] is sys.stdout

    source = _compiled_source(runtime_state_source + "REGISTRY = carrier.modules\n")

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_python312_type_parameter_bounds_are_lazy_but_policy_inspected(
    tmp_path: Path,
) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "def bound():\n"
            "    trace.append('bound')\n"
            "    return object\n"
            "def generic[T: bound()]() -> None:\n"
            "    pass\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == []

    source = _compiled_source(
        "def generic[\n"
        "    T: __import__('manufacturing_vision_studio.e1.policy_v2').E1V2Policy,\n"
        "]() -> None:\n"
        "    pass\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: dynamic-import"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_class_body_global_write_is_eager(tmp_path: Path) -> None:
    runtime_state_source = _compiled_source(
        "import sys as carrier\n"
        "class Scope:\n"
        "    global carrier\n"
        "    carrier = carrier.stdout\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(runtime_state_source, namespace)
    assert namespace["carrier"] is sys.stdout

    source = _compiled_source(runtime_state_source + "REGISTRY = carrier.modules\n")

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_class_local_write_does_not_escape(tmp_path: Path) -> None:
    source = _compiled_source(
        "import sys as carrier\n"
        "class Scope:\n"
        "    carrier = carrier.stdout\n"
        "REGISTRY = carrier.modules\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["carrier"] is sys
    assert namespace["Scope"].carrier is sys.stdout

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("completion", "source"),
    (
        (
            "break",
            "import sys as carrier\n"
            "for _ in (0,):\n"
            "    break\n"
            "    carrier = carrier.stdout\n"
            "REGISTRY = carrier.modules\n",
        ),
        (
            "continue",
            "import sys as carrier\n"
            "for _ in (0,):\n"
            "    continue\n"
            "    carrier = carrier.stdout\n"
            "REGISTRY = carrier.modules\n",
        ),
        (
            "return",
            "def deferred() -> None:\n"
            "    import sys as carrier\n"
            "    try:\n"
            "        return\n"
            "        carrier = carrier.stdout\n"
            "    finally:\n"
            "        REGISTRY = carrier.modules\n",
        ),
        (
            "raise",
            "def deferred() -> None:\n"
            "    import sys as carrier\n"
            "    try:\n"
            "        raise RuntimeError('expected')\n"
            "        carrier = carrier.stdout\n"
            "    except RuntimeError:\n"
            "        REGISTRY = carrier.modules\n",
        ),
    ),
)
def test_abrupt_exit_channels_do_not_feed_following_statements(
    tmp_path: Path,
    completion: str,
    source: str,
) -> None:
    trace_source = {
        "break": (
            "trace = []\n"
            "for _ in (0,):\n"
            "    break\n"
            "    trace.append('unreachable')\n"
            "trace.append('after')\n"
        ),
        "continue": (
            "trace = []\n"
            "for _ in (0,):\n"
            "    continue\n"
            "    trace.append('unreachable')\n"
            "trace.append('after')\n"
        ),
        "return": (
            "trace = []\n"
            "def observed():\n"
            "    trace.append('before')\n"
            "    return\n"
            "    trace.append('unreachable')\n"
            "observed()\n"
            "trace.append('after')\n"
        ),
        "raise": (
            "trace = []\n"
            "try:\n"
            "    trace.append('before')\n"
            "    raise RuntimeError('expected')\n"
            "    trace.append('unreachable')\n"
            "except RuntimeError:\n"
            "    trace.append('after')\n"
        ),
    }[completion]
    trace_namespace: dict[str, object] = {}
    _execute_source(_compiled_source(trace_source), trace_namespace)
    expected_trace = ["after"] if completion in {"break", "continue"} else ["before", "after"]
    assert trace_namespace["trace"] == expected_trace

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "incoming",
    (
        pytest.param("pass", id="normal"),
        "break",
        "continue",
        "return",
        "raise",
    ),
)
def test_finally_completion_replaces_each_incoming_exit(
    tmp_path: Path,
    incoming: str,
) -> None:
    incoming_statement = {
        "pass": "pass",
        "break": "break",
        "continue": "continue",
        "return": "return",
        "raise": "raise RuntimeError",
    }[incoming]
    trace_source = _compiled_source(
        "trace = []\n"
        "def observed():\n"
        "    try:\n"
        "        for _ in (0,):\n"
        "            try:\n"
        f"                {incoming_statement}\n"
        "            finally:\n"
        "                trace.append('finally')\n"
        "                raise LookupError('replacement')\n"
        "    except LookupError:\n"
        "        trace.append('replacement-handler')\n"
        "    trace.append('after')\n"
        "observed()\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == ["finally", "replacement-handler", "after"]

    control_trace_source = _compiled_source(
        "trace = []\n"
        "def observed():\n"
        "    try:\n"
        "        for _ in (0,):\n"
        "            try:\n"
        f"                {incoming_statement}\n"
        "            finally:\n"
        "                trace.append('finally-normal')\n"
        "    except LookupError:\n"
        "        trace.append('replacement-handler')\n"
        "    trace.append('function-after')\n"
        "try:\n"
        "    observed()\n"
        "except RuntimeError:\n"
        "    trace.append('runtime-error')\n"
        "trace.append('caller-after')\n"
    )
    control_trace_namespace: dict[str, object] = {}
    _execute_source(control_trace_source, control_trace_namespace)
    expected_control_trace = {
        "pass": ["finally-normal", "function-after", "caller-after"],
        "break": ["finally-normal", "function-after", "caller-after"],
        "continue": ["finally-normal", "function-after", "caller-after"],
        "return": ["finally-normal", "caller-after"],
        "raise": ["finally-normal", "runtime-error", "caller-after"],
    }[incoming]
    assert control_trace_namespace["trace"] == expected_control_trace

    source_prefix = (
        "def deferred() -> None:\n"
        "    import sys\n"
        "    carrier = sys\n"
        "    try:\n"
        "        for _ in (0,):\n"
        "            try:\n"
        f"                {incoming_statement}\n"
        "            finally:\n"
    )
    source_suffix = (
        "    except LookupError:\n"
        "        carrier = carrier.stdout\n"
        "    REGISTRY = carrier.modules\n"
    )
    replacement_source = _compiled_source(
        source_prefix
        + "                raise LookupError('replacement')\n"
        + source_suffix
    )
    control_source = _compiled_source(source_prefix + "                pass\n" + source_suffix)

    protocol = load_study_protocol_v2()
    replacement_fixture = tmp_path / "replacement"
    replacement_fixture.mkdir()
    replacement_repo = _complete_repo(replacement_fixture, protocol)
    _append(replacement_repo, RUNNER_PATH, "\n" + replacement_source)

    scan_study_dependencies(protocol, repo_root=replacement_repo)

    control_fixture = tmp_path / "control"
    control_fixture.mkdir()
    control_repo = _complete_repo(control_fixture, protocol)
    _append(control_repo, RUNNER_PATH, "\n" + control_source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=control_repo)


def test_deferred_free_reads_use_the_call_time_suffix_envelope(tmp_path: Path) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "carrier = 'definition-time'\n"
            "def deferred():\n"
            "    trace.append(carrier)\n"
            "carrier = 'call-time'\n"
            "deferred()\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == ["call-time"]

    source = _compiled_source(
        "import sys\n"
        "carrier = sys.stdout\n"
        "def deferred() -> object:\n"
        "    return carrier.modules\n"
        "carrier = sys\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match="source capability rejected: import-registry"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("case_id", "source"),
    (
        (
            "function-global-assignment",
            "marker = 0\n"
            "def deferred() -> None:\n"
            "    global marker\n"
            "    marker = 1\n",
        ),
        (
            "async-function-global-assignment",
            "marker = 0\n"
            "async def deferred() -> None:\n"
            "    global marker\n"
            "    marker = 1\n",
        ),
        (
            "function-nonlocal-assignment",
            "def outer() -> None:\n"
            "    marker = 0\n"
            "    def deferred() -> None:\n"
            "        nonlocal marker\n"
            "        marker = 1\n",
        ),
        (
            "async-function-nonlocal-assignment",
            "def outer() -> None:\n"
            "    marker = 0\n"
            "    async def deferred() -> None:\n"
            "        nonlocal marker\n"
            "        marker = 1\n",
        ),
        (
            "global-delete",
            "marker = 0\n"
            "def deferred() -> None:\n"
            "    global marker\n"
            "    del marker\n",
        ),
        (
            "nonlocal-delete",
            "def outer() -> None:\n"
            "    marker = 0\n"
            "    def deferred() -> None:\n"
            "        nonlocal marker\n"
            "        del marker\n",
        ),
        (
            "global-augmented-assignment",
            "marker = 0\n"
            "def deferred() -> None:\n"
            "    global marker\n"
            "    marker += 1\n",
        ),
        (
            "nonlocal-augmented-assignment",
            "def outer() -> None:\n"
            "    marker = 0\n"
            "    def deferred() -> None:\n"
            "        nonlocal marker\n"
            "        marker += 1\n",
        ),
        (
            "global-import-alias-binding",
            "marker = None\n"
            "def deferred() -> None:\n"
            "    global marker\n"
            "    import sys as marker\n",
        ),
        (
            "nonlocal-import-alias-binding",
            "def outer() -> None:\n"
            "    marker = None\n"
            "    def deferred() -> None:\n"
            "        nonlocal marker\n"
            "        import sys as marker\n",
        ),
        (
            "generator-walrus-function-frame",
            "def deferred() -> None:\n"
            "    marker = 0\n"
            "    pending = ((marker := item) for item in (1,))\n",
        ),
        (
            "generator-walrus-lambda-frame",
            "deferred = lambda: ((marker := item) for item in (1,))\n",
        ),
    ),
)
def test_deferred_outer_writes_fail_closed(
    tmp_path: Path,
    case_id: str,
    source: str,
) -> None:
    del case_id
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match="source capability rejected: deferred-effect"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "is_runtime_reachable"),
    (
        (
            "if [item for item in ()]:\n"
            "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
            False,
        ),
        (
            "if [item for item in (0,)]:\n"
            "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
            True,
        ),
        (
            "if [item for item in (0,) if False]:\n"
            "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
            False,
        ),
    ),
)
def test_comprehension_truth_controls_runtime_dependency_edges(
    tmp_path: Path,
    source: str,
    *,
    is_runtime_reachable: bool,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    if is_runtime_reachable:
        with pytest.raises(
            StudyRetentionError,
            match=r"forbidden direct import.*policy_v2",
        ):
            scan_study_dependencies(protocol, repo_root=repo_root)
    else:
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_noniterable_comprehension_reaches_type_error_handler(tmp_path: Path) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "try:\n"
        "    result = [item for item in 0]\n"
        "except TypeError:\n"
        "    trace.append('handled')\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == ["handled"]

    source = _compiled_source(
        "try:\n"
        "    result = [item for item in 0]\n"
        "except TypeError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_noniterable_for_reaches_type_error_handler(tmp_path: Path) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "try:\n"
        "    for item in 0:\n"
        "        trace.append(item)\n"
        "except TypeError:\n"
        "    trace.append('handled')\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == ["handled"]

    source = _compiled_source(
        "try:\n"
        "    for item in 0:\n"
        "        pass\n"
        "except TypeError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_generator_iteration_exception_reaches_surrounding_handler(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "loader = (item for _ in (0,) for item in 0)\n"
        "try:\n"
        "    for _ in loader:\n"
        "        pass\n"
        "except TypeError:\n"
        "    trace.append('handled')\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == ["handled"]

    source = _compiled_source(
        "loader = (item for _ in (0,) for item in 0)\n"
        "try:\n"
        "    for _ in loader:\n"
        "        pass\n"
        "except TypeError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("iterable", "has_runtime_body_edge"),
    (("1", False), ("()", False), ("(0,)", True)),
)
def test_comprehension_condition_distinguishes_noniterable_and_cardinality(
    tmp_path: Path,
    iterable: str,
    *,
    has_runtime_body_edge: bool,
) -> None:
    source = _compiled_source(
        f"if [item for item in {iterable}]:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    if has_runtime_body_edge:
        with pytest.raises(
            StudyRetentionError,
            match=r"forbidden direct import.*policy_v2",
        ):
            scan_study_dependencies(protocol, repo_root=repo_root)
    else:
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("operand", "is_truthy"),
    (("0", True), ("1", False)),
)
def test_bound_truth_is_independent_of_iteration_cardinality(
    tmp_path: Path,
    operand: str,
    *,
    is_truthy: bool,
) -> None:
    trace_source = _compiled_source(f"flag = not {operand}\n")
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["flag"] is is_truthy

    source = _compiled_source(
        f"flag = not {operand}\n"
        "if flag:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    if is_truthy:
        with pytest.raises(
            StudyRetentionError,
            match=r"forbidden direct import.*policy_v2",
        ):
            scan_study_dependencies(protocol, repo_root=repo_root)
    else:
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import sys\n"
        "match (sys,):\n"
        "    case [carrier, missing]:\n"
        "        pass\n"
        "    case _ if carrier.modules:\n"
        "        pass\n",
        "import sys\n"
        "match {'carrier': sys}:\n"
        "    case {'carrier': carrier, 'missing': missing}:\n"
        "        pass\n"
        "    case _ if carrier.modules:\n"
        "        pass\n",
        "import sys\n"
        "match (sys,):\n"
        "    case tuple(carrier, missing):\n"
        "        pass\n"
        "    case _ if carrier.modules:\n"
        "        pass\n",
        "import sys\n"
        "match (sys,):\n"
        "    case [carrier, missing] | [carrier, missing, _]:\n"
        "        pass\n"
        "    case _ if carrier.modules:\n"
        "        pass\n",
        "import sys\n"
        "match (sys,):\n"
        "    case [carrier, missing] as whole:\n"
        "        pass\n"
        "    case _ if carrier.modules:\n"
        "        pass\n",
    ),
)
def test_failed_decomposition_pattern_carries_partial_capture_provenance(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("early_operation", "has_earlier_possible_raise"),
    (("", False), ("object()", True), ("1 / 0", True)),
)
def test_try_handlers_receive_only_actual_may_raise_prefix_states(
    tmp_path: Path,
    early_operation: str,
    *,
    has_earlier_possible_raise: bool,
) -> None:
    early_statement = "" if not early_operation else f"    {early_operation}\n"
    source = _compiled_source(
        "from typing import TYPE_CHECKING\n"
        "guard = TYPE_CHECKING\n"
        "try:\n"
        f"{early_statement}"
        "    guard = False\n"
        "    raise RuntimeError\n"
        "except RuntimeError:\n"
        "    if guard:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    if has_earlier_possible_raise:
        with pytest.raises(
            StudyRetentionError,
            match=r"forbidden direct import.*policy_v2",
        ):
            scan_study_dependencies(protocol, repo_root=repo_root)
    else:
        trace_namespace: dict[str, object] = {}
        _execute_source(source, trace_namespace)
        assert trace_namespace["guard"] is False
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_implicit_exception_keeps_matching_handler_reachable(tmp_path: Path) -> None:
    trace_namespace: dict[str, object] = {}
    _execute_source(
        _compiled_source(
            "trace = []\n"
            "try:\n"
            "    1 / 0\n"
            "except ZeroDivisionError:\n"
            "    trace.append('handled')\n"
        ),
        trace_namespace,
    )
    assert trace_namespace["trace"] == ["handled"]

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + _compiled_source(
            "try:\n"
            "    1 / 0\n"
            "except ZeroDivisionError:\n"
            "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
        ),
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_exact_explicit_raise_keeps_disjoint_handler_policy_only(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + _compiled_source(
            "try:\n"
            "    raise ValueError\n"
            "except TypeError:\n"
            "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
        ),
    )

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_exception_constructor_call_keeps_disjoint_handler_conservatively_reachable(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "try:\n"
        "    try:\n"
        "        raise RuntimeError('constructed')\n"
        "    except LookupError:\n"
        "        trace.append('lookup')\n"
        "except RuntimeError:\n"
        "    trace.append('runtime')\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(trace_source, namespace)
    assert namespace["trace"] == ["runtime"]

    source = _compiled_source(
        "try:\n"
        "    raise RuntimeError('constructed')\n"
        "except LookupError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match=r"forbidden direct import.*policy_v2",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_explicit_raise_reaches_superclass_handler(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + _compiled_source(
            "try:\n"
            "    raise ValueError\n"
            "except Exception:\n"
            "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
        ),
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_except_star_later_handler_receives_prior_raised_handler_state(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "import sys\n"
        "carrier = sys.stdout\n"
        "try:\n"
        "    raise ExceptionGroup('group', [ValueError(), TypeError()])\n"
        "except* ValueError:\n"
        "    carrier = sys\n"
        "    raise LookupError\n"
        "except* TypeError:\n"
        "    REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_ordinary_handlers_do_not_receive_prior_handler_effects(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "import sys\n"
        "carrier = sys.stdout\n"
        "try:\n"
        "    raise ValueError\n"
        "except ValueError:\n"
        "    carrier = sys\n"
        "except TypeError:\n"
        "    REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "try:\n"
        "    raise ValueError\n"
        "except ValueError:\n"
        "    pass\n"
        "except ValueError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "try:\n"
        "    if False:\n"
        "        raise ValueError\n"
        "    raise TypeError\n"
        "except Exception:\n"
        "    pass\n"
        "except (ValueError, TypeError):\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    ),
    ids=("duplicate", "superclass"),
)
def test_ordinary_first_matching_handler_consumes_exact_builtin_exceptions(
    tmp_path: Path,
    source: str,
) -> None:
    trace_source = _compiled_source(
        source.replace(
            "from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy",
            "raise AssertionError('later handler must be dead')",
        )
    )
    _execute_source(trace_source, {})

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_ordinary_handler_partition_preserves_unmatched_exact_exception(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "trace = []\n"
        "try:\n"
        "    if False:\n"
        "        raise ValueError\n"
        "    raise TypeError\n"
        "except ValueError:\n"
        "    trace.append('value')\n"
        "except TypeError:\n"
        "    trace.append('type')\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["trace"] == ["type"]

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + source.replace(
            "trace.append('type')",
            "from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy",
        ),
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_ordinary_handler_type_effect_reaches_later_handler(tmp_path: Path) -> None:
    source = _compiled_source(
        "trace = []\n"
        "guard = False\n"
        "try:\n"
        "    raise ValueError\n"
        "except (guard := KeyError):\n"
        "    trace.append('key')\n"
        "except ValueError:\n"
        "    trace.append(guard is KeyError)\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["trace"] == [True]

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n"
        + source.replace(
            "trace.append(guard is KeyError)",
            "if guard:\n"
            "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy",
        ),
    )

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_consumed_ordinary_exception_state_is_not_reintroduced_to_finally(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "from typing import TYPE_CHECKING\n"
        "guard = TYPE_CHECKING\n"
        "try:\n"
        "    guard = True\n"
        "    raise ValueError\n"
        "except ValueError:\n"
        "    guard = False\n"
        "finally:\n"
        "    if guard:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["guard"] is False

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_abrupt_exact_raise_does_not_revive_unreachable_exact_handler(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "try:\n"
        "    raise ValueError\n"
        "    raise TypeError\n"
        "except ValueError:\n"
        "    trace.append('value')\n"
        "except TypeError:\n"
        "    raise AssertionError('unreachable handler ran')\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(trace_source, namespace)
    assert namespace["trace"] == ["value"]

    source = _compiled_source(
        "try:\n"
        "    raise ValueError\n"
        "    raise TypeError\n"
        "except ValueError:\n"
        "    pass\n"
        "except TypeError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("caught_name", "value_carrier", "type_carrier"),
    (
        pytest.param("ValueError", "sys.stdout", "sys", id="value-handler"),
        pytest.param("TypeError", "sys", "sys.stdout", id="type-handler"),
    ),
)
def test_branch_correlated_exact_handlers_receive_only_their_route_state(
    tmp_path: Path,
    caught_name: str,
    value_carrier: str,
    type_carrier: str,
) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "def observed(flag):\n"
        "    carrier = 'initial'\n"
        "    try:\n"
        "        if flag:\n"
        "            carrier = 'value'\n"
        "            raise ValueError\n"
        "        carrier = 'type'\n"
        "        raise TypeError\n"
        "    except ValueError:\n"
        "        trace.append(('ValueError', carrier))\n"
        "    except TypeError:\n"
        "        trace.append(('TypeError', carrier))\n"
        "observed(True)\n"
        "observed(False)\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(trace_source, namespace)
    assert namespace["trace"] == [
        ("ValueError", "value"),
        ("TypeError", "type"),
    ]

    value_body = (
        "        REGISTRY = carrier.modules\n"
        if caught_name == "ValueError"
        else "        pass\n"
    )
    type_body = (
        "        REGISTRY = carrier.modules\n"
        if caught_name == "TypeError"
        else "        pass\n"
    )
    source = _compiled_source(
        "def deferred(flag):\n"
        "    import sys\n"
        "    carrier = sys.stdout\n"
        "    try:\n"
        "        if flag:\n"
        f"            carrier = {value_carrier}\n"
        "            raise ValueError\n"
        f"        carrier = {type_carrier}\n"
        "        raise TypeError\n"
        "    except ValueError:\n"
        f"{value_body}"
        "    except TypeError:\n"
        f"{type_body}"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_loop_correlated_exact_handler_receives_only_its_route_state(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "try:\n"
        "    for route in (True, False):\n"
        "        if route:\n"
        "            trace.append('value-state')\n"
        "            raise ValueError\n"
        "        trace.append('type-state')\n"
        "        raise TypeError\n"
        "except ValueError:\n"
        "    trace.append('value-handler')\n"
        "except TypeError:\n"
        "    trace.append('type-handler')\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(trace_source, namespace)
    assert namespace["trace"] == ["value-state", "value-handler"]

    source = _compiled_source(
        "def deferred():\n"
        "    import sys\n"
        "    carrier = sys.stdout\n"
        "    try:\n"
        "        for route in (True, False):\n"
        "            if route:\n"
        "                carrier = sys.stdout\n"
        "                raise ValueError\n"
        "            carrier = sys\n"
        "            raise TypeError\n"
        "    except ValueError:\n"
        "        REGISTRY = carrier.modules\n"
        "    except TypeError:\n"
        "        pass\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_consumed_exact_route_is_not_revived_by_unreachable_raise_in_finally(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "from typing import TYPE_CHECKING\n"
        "guard = TYPE_CHECKING\n"
        "try:\n"
        "    guard = True\n"
        "    raise ValueError\n"
        "    raise TypeError\n"
        "except ValueError:\n"
        "    guard = False\n"
        "finally:\n"
        "    if guard:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["guard"] is False

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "try:\n"
        "    raise\n"
        "except TypeError:\n"
        "    pass\n"
        "except BaseException:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "try:\n"
        "    1 / 0\n"
        "except TypeError:\n"
        "    pass\n"
        "except ZeroDivisionError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "class CustomError(Exception):\n"
        "    pass\n"
        "try:\n"
        "    raise CustomError\n"
        "except TypeError:\n"
        "    pass\n"
        "except CustomError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "class CustomError(Exception):\n"
        "    pass\n"
        "ValueError = CustomError\n"
        "try:\n"
        "    raise ValueError\n"
        "except TypeError:\n"
        "    pass\n"
        "except ValueError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "class Errors:\n"
        "    ValueError = ValueError\n"
        "try:\n"
        "    raise Errors.ValueError\n"
        "except TypeError:\n"
        "    pass\n"
        "except Errors.ValueError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "guard = False\n"
        "try:\n"
        "    raise ValueError\n"
        "except (guard := TypeError):\n"
        "    pass\n"
        "except ValueError:\n"
        "    if guard:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    ),
    ids=("bare", "implicit", "custom", "shadowed", "attributed", "effectful"),
)
def test_nonprovable_exception_routes_remain_conservative_controls(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("setup", "raise_statement", "later_handler"),
    (
        (
            "class CustomError(Exception):\n"
            "    pass\n",
            "raise CustomError\n",
            "CustomError",
        ),
        (
            "class CustomError(Exception):\n"
            "    pass\n"
            "ValueError = CustomError\n",
            "raise ValueError\n",
            "ValueError",
        ),
        (
            "class Errors:\n"
            "    ValueError = ValueError\n",
            "raise Errors.ValueError\n",
            "Errors.ValueError",
        ),
        ("", "1 / 0\n", "ZeroDivisionError"),
    ),
    ids=("custom", "shadowed", "attributed", "uncertain"),
)
def test_nonprovable_first_handler_preserves_later_handler_reachability(
    tmp_path: Path,
    setup: str,
    raise_statement: str,
    later_handler: str,
) -> None:
    source = _compiled_source(
        setup
        + "try:\n"
        + textwrap.indent(raise_statement, "    ")
        + "except TypeError:\n"
        "    pass\n"
        f"except {later_handler}:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize("late_loader", ("globals", "len"))
def test_generator_body_uses_iteration_time_suffix_bindings(
    tmp_path: Path,
    late_loader: str,
) -> None:
    call_arguments = "" if late_loader == "globals" else "()"
    source = _compiled_source(
        "loader = len\n"
        f"deferred = (loader({call_arguments}) for _ in (1,))\n"
        f"loader = {late_loader}\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    deferred = namespace["deferred"]
    assert hasattr(deferred, "__next__")
    if late_loader == "globals":
        assert isinstance(next(deferred), dict)
    else:
        assert next(deferred) == 0

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)
    if late_loader == "globals":
        with pytest.raises(
            StudyRetentionError,
            match="source capability rejected: namespace-reflection",
        ):
            scan_study_dependencies(protocol, repo_root=repo_root)
    else:
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "alias_value",
    (
        "tuple[int]",
        "__builtins__['__import__']("
        "'manufacturing_vision_studio.e1.policy_v2')",
    ),
)
def test_python312_type_alias_never_falls_through_source_flow(
    tmp_path: Path,
    alias_value: str,
) -> None:
    source = _compiled_source(f"type Alias = {alias_value}\n")
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="unsupported source-flow syntax: TypeAlias",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("surface", "source"),
    (
        pytest.param(
            "bare-eval",
            "RESULT = eval('1 + 1')\n",
            id="bare-eval",
        ),
        pytest.param(
            "bare-exec",
            "RESULT = exec('value = 1')\n",
            id="bare-exec",
        ),
        pytest.param(
            "bare-compile",
            "RESULT = compile('1 + 1', '<fixture>', 'eval')\n",
            id="bare-compile",
        ),
        pytest.param(
            "attribute-eval",
            "import builtins\nRESULT = builtins.eval('1 + 1')\n",
            id="attribute-eval",
        ),
        pytest.param(
            "attribute-exec",
            "import builtins\nRESULT = builtins.exec('value = 1')\n",
            id="attribute-exec",
        ),
        pytest.param(
            "attribute-compile",
            "import builtins\n"
            "RESULT = builtins.compile('1 + 1', '<fixture>', 'eval')\n",
            id="attribute-compile",
        ),
        pytest.param(
            "literal-getattr-eval",
            "import builtins\nRESULT = getattr(builtins, 'eval')('1 + 1')\n",
            id="literal-getattr-eval",
        ),
        pytest.param(
            "literal-getattr-exec",
            "import builtins\nRESULT = getattr(builtins, 'exec')('value = 1')\n",
            id="literal-getattr-exec",
        ),
        pytest.param(
            "literal-getattr-compile",
            "import builtins\n"
            "RESULT = getattr(builtins, 'compile')('1 + 1', '<fixture>', 'eval')\n",
            id="literal-getattr-compile",
        ),
        pytest.param(
            "from-import-eval",
            "from builtins import eval as executable\n"
            "RESULT = executable('1 + 1')\n",
            id="from-import-eval",
        ),
        pytest.param(
            "from-import-exec",
            "from builtins import exec as executable\n"
            "RESULT = executable('value = 1')\n",
            id="from-import-exec",
        ),
        pytest.param(
            "from-import-compile",
            "from builtins import compile as executable\n"
            "RESULT = executable('1 + 1', '<fixture>', 'eval')\n",
            id="from-import-compile",
        ),
    ),
)
def test_executable_code_capability_survives_builtin_acquisition(
    tmp_path: Path,
    surface: str,
    source: str,
) -> None:
    del surface
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\nRESULT = vars(builtins)['eval']('1 + 1')\n",
        "import builtins\nRESULT = builtins.__dict__['exec']('value = 1')\n",
        "import builtins\n"
        "RESULT = vars(builtins)['compile']('1 + 1', '<fixture>', 'eval')\n",
    ),
    ids=("vars-eval", "dict-exec", "vars-compile"),
)
def test_executable_code_capability_survives_builtin_mapping_subscript(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\n"
        "name = 'eval'\n"
        "RESULT = vars(builtins)[name]('1 + 1')\n",
        "import builtins\n"
        "name = 'exec'\n"
        "RESULT = builtins.__dict__[name]('value = 1')\n",
        "import builtins\n"
        "name = 'compile'\n"
        "RESULT = vars(builtins)[name]('1 + 1', '<fixture>', 'eval')\n",
    ),
    ids=("eval", "exec", "compile"),
)
def test_executable_code_capability_survives_dynamic_builtin_mapping_subscript(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\nRESULT = vars(builtins).get('eval')('1 + 1')\n",
        "import builtins\n"
        "RESULT = builtins.__dict__.get('exec')('value = 1')\n",
        "import builtins\n"
        "RESULT = vars(builtins).get('compile')"
        "('1 + 1', '<fixture>', 'eval')\n",
        "import builtins\n"
        "lookup = vars(builtins).get\n"
        "RESULT = lookup('eval')('1 + 1')\n",
        "import builtins\n"
        "name = 'exec'\n"
        "RESULT = builtins.__dict__.get(name)('value = 1')\n",
        "import builtins\n"
        "lookup = vars(builtins).get\n"
        "if object():\n"
        "    lookup = len\n"
        "RESULT = lookup('eval')('1 + 1')\n",
    ),
    ids=(
        "eval",
        "exec",
        "compile",
        "aliased-eval",
        "dynamic-exec",
        "joined-eval",
    ),
)
def test_executable_code_capability_survives_builtin_mapping_get(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "category"),
    (
        (
            "import builtins\n"
            "RESULT = vars(builtins).get('__import__')('fractions')\n",
            "dynamic-import",
        ),
        (
            "import builtins\nRESULT = builtins.__dict__.get('globals')()\n",
            "namespace-reflection",
        ),
    ),
    ids=("import-loader", "namespace-reflection"),
)
def test_builtin_mapping_get_preserves_existing_sensitive_categories(
    tmp_path: Path,
    source: str,
    category: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match=rf"source capability rejected: {category}",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\nSAFE = builtins.len((1, 2))\n",
        "import builtins\nSAFE = getattr(builtins, 'len')((1, 2))\n",
    ),
    ids=("attribute", "literal-getattr"),
)
def test_harmless_builtins_attribute_acquisition_remains_allowed(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\nSAFE = vars(builtins)['len']((1, 2))\n",
        "import builtins\nSAFE = builtins.__dict__['len']((1, 2))\n",
    ),
    ids=("vars", "dict"),
)
def test_harmless_builtins_mapping_subscript_remains_allowed(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\nSAFE = vars(builtins).get('len')((1, 2))\n",
        "import builtins\nSAFE = builtins.__dict__.get('len')((1, 2))\n",
        "mapping = {'len': len}\nSAFE = mapping.get('len')((1, 2))\n",
    ),
    ids=("vars", "builtins-dict", "generic-dict"),
)
def test_harmless_literal_mapping_get_remains_allowed(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("case_id", "source", "category"),
    (
        (
            "implicit-module-eval",
            "RESULT = __builtins__.eval('1 + 1')\n",
            "executable-code",
        ),
        (
            "implicit-dict-eval",
            "RESULT = __builtins__['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "getattr-builtins-dict",
            "import builtins\n"
            "mapping = getattr(builtins, '__dict__')\n"
            "RESULT = mapping['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "module-getattribute",
            "import builtins\n"
            "RESULT = builtins.__getattribute__('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "from-import-eval",
            "from builtins import eval as execute\n"
            "RESULT = execute('1 + 1')\n",
            "executable-code",
        ),
        (
            "from-import-import",
            "from builtins import __import__ as load\n"
            "RESULT = load('fractions')\n",
            "dynamic-import",
        ),
        (
            "from-import-globals",
            "from builtins import globals as reflect\n"
            "RESULT = reflect()\n",
            "namespace-reflection",
        ),
        (
            "reflected-get",
            "import builtins\n"
            "lookup = getattr(vars(builtins), 'get')\n"
            "RESULT = lookup('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "direct-getitem",
            "import builtins\n"
            "RESULT = vars(builtins).__getitem__('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "reflected-getitem",
            "import builtins\n"
            "lookup = getattr(vars(builtins), '__getitem__')\n"
            "RESULT = lookup('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "aliased-getitem",
            "import builtins\n"
            "lookup = vars(builtins).__getitem__\n"
            "RESULT = lookup('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "joined-getitem",
            "import builtins\n"
            "lookup = vars(builtins).__getitem__\n"
            "if object():\n"
            "    lookup = len\n"
            "RESULT = lookup('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "reflected-dynamic-get",
            "import builtins\n"
            "name = 'eval'\n"
            "lookup = getattr(vars(builtins), 'get')\n"
            "RESULT = lookup(name)('1 + 1')\n",
            "executable-code",
        ),
        (
            "pop",
            "import builtins\n"
            "RESULT = vars(builtins).pop('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "setdefault",
            "import builtins\n"
            "RESULT = vars(builtins).setdefault('len', len)\n",
            "executable-code",
        ),
        (
            "popitem",
            "import builtins\nRESULT = vars(builtins).popitem()\n",
            "executable-code",
        ),
        (
            "values",
            "import builtins\nRESULT = vars(builtins).values()\n",
            "executable-code",
        ),
        (
            "items",
            "import builtins\nRESULT = vars(builtins).items()\n",
            "executable-code",
        ),
        (
            "copy",
            "import builtins\n"
            "RESULT = vars(builtins).copy()['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "dict-unpack",
            "import builtins\n"
            "mapping = {**vars(builtins)}\n"
            "RESULT = mapping['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "union-left",
            "import builtins\n"
            "mapping = vars(builtins) | {}\n"
            "RESULT = mapping['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "union-right",
            "import builtins\n"
            "mapping = {} | vars(builtins)\n"
            "RESULT = mapping['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "dict-wrapper",
            "import builtins\n"
            "mapping = vars(builtins)\n"
            "wrapper = {'mapping': mapping}\n"
            "RESULT = wrapper['mapping']['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "tuple-alias",
            "import builtins\n"
            "mapping = vars(builtins)\n"
            "alias = (mapping,)[0]\n"
            "RESULT = alias['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "ior-alias",
            "import builtins\n"
            "mapping = {}\n"
            "alias = mapping\n"
            "mapping |= vars(builtins)\n"
            "RESULT = alias['eval']('1 + 1')\n",
            "executable-code",
        ),
        (
            "update-crossing",
            "import builtins\n"
            "mapping = {}\n"
            "alias = mapping\n"
            "mapping.update(vars(builtins))\n"
            "RESULT = alias['eval']('1 + 1')\n",
            "executable-code",
        ),
    ),
)
def test_builtins_origin_mapping_missing_families_fail_closed(
    tmp_path: Path,
    case_id: str,
    source: str,
    category: str,
) -> None:
    del case_id
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match=rf"source capability rejected: {category}",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("case_id", "source"),
    (
        (
            "literal-getitem-len",
            "import builtins\n"
            "mapping = vars(builtins)\n"
            "FIRST = mapping.__getitem__('len')((1, 2))\n"
            "SECOND = getattr(mapping, '__getitem__')('len')((1, 2))\n",
        ),
        (
            "copy-len",
            "import builtins\n"
            "SAFE = vars(builtins).copy()['len']((1, 2))\n",
        ),
        (
            "generic-dict-selections",
            "mapping = {'len': len}\n"
            "FIRST = mapping['len']((1, 2))\n"
            "SECOND = mapping.get('len')((1, 2))\n"
            "THIRD = mapping.__getitem__('len')((1, 2))\n",
        ),
        (
            "key-only-operations",
            "import builtins\n"
            "mapping = vars(builtins)\n"
            "KEYS = mapping.keys()\n"
            "PRESENT = 'len' in mapping\n"
            "SIZE = len(mapping)\n"
            "for KEY in mapping:\n"
            "    break\n",
        ),
    ),
)
def test_builtins_origin_mapping_harmless_controls_remain_allowed(
    tmp_path: Path,
    case_id: str,
    source: str,
) -> None:
    del case_id
    compiled = _compiled_source(source)
    _execute_source(compiled, {})
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + compiled)

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\n"
        "import sys\n"
        "carrier = vars(builtins).get('definitely_missing', sys)\n"
        "REGISTRY = carrier.modules\n",
        "import builtins\n"
        "import sys\n"
        "lookup = getattr(vars(builtins), 'get')\n"
        "carrier = lookup('definitely_missing', sys)\n"
        "REGISTRY = carrier.modules\n",
    ),
    ids=("direct", "reflected"),
)
def test_builtins_mapping_get_missing_literal_preserves_sensitive_default(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("case_id", "source"),
    (
        (
            "missing-harmless-default",
            "import builtins\n"
            "SAFE = vars(builtins).get('definitely_missing', len)((1, 2))\n",
        ),
        (
            "existing-len-ignores-default",
            "import builtins\n"
            "import sys\n"
            "SAFE = vars(builtins).get('len', sys)((1, 2))\n",
        ),
    ),
)
def test_builtins_mapping_get_literal_default_controls_remain_allowed(
    tmp_path: Path,
    case_id: str,
    source: str,
) -> None:
    del case_id
    compiled = _compiled_source(source)
    namespace: dict[str, object] = {}
    _execute_source(compiled, namespace)
    assert namespace["SAFE"] == 2
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + compiled)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_builtins_mapping_get_starred_default_preserves_expanded_value(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "import builtins\n"
        "import sys\n"
        "RESULT = vars(builtins).get('definitely_missing', *(sys,)).modules\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert isinstance(namespace["RESULT"], dict)
    assert "sys" in namespace["RESULT"]

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "call",
    (
        "vars(builtins).get(key='eval')",
        "vars(builtins).get(*('eval',), **{})",
    ),
    ids=("keyword", "starred-and-double-starred"),
)
def test_builtins_mapping_helper_ambiguous_call_shapes_fail_closed(
    tmp_path: Path,
    call: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(
        repo_root,
        RUNNER_PATH,
        "\n" + _compiled_source(f"import builtins\nRESULT = {call}\n"),
    )

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_call_operands_execute_once_in_python_args_then_keywords_order() -> None:
    source = _compiled_source(
        "import builtins\n"
        "trace = []\n"
        "def mark(label, value):\n"
        "    trace.append(label)\n"
        "    return value\n"
        "try:\n"
        "    vars(builtins).get(\n"
        "        mark('key', 'missing'),\n"
        "        *mark('star', (None,)),\n"
        "        named=mark('keyword', None),\n"
        "        **mark('double-starred', {}),\n"
        "    )\n"
        "except TypeError:\n"
        "    pass\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["trace"] == [
        "key",
        "star",
        "keyword",
        "double-starred",
    ]


def test_textual_keyword_before_later_star_uses_args_then_keywords_order() -> None:
    source = _compiled_source(
        "trace = []\n"
        "def mark(label, value):\n"
        "    trace.append(label)\n"
        "    return value\n"
        "def collect(*args, **kwargs):\n"
        "    return args, kwargs\n"
        "RESULT = collect(\n"
        "    named=mark('keyword', 2),\n"
        "    *mark('starred', (1,)),\n"
        ")\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)

    assert namespace["trace"] == ["starred", "keyword"]
    assert namespace["RESULT"] == ((1,), {"named": 2})


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\n"
        "RESULT = vars(builtins).__getattribute__('get')('eval')('1 + 1')\n",
        "import builtins\n"
        "RESULT = vars(builtins).__getattribute__(*('get',))('eval')('1 + 1')\n",
        "import builtins\n"
        "lookup = vars(builtins).__getattribute__\n"
        "RESULT = lookup('get')('eval')('1 + 1')\n",
        "import builtins\n"
        "lookup = getattr(vars(builtins), '__getattribute__')\n"
        "RESULT = lookup('get')('eval')('1 + 1')\n",
        "import builtins\n"
        "lookup = vars(builtins).__getattribute__.__call__\n"
        "RESULT = lookup('get')('eval')('1 + 1')\n",
        "import builtins\n"
        "RESULT = vars(builtins).__getattribute__('__getattribute__')"
        "('get')('eval')('1 + 1')\n",
        "import builtins\n"
        "lookup = vars(builtins).__getattribute__\n"
        "if len(()):\n"
        "    lookup = vars(builtins).__getattribute__\n"
        "RESULT = lookup('get')('eval')('1 + 1')\n",
    ),
    ids=(
        "direct",
        "fixed-starred",
        "alias",
        "reflected",
        "carrier-call",
        "recursive-carrier",
        "same-identity-join",
    ),
)
def test_builtins_mapping_getattribute_laundering_fails_closed(
    tmp_path: Path,
    source: str,
) -> None:
    compiled = _compiled_source(source)
    namespace: dict[str, object] = {}
    _execute_source(compiled, namespace)
    assert namespace["RESULT"] == 2

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + compiled)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_builtins_mapping_get_missing_fixed_star_returns_harmless_default(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "import builtins\n"
        "SAFE = vars(builtins).get('definitely_missing', *(len,))((1, 2))\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["SAFE"] == 2

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_builtins_mapping_existing_key_evaluates_and_ignores_fixed_star_default(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "import builtins\n"
        "trace = []\n"
        "def default():\n"
        "    trace.append('default')\n"
        "    return object\n"
        "SAFE = vars(builtins).get('len', *(default(),))((1, 2))\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["trace"] == ["default"]
    assert namespace["SAFE"] == 2

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_module_origin_getattribute_fixed_star_remains_allowed(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "import builtins\n"
        "SAFE = builtins.__getattribute__(*('len',))((1, 2))\n"
    )
    namespace: dict[str, object] = {}
    _execute_source(source, namespace)
    assert namespace["SAFE"] == 2

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "import builtins\nSAFE = vars(builtins).get('len')((1, 2))\n",
        "import builtins\n"
        "SAFE = getattr(vars(builtins), 'get')('len')((1, 2))\n",
        "import builtins\n"
        "lookup = vars(builtins).get\n"
        "SAFE = lookup('len')((1, 2))\n",
        "import builtins\n"
        "SAFE = vars(builtins).__getitem__('len')((1, 2))\n",
        "import builtins\n"
        "SAFE = getattr(vars(builtins), '__getitem__')('len')((1, 2))\n",
        "import builtins\n"
        "lookup = vars(builtins).__getitem__\n"
        "SAFE = lookup('len')((1, 2))\n",
    ),
    ids=(
        "direct-get",
        "reflected-get",
        "aliased-get",
        "direct-getitem",
        "reflected-getitem",
        "aliased-getitem",
    ),
)
def test_harmless_mapping_get_and_getitem_forms_remain_allowed(
    tmp_path: Path,
    source: str,
) -> None:
    compiled = _compiled_source(source)
    namespace: dict[str, object] = {}
    _execute_source(compiled, namespace)
    assert namespace["SAFE"] == 2

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + compiled)

    scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("case_id", "source", "category"),
    (
        (
            "direct-get-call-eval",
            "import builtins\n"
            "RESULT = vars(builtins).get.__call__('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "direct-getitem-call-eval",
            "import builtins\n"
            "RESULT = vars(builtins).__getitem__.__call__('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "reflected-get-call-eval",
            "import builtins\n"
            "lookup = getattr(vars(builtins), 'get').__call__\n"
            "RESULT = lookup('eval')('1 + 1')\n",
            "executable-code",
        ),
        (
            "reflected-get-call-import",
            "import builtins\n"
            "lookup = getattr(vars(builtins), 'get').__call__\n"
            "RESULT = lookup('__import__')('fractions')\n",
            "dynamic-import",
        ),
        (
            "reflected-get-call-globals",
            "import builtins\n"
            "lookup = getattr(vars(builtins), 'get').__call__\n"
            "RESULT = lookup('globals')()\n",
            "namespace-reflection",
        ),
        (
            "arbitrary-method-reflection",
            "import builtins\n"
            "REFLECTED = vars(builtins).get.__func__\n",
            "executable-code",
        ),
    ),
)
def test_builtins_mapping_method_carrier_reflection_fails_closed(
    tmp_path: Path,
    case_id: str,
    source: str,
    category: str,
) -> None:
    del case_id
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(
        StudyRetentionError,
        match=rf"source capability rejected: {category}",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "source",
    (
        "from manufacturing_vision_studio.not_real import marker\n",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.not_real import marker\n",
    ),
    ids=("eager", "type-checking"),
)
def test_named_import_from_nonexistent_project_module_fails_closed(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))

    with pytest.raises(StudyRetentionError, match="unresolved project import"):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_raise_expression_evaluation_keeps_type_error_handler_reachable(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "trace = []\n"
        "try:\n"
        "    raise ValueError(*(item for item in 0))\n"
        "except TypeError:\n"
        "    trace.append('handled')\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == ["handled"]

    source = _compiled_source(
        "try:\n"
        "    raise ValueError(*(item for item in 0))\n"
        "except TypeError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match=r"forbidden direct import.*policy_v2",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("setup", "raise_statement"),
    (
        ("", "raise KeyError()\n"),
        (
            "class CustomError(Exception):\n"
            "    pass\n",
            "raise CustomError()\n",
        ),
        (
            "class CustomError(Exception):\n"
            "    pass\n"
            "ValueError = CustomError\n",
            "raise ValueError()\n",
        ),
        (
            "class Errors:\n"
            "    ValueError = ValueError\n",
            "raise Errors.ValueError()\n",
        ),
    ),
    ids=("unlisted", "custom", "shadowed", "attributed"),
)
def test_nonprovable_exception_relationship_keeps_handler_reachable(
    tmp_path: Path,
    setup: str,
    raise_statement: str,
) -> None:
    indented_raise = textwrap.indent(raise_statement, "    ")
    source = _compiled_source(
        setup
        + "try:\n"
        + indented_raise
        + "except TypeError:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match=r"forbidden direct import.*policy_v2",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    "case_id",
    ("for", "async-for", "eager-comprehension"),
)
def test_later_iterator_exception_receives_backedge_state(
    tmp_path: Path,
    case_id: str,
) -> None:
    if case_id == "async-for":
        iterator_definition = (
            "class LaterIterator:\n"
            "    def __init__(self):\n"
            "        self.step = 0\n"
            "    def __aiter__(self):\n"
            "        return self\n"
            "    async def __anext__(self):\n"
            "        if self.step:\n"
            "            raise RuntimeError('later')\n"
            "        self.step = 1\n"
            "        return 0\n"
        )
        trace_source = _compiled_source(
            "import asyncio\n"
            + iterator_definition
            + "async def observed():\n"
            "    trace = []\n"
            "    carrier = 'before'\n"
            "    try:\n"
            "        async for _ in LaterIterator():\n"
            "            carrier = 'body'\n"
            "            trace.append(carrier)\n"
            "    except RuntimeError:\n"
            "        trace.append(f'handled:{carrier}')\n"
            "    return trace\n"
            "trace = asyncio.run(observed())\n"
        )
        scanner_source = _compiled_source(
            "import sys\n"
            + iterator_definition
            + "async def observed() -> None:\n"
            "    carrier = sys.stdout\n"
            "    try:\n"
            "        async for _ in LaterIterator():\n"
            "            carrier = sys\n"
            "    except RuntimeError:\n"
            "        REGISTRY = carrier.modules\n"
        )
        expected_trace = ["body", "handled:body"]
    else:
        iterator_definition = (
            "class LaterIterator:\n"
            "    def __init__(self):\n"
            "        self.step = 0\n"
            "    def __iter__(self):\n"
            "        return self\n"
            "    def __next__(self):\n"
            "        if self.step:\n"
            "            raise RuntimeError('later')\n"
            "        self.step = 1\n"
            "        return 0\n"
        )
        if case_id == "for":
            trace_source = _compiled_source(
                iterator_definition
                + "trace = []\n"
                "carrier = 'before'\n"
                "try:\n"
                "    for _ in LaterIterator():\n"
                "        carrier = 'body'\n"
                "        trace.append(carrier)\n"
                "except RuntimeError:\n"
                "    trace.append(f'handled:{carrier}')\n"
            )
            scanner_source = _compiled_source(
                "import sys\n"
                + iterator_definition
                + "carrier = sys.stdout\n"
                "try:\n"
                "    for _ in LaterIterator():\n"
                "        carrier = sys\n"
                "except RuntimeError:\n"
                "    REGISTRY = carrier.modules\n"
            )
            expected_trace = ["body", "handled:body"]
        else:
            trace_source = _compiled_source(
                iterator_definition
                + "trace = []\n"
                "carrier = 'before'\n"
                "try:\n"
                "    RESULT = [(carrier := 'body') for _ in LaterIterator()]\n"
                "except RuntimeError:\n"
                "    trace.append(f'handled:{carrier}')\n"
            )
            scanner_source = _compiled_source(
                "import sys\n"
                + iterator_definition
                + "carrier = sys.stdout\n"
                "try:\n"
                "    RESULT = [(carrier := sys) for _ in LaterIterator()]\n"
                "except RuntimeError:\n"
                "    REGISTRY = carrier.modules\n"
            )
            expected_trace = ["handled:body"]

    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == expected_trace

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + scanner_source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_non_normal_class_body_does_not_resurrect_normal_state(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "import sys\n"
        "carrier = sys\n"
        "try:\n"
        "    class Broken:\n"
        "        global carrier\n"
        "        carrier = None\n"
        "        raise ValueError('class body')\n"
        "except ValueError:\n"
        "    pass\n"
        "trace = [carrier is None, 'Broken' in globals()]\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == [True, False]

    source = _compiled_source(
        "import sys\n"
        "carrier = sys\n"
        "try:\n"
        "    class Broken:\n"
        "        global carrier\n"
        "        carrier = None\n"
        "        raise ValueError('class body')\n"
        "except ValueError:\n"
        "    pass\n"
        "REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_raising_with_context_does_not_enter_body_or_resurrect_state(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "import sys\n"
        "carrier = sys\n"
        "trace = []\n"
        "try:\n"
        "    with missing:\n"
        "        trace.append('body')\n"
        "except NameError:\n"
        "    carrier = carrier.stdout\n"
        "missing = object()\n"
        "trace.append(carrier is sys.stdout)\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == [True]

    source = _compiled_source(
        "import sys\n"
        "carrier = sys\n"
        "try:\n"
        "    with missing:\n"
        "        pass\n"
        "except NameError:\n"
        "    carrier = carrier.stdout\n"
        "missing = object()\n"
        "REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_raising_async_with_context_does_not_enter_body_or_resurrect_state(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "import asyncio\n"
        "import sys\n"
        "async def observed():\n"
        "    carrier = sys\n"
        "    trace = []\n"
        "    try:\n"
        "        async with missing:\n"
        "            trace.append('body')\n"
        "    except NameError:\n"
        "        carrier = carrier.stdout\n"
        "    missing = object()\n"
        "    trace.append(carrier is sys.stdout)\n"
        "    return trace\n"
        "trace = asyncio.run(observed())\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == [True]

    source = _compiled_source(
        "import sys\n"
        "async def observed() -> None:\n"
        "    carrier = sys\n"
        "    try:\n"
        "        async with missing:\n"
        "            pass\n"
        "    except NameError:\n"
        "        carrier = carrier.stdout\n"
        "    missing = object()\n"
        "    REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_non_normal_expression_sequence_does_not_resurrect_state(
    tmp_path: Path,
) -> None:
    trace_source = _compiled_source(
        "import sys\n"
        "carrier = sys\n"
        "try:\n"
        "    VALUE = (missing, 0)\n"
        "except NameError:\n"
        "    carrier = carrier.stdout\n"
        "missing = object()\n"
        "trace = [carrier is sys.stdout]\n"
    )
    trace_namespace: dict[str, object] = {}
    _execute_source(trace_source, trace_namespace)
    assert trace_namespace["trace"] == [True]

    source = _compiled_source(
        "import sys\n"
        "carrier = sys\n"
        "try:\n"
        "    VALUE = (missing, 0)\n"
        "except NameError:\n"
        "    carrier = carrier.stdout\n"
        "missing = object()\n"
        "REGISTRY = carrier.modules\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


def test_unreachable_expression_suffix_remains_policy_inspected(
    tmp_path: Path,
) -> None:
    source = _compiled_source(
        "try:\n"
        "    VALUE = (missing, eval('1 + 1'))\n"
        "except NameError:\n"
        "    pass\n"
        "missing = object()\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: executable-code",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def _analyze_source(source: str) -> tuple[ast.Module, object]:
    tree = ast.parse(_compiled_source(source))
    analyzer = retention_module._SourceFlowAnalyzer(
        source_module="source_flow_stats_fixture",
        known_modules=frozenset(),
        initializer_policy=retention_module._InitializerPolicy((), ()),
    )
    return tree, analyzer.analyze(tree)


@pytest.mark.parametrize(
    ("source", "expected_truth"),
    (
        ("VALUE = None is None\n", retention_module._Truth.TRUE),
        ("VALUE = None is not None\n", retention_module._Truth.FALSE),
        ("VALUE = 1 == 1\n", retention_module._Truth.TRUE),
        ("VALUE = 1 is 1\n", retention_module._Truth.UNKNOWN),
    ),
)
def test_compare_pair_truth_preserves_python_singleton_semantics(
    source: str,
    expected_truth: object,
) -> None:
    tree = ast.parse(source)
    analyzer = retention_module._SourceFlowAnalyzer(
        source_module="source_flow_stats_fixture",
        known_modules=frozenset(),
        initializer_policy=retention_module._InitializerPolicy((), ()),
    )
    result = analyzer.analyze(tree)
    value = result.final_states[0].resolve("VALUE").value

    assert value.truth is expected_truth


def test_compare_short_circuit_keeps_real_sys_carrier_visible_to_public_scanner(
    tmp_path: Path,
) -> None:
    source = (
        "import sys as carrier\n"
        "FLAG = 1 is True is (carrier := carrier.stdout)\n"
        "REGISTRY = carrier.modules\n"
    )
    code = _compile_without_emitting_warnings(source)
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["FLAG"] is False
    assert namespace["carrier"] is sys

    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "expected_error_categories"),
    (
        (
            "import sys as carrier\n"
            "VALUE = 0 > 1 < (carrier := carrier.stdout)\n"
            "REGISTRY = carrier.modules\n",
            ("import-registry",),
        ),
        (
            "import sys\n"
            "carrier = sys.stdout\n"
            "VALUE = 0 < 1 < (1 if (carrier := sys) else 0)\n"
            "REGISTRY = carrier.modules\n",
            ("import-registry",),
        ),
        (
            "import sys as carrier\n"
            "VALUE = 0 > 1 < ((carrier := carrier.stdout) or eval('1+1'))\n"
            "REGISTRY = carrier.modules\n",
            ("executable-code", "import-registry"),
        ),
    ),
)
def test_chained_compare_short_circuit_preserves_state_and_policy(
    source: str,
    expected_error_categories: tuple[str, ...],
) -> None:
    _, result = _analyze_source(source)
    carrier = result.final_states[0].resolve("carrier").value
    errors = "\n".join(sorted(result.facts.closure_errors))

    assert carrier.facts.may_capabilities == frozenset({"sys-module"})
    for category in expected_error_categories:
        assert category in errors


@pytest.mark.parametrize(
    ("source", "expected_truth", "expected_outcomes", "may_iteration_raise"),
    (
        ("VALUE = 0\n", retention_module._Truth.FALSE, frozenset(), True),
        ("VALUE = 1\n", retention_module._Truth.TRUE, frozenset(), True),
        (
            "VALUE = ''\n",
            retention_module._Truth.FALSE,
            frozenset({"zero"}),
            False,
        ),
        (
            "VALUE = 'x'\n",
            retention_module._Truth.TRUE,
            frozenset({"one"}),
            False,
        ),
        (
            "VALUE = b'xy'\n",
            retention_module._Truth.TRUE,
            frozenset({"many"}),
            False,
        ),
        (
            "VALUE = []\n",
            retention_module._Truth.FALSE,
            frozenset({"zero"}),
            False,
        ),
        (
            "VALUE = [0]\n",
            retention_module._Truth.TRUE,
            frozenset({"one"}),
            False,
        ),
        (
            "VALUE = (0, 1)\n",
            retention_module._Truth.TRUE,
            frozenset({"many"}),
            False,
        ),
        (
            "VALUE = {1, 1}\n",
            retention_module._Truth.TRUE,
            frozenset({"one"}),
            False,
        ),
        (
            "VALUE = {1: 'first'}\n",
            retention_module._Truth.TRUE,
            frozenset({"one"}),
            False,
        ),
        (
            "VALUE = {1: 'first', 1: 'last'}\n",
            retention_module._Truth.TRUE,
            frozenset({"one"}),
            False,
        ),
    ),
)
def test_literal_truth_and_iteration_facts_are_independent(
    source: str,
    expected_truth: object,
    expected_outcomes: frozenset[str],
    *,
    may_iteration_raise: bool,
) -> None:
    _, result = _analyze_source(source)
    value = result.final_states[0].resolve("VALUE").value

    assert value.truth is expected_truth
    assert value.iteration_outcomes == expected_outcomes
    assert value.may_iteration_raise is may_iteration_raise


@pytest.mark.parametrize("depth", (1, 2, 4, 8, 16, 32, 64))
def test_analysis_stats_are_canonical_for_straight_line_dunder_chains(
    depth: int,
) -> None:
    expression = "object()"
    for _ in range(depth):
        expression = f"({expression}).__getattribute__('x')"
    tree, result = _analyze_source(f"VALUE = {expression}\n")
    stats = result.stats
    syntax_nodes = len(tuple(ast.walk(tree)))

    assert syntax_nodes == 4 * depth + 7
    assert stats == retention_module._AnalysisStats(
        program_points=3 * depth + 3,
        cfg_edges=3 * depth + 2,
        expression_transfers=3 * depth + 2,
        statement_transfers=1,
        pattern_transfers=0,
        state_join_attempts=0,
        strict_state_updates=0,
        worklist_pops=0,
        max_updates_per_program_point=0,
        computed_height_bound=69,
    )
    assert stats.expression_transfers <= 2 * syntax_nodes
    assert stats.max_updates_per_program_point <= stats.computed_height_bound
    assert stats.worklist_pops <= stats.program_points * (
        stats.computed_height_bound + 1
    )
    assert stats.transfer_steps <= stats.program_points * (
        stats.computed_height_bound + 1
    )


def test_analysis_stats_count_diamond_joins_and_reverse_suffix_work() -> None:
    _, result = _analyze_source(
        "alias = len\n"
        "if object():\n"
        "    alias = str\n"
        "else:\n"
        "    alias = bytes\n"
        "def deferred() -> object:\n"
        "    return alias\n"
        "alias = tuple\n"
    )
    stats = result.stats

    assert stats.cfg_edges >= stats.transfer_steps - 1
    assert stats.state_join_attempts > 0
    assert stats.strict_state_updates > 0
    assert stats.worklist_pops >= 5
    assert stats.max_updates_per_program_point <= stats.computed_height_bound
    assert stats.worklist_pops <= stats.program_points * (
        stats.computed_height_bound + 1
    )
    assert stats.transfer_steps <= stats.program_points * (
        stats.computed_height_bound + 1
    )


def test_branch_state_join_uses_canonical_program_point_counters() -> None:
    _, result = _analyze_source(
        "if object():\n"
        "    alias = str\n"
        "else:\n"
        "    alias = bytes\n"
    )

    assert result.stats == retention_module._AnalysisStats(
        program_points=7,
        cfg_edges=8,
        expression_transfers=4,
        statement_transfers=3,
        pattern_transfers=0,
        state_join_attempts=1,
        strict_state_updates=1,
        worklist_pops=0,
        max_updates_per_program_point=1,
        computed_height_bound=69,
    )


def test_retained_loop_point_growth_uses_canonical_update_counters() -> None:
    _, result = _analyze_source(
        "for _ in (0, 1):\n"
        "    deferred = lambda: None\n"
    )
    stats = result.stats

    assert isinstance(stats, retention_module._AnalysisStats)
    assert stats.program_points == 11
    assert stats.state_join_attempts == 6
    assert stats.strict_state_updates == 2
    assert stats.max_updates_per_program_point == 1
    assert stats.computed_height_bound == 137
    assert stats.max_updates_per_program_point <= stats.computed_height_bound
    assert stats.worklist_pops <= stats.program_points * (
        stats.computed_height_bound + 1
    )
    assert stats.transfer_steps <= stats.program_points * (
        stats.computed_height_bound + 1
    )


@pytest.mark.parametrize(
    "definition",
    (
        "def deferred() -> object:\n"
        "    return carrier.modules\n",
        "deferred = lambda: carrier.modules\n",
        "deferred = (carrier.modules for _ in (0,))\n",
    ),
)
def test_suffix_envelope_retains_transient_post_definition_state(
    tmp_path: Path,
    definition: str,
) -> None:
    source = _compiled_source(
        "import sys\n"
        "carrier = sys.stdout\n"
        f"{definition}"
        "carrier = sys\n"
        "carrier = sys.stdout\n"
    )
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: import-registry",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)


def test_computed_height_uses_one_real_program_point_shape() -> None:
    _, result = _analyze_source(
        "wide = None\n"
        "nested = None\n"
        "def wide() -> None:\n"
        "    a = b = c = d = e = f = g = h = i = j = None\n"
        "nested = lambda: (lambda: None)\n"
    )

    assert result.stats.computed_height_bound == 807
