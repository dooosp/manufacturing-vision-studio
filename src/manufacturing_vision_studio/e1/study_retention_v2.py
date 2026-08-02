"""Read-only closure checks and immutable Phase 0 retention evidence."""

from __future__ import annotations

import ast
import os
import re
import subprocess
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.e1.protocol_v2 import verify_e1_v1_history
from manufacturing_vision_studio.e1.study_artifacts_v2 import (
    StudyArtifactError,
    StudyArtifactStore,
    StudyGateRecord,
    finalize_study_record,
    load_strict_json_object,
    read_bounded_bytes,
    validate_study_schema,
    verify_self_hash,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    PROJECT_ROOT,
    StudyProtocolV2,
)

EdgeKind = Literal["direct", "runtime_transitive", "type_checking"]
_DynamicImportLoaderKind = Literal["loader", "nonliteral_reflection"]

_SHA1_LENGTH = 40
_SHA256_LENGTH = 64
_MAX_INPUT_BYTES = 4 * 1024 * 1024
_MAX_PROJECTED_BYTES = 25 * 1024 * 1024
_STUDY_ID = "e1-feasibility-separability"
_SOURCE_BRANCH = "codex/e1-v2-scale-feature-remediation"
_IMPLEMENTATION_VALIDATION_PATH = "implementation-validation.json"
_RETENTION_AUDIT_PATH = "retention-audit.json"
_MODES = ("NEAREST", "BILINEAR", "BICUBIC")

IMPLEMENTATION_VALIDATION_COMMANDS = (
    ("ruff", ("uv", "run", "ruff", "check", ".")),
    ("mypy", ("uv", "run", "mypy", "src")),
    (
        "v0_1_regression",
        ("uv", "run", "pytest", "-q", "tests/test_e1_baseline.py"),
    ),
    ("pytest", ("uv", "run", "pytest", "-q")),
    ("web_check", ("npm", "--prefix", "web", "run", "check")),
    ("playwright", ("npm", "--prefix", "web", "run", "test:e2e")),
)
NOT_APPLICABLE_CONTROLS = (
    ("bundle_verify_reimport_rate", "STUDY_PUBLISHES_NO_BUNDLE"),
    ("dataset_split_hash_overlap", "PROTECTED_SPLIT_MEMBERS_NOT_ENUMERATED"),
    ("same_seed_manifest_equivalence", "FULL_TWO_RUN_EQUIVALENCE_NOT_AUTHORIZED"),
    (
        "revision_mismatch_publication_count",
        "STUDY_HAS_NO_RUNTIME_PUBLICATION_PATH",
    ),
    (
        "corrupted_evidence_publication_count",
        "STUDY_HAS_NO_RUNTIME_PUBLICATION_PATH",
    ),
)
RETAINED_INPUTS = (
    (
        "candidate_a",
        "data/e1-v2-development/candidate-a.json",
        "retained-inputs/candidate-a.json",
        "candidate_a_raw_sha256",
    ),
    (
        "candidate_b",
        "data/e1-v2-development/candidate-b.json",
        "retained-inputs/candidate-b.json",
        "candidate_b_raw_sha256",
    ),
    (
        "task_4_report",
        "docs/evaluation/negative-results/e1-v2-task4-report.raw.txt",
        "retained-inputs/task-4-report.md",
        "task4_report_raw_sha256",
    ),
    (
        "sdd_progress",
        "docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt",
        "retained-inputs/sdd-progress.md",
        "task4_progress_ledger_raw_sha256",
    ),
)
PERFORMANCE_ROOTS = (
    "manufacturing_vision_studio.e1.study_cli_v2",
    "manufacturing_vision_studio.e1.study_runner_v2",
)
FORBIDDEN_DIRECT = frozenset(
    {
        "manufacturing_vision_studio.e1.policy_v2",
        "manufacturing_vision_studio.e1.geometry",
        "manufacturing_vision_studio.e1.geometry_search",
        "manufacturing_vision_studio.e1.diagnostics_v2",
    }
)
_FORBIDDEN_RUNTIME_PREFIXES = (
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
)
_FORBIDDEN_CALL_NAMES = frozenset(
    {
        "compare_candidates",
        "load_candidate_selection",
        "repair_candidate_selection_from_preserved_run",
        "select_candidate",
    }
)
_PROTECTED_SCOPES = frozenset({"SMOKE", "CALIBRATION", "RELEASE_TEST"})
_PROJECTED_PACKAGE_ROOTS = frozenset(
    {"manufacturing_vision_studio", "manufacturing_vision_studio.e1"}
)
_RETAIN = (
    "development diagnostic matrix",
    "split guards",
    "canonical metric calculations",
    "truth-erasing runtime input",
    "final-mask ownership mapping",
    "v1 history verification",
    "Task 4 negative evidence",
)
_ISOLATE = (
    "Candidate A/B search and normalization",
    "candidate ranking",
    "candidate selection loader",
    "candidate work caps",
    "candidate-specific benchmarking and constants",
)
_RE_REVIEW = (
    "candidate-coupled protocol fields",
    "legacy development-template planning",
    "ownership assumptions",
    "any source whose change would invalidate the historical implementation projection",
)
_RFC3339_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)


class StudyRetentionError(ValueError):
    """Retention evidence or the audited repository boundary is invalid."""


@dataclass(frozen=True, slots=True)
class ProjectionEntry:
    path: str
    sha256: str

    def as_record(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    source: str
    target: str
    kind: EdgeKind

    def as_record(self) -> dict[str, object]:
        return {"source": self.source, "target": self.target, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class DependencyScanReport:
    edges: tuple[DependencyEdge, ...]
    forbidden_direct_edges: tuple[DependencyEdge, ...]
    protected_scope_references: tuple[str, ...]
    projection_sha256: str
    direct_import_allowlist: tuple[tuple[str, tuple[str, ...]], ...]

    def as_record(self) -> dict[str, object]:
        return {
            "edges": [edge.as_record() for edge in self.edges],
            "forbidden_direct_edges": [
                edge.as_record() for edge in self.forbidden_direct_edges
            ],
            "protected_scope_references": list(self.protected_scope_references),
            "projection_sha256": self.projection_sha256,
            "direct_import_allowlist": {
                name: list(imports) for name, imports in self.direct_import_allowlist
            },
        }


@dataclass(frozen=True, slots=True)
class HistoricalHoldAudit:
    selection_raw_sha256: str
    selection_record_sha256: str
    outcome: str
    selected_candidate_id: None
    v1_history_outcome: str
    v1_history_artifact_count: int

    def as_record(self) -> dict[str, object]:
        return {
            "selection_raw_sha256": self.selection_raw_sha256,
            "selection_record_sha256": self.selection_record_sha256,
            "outcome": self.outcome,
            "selected_candidate_id": self.selected_candidate_id,
            "v1_history_outcome": self.v1_history_outcome,
            "v1_history_artifact_count": self.v1_history_artifact_count,
        }


@dataclass(frozen=True, slots=True)
class RetainedInputRecord:
    name: str
    path: str
    source_sha256: str
    copied_sha256: str
    byte_size: int

    def as_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "source_sha256": self.source_sha256,
            "copied_sha256": self.copied_sha256,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True, slots=True)
class SeedDisjointnessAudit:
    diagnostic_seed_start: int
    diagnostic_seed_end: int
    diagnostic_seed_count: int
    declared_evaluation_seed_count: int
    overlap_count: int
    overlap_seeds: tuple[int, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "diagnostic_seed_start": self.diagnostic_seed_start,
            "diagnostic_seed_end": self.diagnostic_seed_end,
            "diagnostic_seed_count": self.diagnostic_seed_count,
            "declared_evaluation_seed_count": self.declared_evaluation_seed_count,
            "overlap_count": self.overlap_count,
            "overlap_seeds": list(self.overlap_seeds),
        }


@dataclass(frozen=True, slots=True)
class RetentionClassifications:
    retain: tuple[str, ...]
    isolate: tuple[str, ...]
    re_review: tuple[str, ...]

    def as_mapping(self) -> dict[str, tuple[str, ...]]:
        return {
            "Retain": self.retain,
            "Isolate": self.isolate,
            "Re-review": self.re_review,
        }

    def as_record(self) -> dict[str, object]:
        return {key: list(values) for key, values in self.as_mapping().items()}


@dataclass(frozen=True, slots=True)
class UpstreamArtifact:
    path: str
    raw_sha256: str
    record_sha256: str

    def as_record(self) -> dict[str, object]:
        return {
            "path": self.path,
            "raw_sha256": self.raw_sha256,
            "record_sha256": self.record_sha256,
        }


@dataclass(frozen=True, slots=True)
class ValidationCommand:
    name: str
    argv: tuple[str, ...]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    started_at_utc: str
    ended_at_utc: str


@dataclass(frozen=True, slots=True)
class VerifiedImplementationValidation:
    base_commit: str
    execution_commit: str
    protocol_sha256: str
    artifact_root: str
    artifact_schema_sha256: str
    implementation_projection_sha256: str
    upstream_artifacts: tuple[UpstreamArtifact, ...]
    worktree_clean: bool
    commands: tuple[ValidationCommand, ...]
    first_projection: Mapping[str, str]
    second_projection: Mapping[str, str]
    not_applicable_controls: tuple[StudyGateRecord, ...]
    passed: bool
    raw_sha256: str
    record_sha256: str


@dataclass(frozen=True, slots=True)
class RetentionAudit:
    base_commit: str
    execution_commit: str
    evidence_commit: str
    protocol_sha256: str
    artifact_root: str
    artifact_schema_sha256: str
    implementation_projection_sha256: str
    upstream_artifacts: tuple[UpstreamArtifact, ...]
    history: HistoricalHoldAudit
    retained_inputs: tuple[RetainedInputRecord, ...]
    implementation_projection: tuple[ProjectionEntry, ...]
    dependency_report: DependencyScanReport
    seed_disjointness: SeedDisjointnessAudit
    classifications: RetentionClassifications
    passed: bool
    record_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        finalized = finalize_study_record(self._unfinalized_record())
        object.__setattr__(self, "record_sha256", cast(str, finalized["record_sha256"]))

    def _unfinalized_record(self) -> dict[str, object]:
        return {
            "record_type": "retention_audit",
            "schema_version": "1.0.0",
            "study_id": _STUDY_ID,
            "development_only": True,
            "selection_eligible": False,
            "release_claim_allowed": False,
            "base_commit": self.base_commit,
            "execution_commit": self.execution_commit,
            "evidence_commit": self.evidence_commit,
            "protocol_sha256": self.protocol_sha256,
            "artifact_root": self.artifact_root,
            "artifact_schema_sha256": self.artifact_schema_sha256,
            "implementation_projection_sha256": self.implementation_projection_sha256,
            "upstream_artifacts": [item.as_record() for item in self.upstream_artifacts],
            "payload": {
                "history": self.history.as_record(),
                "retained_inputs": [item.as_record() for item in self.retained_inputs],
                "implementation_projection": [
                    item.as_record() for item in self.implementation_projection
                ],
                "dependency_report": self.dependency_report.as_record(),
                "seed_disjointness": self.seed_disjointness.as_record(),
                "classifications": self.classifications.as_record(),
                "passed": self.passed,
            },
        }

    def as_record(self) -> dict[str, object]:
        finalized = finalize_study_record(self._unfinalized_record())
        if finalized["record_sha256"] != self.record_sha256:
            raise StudyRetentionError("retention audit self-hash changed in memory")
        return finalized


@dataclass(frozen=True, slots=True)
class _ImportReference:
    target: str
    type_checking: bool


@dataclass(frozen=True, slots=True)
class _PreparedInput:
    name: str
    destination: str
    payload: bytes
    source_sha256: str


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, *, source_module: str, known_modules: frozenset[str]) -> None:
        self.source_module = source_module
        self.known_modules = known_modules
        self.type_checking_depth = 0
        self.references: list[_ImportReference] = []
        self.protected: list[str] = []
        self.forbidden_calls: list[str] = []
        self.study_forbidden_calls: list[str] = []
        self.closure_errors: list[str] = []
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.importlib_module_names: set[str] = set()
        self.import_module_names: set[str] = set()
        self.package_object_names: dict[str, str] = {}
        self.allowed_import_module_name_nodes: set[int] = set()

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_test(node.test):
            self.type_checking_depth += 1
            for child in node.body:
                self.visit(child)
            self.type_checking_depth -= 1
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if self.type_checking_depth == 0:
                if alias.name in _PROJECTED_PACKAGE_ROOTS:
                    self.closure_errors.append(
                        f"{self.source_module}:{node.lineno}:"
                        f"runtime package-object import: {alias.name}"
                    )
                if _is_importlib_target(alias.name):
                    self.closure_errors.append(
                        f"{self.source_module}:{node.lineno}:"
                        f"runtime importlib import: {alias.name}"
                    )
            if alias.name == "importlib":
                self.importlib_module_names.add(alias.asname or alias.name)
            if alias.name in _PROJECTED_PACKAGE_ROOTS:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                bound_target = alias.name if alias.asname else "manufacturing_vision_studio"
                self.package_object_names[bound_name] = bound_target
            target = _nearest_known_module(alias.name, self.known_modules)
            if target is not None:
                self.references.append(
                    _ImportReference(target, self.type_checking_depth > 0)
                )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (
            self.type_checking_depth == 0
            and node.level == 0
            and _is_importlib_target(node.module)
            and not _is_allowed_initializer_import_module(self.source_module, node)
        ):
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:"
                f"runtime importlib import: {node.module}"
            )
        if node.level == 0 and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    self.import_module_names.add(alias.asname or alias.name)
        base = _resolve_import_from_base(self.source_module, node.module, node.level)
        if base is None:
            return
        for alias in node.names:
            candidate = f"{base}.{alias.name}" if alias.name != "*" else base
            if (
                base in _PROJECTED_PACKAGE_ROOTS
                and candidate not in self.known_modules
                and self.type_checking_depth == 0
            ):
                self.closure_errors.append(
                    f"{self.source_module}:{node.lineno}:unresolved package symbol import: "
                    f"{candidate}"
                )
                continue
            target = _nearest_known_module(candidate, self.known_modules)
            if target is None:
                target = _nearest_known_module(base, self.known_modules)
            if target is not None:
                self.references.append(
                    _ImportReference(target, self.type_checking_depth > 0)
                )

    def visit_Assign(self, node: ast.Assign) -> None:
        loader_kind = _dynamic_import_loader_kind(
            node.value,
            importlib_module_names=self.importlib_module_names,
            import_module_names=self.import_module_names,
        )
        if loader_kind == "loader":
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.import_module_names.add(target.id)
        elif loader_kind == "nonliteral_reflection" and self.type_checking_depth == 0:
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:"
                "non-literal reflected import loader"
            )
        package_target = self._package_object_target(node.value)
        if package_target is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.package_object_names[target.id] = package_target
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self.type_checking_depth == 0 and node.attr == "__import__":
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:runtime __import__ symbol access"
            )
        package_target = self._package_object_target(node.value)
        if package_target is not None:
            self._record_package_attribute(
                package_target,
                node.attr,
                lineno=node.lineno,
            )
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "EvaluationScope"
            and node.attr in _PROTECTED_SCOPES
        ):
            self.protected.append(f"{self.source_module}:{node.lineno}:EvaluationScope.{node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._visit_package_getattr(node)
        self._visit_reflected_builtin_import(node)
        loader_kind = _dynamic_import_loader_kind(
            node.func,
            importlib_module_names=self.importlib_module_names,
            import_module_names=self.import_module_names,
        )
        if loader_kind == "loader":
            self._visit_dynamic_import(node)
        elif loader_kind == "nonliteral_reflection" and self.type_checking_depth == 0:
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:"
                "non-literal reflected import loader"
            )
        name = _call_name(node.func)
        if (
            name == "plan_cases"
            and not _is_allowed_development_provider_plan(
                self.source_module,
                self.class_stack,
                node,
            )
            and not _is_allowed_legacy_v1_plan(self.source_module, node)
        ):
            self.study_forbidden_calls.append(
                f"{self.source_module}:{node.lineno}:plan_cases outside DevelopmentCorpusProvider"
            )
        elif name in _FORBIDDEN_CALL_NAMES or name == "FreeCADExportAdapter":
            self.forbidden_calls.append(f"{self.source_module}:{node.lineno}:{name}")
        allowed_loader_name = (
            isinstance(node.func, ast.Name)
            and _is_allowed_lazy_package_import(
                self.source_module,
                self.function_stack,
                node,
            )
        )
        if allowed_loader_name:
            self.allowed_import_module_name_nodes.add(id(node.func))
        try:
            self.generic_visit(node)
        finally:
            if allowed_loader_name:
                self.allowed_import_module_name_nodes.remove(id(node.func))

    def visit_Name(self, node: ast.Name) -> None:
        if (
            self.type_checking_depth == 0
            and isinstance(node.ctx, ast.Load)
            and node.id == "__import__"
        ):
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:runtime __import__ symbol access"
            )
        if (
            self.type_checking_depth == 0
            and self.source_module in _PROJECTED_PACKAGE_ROOTS
            and node.id in self.import_module_names
            and id(node) not in self.allowed_import_module_name_nodes
        ):
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:"
                "runtime importlib loader symbol access"
            )

    def _visit_reflected_builtin_import(self, node: ast.Call) -> None:
        if (
            self.type_checking_depth == 0
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "__import__"
        ):
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:runtime __import__ symbol access"
            )

    def _visit_dynamic_import(self, node: ast.Call) -> None:
        if not node.args:
            return
        target_node = node.args[0]
        if isinstance(target_node, ast.Constant) and isinstance(target_node.value, str):
            target = target_node.value
            if not _is_package_target(target):
                return
            if target not in self.known_modules:
                self.closure_errors.append(
                    f"{self.source_module}:{node.lineno}:"
                    f"unresolved dynamic package import: {target}"
                )
                return
            self.references.append(
                _ImportReference(target, self.type_checking_depth > 0)
            )
            return
        if _is_allowed_lazy_package_import(
            self.source_module,
            self.function_stack,
            node,
        ):
            return
        self.closure_errors.append(
            f"{self.source_module}:{node.lineno}:non-literal dynamic package import"
        )

    def _visit_package_getattr(self, node: ast.Call) -> None:
        if (
            not isinstance(node.func, ast.Name)
            or node.func.id != "getattr"
            or len(node.args) < 2
        ):
            return
        package_target = self._package_object_target(node.args[0])
        if package_target is None:
            return
        attribute_node = node.args[1]
        if isinstance(attribute_node, ast.Constant) and isinstance(
            attribute_node.value, str
        ):
            self._record_package_attribute(
                package_target,
                attribute_node.value,
                lineno=node.lineno,
            )
            return
        if self.type_checking_depth == 0:
            self.closure_errors.append(
                f"{self.source_module}:{node.lineno}:non-literal package attribute"
            )

    def _record_package_attribute(
        self,
        package_target: str,
        attribute: str,
        *,
        lineno: int,
    ) -> None:
        candidate = f"{package_target}.{attribute}"
        if candidate in self.known_modules:
            self.references.append(
                _ImportReference(candidate, self.type_checking_depth > 0)
            )
        elif self.type_checking_depth == 0:
            self.closure_errors.append(
                f"{self.source_module}:{lineno}:unresolved package attribute: {candidate}"
            )

    def _package_object_target(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.package_object_names.get(node.id)
        if isinstance(node, ast.Attribute):
            parent = self._package_object_target(node.value)
            candidate = None if parent is None else f"{parent}.{node.attr}"
            if candidate in _PROJECTED_PACKAGE_ROOTS:
                return candidate
        return None


def classify_edge(
    *,
    source: str,
    target: str,
    under_type_checking: bool,
    study_owned: frozenset[str],
) -> EdgeKind:
    """Classify one repository import by the responsibility that owns it."""

    del target
    if under_type_checking:
        return "type_checking"
    if source in study_owned:
        return "direct"
    return "runtime_transitive"


def build_study_implementation_projection(
    protocol: StudyProtocolV2,
    *,
    repo_root: Path = PROJECT_ROOT,
) -> tuple[ProjectionEntry, ...]:
    """Hash the exact sorted, tracked, repository-contained projection."""

    root = _verified_repo_root(repo_root)
    entries, _ = _snapshot_study_implementation_projection(protocol, root=root)
    return entries


def _snapshot_study_implementation_projection(
    protocol: StudyProtocolV2,
    *,
    root: Path,
) -> tuple[tuple[ProjectionEntry, ...], Mapping[str, bytes]]:
    declared = protocol.implementation_projection_paths()
    document_paths = protocol.document.get("implementation_projection_paths")
    if not isinstance(document_paths, list) or tuple(document_paths) != declared:
        raise StudyRetentionError("projected paths differ from the protocol document")
    if len(declared) != len(set(declared)):
        raise StudyRetentionError("duplicate projected paths")
    if declared != tuple(sorted(declared)):
        raise StudyRetentionError("projected paths are not sorted")
    missing: list[str] = []
    untracked: list[str] = []
    entries: list[ProjectionEntry] = []
    payloads: dict[str, bytes] = {}
    for relative in declared:
        path = _projected_path(root, relative)
        if not path.exists():
            missing.append(relative)
            continue
        if not _git_tracked(root, relative):
            untracked.append(relative)
            continue
        try:
            payload = read_bounded_bytes(path, maximum=_MAX_PROJECTED_BYTES)
        except StudyArtifactError as exc:
            raise StudyRetentionError(f"projected path is unsafe: {relative}: {exc}") from exc
        entries.append(ProjectionEntry(relative, sha256_bytes(payload)))
        payloads[relative] = payload
    if missing:
        raise StudyRetentionError(f"missing projected paths: {', '.join(sorted(missing))}")
    if untracked:
        raise StudyRetentionError(f"untracked projected paths: {', '.join(sorted(untracked))}")
    return tuple(entries), MappingProxyType(payloads)


def scan_study_dependencies(
    protocol: StudyProtocolV2,
    *,
    repo_root: Path = PROJECT_ROOT,
) -> DependencyScanReport:
    """Parse the projected source graph without importing or executing it."""

    root = _verified_repo_root(repo_root)
    projection, projection_payloads = _snapshot_study_implementation_projection(
        protocol,
        root=root,
    )
    projection_sha256 = canonical_json_hash([entry.as_record() for entry in projection])
    module_to_path = _projected_modules(protocol.implementation_projection_paths())
    known_modules = _repository_modules(root)
    study_owned = frozenset(
        f"manufacturing_vision_studio.e1.{name}"
        for name in protocol.direct_import_allowlist()
    )
    missing_study = study_owned.difference(module_to_path)
    if missing_study:
        raise StudyRetentionError(
            f"study modules missing from projection: {', '.join(sorted(missing_study))}"
        )

    visitors: dict[str, _ImportVisitor] = {}

    def visitor_for(module: str) -> _ImportVisitor:
        existing = visitors.get(module)
        if existing is not None:
            return existing
        relative = module_to_path[module]
        try:
            tree = ast.parse(projection_payloads[relative], filename=relative)
        except (SyntaxError, ValueError) as exc:
            raise StudyRetentionError(f"projected Python could not be parsed: {relative}") from exc
        visitor = _ImportVisitor(source_module=module, known_modules=known_modules)
        visitor.visit(tree)
        visitors[module] = visitor
        return visitor

    direct_actual: dict[str, set[str]] = {
        name: set() for name in protocol.direct_import_allowlist()
    }
    edges: set[DependencyEdge] = set()
    runtime_graph: dict[str, set[str]] = {}
    protected: list[str] = []
    forbidden_calls: list[str] = []
    closure_errors: list[str] = []
    queue = deque(sorted(study_owned))
    visited: set[str] = set()
    while queue:
        source = queue.popleft()
        if source in visited:
            continue
        visited.add(source)
        source_visitor = visitor_for(source)
        if source in study_owned:
            protected.extend(source_visitor.protected)
            forbidden_calls.extend(source_visitor.study_forbidden_calls)
        forbidden_calls.extend(source_visitor.forbidden_calls)
        closure_errors.extend(source_visitor.closure_errors)
        runtime_targets = runtime_graph.setdefault(source, set())
        for package in _package_initializers(source, known_modules):
            kind = classify_edge(
                source=source,
                target=package,
                under_type_checking=False,
                study_owned=study_owned,
            )
            edges.add(DependencyEdge(source, package, kind))
            runtime_targets.add(package)
            queue.append(package)
        for reference in source_visitor.references:
            if reference.target not in module_to_path:
                raise StudyRetentionError(
                    f"unprojected repository import: {source} -> {reference.target}"
                )
            kind = classify_edge(
                source=source,
                target=reference.target,
                under_type_checking=reference.type_checking,
                study_owned=study_owned,
            )
            edges.add(DependencyEdge(source, reference.target, kind))
            if not reference.type_checking:
                runtime_targets.add(reference.target)
                if not _has_forbidden_runtime_prefix(reference.target):
                    queue.append(reference.target)
            if (
                source in study_owned
                and not reference.type_checking
                and reference.target not in study_owned
                and reference.target
                not in {"manufacturing_vision_studio", "manufacturing_vision_studio.e1"}
            ):
                direct_actual[source.rsplit(".", 1)[-1]].add(reference.target)

    if closure_errors:
        raise StudyRetentionError(sorted(closure_errors)[0])
    if protected:
        raise StudyRetentionError(
            f"protected scope reference: {', '.join(sorted(protected))}"
        )
    if forbidden_calls:
        raise StudyRetentionError(sorted(forbidden_calls)[0])
    forbidden_direct = tuple(
        sorted(
            (
                edge
                for edge in edges
                if edge.kind == "direct" and edge.target in FORBIDDEN_DIRECT
            ),
            key=_edge_key,
        )
    )
    if forbidden_direct:
        first = forbidden_direct[0]
        raise StudyRetentionError(
            f"forbidden direct import: {first.source} -> {first.target}"
        )
    for name, expected in protocol.direct_import_allowlist().items():
        actual = tuple(sorted(direct_actual[name]))
        if actual != expected:
            raise StudyRetentionError(
                f"direct import allowlist mismatch for {name}: expected {expected}, got {actual}"
            )
    forbidden_reachable = _forbidden_runtime_reachability(runtime_graph)
    if forbidden_reachable:
        raise StudyRetentionError(
            f"forbidden performance closure: {', '.join(forbidden_reachable)}"
        )
    allowlist = tuple(
        (name, tuple(imports))
        for name, imports in sorted(protocol.direct_import_allowlist().items())
    )
    return DependencyScanReport(
        edges=tuple(sorted(edges, key=_edge_key)),
        forbidden_direct_edges=(),
        protected_scope_references=(),
        projection_sha256=projection_sha256,
        direct_import_allowlist=allowlist,
    )


def verify_historical_hold(
    protocol: StudyProtocolV2,
    *,
    repo_root: Path = PROJECT_ROOT,
) -> HistoricalHoldAudit:
    """Independently verify the immutable selection HOLD and v1 history."""

    root = _verified_repo_root(repo_root)
    selection_path = root / "configs/evaluation/e1-v2-candidate-selection.json"
    schema_path = root / "schemas/e1-candidate-selection.v2.json"
    try:
        payload = read_bounded_bytes(selection_path, maximum=_MAX_INPUT_BYTES)
        document = load_strict_json_object(payload)
        _validate_external_schema(document, schema_path)
        verify_self_hash(document)
    except StudyArtifactError as exc:
        raise StudyRetentionError(f"historical selection is invalid: {exc}") from exc
    raw_sha256 = sha256_bytes(payload)
    record_sha256 = _required_hash(document, "record_sha256")
    if raw_sha256 != protocol.source_hashes.get("selection_raw_sha256"):
        raise StudyRetentionError("historical selection raw hash does not match protocol")
    if record_sha256 != protocol.source_hashes.get("selection_record_sha256"):
        raise StudyRetentionError("historical selection self-hash does not match protocol")
    if document.get("outcome") != "HOLD" or document.get("selected_candidate_id") is not None:
        raise StudyRetentionError("historical selection is not HOLD/null")
    try:
        history = verify_e1_v1_history()
    except Exception as exc:
        raise StudyRetentionError(f"v1 historical HOLD verification failed: {exc}") from exc
    if history.get("verdict") != "HOLD" or history.get("artifact_count") != 9:
        raise StudyRetentionError("v1 history must verify HOLD with all nine artifacts")
    return HistoricalHoldAudit(
        selection_raw_sha256=raw_sha256,
        selection_record_sha256=record_sha256,
        outcome="HOLD",
        selected_candidate_id=None,
        v1_history_outcome="HOLD",
        v1_history_artifact_count=9,
    )


def verify_implementation_validation(
    protocol: StudyProtocolV2,
    store: StudyArtifactStore,
    *,
    repo_root: Path = PROJECT_ROOT,
) -> VerifiedImplementationValidation:
    """Read and semantically verify Task 7's immutable validation evidence."""

    root = _verified_repo_root(repo_root)
    _require_store_root(protocol, store)
    payload, document = _verified_store_document(
        store,
        _IMPLEMENTATION_VALIDATION_PATH,
        expected_record_type="implementation_validation",
    )
    _verify_common_envelope(protocol, document, root=root)
    if document.get("upstream_artifacts") != []:
        raise StudyRetentionError("implementation validation must have no upstream artifacts")
    execution_commit = _required_sha1(document, "execution_commit")
    _require_git_commit(root, execution_commit, label="validation execution commit")
    projection = build_study_implementation_projection(protocol, repo_root=root)
    projection_sha256 = canonical_json_hash([entry.as_record() for entry in projection])
    if document.get("implementation_projection_sha256") != projection_sha256:
        raise StudyRetentionError("implementation projection for validation does not match")
    raw_payload = document.get("payload")
    if not isinstance(raw_payload, dict):
        raise StudyRetentionError("implementation validation payload is invalid")
    validation_payload = cast(dict[str, Any], raw_payload)
    if validation_payload.get("worktree_clean") is not True:
        raise StudyRetentionError("implementation validation did not record a clean worktree")
    commands = _verify_validation_commands(validation_payload.get("commands"))
    first, second = _verify_determinism(validation_payload.get("determinism_control"))
    controls = _verify_not_applicable_controls(
        validation_payload.get("not_applicable_controls")
    )
    if validation_payload.get("passed") is not True:
        raise StudyRetentionError("implementation validation did not pass")
    record_sha256 = _required_hash(document, "record_sha256")
    return VerifiedImplementationValidation(
        base_commit=protocol.base_commit,
        execution_commit=execution_commit,
        protocol_sha256=protocol.configuration_sha256,
        artifact_root=protocol.artifact_root.as_posix(),
        artifact_schema_sha256=_required_hash(document, "artifact_schema_sha256"),
        implementation_projection_sha256=projection_sha256,
        upstream_artifacts=(),
        worktree_clean=True,
        commands=commands,
        first_projection=MappingProxyType(first),
        second_projection=MappingProxyType(second),
        not_applicable_controls=controls,
        passed=True,
        raw_sha256=sha256_bytes(payload),
        record_sha256=record_sha256,
    )


def run_retention_audit(
    protocol: StudyProtocolV2,
    store: StudyArtifactStore,
    *,
    execution_commit: str,
    repo_root: Path = PROJECT_ROOT,
) -> RetentionAudit:
    """Preflight, capture, and publish the one-time Phase 0 audit."""

    root = _verified_repo_root(repo_root)
    _require_store_root(protocol, store)
    validation = verify_implementation_validation(protocol, store, repo_root=root)
    if validation.execution_commit != execution_commit:
        raise StudyRetentionError("retention execution commit does not match validation")
    history = verify_historical_hold(protocol, repo_root=root)
    projection = build_study_implementation_projection(protocol, repo_root=root)
    dependencies = scan_study_dependencies(protocol, repo_root=root)
    prepared = _prepare_retained_inputs(protocol, root=root)
    _require_unpublished_paths(
        store,
        (*(item.destination for item in prepared), _RETENTION_AUDIT_PATH),
    )
    seeds = _verify_seed_disjointness(root)
    evidence_commit = _verify_git_lineage(
        protocol,
        repo_root=root,
        execution_commit=execution_commit,
        evidence_commit=None,
        require_clean=True,
    )
    projection_sha256 = canonical_json_hash([entry.as_record() for entry in projection])
    if projection_sha256 != validation.implementation_projection_sha256:
        raise StudyRetentionError("validation and retention implementation projection differ")
    if dependencies.projection_sha256 != projection_sha256:
        raise StudyRetentionError("dependency projection does not match implementation projection")
    copied = _publish_retained_inputs(store, prepared)
    upstream = (
        UpstreamArtifact(
            path=_IMPLEMENTATION_VALIDATION_PATH,
            raw_sha256=validation.raw_sha256,
            record_sha256=validation.record_sha256,
        ),
    )
    audit = RetentionAudit(
        base_commit=protocol.base_commit,
        execution_commit=execution_commit,
        evidence_commit=evidence_commit,
        protocol_sha256=protocol.configuration_sha256,
        artifact_root=protocol.artifact_root.as_posix(),
        artifact_schema_sha256=_artifact_schema_sha256(root),
        implementation_projection_sha256=projection_sha256,
        upstream_artifacts=upstream,
        history=history,
        retained_inputs=copied,
        implementation_projection=projection,
        dependency_report=dependencies,
        seed_disjointness=seeds,
        classifications=_fixed_classifications(),
        passed=True,
    )
    try:
        published = store.publish_json(_RETENTION_AUDIT_PATH, audit.as_record())
    except StudyArtifactError as exc:
        raise StudyRetentionError(f"retention audit could not be published: {exc}") from exc
    if published.record_sha256 is None:
        raise StudyRetentionError("published retention audit lacks a self-hash")
    if published.record_sha256 != audit.record_sha256:
        raise StudyRetentionError("published retention audit self-hash changed")
    return audit


def verify_retention_audit(
    protocol: StudyProtocolV2,
    store: StudyArtifactStore,
    *,
    repo_root: Path = PROJECT_ROOT,
) -> RetentionAudit:
    """Recompute every portable, projection, upstream, and git binding."""

    root = _verified_repo_root(repo_root)
    _require_store_root(protocol, store)
    _, document = _verified_store_document(
        store,
        _RETENTION_AUDIT_PATH,
        expected_record_type="retention_audit",
    )
    _verify_common_envelope(protocol, document, root=root)
    execution_commit = _required_sha1(document, "execution_commit")
    evidence_commit = _required_sha1(document, "evidence_commit")
    validation = verify_implementation_validation(protocol, store, repo_root=root)
    upstream = _single_upstream(document)
    if upstream.raw_sha256 != validation.raw_sha256:
        raise StudyRetentionError("retention upstream raw hash does not match validation")
    if upstream.record_sha256 != validation.record_sha256:
        raise StudyRetentionError("retention upstream self-hash does not match validation")
    if execution_commit != validation.execution_commit:
        raise StudyRetentionError("retention execution commit does not match validation")
    projection = build_study_implementation_projection(protocol, repo_root=root)
    projection_sha256 = canonical_json_hash([entry.as_record() for entry in projection])
    raw_payload = document.get("payload")
    if not isinstance(raw_payload, dict):
        raise StudyRetentionError("retention payload is invalid")
    retention_payload = cast(dict[str, Any], raw_payload)
    if retention_payload.get("implementation_projection") != [
        entry.as_record() for entry in projection
    ]:
        raise StudyRetentionError("retention implementation projection changed")
    if document.get("implementation_projection_sha256") != projection_sha256:
        raise StudyRetentionError("retention implementation projection hash changed")
    history = verify_historical_hold(protocol, repo_root=root)
    retained_inputs = _verify_retained_inputs(protocol, store, root=root)
    dependencies = scan_study_dependencies(protocol, repo_root=root)
    seeds = _verify_seed_disjointness(root)
    classifications = _fixed_classifications()
    _verify_git_lineage(
        protocol,
        repo_root=root,
        execution_commit=execution_commit,
        evidence_commit=evidence_commit,
        require_clean=False,
    )
    expected = RetentionAudit(
        base_commit=protocol.base_commit,
        execution_commit=execution_commit,
        evidence_commit=evidence_commit,
        protocol_sha256=protocol.configuration_sha256,
        artifact_root=protocol.artifact_root.as_posix(),
        artifact_schema_sha256=_artifact_schema_sha256(root),
        implementation_projection_sha256=projection_sha256,
        upstream_artifacts=(upstream,),
        history=history,
        retained_inputs=retained_inputs,
        implementation_projection=projection,
        dependency_report=dependencies,
        seed_disjointness=seeds,
        classifications=classifications,
        passed=True,
    )
    if expected.record_sha256 != _required_hash(document, "record_sha256"):
        raise StudyRetentionError("retention audit self-hash does not match recomputation")
    if expected.as_record() != document:
        raise StudyRetentionError("retention audit semantic record does not match recomputation")
    return expected


def _verified_repo_root(repo_root: Path) -> Path:
    root = Path(os.path.abspath(os.fspath(repo_root.expanduser())))
    resolved = _run_git(root, "rev-parse", "--show-toplevel")
    if Path(resolved).resolve() != root.resolve():
        raise StudyRetentionError("repository root identity does not match")
    return root


def _projected_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise StudyRetentionError("projected path is invalid")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise StudyRetentionError(f"projected path escapes repository: {relative}")
    candidate = root.joinpath(*pure.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise StudyRetentionError(f"projected path escapes repository: {relative}") from exc
    return candidate


def _git_tracked(root: Path, relative: str) -> bool:
    completed = subprocess.run(
        ("git", "-C", os.fspath(root), "ls-files", "--error-unmatch", "--", relative),
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0 and completed.stdout.strip() == relative


def _projected_modules(paths: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    prefix = PurePosixPath("src/manufacturing_vision_studio")
    for relative in paths:
        pure = PurePosixPath(relative)
        if pure.suffix != ".py":
            continue
        try:
            subpath = pure.relative_to(prefix)
        except ValueError:
            continue
        parts = list(subpath.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = parts[-1][:-3]
        module = ".".join(("manufacturing_vision_studio", *parts))
        if module in result:
            raise StudyRetentionError(f"duplicate projected module: {module}")
        result[module] = relative
    return result


def _repository_modules(root: Path) -> frozenset[str]:
    source_root = root / "src/manufacturing_vision_studio"
    modules: set[str] = set()
    if not source_root.is_dir():
        raise StudyRetentionError("repository source package is missing")
    for path in source_root.rglob("*.py"):
        if path.is_symlink():
            continue
        relative = path.relative_to(source_root)
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = parts[-1][:-3]
        modules.add(".".join(("manufacturing_vision_studio", *parts)))
    return frozenset(modules)


def _nearest_known_module(candidate: str, known_modules: frozenset[str]) -> str | None:
    current = candidate
    while current.startswith("manufacturing_vision_studio"):
        if current in known_modules:
            return current
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return None


def _resolve_import_from_base(source: str, module: str | None, level: int) -> str | None:
    if level == 0:
        return module
    package = source.rsplit(".", 1)[0]
    parts = package.split(".")
    if level > len(parts):
        return None
    prefix = parts[: len(parts) - level + 1]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def _is_type_checking_test(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
        and node.attr == "TYPE_CHECKING"
    )


def _is_importlib_target(module: str | None) -> bool:
    return module == "importlib" or (
        module is not None and module.startswith("importlib.")
    )


def _is_allowed_initializer_import_module(
    source_module: str,
    node: ast.ImportFrom,
) -> bool:
    return (
        source_module in _PROJECTED_PACKAGE_ROOTS
        and node.level == 0
        and node.module == "importlib"
        and len(node.names) == 1
        and node.names[0].name == "import_module"
        and node.names[0].asname is None
    )


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _dynamic_import_loader_kind(
    node: ast.expr,
    *,
    importlib_module_names: set[str],
    import_module_names: set[str],
) -> _DynamicImportLoaderKind | None:
    if isinstance(node, ast.Name):
        if node.id == "__import__" or node.id in import_module_names:
            return "loader"
        return None
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "import_module"
        and isinstance(node.value, ast.Name)
        and node.value.id in importlib_module_names
    ):
        return "loader"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in importlib_module_names
    ):
        reflected_name = node.args[1]
        if isinstance(reflected_name, ast.Constant) and isinstance(
            reflected_name.value, str
        ):
            if reflected_name.value == "import_module":
                return "loader"
            return None
        return "nonliteral_reflection"
    return None


def _is_package_target(value: str) -> bool:
    return value == "manufacturing_vision_studio" or value.startswith(
        "manufacturing_vision_studio."
    )


def _is_allowed_lazy_package_import(
    source_module: str,
    function_stack: Sequence[str],
    node: ast.Call,
) -> bool:
    return (
        source_module in _PROJECTED_PACKAGE_ROOTS
        and tuple(function_stack) == ("__getattr__",)
        and isinstance(node.func, ast.Name)
        and node.func.id == "import_module"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "module_name"
        and not node.keywords
    )


def _is_allowed_development_provider_plan(
    source_module: str,
    class_stack: Sequence[str],
    node: ast.Call,
) -> bool:
    if (
        source_module != "manufacturing_vision_studio.e1.study_truth_v2"
        or tuple(class_stack) != ("DevelopmentCorpusProvider",)
        or not isinstance(node.func, ast.Attribute)
        or not isinstance(node.func.value, ast.Attribute)
        or not isinstance(node.func.value.value, ast.Name)
        or node.func.value.value.id != "self"
        or node.func.value.attr != "_generator"
        or len(node.args) != 1
        or node.keywords
    ):
        return False
    argument = node.args[0]
    return (
        isinstance(argument, ast.Attribute)
        and isinstance(argument.value, ast.Name)
        and argument.value.id == "EvaluationScope"
        and argument.attr == "DEVELOPMENT"
    )


def _is_allowed_legacy_v1_plan(source_module: str, node: ast.Call) -> bool:
    if source_module != "manufacturing_vision_studio.e1.study_truth_v2":
        return False
    if (
        not isinstance(node.func, ast.Attribute)
        or not isinstance(node.func.value, ast.Name)
        or node.func.value.id != "v1_generator"
        or len(node.args) != 1
        or node.keywords
    ):
        return False
    argument = node.args[0]
    return (
        isinstance(argument, ast.Attribute)
        and isinstance(argument.value, ast.Name)
        and argument.value.id == "DatasetProfile"
        and argument.attr == "FULL"
    )


def _package_initializers(module: str, known_modules: frozenset[str]) -> tuple[str, ...]:
    parts = module.split(".")[:-1]
    packages: list[str] = []
    while parts:
        candidate = ".".join(parts)
        if candidate in known_modules:
            packages.append(candidate)
        parts.pop()
    return tuple(sorted(packages))


def _edge_key(edge: DependencyEdge) -> tuple[str, str, str]:
    return edge.source, edge.target, edge.kind


def _forbidden_runtime_reachability(graph: Mapping[str, set[str]]) -> tuple[str, ...]:
    forbidden: set[str] = set()
    queue = deque(PERFORMANCE_ROOTS)
    visited: set[str] = set()
    while queue:
        source = queue.popleft()
        if source in visited:
            continue
        visited.add(source)
        if _has_forbidden_runtime_prefix(source):
            forbidden.add(source)
        queue.extend(sorted(graph.get(source, set())))
    return tuple(sorted(forbidden))


def _has_forbidden_runtime_prefix(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in _FORBIDDEN_RUNTIME_PREFIXES
    )


def _validate_external_schema(document: Mapping[str, object], schema_path: Path) -> None:
    try:
        schema_payload = read_bounded_bytes(schema_path, maximum=_MAX_INPUT_BYTES)
        schema = load_strict_json_object(schema_payload)
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(document)),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
    except StudyArtifactError:
        raise
    except Exception as exc:
        raise StudyArtifactError(f"external schema is invalid: {exc}") from exc
    if errors:
        raise StudyArtifactError(f"external record failed schema validation: {errors[0].message}")


def _verified_store_document(
    store: StudyArtifactStore,
    relative_path: str,
    *,
    expected_record_type: str,
) -> tuple[bytes, dict[str, object]]:
    try:
        payload = store.read_bytes(relative_path)
        document = load_strict_json_object(payload)
        if canonical_json_bytes(document) != payload:
            raise StudyArtifactError("artifact JSON bytes are not canonical")
        verify_self_hash(document)
        validate_study_schema(document)
    except (StudyArtifactError, TypeError, ValueError, OverflowError) as exc:
        raise StudyRetentionError(f"{relative_path} is invalid: {exc}") from exc
    if document.get("record_type") != expected_record_type:
        raise StudyRetentionError(f"{relative_path} record type does not match")
    return payload, cast(dict[str, object], document)


def _verify_common_envelope(
    protocol: StudyProtocolV2,
    document: Mapping[str, object],
    *,
    root: Path,
) -> None:
    for envelope_field in (
        "protocol_sha256",
        "artifact_schema_sha256",
        "implementation_projection_sha256",
        "record_sha256",
    ):
        _require_real_hash(document.get(envelope_field), field=envelope_field)
    expected = {
        "schema_version": "1.0.0",
        "study_id": _STUDY_ID,
        "development_only": True,
        "selection_eligible": False,
        "release_claim_allowed": False,
        "base_commit": protocol.base_commit,
        "protocol_sha256": protocol.configuration_sha256,
        "artifact_root": protocol.artifact_root.as_posix(),
        "artifact_schema_sha256": _artifact_schema_sha256(root),
    }
    for envelope_field, value in expected.items():
        if document.get(envelope_field) != value:
            raise StudyRetentionError(
                f"artifact envelope {envelope_field} does not match protocol"
            )


def _artifact_schema_sha256(root: Path) -> str:
    path = root / "schemas/e1-feasibility-study-artifact.v1.json"
    try:
        return sha256_bytes(read_bounded_bytes(path, maximum=_MAX_INPUT_BYTES))
    except StudyArtifactError as exc:
        raise StudyRetentionError(f"artifact schema cannot be hashed: {exc}") from exc


def _verify_validation_commands(value: object) -> tuple[ValidationCommand, ...]:
    if not isinstance(value, list) or len(value) != len(IMPLEMENTATION_VALIDATION_COMMANDS):
        raise StudyRetentionError("implementation validation commands are incomplete")
    commands: list[ValidationCommand] = []
    for ordinal, ((expected_name, expected_argv), raw) in enumerate(
        zip(IMPLEMENTATION_VALIDATION_COMMANDS, value, strict=True)
    ):
        if not isinstance(raw, dict):
            raise StudyRetentionError("implementation validation command is invalid")
        command = cast(dict[str, object], raw)
        if command.get("name") != expected_name or command.get("argv") != list(expected_argv):
            raise StudyRetentionError(
                f"implementation validation command {ordinal} does not match"
            )
        if command.get("exit_code") != 0:
            raise StudyRetentionError("implementation validation command did not pass")
        stdout_sha256 = _required_hash(command, "stdout_sha256")
        stderr_sha256 = _required_hash(command, "stderr_sha256")
        started = _required_string(command, "started_at_utc")
        ended = _required_string(command, "ended_at_utc")
        if _parse_utc(ended) < _parse_utc(started):
            raise StudyRetentionError("implementation validation command time range is invalid")
        commands.append(
            ValidationCommand(
                name=expected_name,
                argv=expected_argv,
                exit_code=0,
                stdout_sha256=stdout_sha256,
                stderr_sha256=stderr_sha256,
                started_at_utc=started,
                ended_at_utc=ended,
            )
        )
    return tuple(commands)


def _verify_determinism(value: object) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(value, dict):
        raise StudyRetentionError("implementation determinism control is invalid")
    control = cast(dict[str, object], value)
    first = _mode_projection(control.get("first_projection"))
    second = _mode_projection(control.get("second_projection"))
    if control.get("passed") is not True or first != second:
        raise StudyRetentionError("implementation determinism projections do not match")
    return first, second


def _mode_projection(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(_MODES):
        raise StudyRetentionError("determinism mode projection is invalid")
    projected = cast(dict[str, object], value)
    return {mode: _required_hash(projected, mode) for mode in _MODES}


def _verify_not_applicable_controls(value: object) -> tuple[StudyGateRecord, ...]:
    if not isinstance(value, list) or len(value) != len(NOT_APPLICABLE_CONTROLS):
        raise StudyRetentionError("NOT_APPLICABLE controls are incomplete")
    controls: list[StudyGateRecord] = []
    for (expected_name, expected_reason), raw in zip(
        NOT_APPLICABLE_CONTROLS, value, strict=True
    ):
        if not isinstance(raw, dict):
            raise StudyRetentionError("NOT_APPLICABLE control is invalid")
        item = cast(dict[str, object], raw)
        expected = {
            "name": expected_name,
            "status": "NOT_APPLICABLE",
            "numerator": None,
            "denominator": None,
            "observed": None,
            "operator": None,
            "threshold": None,
            "reason": expected_reason,
        }
        if item != expected:
            raise StudyRetentionError(f"NOT_APPLICABLE control changed: {expected_name}")
        controls.append(
            StudyGateRecord(
                name=expected_name,
                status="NOT_APPLICABLE",
                numerator=None,
                denominator=None,
                observed=None,
                operator=None,
                threshold=None,
                reason=expected_reason,
            )
        )
    return tuple(controls)


def _parse_utc(value: str) -> datetime:
    if not _RFC3339_UTC.fullmatch(value):
        raise StudyRetentionError("implementation validation timestamp is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise StudyRetentionError("implementation validation timestamp is invalid") from exc
    if parsed.tzinfo != UTC:
        raise StudyRetentionError("implementation validation timestamp is not UTC")
    return parsed


def _prepare_retained_inputs(
    protocol: StudyProtocolV2,
    *,
    root: Path,
) -> tuple[_PreparedInput, ...]:
    prepared: list[_PreparedInput] = []
    failures: list[str] = []
    for name, source_relative, destination, hash_field in RETAINED_INPUTS:
        source = _projected_path(root, source_relative)
        try:
            payload = read_bounded_bytes(source, maximum=_MAX_INPUT_BYTES)
        except StudyArtifactError as exc:
            failures.append(f"{name}: {exc}")
            continue
        source_sha256 = sha256_bytes(payload)
        if source_sha256 != protocol.source_hashes.get(hash_field):
            failures.append(f"{name}: source hash does not match protocol")
            continue
        prepared.append(_PreparedInput(name, destination, payload, source_sha256))
    if failures:
        raise StudyRetentionError(f"retained input preflight failed: {'; '.join(failures)}")
    return tuple(prepared)


def _require_unpublished_paths(
    store: StudyArtifactStore,
    relative_paths: Sequence[str],
) -> None:
    existing: list[str] = []
    for relative_path in relative_paths:
        try:
            store.read_bytes(relative_path)
        except StudyArtifactError as exc:
            if str(exc) in {"artifact is missing", "artifact parent is missing"}:
                continue
            raise StudyRetentionError(
                f"retention destination preflight failed: {relative_path}: {exc}"
            ) from exc
        existing.append(relative_path)
    if existing:
        raise StudyRetentionError(
            f"retention destination already exists: {', '.join(existing)}"
        )


def _publish_retained_inputs(
    store: StudyArtifactStore,
    prepared: Sequence[_PreparedInput],
) -> tuple[RetainedInputRecord, ...]:
    copied: list[RetainedInputRecord] = []
    for item in prepared:
        try:
            published = store.publish_bytes(
                item.destination,
                item.payload,
                media_type="application/json"
                if item.destination.endswith(".json")
                else "text/markdown",
            )
            copied_payload = store.read_bytes(item.destination)
        except StudyArtifactError as exc:
            raise StudyRetentionError(f"retained copy publication failed: {exc}") from exc
        copied_sha256 = sha256_bytes(copied_payload)
        if (
            copied_payload != item.payload
            or copied_sha256 != item.source_sha256
            or published.sha256 != item.source_sha256
        ):
            raise StudyRetentionError(f"retained copy differs from source: {item.name}")
        copied.append(
            RetainedInputRecord(
                name=item.name,
                path=item.destination,
                source_sha256=item.source_sha256,
                copied_sha256=copied_sha256,
                byte_size=len(item.payload),
            )
        )
    return tuple(copied)


def _verify_retained_inputs(
    protocol: StudyProtocolV2,
    store: StudyArtifactStore,
    *,
    root: Path,
) -> tuple[RetainedInputRecord, ...]:
    prepared = _prepare_retained_inputs(protocol, root=root)
    verified: list[RetainedInputRecord] = []
    for item in prepared:
        try:
            copied = store.read_bytes(item.destination)
        except StudyArtifactError as exc:
            raise StudyRetentionError(f"retained copy is invalid: {item.name}: {exc}") from exc
        copied_sha256 = sha256_bytes(copied)
        if copied != item.payload or copied_sha256 != item.source_sha256:
            raise StudyRetentionError(f"retained copy hash or bytes changed: {item.name}")
        verified.append(
            RetainedInputRecord(
                name=item.name,
                path=item.destination,
                source_sha256=item.source_sha256,
                copied_sha256=copied_sha256,
                byte_size=len(item.payload),
            )
        )
    return tuple(verified)


def _verify_seed_disjointness(root: Path) -> SeedDisjointnessAudit:
    path = root / "configs/evaluation/e1-v2.json"
    try:
        document = load_strict_json_object(
            read_bounded_bytes(path, maximum=_MAX_INPUT_BYTES)
        )
    except StudyArtifactError as exc:
        raise StudyRetentionError(f"v2 seed configuration is invalid: {exc}") from exc
    try:
        generator = _mapping(document, "generator")
        blocks = _mapping(generator, "seed_blocks")
    except StudyRetentionError:
        raise
    expected_scopes = ("development", "smoke", "calibration", "release_test")
    expected_groups = ("clean", "nuisance", "defect", "trust_boundary")
    if tuple(blocks) != expected_scopes:
        raise StudyRetentionError("declared v2 seed scopes changed")
    declared: list[int] = []
    for scope_name in expected_scopes:
        scope = _mapping(blocks, scope_name)
        if tuple(scope) != expected_groups:
            raise StudyRetentionError(f"declared v2 seed groups changed for {scope_name}")
        for group_name in expected_groups:
            block = _mapping(scope, group_name)
            start = block.get("start")
            count = block.get("count")
            if (
                isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or start < 0
                or count < 1
            ):
                raise StudyRetentionError("declared v2 seed block is invalid")
            declared.extend(range(start, start + count))
    if len(declared) != 528 or len(set(declared)) != 528:
        raise StudyRetentionError("declared v2 seed count or uniqueness changed")
    diagnostic = set(range(800000, 800108))
    overlap = tuple(sorted(diagnostic.intersection(declared)))
    if overlap:
        raise StudyRetentionError("diagnostic seeds overlap declared evaluation seeds")
    return SeedDisjointnessAudit(
        diagnostic_seed_start=800000,
        diagnostic_seed_end=800107,
        diagnostic_seed_count=108,
        declared_evaluation_seed_count=528,
        overlap_count=0,
        overlap_seeds=(),
    )


def _fixed_classifications() -> RetentionClassifications:
    return RetentionClassifications(_RETAIN, _ISOLATE, _RE_REVIEW)


def _single_upstream(document: Mapping[str, object]) -> UpstreamArtifact:
    value = document.get("upstream_artifacts")
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise StudyRetentionError("retention must bind exactly one upstream artifact")
    item = cast(dict[str, object], value[0])
    if item.get("path") != _IMPLEMENTATION_VALIDATION_PATH:
        raise StudyRetentionError("retention upstream path is invalid")
    return UpstreamArtifact(
        path=_IMPLEMENTATION_VALIDATION_PATH,
        raw_sha256=_required_hash(item, "raw_sha256"),
        record_sha256=_required_hash(item, "record_sha256"),
    )


def _verify_git_lineage(
    protocol: StudyProtocolV2,
    *,
    repo_root: Path,
    execution_commit: str,
    evidence_commit: str | None,
    require_clean: bool,
) -> str:
    _require_git_commit(repo_root, protocol.base_commit, label="study base commit")
    _require_git_commit(repo_root, execution_commit, label="execution commit")
    source_branch = _run_git(
        repo_root,
        "rev-parse",
        "--verify",
        f"refs/heads/{_SOURCE_BRANCH}^{{commit}}",
    )
    if source_branch != protocol.base_commit:
        raise StudyRetentionError("frozen source branch no longer resolves to study base")
    _require_ancestor(repo_root, protocol.base_commit, execution_commit)
    current = _run_git(repo_root, "rev-parse", "HEAD")
    if evidence_commit is None:
        evidence = current
    else:
        _require_git_commit(repo_root, evidence_commit, label="evidence commit")
        _require_ancestor(repo_root, evidence_commit, current)
        evidence = evidence_commit
    _require_ancestor(repo_root, execution_commit, evidence)
    _require_ancestor(repo_root, execution_commit, current)
    artifact_relative = _artifact_relative_path(protocol, repo_root)
    changed = _git_changed_paths(repo_root, execution_commit, current)
    outside = tuple(path for path in changed if not _under_artifact_root(path, artifact_relative))
    if outside:
        raise StudyRetentionError(
            f"git evidence-only lineage contains non-artifact paths: {', '.join(outside)}"
        )
    dirty = _git_status_paths(repo_root)
    if require_clean and dirty:
        raise StudyRetentionError("retention requires a clean evidence-only worktree")
    dirty_outside = tuple(
        path for path in dirty if not _under_artifact_root(path, artifact_relative)
    )
    if dirty_outside:
        raise StudyRetentionError(
            f"git evidence-only lineage has dirty non-artifact paths: {', '.join(dirty_outside)}"
        )
    return evidence


def _artifact_relative_path(protocol: StudyProtocolV2, root: Path) -> str:
    artifact = Path(os.path.abspath(os.fspath(protocol.artifact_root)))
    try:
        relative = artifact.relative_to(root).as_posix()
    except ValueError as exc:
        raise StudyRetentionError("artifact root is outside repository") from exc
    if not relative or relative == ".":
        raise StudyRetentionError("artifact root cannot be repository root")
    return relative


def _under_artifact_root(path: str, artifact_relative: str) -> bool:
    return path == artifact_relative or path.startswith(f"{artifact_relative}/")


def _git_changed_paths(root: Path, older: str, newer: str) -> tuple[str, ...]:
    output = _run_git(root, "diff", "--name-only", "--diff-filter=ACDMRTUXB", older, newer)
    return tuple(sorted(line for line in output.splitlines() if line))


def _git_status_paths(root: Path) -> tuple[str, ...]:
    output = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    paths: set[str] = set()
    for line in output.splitlines():
        if len(line) < 4:
            raise StudyRetentionError("git status output is malformed")
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith('"'):
            raise StudyRetentionError("quoted git status paths are unsupported")
        paths.add(path)
    return tuple(sorted(paths))


def _require_ancestor(root: Path, older: str, newer: str) -> None:
    completed = subprocess.run(
        ("git", "-C", os.fspath(root), "merge-base", "--is-ancestor", older, newer),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise StudyRetentionError(f"git ancestry check failed: {older} is not ancestor of {newer}")


def _require_git_commit(root: Path, commit: str, *, label: str) -> None:
    _require_lower_hex(commit, _SHA1_LENGTH, label)
    resolved = _run_git(root, "rev-parse", "--verify", f"{commit}^{{commit}}")
    if resolved != commit:
        raise StudyRetentionError(f"{label} does not resolve exactly")


def _run_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", os.fspath(root), *args),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise StudyRetentionError(f"git command could not run: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise StudyRetentionError(f"git command failed: {' '.join(args)}: {detail}")
    return completed.stdout.strip()


def _require_store_root(protocol: StudyProtocolV2, store: StudyArtifactStore) -> None:
    if store.root != Path(os.path.abspath(os.fspath(protocol.artifact_root))):
        raise StudyRetentionError("artifact store root does not match protocol")


def _required_hash(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    _require_real_hash(item, field=field)
    return cast(str, item)


def _require_real_hash(value: object, *, field: str) -> None:
    _require_lower_hex(value, _SHA256_LENGTH, field)
    if isinstance(value, str) and len(set(value)) == 1:
        raise StudyRetentionError(f"{field} uses a zero or filler hash")


def _required_sha1(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    _require_lower_hex(item, _SHA1_LENGTH, field)
    return cast(str, item)


def _require_lower_hex(value: object, length: int, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StudyRetentionError(f"{field} is not a lowercase {length}-character SHA")


def _required_string(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise StudyRetentionError(f"{field} must be a non-empty string")
    return item


def _mapping(value: Mapping[str, object], field: str) -> dict[str, object]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise StudyRetentionError(f"{field} must be an object")
    return cast(dict[str, object], item)
