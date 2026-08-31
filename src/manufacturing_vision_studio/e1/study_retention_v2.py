"""Read-only closure checks and immutable Phase 0 retention evidence."""

from __future__ import annotations

import ast
import builtins as _python_builtins
import os
import pwd
import re
import selectors
import signal
import subprocess
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, NoReturn, cast

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
_SYS_REGISTRY_MEMBERS = frozenset({"modules", "meta_path", "path_hooks"})
_PKGUTIL_LOADER_MEMBERS = frozenset({"get_loader", "resolve_name"})
_OPERATOR_REFLECTION_MEMBERS = frozenset({"attrgetter", "methodcaller"})
_UNIVERSAL_REFLECTION_MEMBERS = frozenset(
    {
        "__globals__",
        "__subclasses__",
        "__bases__",
        "__mro__",
        "f_globals",
        "f_locals",
        "f_builtins",
        "f_back",
        "tb_frame",
        "gi_frame",
        "cr_frame",
        "ag_frame",
    }
)
_PROJECTED_PACKAGE_ROOTS = frozenset(
    {"manufacturing_vision_studio", "manufacturing_vision_studio.e1"}
)
_PROVABLE_BUILTIN_EXCEPTION_SUPERTYPES: Mapping[str, frozenset[str]] = (
    MappingProxyType(
        {
            "BaseException": frozenset({"BaseException"}),
            "Exception": frozenset({"BaseException", "Exception"}),
            "LookupError": frozenset(
                {"BaseException", "Exception", "LookupError"}
            ),
            "RuntimeError": frozenset(
                {"BaseException", "Exception", "RuntimeError"}
            ),
            "TypeError": frozenset({"BaseException", "Exception", "TypeError"}),
            "ValueError": frozenset({"BaseException", "Exception", "ValueError"}),
        }
    )
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
class _InitializerPolicy:
    exact_call_sites: tuple[_ExactCallSite, ...]
    lazy_targets: tuple[tuple[str, str, str], ...]


_EMPTY_INITIALIZER_POLICY = _InitializerPolicy((), ())


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


_Capability = Literal[
    "builtins-namespace",
    "dynamic-loader-module",
    "evaluation-scope",
    "executable-code",
    "import-loader",
    "import-namespace",
    "import-registry",
    "namespace-mapping",
    "namespace-reflection",
    "operator-module",
    "package-object",
    "plan-cases-callable",
    "pkgutil-module",
    "sys-module",
    "type-checking-sentinel",
    "typing-module",
    "zipimport-module",
]
class _Truth(Enum):
    BOTTOM = "bottom"
    FALSE = "false"
    TRUE = "true"
    UNKNOWN = "unknown"


_IdentityKind = Literal["builtin", "imported", "function", "class", "literal"]
_ExactState = Literal["none", "exact", "top"]
_IterationOutcome = Literal["zero", "one", "many"]
_DeferredKind = Literal["function", "async-function", "lambda", "generator"]
_ExitKind = Literal["normal", "break", "continue", "return", "raise"]
_WriteKind = Literal["assign", "augment", "delete", "import", "star-import"]
_DeferredTiming = Literal["on-call", "on-await", "on-iteration"]
_Multiplicity = Literal["zero-or-one", "exactly-one", "zero-or-many"]
_ScopeKind = Literal["module", "function", "lambda", "class", "comprehension"]
_TransferMode = Literal[
    "eager",
    "deferred",
    "type-only",
    "unreachable",
    "postponed-annotation",
    "lazy-annotation",
]
_PolicyCapability = Literal[
    "dynamic-import",
    "executable-code",
    "namespace-reflection",
    "import-registry",
    "package-object",
    "deferred-effect",
]
_ExactRole = Literal[
    "pep562-import-module",
    "pep562-getattr",
    "pep562-cache-globals",
    "pep562-dir-globals",
    "cli-dataclass-getattr",
    "study-truth-development-plan",
    "study-truth-legacy-plan",
]


@dataclass(frozen=True, slots=True, order=True)
class _SourceLocation:
    module: str
    node_kind: str
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int


_ProgramPoint = tuple[str, _SourceLocation, _TransferMode]
_FrameSkeleton = tuple[
    _SourceLocation,
    _ScopeKind,
    int,
    frozenset[str],
    frozenset[str],
]
_StateSkeleton = tuple[_FrameSkeleton, ...]


@dataclass(frozen=True, slots=True, order=True)
class _ResolvedIdentity:
    kind: _IdentityKind
    owner: str
    name: str
    definition: _SourceLocation | None = None


@dataclass(frozen=True, slots=True)
class _PackageFact:
    state: _ExactState = "none"
    target: str | None = None

    def __post_init__(self) -> None:
        if (self.state == "exact") != (self.target is not None):
            raise ValueError("invalid package fact")


@dataclass(frozen=True, slots=True)
class _IdentityFact:
    state: _ExactState = "none"
    identity: _ResolvedIdentity | None = None

    def __post_init__(self) -> None:
        if (self.state == "exact") != (self.identity is not None):
            raise ValueError("invalid identity fact")


@dataclass(frozen=True, slots=True)
class _ValueFacts:
    may_capabilities: frozenset[_Capability] = frozenset()
    package: _PackageFact = _PackageFact()
    identity: _IdentityFact = _IdentityFact()
    complete: bool = True


@dataclass(frozen=True, slots=True)
class _AbsValue:
    facts: _ValueFacts = _ValueFacts()
    truth: _Truth = _Truth.UNKNOWN
    iterable_element: _ValueFacts = _ValueFacts(complete=False)
    contained: _ValueFacts = _ValueFacts()
    iteration_outcomes: frozenset[_IterationOutcome] = frozenset(
        {"zero", "one", "many"}
    )
    may_iteration_raise: bool = True

    def __post_init__(self) -> None:
        if self.truth is _Truth.BOTTOM:
            raise ValueError("reachable abstract value cannot have bottom truth")


_UNKNOWN_VALUE = _AbsValue(facts=_ValueFacts(complete=False))
_SAFE_VALUE = _AbsValue()


@dataclass(frozen=True, slots=True)
class _BindingSlot:
    value: _AbsValue
    may_be_bound: bool = True
    may_be_unbound: bool = False


@dataclass(frozen=True, slots=True)
class _Frame:
    scope_id: _SourceLocation
    kind: _ScopeKind
    bindings: tuple[tuple[str, _BindingSlot], ...]
    global_names: frozenset[str] = frozenset()
    nonlocal_names: frozenset[str] = frozenset()
    wildcard_shadowed: bool = False

    @classmethod
    def create(
        cls,
        *,
        scope_id: _SourceLocation,
        kind: _ScopeKind,
        names: Sequence[str],
        global_names: frozenset[str] = frozenset(),
        nonlocal_names: frozenset[str] = frozenset(),
    ) -> _Frame:
        local_names = set(names).difference(global_names, nonlocal_names)
        return cls(
            scope_id=scope_id,
            kind=kind,
            bindings=tuple(
                (name, _BindingSlot(_UNKNOWN_VALUE, False, True))
                for name in sorted(local_names)
            ),
            global_names=global_names,
            nonlocal_names=nonlocal_names,
        )

    def replace_binding(self, name: str, slot: _BindingSlot) -> _Frame:
        bindings = dict(self.bindings)
        if name not in bindings:
            raise ValueError(f"binding skeleton does not contain {name}")
        bindings[name] = slot
        return _Frame(
            self.scope_id,
            self.kind,
            tuple(sorted(bindings.items())),
            self.global_names,
            self.nonlocal_names,
            self.wildcard_shadowed,
        )

    def with_wildcard(self) -> _Frame:
        return _Frame(
            self.scope_id,
            self.kind,
            self.bindings,
            self.global_names,
            self.nonlocal_names,
            True,
        )


@dataclass(frozen=True, slots=True)
class _State:
    frames: tuple[_Frame, ...]

    def resolve(self, name: str) -> _BindingSlot:
        index = self._resolution_index(name)
        if index is None:
            return _BindingSlot(_UNKNOWN_VALUE, False, True)
        return dict(self.frames[index].bindings)[name]

    def binding_frame_index(self, name: str) -> int | None:
        current = self.frames[-1]
        if name in current.global_names:
            return 0
        if name in current.nonlocal_names:
            return self._nonlocal_index(name)
        return len(self.frames) - 1

    def bind(self, name: str, value: _AbsValue) -> _State:
        index = self.binding_frame_index(name)
        if index is None:
            raise ValueError(f"unresolved nonlocal binding: {name}")
        frames = list(self.frames)
        frames[index] = frames[index].replace_binding(name, _BindingSlot(value))
        return _State(tuple(frames))

    def unbind(self, name: str) -> _State:
        index = self.binding_frame_index(name)
        if index is None:
            raise ValueError(f"unresolved nonlocal binding: {name}")
        frames = list(self.frames)
        frames[index] = frames[index].replace_binding(
            name, _BindingSlot(_UNKNOWN_VALUE, False, True)
        )
        return _State(tuple(frames))

    def bind_target(self, target: ast.expr, value: _AbsValue) -> _State:
        if isinstance(target, ast.Name):
            return self.bind(target.id, value)
        if isinstance(target, ast.Starred):
            return self.bind_target(target.value, _element_value(value))
        if isinstance(target, (ast.Tuple, ast.List)):
            state = self
            promoted = _element_value(value)
            for element in target.elts:
                state = state.bind_target(element, promoted)
            return state
        return self

    def bind_pattern(self, pattern: ast.pattern, value: _AbsValue) -> _State:
        if isinstance(pattern, ast.MatchAs):
            state = self
            if pattern.pattern is not None:
                state = state.bind_pattern(pattern.pattern, value)
            return state if pattern.name is None else state.bind(pattern.name, value)
        if isinstance(pattern, ast.MatchStar):
            return self if pattern.name is None else self.bind(pattern.name, value)
        if isinstance(pattern, ast.MatchMapping):
            state = self
            derived = _derived_value(value, complete=False)
            for child in pattern.patterns:
                state = state.bind_pattern(child, derived)
            return state if pattern.rest is None else state.bind(pattern.rest, derived)
        if isinstance(pattern, ast.MatchSequence):
            state = self
            derived = _element_value(value)
            for child in pattern.patterns:
                state = state.bind_pattern(child, derived)
            return state
        if isinstance(pattern, ast.MatchClass):
            state = self
            derived = _derived_value(value, complete=False)
            for child in (*pattern.patterns, *pattern.kwd_patterns):
                state = state.bind_pattern(child, derived)
            return state
        if isinstance(pattern, ast.MatchOr):
            states = tuple(self.bind_pattern(child, value) for child in pattern.patterns)
            return _join_states(*states) or self
        return self

    def push(self, frame: _Frame) -> _State:
        return _State((*self.frames, frame))

    def pop(self) -> _State:
        if len(self.frames) == 1:
            raise ValueError("cannot pop module frame")
        return _State(self.frames[:-1])

    def join(self, other: _State) -> _State:
        if self is other:
            return self
        if len(self.frames) != len(other.frames):
            raise ValueError(
                "cannot join states with different scope depths: "
                f"{tuple(frame.kind for frame in self.frames)} != "
                f"{tuple(frame.kind for frame in other.frames)}"
            )
        joined: list[_Frame] = []
        for left, right in zip(self.frames, other.frames, strict=True):
            if left is right:
                joined.append(left)
                continue
            if (
                left.scope_id,
                left.kind,
                left.global_names,
                left.nonlocal_names,
            ) != (
                right.scope_id,
                right.kind,
                right.global_names,
                right.nonlocal_names,
            ):
                raise ValueError("cannot join states with different frame skeletons")
            bindings_list: list[tuple[str, _BindingSlot]] = []
            for (left_name, left_slot), (right_name, right_slot) in zip(
                left.bindings, right.bindings, strict=True
            ):
                if left_name != right_name:
                    raise ValueError("cannot grow a frame skeleton during join")
                bindings_list.append(
                    (left_name, _join_slots(left_slot, right_slot))
                )
            bindings = tuple(bindings_list)
            joined.append(
                _Frame(
                    left.scope_id,
                    left.kind,
                    bindings,
                    left.global_names,
                    left.nonlocal_names,
                    left.wildcard_shadowed or right.wildcard_shadowed,
                )
            )
        return _State(tuple(joined))

    def _resolution_index(self, name: str) -> int | None:
        current = self.frames[-1]
        if name in current.global_names:
            return 0 if name in dict(self.frames[0].bindings) else None
        if name in current.nonlocal_names:
            return self._nonlocal_index(name)
        skip_classes = current.kind in {"function", "lambda", "comprehension"}
        for index in range(len(self.frames) - 1, -1, -1):
            frame = self.frames[index]
            if index != len(self.frames) - 1 and skip_classes and frame.kind == "class":
                continue
            slot = dict(frame.bindings).get(name)
            if slot is None:
                continue
            if frame.kind == "class" and slot.may_be_unbound and not slot.may_be_bound:
                continue
            return index
        return None

    def _nonlocal_index(self, name: str) -> int | None:
        for index in range(len(self.frames) - 2, 0, -1):
            frame = self.frames[index]
            if frame.kind != "class" and name in dict(frame.bindings):
                return index
        return None


@dataclass(frozen=True, slots=True)
class _DeferredWrite:
    kind: _DeferredKind
    name: str
    location: _SourceLocation
    target_scope: _SourceLocation | None
    operation: _WriteKind
    value: _AbsValue
    timing: _DeferredTiming
    multiplicity: _Multiplicity


@dataclass(frozen=True, slots=True)
class _DeferredBody:
    kind: _DeferredKind
    location: _SourceLocation
    enclosing_scope: _SourceLocation
    definition_state: _State
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.GeneratorExp


@dataclass(frozen=True, slots=True)
class _DeferredEffects:
    writes: tuple[_DeferredWrite, ...] = ()
    bodies: tuple[_DeferredBody, ...] = ()
    unknown_outer_write: bool = False


@dataclass(frozen=True, slots=True)
class _TransferContext:
    mode: _TransferMode
    commit_state: bool
    emit_runtime_references: bool
    emit_type_only_references: bool


@dataclass(frozen=True, slots=True)
class _NormalExit:
    value: _AbsValue
    state: _State


@dataclass(frozen=True, slots=True)
class _ExceptionalExits:
    exact: tuple[tuple[_ResolvedIdentity, _State], ...] = ()
    unknown: _State | None = None

    def __post_init__(self) -> None:
        identities = tuple(identity for identity, _state in self.exact)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("exceptional exit identities must be sorted and unique")
        if any(
            identity.kind != "builtin"
            or identity.owner != "builtins"
            or identity.name not in _PROVABLE_BUILTIN_EXCEPTION_SUPERTYPES
            for identity in identities
        ):
            raise ValueError("exceptional exit identity is outside the finite universe")

    @property
    def joined_state(self) -> _State | None:
        return _join_states(
            *(state for _identity, state in self.exact),
            self.unknown,
        )


@dataclass(frozen=True, slots=True, order=True)
class _ExactCallSite:
    role: _ExactRole
    location: _SourceLocation
    required_bindings: tuple[tuple[str, _ResolvedIdentity], ...]
    identity_node: ast.AST | None = field(
        default=None,
        compare=False,
        hash=False,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class _PolicyFacts:
    references: frozenset[_ImportReference] = frozenset()
    protected: frozenset[str] = frozenset()
    forbidden_calls: frozenset[str] = frozenset()
    study_forbidden_calls: frozenset[str] = frozenset()
    closure_errors: frozenset[str] = frozenset()
    pending_exact_uses: tuple[_ExactCallSite, ...] = ()


_EMPTY_DEFERRED_EFFECTS = _DeferredEffects()
_EMPTY_POLICY_FACTS = _PolicyFacts()
_EMPTY_EXCEPTIONAL_EXITS = _ExceptionalExits()


@dataclass(frozen=True, slots=True)
class _ExprResult:
    truthy: _NormalExit | None
    falsy: _NormalExit | None
    raises: _State | None
    deferred: _DeferredEffects = _DeferredEffects()
    facts: _PolicyFacts = _PolicyFacts()

    @property
    def post_state(self) -> _State | None:
        return _join_states(
            None if self.truthy is None else self.truthy.state,
            None if self.falsy is None else self.falsy.state,
        )

    @property
    def value(self) -> _AbsValue:
        values = tuple(
            exit.value for exit in (self.truthy, self.falsy) if exit is not None
        )
        if not values:
            return _UNKNOWN_VALUE
        result = values[0]
        for value in values[1:]:
            result = _join_values(result, value)
        return result

    @property
    def truth(self) -> _Truth:
        if self.truthy is None and self.falsy is None:
            return _Truth.BOTTOM
        if self.truthy is None:
            return _Truth.FALSE
        if self.falsy is None:
            return _Truth.TRUE
        return _Truth.UNKNOWN


@dataclass(frozen=True, slots=True)
class _FlowResult:
    normal: _State | None
    breaks: _State | None = None
    continues: _State | None = None
    returns: _State | None = None
    exceptions: _ExceptionalExits = _ExceptionalExits()
    deferred: _DeferredEffects = _DeferredEffects()
    facts: _PolicyFacts = _PolicyFacts()

    @property
    def raises(self) -> _State | None:
        return self.exceptions.joined_state


@dataclass(frozen=True, slots=True)
class _AnalysisStats:
    program_points: int
    cfg_edges: int
    expression_transfers: int
    statement_transfers: int
    pattern_transfers: int
    state_join_attempts: int
    strict_state_updates: int
    worklist_pops: int
    max_updates_per_program_point: int
    computed_height_bound: int

    @property
    def transfer_steps(self) -> int:
        return (
            self.expression_transfers
            + self.statement_transfers
            + self.pattern_transfers
        )


@dataclass(frozen=True, slots=True)
class _ModuleFlowResult:
    final_states: tuple[_State, ...]
    facts: _PolicyFacts
    stats: _AnalysisStats


@dataclass(slots=True)
class _StatsBuilder:
    program_points: set[_ProgramPoint] = field(default_factory=set)
    cfg_edges: set[tuple[_ProgramPoint, _ProgramPoint]] = field(
        default_factory=set
    )
    expression_transfers: int = 0
    statement_transfers: int = 0
    pattern_transfers: int = 0
    state_join_attempts: int = 0
    strict_state_updates: int = 0
    worklist_pops: int = 0
    max_updates_per_program_point: int = 0
    max_observed_point_height: int = 1
    precomputed_height_bound: int | None = None
    updates_by_program_point: dict[_ProgramPoint, int] = field(
        default_factory=dict
    )

    def record_transfer(self, kind: str) -> None:
        if kind == "expression":
            self.expression_transfers += 1
        elif kind == "statement":
            self.statement_transfers += 1
        elif kind == "pattern":
            self.pattern_transfers += 1
        else:
            raise ValueError(f"unknown transfer kind: {kind}")

    def record_cfg_edge(
        self, source: _ProgramPoint, target: _ProgramPoint
    ) -> None:
        if source != target:
            self.cfg_edges.add((source, target))

    def merge_program_point(
        self,
        point: _ProgramPoint,
        current: _State,
        candidate: _State,
    ) -> tuple[_State, bool]:
        self.state_join_attempts += 1
        joined = current.join(candidate)
        if joined == current:
            return current, False
        self.strict_state_updates += 1
        updates = self.updates_by_program_point.get(point, 0) + 1
        self.updates_by_program_point[point] = updates
        self.max_updates_per_program_point = max(
            self.max_updates_per_program_point, updates
        )
        return joined, True

    def configure_height_bound(self, bound: int) -> None:
        if bound < 1:
            raise ValueError("analysis height bound must be positive")
        self.precomputed_height_bound = bound

    def observe_state(self, state: _State) -> None:
        capability_bits = len(getattr(_Capability, "__args__", ()))
        value_height = 3 * (capability_bits + 2 + 2 + 1) + 5
        point_height = (
            1
            + sum(len(frame.bindings) for frame in state.frames)
            * (value_height + 2)
            + len(state.frames)
        )
        self.max_observed_point_height = max(
            self.max_observed_point_height, point_height
        )

    def freeze(self) -> _AnalysisStats:
        observed_height = self.max_observed_point_height
        height = self.precomputed_height_bound or observed_height
        if observed_height > height:
            raise ValueError("precomputed analysis height bound was too small")
        return _AnalysisStats(
            program_points=len(self.program_points),
            cfg_edges=len(self.cfg_edges),
            expression_transfers=self.expression_transfers,
            statement_transfers=self.statement_transfers,
            pattern_transfers=self.pattern_transfers,
            state_join_attempts=self.state_join_attempts,
            strict_state_updates=self.strict_state_updates,
            worklist_pops=self.worklist_pops,
            max_updates_per_program_point=self.max_updates_per_program_point,
            computed_height_bound=height,
        )


@dataclass(frozen=True, slots=True)
class _ScopeDeclarations:
    local_names: frozenset[str]
    global_names: frozenset[str]
    nonlocal_names: frozenset[str]


def _source_location(module: str, node: ast.AST) -> _SourceLocation:
    if isinstance(node, ast.Module):
        return _SourceLocation(module, "Module", 0, 0, 0, 0)
    return _SourceLocation(
        module,
        type(node).__name__,
        getattr(node, "lineno", 0),
        getattr(node, "col_offset", 0),
        getattr(node, "end_lineno", 0) or 0,
        getattr(node, "end_col_offset", 0) or 0,
    )


def _exact_package(target: str) -> _PackageFact:
    return _PackageFact("exact", target)


def _exact_identity(identity: _ResolvedIdentity) -> _IdentityFact:
    return _IdentityFact("exact", identity)


def _evaluation_scope_identity() -> _ResolvedIdentity:
    return _ResolvedIdentity(
        "imported",
        "manufacturing_vision_studio.e1.domain_v2",
        "EvaluationScope",
    )


def _plan_cases_callable_identity() -> _ResolvedIdentity:
    return _ResolvedIdentity(
        "literal",
        "manufacturing_vision_studio.e1.study_retention_v2",
        "plan_cases.callable",
    )


def _has_exact_identity(value: _AbsValue, expected: _ResolvedIdentity) -> bool:
    return (
        value.facts.complete
        and value.facts.identity.state == "exact"
        and value.facts.identity.identity == expected
    )


def _sys_module_identity() -> _ResolvedIdentity:
    return _ResolvedIdentity("imported", "sys", "<module>")


def _has_exact_sys_module(value: _AbsValue) -> bool:
    return _has_exact_identity(value, _sys_module_identity())


def _protected_scope_fact(
    source_module: str,
    node: ast.AST,
    member: str,
) -> _PolicyFacts:
    return _PolicyFacts(
        protected=frozenset(
            {f"{source_module}:{getattr(node, 'lineno', 0)}:EvaluationScope.{member}"}
        )
    )


def _join_package(left: _PackageFact, right: _PackageFact) -> _PackageFact:
    if left.state == right.state == "none":
        return _PackageFact()
    if (
        left.state == right.state == "exact"
        and left.target == right.target
        and left.target is not None
    ):
        return left
    return _PackageFact("top")


def _join_identity(left: _IdentityFact, right: _IdentityFact) -> _IdentityFact:
    if left.state == right.state == "none":
        return _IdentityFact()
    if (
        left.state == right.state == "exact"
        and left.identity == right.identity
        and left.identity is not None
    ):
        return left
    return _IdentityFact("top")


def _join_value_facts(left: _ValueFacts, right: _ValueFacts) -> _ValueFacts:
    if left is right or left == right:
        return left
    return _ValueFacts(
        may_capabilities=left.may_capabilities | right.may_capabilities,
        package=_join_package(left.package, right.package),
        identity=_join_identity(left.identity, right.identity),
        complete=left.complete and right.complete,
    )


def _flatten_facts(value: _AbsValue) -> _ValueFacts:
    facts = _join_value_facts(value.facts, value.iterable_element)
    return _join_value_facts(facts, value.contained)


def _as_contained(facts: _ValueFacts) -> _ValueFacts:
    package = _PackageFact("top") if facts.package.state != "none" else _PackageFact()
    identity = _IdentityFact("top") if facts.identity.state != "none" else _IdentityFact()
    return _ValueFacts(facts.may_capabilities, package, identity, facts.complete)


def _join_values(left: _AbsValue, right: _AbsValue) -> _AbsValue:
    if left is right or left == right:
        return left
    return _AbsValue(
        facts=_join_value_facts(left.facts, right.facts),
        truth=left.truth if left.truth is right.truth else _Truth.UNKNOWN,
        iterable_element=_join_value_facts(
            left.iterable_element, right.iterable_element
        ),
        contained=_join_value_facts(left.contained, right.contained),
        iteration_outcomes=left.iteration_outcomes | right.iteration_outcomes,
        may_iteration_raise=(
            left.may_iteration_raise or right.may_iteration_raise
        ),
    )


def _join_slots(left: _BindingSlot, right: _BindingSlot) -> _BindingSlot:
    if left is right or left == right:
        return left
    if left.may_be_bound and right.may_be_bound:
        value = _join_values(left.value, right.value)
    elif left.may_be_bound:
        value = left.value
    elif right.may_be_bound:
        value = right.value
    else:
        value = _UNKNOWN_VALUE
    return _BindingSlot(
        value,
        left.may_be_bound or right.may_be_bound,
        left.may_be_unbound or right.may_be_unbound,
    )


def _join_states(*states: _State | None) -> _State | None:
    reachable = tuple(state for state in states if state is not None)
    if not reachable:
        return None
    result = reachable[0]
    for state in reachable[1:]:
        if state is result:
            continue
        result = result.join(state)
    return result


def _unknown_exceptions(state: _State | None) -> _ExceptionalExits:
    if state is None:
        return _EMPTY_EXCEPTIONAL_EXITS
    return _ExceptionalExits(unknown=state)


def _join_exceptions(*exits: _ExceptionalExits) -> _ExceptionalExits:
    exact: dict[_ResolvedIdentity, _State] = {}
    for projection in exits:
        for identity, state in projection.exact:
            previous = exact.get(identity)
            exact[identity] = _join_states(previous, state) or state
    return _ExceptionalExits(
        tuple(sorted(exact.items())),
        _join_states(*(projection.unknown for projection in exits)),
    )


def _replace_exception_states(
    exits: _ExceptionalExits, state: _State | None
) -> _ExceptionalExits:
    if state is None:
        return _EMPTY_EXCEPTIONAL_EXITS
    return _ExceptionalExits(
        tuple((identity, state) for identity, _prior in exits.exact),
        state if exits.unknown is not None else None,
    )


def _map_exception_states(
    exits: _ExceptionalExits,
    transform: Callable[[_State], _State | None],
) -> _ExceptionalExits:
    exact: list[tuple[_ResolvedIdentity, _State]] = []
    for identity, state in exits.exact:
        transformed = transform(state)
        if transformed is not None:
            exact.append((identity, transformed))
    unknown = None if exits.unknown is None else transform(exits.unknown)
    return _ExceptionalExits(tuple(exact), unknown)


def _join_policy(*facts: _PolicyFacts) -> _PolicyFacts:
    pending: dict[tuple[_ExactRole, _SourceLocation], _ExactCallSite] = {}
    for item in facts:
        for use in item.pending_exact_uses:
            pending[(use.role, use.location)] = use
    return _PolicyFacts(
        references=frozenset().union(*(item.references for item in facts)),
        protected=frozenset().union(*(item.protected for item in facts)),
        forbidden_calls=frozenset().union(*(item.forbidden_calls for item in facts)),
        study_forbidden_calls=frozenset().union(
            *(item.study_forbidden_calls for item in facts)
        ),
        closure_errors=frozenset().union(*(item.closure_errors for item in facts)),
        pending_exact_uses=tuple(pending[key] for key in sorted(pending)),
    )


def _deferred_write_key(
    write: _DeferredWrite,
) -> tuple[_DeferredKind, _SourceLocation, _SourceLocation | None, str, _WriteKind]:
    return write.kind, write.location, write.target_scope, write.name, write.operation


def _join_multiplicity(left: _Multiplicity, right: _Multiplicity) -> _Multiplicity:
    if left == right:
        return left
    if "zero-or-many" in {left, right}:
        return "zero-or-many"
    return "zero-or-one"


def _join_deferred(*effects: _DeferredEffects) -> _DeferredEffects:
    writes: dict[
        tuple[_DeferredKind, _SourceLocation, _SourceLocation | None, str, _WriteKind],
        _DeferredWrite,
    ] = {}
    bodies: dict[tuple[_DeferredKind, _SourceLocation], _DeferredBody] = {}
    for effect in effects:
        for write in effect.writes:
            key = _deferred_write_key(write)
            previous = writes.get(key)
            if previous is None:
                writes[key] = write
            else:
                writes[key] = _DeferredWrite(
                    write.kind,
                    write.name,
                    write.location,
                    write.target_scope,
                    write.operation,
                    _join_values(previous.value, write.value),
                    write.timing,
                    _join_multiplicity(previous.multiplicity, write.multiplicity),
                )
        for body in effect.bodies:
            body_key = (body.kind, body.location)
            previous_body = bodies.get(body_key)
            if previous_body is None:
                bodies[body_key] = body
            else:
                bodies[body_key] = _DeferredBody(
                    body.kind,
                    body.location,
                    body.enclosing_scope,
                    previous_body.definition_state.join(body.definition_state),
                    body.node,
                )
    return _DeferredEffects(
        writes=tuple(writes[key] for key in sorted(writes)),
        bodies=tuple(bodies[key] for key in sorted(bodies)),
        unknown_outer_write=any(effect.unknown_outer_write for effect in effects),
    )


def _join_flow(*results: _FlowResult) -> _FlowResult:
    return _FlowResult(
        normal=_join_states(*(result.normal for result in results)),
        breaks=_join_states(*(result.breaks for result in results)),
        continues=_join_states(*(result.continues for result in results)),
        returns=_join_states(*(result.returns for result in results)),
        exceptions=_join_exceptions(*(result.exceptions for result in results)),
        deferred=_join_deferred(*(result.deferred for result in results)),
        facts=_join_policy(*(result.facts for result in results)),
    )


def _policy_only_deferred_bodies(
    bodies: tuple[_DeferredBody, ...], capture_state: _State
) -> tuple[_DeferredBody, ...]:
    rebased: list[_DeferredBody] = []
    for body in bodies:
        prefix_length = 0
        for captured, reachable in zip(
            body.definition_state.frames, capture_state.frames, strict=False
        ):
            captured_skeleton = (
                captured.scope_id,
                captured.kind,
                tuple(name for name, _slot in captured.bindings),
                captured.global_names,
                captured.nonlocal_names,
            )
            reachable_skeleton = (
                reachable.scope_id,
                reachable.kind,
                tuple(name for name, _slot in reachable.bindings),
                reachable.global_names,
                reachable.nonlocal_names,
            )
            if captured_skeleton != reachable_skeleton:
                break
            prefix_length += 1
        definition_state = _State(
            (
                *capture_state.frames[:prefix_length],
                *body.definition_state.frames[prefix_length:],
            )
        )
        rebased.append(replace(body, definition_state=definition_state))
    return tuple(rebased)


def _policy_only_expression(
    result: _ExprResult, capture_state: _State
) -> _ExprResult:
    return _ExprResult(
        None,
        None,
        None,
        _DeferredEffects(
            bodies=_policy_only_deferred_bodies(
                result.deferred.bodies, capture_state
            )
        ),
        result.facts,
    )


def _policy_only_statement(
    result: _FlowResult, capture_state: _State
) -> _FlowResult:
    return _FlowResult(
        None,
        deferred=_DeferredEffects(
            bodies=_policy_only_deferred_bodies(
                result.deferred.bodies, capture_state
            )
        ),
        facts=result.facts,
    )


def _normal_value(value: _AbsValue, state: _State, truth: _Truth) -> _ExprResult:
    if truth is _Truth.BOTTOM:
        return _ExprResult(None, None, state)
    exit = _NormalExit(replace(value, truth=truth), state)
    if truth is _Truth.TRUE:
        return _ExprResult(exit, None, None)
    if truth is _Truth.FALSE:
        return _ExprResult(None, exit, None)
    return _ExprResult(exit, exit, None)


def _result_with(
    result: _ExprResult,
    *,
    raises: _State | None = None,
    deferred: _DeferredEffects = _EMPTY_DEFERRED_EFFECTS,
    facts: _PolicyFacts = _EMPTY_POLICY_FACTS,
) -> _ExprResult:
    return _ExprResult(
        result.truthy,
        result.falsy,
        _join_states(result.raises, raises),
        _join_deferred(result.deferred, deferred),
        _join_policy(result.facts, facts),
    )


def _truth_for_constant(value: object) -> _Truth:
    try:
        return _Truth.TRUE if bool(value) else _Truth.FALSE
    except (TypeError, ValueError):
        return _Truth.UNKNOWN


def _literal_value(value: object) -> _AbsValue:
    if isinstance(value, (tuple, frozenset)):
        return _container_value(
            tuple(_literal_value(item) for item in value), kind="tuple"
        )
    truth = _truth_for_constant(value)
    if isinstance(value, (str, bytes)):
        outcomes = _iteration_outcomes_for_length(len(value))
        return _AbsValue(
            truth=truth,
            iterable_element=_ValueFacts(),
            iteration_outcomes=outcomes,
            may_iteration_raise=False,
        )
    return _AbsValue(
        truth=truth,
        iteration_outcomes=frozenset(),
        may_iteration_raise=True,
    )


def _truth_for_value(value: _AbsValue) -> _Truth:
    return value.truth


def _iteration_outcomes_for_length(
    length: int,
) -> frozenset[_IterationOutcome]:
    if length == 0:
        return frozenset({"zero"})
    if length == 1:
        return frozenset({"one"})
    return frozenset({"many"})


def _literal_container_shape(
    node: ast.List | ast.Tuple | ast.Set | ast.Dict,
) -> tuple[_Truth, frozenset[_IterationOutcome]]:
    try:
        literal = ast.literal_eval(node)
    except (TypeError, ValueError):
        literal = None
    if isinstance(literal, (list, tuple, set, dict)):
        length = len(literal)
        return (
            _Truth.FALSE if length == 0 else _Truth.TRUE,
            _iteration_outcomes_for_length(length),
        )

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        fixed = sum(not isinstance(element, ast.Starred) for element in node.elts)
        has_expansion = fixed != len(node.elts)
        if not has_expansion and not isinstance(node, ast.Set):
            outcomes = _iteration_outcomes_for_length(fixed)
        elif not has_expansion and fixed == 0:
            outcomes = frozenset({"zero"})
        elif not has_expansion and fixed == 1:
            outcomes = frozenset({"one"})
        elif fixed == 0:
            outcomes = frozenset({"zero", "one", "many"})
        elif fixed == 1 or isinstance(node, ast.Set):
            outcomes = frozenset({"one", "many"})
        else:
            outcomes = frozenset({"many"})
    else:
        fixed = sum(key is not None for key in node.keys)
        has_expansion = fixed != len(node.keys)
        if not has_expansion and fixed == 0:
            outcomes = frozenset({"zero"})
        elif not has_expansion and fixed == 1:
            outcomes = frozenset({"one"})
        elif fixed == 0:
            outcomes = frozenset({"zero", "one", "many"})
        else:
            outcomes = frozenset({"one", "many"})
    truth = (
        _Truth.FALSE
        if outcomes == frozenset({"zero"})
        else _Truth.TRUE
        if "zero" not in outcomes
        else _Truth.UNKNOWN
    )
    return truth, outcomes


def _container_value(
    values: Sequence[_AbsValue],
    *,
    kind: str,
    truth: _Truth | None = None,
    iteration_outcomes: frozenset[_IterationOutcome] | None = None,
) -> _AbsValue:
    if values:
        element = _flatten_facts(values[0])
        for value in values[1:]:
            element = _join_value_facts(element, _flatten_facts(value))
        contained = _as_contained(element)
    else:
        element = _ValueFacts(complete=False)
        contained = _ValueFacts()
    length = len(values)
    outcomes = (
        _iteration_outcomes_for_length(length)
        if iteration_outcomes is None
        else iteration_outcomes
    )
    if kind == "dict":
        element = _ValueFacts(complete=False)
    return _AbsValue(
        truth=(_Truth.FALSE if length == 0 else _Truth.TRUE)
        if truth is None
        else truth,
        iterable_element=element,
        contained=contained,
        iteration_outcomes=outcomes,
        may_iteration_raise=False,
    )


def _element_value(value: _AbsValue) -> _AbsValue:
    return _AbsValue(
        facts=value.iterable_element,
        iterable_element=_ValueFacts(complete=False),
        contained=_as_contained(value.iterable_element),
    )


def _derived_value(value: _AbsValue, *, complete: bool) -> _AbsValue:
    flattened = _flatten_facts(value)
    return _AbsValue(
        facts=_ValueFacts(
            may_capabilities=flattened.may_capabilities,
            package=_PackageFact("top")
            if flattened.package.state != "none"
            else _PackageFact(),
            identity=_IdentityFact("top")
            if flattened.identity.state != "none"
            else _IdentityFact(),
            complete=complete and flattened.complete,
        )
    )


def _value_with_capabilities(
    *capabilities: _Capability,
    complete: bool = True,
    package: str | None = None,
    identity: _ResolvedIdentity | None = None,
) -> _AbsValue:
    return _AbsValue(
        facts=_ValueFacts(
            frozenset(capabilities),
            _PackageFact() if package is None else _exact_package(package),
            _IdentityFact() if identity is None else _exact_identity(identity),
            complete,
        )
    )


def _with_plan_cases_capability(value: _AbsValue, receiver: _AbsValue) -> _AbsValue:
    facts = replace(
        value.facts,
        may_capabilities=value.facts.may_capabilities | {"plan-cases-callable"},
    )
    if "plan-cases-callable" not in _flatten_facts(receiver).may_capabilities:
        facts = replace(
            facts,
            identity=_exact_identity(_plan_cases_callable_identity()),
            complete=True,
        )
    return replace(value, facts=facts)


class _ScopeDeclarationCollector(ast.NodeVisitor):
    def __init__(self, arguments: ast.arguments | None = None) -> None:
        self.local_names: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()
        if arguments is not None:
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ):
                self.local_names.add(argument.arg)
            if arguments.vararg is not None:
                self.local_names.add(arguments.vararg.arg)
            if arguments.kwarg is not None:
                self.local_names.add(arguments.kwarg.arg)

    def finish(self) -> _ScopeDeclarations:
        return _ScopeDeclarations(
            frozenset(self.local_names.difference(self.global_names, self.nonlocal_names)),
            frozenset(self.global_names),
            frozenset(self.nonlocal_names),
        )

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.local_names.add(node.id)

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocal_names.update(node.names)

    def visit_Import(self, node: ast.Import) -> None:
        self.local_names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.local_names.update(
            alias.asname or alias.name for alias in node.names if alias.name != "*"
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.local_names.add(node.name)
        self._visit_function_expressions(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.local_names.add(node.name)
        self._visit_function_expressions(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.local_names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for type_param in getattr(node, "type_params", ()):
            self.visit(type_param)

    def visit_TypeAlias(self, node: ast.AST) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, ast.Name):
            self.local_names.add(name.id)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.visit(node.generators[0].iter)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.visit(node.generators[0].iter)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.visit(node.generators[0].iter)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self.visit(node.generators[0].iter)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.local_names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.local_names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.local_names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.local_names.add(node.rest)
        for pattern in node.patterns:
            self.visit(pattern)

    def _visit_function_expressions(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        for type_param in getattr(node, "type_params", ()):
            self.visit(type_param)


@dataclass(slots=True)
class _ActiveTransfer:
    point: _ProgramPoint
    retained_for_suffix: bool
    last_child: _ProgramPoint | None = None
    last_suffix_child: _ProgramPoint | None = None


_ExpressionTransfer = Callable[
    ["_SourceFlowAnalyzer", ast.expr, _State, _TransferContext], _ExprResult
]
_StatementTransfer = Callable[
    ["_SourceFlowAnalyzer", ast.stmt, _State, _TransferContext], _FlowResult
]
_PatternTransfer = Callable[
    ["_SourceFlowAnalyzer", ast.pattern, _AbsValue, _State, _TransferContext],
    tuple[
        _State | None,
        _State | None,
        _PolicyFacts,
        _DeferredEffects,
        _State | None,
    ],
]


def _instrument_expression_transfer(
    method: _ExpressionTransfer,
) -> _ExpressionTransfer:
    def wrapped(
        analyzer: _SourceFlowAnalyzer,
        node: ast.expr,
        state: _State,
        context: _TransferContext,
    ) -> _ExprResult:
        point = analyzer._begin_transfer("expression", node, state, context)
        result = method(analyzer, node, state, context)
        analyzer._finish_transfer(point, result)
        return result

    return wrapped


def _instrument_statement_transfer(
    method: _StatementTransfer,
) -> _StatementTransfer:
    def wrapped(
        analyzer: _SourceFlowAnalyzer,
        node: ast.stmt,
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        point = analyzer._begin_transfer("statement", node, state, context)
        result = method(analyzer, node, state, context)
        analyzer._finish_transfer(point, result)
        return result

    return wrapped


def _instrument_pattern_transfer(
    method: _PatternTransfer,
) -> _PatternTransfer:
    def wrapped(
        analyzer: _SourceFlowAnalyzer,
        pattern: ast.pattern,
        value: _AbsValue,
        state: _State,
        context: _TransferContext,
    ) -> tuple[
        _State | None,
        _State | None,
        _PolicyFacts,
        _DeferredEffects,
        _State | None,
    ]:
        point = analyzer._begin_transfer("pattern", pattern, state, context)
        result = method(analyzer, pattern, value, state, context)
        analyzer._finish_transfer(point, result)
        return result

    return wrapped


class _SourceFlowAnalyzer:
    def __init__(
        self,
        *,
        source_module: str,
        known_modules: frozenset[str],
        initializer_policy: _InitializerPolicy,
    ) -> None:
        self.source_module = source_module
        self.known_modules = known_modules
        self.initializer_policy = initializer_policy
        self._exact_sites_by_location = {
            site.location: site
            for site in initializer_policy.exact_call_sites
            if site.identity_node is None
        }
        self._exact_identity_sites = tuple(
            site
            for site in initializer_policy.exact_call_sites
            if site.identity_node is not None
        )
        self._future_annotations = False
        self._stats = _StatsBuilder()
        self._active_transfers: list[_ActiveTransfer] = []
        self._capture_point_outputs = True
        self._point_outputs: dict[_ProgramPoint, _State] = {}
        self._point_output_skeletons: dict[_ProgramPoint, _StateSkeleton] = {}
        self._suffix_edges: set[tuple[_ProgramPoint, _ProgramPoint]] = set()
        self._body_completion: dict[
            tuple[_DeferredKind, _SourceLocation], _ProgramPoint
        ] = {}
        self._suffix_cache: dict[
            _StateSkeleton, dict[_ProgramPoint, _State]
        ] = {}

    def analyze(self, tree: ast.Module) -> _ModuleFlowResult:
        self._stats.configure_height_bound(self._precomputed_height_bound(tree))
        self._future_annotations = any(
            isinstance(statement, ast.ImportFrom)
            and statement.module == "__future__"
            and any(alias.name == "annotations" for alias in statement.names)
            for statement in tree.body
        )
        declarations = self._scope_declarations(tree.body)
        module_global_names = {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Global)
            for name in node.names
        }
        module_names = declarations.local_names | module_global_names
        module_frame = _Frame.create(
            scope_id=_source_location(self.source_module, tree),
            kind="module",
            names=tuple(module_names),
        )
        state = _State((module_frame,))
        self._stats.observe_state(state)
        context = _TransferContext("eager", True, True, False)
        flow = self._transfer_statements(tree.body, state, context)
        self._capture_point_outputs = False
        final_state = flow.normal or state
        deferred_facts, deferred_effects = self._inspect_deferred_bodies(
            flow.deferred, final_state
        )
        all_deferred = _join_deferred(flow.deferred, deferred_effects)
        facts = _join_policy(flow.facts, deferred_facts)
        final_states = () if flow.normal is None else (flow.normal,)
        facts = _join_policy(
            facts,
            self._validate_exact_call_sites(facts.pending_exact_uses, final_states),
        )
        if all_deferred.unknown_outer_write:
            facts = _join_policy(
                facts,
                self._policy_error(
                    "deferred-effect",
                    tree,
                    "deferred write target could not be resolved",
                ),
            )
        stats = self._stats.freeze()
        iteration_budget = stats.program_points * (stats.computed_height_bound + 1)
        if stats.max_updates_per_program_point > stats.computed_height_bound:
            facts = _join_policy(
                facts,
                self._closure_error(tree, "source dataflow did not converge"),
            )
        if stats.worklist_pops > iteration_budget:
            facts = _join_policy(
                facts,
                self._closure_error(tree, "source dataflow worklist bound exceeded"),
            )
        if stats.transfer_steps > iteration_budget:
            facts = _join_policy(
                facts,
                self._closure_error(tree, "source dataflow transfer bound exceeded"),
            )
        return _ModuleFlowResult(final_states, facts, stats)

    def _exact_call_site(self, node: ast.AST) -> _ExactCallSite | None:
        for site in self._exact_identity_sites:
            if site.identity_node is node:
                return site
        return self._exact_sites_by_location.get(
            _source_location(self.source_module, node)
        )

    @staticmethod
    def _pending_exact_use(site: _ExactCallSite | None) -> _PolicyFacts:
        if site is None:
            return _PolicyFacts()
        return _PolicyFacts(pending_exact_uses=(site,))

    def _exact_use_identity_error(
        self,
        node: ast.Name,
        value: _AbsValue,
        maybe_unbound: bool,
        site: _ExactCallSite | None,
    ) -> _PolicyFacts:
        if site is None:
            return _PolicyFacts()
        expected = dict(site.required_bindings).get(node.id)
        identity = value.facts.identity
        if (
            expected is None
            or (
                not maybe_unbound
                and value.facts.complete
                and identity.state == "exact"
                and identity.identity == expected
            )
        ):
            return _PolicyFacts()
        detail = f"resolved binding mismatch at exact {site.role} use: {node.id}"
        if self.source_module in _PROJECTED_PACKAGE_ROOTS:
            return self._closure_error(
                node,
                f"initializer capability structure: {detail}",
            )
        return self._policy_error("namespace-reflection", node, detail)

    @staticmethod
    def _has_completed_identity(
        state: _State,
        name: str,
        expected: _ResolvedIdentity,
    ) -> bool:
        if any(frame.wildcard_shadowed for frame in state.frames):
            return False
        index = state._resolution_index(name)
        if index is None:
            return expected == _ResolvedIdentity("builtin", "builtins", name)
        slot = dict(state.frames[index].bindings)[name]
        return (
            slot.may_be_bound
            and not slot.may_be_unbound
            and slot.value.facts.complete
            and slot.value.facts.identity.state == "exact"
            and slot.value.facts.identity.identity == expected
        )

    def _validate_exact_call_sites(
        self,
        observed: tuple[_ExactCallSite, ...],
        final_states: tuple[_State, ...],
    ) -> _PolicyFacts:
        expected = frozenset(self.initializer_policy.exact_call_sites)
        seen = frozenset(observed)
        missing = expected.difference(seen)
        mismatches = {
            name
            for site in expected
            for name, identity in site.required_bindings
            if any(
                not self._has_completed_identity(state, name, identity)
                for state in final_states
            )
        }
        if not missing and not mismatches:
            return _PolicyFacts()
        details: list[str] = []
        if missing:
            details.append(
                "unobserved exact roles: "
                + ", ".join(sorted(site.role for site in missing))
            )
        if mismatches:
            details.append(
                "completed binding mismatch: " + ", ".join(sorted(mismatches))
            )
        detail = "; ".join(details)
        if self.source_module in _PROJECTED_PACKAGE_ROOTS:
            error = f"{self.source_module}:0:initializer capability structure: {detail}"
        else:
            error = (
                f"{self.source_module}:0:{detail}; "
                "source capability rejected: namespace-reflection"
            )
        return _PolicyFacts(closure_errors=frozenset({error}))

    def _exact_binding_write_error(
        self,
        node: ast.AST,
        name: str,
        detail: str,
    ) -> _PolicyFacts:
        protected = {
            binding
            for site in self.initializer_policy.exact_call_sites
            for binding, _ in site.required_bindings
        }
        if name not in protected:
            return self._policy_error("deferred-effect", node, detail)
        if self.source_module in _PROJECTED_PACKAGE_ROOTS:
            return self._closure_error(
                node,
                f"initializer capability structure: deferred write to {name}",
            )
        return self._policy_error(
            "namespace-reflection",
            node,
            f"completed binding mutation: deferred write to {name}",
        )

    def _precomputed_height_bound(self, tree: ast.Module) -> int:
        capability_bits = len(getattr(_Capability, "__args__", ()))
        value_height = 3 * (capability_bits + 2 + 2 + 1) + 5
        declarations = self._scope_declarations(tree.body)
        module_global_names = {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Global)
            for name in node.names
        }
        module_slots = len(declarations.local_names | module_global_names)
        maximum = 1 + module_slots * (value_height + 2) + 1
        pending: list[tuple[ast.AST, tuple[int, ...]]] = [
            (statement, (module_slots,)) for statement in reversed(tree.body)
        ]
        while pending:
            node, slot_counts = pending.pop()
            maximum = max(
                maximum,
                1 + sum(slot_counts) * (value_height + 2) + len(slot_counts),
            )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definition_children: tuple[ast.AST, ...] = (
                    *node.decorator_list,
                    *node.args.defaults,
                    *(item for item in node.args.kw_defaults if item is not None),
                    *(item for item in self._argument_annotations(node.args)),
                    *((node.returns,) if node.returns is not None else ()),
                    *getattr(node, "type_params", ()),
                )
                pending.extend(
                    (child, slot_counts) for child in reversed(definition_children)
                )
                child_declarations = self._scope_declarations(node.body, node.args)
                child_slots = (*slot_counts, len(child_declarations.local_names))
                maximum = max(
                    maximum,
                    1
                    + sum(child_slots) * (value_height + 2)
                    + len(child_slots),
                )
                pending.extend(
                    (statement, child_slots) for statement in reversed(node.body)
                )
                continue
            if isinstance(node, ast.ClassDef):
                definition_children = (
                    *node.decorator_list,
                    *node.bases,
                    *(keyword.value for keyword in node.keywords),
                    *getattr(node, "type_params", ()),
                )
                pending.extend(
                    (child, slot_counts) for child in reversed(definition_children)
                )
                child_declarations = self._scope_declarations(node.body)
                child_slots = (*slot_counts, len(child_declarations.local_names))
                maximum = max(
                    maximum,
                    1
                    + sum(child_slots) * (value_height + 2)
                    + len(child_slots),
                )
                pending.extend(
                    (statement, child_slots) for statement in reversed(node.body)
                )
                continue
            if isinstance(node, ast.Lambda):
                defaults = tuple(
                    default
                    for default in (*node.args.defaults, *node.args.kw_defaults)
                    if default is not None
                )
                pending.extend((default, slot_counts) for default in reversed(defaults))
                child_declarations = self._lambda_declarations(node)
                child_slots = (*slot_counts, len(child_declarations.local_names))
                maximum = max(
                    maximum,
                    1
                    + sum(child_slots) * (value_height + 2)
                    + len(child_slots),
                )
                pending.append((node.body, child_slots))
                continue
            if isinstance(
                node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
            ):
                pending.append((node.generators[0].iter, slot_counts))
                child_declarations = self._comprehension_declarations(node.generators)
                child_slots = (*slot_counts, len(child_declarations.local_names))
                maximum = max(
                    maximum,
                    1
                    + sum(child_slots) * (value_height + 2)
                    + len(child_slots),
                )
                deferred_children: list[ast.AST] = []
                for index, generator in enumerate(node.generators):
                    if index:
                        deferred_children.append(generator.iter)
                    deferred_children.extend(generator.ifs)
                if isinstance(node, ast.DictComp):
                    deferred_children.extend((node.key, node.value))
                else:
                    deferred_children.append(node.elt)
                pending.extend(
                    (child, child_slots) for child in reversed(deferred_children)
                )
                continue
            pending.extend(
                (child, slot_counts)
                for child in reversed(tuple(ast.iter_child_nodes(node)))
            )
        return max(1, maximum)

    def _scope_declarations(
        self,
        statements: Sequence[ast.stmt],
        arguments: ast.arguments | None = None,
    ) -> _ScopeDeclarations:
        collector = _ScopeDeclarationCollector(arguments)
        for statement in statements:
            collector.visit(statement)
        return collector.finish()

    def _lambda_declarations(self, node: ast.Lambda) -> _ScopeDeclarations:
        collector = _ScopeDeclarationCollector(node.args)
        collector.visit(node.body)
        return collector.finish()

    def _comprehension_declarations(
        self, generators: Sequence[ast.comprehension]
    ) -> _ScopeDeclarations:
        names: set[str] = set()
        for generator in generators:
            names.update(
                child.id
                for child in ast.walk(generator.target)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
            )
        return _ScopeDeclarations(frozenset(names), frozenset(), frozenset())

    def _builtin_value(self, name: str) -> _AbsValue:
        if name in {"__builtins__", "__dict__"}:
            return self._builtins_mapping_value()
        identity = _ResolvedIdentity("builtin", "builtins", name)
        capabilities: tuple[_Capability, ...] = ()
        if name == "__import__":
            capabilities = ("import-loader",)
        elif name in {"exec", "eval", "compile"}:
            capabilities = ("executable-code",)
        elif name in {"getattr", "vars", "globals", "locals"}:
            capabilities = ("namespace-reflection",)
        return _value_with_capabilities(*capabilities, identity=identity)

    @staticmethod
    def _has_builtins_origin(value: _AbsValue) -> bool:
        return "builtins-namespace" in _flatten_facts(value).may_capabilities

    @staticmethod
    def _is_builtins_mapping(value: _AbsValue) -> bool:
        return {
            "builtins-namespace",
            "namespace-mapping",
        }.issubset(value.facts.may_capabilities)

    @staticmethod
    def _builtins_mapping_value() -> _AbsValue:
        return _value_with_capabilities(
            "builtins-namespace", "namespace-mapping"
        )

    @staticmethod
    def _builtins_method_value(name: str, *, mapping: bool) -> _AbsValue:
        capabilities: tuple[_Capability, ...] = (
            ("builtins-namespace", "namespace-mapping")
            if mapping
            else ("builtins-namespace",)
        )
        owner = "namespace-mapping" if mapping else "namespace"
        return _value_with_capabilities(
            *capabilities,
            identity=_ResolvedIdentity(
                "literal", "builtins", f"{owner}.{name}"
            ),
        )

    @staticmethod
    def _builtins_method_name(value: _AbsValue) -> str | None:
        identity = value.facts.identity.identity
        if (
            not value.facts.complete
            or value.facts.identity.state != "exact"
            or identity is None
            or identity.kind != "literal"
            or identity.owner != "builtins"
        ):
            return None
        owner, separator, name = identity.name.partition(".")
        if separator and owner in {"namespace", "namespace-mapping"}:
            return name
        return None

    def _select_builtins_member(
        self, node: ast.AST, name: str
    ) -> tuple[_AbsValue, _PolicyFacts]:
        value = self._builtin_value(name)
        if name == "__import__":
            return value, self._policy_error(
                "dynamic-import", node, "runtime __import__ symbol access"
            )
        return value, _PolicyFacts()

    def _builtins_attribute_value(
        self, node: ast.AST, receiver: _AbsValue, attribute: str
    ) -> tuple[_AbsValue | None, _PolicyFacts]:
        if not self._has_builtins_origin(receiver):
            return None, _PolicyFacts()
        if self._builtins_method_name(receiver) is not None:
            if attribute == "__call__":
                return receiver, _PolicyFacts()
            return _value_with_capabilities(
                "executable-code", complete=False
            ), self._policy_error(
                "executable-code",
                node,
                "reflective builtins mapping method access",
            )
        if "builtins-namespace" not in receiver.facts.may_capabilities:
            return _derived_value(receiver, complete=False), _PolicyFacts()
        if attribute == "__dict__":
            return self._builtins_mapping_value(), _PolicyFacts()
        if self._is_builtins_mapping(receiver) and attribute in {
            "get",
            "__getitem__",
            "copy",
            "pop",
            "setdefault",
            "popitem",
            "values",
            "items",
            "clear",
            "update",
            "keys",
            "__iter__",
            "__reversed__",
            "__len__",
            "__contains__",
        }:
            return self._builtins_method_value(
                attribute, mapping=True
            ), _PolicyFacts()
        if attribute == "__getattribute__":
            return self._builtins_method_value(
                attribute, mapping=self._is_builtins_mapping(receiver)
            ), _PolicyFacts()
        return self._select_builtins_member(node, attribute)

    def _resolved_value(self, state: _State, name: str) -> tuple[_AbsValue, bool]:
        slot = state.resolve(name)
        if slot.may_be_bound:
            return slot.value, slot.may_be_unbound
        if not any(frame.wildcard_shadowed for frame in state.frames):
            return self._builtin_value(name), False
        return _join_values(_UNKNOWN_VALUE, self._builtin_value(name)), True

    def _program_point(
        self, kind: str, node: ast.AST, context: _TransferContext
    ) -> _ProgramPoint:
        return kind, _source_location(self.source_module, node), context.mode

    def _begin_transfer(
        self,
        kind: str,
        node: ast.AST,
        state: _State,
        context: _TransferContext,
    ) -> _ProgramPoint | None:
        self._stats.record_transfer(kind)
        point = self._program_point(kind, node, context)
        self._stats.program_points.add(point)
        self._stats.observe_state(state)
        if context.mode not in {"eager", "deferred"}:
            return None
        retained_for_suffix = kind in {"statement", "pattern"} or isinstance(
            node, (ast.NamedExpr, ast.Lambda, ast.GeneratorExp)
        )
        self._active_transfers.append(
            _ActiveTransfer(point, retained_for_suffix)
        )
        return point

    def _record_cfg_edge(
        self, source: _ProgramPoint | None, target: _ProgramPoint | None
    ) -> None:
        if source is not None and target is not None:
            self._stats.record_cfg_edge(source, target)

    def _record_suffix_edge(
        self, source: _ProgramPoint | None, target: _ProgramPoint | None
    ) -> None:
        if source is not None and target is not None and source != target:
            self._suffix_edges.add((source, target))

    def _finish_transfer(
        self,
        point: _ProgramPoint | None,
        result: _ExprResult
        | _FlowResult
        | tuple[
            _State | None,
            _State | None,
            _PolicyFacts,
            _DeferredEffects,
            _State | None,
        ],
    ) -> None:
        if point is None:
            return
        if not self._active_transfers or self._active_transfers[-1].point != point:
            raise ValueError("source-flow transfer stack mismatch")
        active = self._active_transfers.pop()
        self._record_cfg_edge(active.last_child, point)
        suffix_completion = active.last_suffix_child
        if active.retained_for_suffix:
            self._record_suffix_edge(active.last_suffix_child, point)
            suffix_completion = point
        states: tuple[_State | None, ...]
        if isinstance(result, _ExprResult):
            states = (
                None if result.truthy is None else result.truthy.state,
                None if result.falsy is None else result.falsy.state,
                result.raises,
            )
            deferred = result.deferred
        elif isinstance(result, _FlowResult):
            states = (
                result.normal,
                result.breaks,
                result.continues,
                result.returns,
                result.raises,
            )
            deferred = result.deferred
        else:
            states = (result[0], result[1], result[4])
            deferred = result[3]
        output = _join_states(*states)
        if (
            output is not None
            and self._capture_point_outputs
            and active.retained_for_suffix
        ):
            previous = self._point_outputs.get(point)
            if previous is None:
                self._point_outputs[point] = output
            else:
                self._point_outputs[point], _ = self._stats.merge_program_point(
                    point, previous, output
                )
            self._point_output_skeletons.setdefault(
                point, self._state_skeleton(output)
            )
        if self._capture_point_outputs:
            for body in deferred.bodies:
                if body.location == point[1]:
                    self._body_completion[(body.kind, body.location)] = point
        if self._active_transfers:
            parent = self._active_transfers[-1]
            if not (
                point[0] == "statement" and parent.point[0] == "statement"
            ):
                self._record_cfg_edge(parent.last_child, point)
                parent.last_child = point
                self._record_suffix_edge(
                    parent.last_suffix_child, suffix_completion
                )
                if suffix_completion is not None:
                    parent.last_suffix_child = suffix_completion

    def _join_program_point(
        self, point: _ProgramPoint, *states: _State | None
    ) -> _State | None:
        reachable = tuple(state for state in states if state is not None)
        if not reachable:
            return None
        result = reachable[0]
        for candidate in reachable[1:]:
            result, _ = self._stats.merge_program_point(
                point, result, candidate
            )
        return result

    def _closure_error(self, node: ast.AST, detail: str) -> _PolicyFacts:
        return _PolicyFacts(
            closure_errors=frozenset(
                {
                    f"{self.source_module}:{getattr(node, 'lineno', 0)}:{detail}"
                }
            )
        )

    def _policy_error(
        self, category: _PolicyCapability, node: ast.AST, detail: str
    ) -> _PolicyFacts:
        return self._closure_error(
            node, f"{detail}; source capability rejected: {category}"
        )

    def _reference_fact(
        self, target: str, context: _TransferContext
    ) -> _PolicyFacts:
        if context.emit_runtime_references:
            return _PolicyFacts(references=frozenset({_ImportReference(target, False)}))
        if context.emit_type_only_references:
            return _PolicyFacts(references=frozenset({_ImportReference(target, True)}))
        return _PolicyFacts()

    def _expr_from_parts(
        self,
        value: _AbsValue,
        state: _State,
        truth: _Truth,
        *,
        raises: _State | None = None,
        deferred: _DeferredEffects = _EMPTY_DEFERRED_EFFECTS,
        facts: _PolicyFacts = _EMPTY_POLICY_FACTS,
    ) -> _ExprResult:
        return _result_with(
            _normal_value(value, state, truth),
            raises=raises,
            deferred=deferred,
            facts=facts,
        )

    @_instrument_expression_transfer
    def _transfer_expression(
        self, node: ast.expr, state: _State, context: _TransferContext
    ) -> _ExprResult:
        if isinstance(node, ast.Constant):
            return self._expr_from_parts(
                _literal_value(node.value), state, _truth_for_constant(node.value)
            )
        if isinstance(node, ast.Name):
            return self._transfer_name(node, state, context)
        if isinstance(node, ast.Attribute):
            return self._transfer_attribute(node, state, context)
        if isinstance(node, ast.Subscript):
            return self._transfer_subscript(node, state, context)
        if isinstance(node, ast.Call):
            return self._transfer_call(node, state, context)
        if isinstance(node, ast.NamedExpr):
            value_result = self._transfer_expression(node.value, state, context)
            return self._bind_expression_target(
                node.target, value_result, context, operation="assign"
            )
        if isinstance(node, ast.BoolOp):
            return self._transfer_bool_op(node, state, context)
        if isinstance(node, ast.IfExp):
            return self._transfer_if_expression(node, state, context)
        if isinstance(node, ast.UnaryOp):
            operand = self._transfer_expression(node.operand, state, context)
            if isinstance(node.op, ast.Not):
                return _ExprResult(
                    None
                    if operand.falsy is None
                    else _NormalExit(_literal_value(True), operand.falsy.state),
                    None
                    if operand.truthy is None
                    else _NormalExit(_literal_value(False), operand.truthy.state),
                    operand.raises,
                    operand.deferred,
                    operand.facts,
                )
            post = operand.post_state
            if post is None:
                return operand
            return self._expr_from_parts(
                _UNKNOWN_VALUE,
                post,
                _Truth.UNKNOWN,
                raises=operand.raises,
                deferred=operand.deferred,
                facts=operand.facts,
            )
        if isinstance(node, ast.Compare):
            return self._transfer_compare(node, state, context)
        if isinstance(node, ast.Lambda):
            return self._transfer_lambda(node, state, context)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            return self._transfer_eager_comprehension(node, state, context)
        if isinstance(node, ast.GeneratorExp):
            return self._transfer_generator_expression(node, state, context)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            sequence = self._transfer_expression_sequence(node.elts, state, context)
            truth, outcomes = _literal_container_shape(node)
            return self._sequence_as_container(
                sequence,
                type(node).__name__.lower(),
                truth=truth,
                iteration_outcomes=outcomes,
            )
        if isinstance(node, ast.Dict):
            expressions = tuple(
                child
                for pair in zip(node.keys, node.values, strict=True)
                for child in pair
                if child is not None
            )
            sequence = self._transfer_expression_sequence(expressions, state, context)
            truth, outcomes = _literal_container_shape(node)
            result = self._sequence_as_container(
                sequence,
                "dict",
                truth=truth,
                iteration_outcomes=outcomes,
            )
            values = sequence[0]
            value_index = 0
            builtins_unpack = False
            for key in node.keys:
                if key is None:
                    builtins_unpack = builtins_unpack or self._has_builtins_origin(
                        values[value_index]
                    )
                    value_index += 1
                else:
                    value_index += 2
            post = result.post_state
            if not builtins_unpack or post is None:
                return result
            mapping = replace(
                self._builtins_mapping_value(),
                truth=result.value.truth,
                iteration_outcomes=result.value.iteration_outcomes,
                may_iteration_raise=result.value.may_iteration_raise,
            )
            return self._expr_from_parts(
                mapping,
                post,
                result.truth,
                raises=result.raises,
                deferred=result.deferred,
                facts=result.facts,
            )
        if isinstance(node, ast.BinOp):
            values, post, raises, deferred, facts = (
                self._transfer_expression_sequence(
                    (node.left, node.right), state, context
                )
            )
            if post is None:
                return _ExprResult(None, None, raises, deferred, facts)
            builtins_origin = any(
                self._has_builtins_origin(value) for value in values
            )
            value = _UNKNOWN_VALUE
            if isinstance(node.op, ast.BitOr) and builtins_origin:
                value = self._builtins_mapping_value()
            elif builtins_origin:
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "executable-code",
                        node,
                        "unsupported builtins-origin transform",
                    ),
                )
                value = _value_with_capabilities(
                    "executable-code", complete=False
                )
            return self._expr_from_parts(
                value,
                post,
                _Truth.UNKNOWN,
                raises=_join_states(raises, post),
                deferred=deferred,
                facts=facts,
            )
        if isinstance(node, ast.Await):
            return self._transfer_expression(node.value, state, context)
        if isinstance(node, ast.Yield):
            if node.value is None:
                return self._expr_from_parts(_SAFE_VALUE, state, _Truth.FALSE)
            return self._transfer_expression(node.value, state, context)
        if isinstance(node, ast.YieldFrom):
            return self._transfer_expression(node.value, state, context)
        if isinstance(node, ast.JoinedStr):
            sequence = self._transfer_expression_sequence(node.values, state, context)
            return self._sequence_as_unknown(sequence, complete=True)
        if isinstance(node, ast.FormattedValue):
            expressions = (node.value,) + (() if node.format_spec is None else (node.format_spec,))
            return self._transfer_generic_operands(expressions, state, context)
        if isinstance(node, ast.Starred):
            return self._transfer_expression(node.value, state, context)
        if isinstance(node, ast.Slice):
            expressions = tuple(
                item for item in (node.lower, node.upper, node.step) if item is not None
            )
            return self._transfer_generic_operands(expressions, state, context)
        return self._expr_from_parts(_UNKNOWN_VALUE, state, _Truth.UNKNOWN)

    def _transfer_name(
        self, node: ast.Name, state: _State, context: _TransferContext
    ) -> _ExprResult:
        if not isinstance(node.ctx, ast.Load):
            return self._expr_from_parts(_SAFE_VALUE, state, _Truth.UNKNOWN)
        resolution_index = state._resolution_index(node.id)
        if resolution_index is None:
            value, maybe_unbound = self._resolved_value(state, node.id)
        else:
            slot = dict(state.frames[resolution_index].bindings)[node.id]
            if not slot.may_be_bound:
                return _ExprResult(None, None, state)
            value = slot.value
            maybe_unbound = slot.may_be_unbound
        facts = _PolicyFacts()
        exact_site = self._exact_call_site(node)
        facts = _join_policy(facts, self._pending_exact_use(exact_site))
        facts = _join_policy(
            facts,
            self._exact_use_identity_error(node, value, maybe_unbound, exact_site),
        )
        if node.id == "__import__" and context.mode != "type-only":
            facts = self._policy_error(
                "dynamic-import", node, "runtime __import__ symbol access"
            )
        if (
            self.source_module in _PROJECTED_PACKAGE_ROOTS
            and "import-loader" in value.facts.may_capabilities
            and (
                exact_site is None
                or exact_site.role != "pep562-import-module"
            )
        ):
            facts = _join_policy(
                facts,
                self._closure_error(node, "runtime importlib loader symbol access"),
            )
        if self._is_type_checking_value(value):
            return _ExprResult(
                None,
                _NormalExit(value, state),
                state if maybe_unbound else None,
                facts=facts,
            )
        truth = _truth_for_value(value)
        return self._expr_from_parts(
            value,
            state,
            truth,
            raises=state if maybe_unbound else None,
            facts=facts,
        )

    def _transfer_expression_sequence(
        self,
        nodes: Sequence[ast.expr],
        state: _State,
        context: _TransferContext,
    ) -> tuple[
        tuple[_AbsValue, ...],
        _State | None,
        _State | None,
        _DeferredEffects,
        _PolicyFacts,
    ]:
        values: list[_AbsValue] = []
        current: _State | None = state
        unreachable_seed = state
        raises: _State | None = None
        deferred = _DeferredEffects()
        facts = _PolicyFacts()
        for node in nodes:
            if current is None:
                inspected = self._transfer_expression(
                    node,
                    unreachable_seed,
                    _TransferContext("unreachable", False, False, False),
                )
                values.append(inspected.value)
                deferred = _join_deferred(deferred, inspected.deferred)
                facts = _join_policy(facts, inspected.facts)
                continue
            result = self._transfer_expression(node, current, context)
            values.append(result.value)
            raises = _join_states(raises, result.raises)
            deferred = _join_deferred(deferred, result.deferred)
            facts = _join_policy(facts, result.facts)
            post = result.post_state
            if post is None:
                unreachable_seed = result.raises or current
                current = None
                continue
            current = post
            unreachable_seed = post
        return tuple(values), current, raises, deferred, facts

    def _sequence_as_container(
        self,
        sequence: tuple[
            tuple[_AbsValue, ...],
            _State | None,
            _State | None,
            _DeferredEffects,
            _PolicyFacts,
        ],
        kind: str,
        *,
        truth: _Truth,
        iteration_outcomes: frozenset[_IterationOutcome],
    ) -> _ExprResult:
        values, state, raises, deferred, facts = sequence
        if state is None:
            return _ExprResult(None, None, raises, deferred, facts)
        value = _container_value(
            values,
            kind=kind,
            truth=truth,
            iteration_outcomes=iteration_outcomes,
        )
        return self._expr_from_parts(
            value,
            state,
            truth,
            raises=raises,
            deferred=deferred,
            facts=facts,
        )

    def _sequence_as_unknown(
        self,
        sequence: tuple[
            tuple[_AbsValue, ...],
            _State | None,
            _State | None,
            _DeferredEffects,
            _PolicyFacts,
        ],
        *,
        complete: bool,
    ) -> _ExprResult:
        _, state, raises, deferred, facts = sequence
        if state is None:
            return _ExprResult(None, None, raises, deferred, facts)
        return self._expr_from_parts(
            _SAFE_VALUE if complete else _UNKNOWN_VALUE,
            state,
            _Truth.UNKNOWN,
            raises=raises,
            deferred=deferred,
            facts=facts,
        )

    def _transfer_generic_operands(
        self,
        nodes: Sequence[ast.expr],
        state: _State,
        context: _TransferContext,
    ) -> _ExprResult:
        return self._sequence_as_unknown(
            self._transfer_expression_sequence(nodes, state, context), complete=False
        )

    def _classify_member_selection(
        self,
        node: ast.AST,
        receiver: _AbsValue,
        member: str | None,
        default: _AbsValue,
        *,
        emit_policy: bool = True,
    ) -> tuple[_AbsValue, _PolicyFacts, bool]:
        capabilities = _flatten_facts(receiver).may_capabilities
        evaluation_scope = (
            _has_exact_identity(receiver, _evaluation_scope_identity())
            or "evaluation-scope" in capabilities
        )
        if member is None:
            if evaluation_scope:
                return (
                    default,
                    _protected_scope_fact(self.source_module, node, "<dynamic>"),
                    True,
                )
            return default, _PolicyFacts(), False
        if member in _UNIVERSAL_REFLECTION_MEMBERS:
            facts = (
                self._policy_error(
                    "namespace-reflection",
                    node,
                    f"sensitive attribute access: {member}",
                )
                if emit_policy
                else _PolicyFacts()
            )
            return (
                _value_with_capabilities("namespace-reflection", complete=False),
                facts,
                True,
            )
        if (
            "sys-module" in capabilities and member in _SYS_REGISTRY_MEMBERS
        ) or (member == "modules" and not receiver.facts.complete):
            facts = (
                self._policy_error(
                    "import-registry", node, "sensitive import registry access"
                )
                if emit_policy
                else _PolicyFacts()
            )
            return (
                _value_with_capabilities("import-registry", complete=False),
                facts,
                True,
            )
        if (
            "pkgutil-module" in capabilities
            and member in _PKGUTIL_LOADER_MEMBERS
        ) or (
            "zipimport-module" in capabilities and member == "zipimporter"
        ):
            facts = (
                self._policy_error(
                    "dynamic-import", node, "runtime dynamic import member access"
                )
                if emit_policy
                else _PolicyFacts()
            )
            return _value_with_capabilities("import-loader"), facts, True
        if (
            "operator-module" in capabilities
            and member in _OPERATOR_REFLECTION_MEMBERS
        ):
            facts = (
                self._policy_error(
                    "namespace-reflection", node, "runtime namespace reflection"
                )
                if emit_policy
                else _PolicyFacts()
            )
            return _value_with_capabilities("namespace-reflection"), facts, True
        if evaluation_scope and member in _PROTECTED_SCOPES:
            return (
                default,
                _protected_scope_fact(self.source_module, node, member),
                True,
            )
        if member == "plan_cases":
            return (
                _with_plan_cases_capability(default, receiver),
                _PolicyFacts(),
                True,
            )
        if "sys-module" in capabilities and member == "stdout":
            return _SAFE_VALUE, _PolicyFacts(), True
        return default, _PolicyFacts(), False

    def _transfer_attribute(
        self, node: ast.Attribute, state: _State, context: _TransferContext
    ) -> _ExprResult:
        receiver = self._transfer_expression(node.value, state, context)
        post = receiver.post_state
        if post is None:
            return receiver
        receiver_value = receiver.value
        capabilities = receiver_value.facts.may_capabilities
        facts = receiver.facts
        value = _derived_value(receiver_value, complete=receiver_value.facts.complete)
        package_target = (
            receiver_value.facts.package.target
            if receiver_value.facts.package.state == "exact"
            else None
        )
        if package_target is not None:
            candidate = f"{package_target}.{node.attr}"
            if candidate in self.known_modules:
                facts = _join_policy(facts, self._reference_fact(candidate, context))
                value = _value_with_capabilities("package-object", package=candidate)
            elif context.mode in {"eager", "deferred"}:
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "package-object",
                        node,
                        f"unresolved package attribute: {candidate}",
                    ),
                )
        elif "package-object" in capabilities and context.mode in {"eager", "deferred"}:
            facts = _join_policy(
                facts,
                self._policy_error(
                    "package-object", node, "ambiguous package attribute"
                ),
            )
        value, selection_facts, matched = self._classify_member_selection(
            node,
            receiver_value,
            node.attr,
            value,
        )
        facts = _join_policy(facts, selection_facts)
        if matched:
            pass
        elif (
            "typing-module" in capabilities
            and receiver_value.facts.complete
            and receiver_value.facts.identity.state == "exact"
            and node.attr == "TYPE_CHECKING"
        ):
            value = _value_with_capabilities(
                "type-checking-sentinel",
                identity=_ResolvedIdentity("imported", "typing", "TYPE_CHECKING"),
            )
        elif self._has_builtins_origin(receiver_value):
            builtins_value, builtins_facts = self._builtins_attribute_value(
                node, receiver_value, node.attr
            )
            if builtins_value is not None:
                value = builtins_value
            facts = _join_policy(facts, builtins_facts)
        elif "import-namespace" in capabilities and node.attr == "import_module":
            value = _value_with_capabilities(
                "import-loader",
                identity=_ResolvedIdentity("imported", "importlib", "import_module"),
            )
        elif "dynamic-loader-module" in capabilities and node.attr in {
            "run_module",
            "run_path",
        }:
            value = _value_with_capabilities(
                "import-loader",
                "dynamic-loader-module",
                identity=_ResolvedIdentity("imported", "runpy", node.attr),
            )
        return self._expr_from_parts(
            value,
            post,
            _Truth.UNKNOWN,
            raises=_join_states(receiver.raises, post),
            deferred=receiver.deferred,
            facts=facts,
        )

    def _transfer_subscript(
        self, node: ast.Subscript, state: _State, context: _TransferContext
    ) -> _ExprResult:
        values, post, raises, deferred, facts = self._transfer_expression_sequence(
            (node.value, node.slice), state, context
        )
        if post is None:
            return _ExprResult(None, None, raises, deferred, facts)
        container_value = values[0]
        element = _element_value(container_value)
        contained = container_value.contained
        selected_facts = _join_value_facts(element.facts, contained)
        selected_facts = replace(
            selected_facts,
            may_capabilities=(
                selected_facts.may_capabilities
                | container_value.facts.may_capabilities
            ),
        )
        value = _AbsValue(
            facts=selected_facts,
            iterable_element=element.iterable_element,
            contained=_join_value_facts(
                element.contained, _as_contained(contained)
            ),
        )
        literal_key = self._string_constant(node.slice)
        if self._is_builtins_mapping(container_value) and literal_key is not None:
            value, selection_facts = self._select_builtins_member(
                node, literal_key
            )
            facts = _join_policy(facts, selection_facts)
        elif self._is_builtins_mapping(container_value):
            facts = _join_policy(
                facts,
                self._policy_error(
                    "executable-code", node, "ambiguous builtins namespace lookup"
                ),
            )
            value = _value_with_capabilities("executable-code", complete=False)
        return self._expr_from_parts(
            value,
            post,
            _Truth.UNKNOWN,
            raises=_join_states(raises, post),
            deferred=deferred,
            facts=facts,
        )

    @staticmethod
    def _string_constant(node: ast.expr) -> str | None:
        return (
            node.value
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            else None
        )

    @staticmethod
    def _expanded_fixed_call_arguments(
        node: ast.Call,
        values: tuple[_AbsValue, ...],
    ) -> tuple[tuple[ast.expr, ...], tuple[_AbsValue, ...]] | None:
        if node.keywords:
            return None
        expanded_nodes: list[ast.expr] = []
        expanded_values: list[_AbsValue] = []
        for argument, value in zip(
            node.args, values[: len(node.args)], strict=True
        ):
            if not isinstance(argument, ast.Starred):
                expanded_nodes.append(argument)
                expanded_values.append(value)
                continue
            if not isinstance(argument.value, (ast.List, ast.Tuple)) or any(
                isinstance(element, ast.Starred)
                for element in argument.value.elts
            ):
                return None
            element_value = _element_value(value)
            expanded_nodes.extend(argument.value.elts)
            expanded_values.extend(
                element_value for _ in argument.value.elts
            )
        return tuple(expanded_nodes), tuple(expanded_values)

    def _transfer_call(
        self, node: ast.Call, state: _State, context: _TransferContext
    ) -> _ExprResult:
        function = self._transfer_expression(node.func, state, context)
        post = function.post_state
        if post is None:
            return function
        arguments = (*node.args, *(keyword.value for keyword in node.keywords))
        values, post, raises, deferred, facts = self._transfer_expression_sequence(
            arguments, post, context
        )
        facts = _join_policy(function.facts, facts)
        deferred = _join_deferred(function.deferred, deferred)
        raises = _join_states(function.raises, raises)
        if post is None:
            return _ExprResult(None, None, raises, deferred, facts)
        exact_site = self._exact_call_site(node.func)
        if exact_site is None:
            exact_site = self._exact_call_site(node)
        facts = _join_policy(facts, self._pending_exact_use(exact_site))
        raises = _join_states(raises, post)
        function_value = function.value
        capabilities = function_value.facts.may_capabilities
        value = _UNKNOWN_VALUE
        identity = function_value.facts.identity.identity
        exact_builtin = (
            identity.name
            if function_value.facts.complete
            and function_value.facts.identity.state == "exact"
            and identity is not None
            and identity.kind == "builtin"
            else None
        )
        exact_plan_cases = (
            function_value.facts.complete
            and function_value.facts.identity.state == "exact"
            and function_value.facts.identity.identity
            == _plan_cases_callable_identity()
        )
        builtins_method = self._builtins_method_name(function_value)
        if (
            builtins_method == "__getattribute__"
            and self._is_builtins_mapping(function_value)
        ):
            facts = _join_policy(
                facts,
                self._policy_error(
                    "executable-code",
                    node,
                    "builtins mapping __getattribute__ lookup",
                ),
            )
            value = _value_with_capabilities(
                "executable-code", complete=False
            )
        elif builtins_method in {"get", "__getitem__", "__getattribute__"}:
            expanded_arguments = self._expanded_fixed_call_arguments(
                node, values
            )
            expanded_nodes = (
                () if expanded_arguments is None else expanded_arguments[0]
            )
            valid_arity = (
                bool(expanded_nodes)
                and (
                    len(expanded_nodes) <= 2
                    if builtins_method == "get"
                    else len(expanded_nodes) == 1
                )
            )
            literal_key = (
                self._string_constant(expanded_nodes[0])
                if valid_arity
                else None
            )
            if literal_key is None:
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "executable-code",
                        node,
                        "ambiguous builtins namespace lookup",
                    ),
                )
                value = _value_with_capabilities(
                    "executable-code", complete=False
                )
            elif (
                builtins_method == "get"
                and literal_key not in vars(_python_builtins)
            ):
                assert expanded_arguments is not None
                value = (
                    expanded_arguments[1][1]
                    if len(expanded_arguments[1]) == 2
                    else _literal_value(None)
                )
            else:
                value, selection_facts = self._select_builtins_member(
                    node, literal_key
                )
                facts = _join_policy(facts, selection_facts)
        elif builtins_method == "copy" and not node.args and not node.keywords:
            value = self._builtins_mapping_value()
        elif builtins_method in {
            "pop",
            "setdefault",
            "popitem",
            "values",
            "items",
            "clear",
            "update",
        }:
            facts = _join_policy(
                facts,
                self._policy_error(
                    "executable-code",
                    node,
                    "builtins mapping value exposure or mutation",
                ),
            )
            value = _value_with_capabilities(
                "executable-code", complete=False
            )
        elif builtins_method in {
            "keys",
            "__iter__",
            "__reversed__",
            "__len__",
            "__contains__",
        }:
            value = _SAFE_VALUE
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "__getattribute__"
        ):
            expanded_arguments = self._expanded_fixed_call_arguments(
                node, values
            )
            selection_receiver: _AbsValue | None = None
            member_node: ast.expr | None = None
            if expanded_arguments is not None:
                expanded_nodes, expanded_values = expanded_arguments
                if len(expanded_nodes) == 1:
                    selection_receiver = function_value
                    member_node = expanded_nodes[0]
                elif len(expanded_nodes) == 2:
                    selection_receiver = expanded_values[0]
                    member_node = expanded_nodes[1]
            member = (
                None
                if member_node is None
                else self._string_constant(member_node)
            )
            if selection_receiver is None or member is None:
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "namespace-reflection",
                        node,
                        "broad non-literal __getattribute__ access",
                    ),
                )
                value = _value_with_capabilities(
                    "namespace-reflection", complete=False
                )
            else:
                default = _derived_value(
                    selection_receiver,
                    complete=selection_receiver.facts.complete,
                )
                value, selection_facts, _ = self._classify_member_selection(
                    node,
                    selection_receiver,
                    member,
                    default,
                )
                facts = _join_policy(facts, selection_facts)
        elif exact_builtin == "getattr":
            value, call_facts = self._transfer_getattr_call(
                node, values, context, exact_site
            )
            facts = _join_policy(facts, call_facts)
        elif exact_builtin in {"vars", "globals", "locals"}:
            if exact_builtin == "vars" and values and (
                "builtins-namespace" in values[0].facts.may_capabilities
            ):
                value = _value_with_capabilities(
                    "namespace-mapping", "builtins-namespace"
                )
            elif (
                exact_builtin == "globals"
                and exact_site is not None
                and exact_site.role
                in {"pep562-cache-globals", "pep562-dir-globals"}
            ):
                value = _value_with_capabilities("namespace-mapping")
            else:
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "namespace-reflection", node, "runtime namespace reflection"
                    ),
                )
                value = _value_with_capabilities("namespace-reflection", complete=False)
        elif exact_builtin in {"exec", "eval", "compile"}:
            facts = _join_policy(
                facts,
                self._policy_error(
                    "executable-code",
                    node,
                    f"runtime executable code: {exact_builtin}",
                ),
            )
            value = _value_with_capabilities("executable-code", complete=False)
        elif "executable-code" in capabilities:
            facts = _join_policy(
                facts,
                self._policy_error(
                    "executable-code",
                    node,
                    "runtime executable code through incomplete callable",
                ),
            )
            value = _value_with_capabilities("executable-code", complete=False)
        elif self._has_builtins_origin(function_value):
            facts = _join_policy(
                facts,
                self._policy_error(
                    "executable-code",
                    node,
                    "ambiguous builtins-origin operation",
                ),
            )
            value = _value_with_capabilities(
                "executable-code", complete=False
            )
        if "import-loader" in capabilities:
            legacy_detail: str | None = None
            if "dynamic-loader-module" in capabilities:
                legacy_detail = "runtime runpy loader"
            else:
                legacy_detail = "runtime importlib import"
            facts = _join_policy(
                facts,
                self._dynamic_import_call_facts(
                    node,
                    context,
                    exact_site=exact_site,
                    legacy_detail=legacy_detail,
                ),
            )
            value = _value_with_capabilities("package-object", complete=False)
        if "dynamic-loader-module" in capabilities:
            facts = _join_policy(
                facts,
                self._policy_error("dynamic-import", node, "runtime runpy loader"),
            )
        if "namespace-reflection" in capabilities and exact_builtin not in {
            "getattr",
            "vars",
            "globals",
            "locals",
        } and exact_site is None:
            facts = _join_policy(
                facts,
                self._policy_error(
                    "namespace-reflection", node, "runtime namespace reflection"
                ),
            )
        call_name = _call_name(node.func)
        allowed_plan_roles = {
            "study-truth-development-plan",
            "study-truth-legacy-plan",
        }
        exact_approved_plan_call = (
            exact_plan_cases
            and exact_site is not None
            and exact_site.role in allowed_plan_roles
        )
        if (
            call_name == "plan_cases"
            or exact_plan_cases
            or "plan-cases-callable" in capabilities
        ) and not exact_approved_plan_call:
            facts = _join_policy(
                facts,
                _PolicyFacts(
                    study_forbidden_calls=frozenset(
                        {
                            f"{self.source_module}:{node.lineno}:"
                            "plan_cases outside DevelopmentCorpusProvider"
                        }
                    )
                ),
            )
        elif call_name in _FORBIDDEN_CALL_NAMES or call_name == "FreeCADExportAdapter":
            facts = _join_policy(
                facts,
                _PolicyFacts(
                    forbidden_calls=frozenset(
                        {f"{self.source_module}:{node.lineno}:{call_name}"}
                    )
                ),
            )
        crossing = _ValueFacts()
        for argument in values:
            crossing = _join_value_facts(crossing, _flatten_facts(argument))
        sensitive_crossing = crossing.may_capabilities.intersection(
            {
                "builtins-namespace",
                "import-loader",
                "import-registry",
                "namespace-reflection",
                "namespace-mapping",
                "executable-code",
                "package-object",
            }
        )
        if (
            sensitive_crossing
            and exact_builtin not in {"getattr", "vars", "len"}
            and exact_site is None
        ):
            category: _PolicyCapability = "namespace-reflection"
            if "builtins-namespace" in sensitive_crossing:
                category = "executable-code"
            elif "import-loader" in sensitive_crossing:
                category = "dynamic-import"
            elif "import-registry" in sensitive_crossing:
                category = "import-registry"
            elif "executable-code" in sensitive_crossing:
                category = "executable-code"
            elif "package-object" in sensitive_crossing:
                category = "package-object"
            facts = _join_policy(
                facts,
                self._policy_error(category, node, "capability crossed unknown call"),
            )
        protected_crossing = crossing.may_capabilities.intersection(
            {"evaluation-scope", "plan-cases-callable"}
        )
        if value is _UNKNOWN_VALUE and protected_crossing:
            value = _value_with_capabilities(*protected_crossing, complete=False)
        return self._expr_from_parts(
            value,
            post,
            _Truth.UNKNOWN,
            raises=raises,
            deferred=deferred,
            facts=facts,
        )

    def _transfer_getattr_call(
        self,
        node: ast.Call,
        values: tuple[_AbsValue, ...],
        context: _TransferContext,
        exact_site: _ExactCallSite | None,
    ) -> tuple[_AbsValue, _PolicyFacts]:
        if len(node.args) < 2 or len(values) < 2:
            return _UNKNOWN_VALUE, self._policy_error(
                "namespace-reflection", node, "broad getattr access"
            )
        receiver = values[0]
        attribute = self._string_constant(node.args[1])
        if attribute is None:
            if exact_site is not None and exact_site.role in {
                "pep562-getattr",
                "cli-dataclass-getattr",
            }:
                return _UNKNOWN_VALUE, _PolicyFacts()
            value, facts, matched = self._classify_member_selection(
                node,
                receiver,
                None,
                _UNKNOWN_VALUE,
            )
            if matched:
                return value, facts
            if "package-object" in receiver.facts.may_capabilities:
                return _UNKNOWN_VALUE, self._policy_error(
                    "package-object", node, "runtime package-object import"
                )
            if "import-namespace" in receiver.facts.may_capabilities:
                return _UNKNOWN_VALUE, self._closure_error(
                    node, "runtime importlib import: non-literal reflected import loader"
                )
            return _UNKNOWN_VALUE, self._policy_error(
                "namespace-reflection", node, "broad non-literal getattr access"
            )
        value = _derived_value(receiver, complete=receiver.facts.complete)
        facts = _PolicyFacts()
        package_target = (
            receiver.facts.package.target
            if receiver.facts.package.state == "exact"
            else None
        )
        if package_target is not None:
            candidate = f"{package_target}.{attribute}"
            if candidate in self.known_modules:
                value = _value_with_capabilities(
                    "package-object", package=candidate
                )
                facts = self._reference_fact(candidate, context)
            else:
                value = _UNKNOWN_VALUE
                facts = self._policy_error(
                    "package-object",
                    node,
                    f"unresolved package attribute: {candidate}",
                )
        value, selection_facts, matched = self._classify_member_selection(
            node,
            receiver,
            attribute,
            value,
        )
        facts = _join_policy(facts, selection_facts)
        if matched:
            return value, facts
        if attribute == "__import__":
            return _value_with_capabilities("import-loader"), _join_policy(
                facts,
                self._policy_error(
                    "dynamic-import", node, "runtime __import__ symbol access"
                ),
            )
        if self._has_builtins_origin(receiver):
            builtins_value, builtins_facts = self._builtins_attribute_value(
                node, receiver, attribute
            )
            if builtins_value is not None:
                return builtins_value, _join_policy(facts, builtins_facts)
        if (
            "import-namespace" in receiver.facts.may_capabilities
            and attribute == "import_module"
        ):
            return _value_with_capabilities(
                "import-loader",
                identity=_ResolvedIdentity("imported", "importlib", "import_module"),
            ), facts
        return value, facts

    def _dynamic_import_call_facts(
        self,
        node: ast.Call,
        context: _TransferContext,
        *,
        exact_site: _ExactCallSite | None,
        legacy_detail: str | None,
    ) -> _PolicyFacts:
        if exact_site is not None and exact_site.role == "pep562-import-module":
            return _PolicyFacts()
        detail_prefix = "" if legacy_detail is None else f"{legacy_detail}; "
        if not node.args:
            return self._policy_error(
                "dynamic-import",
                node,
                f"{detail_prefix}non-literal dynamic package import",
            )
        target = self._string_constant(node.args[0])
        if target is None:
            return self._policy_error(
                "dynamic-import",
                node,
                f"{detail_prefix}non-literal dynamic package import",
            )
        if not _is_package_target(target):
            return self._policy_error(
                "dynamic-import", node, f"{detail_prefix}runtime dynamic import"
            )
        if target not in self.known_modules:
            return self._closure_error(
                node,
                f"{detail_prefix}unresolved dynamic package import: {target}",
            )
        return _join_policy(
            self._reference_fact(target, context),
            self._policy_error(
                "dynamic-import",
                node,
                f"{detail_prefix}runtime dynamic package import",
            ),
        )

    def _bind_expression_target(
        self,
        target: ast.expr,
        result: _ExprResult,
        context: _TransferContext,
        *,
        operation: _WriteKind,
    ) -> _ExprResult:
        deferred = result.deferred
        facts = result.facts
        exits: list[_NormalExit | None] = []
        for exit in (result.truthy, result.falsy):
            if exit is None:
                exits.append(None)
                continue
            bound_state, effect, binding_facts = self._bind_target(
                target,
                exit.value,
                exit.state,
                context,
                operation=operation,
                named_expression=isinstance(target, ast.Name)
                and isinstance(target.ctx, ast.Store),
            )
            deferred = _join_deferred(deferred, effect)
            facts = _join_policy(facts, binding_facts)
            exits.append(_NormalExit(exit.value, bound_state))
        return _ExprResult(exits[0], exits[1], result.raises, deferred, facts)

    def _bind_target(
        self,
        target: ast.expr,
        value: _AbsValue,
        state: _State,
        context: _TransferContext,
        *,
        operation: _WriteKind,
        named_expression: bool = False,
    ) -> tuple[_State, _DeferredEffects, _PolicyFacts]:
        if isinstance(target, ast.Name):
            index = self._target_frame_index(
                state, target.id, named_expression=named_expression
            )
            if index is None:
                return state, _DeferredEffects(unknown_outer_write=True), self._policy_error(
                    "deferred-effect", target, "unresolved deferred write"
                )
            frames = list(state.frames)
            if target.id not in dict(frames[index].bindings):
                return state, _DeferredEffects(unknown_outer_write=True), self._closure_error(
                    target, f"binding skeleton does not contain {target.id}"
                )
            frames[index] = frames[index].replace_binding(
                target.id, _BindingSlot(value)
            )
            new_state = _State(tuple(frames))
            if context.mode == "deferred" and index < len(state.frames) - 1:
                kind: _DeferredKind = (
                    "generator"
                    if state.frames[-1].kind == "comprehension"
                    else "function"
                )
                timing: _DeferredTiming = "on-iteration" if kind == "generator" else "on-call"
                write = _DeferredWrite(
                    kind,
                    target.id,
                    _source_location(self.source_module, target),
                    frames[index].scope_id,
                    operation,
                    value,
                    timing,
                    "zero-or-many" if kind == "generator" else "zero-or-one",
                )
                return (
                    new_state,
                    _DeferredEffects(writes=(write,)),
                    self._exact_binding_write_error(
                        target,
                        target.id,
                        "deferred outer binding write",
                    ),
                )
            return new_state, _DeferredEffects(), _PolicyFacts()
        if isinstance(target, ast.Starred):
            return self._bind_target(
                target.value,
                _element_value(value),
                state,
                context,
                operation=operation,
                named_expression=named_expression,
            )
        if isinstance(target, (ast.Tuple, ast.List)):
            current = state
            deferred = _DeferredEffects()
            facts = _PolicyFacts()
            promoted = _element_value(value)
            for element in target.elts:
                current, effect, element_facts = self._bind_target(
                    element,
                    promoted,
                    current,
                    context,
                    operation=operation,
                    named_expression=named_expression,
                )
                deferred = _join_deferred(deferred, effect)
                facts = _join_policy(facts, element_facts)
            return current, deferred, facts
        return state, _DeferredEffects(), _PolicyFacts()

    def _target_frame_index(
        self, state: _State, name: str, *, named_expression: bool
    ) -> int | None:
        current = state.frames[-1]
        if named_expression and current.kind == "comprehension":
            for index in range(len(state.frames) - 2, -1, -1):
                if state.frames[index].kind != "comprehension":
                    current = state.frames[index]
                    if name in current.global_names:
                        return 0
                    if name in current.nonlocal_names:
                        for outer in range(index - 1, 0, -1):
                            if (
                                state.frames[outer].kind != "class"
                                and name in dict(state.frames[outer].bindings)
                            ):
                                return outer
                        return None
                    return index
            return None
        return state.binding_frame_index(name)

    def _transfer_bool_op(
        self, node: ast.BoolOp, state: _State, context: _TransferContext
    ) -> _ExprResult:
        active: _State | None = state
        truthy: _NormalExit | None = None
        falsy: _NormalExit | None = None
        raises: _State | None = None
        deferred = _DeferredEffects()
        facts = _PolicyFacts()
        is_and = isinstance(node.op, ast.And)
        for index, operand in enumerate(node.values):
            if active is None:
                inspected = self._transfer_expression(
                    operand,
                    state,
                    _TransferContext("unreachable", False, False, False),
                )
                deferred = _join_deferred(deferred, inspected.deferred)
                facts = _join_policy(facts, inspected.facts)
                continue
            result = self._transfer_expression(operand, active, context)
            raises = _join_states(raises, result.raises)
            deferred = _join_deferred(deferred, result.deferred)
            facts = _join_policy(facts, result.facts)
            last = index == len(node.values) - 1
            if is_and:
                falsy = self._join_normal_exits(falsy, result.falsy)
                if last:
                    truthy = self._join_normal_exits(truthy, result.truthy)
                active = None if result.truthy is None else result.truthy.state
            else:
                truthy = self._join_normal_exits(truthy, result.truthy)
                if last:
                    falsy = self._join_normal_exits(falsy, result.falsy)
                active = None if result.falsy is None else result.falsy.state
        return _ExprResult(truthy, falsy, raises, deferred, facts)

    @staticmethod
    def _join_normal_exits(
        left: _NormalExit | None, right: _NormalExit | None
    ) -> _NormalExit | None:
        if left is None:
            return right
        if right is None:
            return left
        return _NormalExit(
            _join_values(left.value, right.value), left.state.join(right.state)
        )

    def _transfer_if_expression(
        self, node: ast.IfExp, state: _State, context: _TransferContext
    ) -> _ExprResult:
        condition = self._transfer_expression(node.test, state, context)
        capture_state = condition.post_state or state
        branches: list[_ExprResult] = []
        for exit, expression in (
            (condition.truthy, node.body),
            (condition.falsy, node.orelse),
        ):
            if exit is None:
                branches.append(
                    _policy_only_expression(
                        self._transfer_expression(
                            expression,
                            capture_state,
                            _TransferContext("unreachable", False, False, False),
                        ),
                        capture_state,
                    )
                )
            else:
                branches.append(self._transfer_expression(expression, exit.state, context))
        return _ExprResult(
            self._join_normal_exits(branches[0].truthy, branches[1].truthy),
            self._join_normal_exits(branches[0].falsy, branches[1].falsy),
            _join_states(condition.raises, *(branch.raises for branch in branches)),
            _join_deferred(condition.deferred, *(branch.deferred for branch in branches)),
            _join_policy(condition.facts, *(branch.facts for branch in branches)),
        )

    @staticmethod
    def _is_foldable_identity_literal(node: ast.expr) -> bool:
        return isinstance(node, ast.Constant) and (
            node.value is None
            or node.value is True
            or node.value is False
            or node.value is Ellipsis
        )

    def _compare_pair_truth(
        self,
        left_node: ast.expr,
        right_node: ast.expr,
        op: ast.cmpop,
        left: _AbsValue,
        right: _AbsValue,
    ) -> _Truth:
        if isinstance(left_node, ast.Constant) and isinstance(right_node, ast.Constant):
            try:
                if isinstance(op, ast.Eq):
                    return (
                        _Truth.TRUE
                        if left_node.value == right_node.value
                        else _Truth.FALSE
                    )
                if isinstance(op, ast.NotEq):
                    return (
                        _Truth.TRUE
                        if left_node.value != right_node.value
                        else _Truth.FALSE
                    )
                if isinstance(op, (ast.Is, ast.IsNot)) and self._is_foldable_identity_literal(
                    left_node
                ) and self._is_foldable_identity_literal(right_node):
                    same = left_node.value is right_node.value
                    if isinstance(op, ast.Is):
                        return _Truth.TRUE if same else _Truth.FALSE
                    return _Truth.FALSE if same else _Truth.TRUE
            except (TypeError, ValueError):
                return _Truth.UNKNOWN
        if isinstance(op, (ast.Is, ast.IsNot)):
            exact_sys_mismatch = (
                _has_exact_sys_module(left)
                and right.facts.complete
                and "sys-module" not in right.facts.may_capabilities
            ) or (
                _has_exact_sys_module(right)
                and left.facts.complete
                and "sys-module" not in left.facts.may_capabilities
            )
            if exact_sys_mismatch:
                return _Truth.FALSE if isinstance(op, ast.Is) else _Truth.TRUE
        return _Truth.UNKNOWN

    def _transfer_compare(
        self, node: ast.Compare, state: _State, context: _TransferContext
    ) -> _ExprResult:
        left_result = self._transfer_expression(node.left, state, context)
        active = left_result.post_state
        active_value = left_result.value
        truthy: _NormalExit | None = None
        falsy: _NormalExit | None = None
        raises = left_result.raises
        deferred = left_result.deferred
        facts = left_result.facts
        unreachable_seed = active if active is not None else left_result.raises or state
        previous_node = node.left

        for index, (op, comparator) in enumerate(
            zip(node.ops, node.comparators, strict=True)
        ):
            if active is None:
                inspected = self._transfer_expression(
                    comparator,
                    unreachable_seed,
                    _TransferContext("unreachable", False, False, False),
                )
                deferred = _join_deferred(deferred, inspected.deferred)
                facts = _join_policy(facts, inspected.facts)
                previous_node = comparator
                continue

            right_result = self._transfer_expression(comparator, active, context)
            raises = _join_states(raises, right_result.raises)
            deferred = _join_deferred(deferred, right_result.deferred)
            facts = _join_policy(facts, right_result.facts)
            post = right_result.post_state
            if post is None:
                active = None
                unreachable_seed = right_result.raises or active or unreachable_seed
                previous_node = comparator
                continue

            pair = _normal_value(
                _SAFE_VALUE,
                post,
                self._compare_pair_truth(
                    previous_node, comparator, op, active_value, right_result.value
                ),
            )
            falsy = self._join_normal_exits(falsy, pair.falsy)
            if index == len(node.ops) - 1:
                truthy = self._join_normal_exits(truthy, pair.truthy)
            active = None if pair.truthy is None else pair.truthy.state
            active_value = right_result.value
            unreachable_seed = post
            previous_node = comparator

        return _ExprResult(truthy, falsy, raises, deferred, facts)

    def _transfer_lambda(
        self, node: ast.Lambda, state: _State, context: _TransferContext
    ) -> _ExprResult:
        defaults = tuple(
            default
            for default in (*node.args.defaults, *node.args.kw_defaults)
            if default is not None
        )
        _, post, raises, deferred, facts = self._transfer_expression_sequence(
            defaults, state, context
        )
        if post is None:
            return _ExprResult(None, None, raises, deferred, facts)
        location = _source_location(self.source_module, node)
        body = _DeferredBody(
            "lambda", location, post.frames[-1].scope_id, post, node
        )
        deferred = _join_deferred(deferred, _DeferredEffects(bodies=(body,)))
        value = _value_with_capabilities(
            identity=_ResolvedIdentity("function", self.source_module, "<lambda>", location)
        )
        return self._expr_from_parts(
            value,
            post,
            _Truth.TRUE,
            raises=raises,
            deferred=deferred,
            facts=facts,
        )

    def _transfer_eager_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp,
        state: _State,
        context: _TransferContext,
    ) -> _ExprResult:
        generators = node.generators
        outer = self._transfer_expression(generators[0].iter, state, context)
        outer_state = outer.post_state
        if outer_state is None:
            return outer
        outer_outcomes = outer.value.iteration_outcomes
        raises = _join_states(
            outer.raises,
            outer_state if outer.value.may_iteration_raise else None,
        )
        if not outer_outcomes:
            return _ExprResult(
                None,
                None,
                raises,
                outer.deferred,
                outer.facts,
            )
        declarations = self._comprehension_declarations(generators)
        frame = _Frame.create(
            scope_id=_source_location(self.source_module, node),
            kind="comprehension",
            names=tuple(declarations.local_names),
        )
        base = outer_state.push(frame)
        self._stats.observe_state(base)
        values: list[_AbsValue] = []
        exits: list[_State] = []
        may_be_empty = "zero" in outer.value.iteration_outcomes
        deferred = outer.deferred
        facts = outer.facts
        if "zero" in outer_outcomes:
            exits.append(base.pop())
        if outer_outcomes.intersection({"one", "many"}):
            (
                iteration,
                produced,
                step_may_skip,
                step_raises,
                step_deferred,
                step_facts,
            ) = self._comprehension_step(node, 0, base, outer.value, context)
            may_be_empty = may_be_empty or step_may_skip
            projected_step_raises = (
                None if step_raises is None else step_raises.pop()
            )
            raises = _join_states(raises, projected_step_raises)
            deferred = _join_deferred(deferred, step_deferred)
            facts = _join_policy(facts, step_facts)
            if iteration is not None:
                projected_iteration = iteration.pop()
                exits.append(projected_iteration)
                if outer.value.may_iteration_raise:
                    raises = _join_states(raises, projected_iteration)
            values.extend(produced)
            if "many" in outer_outcomes and iteration is not None:
                loop_point: _ProgramPoint = (
                    "comprehension-loop",
                    _source_location(self.source_module, node),
                    context.mode,
                )
                self._stats.program_points.add(loop_point)
                self._stats.worklist_pops += 1
                header, _ = self._stats.merge_program_point(
                    loop_point, base, iteration
                )
                while True:
                    self._stats.worklist_pops += 1
                    (
                        next_state,
                        next_values,
                        next_may_skip,
                        next_raises,
                        next_deferred,
                        next_facts,
                    ) = self._comprehension_step(node, 0, header, outer.value, context)
                    may_be_empty = may_be_empty or next_may_skip
                    projected_next_raises = (
                        None if next_raises is None else next_raises.pop()
                    )
                    raises = _join_states(raises, projected_next_raises)
                    deferred = _join_deferred(deferred, next_deferred)
                    facts = _join_policy(facts, next_facts)
                    values.extend(next_values)
                    if next_state is None:
                        break
                    if outer.value.may_iteration_raise:
                        raises = _join_states(raises, next_state.pop())
                    header, changed = self._stats.merge_program_point(
                        loop_point, header, next_state
                    )
                    if not changed:
                        exits.append(next_state.pop())
                        break
                    if (
                        self._stats.updates_by_program_point.get(loop_point, 0)
                        > (self._stats.precomputed_height_bound or 1)
                    ):
                        facts = _join_policy(
                            facts,
                            self._closure_error(node, "source dataflow did not converge"),
                        )
                        break
        post = _join_states(*exits)
        if post is None:
            return _ExprResult(None, None, raises, deferred, facts)
        truth = (
            _Truth.FALSE
            if not values
            else _Truth.UNKNOWN
            if may_be_empty
            else _Truth.TRUE
        )
        result_outcomes: frozenset[_IterationOutcome]
        if truth is _Truth.FALSE:
            result_outcomes = frozenset({"zero"})
        elif truth is _Truth.TRUE:
            result_outcomes = frozenset({"one", "many"})
        else:
            result_outcomes = frozenset({"zero", "one", "many"})
        value = _container_value(
            values,
            kind=type(node).__name__.lower(),
            truth=truth,
            iteration_outcomes=result_outcomes,
        )
        return self._expr_from_parts(
            value,
            post,
            truth,
            raises=raises,
            deferred=deferred,
            facts=facts,
        )

    def _comprehension_step(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        index: int,
        state: _State,
        iterable: _AbsValue,
        context: _TransferContext,
        *,
        bind_target: bool = True,
    ) -> tuple[
        _State | None,
        list[_AbsValue],
        bool,
        _State | None,
        _DeferredEffects,
        _PolicyFacts,
    ]:
        generator = node.generators[index]
        if bind_target:
            current, deferred, facts = self._bind_target(
                generator.target,
                _element_value(iterable),
                state,
                context,
                operation="assign",
            )
        else:
            current = state
            deferred = _DeferredEffects()
            facts = _PolicyFacts()
        raises: _State | None = None
        completed: _State | None = None
        may_skip = False
        for condition in generator.ifs:
            result = self._transfer_expression(condition, current, context)
            raises = _join_states(raises, result.raises)
            deferred = _join_deferred(deferred, result.deferred)
            facts = _join_policy(facts, result.facts)
            completed = _join_states(
                completed,
                None if result.falsy is None else result.falsy.state,
            )
            may_skip = may_skip or result.falsy is not None
            if result.truthy is None:
                return completed, [], True, raises, deferred, facts
            current = result.truthy.state
        if index + 1 < len(node.generators):
            next_generator = node.generators[index + 1]
            next_iterable = self._transfer_expression(next_generator.iter, current, context)
            raises = _join_states(raises, next_iterable.raises)
            deferred = _join_deferred(deferred, next_iterable.deferred)
            facts = _join_policy(facts, next_iterable.facts)
            next_state = next_iterable.post_state
            nested_values: list[_AbsValue] = []
            if (
                next_state is not None
                and next_iterable.value.may_iteration_raise
            ):
                raises = _join_states(raises, next_state)
            if next_state is not None and next_iterable.value.iteration_outcomes.intersection(
                {"one", "many"}
            ):
                (
                    nested_state,
                    nested_values,
                    nested_may_skip,
                    nested_raises,
                    nested_deferred,
                    nested_facts,
                ) = self._comprehension_step(
                    node, index + 1, next_state, next_iterable.value, context
                )
                completed = _join_states(completed, nested_state)
                may_skip = may_skip or nested_may_skip
                raises = _join_states(raises, nested_raises)
                deferred = _join_deferred(deferred, nested_deferred)
                facts = _join_policy(facts, nested_facts)
            if "zero" in next_iterable.value.iteration_outcomes:
                completed = _join_states(completed, next_state)
                may_skip = True
            return completed, nested_values, may_skip, raises, deferred, facts
        expressions: tuple[ast.expr, ...] = (
            (node.key, node.value)
            if isinstance(node, ast.DictComp)
            else (node.elt,)
        )
        (
            values,
            result_state,
            expression_raises,
            expression_deferred,
            expression_facts,
        ) = self._transfer_expression_sequence(expressions, current, context)
        return (
            _join_states(completed, result_state),
            list(values),
            may_skip,
            _join_states(raises, expression_raises),
            _join_deferred(deferred, expression_deferred),
            _join_policy(facts, expression_facts),
        )

    def _transfer_generator_expression(
        self, node: ast.GeneratorExp, state: _State, context: _TransferContext
    ) -> _ExprResult:
        outer = self._transfer_expression(node.generators[0].iter, state, context)
        post = outer.post_state
        if post is None:
            return outer
        raises = _join_states(
            outer.raises,
            post if outer.value.may_iteration_raise else None,
        )
        if not outer.value.iteration_outcomes:
            return _ExprResult(
                None,
                None,
                raises,
                outer.deferred,
                outer.facts,
            )
        frame = _Frame.create(
            scope_id=_source_location(self.source_module, node),
            kind="comprehension",
            names=tuple(self._comprehension_declarations(node.generators).local_names),
        )
        deferred_state = post.push(frame)
        deferred_context = _TransferContext("deferred", True, True, False)
        deferred_state, effects, facts = self._bind_target(
            node.generators[0].target,
            _element_value(outer.value),
            deferred_state,
            deferred_context,
            operation="assign",
        )
        generator_value = _AbsValue(
            truth=_Truth.TRUE,
            iterable_element=_ValueFacts(complete=False),
            contained=_ValueFacts(complete=False),
            iteration_outcomes=frozenset({"zero", "one", "many"}),
            may_iteration_raise=True,
        )
        body = _DeferredBody(
            "generator",
            _source_location(self.source_module, node),
            post.frames[-1].scope_id,
            deferred_state,
            node,
        )
        return self._expr_from_parts(
            generator_value,
            post,
            _Truth.TRUE,
            raises=raises,
            deferred=_join_deferred(
                outer.deferred, effects, _DeferredEffects(bodies=(body,))
            ),
            facts=_join_policy(outer.facts, facts),
        )

    def _transfer_statements(
        self,
        statements: Sequence[ast.stmt],
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        current: _State | None = state
        breaks: _State | None = None
        continues: _State | None = None
        returns: _State | None = None
        exceptions = _ExceptionalExits()
        deferred = _DeferredEffects()
        facts = _PolicyFacts()
        unreachable_seed = state
        runtime = context.mode in {"eager", "deferred"}
        parent_point = (
            self._active_transfers[-1].point
            if runtime and self._active_transfers
            else None
        )
        entry_predecessor = (
            self._active_transfers[-1].last_child
            if runtime and self._active_transfers
            else None
        )
        entry_suffix_predecessor = (
            self._active_transfers[-1].last_suffix_child
            if runtime and self._active_transfers
            else None
        )
        normal_predecessor: _ProgramPoint | None = None
        terminal_point: _ProgramPoint | None = None
        for statement in statements:
            if current is None:
                inspected = self._transfer_statement(
                    statement,
                    unreachable_seed,
                    _TransferContext("unreachable", False, False, False),
                )
                deferred = _join_deferred(deferred, inspected.deferred)
                facts = _join_policy(facts, inspected.facts)
                continue
            point = self._program_point("statement", statement, context)
            self._record_cfg_edge(
                normal_predecessor or entry_predecessor,
                point,
            )
            self._record_suffix_edge(
                normal_predecessor or entry_suffix_predecessor,
                point,
            )
            result = self._transfer_statement(statement, current, context)
            breaks = _join_states(breaks, result.breaks)
            continues = _join_states(continues, result.continues)
            returns = _join_states(returns, result.returns)
            exceptions = _join_exceptions(exceptions, result.exceptions)
            deferred = _join_deferred(deferred, result.deferred)
            facts = _join_policy(facts, result.facts)
            unreachable_seed = current
            current = result.normal
            terminal_point = point
            normal_predecessor = point if current is not None else None
            entry_predecessor = None
            entry_suffix_predecessor = None
        self._record_cfg_edge(terminal_point, parent_point)
        self._record_suffix_edge(terminal_point, parent_point)
        return _FlowResult(
            current, breaks, continues, returns, exceptions, deferred, facts
        )

    @_instrument_statement_transfer
    def _transfer_statement(
        self, node: ast.stmt, state: _State, context: _TransferContext
    ) -> _FlowResult:
        if isinstance(node, ast.Expr):
            result = self._transfer_expression(node.value, state, context)
            return _FlowResult(
                result.post_state,
                exceptions=_unknown_exceptions(result.raises),
                deferred=result.deferred,
                facts=result.facts,
            )
        if isinstance(node, ast.Assign):
            value_result = self._transfer_expression(node.value, state, context)
            current = value_result.post_state
            deferred = value_result.deferred
            facts = value_result.facts
            raises = value_result.raises
            if current is None:
                return _FlowResult(
                    None,
                    exceptions=_unknown_exceptions(raises),
                    deferred=deferred,
                    facts=facts,
                )
            for target in node.targets:
                bound_value = self._reviewed_literal_value(
                    node, target, value_result.value
                )
                current, target_raises, target_deferred, target_facts = self._transfer_store_target(
                    target, current, context, stored_value=bound_value
                )
                raises = _join_states(raises, target_raises)
                deferred = _join_deferred(deferred, target_deferred)
                facts = _join_policy(facts, target_facts)
                if current is None:
                    return _FlowResult(
                        None,
                        exceptions=_unknown_exceptions(raises),
                        deferred=deferred,
                        facts=facts,
                    )
                current, effect, binding_facts = self._bind_target(
                    target,
                    bound_value,
                    current,
                    context,
                    operation="assign",
                )
                deferred = _join_deferred(deferred, effect)
                facts = _join_policy(facts, binding_facts)
            return _FlowResult(
                current,
                exceptions=_unknown_exceptions(raises),
                deferred=deferred,
                facts=facts,
            )
        if isinstance(node, ast.AnnAssign):
            annotation_context = (
                _TransferContext("postponed-annotation", False, False, False)
                if self._future_annotations
                else context
            )
            annotation = self._transfer_expression(node.annotation, state, annotation_context)
            current = state if self._future_annotations else annotation.post_state
            raises = None if self._future_annotations else annotation.raises
            deferred = annotation.deferred
            facts = annotation.facts
            value = _SAFE_VALUE
            if current is None:
                if node.value is not None:
                    inspected = self._transfer_expression(
                        node.value,
                        annotation.raises or state,
                        _TransferContext("unreachable", False, False, False),
                    )
                    deferred = _join_deferred(deferred, inspected.deferred)
                    facts = _join_policy(facts, inspected.facts)
                return _FlowResult(
                    None,
                    exceptions=_unknown_exceptions(raises),
                    deferred=deferred,
                    facts=facts,
                )
            if node.value is not None:
                result = self._transfer_expression(node.value, current, context)
                value = self._reviewed_literal_value(node, node.target, result.value)
                raises = _join_states(raises, result.raises)
                deferred = _join_deferred(deferred, result.deferred)
                facts = _join_policy(facts, result.facts)
                current = result.post_state
                if current is None:
                    return _FlowResult(
                        None,
                        exceptions=_unknown_exceptions(raises),
                        deferred=deferred,
                        facts=facts,
                    )
            current, target_raises, target_deferred, target_facts = self._transfer_store_target(
                node.target, current, context, stored_value=value
            )
            if current is None:
                return _FlowResult(
                    None,
                    exceptions=_unknown_exceptions(
                        _join_states(raises, target_raises)
                    ),
                    deferred=_join_deferred(deferred, target_deferred),
                    facts=_join_policy(facts, target_facts),
                )
            current, effect, binding_facts = self._bind_target(
                node.target, value, current, context, operation="assign"
            )
            return _FlowResult(
                current,
                exceptions=_unknown_exceptions(
                    _join_states(raises, target_raises)
                ),
                deferred=_join_deferred(deferred, target_deferred, effect),
                facts=_join_policy(facts, target_facts, binding_facts),
            )
        if isinstance(node, ast.AugAssign):
            target_result = self._transfer_expression(node.target, state, context)
            current = target_result.post_state
            if current is None:
                return _FlowResult(
                    None,
                    exceptions=_unknown_exceptions(target_result.raises),
                    deferred=target_result.deferred,
                    facts=target_result.facts,
                )
            value_result = self._transfer_expression(node.value, current, context)
            current = value_result.post_state
            if current is None:
                return _FlowResult(
                    None,
                    exceptions=_unknown_exceptions(
                        _join_states(target_result.raises, value_result.raises)
                    ),
                    deferred=_join_deferred(
                        target_result.deferred, value_result.deferred
                    ),
                    facts=_join_policy(target_result.facts, value_result.facts),
                )
            prior = target_result.value
            value = _join_values(prior, _UNKNOWN_VALUE)
            mutation_facts = _PolicyFacts()
            if isinstance(node.op, ast.BitOr) and (
                self._has_builtins_origin(prior)
                or self._has_builtins_origin(value_result.value)
            ):
                mutation_facts = self._policy_error(
                    "executable-code",
                    node,
                    "heapless builtins-origin augmented mapping mutation",
                )
                value = self._builtins_mapping_value()
            current, effect, binding_facts = self._bind_target(
                node.target, value, current, context, operation="augment"
            )
            return _FlowResult(
                current,
                exceptions=_unknown_exceptions(
                    _join_states(target_result.raises, value_result.raises)
                ),
                deferred=_join_deferred(
                    target_result.deferred, value_result.deferred, effect
                ),
                facts=_join_policy(
                    target_result.facts,
                    value_result.facts,
                    mutation_facts,
                    binding_facts,
                ),
            )
        if isinstance(node, ast.Delete):
            current = state
            delete_raises: _State | None = None
            deferred = _DeferredEffects()
            facts = _PolicyFacts()
            for target in node.targets:
                target_result = self._transfer_expression(target, current, context)
                current = target_result.post_state or current
                delete_raises = _join_states(delete_raises, target_result.raises)
                deferred = _join_deferred(deferred, target_result.deferred)
                facts = _join_policy(facts, target_result.facts)
                current, effect, delete_facts = self._delete_target(
                    target, current, context
                )
                deferred = _join_deferred(deferred, effect)
                facts = _join_policy(facts, delete_facts)
            return _FlowResult(
                current,
                exceptions=_unknown_exceptions(delete_raises),
                deferred=deferred,
                facts=facts,
            )
        if isinstance(node, ast.Import):
            return self._transfer_import(node, state, context)
        if isinstance(node, ast.ImportFrom):
            return self._transfer_import_from(node, state, context)
        if isinstance(node, ast.Return):
            if node.value is None:
                return _FlowResult(None, returns=state)
            result = self._transfer_expression(node.value, state, context)
            return _FlowResult(
                None,
                returns=result.post_state,
                exceptions=_unknown_exceptions(result.raises),
                deferred=result.deferred,
                facts=result.facts,
            )
        if isinstance(node, ast.Raise):
            expressions = tuple(
                expression for expression in (node.exc, node.cause) if expression is not None
            )
            values, post, raises, deferred, facts = self._transfer_expression_sequence(
                expressions, state, context
            )
            exceptions = _unknown_exceptions(raises)
            if node.exc is None:
                exceptions = _join_exceptions(
                    exceptions, _unknown_exceptions(post)
                )
            elif post is not None:
                identity = values[0].facts.identity.identity
                if (
                    values[0].facts.complete
                    and values[0].facts.identity.state == "exact"
                    and identity is not None
                    and identity.kind == "builtin"
                    and identity.owner == "builtins"
                    and identity.name
                    in _PROVABLE_BUILTIN_EXCEPTION_SUPERTYPES
                ):
                    exceptions = _join_exceptions(
                        exceptions,
                        _ExceptionalExits(((identity, post),)),
                    )
                else:
                    exceptions = _join_exceptions(
                        exceptions, _unknown_exceptions(post)
                    )
            return _FlowResult(
                None,
                exceptions=exceptions,
                deferred=deferred,
                facts=facts,
            )
        if isinstance(node, ast.Break):
            return _FlowResult(None, breaks=state)
        if isinstance(node, ast.Continue):
            return _FlowResult(None, continues=state)
        if isinstance(node, (ast.Pass, ast.Global, ast.Nonlocal)):
            return _FlowResult(state)
        if isinstance(node, ast.If):
            return self._transfer_if_statement(node, state, context)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._transfer_function_definition(node, state, context)
        if isinstance(node, ast.ClassDef):
            return self._transfer_class_definition(node, state, context)
        if isinstance(node, (ast.For, ast.AsyncFor)):
            return self._transfer_for(node, state, context)
        if isinstance(node, ast.While):
            return self._transfer_while(node, state, context)
        if isinstance(node, ast.Match):
            return self._transfer_match(node, state, context)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return self._transfer_with(node, state, context)
        if isinstance(node, (ast.Try, ast.TryStar)):
            return self._transfer_try(node, state, context)
        if isinstance(node, ast.Assert):
            result = self._transfer_expression(node.test, state, context)
            if node.msg is not None and result.falsy is not None:
                message = self._transfer_expression(node.msg, result.falsy.state, context)
                return _FlowResult(
                    None if result.truthy is None else result.truthy.state,
                    exceptions=_unknown_exceptions(
                        _join_states(
                            result.raises,
                            result.falsy.state,
                            message.raises,
                        )
                    ),
                    deferred=_join_deferred(result.deferred, message.deferred),
                    facts=_join_policy(result.facts, message.facts),
                )
            return _FlowResult(
                None if result.truthy is None else result.truthy.state,
                exceptions=_unknown_exceptions(
                    _join_states(
                        result.raises,
                        None if result.falsy is None else result.falsy.state,
                    )
                ),
                deferred=result.deferred,
                facts=result.facts,
            )
        inspected_deferred, inspected_facts = self._inspect_unsupported_children(
            node, state
        )
        return _FlowResult(
            state,
            deferred=inspected_deferred,
            facts=_join_policy(
                inspected_facts,
                self._closure_error(
                    node, f"unsupported source-flow syntax: {type(node).__name__}"
                ),
            ),
        )

    def _inspect_unsupported_children(
        self, node: ast.AST, state: _State
    ) -> tuple[_DeferredEffects, _PolicyFacts]:
        context = _TransferContext("unreachable", False, False, False)
        deferred = _DeferredEffects()
        facts = _PolicyFacts()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                expr_result = self._transfer_expression(child, state, context)
                deferred = _join_deferred(deferred, expr_result.deferred)
                facts = _join_policy(facts, expr_result.facts)
            elif isinstance(child, ast.stmt):
                statement_result = self._transfer_statement(child, state, context)
                deferred = _join_deferred(deferred, statement_result.deferred)
                facts = _join_policy(facts, statement_result.facts)
            elif isinstance(child, ast.pattern):
                _, _, child_facts, child_deferred, _ = self._transfer_pattern(
                    child, _UNKNOWN_VALUE, state, context
                )
                deferred = _join_deferred(deferred, child_deferred)
                facts = _join_policy(facts, child_facts)
            else:
                child_deferred, child_facts = self._inspect_unsupported_children(
                    child, state
                )
                deferred = _join_deferred(deferred, child_deferred)
                facts = _join_policy(facts, child_facts)
        return deferred, facts

    def _reviewed_literal_value(
        self,
        statement: ast.Assign | ast.AnnAssign,
        target: ast.expr,
        value: _AbsValue,
    ) -> _AbsValue:
        if (
            self.source_module not in _PROJECTED_PACKAGE_ROOTS
            or not isinstance(target, ast.Name)
            or target.id not in {"_LAZY_EXPORTS", "__all__"}
            or not isinstance(
                statement.value,
                (ast.Dict, ast.List, ast.Tuple, ast.Set),
            )
        ):
            return value
        identity = _ResolvedIdentity(
            "literal",
            self.source_module,
            target.id,
            _source_location(self.source_module, statement),
        )
        return replace(
            value,
            facts=replace(value.facts, identity=_exact_identity(identity)),
        )

    def _transfer_store_target(
        self,
        target: ast.expr,
        state: _State,
        context: _TransferContext,
        *,
        stored_value: _AbsValue | None = None,
    ) -> tuple[_State | None, _State | None, _DeferredEffects, _PolicyFacts]:
        if isinstance(target, ast.Attribute):
            result = self._transfer_expression(target.value, state, context)
            facts = result.facts
            if self._has_builtins_origin(result.value) or (
                stored_value is not None
                and self._has_builtins_origin(stored_value)
            ):
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "executable-code",
                        target,
                        "heapless builtins-origin attribute mutation",
                    ),
                )
            return (
                result.post_state,
                result.raises,
                result.deferred,
                facts,
            )
        if isinstance(target, ast.Subscript):
            values, post, raises, deferred, facts = self._transfer_expression_sequence(
                (target.value, target.slice), state, context
            )
            if self._has_builtins_origin(values[0]) or (
                stored_value is not None
                and self._has_builtins_origin(stored_value)
            ):
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "executable-code",
                        target,
                        "heapless builtins-origin subscript mutation",
                    ),
                )
            return post, raises, deferred, facts
        if isinstance(target, ast.Starred):
            return self._transfer_store_target(
                target.value,
                state,
                context,
                stored_value=stored_value,
            )
        if isinstance(target, (ast.Tuple, ast.List)):
            current: _State | None = state
            tuple_raises: _State | None = None
            deferred = _DeferredEffects()
            facts = _PolicyFacts()
            for element in target.elts:
                if current is None:
                    break
                (
                    current,
                    element_raises,
                    element_deferred,
                    element_facts,
                ) = self._transfer_store_target(element, current, context)
                tuple_raises = _join_states(tuple_raises, element_raises)
                deferred = _join_deferred(deferred, element_deferred)
                facts = _join_policy(facts, element_facts)
            return current, tuple_raises, deferred, facts
        return state, None, _DeferredEffects(), _PolicyFacts()

    def _delete_target(
        self,
        target: ast.expr,
        state: _State,
        context: _TransferContext,
    ) -> tuple[_State, _DeferredEffects, _PolicyFacts]:
        if isinstance(target, ast.Name):
            index = state.binding_frame_index(target.id)
            if index is None:
                return state, _DeferredEffects(unknown_outer_write=True), self._closure_error(
                    target, "unresolved nonlocal binding"
                )
            frames = list(state.frames)
            if target.id not in dict(frames[index].bindings):
                return state, _DeferredEffects(unknown_outer_write=True), self._closure_error(
                    target, f"binding skeleton does not contain {target.id}"
                )
            frames[index] = frames[index].replace_binding(
                target.id, _BindingSlot(_UNKNOWN_VALUE, False, True)
            )
            new_state = _State(tuple(frames))
            if context.mode == "deferred" and index < len(state.frames) - 1:
                write = _DeferredWrite(
                    "function",
                    target.id,
                    _source_location(self.source_module, target),
                    frames[index].scope_id,
                    "delete",
                    _UNKNOWN_VALUE,
                    "on-call",
                    "zero-or-one",
                )
                return (
                    new_state,
                    _DeferredEffects(writes=(write,)),
                    self._exact_binding_write_error(
                        target,
                        target.id,
                        "deferred outer binding delete",
                    ),
                )
            return new_state, _DeferredEffects(), _PolicyFacts()
        if isinstance(target, ast.Starred):
            return self._delete_target(target.value, state, context)
        if isinstance(target, (ast.Tuple, ast.List)):
            current = state
            deferred = _DeferredEffects()
            facts = _PolicyFacts()
            for element in target.elts:
                current, effect, element_facts = self._delete_target(
                    element, current, context
                )
                deferred = _join_deferred(deferred, effect)
                facts = _join_policy(facts, element_facts)
            return current, deferred, facts
        return state, _DeferredEffects(), _PolicyFacts()

    def _import_value(self, module: str, imported_name: str | None = None) -> _AbsValue:
        if module == "builtins" and imported_name is not None:
            return self._builtin_value(imported_name)
        capabilities: list[_Capability] = []
        package: str | None = None
        identity: _ResolvedIdentity | None = _ResolvedIdentity(
            "imported", module, "<module>"
        )
        if imported_name is None:
            if module == "sys":
                capabilities.append("sys-module")
            elif module == "typing":
                capabilities.append("typing-module")
            elif module == "builtins":
                capabilities.append("builtins-namespace")
            elif module == "importlib":
                capabilities.append("import-namespace")
            elif module == "runpy":
                capabilities.append("dynamic-loader-module")
            elif module == "pkgutil":
                capabilities.append("pkgutil-module")
            elif module == "zipimport":
                capabilities.append("zipimport-module")
            elif module == "operator":
                capabilities.append("operator-module")
            if module in _PROJECTED_PACKAGE_ROOTS:
                capabilities.append("package-object")
                package = module
        else:
            identity = _ResolvedIdentity("imported", module, imported_name)
            if (
                module == "manufacturing_vision_studio.e1.domain_v2"
                and imported_name == "EvaluationScope"
            ):
                capabilities = ["evaluation-scope"]
            elif module == "typing" and imported_name == "TYPE_CHECKING":
                capabilities = ["type-checking-sentinel"]
            elif module == "importlib" and imported_name == "import_module":
                capabilities = ["import-loader"]
            elif module == "runpy" and imported_name in {"run_module", "run_path"}:
                capabilities = ["import-loader", "dynamic-loader-module"]
        return _value_with_capabilities(
            *capabilities, package=package, identity=identity
        )

    def _transfer_import(
        self, node: ast.Import, state: _State, context: _TransferContext
    ) -> _FlowResult:
        current = state
        facts = _PolicyFacts()
        deferred = _DeferredEffects()
        for alias in node.names:
            if context.mode != "type-only" and alias.name in _PROJECTED_PACKAGE_ROOTS:
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "package-object",
                        node,
                        f"runtime package-object import: {alias.name}",
                    ),
                )
            if context.mode != "type-only" and _is_importlib_target(alias.name):
                facts = _join_policy(
                    facts,
                    self._closure_error(node, f"runtime importlib import: {alias.name}"),
                )
            target = _nearest_known_module(alias.name, self.known_modules)
            if _is_package_target(alias.name) and target != alias.name:
                facts = _join_policy(
                    facts,
                    self._closure_error(
                        node, f"unresolved project import: {alias.name}"
                    ),
                )
            elif target is not None:
                facts = _join_policy(facts, self._reference_fact(target, context))
            bound_name = alias.asname or alias.name.split(".", 1)[0]
            imported_module = alias.name if alias.asname else alias.name.split(".", 1)[0]
            value = self._import_value(imported_module)
            current, effect, binding_facts = self._bind_target(
                ast.Name(
                    id=bound_name,
                    ctx=ast.Store(),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                ),
                value,
                current,
                context,
                operation="import",
            )
            deferred = _join_deferred(deferred, effect)
            facts = _join_policy(facts, binding_facts)
        return _FlowResult(current, deferred=deferred, facts=facts)

    def _transfer_import_from(
        self, node: ast.ImportFrom, state: _State, context: _TransferContext
    ) -> _FlowResult:
        current = state
        exact_site = self._exact_call_site(node)
        facts = self._pending_exact_use(exact_site)
        deferred = _DeferredEffects()
        if (
            context.mode != "type-only"
            and node.level == 0
            and _is_importlib_target(node.module)
            and (
                exact_site is None
                or exact_site.role != "pep562-import-module"
            )
        ):
            facts = _join_policy(
                facts,
                self._closure_error(node, f"runtime importlib import: {node.module}"),
            )
        base = _resolve_import_from_base(self.source_module, node.module, node.level)
        if base is None:
            if any(alias.name == "*" for alias in node.names):
                facts = _join_policy(
                    facts,
                    self._closure_error(node, "unresolved wildcard import source"),
                )
            return _FlowResult(current, facts=facts)
        if (
            not any(alias.name == "*" for alias in node.names)
            and _is_package_target(base)
            and base not in self.known_modules
        ):
            facts = _join_policy(
                facts,
                self._closure_error(node, f"unresolved project import: {base}"),
            )
            return _FlowResult(current, facts=facts)
        for alias in node.names:
            if alias.name == "*":
                target = _nearest_known_module(base, self.known_modules)
                if (
                    _is_package_target(base)
                    and target != base
                ):
                    facts = _join_policy(
                        facts,
                        self._closure_error(
                            node, f"unresolved wildcard package import: {base}"
                        ),
                    )
                elif target is not None:
                    facts = _join_policy(
                        facts, self._reference_fact(target, context)
                    )
                frames = list(current.frames)
                frames[-1] = frames[-1].with_wildcard()
                current = _State(tuple(frames))
                continue
            candidate = f"{base}.{alias.name}"
            if (
                base in _PROJECTED_PACKAGE_ROOTS
                and candidate not in self.known_modules
                and context.mode != "type-only"
            ):
                facts = _join_policy(
                    facts,
                    self._closure_error(
                        node, f"unresolved package symbol import: {candidate}"
                    ),
                )
                continue
            target = _nearest_known_module(candidate, self.known_modules)
            if target is None:
                target = _nearest_known_module(base, self.known_modules)
            if target is not None:
                facts = _join_policy(facts, self._reference_fact(target, context))
            if (
                node.level == 0
                and node.module == "builtins"
                and alias.name == "__import__"
                and context.mode != "type-only"
            ):
                facts = _join_policy(
                    facts,
                    self._policy_error(
                        "dynamic-import", node, "runtime __import__ symbol access"
                    ),
                )
            value = self._import_value(base, alias.name)
            if candidate in _PROJECTED_PACKAGE_ROOTS:
                value = _value_with_capabilities("package-object", package=candidate)
            elif candidate in self.known_modules:
                value = _value_with_capabilities(
                    identity=_ResolvedIdentity(
                        "imported", candidate, "<module>"
                    )
                )
            owner = self._import_value(base)
            value, selection_facts, _ = self._classify_member_selection(
                node,
                owner,
                alias.name,
                value,
                emit_policy=context.mode != "type-only",
            )
            facts = _join_policy(facts, selection_facts)
            bound_name = alias.asname or alias.name
            synthetic = ast.Name(
                id=bound_name,
                ctx=ast.Store(),
                lineno=node.lineno,
                col_offset=node.col_offset,
            )
            current, effect, binding_facts = self._bind_target(
                synthetic, value, current, context, operation="import"
            )
            deferred = _join_deferred(deferred, effect)
            facts = _join_policy(facts, binding_facts)
        return _FlowResult(current, deferred=deferred, facts=facts)

    def _transfer_if_statement(
        self, node: ast.If, state: _State, context: _TransferContext
    ) -> _FlowResult:
        condition = self._transfer_expression(node.test, state, context)
        type_only = self._is_type_checking_value(condition.value)
        if type_only:
            inspected = self._transfer_statements(
                node.body,
                condition.post_state or state,
                _TransferContext("type-only", False, False, True),
            )
            normal = self._transfer_statements(
                node.orelse,
                condition.falsy.state if condition.falsy is not None else state,
                context,
            )
            return _FlowResult(
                normal.normal,
                normal.breaks,
                normal.continues,
                normal.returns,
                _join_exceptions(
                    _unknown_exceptions(condition.raises),
                    normal.exceptions,
                ),
                _join_deferred(condition.deferred, inspected.deferred, normal.deferred),
                _join_policy(condition.facts, inspected.facts, normal.facts),
            )
        branches: list[_FlowResult] = []
        for exit, statements in (
            (condition.truthy, node.body),
            (condition.falsy, node.orelse),
        ):
            if exit is None:
                capture_state = condition.post_state or state
                branches.append(
                    _policy_only_statement(
                        self._transfer_statements(
                            statements,
                            capture_state,
                            _TransferContext("unreachable", False, False, False),
                        ),
                        capture_state,
                    )
                )
            else:
                branches.append(self._transfer_statements(statements, exit.state, context))
        point = self._program_point("statement", node, context)
        joined = _FlowResult(
            self._join_program_point(
                point, *(branch.normal for branch in branches)
            ),
            _join_states(*(branch.breaks for branch in branches)),
            _join_states(*(branch.continues for branch in branches)),
            _join_states(*(branch.returns for branch in branches)),
            _join_exceptions(*(branch.exceptions for branch in branches)),
            _join_deferred(*(branch.deferred for branch in branches)),
            _join_policy(*(branch.facts for branch in branches)),
        )
        return _FlowResult(
            joined.normal,
            joined.breaks,
            joined.continues,
            joined.returns,
            _join_exceptions(
                _unknown_exceptions(condition.raises),
                joined.exceptions,
            ),
            _join_deferred(condition.deferred, joined.deferred),
            _join_policy(condition.facts, joined.facts),
        )

    @staticmethod
    def _is_type_checking_value(value: _AbsValue) -> bool:
        return (
            value.facts.complete
            and value.facts.may_capabilities == frozenset({"type-checking-sentinel"})
            and value.facts.identity.state == "exact"
            and value.facts.identity.identity
            == _ResolvedIdentity("imported", "typing", "TYPE_CHECKING")
        )

    def _transfer_function_definition(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        expressions: list[ast.expr] = list(node.decorator_list)
        expressions.extend(node.args.defaults)
        expressions.extend(
            default for default in node.args.kw_defaults if default is not None
        )
        annotations = self._argument_annotations(node.args)
        if node.returns is not None:
            annotations = (*annotations, node.returns)
        values, current, raises, deferred, facts = self._transfer_expression_sequence(
            tuple(expressions), state, context
        )
        del values
        inspection_state = current or raises or state
        annotation_context = (
            _TransferContext("postponed-annotation", False, False, False)
            if self._future_annotations
            else context
        )
        for annotation in annotations:
            active_state = current or inspection_state
            active_context = (
                annotation_context
                if current is not None
                else _TransferContext("unreachable", False, False, False)
            )
            result = self._transfer_expression(
                annotation, active_state, active_context
            )
            facts = _join_policy(facts, result.facts)
            deferred = _join_deferred(deferred, result.deferred)
            if current is not None and not self._future_annotations:
                raises = _join_states(raises, result.raises)
                current = result.post_state
                if current is None:
                    inspection_state = result.raises or active_state
        for expression in self._type_parameter_expressions(node):
            result = self._transfer_expression(
                expression,
                current or inspection_state,
                _TransferContext(
                    "lazy-annotation" if current is not None else "unreachable",
                    False,
                    False,
                    False,
                ),
            )
            facts = _join_policy(facts, result.facts)
            deferred = _join_deferred(deferred, result.deferred)
        location = _source_location(self.source_module, node)
        kind: _DeferredKind = (
            "async-function" if isinstance(node, ast.AsyncFunctionDef) else "function"
        )
        if current is None:
            definition_state = (
                inspection_state.pop()
                if inspection_state.frames[-1].kind == "class"
                else inspection_state
            )
            body = _DeferredBody(
                kind,
                location,
                definition_state.frames[-1].scope_id,
                definition_state,
                node,
            )
            return _FlowResult(
                None,
                exceptions=_unknown_exceptions(raises),
                deferred=_join_deferred(
                    deferred, _DeferredEffects(bodies=(body,))
                ),
                facts=facts,
            )
        function_value = _value_with_capabilities(
            identity=_ResolvedIdentity(
                "function", self.source_module, node.name, location
            ),
            complete=not node.decorator_list,
        )
        synthetic = ast.Name(
            id=node.name,
            ctx=ast.Store(),
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        current, effect, binding_facts = self._bind_target(
            synthetic, function_value, current, context, operation="assign"
        )
        definition_state = current.pop() if current.frames[-1].kind == "class" else current
        body = _DeferredBody(
            kind,
            location,
            definition_state.frames[-1].scope_id,
            definition_state,
            node,
        )
        deferred = _join_deferred(deferred, _DeferredEffects(bodies=(body,)))
        return _FlowResult(
            current,
            exceptions=_unknown_exceptions(raises),
            deferred=_join_deferred(deferred, effect),
            facts=_join_policy(facts, binding_facts),
        )

    @staticmethod
    def _argument_annotations(arguments: ast.arguments) -> tuple[ast.expr, ...]:
        result: list[ast.expr] = []
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            if argument.annotation is not None:
                result.append(argument.annotation)
        if arguments.vararg is not None and arguments.vararg.annotation is not None:
            result.append(arguments.vararg.annotation)
        if arguments.kwarg is not None and arguments.kwarg.annotation is not None:
            result.append(arguments.kwarg.annotation)
        return tuple(result)

    @staticmethod
    def _type_parameter_expressions(
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    ) -> tuple[ast.expr, ...]:
        result: list[ast.expr] = []
        for type_parameter in getattr(node, "type_params", ()):
            bound = getattr(type_parameter, "bound", None)
            if isinstance(bound, ast.expr):
                result.append(bound)
            default = getattr(type_parameter, "default_value", None)
            if isinstance(default, ast.expr):
                result.append(default)
        return tuple(result)

    def _transfer_class_definition(
        self, node: ast.ClassDef, state: _State, context: _TransferContext
    ) -> _FlowResult:
        expressions = (
            *node.decorator_list,
            *node.bases,
            *(keyword.value for keyword in node.keywords),
        )
        values, current, raises, deferred, facts = self._transfer_expression_sequence(
            expressions, state, context
        )
        del values
        inspection_state = current or raises or state
        for expression in self._type_parameter_expressions(node):
            result = self._transfer_expression(
                expression,
                inspection_state,
                _TransferContext(
                    "lazy-annotation" if current is not None else "unreachable",
                    False,
                    False,
                    False,
                ),
            )
            facts = _join_policy(facts, result.facts)
            deferred = _join_deferred(deferred, result.deferred)
        declarations = self._scope_declarations(node.body)
        frame = _Frame.create(
            scope_id=_source_location(self.source_module, node),
            kind="class",
            names=tuple(declarations.local_names),
            global_names=declarations.global_names,
            nonlocal_names=declarations.nonlocal_names,
        )
        if current is None:
            inspected = self._transfer_statements(
                node.body,
                inspection_state.push(frame),
                _TransferContext("unreachable", False, False, False),
            )
            return _FlowResult(
                None,
                exceptions=_unknown_exceptions(raises),
                deferred=_join_deferred(deferred, inspected.deferred),
                facts=_join_policy(facts, inspected.facts),
            )
        class_flow = self._transfer_statements(node.body, current.push(frame), context)
        facts = _join_policy(facts, class_flow.facts)
        deferred = _join_deferred(deferred, class_flow.deferred)
        class_exceptions = _map_exception_states(
            class_flow.exceptions, lambda exception_state: exception_state.pop()
        )
        exceptions = _join_exceptions(
            _unknown_exceptions(raises), class_exceptions
        )
        if class_flow.normal is None:
            return _FlowResult(
                None,
                exceptions=exceptions,
                deferred=deferred,
                facts=facts,
            )
        outer = class_flow.normal.pop()
        class_value = _value_with_capabilities(
            identity=_ResolvedIdentity(
                "class",
                self.source_module,
                node.name,
                _source_location(self.source_module, node),
            ),
            complete=not node.decorator_list,
        )
        synthetic = ast.Name(
            id=node.name,
            ctx=ast.Store(),
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        outer, effect, binding_facts = self._bind_target(
            synthetic, class_value, outer, context, operation="assign"
        )
        return _FlowResult(
            outer,
            exceptions=exceptions,
            deferred=_join_deferred(deferred, effect),
            facts=_join_policy(facts, binding_facts),
        )

    @staticmethod
    def _state_skeleton(state: _State) -> _StateSkeleton:
        return tuple(
            (
                frame.scope_id,
                frame.kind,
                len(frame.bindings),
                frame.global_names,
                frame.nonlocal_names,
            )
            for frame in state.frames
        )

    @classmethod
    def _project_state(
        cls, state: _State, skeleton: _StateSkeleton
    ) -> _State | None:
        if len(state.frames) < len(skeleton):
            return None
        projected = _State(state.frames[: len(skeleton)])
        if cls._state_skeleton(projected) != skeleton:
            return None
        return projected

    def _reverse_suffix_envelopes(
        self, definition_state: _State
    ) -> dict[_ProgramPoint, _State]:
        skeleton = self._state_skeleton(definition_state)
        cached = self._suffix_cache.get(skeleton)
        if cached is not None:
            return cached
        outputs: dict[_ProgramPoint, _State] = {}
        for point, state in self._point_outputs.items():
            output_skeleton = self._point_output_skeletons[point]
            if (
                len(output_skeleton) >= len(skeleton)
                and output_skeleton[: len(skeleton)] == skeleton
            ):
                outputs[point] = _State(state.frames[: len(skeleton)])
        successors: dict[_ProgramPoint, set[_ProgramPoint]] = {
            point: set() for point in outputs
        }
        predecessors: dict[_ProgramPoint, set[_ProgramPoint]] = {
            point: set() for point in outputs
        }
        for source, target in self._suffix_edges:
            if source not in outputs or target not in outputs:
                continue
            successors[source].add(target)
            predecessors[target].add(source)
        envelopes = dict(outputs)
        ordered_points = sorted(
            outputs,
            key=lambda point: (point[1], point[0], point[2]),
            reverse=True,
        )
        worklist = deque(ordered_points)
        queued = set(ordered_points)
        while worklist:
            point = worklist.popleft()
            queued.remove(point)
            self._stats.worklist_pops += 1
            suffix_point: _ProgramPoint = ("suffix", point[1], "deferred")
            self._stats.program_points.add(suffix_point)
            current = envelopes[point]
            grew = False
            for successor in sorted(
                successors[point],
                key=lambda item: (item[1], item[0], item[2]),
            ):
                current, changed = self._stats.merge_program_point(
                    suffix_point, current, envelopes[successor]
                )
                grew = grew or changed
            if not grew:
                continue
            envelopes[point] = current
            for predecessor in sorted(
                predecessors[point],
                key=lambda item: (item[1], item[0], item[2]),
            ):
                if predecessor not in queued:
                    worklist.append(predecessor)
                    queued.add(predecessor)
        self._suffix_cache[skeleton] = envelopes
        return envelopes

    def _suffix_envelope(
        self, body: _DeferredBody, fallback_state: _State
    ) -> tuple[_State, _PolicyFacts, bool]:
        definition_state = body.definition_state
        generator_frame: _Frame | None = None
        if body.kind == "generator":
            if definition_state.frames[-1].kind != "comprehension":
                return (
                    definition_state,
                    self._closure_error(
                        body.node, "generator frame skeleton is incompatible"
                    ),
                    False,
                )
            generator_frame = definition_state.frames[-1]
            definition_state = definition_state.pop()
        completion = self._body_completion.get((body.kind, body.location))
        if completion is None:
            runtime_point_exists = any(
                point[1] == body.location
                and point[2] in {"eager", "deferred"}
                for point in self._stats.program_points
            )
            if runtime_point_exists:
                return (
                    body.definition_state,
                    self._closure_error(
                        body.node, "deferred body completion point is missing"
                    ),
                    False,
                )
            return body.definition_state, _PolicyFacts(), False
        envelopes = self._reverse_suffix_envelopes(definition_state)
        suffix = envelopes.get(completion)
        if suffix is None:
            return (
                body.definition_state,
                self._closure_error(
                    body.node, "deferred body frame skeleton is incompatible"
                ),
                False,
            )
        fallback = self._project_state(
            fallback_state, self._state_skeleton(definition_state)
        )
        if fallback is not None:
            suffix = suffix.join(fallback)
        envelope = definition_state.join(suffix)
        if generator_frame is not None:
            envelope = envelope.push(generator_frame)
        return envelope, _PolicyFacts(), True

    @staticmethod
    def _has_nested_deferred_syntax(node: ast.AST) -> bool:
        pending = list(ast.iter_child_nodes(node))
        while pending:
            child = pending.pop()
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.GeneratorExp),
            ):
                return True
            pending.extend(ast.iter_child_nodes(child))
        return False

    def _inspect_deferred_bodies(
        self, effects: _DeferredEffects, suffix_state: _State
    ) -> tuple[_PolicyFacts, _DeferredEffects]:
        facts = _PolicyFacts()
        accumulated = _DeferredEffects(writes=effects.writes)
        for body in effects.bodies:
            envelope, envelope_facts, runtime_body = self._suffix_envelope(
                body, suffix_state
            )
            facts = _join_policy(facts, envelope_facts)
            previous_capture = self._capture_point_outputs
            self._capture_point_outputs = (
                runtime_body and self._has_nested_deferred_syntax(body.node)
            )
            deferred_context = (
                _TransferContext("deferred", True, True, False)
                if runtime_body
                else _TransferContext("unreachable", False, False, False)
            )
            if isinstance(body.node, ast.GeneratorExp):
                if body.kind != "generator":
                    facts = _join_policy(
                        facts,
                        self._closure_error(
                            body.node, "invalid deferred generator kind"
                        ),
                    )
                    self._capture_point_outputs = previous_capture
                    continue
                (
                    iteration,
                    values,
                    may_skip,
                    raises,
                    body_deferred,
                    body_facts,
                ) = self._comprehension_step(
                    body.node,
                    0,
                    envelope,
                    _UNKNOWN_VALUE,
                    deferred_context,
                    bind_target=False,
                )
                del values, may_skip
                body_flow = _FlowResult(
                    iteration,
                    exceptions=_unknown_exceptions(raises),
                    deferred=body_deferred,
                    facts=body_facts,
                )
                body_state = envelope
            elif isinstance(body.node, ast.Lambda):
                declarations = self._lambda_declarations(body.node)
                arguments = body.node.args
            elif isinstance(body.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                declarations = self._scope_declarations(
                    body.node.body, body.node.args
                )
                arguments = body.node.args
            else:
                facts = _join_policy(
                    facts,
                    self._closure_error(body.node, "invalid deferred body node"),
                )
                self._capture_point_outputs = previous_capture
                continue
            if not isinstance(body.node, ast.GeneratorExp):
                frame = _Frame.create(
                    scope_id=body.location,
                    kind="lambda" if body.kind == "lambda" else "function",
                    names=tuple(declarations.local_names),
                    global_names=declarations.global_names,
                    nonlocal_names=declarations.nonlocal_names,
                )
                body_state = envelope.push(frame)
                body_state = self._bind_arguments(arguments, body_state)
                unresolved = tuple(
                    name
                    for name in declarations.nonlocal_names
                    if body_state._nonlocal_index(name) is None
                )
                if unresolved:
                    facts = _join_policy(
                        facts,
                        self._closure_error(
                            body.node,
                            f"unresolved nonlocal binding: {', '.join(sorted(unresolved))}",
                        ),
                    )
                if isinstance(body.node, ast.Lambda):
                    result = self._transfer_expression(
                        body.node.body, body_state, deferred_context
                    )
                    body_flow = _FlowResult(
                        result.post_state,
                        exceptions=_unknown_exceptions(result.raises),
                        deferred=result.deferred,
                        facts=result.facts,
                    )
                elif isinstance(body.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    body_flow = self._transfer_statements(
                        body.node.body, body_state, deferred_context
                    )
                else:
                    self._capture_point_outputs = previous_capture
                    continue
            self._capture_point_outputs = previous_capture
            facts = _join_policy(facts, body_flow.facts)
            accumulated = _join_deferred(accumulated, body_flow.deferred)
            nested_suffix = body_flow.normal or body_state
            nested_facts, nested_effects = self._inspect_deferred_bodies(
                body_flow.deferred, nested_suffix
            )
            facts = _join_policy(facts, nested_facts)
            accumulated = _join_deferred(accumulated, nested_effects)
        return facts, accumulated

    @staticmethod
    def _bind_arguments(arguments: ast.arguments, state: _State) -> _State:
        current = state
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            current = current.bind(argument.arg, _UNKNOWN_VALUE)
        if arguments.vararg is not None:
            current = current.bind(arguments.vararg.arg, _UNKNOWN_VALUE)
        if arguments.kwarg is not None:
            current = current.bind(arguments.kwarg.arg, _UNKNOWN_VALUE)
        return current

    def _transfer_for(
        self,
        node: ast.For | ast.AsyncFor,
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        iterable = self._transfer_expression(node.iter, state, context)
        post = iterable.post_state
        if post is None:
            return _FlowResult(
                None,
                exceptions=_unknown_exceptions(iterable.raises),
                deferred=iterable.deferred,
                facts=iterable.facts,
            )
        outcomes = iterable.value.iteration_outcomes
        may_iteration_raise = iterable.value.may_iteration_raise
        if isinstance(node, ast.AsyncFor):
            outcomes = frozenset({"zero", "one", "many"})
            may_iteration_raise = True
        exhaustion: _State | None = post if "zero" in outcomes else None
        breaks: _State | None = None
        returns: _State | None = None
        exceptions = _unknown_exceptions(
            _join_states(
                iterable.raises,
                post if may_iteration_raise else None,
            )
        )
        deferred = iterable.deferred
        facts = iterable.facts
        if outcomes.intersection({"one", "many"}):
            header = post
            loop_point: _ProgramPoint = (
                "loop",
                _source_location(self.source_module, node),
                context.mode,
            )
            self._stats.program_points.add(loop_point)
            while True:
                self._stats.worklist_pops += 1
                bound, effect, binding_facts = self._bind_target(
                    node.target,
                    _UNKNOWN_VALUE
                    if isinstance(node, ast.AsyncFor)
                    else _element_value(iterable.value),
                    header,
                    context,
                    operation="assign",
                )
                body = self._transfer_statements(node.body, bound, context)
                deferred = _join_deferred(deferred, effect, body.deferred)
                facts = _join_policy(facts, binding_facts, body.facts)
                exceptions = _join_exceptions(exceptions, body.exceptions)
                returns = _join_states(returns, body.returns)
                breaks = _join_states(breaks, body.breaks)
                backedge = _join_states(body.normal, body.continues)
                exhaustion = _join_states(exhaustion, backedge)
                if may_iteration_raise:
                    exceptions = _join_exceptions(
                        exceptions, _unknown_exceptions(backedge)
                    )
                if "many" not in outcomes or backedge is None:
                    break
                header, changed = self._stats.merge_program_point(
                    loop_point, header, backedge
                )
                if not changed:
                    break
                if (
                    self._stats.updates_by_program_point.get(loop_point, 0)
                    > (self._stats.precomputed_height_bound or 1)
                ):
                    facts = _join_policy(
                        facts,
                        self._closure_error(node, "source dataflow did not converge"),
                    )
                    break
        else_result = (
            _FlowResult(exhaustion)
            if not node.orelse or exhaustion is None
            else self._transfer_statements(node.orelse, exhaustion, context)
        )
        normal = _join_states(breaks, else_result.normal)
        return _FlowResult(
            normal,
            returns=_join_states(returns, else_result.returns),
            exceptions=_join_exceptions(
                exceptions, else_result.exceptions
            ),
            deferred=_join_deferred(deferred, else_result.deferred),
            facts=_join_policy(facts, else_result.facts),
        )

    def _transfer_while(
        self, node: ast.While, state: _State, context: _TransferContext
    ) -> _FlowResult:
        header = state
        exhaustion: _State | None = None
        breaks: _State | None = None
        returns: _State | None = None
        exceptions = _ExceptionalExits()
        deferred = _DeferredEffects()
        facts = _PolicyFacts()
        loop_point: _ProgramPoint = (
            "loop",
            _source_location(self.source_module, node),
            context.mode,
        )
        self._stats.program_points.add(loop_point)
        while True:
            self._stats.worklist_pops += 1
            condition = self._transfer_expression(node.test, header, context)
            exceptions = _join_exceptions(
                exceptions, _unknown_exceptions(condition.raises)
            )
            deferred = _join_deferred(deferred, condition.deferred)
            facts = _join_policy(facts, condition.facts)
            exhaustion = _join_states(
                exhaustion,
                None if condition.falsy is None else condition.falsy.state,
            )
            if condition.truthy is None:
                break
            body = self._transfer_statements(node.body, condition.truthy.state, context)
            breaks = _join_states(breaks, body.breaks)
            returns = _join_states(returns, body.returns)
            exceptions = _join_exceptions(exceptions, body.exceptions)
            deferred = _join_deferred(deferred, body.deferred)
            facts = _join_policy(facts, body.facts)
            backedge = _join_states(body.normal, body.continues)
            if backedge is None:
                break
            header, changed = self._stats.merge_program_point(
                loop_point, header, backedge
            )
            if not changed:
                break
            if (
                self._stats.updates_by_program_point.get(loop_point, 0)
                > (self._stats.precomputed_height_bound or 1)
            ):
                facts = _join_policy(
                    facts, self._closure_error(node, "source dataflow did not converge")
                )
                break
        else_result = (
            _FlowResult(exhaustion)
            if not node.orelse or exhaustion is None
            else self._transfer_statements(node.orelse, exhaustion, context)
        )
        return _FlowResult(
            _join_states(breaks, else_result.normal),
            returns=_join_states(returns, else_result.returns),
            exceptions=_join_exceptions(
                exceptions, else_result.exceptions
            ),
            deferred=_join_deferred(deferred, else_result.deferred),
            facts=_join_policy(facts, else_result.facts),
        )

    def _transfer_match(
        self, node: ast.Match, state: _State, context: _TransferContext
    ) -> _FlowResult:
        subject = self._transfer_expression(node.subject, state, context)
        remaining = subject.post_state
        outputs: list[_FlowResult] = []
        facts = subject.facts
        deferred = subject.deferred
        exceptions = _unknown_exceptions(subject.raises)
        for case in node.cases:
            if remaining is None:
                inspected = self._transfer_statements(
                    case.body,
                    state,
                    _TransferContext("unreachable", False, False, False),
                )
                facts = _join_policy(facts, inspected.facts)
                deferred = _join_deferred(deferred, inspected.deferred)
                continue
            (
                matched,
                no_match,
                pattern_facts,
                pattern_deferred,
                pattern_raises,
            ) = self._transfer_pattern(case.pattern, subject.value, remaining, context)
            facts = _join_policy(facts, pattern_facts)
            deferred = _join_deferred(deferred, pattern_deferred)
            exceptions = _join_exceptions(
                exceptions, _unknown_exceptions(pattern_raises)
            )
            if matched is None:
                remaining = None
                continue
            if case.guard is not None:
                guard = self._transfer_expression(case.guard, matched, context)
                facts = _join_policy(facts, guard.facts)
                deferred = _join_deferred(deferred, guard.deferred)
                exceptions = _join_exceptions(
                    exceptions, _unknown_exceptions(guard.raises)
                )
                remaining = _join_states(
                    no_match,
                    None if guard.falsy is None else guard.falsy.state,
                )
                matched_state = None if guard.truthy is None else guard.truthy.state
            else:
                remaining = no_match
                matched_state = matched
            if matched_state is not None:
                outputs.append(self._transfer_statements(case.body, matched_state, context))
        if remaining is not None:
            outputs.append(_FlowResult(remaining))
        joined = _join_flow(*outputs) if outputs else _FlowResult(None)
        return _FlowResult(
            joined.normal,
            joined.breaks,
            joined.continues,
            joined.returns,
            _join_exceptions(exceptions, joined.exceptions),
            _join_deferred(deferred, joined.deferred),
            _join_policy(facts, joined.facts),
        )

    @_instrument_pattern_transfer
    def _transfer_pattern(
        self,
        pattern: ast.pattern,
        value: _AbsValue,
        state: _State,
        context: _TransferContext,
    ) -> tuple[
        _State | None,
        _State | None,
        _PolicyFacts,
        _DeferredEffects,
        _State | None,
    ]:
        expressions: list[ast.expr] = []
        always_matches = isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and (
            not isinstance(pattern, ast.MatchAs) or pattern.pattern is None
        )
        if isinstance(pattern, ast.MatchValue):
            expressions.append(pattern.value)
        elif isinstance(pattern, ast.MatchClass):
            expressions.append(pattern.cls)
        elif isinstance(pattern, ast.MatchMapping):
            expressions.extend(pattern.keys)
        _, post, raises, deferred, facts = self._transfer_expression_sequence(
            tuple(expressions), state, context
        )
        if post is None:
            return None, None, facts, deferred, raises
        bound = post.bind_pattern(pattern, value)
        if always_matches:
            failed = None
        else:
            failed = self._join_program_point(
                self._program_point("pattern", pattern, context), post, bound
            )
        return bound, failed, facts, deferred, raises

    def _transfer_with(
        self,
        node: ast.With | ast.AsyncWith,
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        current = state
        exceptions = _ExceptionalExits()
        deferred = _DeferredEffects()
        facts = _PolicyFacts()
        for index, item in enumerate(node.items):
            result = self._transfer_expression(item.context_expr, current, context)
            exceptions = _join_exceptions(
                exceptions, _unknown_exceptions(result.raises)
            )
            deferred = _join_deferred(deferred, result.deferred)
            facts = _join_policy(facts, result.facts)
            post = result.post_state
            if post is None:
                inspection_state = result.raises or current
                unreachable = _TransferContext(
                    "unreachable", False, False, False
                )
                for remaining in node.items[index + 1 :]:
                    inspected = self._transfer_expression(
                        remaining.context_expr, inspection_state, unreachable
                    )
                    deferred = _join_deferred(deferred, inspected.deferred)
                    facts = _join_policy(facts, inspected.facts)
                inspected_body = self._transfer_statements(
                    node.body, inspection_state, unreachable
                )
                return _FlowResult(
                    None,
                    exceptions=exceptions,
                    deferred=_join_deferred(
                        deferred, inspected_body.deferred
                    ),
                    facts=_join_policy(facts, inspected_body.facts),
                )
            current = post
            if item.optional_vars is not None:
                target_value = _derived_value(result.value, complete=False)
                current, effect, binding_facts = self._bind_target(
                    item.optional_vars,
                    target_value,
                    current,
                    context,
                    operation="assign",
                )
                deferred = _join_deferred(deferred, effect)
                facts = _join_policy(facts, binding_facts)
        body = self._transfer_statements(node.body, current, context)
        return _FlowResult(
            _join_states(body.normal, body.raises),
            body.breaks,
            body.continues,
            body.returns,
            _join_exceptions(exceptions, body.exceptions),
            _join_deferred(deferred, body.deferred),
            _join_policy(facts, body.facts),
        )

    def _transfer_try(
        self,
        node: ast.Try | ast.TryStar,
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        if isinstance(node, ast.TryStar):
            return self._transfer_try_star(node, state, context)
        return self._transfer_ordinary_try(node, state, context)

    def _transfer_ordinary_try(
        self,
        node: ast.Try,
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        body = self._transfer_statements(node.body, state, context)
        residual = body.exceptions
        handler_outputs: list[_FlowResult] = []
        handler_facts = _PolicyFacts()
        handler_deferred = _DeferredEffects()
        handler_resolution_exceptions = _ExceptionalExits()
        for handler in node.handlers:
            handler_input = residual.joined_state
            if handler_input is None:
                if handler.type is not None:
                    inspected_type = self._transfer_expression(
                        handler.type,
                        state,
                        _TransferContext("unreachable", False, False, False),
                    )
                    handler_facts = _join_policy(
                        handler_facts, inspected_type.facts
                    )
                    handler_deferred = _join_deferred(
                        handler_deferred, inspected_type.deferred
                    )
                inspected = self._transfer_statements(
                    handler.body,
                    state,
                    _TransferContext("unreachable", False, False, False),
                )
                handler_facts = _join_policy(handler_facts, inspected.facts)
                handler_deferred = _join_deferred(
                    handler_deferred, inspected.deferred
                )
                continue
            current = handler_input
            type_facts = _PolicyFacts()
            type_deferred = _DeferredEffects()
            target_facts = _PolicyFacts()
            target_deferred = _DeferredEffects()
            matched = residual
            unmatched = _ExceptionalExits()
            if handler.type is not None:
                type_result = self._transfer_expression(handler.type, current, context)
                type_post = type_result.post_state
                type_facts = type_result.facts
                type_deferred = type_result.deferred
                handler_resolution_exceptions = _join_exceptions(
                    handler_resolution_exceptions,
                    _unknown_exceptions(type_result.raises),
                )
                handler_facts = _join_policy(handler_facts, type_facts)
                handler_deferred = _join_deferred(
                    handler_deferred, type_deferred
                )
                if type_post is None:
                    inspected = self._transfer_statements(
                        handler.body,
                        type_result.raises or handler_input,
                        _TransferContext("unreachable", False, False, False),
                    )
                    handler_facts = _join_policy(
                        handler_facts, inspected.facts
                    )
                    handler_deferred = _join_deferred(
                        handler_deferred, inspected.deferred
                    )
                    residual = _ExceptionalExits()
                    continue
                current = type_post
                caught_names = self._provable_handler_exception_names(
                    handler.type,
                    handler_input,
                    type_result,
                )
                if caught_names is None:
                    matched = _replace_exception_states(residual, current)
                    unmatched = matched
                else:
                    matched, unmatched = self._partition_exception_routes(
                        residual, caught_names
                    )
            else:
                matched = residual
                unmatched = _ExceptionalExits()
            matched_state = matched.joined_state
            if matched_state is None:
                inspected = self._transfer_statements(
                    handler.body,
                    handler_input,
                    _TransferContext("unreachable", False, False, False),
                )
                handler_facts = _join_policy(handler_facts, inspected.facts)
                handler_deferred = _join_deferred(
                    handler_deferred, inspected.deferred
                )
                residual = unmatched
                continue
            current = matched_state
            if handler.name is not None:
                synthetic = ast.Name(
                    id=handler.name,
                    ctx=ast.Store(),
                    lineno=handler.lineno,
                    col_offset=handler.col_offset,
                )
                current, effect, binding_facts = self._bind_target(
                    synthetic,
                    _UNKNOWN_VALUE,
                    current,
                    context,
                    operation="assign",
                )
                target_deferred = effect
                target_facts = binding_facts
            handled = self._transfer_statements(handler.body, current, context)
            if handler.name is not None:
                handled = self._cleanup_handler_name(handled, handler.name)
            handler_point: _ProgramPoint = (
                "handler",
                _source_location(self.source_module, handler),
                context.mode,
            )
            self._stats.program_points.add(handler_point)
            self._join_program_point(
                handler_point, handled.normal, handled.raises
            )
            handled = _FlowResult(
                handled.normal,
                handled.breaks,
                handled.continues,
                handled.returns,
                handled.exceptions,
                _join_deferred(target_deferred, handled.deferred),
                _join_policy(target_facts, handled.facts),
            )
            handler_outputs.append(handled)
            residual = unmatched
        else_result = (
            _FlowResult(body.normal)
            if not node.orelse or body.normal is None
            else self._transfer_statements(node.orelse, body.normal, context)
        )
        handlers = _join_flow(*handler_outputs) if handler_outputs else _FlowResult(None)
        pre_finally = _FlowResult(
            _join_states(else_result.normal, handlers.normal),
            _join_states(body.breaks, else_result.breaks, handlers.breaks),
            _join_states(body.continues, else_result.continues, handlers.continues),
            _join_states(body.returns, else_result.returns, handlers.returns),
            _join_exceptions(
                residual,
                else_result.exceptions,
                handlers.exceptions,
                handler_resolution_exceptions,
            ),
            _join_deferred(
                body.deferred,
                else_result.deferred,
                handlers.deferred,
                handler_deferred,
            ),
            _join_policy(
                body.facts,
                else_result.facts,
                handlers.facts,
                handler_facts,
            ),
        )
        if not node.finalbody:
            return pre_finally
        return self._apply_finally(node.finalbody, pre_finally, context)

    def _transfer_try_star(
        self,
        node: ast.TryStar,
        state: _State,
        context: _TransferContext,
    ) -> _FlowResult:
        body = self._transfer_statements(node.body, state, context)
        ordered_input = body.raises
        handler_outputs: list[_FlowResult] = []
        handler_facts = _PolicyFacts()
        handler_deferred = _DeferredEffects()
        for handler in node.handlers:
            if ordered_input is None:
                inspected = self._transfer_statements(
                    handler.body,
                    state,
                    _TransferContext("unreachable", False, False, False),
                )
                handler_facts = _join_policy(handler_facts, inspected.facts)
                handler_deferred = _join_deferred(
                    handler_deferred, inspected.deferred
                )
                continue
            current = ordered_input
            type_facts = _PolicyFacts()
            type_deferred = _DeferredEffects()
            type_raises: _State | None = None
            if handler.type is not None:
                type_result = self._transfer_expression(handler.type, current, context)
                type_facts = type_result.facts
                type_deferred = type_result.deferred
                type_raises = type_result.raises
                current = type_result.post_state or ordered_input
            if handler.name is not None:
                synthetic = ast.Name(
                    id=handler.name,
                    ctx=ast.Store(),
                    lineno=handler.lineno,
                    col_offset=handler.col_offset,
                )
                current, effect, binding_facts = self._bind_target(
                    synthetic,
                    _UNKNOWN_VALUE,
                    current,
                    context,
                    operation="assign",
                )
                type_deferred = _join_deferred(type_deferred, effect)
                type_facts = _join_policy(type_facts, binding_facts)
            handled = self._transfer_statements(handler.body, current, context)
            if handler.name is not None:
                handled = self._cleanup_handler_name(handled, handler.name)
            handler_point: _ProgramPoint = (
                "handler",
                _source_location(self.source_module, handler),
                context.mode,
            )
            self._stats.program_points.add(handler_point)
            ordered_effect = self._join_program_point(
                handler_point, handled.normal, handled.raises
            )
            handled = _FlowResult(
                handled.normal,
                handled.breaks,
                handled.continues,
                handled.returns,
                _unknown_exceptions(
                    _join_states(type_raises, handled.raises)
                ),
                _join_deferred(type_deferred, handled.deferred),
                _join_policy(type_facts, handled.facts),
            )
            handler_outputs.append(handled)
            ordered_input = self._join_program_point(
                handler_point, ordered_input, ordered_effect
            )
        else_result = (
            _FlowResult(body.normal)
            if not node.orelse or body.normal is None
            else self._transfer_statements(node.orelse, body.normal, context)
        )
        handlers = (
            _join_flow(*handler_outputs)
            if handler_outputs
            else _FlowResult(None)
        )
        pre_finally = _FlowResult(
            _join_states(else_result.normal, handlers.normal),
            _join_states(body.breaks, else_result.breaks, handlers.breaks),
            _join_states(body.continues, else_result.continues, handlers.continues),
            _join_states(body.returns, else_result.returns, handlers.returns),
            _unknown_exceptions(
                _join_states(
                    body.raises,
                    else_result.raises,
                    handlers.raises,
                )
            ),
            _join_deferred(
                body.deferred,
                else_result.deferred,
                handlers.deferred,
                handler_deferred,
            ),
            _join_policy(
                body.facts,
                else_result.facts,
                handlers.facts,
                handler_facts,
            ),
        )
        if not node.finalbody:
            return pre_finally
        return self._apply_finally(node.finalbody, pre_finally, context)

    def _cleanup_handler_name(self, flow: _FlowResult, name: str) -> _FlowResult:
        def cleanup(state: _State | None) -> _State | None:
            if state is None:
                return None
            index = state.binding_frame_index(name)
            if index is None or name not in dict(state.frames[index].bindings):
                return state
            frames = list(state.frames)
            frames[index] = frames[index].replace_binding(
                name, _BindingSlot(_UNKNOWN_VALUE, False, True)
            )
            return _State(tuple(frames))

        return _FlowResult(
            cleanup(flow.normal),
            cleanup(flow.breaks),
            cleanup(flow.continues),
            cleanup(flow.returns),
            _map_exception_states(
                flow.exceptions,
                lambda exception_state: cleanup(exception_state),
            ),
            flow.deferred,
            flow.facts,
        )

    def _apply_finally(
        self,
        finalbody: Sequence[ast.stmt],
        incoming: _FlowResult,
        context: _TransferContext,
    ) -> _FlowResult:
        output = _FlowResult(None, deferred=incoming.deferred, facts=incoming.facts)
        for kind, state in (
            ("normal", incoming.normal),
            ("break", incoming.breaks),
            ("continue", incoming.continues),
            ("return", incoming.returns),
        ):
            if state is None:
                continue
            final = self._transfer_statements(finalbody, state, context)
            preserved = _FlowResult(
                final.normal if kind == "normal" else None,
                final.normal if kind == "break" else None,
                final.normal if kind == "continue" else None,
                final.normal if kind == "return" else None,
                _ExceptionalExits(),
                final.deferred,
                final.facts,
            )
            replacements = _FlowResult(
                None,
                final.breaks,
                final.continues,
                final.returns,
                final.exceptions,
                final.deferred,
                final.facts,
            )
            output = _join_flow(output, preserved, replacements)
        exceptional_input = self._finally_exception_projection(
            incoming.exceptions
        )
        exceptional_state = exceptional_input.joined_state
        if exceptional_state is not None:
            final = self._transfer_statements(
                finalbody, exceptional_state, context
            )
            preserved = _FlowResult(
                None,
                exceptions=_replace_exception_states(
                    exceptional_input, final.normal
                ),
                deferred=final.deferred,
                facts=final.facts,
            )
            replacements = _FlowResult(
                None,
                final.breaks,
                final.continues,
                final.returns,
                final.exceptions,
                final.deferred,
                final.facts,
            )
            output = _join_flow(output, preserved, replacements)
        return output

    @staticmethod
    def _finally_exception_projection(
        exits: _ExceptionalExits,
    ) -> _ExceptionalExits:
        if len(exits.exact) <= 1:
            return exits
        first_state = exits.exact[0][1]
        if exits.unknown is None and all(
            state == first_state for _identity, state in exits.exact[1:]
        ):
            return exits
        return _unknown_exceptions(exits.joined_state)

    def _provable_handler_exception_names(
        self,
        handler_type: ast.expr,
        state: _State,
        result: _ExprResult,
    ) -> frozenset[str] | None:
        if (
            result.raises is not None
            or result.post_state != state
            or result.deferred != _EMPTY_DEFERRED_EFFECTS
        ):
            return None
        candidates = (
            handler_type.elts
            if isinstance(handler_type, ast.Tuple)
            else (handler_type,)
        )
        caught_names: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, ast.Name):
                return None
            if self._provable_builtin_exception_supertypes(
                state, candidate.id
            ) is None:
                return None
            caught_names.append(candidate.id)
        return frozenset(caught_names)

    @staticmethod
    def _partition_exception_routes(
        exits: _ExceptionalExits,
        caught_names: frozenset[str],
    ) -> tuple[_ExceptionalExits, _ExceptionalExits]:
        matched: list[tuple[_ResolvedIdentity, _State]] = []
        unmatched: list[tuple[_ResolvedIdentity, _State]] = []
        for identity, state in exits.exact:
            supertypes = _PROVABLE_BUILTIN_EXCEPTION_SUPERTYPES[identity.name]
            if caught_names.intersection(supertypes):
                matched.append((identity, state))
            else:
                unmatched.append((identity, state))
        if "BaseException" in caught_names:
            matched_unknown = exits.unknown
            unmatched_unknown = None
        else:
            matched_unknown = exits.unknown
            unmatched_unknown = exits.unknown
        return (
            _ExceptionalExits(tuple(matched), matched_unknown),
            _ExceptionalExits(tuple(unmatched), unmatched_unknown),
        )

    def _provable_builtin_exception_supertypes(
        self, state: _State, name: str
    ) -> frozenset[str] | None:
        supertypes = _PROVABLE_BUILTIN_EXCEPTION_SUPERTYPES.get(name)
        if supertypes is None:
            return None
        value, may_be_unbound = self._resolved_value(state, name)
        if (
            may_be_unbound
            or not value.facts.complete
            or value.facts.identity.state != "exact"
            or value.facts.identity.identity
            != _ResolvedIdentity("builtin", "builtins", name)
        ):
            return None
        return supertypes


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

    flow_results: dict[str, _ModuleFlowResult] = {}

    def result_for(module: str) -> _ModuleFlowResult:
        existing = flow_results.get(module)
        if existing is not None:
            return existing
        relative = module_to_path[module]
        try:
            tree = ast.parse(projection_payloads[relative], filename=relative)
        except (SyntaxError, ValueError) as exc:
            raise StudyRetentionError(f"projected Python could not be parsed: {relative}") from exc
        initializer_policy = _validate_initializer_policy(
            module,
            tree,
            frozenset(module_to_path),
        )
        analyzer = _SourceFlowAnalyzer(
            source_module=module,
            known_modules=known_modules,
            initializer_policy=initializer_policy,
        )
        result = analyzer.analyze(tree)
        flow_results[module] = result
        return result

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
        source_result = result_for(source)
        source_facts = source_result.facts
        if source in study_owned:
            protected.extend(source_facts.protected)
            forbidden_calls.extend(source_facts.study_forbidden_calls)
        forbidden_calls.extend(source_facts.forbidden_calls)
        closure_errors.extend(source_facts.closure_errors)
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
        for reference in source_facts.references:
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

    selected_closure_error = (
        None
        if not closure_errors
        else min(closure_errors, key=_closure_error_key)
    )
    delayed_deferred_error = (
        selected_closure_error
        if selected_closure_error is not None
        and "source capability rejected: deferred-effect" in selected_closure_error
        else None
    )
    if selected_closure_error is not None and delayed_deferred_error is None:
        raise StudyRetentionError(selected_closure_error)
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
        suffix = (
            "" if delayed_deferred_error is None else f"; {delayed_deferred_error}"
        )
        raise StudyRetentionError(
            f"forbidden direct import: {first.source} -> {first.target}{suffix}"
        )
    if delayed_deferred_error is not None:
        raise StudyRetentionError(delayed_deferred_error)
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


def _is_importlib_target(module: str | None) -> bool:
    return module == "importlib" or (
        module is not None and module.startswith("importlib.")
    )


def _validate_initializer_policy(
    source_module: str,
    tree: ast.Module,
    projected_modules: frozenset[str],
) -> _InitializerPolicy:
    if source_module == "manufacturing_vision_studio.e1.study_truth_v2":
        return _validate_study_truth_plan_policy(source_module, tree)
    if source_module == "manufacturing_vision_studio.e1.study_cli_v2":
        return _validate_cli_json_policy(source_module, tree)
    if source_module not in _PROJECTED_PACKAGE_ROOTS:
        return _EMPTY_INITIALIZER_POLICY

    def fail(detail: str) -> NoReturn:
        raise StudyRetentionError(
            f"{source_module}: initializer capability structure: {detail}"
        )

    import_candidates = [
        statement
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom)
        and statement.level == 0
        and statement.module == "importlib"
        and any(alias.name == "import_module" for alias in statement.names)
    ]
    if len(import_candidates) != 1:
        fail("expected one module-level import_module import")
    import_statement = import_candidates[0]
    if (
        len(import_statement.names) != 1
        or import_statement.names[0].name != "import_module"
        or import_statement.names[0].asname is not None
    ):
        fail("import_module import must be unaliased and exclusive")

    lazy_assignments = [
        statement
        for statement in tree.body
        if _statement_binds_name(statement, "_LAZY_EXPORTS")
    ]
    if len(lazy_assignments) != 1 or not isinstance(
        lazy_assignments[0], ast.Assign
    ):
        fail("expected one literal module-level _LAZY_EXPORTS assignment")
    lazy_assignment = lazy_assignments[0]
    if (
        len(lazy_assignment.targets) != 1
        or not _is_name(lazy_assignment.targets[0], "_LAZY_EXPORTS", ast.Store)
        or not isinstance(lazy_assignment.value, ast.Dict)
    ):
        fail("_LAZY_EXPORTS must be assigned one literal dictionary")

    lazy_targets: list[tuple[str, str, str]] = []
    export_names: set[str] = set()
    for key, value in zip(
        lazy_assignment.value.keys,
        lazy_assignment.value.values,
        strict=True,
    ):
        export_name = _string_literal(key)
        if export_name is None or export_name in export_names:
            fail("_LAZY_EXPORTS keys must be unique string literals")
        export_names.add(export_name)
        if not isinstance(value, ast.Tuple) or len(value.elts) != 2:
            fail("_LAZY_EXPORTS values must be two-string tuples")
        module_name = _string_literal(value.elts[0])
        attribute_name = _string_literal(value.elts[1])
        if module_name is None or attribute_name is None:
            fail("_LAZY_EXPORTS values must be two-string tuples")
        if module_name not in projected_modules:
            fail(f"lazy target is not projected: {module_name}")
        lazy_targets.append((export_name, module_name, attribute_name))

    all_assignments = [
        statement for statement in tree.body if _statement_binds_name(statement, "__all__")
    ]
    if len(all_assignments) != 1 or not isinstance(all_assignments[0], ast.Assign):
        fail("expected one literal module-level __all__ assignment")
    all_assignment = all_assignments[0]
    if (
        len(all_assignment.targets) != 1
        or not _is_name(all_assignment.targets[0], "__all__", ast.Store)
        or not isinstance(all_assignment.value, ast.List)
        or any(_string_literal(item) is None for item in all_assignment.value.elts)
        or len({_string_literal(item) for item in all_assignment.value.elts})
        != len(all_assignment.value.elts)
    ):
        fail("__all__ must be assigned one unique literal string list")

    getattr_function = _one_module_function(tree, "__getattr__", fail)
    if not _has_exact_getattr_signature(getattr_function):
        fail("__getattr__ must have the current name: str signature")
    if len(getattr_function.body) != 4 or not _is_lazy_lookup_try(
        getattr_function.body[0]
    ):
        fail("__getattr__ must preserve the current fail-closed lookup")
    value_assignment = getattr_function.body[1]
    cache_assignment = getattr_function.body[2]
    value_return = getattr_function.body[3]
    loader_nodes = _lazy_value_loader_nodes(value_assignment)
    if loader_nodes is None:
        fail("__getattr__ must use the direct lazy import expression")
    outer_getattr, import_call = loader_nodes
    cache_globals = _lazy_cache_globals_call(cache_assignment)
    if cache_globals is None:
        fail("__getattr__ must cache through globals()[name]")
    if not (
        isinstance(value_return, ast.Return)
        and _is_name(value_return.value, "value", ast.Load)
    ):
        fail("__getattr__ must return the cached value")

    dir_function = _one_module_function(tree, "__dir__", fail)
    if not _has_exact_dir_signature(dir_function) or len(dir_function.body) != 1:
        fail("__dir__ must preserve the current signature and body")
    dir_return = dir_function.body[0]
    dir_globals = _dir_globals_call(dir_return)
    if dir_globals is None:
        fail("__dir__ must return the current sorted public namespace")

    lookup_try = cast(ast.Try, getattr_function.body[0])
    lookup_assignment = cast(ast.Assign, lookup_try.body[0])
    lookup_subscript = cast(ast.Subscript, lookup_assignment.value)
    lookup_handler = lookup_try.handlers[0]
    key_error_name = cast(ast.Name, lookup_handler.type)
    attribute_error_call = cast(ast.Call, cast(ast.Raise, lookup_handler.body[0]).exc)
    dir_sorted = cast(ast.Call, cast(ast.Return, dir_return).value)
    dir_union = cast(ast.BinOp, dir_sorted.args[0])
    dir_left_set = cast(ast.Call, dir_union.left)
    dir_right_set = cast(ast.Call, dir_union.right)
    required_bindings = tuple(
        sorted(
            (
                ("import_module", _ResolvedIdentity("imported", "importlib", "import_module")),
                ("getattr", _ResolvedIdentity("builtin", "builtins", "getattr")),
                ("globals", _ResolvedIdentity("builtin", "builtins", "globals")),
                ("KeyError", _ResolvedIdentity("builtin", "builtins", "KeyError")),
                (
                    "AttributeError",
                    _ResolvedIdentity("builtin", "builtins", "AttributeError"),
                ),
                ("sorted", _ResolvedIdentity("builtin", "builtins", "sorted")),
                ("set", _ResolvedIdentity("builtin", "builtins", "set")),
                (
                    "_LAZY_EXPORTS",
                    _ResolvedIdentity(
                        "literal",
                        source_module,
                        "_LAZY_EXPORTS",
                        _source_location(source_module, lazy_assignment),
                    ),
                ),
                (
                    "__all__",
                    _ResolvedIdentity(
                        "literal",
                        source_module,
                        "__all__",
                        _source_location(source_module, all_assignment),
                    ),
                ),
                (
                    "__getattr__",
                    _ResolvedIdentity(
                        "function",
                        source_module,
                        "__getattr__",
                        _source_location(source_module, getattr_function),
                    ),
                ),
                (
                    "__dir__",
                    _ResolvedIdentity(
                        "function",
                        source_module,
                        "__dir__",
                        _source_location(source_module, dir_function),
                    ),
                ),
            )
        )
    )
    exact_nodes: tuple[tuple[_ExactRole, ast.AST], ...] = (
        ("pep562-import-module", import_statement),
        ("pep562-import-module", import_call.func),
        ("pep562-getattr", outer_getattr.func),
        ("pep562-getattr", key_error_name),
        ("pep562-getattr", attribute_error_call.func),
        ("pep562-cache-globals", cache_globals.func),
        ("pep562-dir-globals", dir_sorted.func),
        ("pep562-dir-globals", dir_left_set.func),
        ("pep562-dir-globals", dir_globals.func),
        ("pep562-dir-globals", dir_right_set.func),
    )
    exact_call_sites = tuple(
        _ExactCallSite(
            role,
            _source_location(source_module, node),
            required_bindings,
        )
        for role, node in exact_nodes
    )
    allowed_capability_names = {
        site.location
        for site in exact_call_sites
        if site.location.node_kind == "Name"
    }
    allowed_literal_names = {
        _source_location(source_module, lazy_assignment.targets[0]),
        _source_location(source_module, lookup_subscript.value),
        _source_location(source_module, all_assignment.targets[0]),
        _source_location(source_module, dir_right_set.args[0]),
    }
    import_statement_location = _source_location(source_module, import_statement)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            _is_importlib_target(alias.name) for alias in node.names
        ):
            fail("unexpected importlib loader import")
        if (
            isinstance(node, ast.ImportFrom)
            and _is_importlib_target(node.module)
            and _source_location(source_module, node) != import_statement_location
        ):
            fail("unexpected importlib loader import")
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in {"getattr", "globals"}
            and _source_location(source_module, node) not in allowed_capability_names
        ):
            fail(f"unexpected {node.id} capability node")
        if (
            isinstance(node, ast.Call)
            and _is_name(node.func, "import_module", ast.Load)
            and _source_location(source_module, node.func)
            != _source_location(source_module, import_call.func)
        ):
            fail("unexpected import_module call")
        if isinstance(node, ast.Attribute) and node.attr == "import_module":
            fail("unexpected import_module reflection node")
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in {"_LAZY_EXPORTS", "__all__"}
            and _source_location(source_module, node) not in allowed_literal_names
        ):
            fail(f"unexpected {node.id} binding or access")
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in {"__dir__", "__getattr__"}
        ):
            fail(f"unexpected {node.id} binding or access")

    return _InitializerPolicy(
        exact_call_sites,
        tuple(sorted(lazy_targets)),
    )


def _validate_study_truth_plan_policy(
    source_module: str,
    tree: ast.Module,
) -> _InitializerPolicy:
    def fail(detail: str) -> NoReturn:
        raise StudyRetentionError(
            f"{source_module}: initializer capability structure: {detail}"
        )

    development_classes = [
        statement
        for statement in tree.body
        if isinstance(statement, ast.ClassDef)
        and statement.name == "DevelopmentCorpusProvider"
    ]
    if len(development_classes) != 1:
        fail("expected one top-level DevelopmentCorpusProvider class")

    load_methods = [
        statement
        for statement in development_classes[0].body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "load"
    ]
    if len(load_methods) != 1 or not isinstance(load_methods[0], ast.FunctionDef):
        fail("expected one top-level DevelopmentCorpusProvider.load method")
    load_method = load_methods[0]
    development_plan = _approved_plan_cases_call(
        load_method.body,
        target_name="plans",
        matcher=_is_development_provider_plan_call,
    )
    if development_plan is None:
        fail(
            "expected one approved plans = "
            "self._generator.plan_cases(EvaluationScope.DEVELOPMENT) assignment"
        )

    legacy_functions = [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "render_diagnostic"
    ]
    if len(legacy_functions) != 1 or not isinstance(
        legacy_functions[0], ast.FunctionDef
    ):
        fail("expected one top-level render_diagnostic function")
    legacy_function = legacy_functions[0]
    legacy_plan = _approved_plan_cases_call(
        legacy_function.body,
        target_name="templates",
        matcher=_is_legacy_v1_plan_call,
    )
    if legacy_plan is None:
        fail(
            "expected one approved templates = "
            "v1_generator.plan_cases(DatasetProfile.FULL) assignment"
        )

    return _InitializerPolicy(
        (
            _ExactCallSite(
                "study-truth-development-plan",
                _source_location(source_module, development_plan),
                (),
                identity_node=development_plan,
            ),
            _ExactCallSite(
                "study-truth-legacy-plan",
                _source_location(source_module, legacy_plan),
                (),
                identity_node=legacy_plan,
            ),
        ),
        (),
    )


def _validate_cli_json_policy(
    source_module: str,
    tree: ast.Module,
) -> _InitializerPolicy:
    candidates = [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "_json_value"
    ]
    if not candidates:
        return _EMPTY_INITIALIZER_POLICY

    def fail(detail: str) -> NoReturn:
        raise StudyRetentionError(
            f"{source_module}:0:{detail}; "
            "source capability rejected: namespace-reflection"
        )

    if len(candidates) != 1 or not isinstance(candidates[0], ast.FunctionDef):
        fail("expected one top-level synchronous _json_value")
    function = candidates[0]
    arguments = function.args
    if not (
        not function.decorator_list
        and not arguments.posonlyargs
        and len(arguments.args) == 1
        and arguments.args[0].arg == "value"
        and _is_name(arguments.args[0].annotation, "object", ast.Load)
        and arguments.vararg is None
        and not arguments.kwonlyargs
        and arguments.kwarg is None
        and not arguments.defaults
        and not arguments.kw_defaults
        and _is_name(function.returns, "object", ast.Load)
    ):
        fail("_json_value must preserve its exact undecorated signature")
    if len(function.body) != 7:
        fail("_json_value must preserve its exact branch structure")
    dataclass_if = function.body[5]
    if not isinstance(dataclass_if, ast.If):
        fail("_json_value must preserve the dataclass guard")
    guard = dataclass_if.test
    if (
        not isinstance(guard, ast.BoolOp)
        or not isinstance(guard.op, ast.And)
        or len(guard.values) != 2
        or not _is_one_name_call(guard.values[0], "is_dataclass", "value")
        or not isinstance(guard.values[1], ast.UnaryOp)
        or not isinstance(guard.values[1].op, ast.Not)
        or not _is_two_name_call(
            guard.values[1].operand,
            "isinstance",
            "value",
            "type",
        )
    ):
        fail("_json_value must preserve the exact dataclass guard")
    if len(dataclass_if.body) != 1 or dataclass_if.orelse:
        fail("_json_value must preserve the dataclass return")
    dataclass_return = dataclass_if.body[0]
    if not isinstance(dataclass_return, ast.Return) or not isinstance(
        dataclass_return.value, ast.DictComp
    ):
        fail("_json_value must preserve the dataclass comprehension")
    comprehension = dataclass_return.value
    if len(comprehension.generators) != 1:
        fail("_json_value must preserve one fields comprehension")
    generator = comprehension.generators[0]
    if (
        generator.is_async
        or not _is_name(generator.target, "field", ast.Store)
        or not _is_one_name_call(generator.iter, "fields", "value")
        or len(generator.ifs) != 1
        or not _is_private_field_filter(generator.ifs[0])
        or not _is_field_name(comprehension.key)
    ):
        fail("_json_value must preserve fields and the private-name filter")
    recursive_call = comprehension.value
    if (
        not isinstance(recursive_call, ast.Call)
        or not _is_name(recursive_call.func, "_json_value", ast.Load)
        or len(recursive_call.args) != 1
        or recursive_call.keywords
        or not isinstance(recursive_call.args[0], ast.Call)
    ):
        fail("_json_value must preserve its recursive dataclass call")
    reflected = recursive_call.args[0]
    if (
        not _is_name(reflected.func, "getattr", ast.Load)
        or len(reflected.args) != 2
        or reflected.keywords
        or not _is_name(reflected.args[0], "value", ast.Load)
        or not _is_field_name(reflected.args[1])
    ):
        fail("_json_value must preserve its exact dataclass getattr")
    required_bindings = tuple(
        sorted(
            (
                ("fields", _ResolvedIdentity("imported", "dataclasses", "fields")),
                (
                    "is_dataclass",
                    _ResolvedIdentity("imported", "dataclasses", "is_dataclass"),
                ),
                ("getattr", _ResolvedIdentity("builtin", "builtins", "getattr")),
                (
                    "isinstance",
                    _ResolvedIdentity("builtin", "builtins", "isinstance"),
                ),
                ("type", _ResolvedIdentity("builtin", "builtins", "type")),
                (
                    "_json_value",
                    _ResolvedIdentity(
                        "function",
                        source_module,
                        "_json_value",
                        _source_location(source_module, function),
                    ),
                ),
            )
        )
    )
    is_dataclass_call = cast(ast.Call, guard.values[0])
    isinstance_call = cast(ast.Call, guard.values[1].operand)
    fields_call = cast(ast.Call, generator.iter)
    exact_names = (
        cast(ast.Name, is_dataclass_call.func),
        cast(ast.Name, isinstance_call.func),
        cast(ast.Name, isinstance_call.args[1]),
        cast(ast.Name, fields_call.func),
        cast(ast.Name, recursive_call.func),
        cast(ast.Name, reflected.func),
    )
    return _InitializerPolicy(
        tuple(
            _ExactCallSite(
                "cli-dataclass-getattr",
                _source_location(source_module, node),
                required_bindings,
            )
            for node in exact_names
        ),
        (),
    )


def _is_one_name_call(node: ast.AST, function: str, argument: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and _is_name(node.func, function, ast.Load)
        and len(node.args) == 1
        and _is_name(node.args[0], argument, ast.Load)
        and not node.keywords
    )


def _is_two_name_call(
    node: ast.AST,
    function: str,
    first: str,
    second: str,
) -> bool:
    return (
        isinstance(node, ast.Call)
        and _is_name(node.func, function, ast.Load)
        and len(node.args) == 2
        and _is_name(node.args[0], first, ast.Load)
        and _is_name(node.args[1], second, ast.Load)
        and not node.keywords
    )


def _approved_plan_cases_call(
    statements: Sequence[ast.stmt],
    *,
    target_name: str,
    matcher: Callable[[ast.Call], bool],
) -> ast.Call | None:
    matches: list[ast.Call] = []
    for statement in statements:
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not _is_name(statement.targets[0], target_name, ast.Store)
            or not isinstance(statement.value, ast.Call)
            or not matcher(statement.value)
        ):
            continue
        matches.append(statement.value)
    if len(matches) != 1:
        return None
    return matches[0]


def _is_development_provider_plan_call(node: ast.Call) -> bool:
    if (
        not isinstance(node.func, ast.Attribute)
        or node.func.attr != "plan_cases"
        or not isinstance(node.func.value, ast.Attribute)
        or node.func.value.attr != "_generator"
        or not _is_name(node.func.value.value, "self", ast.Load)
        or len(node.args) != 1
        or node.keywords
    ):
        return False
    argument = node.args[0]
    return (
        isinstance(argument, ast.Attribute)
        and _is_name(argument.value, "EvaluationScope", ast.Load)
        and argument.attr == "DEVELOPMENT"
    )


def _is_legacy_v1_plan_call(node: ast.Call) -> bool:
    if (
        not isinstance(node.func, ast.Attribute)
        or node.func.attr != "plan_cases"
        or not _is_name(node.func.value, "v1_generator", ast.Load)
        or len(node.args) != 1
        or node.keywords
    ):
        return False
    argument = node.args[0]
    return (
        isinstance(argument, ast.Attribute)
        and _is_name(argument.value, "DatasetProfile", ast.Load)
        and argument.attr == "FULL"
    )


def _is_field_name(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and _is_name(node.value, "field", ast.Load)
        and node.attr == "name"
    )


def _is_private_field_filter(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.Not)
        and isinstance(node.operand, ast.Call)
        and isinstance(node.operand.func, ast.Attribute)
        and _is_field_name(node.operand.func.value)
        and node.operand.func.attr == "startswith"
        and len(node.operand.args) == 1
        and _string_literal(node.operand.args[0]) == "_"
        and not node.operand.keywords
    )


def _statement_binds_name(statement: ast.stmt, name: str) -> bool:
    targets: tuple[ast.expr, ...]
    if isinstance(statement, ast.Assign):
        targets = tuple(statement.targets)
    elif isinstance(statement, ast.AnnAssign):
        targets = (statement.target,)
    else:
        return False
    return any(
        isinstance(node, ast.Name) and node.id == name
        for target in targets
        for node in ast.walk(target)
    )


def _one_module_function(
    tree: ast.Module,
    name: str,
    fail: Callable[[str], NoReturn],
) -> ast.FunctionDef:
    candidates = [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == name
    ]
    if len(candidates) != 1 or not isinstance(candidates[0], ast.FunctionDef):
        fail(f"expected one module-level {name} function")
    return candidates[0]


def _has_exact_getattr_signature(function: ast.FunctionDef) -> bool:
    arguments = function.args
    return (
        not function.decorator_list
        and not arguments.posonlyargs
        and len(arguments.args) == 1
        and arguments.args[0].arg == "name"
        and _is_name(arguments.args[0].annotation, "str", ast.Load)
        and arguments.vararg is None
        and not arguments.kwonlyargs
        and arguments.kwarg is None
        and not arguments.defaults
        and not arguments.kw_defaults
        and _is_name(function.returns, "Any", ast.Load)
    )


def _has_exact_dir_signature(function: ast.FunctionDef) -> bool:
    arguments = function.args
    returns = function.returns
    return (
        not function.decorator_list
        and not arguments.posonlyargs
        and not arguments.args
        and arguments.vararg is None
        and not arguments.kwonlyargs
        and arguments.kwarg is None
        and not arguments.defaults
        and not arguments.kw_defaults
        and isinstance(returns, ast.Subscript)
        and _is_name(returns.value, "list", ast.Load)
        and _is_name(returns.slice, "str", ast.Load)
    )


def _is_lazy_lookup_try(node: ast.stmt) -> bool:
    if (
        not isinstance(node, ast.Try)
        or len(node.body) != 1
        or len(node.handlers) != 1
        or node.orelse
        or node.finalbody
    ):
        return False
    lookup = node.body[0]
    if (
        not isinstance(lookup, ast.Assign)
        or len(lookup.targets) != 1
        or not isinstance(lookup.targets[0], ast.Tuple)
        or len(lookup.targets[0].elts) != 2
        or not _is_name(lookup.targets[0].elts[0], "module_name", ast.Store)
        or not _is_name(lookup.targets[0].elts[1], "attribute_name", ast.Store)
        or not isinstance(lookup.value, ast.Subscript)
        or not _is_name(lookup.value.value, "_LAZY_EXPORTS", ast.Load)
        or not _is_name(lookup.value.slice, "name", ast.Load)
    ):
        return False
    handler = node.handlers[0]
    if (
        not _is_name(handler.type, "KeyError", ast.Load)
        or handler.name is not None
        or len(handler.body) != 1
        or not isinstance(handler.body[0], ast.Raise)
    ):
        return False
    raised = handler.body[0]
    return (
        isinstance(raised.exc, ast.Call)
        and _is_name(raised.exc.func, "AttributeError", ast.Load)
        and len(raised.exc.args) == 1
        and _is_exact_attribute_error_message(raised.exc.args[0])
        and not raised.exc.keywords
        and isinstance(raised.cause, ast.Constant)
        and raised.cause.value is None
    )


def _is_exact_attribute_error_message(node: ast.expr) -> bool:
    if not isinstance(node, ast.JoinedStr) or len(node.values) != 4:
        return False
    return (
        isinstance(node.values[0], ast.Constant)
        and node.values[0].value == "module "
        and _is_repr_formatted_name(node.values[1], "__name__")
        and isinstance(node.values[2], ast.Constant)
        and node.values[2].value == " has no attribute "
        and _is_repr_formatted_name(node.values[3], "name")
    )


def _is_repr_formatted_name(node: ast.expr, name: str) -> bool:
    return (
        isinstance(node, ast.FormattedValue)
        and _is_name(node.value, name, ast.Load)
        and node.conversion == ord("r")
        and node.format_spec is None
    )


def _lazy_value_loader_nodes(
    node: ast.stmt,
) -> tuple[ast.Call, ast.Call] | None:
    if (
        not isinstance(node, ast.Assign)
        or len(node.targets) != 1
        or not _is_name(node.targets[0], "value", ast.Store)
        or not isinstance(node.value, ast.Call)
        or not _is_name(node.value.func, "getattr", ast.Load)
        or len(node.value.args) != 2
        or node.value.keywords
        or not isinstance(node.value.args[0], ast.Call)
        or not _is_name(node.value.args[1], "attribute_name", ast.Load)
    ):
        return None
    import_call = node.value.args[0]
    if (
        not _is_name(import_call.func, "import_module", ast.Load)
        or len(import_call.args) != 1
        or not _is_name(import_call.args[0], "module_name", ast.Load)
        or import_call.keywords
    ):
        return None
    return node.value, import_call


def _lazy_cache_globals_call(node: ast.stmt) -> ast.Call | None:
    if (
        not isinstance(node, ast.Assign)
        or len(node.targets) != 1
        or not isinstance(node.targets[0], ast.Subscript)
        or not _is_name(node.targets[0].slice, "name", ast.Load)
        or not _is_name(node.value, "value", ast.Load)
    ):
        return None
    namespace = node.targets[0].value
    if (
        not isinstance(namespace, ast.Call)
        or not _is_name(namespace.func, "globals", ast.Load)
        or namespace.args
        or namespace.keywords
    ):
        return None
    return namespace


def _dir_globals_call(node: ast.stmt) -> ast.Call | None:
    if (
        not isinstance(node, ast.Return)
        or not isinstance(node.value, ast.Call)
        or not _is_name(node.value.func, "sorted", ast.Load)
        or len(node.value.args) != 1
        or node.value.keywords
        or not isinstance(node.value.args[0], ast.BinOp)
        or not isinstance(node.value.args[0].op, ast.BitOr)
    ):
        return None
    left = node.value.args[0].left
    right = node.value.args[0].right
    if (
        not isinstance(left, ast.Call)
        or not _is_name(left.func, "set", ast.Load)
        or len(left.args) != 1
        or left.keywords
        or not isinstance(left.args[0], ast.Call)
        or not isinstance(right, ast.Call)
        or not _is_name(right.func, "set", ast.Load)
        or len(right.args) != 1
        or right.keywords
        or not _is_name(right.args[0], "__all__", ast.Load)
    ):
        return None
    namespace = left.args[0]
    if (
        not _is_name(namespace.func, "globals", ast.Load)
        or namespace.args
        or namespace.keywords
    ):
        return None
    return namespace


def _is_name(node: ast.AST | None, name: str, context: type[ast.expr_context]) -> bool:
    return isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, context)


def _string_literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_package_target(value: str) -> bool:
    return value == "manufacturing_vision_studio" or value.startswith(
        "manufacturing_vision_studio."
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


def _closure_error_key(error: str) -> tuple[int, str]:
    priorities = (
        "unsupported source-flow syntax",
        "source capability rejected: deferred-effect",
        "source capability rejected: dynamic-import",
        "source capability rejected: executable-code",
        "source capability rejected: namespace-reflection",
        "source capability rejected: import-registry",
        "source capability rejected: package-object",
    )
    for priority, marker in enumerate(priorities):
        if marker in error:
            return priority, error
    return len(priorities), error


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
    _verify_monotonic_evidence_history(
        repo_root,
        execution_commit=execution_commit,
        current_commit=current,
        artifact_relative=artifact_relative,
        allow_retained_input_copies=allow_retained_input_copies,
    )
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


def _verify_pristine_artifact_history(
    protocol: StudyProtocolV2,
    *,
    repo_root: Path,
    current_commit: str,
) -> None:
    """Reject evidence that was committed before first validation publication."""

    _require_git_commit(repo_root, protocol.base_commit, label="study base commit")
    _require_git_commit(repo_root, current_commit, label="validation execution commit")
    source_branch = _run_git(
        repo_root,
        "rev-parse",
        "--verify",
        f"refs/heads/{_SOURCE_BRANCH}^{{commit}}",
    )
    if source_branch != protocol.base_commit:
        raise StudyRetentionError("frozen source branch no longer resolves to study base")
    _require_ancestor(repo_root, protocol.base_commit, current_commit)
    artifact_relative = _artifact_relative_path(protocol, repo_root)
    for parent, commit in _linear_commit_history(
        repo_root,
        older=protocol.base_commit,
        newer=current_commit,
    ):
        for change in _git_changed_paths(repo_root, parent, commit):
            if any(
                _under_artifact_root(path, artifact_relative) for path in change.paths
            ):
                raise StudyRetentionError(
                    "prior committed artifact history prevents first validation publication"
                )


def _verify_monotonic_evidence_history(
    repo_root: Path,
    *,
    execution_commit: str,
    current_commit: str,
    artifact_relative: str,
    allow_retained_input_copies: bool,
) -> None:
    """Require the full evidence chain to be linear and add-only."""

    for parent, commit in _linear_commit_history(
        repo_root,
        older=execution_commit,
        newer=current_commit,
    ):
        for change in _git_changed_paths(repo_root, parent, commit):
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
                continue
            if change.status != "A":
                raise StudyRetentionError(
                    "git monotonic evidence history rejects non-add evidence status"
                )
            if not _under_artifact_root(change.destination, artifact_relative):
                raise StudyRetentionError(
                    "git monotonic evidence history contains non-artifact paths"
                )


def _linear_commit_history(
    root: Path,
    *,
    older: str,
    newer: str,
) -> tuple[tuple[str, str], ...]:
    """Return every parent-to-child edge in a sealed single-parent ancestry chain."""

    output = _run_git(root, "rev-list", "--reverse", "--parents", f"{older}..{newer}")
    if not output:
        return ()
    previous = older
    history: list[tuple[str, str]] = []
    for record in output.splitlines():
        fields = record.split()
        if len(fields) != 2:
            raise StudyRetentionError("git monotonic evidence history is not linear")
        commit, parent = fields
        _require_lower_hex(commit, _SHA1_LENGTH, "lineage commit")
        _require_lower_hex(parent, _SHA1_LENGTH, "lineage parent")
        if parent != previous:
            raise StudyRetentionError("git monotonic evidence history is not linear")
        history.append((parent, commit))
        previous = commit
    if previous != newer:
        raise StudyRetentionError("git monotonic evidence history is incomplete")
    return tuple(history)


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
