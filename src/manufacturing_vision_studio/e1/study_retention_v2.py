"""Read-only closure checks and immutable Phase 0 retention evidence."""

from __future__ import annotations

import ast
import os
import pwd
import re
import selectors
import signal
import subprocess
import time
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
from manufacturing_vision_studio.e1.protocol_v2 import (
    DEFAULT_V1_HISTORY_INTEGRITY_PATH,
)
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
_GIT_TIMEOUT_SECONDS = 30
_GIT_OUTPUT_LIMIT_BYTES = 1024 * 1024
_STUDY_ID = "e1-feasibility-separability"
_SOURCE_BRANCH = "codex/e1-v2-scale-feature-remediation"
_IMPLEMENTATION_VALIDATION_PATH = "implementation-validation.json"
_RETENTION_AUDIT_PATH = "retention-audit.json"
_MODES = ("NEAREST", "BILINEAR", "BICUBIC")
_V1_HISTORY_RELATIVE_PATH = "configs/evaluation/e1-v1-history-integrity.json"
_V1_HISTORY_ARTIFACT_FIELDS = (
    (
        "configs/evaluation/e1-v1.json",
        (
            ("protocol_id", "mvs-e1"),
            ("protocol_version", "1.3.0"),
            ("status", "frozen_before_test"),
        ),
    ),
    (
        "schemas/e1-case-manifest.v1.json",
        (("$schema", "https://json-schema.org/draft/2020-12/schema"),),
    ),
    (
        "schemas/e1-evaluation-protocol.v1.json",
        (("$schema", "https://json-schema.org/draft/2020-12/schema"),),
    ),
    (
        "schemas/e1-evaluation-result.v1.json",
        (("$schema", "https://json-schema.org/draft/2020-12/schema"),),
    ),
    (
        "schemas/e1-threshold-lock.v1.json",
        (("$schema", "https://json-schema.org/draft/2020-12/schema"),),
    ),
    (
        "docs/evaluation/results/e1-mini-v0.2.0-hold.json",
        (
            ("profile", "mini"),
            ("verdict", "HOLD"),
            ("evaluation_status", "COMPLETED"),
        ),
    ),
    (
        "docs/evaluation/results/e1-full-v0.2.0-hold.json",
        (
            ("profile", "full"),
            ("verdict", "HOLD"),
            ("evaluation_status", "CALIBRATION_HOLD"),
        ),
    ),
    ("docs/releases/v0.2.0/E1_HOLD.md", ()),
    ("docs/releases/v0.1.0/evidence-bundle.zip", ()),
)
_V1_HISTORY_PREFLIGHT = MappingProxyType(
    {
        "parent_branch": "codex/e1-authoritative-mask-nuisance-evaluation-v0.2.0",
        "parent_head": "d7254cf8e09561a085def5cb9c914c31d79b9725",
        "v0_1_tag": "v0.1.0",
        "v0_1_tag_object": "67bd8af8d6bfdbcb5ff2654fd37b797dc7c75f3d",
        "v0_1_commit": "cf7b9ac37d0533f656068199d3275410cf8cc2f8",
        "e1_evaluation_commit": "2f87b885b29c12468effea927279d27424eaa340",
    }
)
_V1_HISTORY_REVISIONS = (
    ("v0.1.0^{tag}", "67bd8af8d6bfdbcb5ff2654fd37b797dc7c75f3d"),
    ("v0.1.0^{commit}", "cf7b9ac37d0533f656068199d3275410cf8cc2f8"),
    (
        "2f87b885b29c12468effea927279d27424eaa340^{commit}",
        "2f87b885b29c12468effea927279d27424eaa340",
    ),
)

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
IMPLEMENTATION_VALIDATION_TIMEOUT_SECONDS = (300, 300, 600, 1800, 600, 900)
_VALIDATION_OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
_SANITIZED_ENVIRONMENT_KEYS = (
    "HOME",
    "PATH",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "TZ",
    "TERM",
    "NO_COLOR",
    "FORCE_COLOR",
    "PYTHONHASHSEED",
    "PYTHONUTF8",
    "PYTHONNOUSERSITE",
    "UV_NO_CONFIG",
    "NPM_CONFIG_USERCONFIG",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
)
_FIXED_SANITIZED_ENVIRONMENT = {
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
VALIDATION_SYSTEM_PATH_SUFFIX = "/usr/bin:/bin:/usr/sbin:/sbin"
_FIXED_VALIDATION_EXECUTABLE_ROOTS = ("/opt/homebrew/bin", "/usr/local/bin")
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


def reviewed_validation_executable_roots() -> tuple[str, ...]:
    """Return the only roots authorized for validation executables."""

    try:
        account_home_value = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError) as exc:
        raise StudyRetentionError("OS account home is unavailable") from exc
    account_home = PurePosixPath(account_home_value)
    if (
        not account_home_value.startswith("/")
        or len(account_home_value) > 4096
        or ":" in account_home_value
        or any(ord(character) < 32 or ord(character) == 127 for character in account_home_value)
        or any(component in {"", ".", ".."} for component in account_home_value.split("/")[1:])
        or not account_home.is_absolute()
        or account_home.as_posix() != account_home_value
    ):
        raise StudyRetentionError("OS account home is invalid")
    roots = (
        (account_home / ".local/bin").as_posix(),
        *_FIXED_VALIDATION_EXECUTABLE_ROOTS,
        *VALIDATION_SYSTEM_PATH_SUFFIX.split(":"),
    )
    if any(
        not root.startswith("/")
        or ":" in root
        or any(ord(character) < 32 or ord(character) == 127 for character in root)
        or PurePosixPath(root).as_posix() != root
        for root in roots
    ):
        raise StudyRetentionError("reviewed executable root is invalid")
    return roots


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
    executable_lookup_path: str
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    started_at_utc: str
    ended_at_utc: str
    cwd: str
    shell: bool
    timeout_seconds: int
    output_limit_bytes: int
    timed_out: bool
    stdout_byte_count: int
    stderr_byte_count: int
    sanitized_environment: Mapping[str, str]


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


@dataclass(frozen=True, slots=True)
class _GitChangeRecord:
    status: str
    score: int | None
    source: str | None
    destination: str

    @property
    def paths(self) -> tuple[str, ...]:
        if self.source is None:
            return (self.destination,)
        return (self.source, self.destination)


@dataclass(frozen=True, slots=True)
class _GitCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


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
    runtime_cycle = _study_owned_runtime_cycle(runtime_graph, study_owned)
    if runtime_cycle:
        raise StudyRetentionError(
            "runtime cycle among study-owned modules: "
            + " -> ".join(runtime_cycle)
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
        history = _verify_e1_v1_history_local(root)
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


def _verify_e1_v1_history_local(root: Path) -> dict[str, object]:
    """Verify the fixed v1 HOLD inventory without ambient protocol seams."""

    try:
        bound_relative = DEFAULT_V1_HISTORY_INTEGRITY_PATH.relative_to(
            PROJECT_ROOT
        ).as_posix()
    except ValueError as exc:
        raise StudyRetentionError("v1 history configuration path is invalid") from exc
    if bound_relative != _V1_HISTORY_RELATIVE_PATH:
        raise StudyRetentionError("v1 history configuration path is not fixed")
    configuration_path = _projected_path(root, _V1_HISTORY_RELATIVE_PATH)
    try:
        configuration_payload = read_bounded_bytes(
            configuration_path,
            maximum=_MAX_INPUT_BYTES,
        )
        document = load_strict_json_object(configuration_payload)
    except (OSError, StudyArtifactError) as exc:
        raise StudyRetentionError(f"v1 history configuration is invalid: {exc}") from exc
    if document.get("schema_version") != "1.0.0":
        raise StudyRetentionError("v1 history schema version is invalid")
    raw_artifacts = document.get("artifacts")
    if not isinstance(raw_artifacts, list) or len(raw_artifacts) != len(
        _V1_HISTORY_ARTIFACT_FIELDS
    ):
        raise StudyRetentionError("v1 history must contain exactly nine artifacts")
    artifacts = cast(list[object], raw_artifacts)
    for ordinal, ((fixed_path, fixed_fields), raw_artifact) in enumerate(
        zip(_V1_HISTORY_ARTIFACT_FIELDS, artifacts, strict=True)
    ):
        if not isinstance(raw_artifact, dict):
            raise StudyRetentionError(f"v1 history artifact {ordinal} is invalid")
        artifact = cast(dict[str, object], raw_artifact)
        expected_keys = {"path", "sha256"}
        if fixed_fields:
            expected_keys.add("expected_fields")
        if set(artifact) != expected_keys or artifact.get("path") != fixed_path:
            raise StudyRetentionError(f"v1 history artifact {ordinal} binding is invalid")
        expected_sha = artifact.get("sha256")
        _require_lower_hex(expected_sha, _SHA256_LENGTH, f"v1 history {fixed_path} sha256")
        expected_fields = dict(fixed_fields)
        if artifact.get("expected_fields", {}) != expected_fields:
            raise StudyRetentionError(f"v1 history expected fields changed: {fixed_path}")
        artifact_path = _projected_path(root, fixed_path)
        try:
            payload = read_bounded_bytes(artifact_path, maximum=_MAX_INPUT_BYTES)
        except (OSError, StudyArtifactError) as exc:
            raise StudyRetentionError(
                f"v1 history artifact cannot be read safely: {fixed_path}: {exc}"
            ) from exc
        if sha256_bytes(payload) != expected_sha:
            raise StudyRetentionError(f"v1 history hash mismatch: {fixed_path}")
        if expected_fields:
            try:
                parsed = load_strict_json_object(payload)
            except StudyArtifactError as exc:
                raise StudyRetentionError(
                    f"v1 history identity document is invalid: {fixed_path}: {exc}"
                ) from exc
            if any(parsed.get(key) != value for key, value in expected_fields.items()):
                raise StudyRetentionError(f"v1 history identity mismatch: {fixed_path}")
    preflight = document.get("preflight")
    if not isinstance(preflight, dict) or preflight != dict(_V1_HISTORY_PREFLIGHT):
        raise StudyRetentionError("v1 history preflight identity is invalid")
    for revision, expected_identity in _V1_HISTORY_REVISIONS:
        if _run_git(root, "rev-parse", revision) != expected_identity:
            raise StudyRetentionError(
                f"v1 history Git identity does not resolve: {revision}"
            )
    return {"verdict": "HOLD", "artifact_count": len(artifacts)}


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
        artifact_root=protocol.artifact_root_identity,
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
        artifact_root=protocol.artifact_root_identity,
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
        allow_retained_input_copies=True,
    )
    expected = RetentionAudit(
        base_commit=protocol.base_commit,
        execution_commit=execution_commit,
        evidence_commit=evidence_commit,
        protocol_sha256=protocol.configuration_sha256,
        artifact_root=protocol.artifact_root_identity,
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
    completed = _run_git_command(
        root,
        "ls-files",
        "--error-unmatch",
        "--",
        relative,
        accepted_returncodes=(0, 1),
    )
    return completed.returncode == 0 and os.fsdecode(completed.stdout).strip() == relative


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


def _study_owned_runtime_cycle(
    graph: Mapping[str, set[str]],
    study_owned: frozenset[str],
) -> tuple[str, ...]:
    state: dict[str, int] = {}
    stack: list[str] = []
    stack_positions: dict[str, int] = {}

    def visit(source: str) -> tuple[str, ...]:
        state[source] = 1
        stack_positions[source] = len(stack)
        stack.append(source)
        for target in sorted(graph.get(source, set()).intersection(study_owned)):
            target_state = state.get(target, 0)
            if target_state == 0:
                cycle = visit(target)
                if cycle:
                    return cycle
            elif target_state == 1:
                return tuple((*stack[stack_positions[target] :], target))
        stack.pop()
        stack_positions.pop(source)
        state[source] = 2
        return ()

    for source in sorted(study_owned):
        if state.get(source, 0) == 0:
            cycle = visit(source)
            if cycle:
                return cycle
    return ()


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
        "artifact_root": protocol.artifact_root_identity,
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


def _contains_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _verify_sanitized_environment(
    value: object,
    *,
    expected_path: str,
) -> Mapping[str, str]:
    if not isinstance(value, dict) or set(value) != set(_SANITIZED_ENVIRONMENT_KEYS):
        raise StudyRetentionError("implementation validation command environment is invalid")
    raw = cast(dict[str, object], value)
    environment: dict[str, str] = {}
    for key in _SANITIZED_ENVIRONMENT_KEYS:
        item = raw[key]
        if not isinstance(item, str):
            raise StudyRetentionError("implementation validation command environment is invalid")
        environment[key] = item
    for key, expected in _FIXED_SANITIZED_ENVIRONMENT.items():
        if environment[key] != expected:
            raise StudyRetentionError("implementation validation command environment is poisoned")
    for key in ("HOME", "PATH", "TMPDIR"):
        item = environment[key]
        if not item or _contains_control_character(item):
            raise StudyRetentionError("implementation validation command environment is unsafe")
    if not PurePosixPath(environment["HOME"]).is_absolute() or not PurePosixPath(
        environment["TMPDIR"]
    ).is_absolute():
        raise StudyRetentionError("implementation validation command environment path is relative")
    if environment["PATH"] != expected_path:
        raise StudyRetentionError("implementation validation command environment PATH is invalid")
    return MappingProxyType(environment)


def _verify_executable_lookup_path(value: object, *, expected_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or len(value) > 4096
        or ":" in value
        or _contains_control_character(value)
    ):
        raise StudyRetentionError("implementation validation executable lookup path is invalid")
    components = value.split("/")[1:]
    if not components or any(component in {"", ".", ".."} for component in components):
        raise StudyRetentionError("implementation validation executable lookup path is invalid")
    lookup_path = PurePosixPath(value)
    if (
        not lookup_path.is_absolute()
        or lookup_path.as_posix() != value
        or lookup_path.name != expected_name
    ):
        raise StudyRetentionError("implementation validation executable lookup path is invalid")
    return value


def _expected_validation_environment_path(lookup_paths: tuple[str, ...]) -> str:
    uv_paths = lookup_paths[:4]
    npm_paths = lookup_paths[4:]
    if len(set(uv_paths)) != 1 or len(set(npm_paths)) != 1:
        raise StudyRetentionError("implementation validation executable lookup paths differ")
    dynamic_parents: list[str] = []
    for lookup_path in (uv_paths[0], npm_paths[0]):
        parent = PurePosixPath(lookup_path).parent.as_posix()
        if parent not in dynamic_parents:
            dynamic_parents.append(parent)
    return f"{':'.join(dynamic_parents)}:{VALIDATION_SYSTEM_PATH_SUFFIX}"


def _validation_byte_count(command: Mapping[str, object], field_name: str) -> int:
    value = command.get(field_name)
    if type(value) is not int or not 0 <= value <= _VALIDATION_OUTPUT_LIMIT_BYTES:
        raise StudyRetentionError("implementation validation command byte count is invalid")
    return value


def _verify_validation_commands(value: object) -> tuple[ValidationCommand, ...]:
    if not isinstance(value, list) or len(value) != len(IMPLEMENTATION_VALIDATION_COMMANDS):
        raise StudyRetentionError("implementation validation commands are incomplete")
    raw_commands: list[dict[str, object]] = []
    lookup_paths: list[str] = []
    reviewed_roots = frozenset(reviewed_validation_executable_roots())
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
        lookup_path = _verify_executable_lookup_path(
            command.get("executable_lookup_path"),
            expected_name=expected_argv[0],
        )
        if PurePosixPath(lookup_path).parent.as_posix() not in reviewed_roots:
            raise StudyRetentionError(
                "implementation validation executable lookup path is outside "
                "a reviewed executable root"
            )
        lookup_paths.append(lookup_path)
        raw_commands.append(command)
    expected_environment_path = _expected_validation_environment_path(tuple(lookup_paths))
    commands: list[ValidationCommand] = []
    shared_environment: Mapping[str, str] | None = None
    for ordinal, ((expected_name, expected_argv), command) in enumerate(
        zip(IMPLEMENTATION_VALIDATION_COMMANDS, raw_commands, strict=True)
    ):
        if command.get("exit_code") != 0:
            raise StudyRetentionError("implementation validation command did not pass")
        expected_timeout = IMPLEMENTATION_VALIDATION_TIMEOUT_SECONDS[ordinal]
        if (
            command.get("cwd") != "."
            or command.get("shell") is not False
            or command.get("timeout_seconds") != expected_timeout
            or command.get("output_limit_bytes") != _VALIDATION_OUTPUT_LIMIT_BYTES
            or command.get("timed_out") is not False
        ):
            raise StudyRetentionError("implementation validation command audit metadata is invalid")
        stdout_byte_count = _validation_byte_count(command, "stdout_byte_count")
        stderr_byte_count = _validation_byte_count(command, "stderr_byte_count")
        environment = _verify_sanitized_environment(
            command.get("sanitized_environment"),
            expected_path=expected_environment_path,
        )
        if shared_environment is None:
            shared_environment = environment
        elif environment != shared_environment:
            raise StudyRetentionError("implementation validation command environments differ")
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
                executable_lookup_path=lookup_paths[ordinal],
                exit_code=0,
                stdout_sha256=stdout_sha256,
                stderr_sha256=stderr_sha256,
                started_at_utc=started,
                ended_at_utc=ended,
                cwd=".",
                shell=False,
                timeout_seconds=expected_timeout,
                output_limit_bytes=_VALIDATION_OUTPUT_LIMIT_BYTES,
                timed_out=False,
                stdout_byte_count=stdout_byte_count,
                stderr_byte_count=stderr_byte_count,
                sanitized_environment=environment,
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
    allow_retained_input_copies: bool = False,
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
    changes = _git_changed_paths(repo_root, execution_commit, current)
    changed = tuple(
        sorted(
            {
                path
                for change in changes
                for path in _lineage_paths(
                    change,
                    artifact_relative=artifact_relative,
                    allow_retained_input_copies=allow_retained_input_copies,
                )
            }
        )
    )
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


def _lineage_paths(
    change: _GitChangeRecord,
    *,
    artifact_relative: str,
    allow_retained_input_copies: bool,
) -> tuple[str, ...]:
    if (
        allow_retained_input_copies
        and change.status == "C"
        and change.score == 100
        and change.source is not None
        and (change.source, change.destination)
        in {
            (source, f"{artifact_relative}/{destination}")
            for _, source, destination, _ in RETAINED_INPUTS
        }
    ):
        return (change.destination,)
    return change.paths


def _git_changed_paths(
    root: Path,
    older: str,
    newer: str,
) -> tuple[_GitChangeRecord, ...]:
    output = _run_git_bytes(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-status",
        "-z",
        "--find-renames",
        "--find-copies-harder",
        "--diff-filter=ACDMRTUXB",
        older,
        newer,
    )
    fields = _nul_fields(output, label="git diff")
    changes: list[_GitChangeRecord] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        status_code = status[:1]
        if status_code not in {
            b"A",
            b"B",
            b"C",
            b"D",
            b"M",
            b"R",
            b"T",
            b"U",
            b"X",
        }:
            raise StudyRetentionError("git diff name-status output is malformed")
        score: int | None = None
        if status_code in {b"R", b"C"}:
            score_bytes = status[1:]
            if not score_bytes.isdigit() or int(score_bytes) > 100:
                raise StudyRetentionError("git diff rename/copy status is malformed")
            score = int(score_bytes)
        elif len(status) != 1:
            raise StudyRetentionError("git diff name-status output is malformed")
        index += 1
        if index >= len(fields):
            raise StudyRetentionError("git diff path output is malformed")
        first_path = os.fsdecode(fields[index])
        index += 1
        if status_code in {b"R", b"C"}:
            if index >= len(fields):
                raise StudyRetentionError("git diff rename/copy output is malformed")
            second_path = os.fsdecode(fields[index])
            index += 1
            changes.append(
                _GitChangeRecord(
                    status=os.fsdecode(status_code),
                    score=score,
                    source=first_path,
                    destination=second_path,
                )
            )
        else:
            changes.append(
                _GitChangeRecord(
                    status=os.fsdecode(status_code),
                    score=None,
                    source=None,
                    destination=first_path,
                )
            )
    return tuple(changes)


def _git_status_paths(root: Path) -> tuple[str, ...]:
    output = _run_git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    fields = _nul_fields(output, label="git status")
    paths: set[str] = set()
    index = 0
    while index < len(fields):
        record = fields[index]
        if len(record) < 4 or record[2:3] != b" ":
            raise StudyRetentionError("git status output is malformed")
        status = record[:2]
        path = record[3:]
        if not path:
            raise StudyRetentionError("git status output is malformed")
        paths.add(os.fsdecode(path))
        if b"R" in status or b"C" in status:
            index += 1
            if index >= len(fields) or not fields[index]:
                raise StudyRetentionError("git status rename/copy output is malformed")
            paths.add(os.fsdecode(fields[index]))
        index += 1
    return tuple(sorted(paths))


def _nul_fields(payload: bytes, *, label: str) -> tuple[bytes, ...]:
    if not payload:
        return ()
    if not payload.endswith(b"\0"):
        raise StudyRetentionError(f"{label} NUL-delimited output is malformed")
    fields = tuple(payload[:-1].split(b"\0"))
    if any(not field for field in fields):
        raise StudyRetentionError(f"{label} NUL-delimited output is malformed")
    return fields


def _require_ancestor(root: Path, older: str, newer: str) -> None:
    completed = _run_git_command(
        root,
        "merge-base",
        "--is-ancestor",
        older,
        newer,
        accepted_returncodes=(0, 1),
    )
    if completed.returncode != 0:
        raise StudyRetentionError(f"git ancestry check failed: {older} is not ancestor of {newer}")


def _require_git_commit(root: Path, commit: str, *, label: str) -> None:
    _require_lower_hex(commit, _SHA1_LENGTH, label)
    resolved = _run_git(root, "rev-parse", "--verify", f"{commit}^{{commit}}")
    if resolved != commit:
        raise StudyRetentionError(f"{label} does not resolve exactly")


def _run_git(root: Path, *args: str) -> str:
    completed = _run_git_command(root, *args)
    return os.fsdecode(completed.stdout).strip()


def _run_git_bytes(root: Path, *args: str) -> bytes:
    return _run_git_command(root, *args).stdout


def _resolve_system_git_executable() -> Path:
    for directory in VALIDATION_SYSTEM_PATH_SUFFIX.split(":"):
        candidate = Path(directory) / "git"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise StudyRetentionError("Git is unavailable in the fixed system path")


def _run_git_command(
    root: Path,
    *args: str,
    accepted_returncodes: tuple[int, ...] = (0,),
) -> _GitCommandResult:
    """Run one bounded Git control-plane command without inherited authority."""

    lexical_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    executable = _resolve_system_git_executable()
    if not executable.is_absolute():
        raise StudyRetentionError("Git executable lookup did not return an absolute path")
    environment = {
        "HOME": os.fspath(lexical_root),
        "PATH": VALIDATION_SYSTEM_PATH_SUFFIX,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    try:
        process = subprocess.Popen(
            (
                os.fspath(executable),
                "--no-pager",
                "-c",
                "core.fsmonitor=false",
                *args,
            ),
            cwd=lexical_root,
            env=environment,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise StudyRetentionError(f"git command could not run: {exc}") from exc

    stdout, stderr = _drain_git_process(process)
    completed = _GitCommandResult(cast(int, process.returncode), stdout, stderr)
    if completed.returncode not in accepted_returncodes:
        detail = os.fsdecode(completed.stderr.strip() or completed.stdout.strip())
        raise StudyRetentionError(f"git command failed: {' '.join(args)}: {detail}")
    return completed


def _drain_git_process(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    if process.stdout is None or process.stderr is None:
        _kill_process_group(process)
        raise StudyRetentionError("git command pipes were not created")
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    pipes = {stdout_fd: process.stdout, stderr_fd: process.stderr}
    buffers = {stdout_fd: bytearray(), stderr_fd: bytearray()}
    selector = selectors.DefaultSelector()
    for descriptor in pipes:
        os.set_blocking(descriptor, False)
        selector.register(descriptor, selectors.EVENT_READ)
    deadline = time.monotonic() + _GIT_TIMEOUT_SECONDS
    overflow = False
    timed_out = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process_group(process)
                remaining = 0.1
            for key, _ in selector.select(min(max(remaining, 0.0), 0.1)):
                descriptor = key.fd
                try:
                    chunk = os.read(descriptor, 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(descriptor)
                    pipes[descriptor].close()
                    continue
                buffer = buffers[descriptor]
                if not overflow:
                    buffer.extend(chunk)
                    if len(buffer) > _GIT_OUTPUT_LIMIT_BYTES:
                        overflow = True
                        _kill_process_group(process)
        process.wait(timeout=1)
    except (OSError, subprocess.SubprocessError) as exc:
        _kill_process_group(process)
        process.wait()
        raise StudyRetentionError(f"git command output could not be drained: {exc}") from exc
    finally:
        selector.close()
    if timed_out:
        raise StudyRetentionError("git command timed out")
    if overflow:
        raise StudyRetentionError("git command output exceeded the byte limit")
    return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd])


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


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
