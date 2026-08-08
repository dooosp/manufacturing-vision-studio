from __future__ import annotations

import subprocess
import sys
import textwrap
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
    compile(source, "<dependency-guard-fixture>", "exec")
    return source


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

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
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


def _nested_expression(family: str, depth: int) -> str:
    expression = "object()"
    for _ in range(depth):
        if family == "dunder":
            expression = f"({expression}).__getattribute__('x')"
        elif family == "boolop":
            expression = f"(False or {expression})"
        elif family == "ifexp":
            expression = f"({expression} if True else object())"
        elif family == "lambda":
            expression = f"(lambda value={expression}: value)"
        elif family == "genexpr":
            expression = f"({expression} for _ in (0,))"
        elif family == "comprehension":
            expression = f"[{expression} for _ in (0,)]"
        elif family == "container":
            expression = f"[{expression}]"
        else:
            raise AssertionError(f"unknown fixture family: {family}")
    return f"VALUE = {expression}\n"


@pytest.mark.parametrize("depth", (1, 2, 4, 8, 16, 32, 64))
@pytest.mark.parametrize(
    "family",
    ("dunder", "boolop", "ifexp", "lambda", "genexpr", "comprehension", "container"),
)
def test_transfer_is_single_pass_for_structural_fixture_families(
    tmp_path: Path,
    family: str,
    depth: int,
) -> None:
    """Task 1 records stable baseline acceptance; Task 5 adds canonical counters."""

    source = _compiled_source(_nested_expression(family, depth))
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    scan_study_dependencies(protocol, repo_root=repo_root)


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
