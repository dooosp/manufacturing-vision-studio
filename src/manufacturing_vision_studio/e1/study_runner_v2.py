"""Sealed orchestration and semantic state inspection for the E1 study."""

from __future__ import annotations

import json
import os
import platform
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol, cast

import numpy as np
from PIL import Image
from PIL import __version__ as pillow_version

from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.feature_mapping import FeatureMappingResult
from manufacturing_vision_studio.e1.known_transform_v2 import (
    AppliedAffineTransform,
    KnownTransformResult,
    ReferenceBoundaryBand,
    ResamplingMode,
    normalize_known_transform,
    reference_boundary_band,
)
from manufacturing_vision_studio.e1.metrics_v2 import E1V2EvaluationObservation, Outcome
from manufacturing_vision_studio.e1.protocol_v2 import E1V2Protocol, load_e1_v2_protocol
from manufacturing_vision_studio.e1.study_artifacts_v2 import (
    StudyArtifactError,
    StudyArtifactRecord,
    StudyArtifactStore,
    StudyGateRecord,
    VerifiedStudyJson,
    _frozen_oracle_layout_projection,
    begin_phase_execution,
    finalize_study_record,
    verify_inference_trace_consistency,
)
from manufacturing_vision_studio.e1.study_inference_v2 import (
    StudyInferenceAdapter,
    StudyInferenceInput,
    StudyInferenceResult,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    PROJECT_ROOT,
    FrozenDiagnosticPlan,
    StudyProtocolV2,
    load_frozen_diagnostic_matrix,
    load_study_protocol_v2,
)
from manufacturing_vision_studio.e1.study_retention_v2 import (
    IMPLEMENTATION_VALIDATION_COMMANDS,
    IMPLEMENTATION_VALIDATION_TIMEOUT_SECONDS,
    NOT_APPLICABLE_CONTROLS,
    VALIDATION_SYSTEM_PATH_SUFFIX,
    ProjectionEntry,
    StudyRetentionError,
    _git_status_paths,
    _run_git,
    _run_git_bytes,
    _verify_git_lineage,
    _verify_pristine_artifact_history,
    build_study_implementation_projection,
    reviewed_validation_executable_roots,
    run_retention_audit,
    verify_implementation_validation,
    verify_retention_audit,
)
from manufacturing_vision_studio.e1.study_truth_v2 import (
    DevelopmentCorpus,
    DevelopmentCorpusProvider,
    DevelopmentModeSummary,
    DiagnosticModeSummary,
    DiagnosticObservation,
    FeatureOracleResult,
    StudyTruthCase,
    diagnostic_observation,
    make_truth_free_input,
    observation_from_study,
    raw_identity_difference_mask,
    reduce_development_mode,
    reduce_diagnostic_mode,
    render_diagnostic,
    run_feature_ownership_oracle,
)

TerminalDecision = Literal[
    "PENDING",
    "STUDY_INVALID",
    "FEATURE_CONTRACT_FAILED",
    "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED",
    "DIFFERENCE_BASELINE_LIMITED",
    "TRANSFORM_ESTIMATION_LIMITED",
]

_PRE_DECISION_PATHS = (
    "implementation-validation.json",
    "retention-audit.json",
    "phase-1-execution-claim.json",
    "known-transform-diagnostic-108.json",
    "scope-audit.json",
    "feature-ownership-oracle.json",
    "phase-2-execution-claim.json",
    "known-transform-development-120.json",
)
_JSON_RECORD_TYPES = {
    "implementation-validation.json": "implementation_validation",
    "retention-audit.json": "retention_audit",
    "phase-1-execution-claim.json": "phase_execution_claim",
    "known-transform-diagnostic-108.json": "diagnostic_result",
    "scope-audit.json": "scope_audit",
    "feature-ownership-oracle.json": "feature_oracle",
    "phase-2-execution-claim.json": "phase_execution_claim",
    "known-transform-development-120.json": "development_result",
    "decision.json": "decision",
}
_RETAINED_DIRECTORY = "retained-inputs"
_RETAINED_FILES = (
    "retained-inputs/candidate-a.json",
    "retained-inputs/candidate-b.json",
    "retained-inputs/task-4-report.md",
    "retained-inputs/sdd-progress.md",
)
_EXPECTED_KINDS = {
    **{path: "file" for path in _JSON_RECORD_TYPES},
    "report.md": "file",
    _RETAINED_DIRECTORY: "directory",
    **{path: "file" for path in _RETAINED_FILES},
}
_ARTIFACT_VERIFICATION_DEPENDENCIES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "retention-audit.json": ("implementation-validation.json",),
        "phase-1-execution-claim.json": ("retention-audit.json",),
        "known-transform-diagnostic-108.json": (
            "retention-audit.json",
            "phase-1-execution-claim.json",
        ),
        "scope-audit.json": (
            "retention-audit.json",
            "known-transform-diagnostic-108.json",
        ),
        "feature-ownership-oracle.json": (
            "scope-audit.json",
            "known-transform-diagnostic-108.json",
        ),
        "phase-2-execution-claim.json": ("feature-ownership-oracle.json",),
        "known-transform-development-120.json": (
            "retention-audit.json",
            "known-transform-diagnostic-108.json",
            "scope-audit.json",
            "feature-ownership-oracle.json",
            "phase-2-execution-claim.json",
        ),
        "report.md": ("decision.json",),
    }
)
_VALIDATION_OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
_ALLOWED_NEXT_ACTIONS = {
    "STUDY_INVALID": "Repair evidence machinery only; no performance conclusion",
    "FEATURE_CONTRACT_FAILED": "New protocol/ownership design; do not alter model",
    "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED": (
        "End affine-candidate search; analyze resampling/baseline residual evidence"
    ),
    "DIFFERENCE_BASELINE_LIMITED": (
        "Preserve negative result; Candidate C prohibited; a new model family needs a new protocol"
    ),
    "TRANSFORM_ESTIMATION_LIMITED": (
        "A separate approved plan may design exactly one evidence-based Candidate C"
    ),
}
_DECISION_REASONS = {
    "STUDY_INVALID": "ARTIFACT_VERIFICATION_FAILED",
    "FEATURE_CONTRACT_FAILED": "FEATURE_ORACLE_FAILED",
    "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED": "NO_DIAGNOSTIC_MODE_ELIGIBLE",
    "DIFFERENCE_BASELINE_LIMITED": "NO_DEVELOPMENT_MODE_PASSED",
    "TRANSFORM_ESTIMATION_LIMITED": "DEVELOPMENT_MODE_PASSED",
}


class StudyStateError(ValueError):
    """The immutable study packet is incomplete, invalid, or unauthorized."""


@dataclass(frozen=True, slots=True)
class StudyStatus:
    study_valid: bool
    phase1_complete: bool
    feature_oracle_complete: bool
    phase2_authorized: bool
    phase2_complete: bool
    terminal_decision: TerminalDecision
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StudyVerificationReport:
    verified_paths: tuple[str, ...]
    verify_rate: float
    status: StudyStatus


@dataclass(frozen=True, slots=True)
class ValidationCommandRequest:
    name: str
    argv: tuple[str, ...]
    executable_lookup_path: Path
    cwd: Path
    environment: Mapping[str, str]
    timeout_seconds: int
    output_limit_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


@dataclass(frozen=True, slots=True)
class ValidationCommandResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    started_at_utc: datetime
    ended_at_utc: datetime


@dataclass(frozen=True, slots=True)
class DeterminismControl:
    first_projection: Mapping[str, str]
    second_projection: Mapping[str, str]
    passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "first_projection",
            MappingProxyType(dict(self.first_projection)),
        )
        object.__setattr__(
            self,
            "second_projection",
            MappingProxyType(dict(self.second_projection)),
        )


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    head: str
    dirty_paths: tuple[str, ...]
    projection: tuple[ProjectionEntry, ...]


class NormalizeCallback(Protocol):
    def __call__(
        self,
        reference_bytes: bytes,
        inspection_bytes: bytes,
        *,
        reference_sha256: str,
        inspection_sha256: str,
        applied_transform: AppliedAffineTransform,
        resampling: ResamplingMode,
    ) -> KnownTransformResult: ...


CommandRunner = Callable[[ValidationCommandRequest], ValidationCommandResult]
ExecutableResolver = Callable[[str, str | None], Path]
RepositoryStateReader = Callable[[], RepositorySnapshot]
DiagnosticMatrixLoader = Callable[[], tuple[FrozenDiagnosticPlan, ...]]
DiagnosticRenderer = Callable[
    [FrozenDiagnosticPlan, StudyProtocolV2, E1V2Protocol], StudyTruthCase
]
CorpusLoader = Callable[[], DevelopmentCorpus]
OracleRunner = Callable[
    [DevelopmentCorpus, E1V2Protocol, StudyProtocolV2], FeatureOracleResult
]
InferenceRunner = Callable[[StudyInferenceInput], StudyInferenceResult]


@dataclass(frozen=True, slots=True)
class VerifiedStudyState:
    """Pure semantic state plus immutable single-read JSON evidence."""

    status: StudyStatus
    present_paths: tuple[str, ...]
    invalid_paths: tuple[str, ...]
    verified_json: Mapping[str, VerifiedStudyJson]

    @property
    def verified_paths(self) -> tuple[str, ...]:
        return tuple(path for path in self.present_paths if path not in self.invalid_paths)


@dataclass(frozen=True, slots=True)
class _SemanticStudyEvidence:
    execution_commit: str | None
    eligible_modes: tuple[ResamplingMode, ...]
    oracle_passed: bool | None
    passing_modes: tuple[ResamplingMode, ...]


def inspect_state(
    protocol: StudyProtocolV2,
    *,
    repo_root: Path = PROJECT_ROOT,
    store: StudyArtifactStore | None = None,
) -> VerifiedStudyState:
    """Inspect the fixed packet without creating roots or invoking study callbacks."""

    owned_store = False
    if store is None:
        try:
            store = StudyArtifactStore.open_existing(
                protocol.artifact_root,
                allowed_root=repo_root,
            )
        except StudyArtifactError:
            return _invalid_state(("ARTIFACT_ROOT_UNSAFE",))
        if store is None:
            return _pending_state()
        owned_store = True
    try:
        return _inspect_open_store(protocol, store)
    finally:
        if owned_store:
            store.close()


def _inspect_open_store(
    protocol: StudyProtocolV2,
    store: StudyArtifactStore,
) -> VerifiedStudyState:
    try:
        inventory = store.inventory()
    except StudyArtifactError:
        return _invalid_state(("ARTIFACT_INVENTORY_INVALID",))
    present = tuple(entry.path for entry in inventory if entry.kind != "directory")
    inventory_invalid = tuple(
        entry.path
        for entry in inventory
        if _EXPECTED_KINDS.get(entry.path) != entry.kind
        or (entry.kind == "file" and entry.link_count != 1)
    )
    if inventory_invalid:
        return _invalid_state(
            ("ARTIFACT_INVENTORY_INVALID",),
            present_paths=present,
            invalid_paths=inventory_invalid,
        )

    inventory_paths = {entry.path for entry in inventory}
    retained_present = inventory_paths.intersection(
        {_RETAINED_DIRECTORY, *_RETAINED_FILES}
    )

    present_set = set(present)
    verified: dict[str, VerifiedStudyJson] = {}
    invalid_json: list[str] = []
    for path, record_type in _JSON_RECORD_TYPES.items():
        if path not in present_set:
            continue
        try:
            verified[path] = store.verify_json_result(
                path,
                expected_record_type=record_type,
            )
        except StudyArtifactError:
            invalid_json.append(path)
    if invalid_json:
        invalid = _invalid_state(
            ("ARTIFACT_VERIFICATION_FAILED",),
            present_paths=present,
            invalid_paths=tuple(invalid_json),
            verified_json=verified,
        )
        return _verify_invalid_terminal_projection(
            protocol,
            store,
            invalid,
            present_set,
        )
    relationship_reasons = _relationship_reasons(present_set, retained_present)
    if relationship_reasons:
        invalid = _invalid_state(
            relationship_reasons,
            present_paths=present,
            invalid_paths=_relationship_invalid_paths(
                present,
                retained_present=retained_present,
                reasons=relationship_reasons,
            ),
            verified_json=verified,
        )
        return _verify_invalid_terminal_projection(
            protocol,
            store,
            invalid,
            present_set,
        )

    try:
        semantic = _verify_semantic_packet(protocol, verified, present_set)
    except (StudyArtifactError, StudyStateError, TypeError, ValueError, KeyError):
        invalid = _invalid_state(
            ("ARTIFACT_VERIFICATION_FAILED",),
            present_paths=present,
            invalid_paths=tuple(
                path
                for path in _PRE_DECISION_PATHS
                if path in present_set
            ),
            verified_json=verified,
        )
        return _verify_invalid_terminal_projection(
            protocol,
            store,
            invalid,
            present_set,
        )

    phase1_claim = "phase-1-execution-claim.json" in present_set
    phase1_result = "known-transform-diagnostic-108.json" in present_set
    scope = "scope-audit.json" in present_set
    oracle = "feature-ownership-oracle.json" in present_set
    phase2_claim = "phase-2-execution-claim.json" in present_set
    phase2_result = "known-transform-development-120.json" in present_set
    phase1_complete = phase1_claim and phase1_result
    oracle_complete = scope and oracle
    phase2_complete = phase2_claim and phase2_result
    terminal_decision: TerminalDecision = "PENDING"
    phase2_prerequisites_met = False
    phase2_authorized = False
    reasons: tuple[str, ...] = ()
    if oracle_complete:
        if semantic.oracle_passed is False:
            terminal_decision = "FEATURE_CONTRACT_FAILED"
            reasons = ("FEATURE_ORACLE_FAILED",)
        elif not semantic.eligible_modes:
            terminal_decision = "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED"
            reasons = ("NO_DIAGNOSTIC_MODE_ELIGIBLE",)
        else:
            phase2_prerequisites_met = True
        if phase2_prerequisites_met and not phase2_complete:
            phase2_authorized = True
        elif phase2_prerequisites_met and not semantic.passing_modes:
            terminal_decision = "DIFFERENCE_BASELINE_LIMITED"
            reasons = ("NO_DEVELOPMENT_MODE_PASSED",)
        elif phase2_prerequisites_met:
            terminal_decision = "TRANSFORM_ESTIMATION_LIMITED"
            reasons = ("DEVELOPMENT_MODE_PASSED",)
    if (phase2_claim or phase2_result) and not phase2_prerequisites_met:
        invalid = _invalid_state(
            ("UNAUTHORIZED_PHASE2_ARTIFACT",),
            present_paths=present,
            invalid_paths=tuple(
                path
                for path in (
                    "phase-2-execution-claim.json",
                    "known-transform-development-120.json",
                )
                if path in present_set
            ),
            verified_json=verified,
        )
        return _verify_invalid_terminal_projection(
            protocol,
            store,
            invalid,
            present_set,
        )
    if "decision.json" in present_set:
        if terminal_decision == "PENDING" or not _decision_matches_state(
            verified,
            terminal_decision,
            tuple(path for path in _PRE_DECISION_PATHS if path in present_set),
            (),
        ):
            return _invalid_state(
                ("ARTIFACT_VERIFICATION_FAILED",),
                present_paths=present,
                invalid_paths=("decision.json",),
                verified_json=verified,
            )
        if "report.md" in present_set:
            decision = verified["decision.json"]
            try:
                expected_report = _decision_report(decision.document)
                actual_report = store.read_bytes("report.md")
            except StudyArtifactError:
                return _invalid_state(
                    ("ARTIFACT_VERIFICATION_FAILED",),
                    present_paths=present,
                    invalid_paths=("report.md",),
                    verified_json=verified,
                )
            if actual_report != expected_report:
                return _invalid_state(
                    ("ARTIFACT_VERIFICATION_FAILED",),
                    present_paths=present,
                    invalid_paths=("report.md",),
                    verified_json=verified,
                )
    status = StudyStatus(
        study_valid=True,
        phase1_complete=phase1_complete,
        feature_oracle_complete=oracle_complete,
        phase2_authorized=phase2_authorized,
        phase2_complete=phase2_complete,
        terminal_decision=terminal_decision,
        reasons=reasons,
    )
    return VerifiedStudyState(
        status=status,
        present_paths=tuple(
            path
            for path in (*_PRE_DECISION_PATHS, "decision.json", "report.md")
            if path in present_set
        ),
        invalid_paths=(),
        verified_json=MappingProxyType(verified),
    )


def _pending_state() -> VerifiedStudyState:
    status = StudyStatus(
        study_valid=True,
        phase1_complete=False,
        feature_oracle_complete=False,
        phase2_authorized=False,
        phase2_complete=False,
        terminal_decision="PENDING",
        reasons=(),
    )
    return VerifiedStudyState(status, (), (), MappingProxyType({}))


def _relationship_reasons(
    present_set: set[str],
    retained_present: set[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    phase1_claim = "phase-1-execution-claim.json" in present_set
    phase1_result = "known-transform-diagnostic-108.json" in present_set
    if phase1_claim is not phase1_result:
        reasons.append("PHASE1_CLAIM_RESULT_ORPHAN")
    scope = "scope-audit.json" in present_set
    oracle = "feature-ownership-oracle.json" in present_set
    if scope is not oracle:
        reasons.append("SCOPE_ORACLE_ORPHAN")
    phase2_claim = "phase-2-execution-claim.json" in present_set
    phase2_result = "known-transform-development-120.json" in present_set
    if phase2_claim is not phase2_result:
        reasons.append("PHASE2_CLAIM_RESULT_ORPHAN")
    if "report.md" in present_set and "decision.json" not in present_set:
        reasons.append("REPORT_WITHOUT_DECISION")

    retention_complete = (
        "retention-audit.json" in present_set
        and retained_present == {_RETAINED_DIRECTORY, *_RETAINED_FILES}
    )
    if retained_present and "retention-audit.json" not in present_set:
        reasons.append("PARTIAL_RETENTION_PACKET")
    if "retention-audit.json" in present_set and not retention_complete:
        reasons.append("PARTIAL_RETENTION_PACKET")
    if any(
        path not in retained_present and path != "implementation-validation.json"
        for path in present_set
    ) and ("implementation-validation.json" not in present_set):
        reasons.append("MISSING_IMPLEMENTATION_VALIDATION")
    if (phase1_claim or phase1_result) and not retention_complete:
        reasons.append("PHASE1_WITHOUT_RETENTION")
    if (scope or oracle) and not (phase1_claim and phase1_result):
        reasons.append("ORACLE_WITHOUT_PHASE1")
    if (phase2_claim or phase2_result) and not (scope and oracle):
        reasons.append("PHASE2_WITHOUT_ORACLE")
    return tuple(dict.fromkeys(reasons))


def _relationship_invalid_paths(
    present_paths: tuple[str, ...],
    *,
    retained_present: set[str],
    reasons: tuple[str, ...],
) -> tuple[str, ...]:
    invalid: set[str] = set()
    if "MISSING_IMPLEMENTATION_VALIDATION" in reasons:
        invalid.update(present_paths)
    if any(
        reason in reasons
        for reason in ("PARTIAL_RETENTION_PACKET", "PHASE1_WITHOUT_RETENTION")
    ):
        invalid.update(path for path in present_paths if path in _PRE_DECISION_PATHS[1:])
        invalid.update(retained_present)
    if "PHASE1_CLAIM_RESULT_ORPHAN" in reasons:
        invalid.update(path for path in present_paths if path in _PRE_DECISION_PATHS[2:])
    if any(reason in reasons for reason in ("SCOPE_ORACLE_ORPHAN", "ORACLE_WITHOUT_PHASE1")):
        invalid.update(path for path in present_paths if path in _PRE_DECISION_PATHS[4:])
    if "PHASE2_CLAIM_RESULT_ORPHAN" in reasons or "PHASE2_WITHOUT_ORACLE" in reasons:
        invalid.update(path for path in present_paths if path in _PRE_DECISION_PATHS[6:])
    if "REPORT_WITHOUT_DECISION" in reasons:
        invalid.add("report.md")
    return tuple(path for path in present_paths if path in invalid)


def _verify_semantic_packet(
    protocol: StudyProtocolV2,
    verified: Mapping[str, VerifiedStudyJson],
    present: set[str],
) -> _SemanticStudyEvidence:
    validation = verified.get("implementation-validation.json")
    if validation is None:
        if verified:
            raise StudyStateError("study evidence exists without validation")
        return _SemanticStudyEvidence(None, (), None, ())
    validation_document = validation.document
    _verify_common_identity(
        protocol,
        validation_document,
        execution_commit=cast(str, validation_document.get("execution_commit")),
        validation=validation,
    )
    if _plain_json(validation_document.get("upstream_artifacts")) != []:
        raise StudyStateError("implementation validation has upstream artifacts")
    execution_commit = cast(str, validation_document["execution_commit"])

    retention = verified.get("retention-audit.json")
    if retention is not None:
        _verify_common_identity(
            protocol,
            retention.document,
            execution_commit=execution_commit,
            validation=validation,
        )
        _verify_upstream_records(
            retention.document,
            ("implementation-validation.json",),
            verified,
        )

    eligible: tuple[ResamplingMode, ...] = ()
    phase1_claim = verified.get("phase-1-execution-claim.json")
    diagnostic = verified.get("known-transform-diagnostic-108.json")
    if phase1_claim is not None:
        expected_claim = begin_phase_execution(
            phase="phase1",
            protocol=protocol,
            execution_commit=execution_commit,
            eligible_modes=(),
        )
        if phase1_claim.raw_bytes != _canonical_json_bytes(
            finalize_study_record(expected_claim.as_record())
        ):
            raise StudyStateError("Phase 1 claim is not the expected control record")
    if diagnostic is not None:
        _verify_result_identity(
            protocol,
            diagnostic,
            validation=validation,
            execution_commit=execution_commit,
        )
        _verify_upstream_records(
            diagnostic.document,
            ("retention-audit.json", "phase-1-execution-claim.json"),
            verified,
        )
        eligible = _verify_diagnostic_payload(protocol, diagnostic.document)

    scope = verified.get("scope-audit.json")
    if scope is not None:
        _verify_result_identity(
            protocol,
            scope,
            validation=validation,
            execution_commit=execution_commit,
        )
        _verify_upstream_records(
            scope.document,
            ("retention-audit.json", "known-transform-diagnostic-108.json"),
            verified,
        )
        _verify_scope_payload(scope.document)

    oracle_passed: bool | None = None
    oracle = verified.get("feature-ownership-oracle.json")
    if oracle is not None:
        _verify_result_identity(
            protocol,
            oracle,
            validation=validation,
            execution_commit=execution_commit,
        )
        _verify_upstream_records(
            oracle.document,
            ("scope-audit.json", "known-transform-diagnostic-108.json"),
            verified,
        )
        if scope is None:
            raise StudyStateError("oracle lacks its scope")
        oracle_passed = _verify_oracle_payload(protocol, scope.document, oracle.document)

    phase2_claim = verified.get("phase-2-execution-claim.json")
    development = verified.get("known-transform-development-120.json")
    if phase2_claim is not None:
        expected_claim = begin_phase_execution(
            phase="phase2",
            protocol=protocol,
            execution_commit=execution_commit,
            eligible_modes=tuple(mode.value for mode in eligible),
        )
        if phase2_claim.raw_bytes != _canonical_json_bytes(
            finalize_study_record(expected_claim.as_record())
        ):
            raise StudyStateError("Phase 2 claim is not the expected control record")
    passing: tuple[ResamplingMode, ...] = ()
    if development is not None:
        _verify_result_identity(
            protocol,
            development,
            validation=validation,
            execution_commit=execution_commit,
        )
        _verify_upstream_records(
            development.document,
            (
                "retention-audit.json",
                "known-transform-diagnostic-108.json",
                "scope-audit.json",
                "feature-ownership-oracle.json",
                "phase-2-execution-claim.json",
            ),
            verified,
        )
        if scope is None:
            raise StudyStateError("development result lacks its scope")
        passing = _verify_development_payload(
            scope.document,
            development.document,
            eligible,
            protocol,
        )

    decision = verified.get("decision.json")
    if decision is not None:
        _verify_result_identity(
            protocol,
            decision,
            validation=validation,
            execution_commit=execution_commit,
        )
        payload = _record_mapping(decision.document, "payload")
        declared_paths = tuple(cast(list[str], _plain_json(payload.get("present_paths"))))
        expected_present = tuple(path for path in _PRE_DECISION_PATHS if path in present)
        if declared_paths != expected_present:
            raise StudyStateError("decision present-path inventory changed")
        verified_paths = tuple(
            path
            for path in declared_paths
            if path not in tuple(cast(list[str], _plain_json(payload.get("invalid_paths"))))
        )
        _verify_upstream_records(decision.document, verified_paths, verified)

    return _SemanticStudyEvidence(execution_commit, eligible, oracle_passed, passing)


def _verify_common_identity(
    protocol: StudyProtocolV2,
    document: Mapping[str, object],
    *,
    execution_commit: str,
    validation: VerifiedStudyJson,
) -> None:
    if (
        document.get("base_commit") != protocol.base_commit
        or document.get("execution_commit") != execution_commit
        or document.get("protocol_sha256") != protocol.configuration_sha256
        or document.get("artifact_root") != protocol.artifact_root_identity
    ):
        raise StudyStateError("study envelope identity changed")
    if document is not validation.document and (
        document.get("artifact_schema_sha256")
        != validation.document.get("artifact_schema_sha256")
        or document.get("implementation_projection_sha256")
        != validation.document.get("implementation_projection_sha256")
    ):
        raise StudyStateError("study envelope implementation hashes changed")


def _verify_result_identity(
    protocol: StudyProtocolV2,
    result: VerifiedStudyJson,
    *,
    validation: VerifiedStudyJson,
    execution_commit: str,
) -> None:
    _verify_common_identity(
        protocol,
        result.document,
        execution_commit=execution_commit,
        validation=validation,
    )


def _verify_upstream_records(
    document: Mapping[str, object],
    paths: tuple[str, ...],
    verified: Mapping[str, VerifiedStudyJson],
) -> None:
    expected: list[dict[str, str]] = []
    for path in paths:
        upstream = verified.get(path)
        if upstream is None:
            raise StudyStateError(f"artifact upstream is missing: {path}")
        expected.append(
            {
                "path": path,
                "raw_sha256": upstream.raw_sha256,
                "record_sha256": upstream.record_sha256,
            }
        )
    if _plain_json(document.get("upstream_artifacts")) != expected:
        raise StudyStateError("artifact upstream binding changed")


def _record_mapping(
    document: Mapping[str, object],
    field: str,
) -> Mapping[str, object]:
    value = document.get(field)
    if not isinstance(value, Mapping):
        raise StudyStateError(f"study record field is not an object: {field}")
    return cast(Mapping[str, object], value)


def _record_sequence(
    document: Mapping[str, object],
    field: str,
) -> tuple[object, ...]:
    value = document.get(field)
    if not isinstance(value, tuple):
        raise StudyStateError(f"study record field is not an array: {field}")
    return value


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _verify_diagnostic_payload(
    protocol: StudyProtocolV2,
    document: Mapping[str, object],
) -> tuple[ResamplingMode, ...]:
    payload = _record_mapping(document, "payload")
    cases = _record_sequence(payload, "cases")
    plans = load_frozen_diagnostic_matrix()
    if len(cases) != len(plans):
        raise StudyStateError("diagnostic cases are incomplete")
    for raw_case, plan in zip(cases, plans, strict=True):
        if not isinstance(raw_case, Mapping):
            raise StudyStateError("diagnostic case is not an object")
        case = cast(Mapping[str, object], raw_case)
        expected_transform = AppliedAffineTransform(
            1.0 + plan.scale_delta,
            plan.rotation_degrees,
            float(plan.translation_x),
            float(plan.translation_y),
        )
        if (
            case.get("diagnostic_id") != plan.diagnostic_id
            or case.get("seed") != plan.seed
            or case.get("cad_revision") != plan.cad_revision.value
            or case.get("view_id") != plan.view_id.value
            or case.get("defect_type") != plan.defect_type
            or case.get("defect_severity") != plan.defect_severity
            or case.get("expected_feature_id") != plan.expected_feature_id
            or _plain_json(case.get("applied_transform"))
            != _applied_transform_record(expected_transform)
        ):
            raise StudyStateError("diagnostic case does not match the frozen matrix")

    rows_by_mode: dict[ResamplingMode, list[DiagnosticObservation]] = {
        mode: [] for mode in ResamplingMode
    }
    observations = _record_sequence(payload, "observations")
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise StudyStateError("diagnostic observation is not an object")
        row = cast(Mapping[str, object], raw)
        mode = ResamplingMode(cast(str, row["mode"]))
        inference = _record_mapping(row, "inference_trace")
        _validate_stored_feature_mapping(_record_mapping(inference, "feature_mapping"))
        verify_inference_trace_consistency(
            context="diagnostic",
            mode=mode.value,
            inference_trace=inference,
            actual_outcome=cast(str, row["actual_outcome"]),
            total_residual=cast(int, row["total_residual"]),
        )
        rows_by_mode[mode].append(
            DiagnosticObservation(
                diagnostic_id=cast(str, row["diagnostic_id"]),
                seed=cast(int, row["seed"]),
                mode=mode,
                defect_row=cast(bool, row["defect_row"]),
                medium_high_row=cast(bool, row["medium_high_row"]),
                actual_outcome=cast(str, row["actual_outcome"]),
                identity_recall=cast(float, row["identity_recall"]),
                study_recall=cast(float, row["study_recall"]),
                identity_dice=cast(float, row["identity_dice"]),
                study_dice=cast(float, row["study_dice"]),
                study_iou=cast(float, row["study_iou"]),
                total_residual=cast(int, row["total_residual"]),
                boundary_residual=cast(int, row["boundary_residual"]),
                outside_boundary_residual=cast(int, row["outside_boundary_residual"]),
                record=row,
            )
        )
    summaries = _record_sequence(payload, "mode_summaries")
    reduced = tuple(
        reduce_diagnostic_mode(mode, rows_by_mode[mode], protocol.diagnostic_gates)
        for mode in ResamplingMode
    )
    expected_summaries = [_diagnostic_summary_record(summary) for summary in reduced]
    if _plain_json(summaries) != expected_summaries:
        raise StudyStateError("diagnostic summaries do not match row reduction")
    eligible = tuple(summary.mode for summary in reduced if summary.eligible)
    if _plain_json(payload.get("eligible_modes")) != [mode.value for mode in eligible]:
        raise StudyStateError("diagnostic eligible modes do not match row reduction")
    return eligible


def _verify_scope_payload(document: Mapping[str, object]) -> None:
    payload = _record_mapping(document, "payload")
    bindings = _record_sequence(payload, "bindings")
    expected = tuple(
        (f"e1-v2-development-{group}-{ordinal:03d}", start + ordinal, group)
        for group, count, start in (
            ("clean", 24, 400000),
            ("nuisance", 30, 410000),
            ("defect", 60, 420000),
            ("trust_boundary", 6, 430000),
        )
        for ordinal in range(count)
    )
    actual = tuple(
        (
            cast(Mapping[str, object], binding).get("case_id"),
            cast(Mapping[str, object], binding).get("seed"),
            cast(Mapping[str, object], binding).get("group"),
        )
        for binding in bindings
        if isinstance(binding, Mapping)
    )
    if actual != expected:
        raise StudyStateError("scope bindings do not match the frozen development corpus")
    case_binding_hashes: list[str] = []
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise StudyStateError("scope binding is not an object")
        case_binding_sha256 = binding.get("case_binding_sha256")
        if not isinstance(case_binding_sha256, str):
            raise StudyStateError("scope case binding hash is invalid")
        case_binding_hashes.append(case_binding_sha256)
    if len(set(case_binding_hashes)) != len(case_binding_hashes):
        raise StudyStateError("scope case binding hashes are not unique")


def _verify_oracle_payload(
    protocol: StudyProtocolV2,
    scope_document: Mapping[str, object],
    oracle_document: Mapping[str, object],
) -> bool:
    scope = _record_mapping(scope_document, "payload")
    bindings = _record_sequence(scope, "bindings")
    defect_bindings = bindings[54:114]
    payload = _record_mapping(oracle_document, "payload")
    if _plain_json(payload.get("ownership_hashes")) != dict(
        protocol.ownership_map_hashes
    ):
        raise StudyStateError("oracle ownership hashes changed")
    records = _record_sequence(payload, "records")
    layouts = _frozen_oracle_layout_projection()
    for binding, record, layout in zip(defect_bindings, records, layouts, strict=True):
        if not isinstance(binding, Mapping) or not isinstance(record, Mapping):
            raise StudyStateError("oracle binding is not an object")
        case_id, seed, cad_revision, view_id = layout
        if (
            record.get("case_id") != case_id
            or record.get("seed") != seed
            or binding.get("case_id") != case_id
            or binding.get("seed") != seed
            or record.get("authoritative_mask_sha256")
            != binding.get("authoritative_mask_sha256")
            or record.get("cad_revision") != cad_revision
            or record.get("view_id") != view_id
        ):
            raise StudyStateError("oracle row is not bound to its scope member")
        expected_hash = protocol.ownership_map_hashes.get(f"{cad_revision}/{view_id}")
        hash_binding_matches = (
            isinstance(expected_hash, str)
            and record.get("ownership_map_sha256") == expected_hash
        )
        if (
            record.get("hash_binding_matches") is not hash_binding_matches
            or not hash_binding_matches
        ):
            raise StudyStateError("oracle ownership hash is not bound to its frozen layout")
    return cast(bool, payload["passed"])


def _validate_stored_feature_mapping(record: Mapping[str, object]) -> None:
    margin = record.get("winner_margin")
    reconstructed = FeatureMappingResult(
        predicted_feature_id=cast(str | None, record.get("predicted_feature_id")),
        status=cast(str, record["status"]),
        reason=cast(str, record["reason"]),
        owner_pixel_counts=cast(
            Mapping[str, int], _record_mapping(record, "owner_pixel_counts")
        ),
        owned_pixel_count=cast(int, record["owned_pixel_count"]),
        winner_owned_pixel_count=cast(int, record["winner_owned_pixel_count"]),
        final_positive_pixel_count=cast(int, record["final_positive_pixel_count"]),
        unmapped_pixel_count=cast(int, record["unmapped_pixel_count"]),
        winner_margin=None if margin is None else float(cast(str, margin)),
        final_mask_sha256=cast(str, record["final_mask_sha256"]),
        ownership_map_sha256=cast(str, record["ownership_map_sha256"]),
    )
    if reconstructed.as_record() != _plain_json(record):
        raise StudyStateError("stored feature mapping does not round-trip")


def _verify_development_payload(
    scope_document: Mapping[str, object],
    development_document: Mapping[str, object],
    eligible: tuple[ResamplingMode, ...],
    protocol: StudyProtocolV2,
) -> tuple[ResamplingMode, ...]:
    scope_payload = _record_mapping(scope_document, "payload")
    payload = _record_mapping(development_document, "payload")
    if _plain_json(payload.get("bindings")) != _plain_json(scope_payload.get("bindings")):
        raise StudyStateError("development bindings differ from verified scope")
    if _plain_json(payload.get("eligible_modes")) != [mode.value for mode in eligible]:
        raise StudyStateError("development eligible modes differ from diagnostic")
    observations_by_mode: dict[ResamplingMode, list[E1V2EvaluationObservation]] = {
        mode: [] for mode in eligible
    }
    records = _record_sequence(payload, "inference_records")
    for raw in records:
        if not isinstance(raw, Mapping):
            raise StudyStateError("development inference row is not an object")
        record = cast(Mapping[str, object], raw)
        mode = ResamplingMode(cast(str, record["mode"]))
        if mode not in observations_by_mode:
            raise StudyStateError("development inference mode is unauthorized")
        inference = _record_mapping(record, "inference_trace")
        _validate_stored_feature_mapping(_record_mapping(inference, "feature_mapping"))
        metrics = _record_mapping(record, "metrics")
        verify_inference_trace_consistency(
            context="development",
            mode=mode.value,
            inference_trace=inference,
            actual_outcome=cast(Outcome, metrics["actual_outcome"]),
            anomaly_score=cast(float, metrics["anomaly_score"]),
            predicted_positive_pixels=cast(int, metrics["predicted_positive_pixels"]),
            predicted_feature_id=metrics.get("predicted_feature_id"),
        )
        observations_by_mode[mode].append(
            E1V2EvaluationObservation(
                case_id=cast(str, record["case_id"]),
                scope="development",
                group=cast(str, record["group"]),
                expected_outcome=cast(Outcome, metrics["expected_outcome"]),
                actual_outcome=cast(Outcome, metrics["actual_outcome"]),
                anomaly_score=cast(float, metrics["anomaly_score"]),
                defect_type=cast(str | None, metrics.get("defect_type")),
                severity=cast(str | None, metrics.get("severity")),
                nuisance_types=tuple(cast(list[str], _plain_json(metrics["nuisance_types"]))),
                cad_revision=cast(str, metrics["cad_revision"]),
                view_id=cast(str, metrics["view_id"]),
                truth_positive_pixels=cast(int, metrics["truth_positive_pixels"]),
                predicted_positive_pixels=cast(
                    int, metrics["predicted_positive_pixels"]
                ),
                intersection_pixels=cast(int, metrics["intersection_pixels"]),
                total_pixels=cast(int, metrics["total_pixels"]),
                expected_feature_id=cast(
                    str | None, metrics.get("expected_feature_id")
                ),
                predicted_feature_id=cast(
                    str | None, metrics.get("predicted_feature_id")
                ),
            )
        )
    reduced = tuple(
        reduce_development_mode(
            mode,
            observations_by_mode[mode],
            protocol.development_gates,
        )
        for mode in eligible
    )
    if _plain_json(payload.get("mode_summaries")) != [
        _development_summary_record(summary) for summary in reduced
    ]:
        raise StudyStateError("development summaries do not match row reduction")
    passing = tuple(summary.mode for summary in reduced if summary.passed_all_gates)
    if _plain_json(payload.get("passing_modes")) != [mode.value for mode in passing]:
        raise StudyStateError("development passing modes do not match row reduction")
    return passing


def _decision_matches_state(
    verified: Mapping[str, VerifiedStudyJson],
    decision: TerminalDecision,
    present_paths: tuple[str, ...],
    invalid_paths: tuple[str, ...],
) -> bool:
    evidence = verified.get("decision.json")
    if evidence is None or decision == "PENDING":
        return False
    if decision != "STUDY_INVALID" and invalid_paths:
        return False
    verified_paths = tuple(
        path
        for path in present_paths
        if path not in invalid_paths and path in verified
    )
    rate = len(verified_paths) / len(present_paths) if present_paths else 0.0
    payload = _record_mapping(evidence.document, "payload")
    expected = {
        "decision": decision,
        "allowed_next_action": _ALLOWED_NEXT_ACTIONS[decision],
        "reasons": [_DECISION_REASONS[decision]],
        "verified_artifact_count": len(verified_paths),
        "present_artifact_count": len(present_paths),
        "study_artifact_verify_rate": rate,
        "present_paths": list(present_paths),
        "invalid_paths": list(invalid_paths),
    }
    return _plain_json(payload) == expected


def _verify_invalid_terminal_projection(
    protocol: StudyProtocolV2,
    store: StudyArtifactStore,
    state: VerifiedStudyState,
    present_set: set[str],
) -> VerifiedStudyState:
    """Verify an optional invalid decision/report without trusting failed evidence."""

    decision = state.verified_json.get("decision.json")
    if decision is None:
        return state
    present_paths = tuple(path for path in _PRE_DECISION_PATHS if path in present_set)
    invalid_paths = tuple(path for path in present_paths if path in state.invalid_paths)
    decision_valid = False
    validation = state.verified_json.get("implementation-validation.json")
    if validation is not None:
        execution_commit = validation.document.get("execution_commit")
        if isinstance(execution_commit, str):
            try:
                _verify_result_identity(
                    protocol,
                    decision,
                    validation=validation,
                    execution_commit=execution_commit,
                )
                _verify_upstream_records(
                    decision.document,
                    tuple(
                        path
                        for path in present_paths
                        if path not in invalid_paths and path in state.verified_json
                    ),
                    state.verified_json,
                )
                decision_valid = _decision_matches_state(
                    state.verified_json,
                    "STUDY_INVALID",
                    present_paths,
                    invalid_paths,
                )
            except (StudyArtifactError, StudyStateError, TypeError, ValueError, KeyError):
                decision_valid = False

    projection_invalid = list(state.invalid_paths)
    if not decision_valid:
        projection_invalid.append("decision.json")
    if "report.md" in present_set:
        report_valid = False
        if decision_valid:
            try:
                report_valid = store.read_bytes("report.md") == _decision_report(
                    decision.document
                )
            except StudyArtifactError:
                report_valid = False
        if not report_valid:
            projection_invalid.append("report.md")
    return _invalid_state(
        state.status.reasons,
        present_paths=state.present_paths,
        invalid_paths=tuple(dict.fromkeys(projection_invalid)),
        verified_json=state.verified_json,
    )


def _decision_document(
    protocol: StudyProtocolV2,
    state: VerifiedStudyState,
    decision: TerminalDecision,
) -> dict[str, object]:
    if decision == "PENDING":
        raise StudyStateError("PENDING is not a terminal decision")
    present_paths = tuple(path for path in _PRE_DECISION_PATHS if path in state.present_paths)
    invalid_paths = tuple(path for path in present_paths if path in state.invalid_paths)
    verified_paths = tuple(
        path
        for path in present_paths
        if path not in invalid_paths and path in state.verified_json
    )
    if decision != "STUDY_INVALID" and (
        invalid_paths or len(verified_paths) != len(present_paths)
    ):
        raise StudyStateError("performance decision requires fully verified evidence")
    rate = len(verified_paths) / len(present_paths) if present_paths else 0.0
    return _result_envelope(
        protocol,
        state,
        record_type="decision",
        execution_commit=_state_execution_commit(state),
        upstream_paths=verified_paths,
        payload={
            "decision": decision,
            "allowed_next_action": _ALLOWED_NEXT_ACTIONS[decision],
            "reasons": [_DECISION_REASONS[decision]],
            "verified_artifact_count": len(verified_paths),
            "present_artifact_count": len(present_paths),
            "study_artifact_verify_rate": rate,
            "present_paths": list(present_paths),
            "invalid_paths": list(invalid_paths),
        },
    )


def _decision_report(document: Mapping[str, object]) -> bytes:
    payload = _record_mapping(document, "payload")
    decision = cast(str, payload["decision"])
    action = cast(str, payload["allowed_next_action"])
    reasons = cast(list[str], _plain_json(payload["reasons"]))
    verified_count = cast(int, payload["verified_artifact_count"])
    present_count = cast(int, payload["present_artifact_count"])
    rate = cast(float, payload["study_artifact_verify_rate"])
    invalid = cast(list[str], _plain_json(payload["invalid_paths"]))
    lines = (
        "# E1 feasibility study result",
        "",
        (
            "Development-only evidence. This record is not a release claim and is "
            "not selection-eligible."
        ),
        "",
        f"Decision: {decision}",
        f"Allowed next action: {action}",
        f"Reasons: {', '.join(reasons)}",
        (
            f"Verified artifacts: {verified_count}/{present_count} "
            f"({json.dumps(rate, allow_nan=False)})"
        ),
        f"Invalid artifacts: {', '.join(invalid) if invalid else 'none'}",
        "",
    )
    return "\n".join(lines).encode("utf-8")


def _invalid_state(
    reasons: tuple[str, ...],
    *,
    present_paths: tuple[str, ...] = (),
    invalid_paths: tuple[str, ...] = (),
    verified_json: Mapping[str, VerifiedStudyJson] | None = None,
) -> VerifiedStudyState:
    status = StudyStatus(
        study_valid=False,
        phase1_complete=False,
        feature_oracle_complete=False,
        phase2_authorized=False,
        phase2_complete=False,
        terminal_decision="STUDY_INVALID",
        reasons=reasons,
    )
    closed_invalid_paths = _closed_invalid_paths(present_paths, invalid_paths)
    return VerifiedStudyState(
        status=status,
        present_paths=present_paths,
        invalid_paths=closed_invalid_paths,
        verified_json=MappingProxyType(dict(verified_json or {})),
    )


def _closed_invalid_paths(
    present_paths: tuple[str, ...],
    invalid_paths: tuple[str, ...],
) -> tuple[str, ...]:
    present = set(present_paths)
    invalid = set(invalid_paths)
    changed = True
    while changed:
        changed = False
        for dependent, requirements in _ARTIFACT_VERIFICATION_DEPENDENCIES.items():
            if dependent not in present or dependent in invalid:
                continue
            if any(
                requirement not in present or requirement in invalid
                for requirement in requirements
            ):
                invalid.add(dependent)
                changed = True
    return tuple(path for path in present_paths if path in invalid)


def run_small_fixture_determinism_control(
    *,
    normalize: NormalizeCallback = normalize_known_transform,
) -> DeterminismControl:
    """Run the fixed asymmetric fixture through independent PIL and NumPy paths."""

    background = (17, 23, 31)
    boxes = (
        ((52, 44, 178, 162), (231, 37, 19)),
        ((246, 89, 314, 138), (29, 211, 83)),
        ((355, 217, 412, 296), (61, 97, 239)),
        ((192, 257, 287, 329), (241, 197, 41)),
    )
    pillow_image = Image.new("RGB", (512, 384), background)
    for bounds, color in boxes:
        pillow_image.paste(color, bounds)
    first_payload = encode_png(pillow_image, mode="RGB")

    pixels = np.full((384, 512, 3), background, dtype=np.uint8)
    for (x0, y0, x1, y1), color in boxes:
        pixels[y0:y1, x0:x1] = color
    second_payload = encode_png(Image.fromarray(pixels, mode="RGB"), mode="RGB")
    if first_payload != second_payload:
        raise StudyStateError("determinism fixture construction bytes differ")

    applied = AppliedAffineTransform(1.08, 7.5, 9.0, -4.0)

    def project(payload: bytes) -> dict[str, str]:
        source_hash = sha256(payload).hexdigest()
        projection: dict[str, str] = {}
        for mode in ResamplingMode:
            result = normalize(
                payload,
                payload,
                reference_sha256=source_hash,
                inspection_sha256=source_hash,
                applied_transform=applied,
                resampling=mode,
            )
            normalized_bytes = getattr(result, "normalized_bytes", None)
            normalized_sha256 = getattr(result, "normalized_sha256", None)
            trace = getattr(result, "trace", None)
            if not isinstance(normalized_bytes, bytes) or not isinstance(
                normalized_sha256, str
            ):
                raise StudyStateError("determinism normalizer returned invalid output")
            if (
                sha256(normalized_bytes).hexdigest() != normalized_sha256
                or getattr(trace, "normalized_sha256", None) != normalized_sha256
            ):
                raise StudyStateError("determinism normalized hash binding failed")
            projection[mode.value] = normalized_sha256
        return projection

    first_projection = project(first_payload)
    second_projection = project(second_payload)
    if first_projection != second_projection:
        raise StudyStateError("determinism mode projections differ")
    return DeterminismControl(first_projection, second_projection, True)


def _default_executable_resolver(name: str, search_path: str | None) -> Path:
    if search_path is None:
        raise StudyStateError("required executable lookup path is not sealed")
    resolved = shutil.which(name, path=search_path)
    if resolved is None:
        raise StudyStateError(f"required executable is unavailable: {name}")
    return Path(resolved)


def _execute_validation_command(
    request: ValidationCommandRequest,
) -> ValidationCommandResult:
    """Execute one fixed validation request with bounded concurrent output draining."""

    executable = request.executable_lookup_path
    argv = (os.fspath(executable), *request.argv[1:])
    started = datetime.now(UTC)
    try:
        process = subprocess.Popen(
            argv,
            cwd=request.cwd,
            env=dict(request.environment),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise StudyStateError(f"validation command could not start: {request.name}") from exc
    stdout, stderr = _drain_validation_process(
        process,
        timeout_seconds=request.timeout_seconds,
        output_limit_bytes=request.output_limit_bytes,
    )
    return ValidationCommandResult(
        exit_code=cast(int, process.returncode),
        stdout=stdout,
        stderr=stderr,
        started_at_utc=started,
        ended_at_utc=datetime.now(UTC),
    )


def _drain_validation_process(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: int,
    output_limit_bytes: int,
) -> tuple[bytes, bytes]:
    if process.stdout is None or process.stderr is None:
        _kill_process_group(process)
        raise StudyStateError("validation command pipes were not created")
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    streams = {stdout_fd: process.stdout, stderr_fd: process.stderr}
    buffers = {stdout_fd: bytearray(), stderr_fd: bytearray()}
    overflowed: set[int] = set()
    selector = selectors.DefaultSelector()
    for descriptor in streams:
        os.set_blocking(descriptor, False)
        selector.register(descriptor, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
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
                    selector.unregister(key.fileobj)
                    streams[descriptor].close()
                    continue
                if descriptor not in overflowed:
                    buffers[descriptor].extend(chunk)
                    if len(buffers[descriptor]) > output_limit_bytes:
                        overflowed.add(descriptor)
                        _kill_process_group(process)
        process.wait(timeout=1)
    except (OSError, subprocess.SubprocessError) as exc:
        _kill_process_group(process)
        process.wait()
        raise StudyStateError("validation command output could not be drained") from exc
    finally:
        selector.close()
    if timed_out:
        raise StudyStateError("validation command timed out")
    if overflowed:
        raise StudyStateError("validation command output exceeded the byte limit")
    return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd])


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


class StudyRunner:
    """Protocol-fixed runner; read-only methods never create the artifact root."""

    def __init__(
        self,
        protocol: StudyProtocolV2,
        *,
        repo_root: Path = PROJECT_ROOT,
        store: StudyArtifactStore | None = None,
        command_runner: CommandRunner = _execute_validation_command,
        executable_resolver: ExecutableResolver = _default_executable_resolver,
        repository_state: RepositoryStateReader | None = None,
        normalize: NormalizeCallback = normalize_known_transform,
        diagnostic_matrix: DiagnosticMatrixLoader = load_frozen_diagnostic_matrix,
        render: DiagnosticRenderer = render_diagnostic,
        corpus: CorpusLoader | None = None,
        oracle: OracleRunner = run_feature_ownership_oracle,
        inference: InferenceRunner | None = None,
        e1_protocol_loader: Callable[[], E1V2Protocol] = load_e1_v2_protocol,
        home_directory: Path | None = None,
        temp_directory: Path | None = None,
    ) -> None:
        self.protocol = protocol
        self.repo_root = Path(os.path.abspath(os.fspath(repo_root.expanduser())))
        self._store = store
        self._command_runner = command_runner
        self._executable_resolver = executable_resolver
        self._repository_state = repository_state or self._capture_repository_state
        self._normalize = normalize
        self._diagnostic_matrix = diagnostic_matrix
        self._render = render
        self._corpus = corpus
        self._oracle = oracle
        self._inference = inference
        self._e1_protocol_loader = e1_protocol_loader
        self._home_directory = _absolute_lexical(home_directory or Path.home())
        self._temp_directory = _absolute_lexical(
            temp_directory or Path(tempfile.gettempdir())
        )

    @classmethod
    def from_default(cls) -> StudyRunner:
        return cls(load_study_protocol_v2())

    def status(self) -> StudyStatus:
        return self._public_state().status

    def verify(self) -> StudyVerificationReport:
        state = self._public_state()
        present = state.present_paths
        verified = state.verified_paths
        rate = len(verified) / len(present) if present else 0.0
        return StudyVerificationReport(verified, rate, state.status)

    def _public_state(self) -> VerifiedStudyState:
        state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        if "implementation-validation.json" not in state.verified_json:
            if not state.present_paths:
                return state
            return _invalid_state(
                state.status.reasons or ("ARTIFACT_VERIFICATION_FAILED",),
                present_paths=state.present_paths,
                invalid_paths=state.present_paths,
                verified_json=state.verified_json,
            )
        try:
            self._verify_trusted_evidence(state)
            return state
        except StudyRetentionError as exc:
            del exc
            return _invalid_state(
                ("ARTIFACT_VERIFICATION_FAILED",),
                present_paths=state.present_paths,
                invalid_paths=state.present_paths,
            )
        except (
            StudyArtifactError,
            StudyStateError,
            TypeError,
            ValueError,
            KeyError,
        ):
            return _invalid_state(
                ("ARTIFACT_VERIFICATION_FAILED",),
                present_paths=state.present_paths,
                invalid_paths=state.present_paths,
            )

    def finalize(self) -> StudyArtifactRecord:
        """Publish one terminal decision, then its deterministic human projection."""

        state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        decision = state.status.terminal_decision
        if decision == "PENDING":
            raise StudyStateError("PENDING study evidence cannot be finalized")
        self._require_finalization_evidence(state)

        existing = state.verified_json.get("decision.json")
        if existing is not None:
            if "decision.json" in state.invalid_paths:
                raise StudyStateError("existing terminal decision is invalid")
            if "report.md" in state.present_paths and "report.md" in state.invalid_paths:
                raise StudyStateError("existing terminal report is invalid")
            if "report.md" not in state.present_paths:
                store, owned = self._write_store()
                try:
                    store.verify_lexical_root_identity()
                    store.publish_bytes(
                        "report.md",
                        _decision_report(existing.document),
                        media_type="text/markdown; charset=utf-8",
                    )
                    completed = inspect_state(
                        self.protocol,
                        repo_root=self.repo_root,
                        store=store,
                    )
                    if (
                        completed.status.terminal_decision != decision
                        or "decision.json" in completed.invalid_paths
                        or "report.md" in completed.invalid_paths
                    ):
                        raise StudyStateError("published decision report failed verification")
                finally:
                    if owned:
                        store.close()
            return StudyArtifactRecord(
                "decision.json",
                existing.raw_sha256,
                len(existing.raw_bytes),
                "application/json",
                existing.record_sha256,
            )

        baseline = self._require_finalization_preflight(state)
        document = _decision_document(self.protocol, state, decision)
        store, owned = self._write_store()
        try:
            store.verify_lexical_root_identity()
            published = store.publish_json("decision.json", document)
            verified_decision = store.verify_json_result(
                "decision.json",
                expected_record_type="decision",
            )
            post_decision = inspect_state(
                self.protocol,
                repo_root=self.repo_root,
                store=store,
            )
            if (
                post_decision.status.terminal_decision != decision
                or "decision.json" in post_decision.invalid_paths
                or (
                    decision != "STUDY_INVALID"
                    and not post_decision.status.study_valid
                )
            ):
                raise StudyStateError("published terminal decision failed verification")
            store.publish_bytes(
                "report.md",
                _decision_report(verified_decision.document),
                media_type="text/markdown; charset=utf-8",
            )
            completed = inspect_state(
                self.protocol,
                repo_root=self.repo_root,
                store=store,
            )
            if (
                completed.status.terminal_decision != decision
                or "decision.json" in completed.invalid_paths
                or "report.md" in completed.invalid_paths
                or (decision != "STUDY_INVALID" and not completed.status.study_valid)
            ):
                raise StudyStateError("published decision report failed verification")
            self._require_phase_publication_state(
                baseline,
                ("decision.json", "report.md"),
            )
            return published
        finally:
            if owned:
                store.close()

    def _verify_trusted_evidence(self, state: VerifiedStudyState) -> None:
        """Deeply verify the immutable evidence anchors and their Git lineage."""

        store, owned = self._read_store()
        try:
            store.verify_lexical_root_identity()
            validation = verify_implementation_validation(
                self.protocol,
                store,
                repo_root=self.repo_root,
            )
            evidence_commit: str | None = None
            if "retention-audit.json" in state.present_paths:
                retention = verify_retention_audit(
                    self.protocol,
                    store,
                    repo_root=self.repo_root,
                )
                evidence_commit = retention.evidence_commit
            _verify_git_lineage(
                self.protocol,
                repo_root=self.repo_root,
                execution_commit=validation.execution_commit,
                evidence_commit=evidence_commit,
                require_clean=False,
                allow_retained_input_copies=True,
            )
            store.verify_lexical_root_identity()
        finally:
            if owned:
                store.close()

    def _require_finalization_evidence(self, state: VerifiedStudyState) -> None:
        try:
            self._verify_trusted_evidence(state)
        except (
            StudyArtifactError,
            StudyRetentionError,
            StudyStateError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            raise StudyStateError(
                "study finalization evidence verification failed"
            ) from exc

    def validate_implementation(self) -> StudyArtifactRecord:
        """Run and publish the fixed implementation-validation transaction once."""

        existing = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        if not existing.status.study_valid:
            raise StudyStateError("existing study packet is invalid")
        if existing.present_paths:
            if existing.present_paths != ("implementation-validation.json",):
                raise StudyStateError("implementation validation packet has extraneous artifacts")
            evidence = existing.verified_json.get("implementation-validation.json")
            if evidence is None:
                raise StudyStateError("existing implementation validation is invalid")
            store, owned = self._read_store()
            try:
                verify_implementation_validation(
                    self.protocol,
                    store,
                    repo_root=self.repo_root,
                )
            except Exception as exc:
                raise StudyStateError("existing implementation validation is invalid") from exc
            finally:
                if owned:
                    store.close()
            return StudyArtifactRecord(
                path="implementation-validation.json",
                sha256=evidence.raw_sha256,
                byte_size=len(evidence.raw_bytes),
                media_type="application/json",
                record_sha256=evidence.record_sha256,
            )

        baseline = self._require_clean_snapshot(self._repository_state())
        try:
            _verify_pristine_artifact_history(
                self.protocol,
                repo_root=self.repo_root,
                current_commit=baseline.head,
            )
        except StudyRetentionError as exc:
            raise StudyStateError(
                f"implementation validation monotonic history is invalid: {exc}"
            ) from exc
        production_search_path = _production_executable_search_path()
        reviewed_roots = frozenset(production_search_path.split(":"))
        uv_path = _validated_lookup_path(
            self._executable_resolver("uv", production_search_path),
            expected_name="uv",
        )
        npm_path = _validated_lookup_path(
            self._executable_resolver("npm", production_search_path),
            expected_name="npm",
        )
        if any(
            path.parent.as_posix() not in reviewed_roots for path in (uv_path, npm_path)
        ):
            raise StudyStateError(
                "validation executable lookup path is outside a reviewed executable root"
            )
        environment = self._validation_environment(uv_path, npm_path)
        node_path = _validated_lookup_path(
            self._executable_resolver("node", environment["PATH"]),
            expected_name="node",
        )
        if node_path.parent.as_posix() not in environment["PATH"].split(":"):
            raise StudyStateError("node does not resolve through the sealed validation PATH")

        command_records: list[dict[str, object]] = []
        for ordinal, ((name, argv), timeout_seconds) in enumerate(
            zip(
                IMPLEMENTATION_VALIDATION_COMMANDS,
                IMPLEMENTATION_VALIDATION_TIMEOUT_SECONDS,
                strict=True,
            )
        ):
            if ordinal:
                self._require_unchanged_snapshot(self._repository_state(), baseline)
            lookup_path = uv_path if ordinal < 4 else npm_path
            request = ValidationCommandRequest(
                name=name,
                argv=argv,
                executable_lookup_path=lookup_path,
                cwd=self.repo_root,
                environment=environment,
                timeout_seconds=timeout_seconds,
                output_limit_bytes=_VALIDATION_OUTPUT_LIMIT_BYTES,
            )
            try:
                result = self._command_runner(request)
            except Exception as exc:
                raise StudyStateError(f"validation command failed: {name}") from exc
            command_records.append(_validation_command_record(request, result))
            self._require_unchanged_snapshot(self._repository_state(), baseline)

        determinism = run_small_fixture_determinism_control(normalize=self._normalize)
        self._require_unchanged_snapshot(self._repository_state(), baseline)
        projection_sha256 = _canonical_json_hash(
            [entry.as_record() for entry in baseline.projection]
        )
        schema_sha256 = _projection_hash(
            baseline.projection,
            "schemas/e1-feasibility-study-artifact.v1.json",
        )
        document: dict[str, object] = {
            "record_type": "implementation_validation",
            "schema_version": "1.0.0",
            "study_id": "e1-feasibility-separability",
            "development_only": True,
            "selection_eligible": False,
            "release_claim_allowed": False,
            "base_commit": self.protocol.base_commit,
            "execution_commit": baseline.head,
            "protocol_sha256": self.protocol.configuration_sha256,
            "artifact_root": self.protocol.artifact_root_identity,
            "artifact_schema_sha256": schema_sha256,
            "implementation_projection_sha256": projection_sha256,
            "upstream_artifacts": [],
            "payload": {
                "worktree_clean": True,
                "commands": command_records,
                "determinism_control": {
                    "first_projection": dict(determinism.first_projection),
                    "second_projection": dict(determinism.second_projection),
                    "passed": determinism.passed,
                },
                "not_applicable_controls": [
                    StudyGateRecord(
                        name=name,
                        status="NOT_APPLICABLE",
                        numerator=None,
                        denominator=None,
                        observed=None,
                        operator=None,
                        threshold=None,
                        reason=reason,
                    ).as_record()
                    for name, reason in NOT_APPLICABLE_CONTROLS
                ],
                "passed": True,
            },
        }
        self._require_unchanged_snapshot(self._repository_state(), baseline)
        store, owned = self._write_store()
        try:
            store.verify_lexical_root_identity()
            published = store.publish_json("implementation-validation.json", document)
            expected_dirty = (f"{self._artifact_relative_root()}/implementation-validation.json",)
            self._require_unchanged_snapshot(
                self._repository_state(),
                baseline,
                allowed_dirty=expected_dirty,
            )
            verify_implementation_validation(
                self.protocol,
                store,
                repo_root=self.repo_root,
            )
            return published
        except StudyArtifactError as exc:
            raise StudyStateError("implementation validation could not be published") from exc
        finally:
            if owned:
                store.close()

    def phase1(self) -> StudyArtifactRecord:
        """Execute the frozen known-transform diagnostic exactly once."""

        state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        expected = ("implementation-validation.json", "retention-audit.json")
        if not state.status.study_valid or state.present_paths != expected:
            raise StudyStateError("Phase 1 requires the pristine verified Phase 0 packet")
        baseline = self._require_mutating_preflight(state, expected_paths=expected)
        execution_commit = _state_execution_commit(state)
        store, owned = self._write_store()
        try:
            store.verify_lexical_root_identity()
            claim = begin_phase_execution(
                phase="phase1",
                protocol=self.protocol,
                execution_commit=execution_commit,
                eligible_modes=(),
            )
            store.publish_json("phase-1-execution-claim.json", claim.as_record())
            verified_claim = store.verify_json_result(
                "phase-1-execution-claim.json",
                expected_record_type="phase_execution_claim",
            )
            if verified_claim.raw_bytes != _canonical_json_bytes(
                finalize_study_record(claim.as_record())
            ):
                raise StudyStateError("published Phase 1 claim changed")
            store.verify_lexical_root_identity()
            self._require_phase_publication_state(
                baseline,
                ("phase-1-execution-claim.json",),
            )

            e1_protocol = self._e1_protocol_loader()
            inference = self._phase_inference(e1_protocol)
            plans = self._diagnostic_matrix()
            cases: list[StudyTruthCase] = []
            observations: list[DiagnosticObservation] = []
            observation_records: list[dict[str, object]] = []
            rows_by_mode: dict[ResamplingMode, list[DiagnosticObservation]] = {
                mode: [] for mode in ResamplingMode
            }
            for plan in plans:
                case = self._render(plan, self.protocol, e1_protocol)
                cases.append(case)
                identity_mask = raw_identity_difference_mask(case)
                boundary = reference_boundary_band(case.reference_bytes)
                for mode in ResamplingMode:
                    normalized = self._normalize(
                        case.reference_bytes,
                        case.inspection_bytes,
                        reference_sha256=case.reference_sha256,
                        inspection_sha256=case.inspection_sha256,
                        applied_transform=case.applied_transform,
                        resampling=mode,
                    )
                    result = inference(make_truth_free_input(case, normalized))
                    row = diagnostic_observation(
                        case,
                        result,
                        identity_mask,
                        boundary,
                    )
                    observations.append(row)
                    rows_by_mode[mode].append(row)
                    observation_records.append(
                        _diagnostic_observation_record(row, boundary)
                    )
            summaries = tuple(
                reduce_diagnostic_mode(
                    mode,
                    rows_by_mode[mode],
                    self.protocol.diagnostic_gates,
                )
                for mode in ResamplingMode
            )
            eligible = tuple(summary.mode.value for summary in summaries if summary.eligible)
            document = _result_envelope(
                self.protocol,
                state,
                record_type="diagnostic_result",
                execution_commit=execution_commit,
                upstream_paths=(
                    "retention-audit.json",
                    "phase-1-execution-claim.json",
                ),
                extra_upstreams={
                    "phase-1-execution-claim.json": verified_claim,
                },
                payload={
                    "runtime_versions": _runtime_versions(),
                    "row_count": len(cases),
                    "observation_count": len(observations),
                    "cases": [_diagnostic_case_record(case) for case in cases],
                    "observations": observation_records,
                    "mode_summaries": [
                        _diagnostic_summary_record(summary) for summary in summaries
                    ],
                    "eligible_modes": list(eligible),
                },
            )
            published = store.publish_json(
                "known-transform-diagnostic-108.json",
                document,
            )
            self._require_completed_phase("phase1", store)
            self._require_phase_publication_state(
                baseline,
                (
                    "phase-1-execution-claim.json",
                    "known-transform-diagnostic-108.json",
                ),
            )
            return published
        finally:
            if owned:
                store.close()

    def phase0(self) -> StudyArtifactRecord:
        """Delegate the immutable retention transaction to the Task 6 implementation."""

        state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        expected = ("implementation-validation.json",)
        if not state.status.study_valid or state.present_paths != expected:
            raise StudyStateError("Phase 0 requires only verified implementation validation")
        baseline = self._require_mutating_preflight(state, expected_paths=expected)
        store, owned = self._write_store()
        try:
            store.verify_lexical_root_identity()
            validation = verify_implementation_validation(
                self.protocol,
                store,
                repo_root=self.repo_root,
            )
            audit = run_retention_audit(
                self.protocol,
                store,
                execution_commit=validation.execution_commit,
                repo_root=self.repo_root,
            )
            verified = verify_retention_audit(
                self.protocol,
                store,
                repo_root=self.repo_root,
            )
            if verified.as_record() != audit.as_record():
                raise StudyStateError("published retention audit changed")
            self._require_phase_publication_state(
                baseline,
                (*_RETAINED_FILES, "retention-audit.json"),
            )
            result = store.verify_json_result(
                "retention-audit.json",
                expected_record_type="retention_audit",
            )
            return StudyArtifactRecord(
                "retention-audit.json",
                result.raw_sha256,
                len(result.raw_bytes),
                "application/json",
                result.record_sha256,
            )
        except StudyStateError:
            raise
        except Exception as exc:
            raise StudyStateError("Phase 0 retention transaction failed") from exc
        finally:
            if owned:
                store.close()

    def feature_oracle(self) -> StudyArtifactRecord:
        """Publish the exact development scope and truth-only ownership oracle."""

        state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        expected = _PRE_DECISION_PATHS[:4]
        if (
            not state.status.study_valid
            or not state.status.phase1_complete
            or state.present_paths != expected
        ):
            raise StudyStateError("feature oracle requires complete verified Phase 1")
        baseline = self._require_mutating_preflight(state, expected_paths=expected)
        execution_commit = _state_execution_commit(state)
        e1_protocol = self._e1_protocol_loader()
        corpus = self._load_corpus(e1_protocol)
        bindings = _development_bindings(corpus)
        scope_document = _result_envelope(
            self.protocol,
            state,
            record_type="scope_audit",
            execution_commit=execution_commit,
            upstream_paths=(
                "retention-audit.json",
                "known-transform-diagnostic-108.json",
            ),
            payload={
                "member_count": len(bindings),
                "bindings": bindings,
                "group_counts": dict(corpus.counts),
                "scope_projection": list(corpus.scope_projection),
                "external_request_count": corpus.external_request_count,
                "internal_membership_validation_count": (
                    corpus.internal_membership_validation_count
                ),
                "protected_emission_count": 0,
                "legacy_v1_planning_caveat": (
                    "LEGACY_V1_FULL_TEMPLATES_FILTERED_TO_V2_DEVELOPMENT_ONLY"
                ),
                "passed": True,
            },
        )
        store, owned = self._write_store()
        try:
            store.verify_lexical_root_identity()
            store.publish_json("scope-audit.json", scope_document)
            verified_scope = store.verify_json_result(
                "scope-audit.json",
                expected_record_type="scope_audit",
            )
            self._require_phase_publication_state(
                baseline,
                ("scope-audit.json",),
            )
            oracle = self._oracle(corpus, e1_protocol, self.protocol)
            records = _oracle_records(self.protocol, corpus, oracle)
            oracle_document = _result_envelope(
                self.protocol,
                state,
                record_type="feature_oracle",
                execution_commit=execution_commit,
                upstream_paths=(
                    "scope-audit.json",
                    "known-transform-diagnostic-108.json",
                ),
                extra_upstreams={"scope-audit.json": verified_scope},
                payload={
                    "case_count": oracle.case_count,
                    "correct_cases": oracle.correct_cases,
                    "ambiguous_cases": oracle.ambiguous_cases,
                    "null_cases": oracle.null_cases,
                    "wrong_cases": oracle.wrong_cases,
                    "minimum_winner_pixels": 8,
                    "ambiguity_margin": 0.1,
                    "ownership_hashes": dict(oracle.ownership_hashes),
                    "records": records,
                    "passed": oracle.passed,
                },
            )
            published = store.publish_json(
                "feature-ownership-oracle.json",
                oracle_document,
            )
            self._require_completed_phase("oracle", store)
            self._require_phase_publication_state(
                baseline,
                ("scope-audit.json", "feature-ownership-oracle.json"),
            )
            return published
        finally:
            if owned:
                store.close()

    def phase2(self) -> StudyArtifactRecord:
        """Execute the authorized development corpus once for every eligible mode."""

        state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        expected = _PRE_DECISION_PATHS[:6]
        eligible = _state_eligible_modes(state)
        if (
            not state.status.study_valid
            or not state.status.phase2_authorized
            or state.present_paths != expected
            or not eligible
        ):
            raise StudyStateError("Phase 2 is not authorized by verified evidence")
        baseline = self._require_mutating_preflight(state, expected_paths=expected)
        execution_commit = _state_execution_commit(state)
        scope_bindings = _scope_bindings(state)
        e1_protocol = self._e1_protocol_loader()
        corpus = self._load_corpus(e1_protocol)
        bindings = _development_bindings(corpus)
        if bindings != scope_bindings:
            raise StudyStateError("Phase 2 corpus does not match the verified scope")

        refreshed_state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=self._store,
        )
        refreshed_baseline = self._require_mutating_preflight(
            refreshed_state,
            expected_paths=expected,
        )
        refreshed_execution_commit = _state_execution_commit(refreshed_state)
        refreshed_eligible = _state_eligible_modes(refreshed_state)
        refreshed_scope_bindings = _scope_bindings(refreshed_state)
        if (
            not refreshed_state.status.phase2_authorized
            or refreshed_execution_commit != execution_commit
            or refreshed_eligible != eligible
            or refreshed_scope_bindings != scope_bindings
            or bindings != refreshed_scope_bindings
        ):
            raise StudyStateError("Phase 2 authorization evidence changed before claim")
        state = refreshed_state
        baseline = refreshed_baseline
        store, owned = self._write_store()
        try:
            store.verify_lexical_root_identity()
            claim = begin_phase_execution(
                phase="phase2",
                protocol=self.protocol,
                execution_commit=execution_commit,
                eligible_modes=tuple(mode.value for mode in eligible),
            )
            store.publish_json("phase-2-execution-claim.json", claim.as_record())
            verified_claim = store.verify_json_result(
                "phase-2-execution-claim.json",
                expected_record_type="phase_execution_claim",
            )
            if verified_claim.raw_bytes != _canonical_json_bytes(
                finalize_study_record(claim.as_record())
            ):
                raise StudyStateError("published Phase 2 claim changed")
            store.verify_lexical_root_identity()
            self._require_phase_publication_state(
                baseline,
                ("phase-2-execution-claim.json",),
            )
            inference = self._phase_inference(e1_protocol)
            applicable_cases = tuple(
                case for case in corpus.cases if not case.trust_boundary
            )
            trust_cases = tuple(case for case in corpus.cases if case.trust_boundary)
            inference_records: list[dict[str, object]] = []
            summaries: list[DevelopmentModeSummary] = []
            for mode in eligible:
                observations: list[E1V2EvaluationObservation] = []
                for case in applicable_cases:
                    normalized = self._normalize(
                        case.reference_bytes,
                        case.inspection_bytes,
                        reference_sha256=case.reference_sha256,
                        inspection_sha256=case.inspection_sha256,
                        applied_transform=case.applied_transform,
                        resampling=mode,
                    )
                    result = inference(make_truth_free_input(case, normalized))
                    observation = observation_from_study(case, result)
                    observations.append(observation)
                    inference_records.append(
                        _development_inference_record(case, mode, result, observation)
                    )
                summaries.append(
                    reduce_development_mode(
                        mode,
                        observations,
                        self.protocol.development_gates,
                    )
                )
            passing = tuple(
                summary.mode.value for summary in summaries if summary.passed_all_gates
            )
            document = _result_envelope(
                self.protocol,
                state,
                record_type="development_result",
                execution_commit=execution_commit,
                upstream_paths=(
                    "retention-audit.json",
                    "known-transform-diagnostic-108.json",
                    "scope-audit.json",
                    "feature-ownership-oracle.json",
                    "phase-2-execution-claim.json",
                ),
                extra_upstreams={"phase-2-execution-claim.json": verified_claim},
                payload={
                    "runtime_versions": _runtime_versions(),
                    "member_count": len(bindings),
                    "bindings": bindings,
                    "eligible_modes": [mode.value for mode in eligible],
                    "inference_records": inference_records,
                    "trust_bindings": [
                        _trust_binding_record(case) for case in trust_cases
                    ],
                    "mode_summaries": [
                        _development_summary_record(summary) for summary in summaries
                    ],
                    "passing_modes": list(passing),
                },
            )
            published = store.publish_json(
                "known-transform-development-120.json",
                document,
            )
            self._require_completed_phase("phase2", store)
            self._require_phase_publication_state(
                baseline,
                (
                    "phase-2-execution-claim.json",
                    "known-transform-development-120.json",
                ),
            )
            return published
        finally:
            if owned:
                store.close()

    def _phase_inference(self, e1_protocol: E1V2Protocol) -> InferenceRunner:
        if self._inference is not None:
            return self._inference
        adapter = StudyInferenceAdapter(self.protocol, e1_protocol)
        return adapter.inspect

    def _load_corpus(self, e1_protocol: E1V2Protocol) -> DevelopmentCorpus:
        if self._corpus is not None:
            return self._corpus()
        return DevelopmentCorpusProvider(e1_protocol).load()

    def _require_mutating_preflight(
        self,
        state: VerifiedStudyState,
        *,
        expected_paths: tuple[str, ...],
    ) -> RepositorySnapshot:
        if not state.status.study_valid or state.present_paths != expected_paths:
            raise StudyStateError("study phase prerequisites are incomplete")
        snapshot = self._require_clean_snapshot(self._repository_state())
        store, owned = self._read_store()
        try:
            store.verify_lexical_root_identity()
            validation = verify_implementation_validation(
                self.protocol,
                store,
                repo_root=self.repo_root,
            )
            if "retention-audit.json" in expected_paths:
                verify_retention_audit(
                    self.protocol,
                    store,
                    repo_root=self.repo_root,
                )
            evidence_commit = _verify_git_lineage(
                self.protocol,
                repo_root=self.repo_root,
                execution_commit=validation.execution_commit,
                evidence_commit=None,
                require_clean=True,
                allow_retained_input_copies=True,
            )
            if evidence_commit != snapshot.head:
                raise StudyStateError("study phase evidence HEAD changed")
            if _canonical_json_hash(
                [entry.as_record() for entry in snapshot.projection]
            ) != validation.implementation_projection_sha256:
                raise StudyStateError("study phase implementation projection changed")
            committed_paths = list(expected_paths)
            if "retention-audit.json" in expected_paths:
                committed_paths.extend(_RETAINED_FILES)
            root = self._artifact_relative_root()
            for path in committed_paths:
                if path in state.verified_json:
                    working_bytes = state.verified_json[path].raw_bytes
                else:
                    working_bytes = store.read_bytes(path)
                committed_bytes = _run_git_bytes(
                    self.repo_root,
                    "show",
                    f"HEAD:{root}/{path}",
                )
                if committed_bytes != working_bytes:
                    raise StudyStateError(
                        f"study prerequisite is not committed at HEAD: {path}"
                    )
            store.verify_lexical_root_identity()
        finally:
            if owned:
                store.close()
        if self._repository_state() != snapshot:
            raise StudyStateError("study phase HEAD changed during preflight")
        return snapshot

    def _require_finalization_preflight(
        self,
        state: VerifiedStudyState,
    ) -> RepositorySnapshot:
        if state.status.terminal_decision == "PENDING":
            raise StudyStateError("PENDING study evidence cannot be finalized")
        snapshot = self._require_clean_snapshot(self._repository_state())
        try:
            evidence_commit = _verify_git_lineage(
                self.protocol,
                repo_root=self.repo_root,
                execution_commit=_state_execution_commit(state),
                evidence_commit=None,
                require_clean=True,
                allow_retained_input_copies=True,
            )
        except StudyRetentionError as exc:
            raise StudyStateError(
                f"study finalization monotonic history is invalid: {exc}"
            ) from exc
        if evidence_commit != snapshot.head:
            raise StudyStateError("study finalization evidence HEAD changed")
        if snapshot.head != self._repository_state().head:
            raise StudyStateError("study finalization HEAD changed during preflight")
        return snapshot

    def _require_phase_publication_state(
        self,
        baseline: RepositorySnapshot,
        published_paths: tuple[str, ...],
    ) -> None:
        dirty = tuple(
            sorted(
                f"{self._artifact_relative_root()}/{path}" for path in published_paths
            )
        )
        self._require_unchanged_snapshot(
            self._repository_state(),
            baseline,
            allowed_dirty=dirty,
        )

    def _require_completed_phase(
        self,
        phase: Literal["phase1", "oracle", "phase2"],
        store: StudyArtifactStore,
    ) -> None:
        state = inspect_state(
            self.protocol,
            repo_root=self.repo_root,
            store=store,
        )
        if not state.status.study_valid:
            raise StudyStateError(f"published {phase} evidence failed semantic verification")
        complete = {
            "phase1": state.status.phase1_complete,
            "oracle": state.status.feature_oracle_complete,
            "phase2": state.status.phase2_complete,
        }[phase]
        if not complete:
            raise StudyStateError(f"published {phase} evidence is incomplete")

    def _capture_repository_state(self) -> RepositorySnapshot:
        return RepositorySnapshot(
            head=_run_git(self.repo_root, "rev-parse", "HEAD"),
            dirty_paths=_git_status_paths(self.repo_root),
            projection=build_study_implementation_projection(
                self.protocol,
                repo_root=self.repo_root,
            ),
        )

    def _require_clean_snapshot(self, snapshot: RepositorySnapshot) -> RepositorySnapshot:
        if snapshot.dirty_paths:
            raise StudyStateError("implementation validation requires a clean worktree")
        if (
            len(snapshot.head) != 40
            or any(character not in "0123456789abcdef" for character in snapshot.head)
        ):
            raise StudyStateError("implementation validation HEAD is invalid")
        expected_paths = self.protocol.implementation_projection_paths()
        if tuple(entry.path for entry in snapshot.projection) != expected_paths:
            raise StudyStateError("implementation projection is incomplete or reordered")
        return snapshot

    def _require_unchanged_snapshot(
        self,
        snapshot: RepositorySnapshot,
        baseline: RepositorySnapshot,
        *,
        allowed_dirty: tuple[str, ...] = (),
    ) -> None:
        if snapshot.head != baseline.head:
            raise StudyStateError("implementation validation HEAD changed")
        if snapshot.projection != baseline.projection:
            raise StudyStateError("implementation validation projection changed")
        if snapshot.dirty_paths != allowed_dirty:
            raise StudyStateError("implementation validation worktree changed")

    def _validation_environment(self, uv_path: Path, npm_path: Path) -> Mapping[str, str]:
        parents: list[str] = []
        for parent in (uv_path.parent.as_posix(), npm_path.parent.as_posix()):
            if parent not in parents:
                parents.append(parent)
        path = ":".join((*parents, VALIDATION_SYSTEM_PATH_SUFFIX))
        return MappingProxyType(
            {
                "HOME": self._home_directory.as_posix(),
                "PATH": path,
                "TMPDIR": self._temp_directory.as_posix(),
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
        )

    def _artifact_relative_root(self) -> str:
        try:
            relative = self.protocol.artifact_root.relative_to(self.repo_root).as_posix()
        except ValueError as exc:
            raise StudyStateError("artifact root is outside the repository") from exc
        if not relative or relative == ".":
            raise StudyStateError("artifact root cannot be the repository root")
        return relative

    def _read_store(self) -> tuple[StudyArtifactStore, bool]:
        if self._store is not None:
            return self._store, False
        store = StudyArtifactStore.open_existing(
            self.protocol.artifact_root,
            allowed_root=self.repo_root,
        )
        if store is None:
            raise StudyStateError("study artifact root is absent")
        return store, True

    def _write_store(self) -> tuple[StudyArtifactStore, bool]:
        if self._store is not None:
            return self._store, False
        return (
            StudyArtifactStore(
                self.protocol.artifact_root,
                allowed_root=self.repo_root,
            ),
            True,
        )


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _production_executable_search_path() -> str:
    """Return reviewed executable roots without ambient PATH or HOME authority."""

    try:
        return ":".join(reviewed_validation_executable_roots())
    except StudyRetentionError as exc:
        raise StudyStateError("production executable lookup root is invalid") from exc


def _validated_lookup_path(path: Path, *, expected_name: str) -> Path:
    lexical = _absolute_lexical(path)
    value = lexical.as_posix()
    if (
        lexical.name != expected_name
        or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in {"", ".", ".."} for part in lexical.parts[1:])
    ):
        raise StudyStateError(f"{expected_name} executable lookup path is invalid")
    return lexical


def _validation_command_record(
    request: ValidationCommandRequest,
    result: ValidationCommandResult,
) -> dict[str, object]:
    if type(result.exit_code) is not int or result.exit_code != 0:
        raise StudyStateError(f"validation command returned nonzero: {request.name}")
    if not isinstance(result.stdout, bytes) or not isinstance(result.stderr, bytes):
        raise StudyStateError("validation command output must be bytes")
    if (
        len(result.stdout) > request.output_limit_bytes
        or len(result.stderr) > request.output_limit_bytes
    ):
        raise StudyStateError("validation command output exceeded the byte limit")
    started = _utc_timestamp(result.started_at_utc)
    ended = _utc_timestamp(result.ended_at_utc)
    if result.ended_at_utc < result.started_at_utc:
        raise StudyStateError("validation command timestamps are reversed")
    return {
        "name": request.name,
        "argv": list(request.argv),
        "executable_lookup_path": request.executable_lookup_path.as_posix(),
        "exit_code": result.exit_code,
        "stdout_sha256": sha256(result.stdout).hexdigest(),
        "stderr_sha256": sha256(result.stderr).hexdigest(),
        "started_at_utc": started,
        "ended_at_utc": ended,
        "cwd": ".",
        "shell": False,
        "timeout_seconds": request.timeout_seconds,
        "output_limit_bytes": request.output_limit_bytes,
        "timed_out": False,
        "stdout_byte_count": len(result.stdout),
        "stderr_byte_count": len(result.stderr),
        "sanitized_environment": dict(request.environment),
    }


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != datetime.min.replace(tzinfo=UTC).utcoffset():
        raise StudyStateError("validation command timestamp is not UTC")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json_hash(value: object) -> str:
    return sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _projection_hash(projection: tuple[ProjectionEntry, ...], path: str) -> str:
    try:
        return next(entry.sha256 for entry in projection if entry.path == path)
    except StopIteration as exc:
        raise StudyStateError(f"implementation projection is missing {path}") from exc


def _state_execution_commit(state: VerifiedStudyState) -> str:
    validation = state.verified_json.get("implementation-validation.json")
    if validation is None:
        raise StudyStateError("implementation validation evidence is missing")
    value = validation.document.get("execution_commit")
    if not isinstance(value, str) or len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise StudyStateError("implementation validation execution commit is invalid")
    return value


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": pillow_version,
    }


def _applied_transform_record(transform: AppliedAffineTransform) -> dict[str, float]:
    return {
        "scale_factor": transform.scale_factor,
        "rotation_degrees": transform.rotation_degrees,
        "translation_x": transform.translation_x,
        "translation_y": transform.translation_y,
    }


def _diagnostic_case_record(case: StudyTruthCase) -> dict[str, object]:
    return {
        "diagnostic_id": case.case_id,
        "seed": case.seed,
        "expected_outcome": case.expected_outcome,
        "part_id": case.part_id,
        "cad_revision": case.cad_revision,
        "view_id": case.view_id,
        "reference_sha256": case.reference_sha256,
        "inspection_sha256": case.inspection_sha256,
        "authoritative_mask_sha256": case.authoritative_mask_sha256,
        "applied_transform": _applied_transform_record(case.applied_transform),
        "defect_type": case.defect_type,
        "defect_severity": case.defect_severity,
        "expected_feature_id": case.expected_feature_id,
    }


def _diagnostic_observation_record(
    row: DiagnosticObservation,
    boundary: ReferenceBoundaryBand,
) -> dict[str, object]:
    record = dict(row.record)
    record["defect_row"] = row.defect_row
    record["medium_high_row"] = row.medium_high_row
    record["boundary_band"] = {
        "radius": boundary.radius,
        "foreground_positive_pixels": boundary.foreground_positive_pixels,
        "boundary_positive_pixels": boundary.boundary_positive_pixels,
        "band_positive_pixels": boundary.band_positive_pixels,
        "band_mask_sha256": boundary.band_mask_sha256,
    }
    return record


def _applicable_gate(
    *,
    name: str,
    passed: bool,
    numerator: int | None,
    denominator: int,
    exclusions: int,
    observed: float,
    operator: Literal["ge", "le", "eq"],
    threshold: float,
) -> dict[str, object]:
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "numerator": numerator,
        "denominator": denominator,
        "exclusions": exclusions,
        "observed": observed,
        "operator": operator,
        "threshold": threshold,
        "reason": None,
    }


def _diagnostic_summary_record(summary: DiagnosticModeSummary) -> dict[str, object]:
    maximum_passed = summary.maximum_recall_drop <= 0.05
    median_passed = summary.median_dice_drop <= 0.01
    classification_passed = summary.medium_high_classification_recall >= 0.9
    return {
        "mode": summary.mode.value,
        "row_count": summary.row_count,
        "defect_drop_denominator": summary.defect_drop_denominator,
        "defect_drop_exclusions": 84,
        "medium_high_classification_denominator": (
            summary.medium_high_classification_denominator
        ),
        "medium_high_classification_exclusions": 84,
        "maximum_recall_drop": summary.maximum_recall_drop,
        "median_dice_drop": summary.median_dice_drop,
        "medium_high_classification_recall": (
            summary.medium_high_classification_recall
        ),
        "gates": [
            _applicable_gate(
                name="maximum_recall_drop",
                passed=maximum_passed,
                numerator=None,
                denominator=24,
                exclusions=84,
                observed=summary.maximum_recall_drop,
                operator="le",
                threshold=0.05,
            ),
            _applicable_gate(
                name="median_dice_drop",
                passed=median_passed,
                numerator=None,
                denominator=24,
                exclusions=84,
                observed=summary.median_dice_drop,
                operator="le",
                threshold=0.01,
            ),
            _applicable_gate(
                name="medium_high_classification_recall",
                passed=classification_passed,
                numerator=round(summary.medium_high_classification_recall * 24),
                denominator=24,
                exclusions=84,
                observed=summary.medium_high_classification_recall,
                operator="ge",
                threshold=0.9,
            ),
        ],
        "eligible": summary.eligible,
    }


def _result_envelope(
    protocol: StudyProtocolV2,
    state: VerifiedStudyState,
    *,
    record_type: str,
    execution_commit: str,
    upstream_paths: tuple[str, ...],
    payload: Mapping[str, object],
    extra_upstreams: Mapping[str, VerifiedStudyJson] | None = None,
) -> dict[str, object]:
    validation = state.verified_json.get("implementation-validation.json")
    if validation is None:
        raise StudyStateError("result envelope lacks implementation validation")
    artifact_schema_sha256 = validation.document.get("artifact_schema_sha256")
    projection_sha256 = validation.document.get("implementation_projection_sha256")
    if not isinstance(artifact_schema_sha256, str) or not isinstance(
        projection_sha256, str
    ):
        raise StudyStateError("validation envelope hashes are invalid")
    available = dict(state.verified_json)
    available.update(extra_upstreams or {})
    upstream_records: list[dict[str, str]] = []
    for path in upstream_paths:
        upstream = available.get(path)
        if upstream is None:
            raise StudyStateError(f"result upstream is missing: {path}")
        upstream_records.append(
            {
                "path": path,
                "raw_sha256": upstream.raw_sha256,
                "record_sha256": upstream.record_sha256,
            }
        )
    return {
        "record_type": record_type,
        "schema_version": "1.0.0",
        "study_id": "e1-feasibility-separability",
        "development_only": True,
        "selection_eligible": False,
        "release_claim_allowed": False,
        "base_commit": protocol.base_commit,
        "execution_commit": execution_commit,
        "protocol_sha256": protocol.configuration_sha256,
        "artifact_root": protocol.artifact_root_identity,
        "artifact_schema_sha256": artifact_schema_sha256,
        "implementation_projection_sha256": projection_sha256,
        "upstream_artifacts": upstream_records,
        "payload": dict(payload),
    }


def _development_bindings(corpus: DevelopmentCorpus) -> list[dict[str, object]]:
    expected = tuple(
        (group, ordinal, start + ordinal)
        for group, count, start in (
            ("clean", 24, 400000),
            ("nuisance", 30, 410000),
            ("defect", 60, 420000),
            ("trust_boundary", 6, 430000),
        )
        for ordinal in range(count)
    )
    if len(corpus.cases) != 120 or len(expected) != len(corpus.cases):
        raise StudyStateError("development corpus does not contain 120 cases")
    records: list[dict[str, object]] = []
    for case, (group, ordinal, seed) in zip(corpus.cases, expected, strict=True):
        expected_id = f"e1-v2-development-{group}-{ordinal:03d}"
        if (
            case.case_id != expected_id
            or case.seed != seed
            or case.group != group
            or case.case_binding_sha256 is None
            or case.trust_boundary is (group != "trust_boundary")
        ):
            raise StudyStateError("development corpus ordering or binding changed")
        records.append(
            {
                "case_id": case.case_id,
                "seed": case.seed,
                "group": case.group,
                "reference_sha256": case.reference_sha256,
                "inspection_sha256": case.inspection_sha256,
                "authoritative_mask_sha256": case.authoritative_mask_sha256,
                "case_binding_sha256": case.case_binding_sha256,
            }
        )
    expected_counts = {
        "clean": 24,
        "nuisance": 30,
        "defect": 60,
        "trust_boundary": 6,
        "total": 120,
    }
    if (
        dict(corpus.counts) != expected_counts
        or corpus.scope_projection != ("development",)
        or corpus.external_request_count != 1
        or corpus.internal_membership_validation_count != 120
    ):
        raise StudyStateError("development corpus scope audit changed")
    return records


def _oracle_records(
    protocol: StudyProtocolV2,
    corpus: DevelopmentCorpus,
    oracle: FeatureOracleResult,
) -> list[dict[str, object]]:
    defects = tuple(case for case in corpus.cases if case.group == "defect")
    if len(defects) != 60 or len(oracle.records) != 60 or oracle.case_count != 60:
        raise StudyStateError("feature oracle row count changed")
    if dict(oracle.ownership_hashes) != dict(protocol.ownership_map_hashes):
        raise StudyStateError("feature oracle ownership hashes changed")
    records: list[dict[str, object]] = []
    layouts = _frozen_oracle_layout_projection()
    for case, source, layout in zip(defects, oracle.records, layouts, strict=True):
        record = dict(source)
        case_id, seed, cad_revision, view_id = layout
        if (
            (case.case_id, case.seed, case.cad_revision, case.view_id) != layout
            or record.get("case_id") != case_id
            or record.get("cad_revision") != cad_revision
            or record.get("view_id") != view_id
            or record.get("authoritative_mask_sha256")
            != case.authoritative_mask_sha256
            or record.get("expected_feature_id") != case.expected_feature_id
        ):
            raise StudyStateError("feature oracle record layout is not bound to its case")
        expected_hash = protocol.ownership_map_hashes.get(f"{cad_revision}/{view_id}")
        hash_binding_matches = (
            isinstance(expected_hash, str)
            and record.get("ownership_map_sha256") == expected_hash
        )
        if (
            record.get("hash_binding_matches") is not hash_binding_matches
            or not hash_binding_matches
        ):
            raise StudyStateError("feature oracle ownership hash binding changed")
        positive = record.get("authoritative_positive_pixels")
        owned = record.get("owned_pixel_count")
        unmapped = record.get("unmapped_pixel_count")
        conserved = (
            type(positive) is int
            and type(owned) is int
            and type(unmapped) is int
            and owned + unmapped == positive
        )
        target_owned = record.get("target_owned_pixels")
        expected_correct = (
            record.get("status") == "MAPPED"
            and record.get("predicted_feature_id") == record.get("expected_feature_id")
            and type(target_owned) is int
            and target_owned >= 8
            and conserved
            and hash_binding_matches
        )
        if record.get("correct") is not expected_correct:
            raise StudyStateError("feature oracle correct-case declaration changed")
        record["seed"] = seed
        record["conserved"] = conserved
        records.append(record)
    correct = sum(record.get("correct") is True for record in records)
    ambiguous = sum(record.get("status") == "AMBIGUOUS" for record in records)
    null = sum(record.get("status") == "UNMAPPED" for record in records)
    wrong = 60 - correct - ambiguous - null
    recomputed_passed = (
        correct == 60
        and ambiguous == 0
        and null == 0
        and wrong == 0
        and all(record["conserved"] is True for record in records)
        and all(record.get("hash_binding_matches") is True for record in records)
    )
    if (
        (oracle.correct_cases, oracle.ambiguous_cases, oracle.null_cases, oracle.wrong_cases)
        != (correct, ambiguous, null, wrong)
        or oracle.passed is not recomputed_passed
    ):
        raise StudyStateError("feature oracle totals or pass flag changed")
    return records


def _state_eligible_modes(state: VerifiedStudyState) -> tuple[ResamplingMode, ...]:
    diagnostic = state.verified_json.get("known-transform-diagnostic-108.json")
    if diagnostic is None:
        return ()
    payload = diagnostic.document.get("payload")
    if not isinstance(payload, Mapping):
        raise StudyStateError("diagnostic payload is invalid")
    values = payload.get("eligible_modes")
    if not isinstance(values, tuple):
        raise StudyStateError("diagnostic eligible modes are invalid")
    try:
        modes = tuple(ResamplingMode(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise StudyStateError("diagnostic eligible modes are invalid") from exc
    expected = tuple(mode for mode in ResamplingMode if mode in modes)
    if modes != expected:
        raise StudyStateError("diagnostic eligible modes are reordered")
    return modes


def _scope_bindings(state: VerifiedStudyState) -> list[dict[str, object]]:
    scope = state.verified_json.get("scope-audit.json")
    if scope is None:
        raise StudyStateError("verified scope is missing")
    payload = scope.document.get("payload")
    if not isinstance(payload, Mapping):
        raise StudyStateError("verified scope payload is invalid")
    bindings = payload.get("bindings")
    if not isinstance(bindings, tuple) or not all(
        isinstance(binding, Mapping) for binding in bindings
    ):
        raise StudyStateError("verified scope bindings are invalid")
    return [dict(cast(Mapping[str, object], binding)) for binding in bindings]


def _validate_feature_mapping_roundtrip(mapping: FeatureMappingResult) -> None:
    record = mapping.as_record()
    margin = record["winner_margin"]
    reconstructed = FeatureMappingResult(
        predicted_feature_id=cast(str | None, record["predicted_feature_id"]),
        status=cast(str, record["status"]),
        reason=cast(str, record["reason"]),
        owner_pixel_counts=cast(Mapping[str, int], record["owner_pixel_counts"]),
        owned_pixel_count=cast(int, record["owned_pixel_count"]),
        winner_owned_pixel_count=cast(int, record["winner_owned_pixel_count"]),
        final_positive_pixel_count=cast(int, record["final_positive_pixel_count"]),
        unmapped_pixel_count=cast(int, record["unmapped_pixel_count"]),
        winner_margin=None if margin is None else float(cast(str, margin)),
        final_mask_sha256=cast(str, record["final_mask_sha256"]),
        ownership_map_sha256=cast(str, record["ownership_map_sha256"]),
    )
    if reconstructed.as_record() != record:
        raise StudyStateError("feature mapping trace does not round-trip")


def _development_metrics_record(
    observation: E1V2EvaluationObservation,
) -> dict[str, object]:
    if observation.anomaly_score is None:
        raise StudyStateError("applicable development observation lacks a score")
    return {
        "expected_outcome": observation.expected_outcome,
        "actual_outcome": observation.actual_outcome,
        "anomaly_score": observation.anomaly_score,
        "defect_type": observation.defect_type,
        "severity": observation.severity,
        "nuisance_types": list(observation.nuisance_types),
        "cad_revision": observation.cad_revision,
        "view_id": observation.view_id,
        "truth_positive_pixels": observation.truth_positive_pixels,
        "predicted_positive_pixels": observation.predicted_positive_pixels,
        "intersection_pixels": observation.intersection_pixels,
        "total_pixels": observation.total_pixels,
        "expected_feature_id": observation.expected_feature_id,
        "predicted_feature_id": observation.predicted_feature_id,
    }


def _development_inference_record(
    case: StudyTruthCase,
    mode: ResamplingMode,
    result: StudyInferenceResult,
    observation: E1V2EvaluationObservation,
) -> dict[str, object]:
    if case.case_binding_sha256 is None:
        raise StudyStateError("development inference case lacks a binding")
    if result.transform_trace.resampling is not mode:
        raise StudyStateError("development inference trace mode changed")
    _validate_feature_mapping_roundtrip(result.feature_mapping)
    return {
        "case_id": case.case_id,
        "seed": case.seed,
        "group": case.group,
        "mode": mode.value,
        "case_binding_sha256": case.case_binding_sha256,
        "evaluation_status": "APPLICABLE",
        "inference_trace": result.as_record(),
        "metrics": _development_metrics_record(observation),
    }


def _trust_binding_record(case: StudyTruthCase) -> dict[str, object]:
    if case.case_binding_sha256 is None or not case.trust_boundary:
        raise StudyStateError("trust row is not a binding-only member")
    if case.applied_transform != AppliedAffineTransform(1.0, 0.0, 0.0, 0.0):
        raise StudyStateError("trust binding geometry is not identity")
    return {
        "case_id": case.case_id,
        "seed": case.seed,
        "group": case.group,
        "reference_sha256": case.reference_sha256,
        "inspection_sha256": case.inspection_sha256,
        "authoritative_mask_sha256": case.authoritative_mask_sha256,
        "case_binding_sha256": case.case_binding_sha256,
        "applied_transform": _applied_transform_record(case.applied_transform),
        "evaluation_status": "NOT_APPLICABLE",
        "actual_outcome": None,
        "anomaly_score": None,
        "denominator_exclusion": "TRUST_BOUNDARY_BINDING_ONLY",
    }


def _development_summary_record(summary: DevelopmentModeSummary) -> dict[str, object]:
    recall_passed = summary.medium_high_recall >= 0.9
    nuisance_passed = summary.nuisance_false_positive_rate <= 0.05
    dice_passed = summary.positive_median_dice >= 0.7
    feature_passed = summary.feature_mapping_accuracy >= 0.95
    return {
        "mode": summary.mode.value,
        "member_count": summary.member_count,
        "inference_count": summary.inference_count,
        "trust_binding_count": summary.trust_binding_count,
        "medium_high_recall": summary.medium_high_recall,
        "nuisance_false_positive_rate": summary.nuisance_false_positive_rate,
        "positive_median_dice": summary.positive_median_dice,
        "feature_mapping_accuracy": summary.feature_mapping_accuracy,
        "gates": [
            _applicable_gate(
                name="medium_high_defect_recall",
                passed=recall_passed,
                numerator=round(summary.medium_high_recall * 40),
                denominator=40,
                exclusions=74,
                observed=summary.medium_high_recall,
                operator="ge",
                threshold=0.9,
            ),
            _applicable_gate(
                name="nuisance_only_false_positive_rate",
                passed=nuisance_passed,
                numerator=round(summary.nuisance_false_positive_rate * 30),
                denominator=30,
                exclusions=84,
                observed=summary.nuisance_false_positive_rate,
                operator="le",
                threshold=0.05,
            ),
            _applicable_gate(
                name="positive_case_median_dice",
                passed=dice_passed,
                numerator=None,
                denominator=60,
                exclusions=54,
                observed=summary.positive_median_dice,
                operator="ge",
                threshold=0.7,
            ),
            _applicable_gate(
                name="affected_feature_mapping_accuracy",
                passed=feature_passed,
                numerator=round(summary.feature_mapping_accuracy * 60),
                denominator=60,
                exclusions=54,
                observed=summary.feature_mapping_accuracy,
                operator="ge",
                threshold=0.95,
            ),
        ],
        "passed_all_gates": summary.passed_all_gates,
    }
