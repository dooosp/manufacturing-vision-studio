from __future__ import annotations

import io
import json
import os
import pwd
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import cast

import pytest
from PIL import Image
from test_e1_study_artifacts_v2 import (
    minimal_valid_decision_record,
    minimal_valid_development_result_record,
    minimal_valid_diagnostic_result_record,
    minimal_valid_feature_oracle_record,
    minimal_valid_implementation_validation_record,
    minimal_valid_retention_audit_record,
    minimal_valid_scope_audit_record,
)
from test_e1_study_retention_v2 import _build_retention_fixture

from manufacturing_vision_studio.e1 import study_artifacts_v2 as artifacts_module
from manufacturing_vision_studio.e1 import study_runner_v2 as runner_module
from manufacturing_vision_studio.e1.known_transform_v2 import (
    AppliedAffineTransform,
    ResamplingMode,
)
from manufacturing_vision_studio.e1.protocol_v2 import E1V2Protocol
from manufacturing_vision_studio.e1.study_artifacts_v2 import (
    StudyArtifactError,
    StudyArtifactRecord,
    StudyArtifactStore,
    VerifiedStudyJson,
    begin_phase_execution,
    finalize_study_record,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    FrozenDiagnosticPlan,
    StudyProtocolV2,
    load_study_protocol_v2,
)
from manufacturing_vision_studio.e1.study_retention_v2 import (
    IMPLEMENTATION_VALIDATION_COMMANDS,
    IMPLEMENTATION_VALIDATION_TIMEOUT_SECONDS,
    ProjectionEntry,
    run_retention_audit,
)
from manufacturing_vision_studio.e1.study_runner_v2 import (
    CommandRunner,
    DiagnosticRenderer,
    InferenceRunner,
    NormalizeCallback,
    OracleRunner,
    RepositorySnapshot,
    StudyRunner,
    StudyStateError,
    StudyStatus,
    ValidationCommandRequest,
    ValidationCommandResult,
    VerifiedStudyState,
    run_small_fixture_determinism_control,
)
from manufacturing_vision_studio.e1.study_truth_v2 import (
    DevelopmentCorpus,
    DevelopmentModeSummary,
    DiagnosticModeSummary,
    DiagnosticObservation,
    FeatureOracleResult,
    StudyTruthCase,
)

_ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
_REVIEWED_PRODUCTION_LOOKUP_PATH = ":".join(
    (
        (_ACCOUNT_HOME / ".local/bin").as_posix(),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    )
)


def _runner(tmp_path: Path, *, root_name: str = "artifacts") -> StudyRunner:
    protocol = replace(
        load_study_protocol_v2(),
        artifact_root=tmp_path / root_name,
    )
    return StudyRunner(protocol, repo_root=tmp_path)


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _runner_with_deleted_committed_evidence(
    tmp_path: Path,
    *,
    active_paths: tuple[str, ...] = (),
    deleted_path: str = "implementation-validation.json",
) -> tuple[StudyRunner, RepositorySnapshot, SimpleNamespace]:
    """Build a real linear Git history whose endpoint hides deleted evidence."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "fixture")
    _git(repo_root, "config", "user.name", "Monotonic History Test")
    _git(repo_root, "config", "user.email", "history@example.invalid")
    (repo_root / ".base").write_bytes(b"base\n")
    _git(repo_root, "add", ".base")
    _git(repo_root, "commit", "-m", "base")
    base_commit = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "branch", "codex/e1-v2-scale-feature-remediation", base_commit)
    (repo_root / "implementation.txt").write_bytes(b"implementation\n")
    _git(repo_root, "add", "implementation.txt")
    _git(repo_root, "commit", "-m", "implementation")
    execution_commit = _git(repo_root, "rev-parse", "HEAD")

    real = load_study_protocol_v2()
    document = real.document
    document["base_commit"] = base_commit
    protocol = replace(
        real,
        _document=document,
        artifact_root=repo_root / "artifacts",
    )
    for relative_path in active_paths:
        path = protocol.artifact_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"active {relative_path}\n".encode())
    if active_paths:
        _git(repo_root, "add", "artifacts")
        _git(repo_root, "commit", "-m", "active evidence prerequisites")
    evidence_path = protocol.artifact_root / deleted_path
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_bytes(b"committed evidence\n")
    _git(repo_root, "add", f"artifacts/{deleted_path}")
    _git(repo_root, "commit", "-m", "commit transient evidence")
    evidence_path.unlink()
    _git(repo_root, "add", "-A", "artifacts")
    _git(repo_root, "commit", "-m", "delete validation evidence")
    head = _git(repo_root, "rev-parse", "HEAD")
    projection = _projection(protocol.implementation_projection_paths())
    snapshot = RepositorySnapshot(head, (), projection)
    validation = SimpleNamespace(
        document={"execution_commit": execution_commit},
        execution_commit=execution_commit,
        raw_bytes=(
            (protocol.artifact_root / "implementation-validation.json").read_bytes()
            if "implementation-validation.json" in active_paths
            else b""
        ),
        implementation_projection_sha256=runner_module._canonical_json_hash(
            [entry.as_record() for entry in projection]
        ),
    )
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=repo_root)
    runner = StudyRunner(
        protocol,
        repo_root=repo_root,
        store=store,
        repository_state=lambda: RepositorySnapshot(
            head,
            runner_module._git_status_paths(repo_root),
            projection,
        ),
    )
    return runner, snapshot, validation


def test_validation_history_deletion_stops_commands_before_first_callback(
    tmp_path: Path,
) -> None:
    """Catch first validation reopening after prior committed evidence removal."""

    runner, _, _ = _runner_with_deleted_committed_evidence(tmp_path)
    calls = 0

    def command_runner(request: ValidationCommandRequest) -> ValidationCommandResult:
        nonlocal calls
        del request
        calls += 1
        raise AssertionError("historical deletion must stop validation commands")

    runner._command_runner = command_runner

    with pytest.raises(StudyStateError, match=r"monotonic|deleted|history"):
        runner.validate_implementation()

    assert calls == 0


@pytest.mark.parametrize("phase", ("phase0", "phase1", "oracle", "phase2"))
def test_mutating_phase_history_deletion_stops_corresponding_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    """Catch later study phases reopening after committed evidence is removed."""

    calls = 0
    expected_by_phase = {
        "phase0": ("implementation-validation.json",),
        "phase1": ("implementation-validation.json", "retention-audit.json"),
        "oracle": runner_module._PRE_DECISION_PATHS[:4],
        "phase2": runner_module._PRE_DECISION_PATHS[:6],
    }
    status_by_phase = {
        "phase0": StudyStatus(True, False, False, False, False, "PENDING", ()),
        "phase1": StudyStatus(True, False, False, False, False, "PENDING", ()),
        "oracle": StudyStatus(True, True, False, False, False, "PENDING", ()),
        "phase2": StudyStatus(True, True, True, True, False, "PENDING", ()),
    }
    expected = expected_by_phase[phase]
    deleted_by_phase = {
        "phase0": "retention-audit.json",
        "phase1": "phase-1-execution-claim.json",
        "oracle": "scope-audit.json",
        "phase2": "phase-2-execution-claim.json",
    }
    active_paths = expected
    if "retention-audit.json" in expected:
        active_paths = (*active_paths, *runner_module._RETAINED_FILES)
    runner, _, validation = _runner_with_deleted_committed_evidence(
        tmp_path,
        active_paths=active_paths,
        deleted_path=deleted_by_phase[phase],
    )
    evidence = {"implementation-validation.json": validation}
    if "retention-audit.json" in expected:
        evidence["retention-audit.json"] = SimpleNamespace(
            document={},
            raw_bytes=(runner.protocol.artifact_root / "retention-audit.json").read_bytes(),
        )
    for relative_path in expected:
        if relative_path not in evidence:
            document: Mapping[str, object] = {}
            if relative_path == "known-transform-diagnostic-108.json":
                document = {"payload": {"eligible_modes": ("NEAREST",)}}
            evidence[relative_path] = SimpleNamespace(
                document=document,
                raw_bytes=(runner.protocol.artifact_root / relative_path).read_bytes(),
            )
    state = VerifiedStudyState(
        status_by_phase[phase],
        expected,
        (),
        cast(Mapping[str, VerifiedStudyJson], evidence),
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        runner_module,
        "verify_implementation_validation",
        lambda *args, **kwargs: validation,
    )
    monkeypatch.setattr(runner_module, "verify_retention_audit", lambda *args, **kwargs: object())

    def forbidden(*args: object, **kwargs: object) -> object:
        nonlocal calls
        del args, kwargs
        calls += 1
        raise AssertionError("historical deletion must stop the phase callback")

    if phase == "phase0":
        monkeypatch.setattr(runner_module, "run_retention_audit", forbidden)
        invoke = runner.phase0
    elif phase == "phase1":
        runner._e1_protocol_loader = lambda: cast(E1V2Protocol, SimpleNamespace())
        runner._render = cast(DiagnosticRenderer, forbidden)
        invoke = runner.phase1
    elif phase == "oracle":
        runner._e1_protocol_loader = lambda: cast(E1V2Protocol, SimpleNamespace())
        runner._corpus = cast(Callable[[], DevelopmentCorpus], forbidden)
        invoke = runner.feature_oracle
    else:
        runner._e1_protocol_loader = lambda: cast(E1V2Protocol, SimpleNamespace())
        runner._corpus = cast(Callable[[], DevelopmentCorpus], forbidden)
        invoke = runner.phase2

    with pytest.raises(runner_module.StudyRetentionError, match=r"monotonic|deleted|history"):
        invoke()

    assert calls == 0


def test_finalization_preflight_rejects_deleted_committed_evidence(
    tmp_path: Path,
) -> None:
    """Catch finalization reopening after a committed decision is removed."""

    active_paths = (*runner_module._PRE_DECISION_PATHS, *runner_module._RETAINED_FILES)
    runner, _, validation = _runner_with_deleted_committed_evidence(
        tmp_path,
        active_paths=active_paths,
        deleted_path="decision.json",
    )
    state = VerifiedStudyState(
        StudyStatus(True, True, True, True, True, "TRANSFORM_ESTIMATION_LIMITED", ()),
        runner_module._PRE_DECISION_PATHS,
        (),
        cast(
            Mapping[str, VerifiedStudyJson],
            {"implementation-validation.json": validation},
        ),
    )

    with pytest.raises(StudyStateError, match=r"monotonic|deleted|history"):
        runner._require_finalization_preflight(state)


def test_status_on_absent_root_is_pristine_and_creates_nothing(tmp_path: Path) -> None:
    artifact_root = tmp_path / "missing-artifacts"
    runner = _runner(tmp_path, root_name="missing-artifacts")

    status = runner.status()

    assert status.study_valid is True
    assert status.phase1_complete is False
    assert status.feature_oracle_complete is False
    assert status.phase2_authorized is False
    assert status.phase2_complete is False
    assert status.terminal_decision == "PENDING"
    assert status.reasons == ()
    assert not artifact_root.exists()


def test_verify_on_absent_root_is_read_only(tmp_path: Path) -> None:
    runner = _runner(tmp_path, root_name="missing-artifacts")

    report = runner.verify()

    assert report.verified_paths == ()
    assert report.verify_rate == 0.0
    assert report.status.terminal_decision == "PENDING"
    assert not (tmp_path / "missing-artifacts").exists()


def test_inventory_rejects_unknown_symlink_and_hardlink_nodes(tmp_path: Path) -> None:
    for ordinal, create_invalid in enumerate(
        (
            lambda root: (root / "unknown.tmp").write_bytes(b"stale"),
            lambda root: (root / "unknown-link").symlink_to("missing"),
            lambda root: os.link(
                root.parent / "hardlink-source",
                root / "implementation-validation.json",
            ),
        )
    ):
        case_root = tmp_path / f"case-{ordinal}"
        case_root.mkdir()
        if ordinal == 2:
            (tmp_path / "hardlink-source").write_bytes(b"not-json")
        create_invalid(case_root)
        runner = _runner(tmp_path, root_name=f"case-{ordinal}")

        status = runner.status()

        assert status.study_valid is False
        assert status.terminal_decision == "STUDY_INVALID"
        assert "ARTIFACT_INVENTORY_INVALID" in status.reasons


def test_partial_retained_packet_is_permanently_invalid(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    retained = tmp_path / "artifacts" / "retained-inputs"
    retained.mkdir(parents=True)
    (retained / "candidate-a.json").write_bytes(b"partial")

    status = runner.status()
    report = runner.verify()

    assert status.study_valid is False
    assert status.terminal_decision == "STUDY_INVALID"
    assert status.reasons == ("PARTIAL_RETENTION_PACKET",)
    assert report.status == status
    assert tuple(sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))) == (
        "artifacts",
        "artifacts/retained-inputs",
        "artifacts/retained-inputs/candidate-a.json",
    )


def test_orphaned_phase1_claim_is_terminal_and_never_removed(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    protocol = runner.protocol
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    try:
        claim = begin_phase_execution(
            phase="phase1",
            protocol=protocol,
            execution_commit="a" * 40,
            eligible_modes=(),
        )
        store.publish_json("phase-1-execution-claim.json", claim.as_record())
    finally:
        store.close()

    status = runner.status()

    assert status.study_valid is False
    assert status.terminal_decision == "STUDY_INVALID"
    assert "PHASE1_CLAIM_RESULT_ORPHAN" in status.reasons
    assert (protocol.artifact_root / "phase-1-execution-claim.json").is_file()


def test_determinism_fixture_uses_two_independent_paths_and_exact_mode_order() -> None:
    calls: list[tuple[bytes, bytes, object, object]] = []

    def normalize(
        reference_bytes: bytes,
        inspection_bytes: bytes,
        *,
        reference_sha256: str,
        inspection_sha256: str,
        applied_transform: object,
        resampling: object,
    ) -> object:
        assert sha256(reference_bytes).hexdigest() == reference_sha256
        assert sha256(inspection_bytes).hexdigest() == inspection_sha256
        digest = sha256(reference_bytes).hexdigest()
        calls.append((reference_bytes, inspection_bytes, applied_transform, resampling))
        return SimpleNamespace(
            normalized_bytes=reference_bytes,
            normalized_sha256=digest,
            trace=SimpleNamespace(normalized_sha256=digest),
        )

    control = run_small_fixture_determinism_control(
        normalize=cast(NormalizeCallback, normalize)
    )

    assert control.passed is True
    assert dict(control.first_projection) == dict(control.second_projection)
    assert tuple(str(call[3]) for call in calls) == (
        "NEAREST",
        "BILINEAR",
        "BICUBIC",
        "NEAREST",
        "BILINEAR",
        "BICUBIC",
    )
    assert calls[0][0] == calls[3][0]
    assert calls[0][0] is not calls[3][0]
    with Image.open(io.BytesIO(calls[0][0])) as image:
        assert image.size == (512, 384)
        assert image.getpixel((0, 0)) == (17, 23, 31)
        assert image.getpixel((52, 44)) == (231, 37, 19)
        assert image.getpixel((177, 161)) == (231, 37, 19)
        assert image.getpixel((178, 162)) == (17, 23, 31)


def _projection(protocol_paths: tuple[str, ...]) -> tuple[ProjectionEntry, ...]:
    return tuple(
        ProjectionEntry(path, sha256(path.encode()).hexdigest()) for path in protocol_paths
    )


def _validation_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    command_runner: CommandRunner,
    snapshots: list[RepositorySnapshot] | None = None,
) -> tuple[StudyRunner, list[tuple[str, str | None]], list[RepositorySnapshot]]:
    monkeypatch.setattr(
        runner_module,
        "_verify_pristine_artifact_history",
        lambda *args, **kwargs: None,
    )
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    projection = _projection(protocol.implementation_projection_paths())
    baseline = RepositorySnapshot("a" * 40, (), projection)
    observed_snapshots: list[RepositorySnapshot] = []

    def repository_state() -> RepositorySnapshot:
        if snapshots:
            snapshot = snapshots.pop(0)
        elif (protocol.artifact_root / "implementation-validation.json").exists():
            snapshot = RepositorySnapshot(
                baseline.head,
                ("artifacts/implementation-validation.json",),
                projection,
            )
        else:
            snapshot = baseline
        observed_snapshots.append(snapshot)
        return snapshot

    resolver_calls: list[tuple[str, str | None]] = []

    def resolve(name: str, search_path: str | None) -> Path:
        resolver_calls.append((name, search_path))
        if name == "uv":
            return Path("/opt/homebrew/bin/uv")
        if name == "npm":
            return Path("/usr/local/bin/npm")
        if name == "node":
            return Path("/usr/local/bin/node")
        raise AssertionError(name)

    def normalize(
        reference_bytes: bytes,
        inspection_bytes: bytes,
        *,
        reference_sha256: str,
        inspection_sha256: str,
        applied_transform: object,
        resampling: object,
    ) -> object:
        del inspection_bytes, reference_sha256, inspection_sha256, applied_transform
        digest = sha256(reference_bytes).hexdigest()
        return SimpleNamespace(
            normalized_bytes=reference_bytes,
            normalized_sha256=digest,
            trace=SimpleNamespace(normalized_sha256=digest),
        )

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        command_runner=command_runner,
        executable_resolver=resolve,
        repository_state=repository_state,
        normalize=cast(NormalizeCallback, normalize),
        home_directory=Path("/tmp/e1-study-home"),
        temp_directory=Path("/tmp/e1-study"),
    )
    return runner, resolver_calls, observed_snapshots


def test_validation_transaction_records_fixed_requests_and_rechecks_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[ValidationCommandRequest] = []
    started = datetime(2026, 8, 1, tzinfo=UTC)

    def command_runner(request: ValidationCommandRequest) -> ValidationCommandResult:
        requests.append(request)
        ordinal = len(requests)
        return ValidationCommandResult(
            exit_code=0,
            stdout=f"stdout-{ordinal}".encode(),
            stderr=f"stderr-{ordinal}".encode(),
            started_at_utc=started + timedelta(seconds=ordinal),
            ended_at_utc=started + timedelta(seconds=ordinal + 1),
        )

    runner, resolver_calls, snapshots = _validation_dependencies(
        tmp_path,
        monkeypatch,
        command_runner=command_runner,
    )
    verifier_calls: list[str] = []

    def verify_published(protocol: object, store: StudyArtifactStore, **kwargs: object) -> object:
        del protocol, kwargs
        verifier_calls.append("implementation-validation.json")
        return store.verify_json_result(
            "implementation-validation.json",
            expected_record_type="implementation_validation",
        )

    monkeypatch.setattr(
        runner_module,
        "verify_implementation_validation",
        verify_published,
    )

    published = runner.validate_implementation()

    assert published.path == "implementation-validation.json"
    assert tuple((request.name, request.argv) for request in requests) == (
        IMPLEMENTATION_VALIDATION_COMMANDS
    )
    assert tuple(request.timeout_seconds for request in requests) == (
        IMPLEMENTATION_VALIDATION_TIMEOUT_SECONDS
    )
    assert tuple(request.executable_lookup_path.as_posix() for request in requests) == (
        *("/opt/homebrew/bin/uv" for _ in range(4)),
        *("/usr/local/bin/npm" for _ in range(2)),
    )
    expected_path = (
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    )
    assert all(request.cwd == tmp_path for request in requests)
    assert all(request.output_limit_bytes == 4_194_304 for request in requests)
    assert all(request.environment["PATH"] == expected_path for request in requests)
    assert all(len(request.environment) == 16 for request in requests)
    assert all(request.environment == requests[0].environment for request in requests)
    assert resolver_calls == [
        ("uv", _REVIEWED_PRODUCTION_LOOKUP_PATH),
        ("npm", _REVIEWED_PRODUCTION_LOOKUP_PATH),
        ("node", expected_path),
    ]
    assert len(snapshots) == 15
    assert snapshots[-1].dirty_paths == (
        "artifacts/implementation-validation.json",
    )
    assert verifier_calls == ["implementation-validation.json"]
    store = StudyArtifactStore.open_existing(
        runner.protocol.artifact_root,
        allowed_root=tmp_path,
    )
    assert store is not None
    try:
        document = store.verify_json(
            "implementation-validation.json",
            expected_record_type="implementation_validation",
        )
    finally:
        store.close()
    payload = cast(dict[str, object], document["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    assert [command["stdout_byte_count"] for command in commands] == [8] * 6
    assert [command["stderr_byte_count"] for command in commands] == [8] * 6


def test_existing_valid_implementation_validation_runs_zero_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = replace(
        load_study_protocol_v2(),
        artifact_root=tmp_path / "artifacts",
    )
    protocol.artifact_root.mkdir()
    callback_calls: list[str] = []

    def forbidden_callback(*args: object, **kwargs: object) -> object:
        del args, kwargs
        callback_calls.append("called")
        raise AssertionError("existing evidence must not invoke an execution callback")

    evidence = SimpleNamespace(
        raw_sha256="1" * 64,
        raw_bytes=b"{}",
        record_sha256="2" * 64,
    )
    state = VerifiedStudyState(
        status=StudyStatus(True, False, False, False, False, "PENDING", ()),
        present_paths=("implementation-validation.json",),
        invalid_paths=(),
        verified_json=cast(
            Mapping[str, VerifiedStudyJson],
            {"implementation-validation.json": evidence},
        ),
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        runner_module,
        "verify_implementation_validation",
        lambda *args, **kwargs: evidence,
    )
    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        command_runner=cast(CommandRunner, forbidden_callback),
        executable_resolver=cast(runner_module.ExecutableResolver, forbidden_callback),
        repository_state=cast(runner_module.RepositoryStateReader, forbidden_callback),
        normalize=cast(NormalizeCallback, forbidden_callback),
    )

    record = runner.validate_implementation()

    assert record == StudyArtifactRecord(
        path="implementation-validation.json",
        sha256="1" * 64,
        byte_size=2,
        media_type="application/json",
        record_sha256="2" * 64,
    )
    assert callback_calls == []


@pytest.mark.parametrize(
    "bad_result",
    (
        ValidationCommandResult(
            2,
            b"",
            b"failed",
            datetime(2026, 8, 1, tzinfo=UTC),
            datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC),
        ),
        ValidationCommandResult(
            0,
            b"x" * (4_194_304 + 1),
            b"",
            datetime(2026, 8, 1, tzinfo=UTC),
            datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC),
        ),
        ValidationCommandResult(
            0,
            b"",
            b"",
            datetime(2026, 8, 1),
            datetime(2026, 8, 1, 0, 0, 1),
        ),
    ),
)
def test_validation_failure_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_result: ValidationCommandResult,
) -> None:
    calls = 0

    def command_runner(request: ValidationCommandRequest) -> ValidationCommandResult:
        nonlocal calls
        del request
        calls += 1
        return bad_result

    runner, _, _ = _validation_dependencies(
        tmp_path,
        monkeypatch,
        command_runner=command_runner,
    )

    with pytest.raises(StudyStateError):
        runner.validate_implementation()

    assert calls == 1
    assert not runner.protocol.artifact_root.exists()


def test_validation_head_drift_stops_between_commands_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = load_study_protocol_v2()
    projection = _projection(protocol.implementation_projection_paths())
    snapshots = [
        RepositorySnapshot("a" * 40, (), projection),
        RepositorySnapshot("b" * 40, (), projection),
    ]
    calls = 0

    def command_runner(request: ValidationCommandRequest) -> ValidationCommandResult:
        nonlocal calls
        del request
        calls += 1
        return ValidationCommandResult(
            0,
            b"",
            b"",
            datetime(2026, 8, 1, tzinfo=UTC),
            datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC),
        )

    runner, _, _ = _validation_dependencies(
        tmp_path,
        monkeypatch,
        command_runner=command_runner,
        snapshots=snapshots,
    )

    with pytest.raises(StudyStateError, match="HEAD"):
        runner.validate_implementation()

    assert calls == 1
    assert not runner.protocol.artifact_root.exists()


def test_validation_rejects_node_outside_sealed_path_before_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def command_runner(request: ValidationCommandRequest) -> ValidationCommandResult:
        nonlocal calls
        del request
        calls += 1
        raise AssertionError("command must not run")

    runner, _, _ = _validation_dependencies(
        tmp_path,
        monkeypatch,
        command_runner=command_runner,
    )

    def bad_resolver(name: str, search_path: str | None) -> Path:
        del search_path
        if name == "uv":
            return Path("/opt/homebrew/bin/uv")
        if name == "npm":
            return Path("/usr/local/bin/npm")
        return Path("/outside/node")

    monkeypatch.setattr(runner, "_executable_resolver", bad_resolver)

    with pytest.raises(StudyStateError, match="node"):
        runner.validate_implementation()

    assert calls == 0
    assert not runner.protocol.artifact_root.exists()


@pytest.mark.parametrize(
    ("tool_name", "unreviewed_path"),
    (
        ("uv", Path("/tmp/unreviewed-tools/uv")),
        ("npm", Path("/opt/homebrew/bin/nested/npm")),
    ),
)
def test_validation_rejects_unreviewed_resolver_result_before_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    unreviewed_path: Path,
) -> None:
    calls = 0

    def command_runner(request: ValidationCommandRequest) -> ValidationCommandResult:
        nonlocal calls
        del request
        calls += 1
        raise AssertionError("unreviewed executable must stop before command 1")

    runner, _, _ = _validation_dependencies(
        tmp_path,
        monkeypatch,
        command_runner=command_runner,
    )

    def bad_resolver(name: str, search_path: str | None) -> Path:
        del search_path
        uv_path = (
            unreviewed_path
            if tool_name == "uv"
            else Path("/opt/homebrew/bin/uv")
        )
        npm_path = (
            unreviewed_path
            if tool_name == "npm"
            else Path("/usr/local/bin/npm")
        )
        if name == "uv":
            return uv_path
        if name == "npm":
            return npm_path
        return npm_path.parent / "node"

    monkeypatch.setattr(runner, "_executable_resolver", bad_resolver)

    with pytest.raises(StudyStateError, match="reviewed executable root"):
        runner.validate_implementation()

    assert calls == 0
    assert not runner.protocol.artifact_root.exists()


def _write_fake_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o700)


def test_production_validation_resolution_ignores_ambient_path_and_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner_module,
        "_verify_pristine_artifact_history",
        lambda *args, **kwargs: None,
    )
    poison_bin = tmp_path / "poison-bin"
    poison_bin.mkdir()
    for name in ("uv", "npm", "node"):
        _write_fake_executable(poison_bin / name)
    monkeypatch.setenv("PATH", poison_bin.as_posix())
    monkeypatch.setenv("HOME", (tmp_path / "poison-home").as_posix())

    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    snapshot = RepositorySnapshot(
        "a" * 40,
        (),
        _projection(protocol.implementation_projection_paths()),
    )
    requests: list[ValidationCommandRequest] = []

    def stop_after_lookup(request: ValidationCommandRequest) -> ValidationCommandResult:
        requests.append(request)
        raise RuntimeError("stop after executable lookup")

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        command_runner=stop_after_lookup,
        repository_state=lambda: snapshot,
        home_directory=tmp_path / "sealed-home",
        temp_directory=tmp_path / "sealed-tmp",
    )

    with pytest.raises(StudyStateError, match="validation command failed"):
        runner.validate_implementation()

    assert len(requests) == 1
    assert requests[0].executable_lookup_path.parent != poison_bin
    assert poison_bin.as_posix() not in requests[0].environment["PATH"].split(":")
    assert not protocol.artifact_root.exists()


def test_reviewed_production_lookup_finds_real_checkout_tools() -> None:
    uv_path = runner_module._validated_lookup_path(
        runner_module._default_executable_resolver(
            "uv",
            _REVIEWED_PRODUCTION_LOOKUP_PATH,
        ),
        expected_name="uv",
    )
    npm_path = runner_module._validated_lookup_path(
        runner_module._default_executable_resolver(
            "npm",
            _REVIEWED_PRODUCTION_LOOKUP_PATH,
        ),
        expected_name="npm",
    )
    runner = _runner(_ACCOUNT_HOME)
    environment = runner._validation_environment(uv_path, npm_path)
    node_path = runner_module._validated_lookup_path(
        runner_module._default_executable_resolver("node", environment["PATH"]),
        expected_name="node",
    )

    assert uv_path == _ACCOUNT_HOME / ".local/bin/uv"
    assert npm_path == Path("/opt/homebrew/bin/npm")
    assert node_path == Path("/opt/homebrew/bin/node")
    assert environment["PATH"] == (
        f"{_ACCOUNT_HOME.as_posix()}/.local/bin:/opt/homebrew/bin:"
        "/usr/bin:/bin:/usr/sbin:/sbin"
    )


@pytest.mark.parametrize("tool_state", ("missing", "unusable"))
def test_production_resolver_fails_closed_for_missing_or_unusable_tool(
    tmp_path: Path,
    tool_state: str,
) -> None:
    lookup_root = tmp_path / "reviewed-bin"
    lookup_root.mkdir()
    if tool_state == "unusable":
        tool = lookup_root / "uv"
        tool.write_text("not executable\n", encoding="utf-8")
        tool.chmod(0o600)

    with pytest.raises(StudyStateError, match="required executable is unavailable"):
        runner_module._default_executable_resolver("uv", lookup_root.as_posix())


def test_phase1_claim_is_reopened_before_first_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = replace(
        load_study_protocol_v2(),
        artifact_root=tmp_path / "artifacts",
    )
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    events: list[str] = []
    state = VerifiedStudyState(
        status=StudyStatus(True, False, False, False, False, "PENDING", ()),
        present_paths=("implementation-validation.json", "retention-audit.json"),
        invalid_paths=(),
        verified_json=cast(
            Mapping[str, VerifiedStudyJson],
            {
                "implementation-validation.json": SimpleNamespace(
                    document={"execution_commit": "a" * 40}
                ),
                "retention-audit.json": SimpleNamespace(document={}),
            },
        ),
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: state)

    def no_op_preflight(*args: object, **kwargs: object) -> RepositorySnapshot:
        del args, kwargs
        return RepositorySnapshot("b" * 40, (), ())

    monkeypatch.setattr(StudyRunner, "_require_mutating_preflight", no_op_preflight)
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )
    original_verify = StudyArtifactStore.verify_json_result

    def observe_verify(
        self: StudyArtifactStore,
        relative_path: str,
        *,
        expected_record_type: str,
    ) -> object:
        if relative_path == "phase-1-execution-claim.json":
            events.append("claim-verified")
        return original_verify(
            self,
            relative_path,
            expected_record_type=expected_record_type,
        )

    monkeypatch.setattr(StudyArtifactStore, "verify_json_result", observe_verify)

    def render(*args: object) -> object:
        del args
        events.append("render")
        raise RuntimeError("stop after callback one")

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        store=store,
        render=cast(DiagnosticRenderer, render),
    )
    try:
        with pytest.raises(RuntimeError, match="callback one"):
            runner.phase1()
    finally:
        store.close()

    assert events == ["claim-verified", "render"]
    assert (protocol.artifact_root / "phase-1-execution-claim.json").is_file()


def test_orphaned_phase1_claim_blocks_rerun_before_render(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    store = StudyArtifactStore(runner.protocol.artifact_root, allowed_root=tmp_path)
    try:
        store.publish_json(
            "phase-1-execution-claim.json",
            begin_phase_execution(
                phase="phase1",
                protocol=runner.protocol,
                execution_commit="a" * 40,
                eligible_modes=(),
            ).as_record(),
        )
    finally:
        store.close()
    renders = 0

    def render(*args: object) -> object:
        nonlocal renders
        del args
        renders += 1
        raise AssertionError("orphaned claim must block rendering")

    runner._render = cast(DiagnosticRenderer, render)

    with pytest.raises(StudyStateError, match="Phase 1"):
        runner.phase1()

    assert renders == 0


def test_phase1_executes_exact_case_major_callback_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    validation = VerifiedStudyJson(
        document=MappingProxyType(
            {
                "execution_commit": "a" * 40,
                "artifact_schema_sha256": "b" * 64,
                "implementation_projection_sha256": "c" * 64,
            }
        ),
        raw_bytes=b"validation",
        raw_sha256="d" * 64,
        record_sha256="e" * 64,
    )
    retention = VerifiedStudyJson(
        document=MappingProxyType({}),
        raw_bytes=b"retention",
        raw_sha256="f" * 64,
        record_sha256="1" * 64,
    )
    state = VerifiedStudyState(
        StudyStatus(True, False, False, False, False, "PENDING", ()),
        ("implementation-validation.json", "retention-audit.json"),
        (),
        MappingProxyType(
            {
                "implementation-validation.json": validation,
                "retention-audit.json": retention,
            }
        ),
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        StudyRunner,
        "_require_mutating_preflight",
        lambda *args, **kwargs: RepositorySnapshot("b" * 40, (), ()),
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_completed_phase",
        lambda *args, **kwargs: None,
    )
    plans = tuple(SimpleNamespace(ordinal=ordinal) for ordinal in range(108))
    events: list[tuple[str, int, str | None]] = []

    def render(plan: object, *args: object) -> object:
        del args
        ordinal = cast(int, cast(SimpleNamespace, plan).ordinal)
        events.append(("render", ordinal, None))
        return SimpleNamespace(
            case_id=f"e1-v2-development-diagnostic-{ordinal:03d}",
            seed=800000 + ordinal,
            expected_outcome="ANOMALY" if ordinal >= 84 else "NORMAL",
            part_id="plate-demo",
            cad_revision="rev-A",
            view_id="front",
            reference_bytes=b"reference",
            inspection_bytes=b"inspection",
            authoritative_mask_bytes=b"mask",
            reference_sha256="2" * 64,
            inspection_sha256="3" * 64,
            authoritative_mask_sha256="4" * 64,
            applied_transform=AppliedAffineTransform(1.01, 0.5, 1.0, -1.0),
            defect_type="scratch" if ordinal >= 84 else None,
            defect_severity="MEDIUM" if ordinal >= 84 else None,
            expected_feature_id="top_face" if ordinal >= 84 else None,
        )

    def normalize(
        reference_bytes: bytes,
        inspection_bytes: bytes,
        *,
        reference_sha256: str,
        inspection_sha256: str,
        applied_transform: AppliedAffineTransform,
        resampling: ResamplingMode,
    ) -> object:
        del reference_bytes, inspection_bytes, reference_sha256, inspection_sha256
        del applied_transform
        ordinal = sum(1 for event in events if event[0] == "render") - 1
        events.append(("normalize", ordinal, resampling.value))
        return SimpleNamespace(mode=resampling)

    def infer(value: object) -> object:
        case, normalized = cast(tuple[object, object], value)
        ordinal = cast(int, cast(SimpleNamespace, case).seed) - 800000
        mode = cast(ResamplingMode, cast(SimpleNamespace, normalized).mode)
        events.append(("inference", ordinal, mode.value))
        return SimpleNamespace(mode=mode)

    monkeypatch.setattr(runner_module, "raw_identity_difference_mask", lambda case: b"id")
    monkeypatch.setattr(
        runner_module,
        "reference_boundary_band",
        lambda payload: SimpleNamespace(
            radius=3,
            foreground_positive_pixels=1,
            boundary_positive_pixels=1,
            band_positive_pixels=1,
            band_mask_sha256="5" * 64,
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "make_truth_free_input",
        lambda case, normalized: (case, normalized),
    )

    def observe(case: object, result: object, *args: object) -> DiagnosticObservation:
        del args
        ordinal = cast(int, cast(SimpleNamespace, case).seed) - 800000
        mode = cast(ResamplingMode, cast(SimpleNamespace, result).mode)
        defect = ordinal >= 84
        return DiagnosticObservation(
            diagnostic_id=cast(str, cast(SimpleNamespace, case).case_id),
            seed=800000 + ordinal,
            mode=mode,
            defect_row=defect,
            medium_high_row=defect,
            actual_outcome="ANOMALY" if defect else "NORMAL",
            identity_recall=1.0,
            study_recall=1.0,
            identity_dice=1.0,
            study_dice=1.0,
            study_iou=1.0,
            total_residual=1 if defect else 0,
            boundary_residual=0,
            outside_boundary_residual=1 if defect else 0,
            record={
                "diagnostic_id": cast(str, cast(SimpleNamespace, case).case_id),
                "seed": 800000 + ordinal,
                "mode": mode.value,
            },
        )

    monkeypatch.setattr(runner_module, "diagnostic_observation", observe)

    def reduce(
        mode: ResamplingMode,
        rows: object,
        gates: object,
    ) -> DiagnosticModeSummary:
        del gates
        checked = cast(list[DiagnosticObservation], rows)
        assert len(checked) == 108
        assert all(row.mode is mode for row in checked)
        return DiagnosticModeSummary(mode, 108, 24, 24, 0.0, 0.0, 1.0, True)

    monkeypatch.setattr(runner_module, "reduce_diagnostic_mode", reduce)
    published_documents: list[dict[str, object]] = []
    original_publish = StudyArtifactStore.publish_json

    def publish(
        self: StudyArtifactStore,
        relative_path: str,
        document: object,
    ) -> StudyArtifactRecord:
        if relative_path == "known-transform-diagnostic-108.json":
            published_documents.append(cast(dict[str, object], document))
            return StudyArtifactRecord(relative_path, "6" * 64, 1, "application/json", "7" * 64)
        return original_publish(self, relative_path, cast(dict[str, object], document))

    monkeypatch.setattr(StudyArtifactStore, "publish_json", publish)
    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        store=store,
        diagnostic_matrix=lambda: cast(tuple[FrozenDiagnosticPlan, ...], plans),
        render=cast(DiagnosticRenderer, render),
        normalize=cast(NormalizeCallback, normalize),
        inference=cast(InferenceRunner, infer),
    )
    try:
        runner.phase1()
    finally:
        store.close()

    assert sum(event[0] == "render" for event in events) == 108
    assert sum(event[0] == "normalize" for event in events) == 324
    assert sum(event[0] == "inference" for event in events) == 324
    assert events[:7] == [
        ("render", 0, None),
        ("normalize", 0, "NEAREST"),
        ("inference", 0, "NEAREST"),
        ("normalize", 0, "BILINEAR"),
        ("inference", 0, "BILINEAR"),
        ("normalize", 0, "BICUBIC"),
        ("inference", 0, "BICUBIC"),
    ]
    assert len(published_documents) == 1


def _fake_development_corpus() -> DevelopmentCorpus:
    cases: list[object] = []
    defect_layouts = {
        ordinal: (cad_revision, view_id)
        for ordinal, (_, _, cad_revision, view_id) in enumerate(
            artifacts_module._frozen_oracle_layout_projection()
        )
    }
    for group, count, start in (
        ("clean", 24, 400000),
        ("nuisance", 30, 410000),
        ("defect", 60, 420000),
        ("trust_boundary", 6, 430000),
    ):
        for ordinal in range(count):
            case_id = f"e1-v2-development-{group}-{ordinal:03d}"
            cad_revision, view_id = (
                defect_layouts[ordinal] if group == "defect" else ("rev-A", "front")
            )
            cases.append(
                SimpleNamespace(
                    case_id=case_id,
                    seed=start + ordinal,
                    group=group,
                    reference_bytes=b"reference",
                    inspection_bytes=b"inspection",
                    authoritative_mask_bytes=b"mask",
                    reference_sha256=sha256(f"{case_id}-reference".encode()).hexdigest(),
                    inspection_sha256=sha256(f"{case_id}-inspection".encode()).hexdigest(),
                    authoritative_mask_sha256=sha256(f"{case_id}-mask".encode()).hexdigest(),
                    case_binding_sha256=sha256(f"{case_id}-binding".encode()).hexdigest(),
                    cad_revision=cad_revision,
                    view_id=view_id,
                    applied_transform=AppliedAffineTransform(1.0, 0.0, 0.0, 0.0),
                    trust_boundary=group == "trust_boundary",
                    expected_feature_id="top_face" if group == "defect" else None,
                )
            )
    return DevelopmentCorpus(
        cases=cast(tuple[StudyTruthCase, ...], tuple(cases)),
        counts={
            "clean": 24,
            "nuisance": 30,
            "defect": 60,
            "trust_boundary": 6,
            "total": 120,
        },
        scope_projection=("development",),
        external_request_count=1,
        internal_membership_validation_count=120,
    )


def _fake_feature_oracle_result(
    protocol: StudyProtocolV2,
    corpus: DevelopmentCorpus,
) -> FeatureOracleResult:
    records: list[dict[str, object]] = []
    for case in corpus.cases:
        if case.group != "defect":
            continue
        cad_revision = getattr(case, "cad_revision", None)
        view_id = getattr(case, "view_id", None)
        layout = (
            f"{cad_revision}/{view_id}"
            if isinstance(cad_revision, str) and isinstance(view_id, str)
            else "rev-A/front"
        )
        records.append(
            {
                "case_id": case.case_id,
                "cad_revision": cad_revision,
                "view_id": view_id,
                "authoritative_mask_sha256": case.authoritative_mask_sha256,
                "authoritative_positive_pixels": 16,
                "expected_feature_id": "top_face",
                "predicted_feature_id": "top_face",
                "status": "MAPPED",
                "correct": True,
                "hash_binding_matches": True,
                "ownership_map_sha256": protocol.ownership_map_hashes[layout],
                "target_owned_pixels": 16,
                "owned_pixel_count": 16,
                "unmapped_pixel_count": 0,
            }
        )
    return FeatureOracleResult(
        60,
        60,
        0,
        0,
        0,
        protocol.ownership_map_hashes,
        tuple(records),
        True,
    )


def _fake_verified(document: dict[str, object]) -> VerifiedStudyJson:
    finalized = finalize_study_record(document)
    raw = runner_module._canonical_json_bytes(finalized)

    def freeze(value: object) -> object:
        if isinstance(value, dict):
            return MappingProxyType({key: freeze(item) for key, item in value.items()})
        if isinstance(value, list):
            return tuple(freeze(item) for item in value)
        return value

    return VerifiedStudyJson(
        document=cast(Mapping[str, object], freeze(finalized)),
        raw_bytes=raw,
        raw_sha256=sha256(raw).hexdigest(),
        record_sha256=cast(str, finalized["record_sha256"]),
    )


def _base_phase_evidence() -> tuple[VerifiedStudyJson, VerifiedStudyJson]:
    validation = _fake_verified(
        {
            "execution_commit": "a" * 40,
            "artifact_schema_sha256": "b" * 64,
            "implementation_projection_sha256": "c" * 64,
        }
    )
    retention = _fake_verified({})
    return validation, retention


def _intercept_publication(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
) -> dict[str, VerifiedStudyJson]:
    published: dict[str, VerifiedStudyJson] = {}

    def publish(
        self: StudyArtifactStore,
        relative_path: str,
        document: Mapping[str, object],
    ) -> StudyArtifactRecord:
        del self
        events.append(f"publish:{relative_path}")
        evidence = _fake_verified(dict(document))
        published[relative_path] = evidence
        return StudyArtifactRecord(
            relative_path,
            evidence.raw_sha256,
            len(evidence.raw_bytes),
            "application/json",
            evidence.record_sha256,
        )

    def verify(
        self: StudyArtifactStore,
        relative_path: str,
        *,
        expected_record_type: str,
    ) -> VerifiedStudyJson:
        del self, expected_record_type
        events.append(f"verify:{relative_path}")
        return published[relative_path]

    monkeypatch.setattr(StudyArtifactStore, "publish_json", publish)
    monkeypatch.setattr(StudyArtifactStore, "verify_json_result", verify)
    monkeypatch.setattr(
        StudyRunner,
        "_require_mutating_preflight",
        lambda *args, **kwargs: RepositorySnapshot("f" * 40, (), ()),
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_completed_phase",
        lambda *args, **kwargs: None,
    )
    return published


def _track_real_publication(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
) -> None:
    publish_json = StudyArtifactStore.publish_json
    verify_json_result = StudyArtifactStore.verify_json_result

    def publish(
        self: StudyArtifactStore,
        relative_path: str,
        document: Mapping[str, object],
    ) -> StudyArtifactRecord:
        events.append(f"publish:{relative_path}")
        return publish_json(self, relative_path, document)

    def verify(
        self: StudyArtifactStore,
        relative_path: str,
        *,
        expected_record_type: str,
    ) -> VerifiedStudyJson:
        events.append(f"verify:{relative_path}")
        return verify_json_result(
            self,
            relative_path,
            expected_record_type=expected_record_type,
        )

    monkeypatch.setattr(StudyArtifactStore, "publish_json", publish)
    monkeypatch.setattr(StudyArtifactStore, "verify_json_result", verify)
    monkeypatch.setattr(
        StudyRunner,
        "_require_mutating_preflight",
        lambda *args, **kwargs: RepositorySnapshot("f" * 40, (), ()),
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )


def _seed_phase2_prerequisite_packet(store: StudyArtifactStore) -> None:
    for relative_path in runner_module._PRE_DECISION_PATHS[:6]:
        (store.root / relative_path).write_bytes(b"verified-prerequisite\n")


def _stored_paths(store: StudyArtifactStore) -> tuple[str, ...]:
    return tuple(entry.path for entry in store.inventory())


def _move_first_oracle_row_to_another_allowed_layout(
    document: dict[str, object],
    protocol: StudyProtocolV2,
) -> None:
    payload = cast(dict[str, object], document["payload"])
    first = cast(list[dict[str, object]], payload["records"])[0]
    ownership_hashes = cast(Mapping[str, str], protocol.ownership_map_hashes)
    current_hash = cast(str, first["ownership_map_sha256"])
    wrong_layout, wrong_hash = next(
        item for item in ownership_hashes.items() if item[1] != current_hash
    )
    first["ownership_map_sha256"] = wrong_hash
    if "cad_revision" in first and "view_id" in first:
        first["cad_revision"], first["view_id"] = wrong_layout.split("/", 1)


def test_feature_oracle_materializes_once_and_never_calls_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    validation, retention = _base_phase_evidence()
    phase1_claim = _fake_verified({})
    diagnostic = _fake_verified({})
    state = VerifiedStudyState(
        StudyStatus(True, True, False, False, False, "PENDING", ()),
        (
            "implementation-validation.json",
            "retention-audit.json",
            "phase-1-execution-claim.json",
            "known-transform-diagnostic-108.json",
        ),
        (),
        MappingProxyType(
            {
                "implementation-validation.json": validation,
                "retention-audit.json": retention,
                "phase-1-execution-claim.json": phase1_claim,
                "known-transform-diagnostic-108.json": diagnostic,
            }
        ),
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: state)
    events: list[str] = []
    published = _intercept_publication(monkeypatch, events)
    corpus = _fake_development_corpus()
    corpus_calls = 0
    oracle_calls = 0

    def load_corpus() -> DevelopmentCorpus:
        nonlocal corpus_calls
        corpus_calls += 1
        events.append("corpus")
        return corpus

    def run_oracle(*args: object) -> FeatureOracleResult:
        nonlocal oracle_calls
        del args
        oracle_calls += 1
        events.append("oracle")
        return _fake_feature_oracle_result(protocol, corpus)

    def forbidden_inference(value: object) -> object:
        del value
        raise AssertionError("feature oracle cannot invoke inference")

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        store=store,
        corpus=load_corpus,
        oracle=cast(OracleRunner, run_oracle),
        inference=cast(InferenceRunner, forbidden_inference),
    )
    try:
        runner.feature_oracle()
    finally:
        store.close()

    assert corpus_calls == 1
    assert oracle_calls == 1
    assert events == [
        "corpus",
        "publish:scope-audit.json",
        "verify:scope-audit.json",
        "oracle",
        "publish:feature-ownership-oracle.json",
    ]
    assert set(published) == {"scope-audit.json", "feature-ownership-oracle.json"}


def test_oracle_generation_rejects_forged_allowed_layout_hash(
    tmp_path: Path,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    corpus = _fake_development_corpus()
    oracle = _fake_feature_oracle_result(protocol, corpus)
    records = [dict(record) for record in oracle.records]
    current_hash = cast(str, records[0]["ownership_map_sha256"])
    wrong_layout, wrong_hash = next(
        item for item in protocol.ownership_map_hashes.items() if item[1] != current_hash
    )
    records[0]["ownership_map_sha256"] = wrong_hash
    if "cad_revision" in records[0] and "view_id" in records[0]:
        records[0]["cad_revision"], records[0]["view_id"] = wrong_layout.split("/", 1)
    forged = FeatureOracleResult(
        oracle.case_count,
        oracle.correct_cases,
        oracle.ambiguous_cases,
        oracle.null_cases,
        oracle.wrong_cases,
        oracle.ownership_hashes,
        tuple(records),
        oracle.passed,
    )

    with pytest.raises(StudyStateError, match=r"oracle.*(layout|ownership|binding)"):
        runner_module._oracle_records(protocol, corpus, forged)


def test_phase2_is_mode_major_with_114_callbacks_per_eligible_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    validation, retention = _base_phase_evidence()
    corpus = _fake_development_corpus()
    bindings = runner_module._development_bindings(corpus)
    evidence = {
        "implementation-validation.json": validation,
        "retention-audit.json": retention,
        "phase-1-execution-claim.json": _fake_verified({}),
        "known-transform-diagnostic-108.json": _fake_verified(
            {"payload": {"eligible_modes": ["NEAREST", "BICUBIC"]}}
        ),
        "scope-audit.json": _fake_verified({"payload": {"bindings": bindings}}),
        "feature-ownership-oracle.json": _fake_verified({}),
    }
    state = VerifiedStudyState(
        StudyStatus(True, True, True, True, False, "PENDING", ()),
        tuple(evidence),
        (),
        MappingProxyType(evidence),
    )
    authorization_events: list[str] = []
    state_reads = 0

    def inspect(*args: object, **kwargs: object) -> VerifiedStudyState:
        nonlocal state_reads
        del args, kwargs
        state_reads += 1
        authorization_events.append("state")
        return state

    monkeypatch.setattr(runner_module, "inspect_state", inspect)
    events: list[tuple[str, str, str]] = []
    published = _intercept_publication(monkeypatch, authorization_events)
    preflight_calls = 0

    def preflight(*args: object, **kwargs: object) -> RepositorySnapshot:
        nonlocal preflight_calls
        del args, kwargs
        preflight_calls += 1
        authorization_events.append("preflight")
        return RepositorySnapshot("f" * 40, (), ())

    monkeypatch.setattr(StudyRunner, "_require_mutating_preflight", preflight)
    protocol_calls = 0
    corpus_calls = 0

    def load_e1_protocol() -> E1V2Protocol:
        nonlocal protocol_calls
        protocol_calls += 1
        authorization_events.append("protocol")
        return runner_module.load_e1_v2_protocol()

    def load_corpus() -> DevelopmentCorpus:
        nonlocal corpus_calls
        corpus_calls += 1
        authorization_events.append("corpus")
        return corpus

    def normalize(*args: object, **kwargs: object) -> object:
        del args
        mode = cast(ResamplingMode, kwargs["resampling"])
        case_id = cast(str, kwargs.pop("case_id", ""))
        del case_id
        return SimpleNamespace(mode=mode)

    monkeypatch.setattr(
        runner_module,
        "make_truth_free_input",
        lambda case, normalized: (case, normalized),
    )

    def infer(value: object) -> object:
        case, normalized = cast(tuple[SimpleNamespace, SimpleNamespace], value)
        events.append(("inference", normalized.mode.value, case.case_id))
        return SimpleNamespace(mode=normalized.mode)

    def observe(case: object, result: object) -> object:
        return SimpleNamespace(case=case, result=result)

    monkeypatch.setattr(runner_module, "observation_from_study", observe)
    monkeypatch.setattr(
        runner_module,
        "_development_inference_record",
        lambda case, mode, result, observation: {
            "case_id": case.case_id,
            "mode": mode.value,
        },
    )

    def reduce(mode: ResamplingMode, rows: object, gates: object) -> DevelopmentModeSummary:
        del gates
        checked = cast(list[object], rows)
        assert len(checked) == 114
        return DevelopmentModeSummary(mode, 120, 114, 6, 1.0, 0.0, 1.0, 1.0, True)

    monkeypatch.setattr(runner_module, "reduce_development_mode", reduce)
    normalize_events: list[tuple[str, str]] = []

    def counting_normalize(
        reference_bytes: bytes,
        inspection_bytes: bytes,
        *,
        reference_sha256: str,
        inspection_sha256: str,
        applied_transform: AppliedAffineTransform,
        resampling: ResamplingMode,
    ) -> object:
        del reference_bytes, inspection_bytes, reference_sha256, inspection_sha256
        del applied_transform
        ordinal = len(normalize_events) % 114
        authorization_events.append("normalize")
        normalize_events.append((resampling.value, corpus.cases[ordinal].case_id))
        return SimpleNamespace(mode=resampling)

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        store=store,
        corpus=load_corpus,
        normalize=cast(NormalizeCallback, counting_normalize),
        inference=cast(InferenceRunner, infer),
        e1_protocol_loader=load_e1_protocol,
    )
    try:
        runner.phase2()
    finally:
        store.close()

    assert state_reads == 2
    assert preflight_calls == 2
    assert protocol_calls == 1
    assert corpus_calls == 1
    assert len(normalize_events) == 228
    assert len(events) == 228
    assert [mode for mode, _ in normalize_events[:114]] == ["NEAREST"] * 114
    assert [mode for mode, _ in normalize_events[114:]] == ["BICUBIC"] * 114
    assert normalize_events[0][1] == "e1-v2-development-clean-000"
    assert normalize_events[113][1] == "e1-v2-development-defect-059"
    assert authorization_events[:9] == [
        "state",
        "preflight",
        "protocol",
        "corpus",
        "state",
        "preflight",
        "publish:phase-2-execution-claim.json",
        "verify:phase-2-execution-claim.json",
        "normalize",
    ]
    assert "known-transform-development-120.json" in published
    payload = cast(
        Mapping[str, object],
        published["known-transform-development-120.json"].document["payload"],
    )
    assert len(cast(tuple[object, ...], payload["trust_bindings"])) == 6


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("case_id", "e1-v2-development-clean-999"),
        ("seed", 999999),
        ("group", "nuisance"),
        ("reference_sha256", sha256(b"changed-reference").hexdigest()),
        ("inspection_sha256", sha256(b"changed-inspection").hexdigest()),
        ("authoritative_mask_sha256", sha256(b"changed-mask").hexdigest()),
        ("case_binding_sha256", sha256(b"changed-binding").hexdigest()),
    ),
)
def test_phase2_rejects_every_scope_binding_drift_before_compute_callback_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad_value: object,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    _seed_phase2_prerequisite_packet(store)
    validation, retention = _base_phase_evidence()
    corpus = _fake_development_corpus()
    bindings = runner_module._development_bindings(corpus)
    mutated_bindings = [dict(binding) for binding in bindings]
    mutated_bindings[0][field] = bad_value
    evidence = {
        "implementation-validation.json": validation,
        "retention-audit.json": retention,
        "phase-1-execution-claim.json": _fake_verified({}),
        "known-transform-diagnostic-108.json": _fake_verified(
            {"payload": {"eligible_modes": ["NEAREST"]}}
        ),
        "scope-audit.json": _fake_verified(
            {"payload": {"bindings": mutated_bindings}}
        ),
        "feature-ownership-oracle.json": _fake_verified({}),
    }
    state = VerifiedStudyState(
        StudyStatus(True, True, True, True, False, "PENDING", ()),
        tuple(evidence),
        (),
        MappingProxyType(evidence),
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: state)
    publication_events: list[str] = []
    _track_real_publication(monkeypatch, publication_events)
    corpus_calls = 0
    normalization_calls = 0
    inference_calls = 0

    def load_corpus() -> DevelopmentCorpus:
        nonlocal corpus_calls
        corpus_calls += 1
        return corpus

    def forbidden_normalize(*args: object, **kwargs: object) -> object:
        nonlocal normalization_calls
        del args, kwargs
        normalization_calls += 1
        raise AssertionError("scope mismatch must stop before normalization/inference")

    def forbidden_inference(*args: object, **kwargs: object) -> object:
        nonlocal inference_calls
        del args, kwargs
        inference_calls += 1
        raise AssertionError("scope mismatch must stop before normalization/inference")

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        store=store,
        corpus=load_corpus,
        normalize=cast(NormalizeCallback, forbidden_normalize),
        inference=cast(InferenceRunner, forbidden_inference),
    )
    try:
        with pytest.raises(StudyStateError, match="corpus does not match"):
            runner.phase2()
        assert corpus_calls == 1
        assert normalization_calls == 0
        assert inference_calls == 0
        assert publication_events == []
        assert not (protocol.artifact_root / "phase-2-execution-claim.json").exists()
        assert frozenset(_stored_paths(store)) == frozenset(
            runner_module._PRE_DECISION_PATHS[:6]
        )
    finally:
        store.close()


def test_phase2_corpus_loader_failure_publishes_nothing_and_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    _seed_phase2_prerequisite_packet(store)
    validation, retention = _base_phase_evidence()
    corpus = _fake_development_corpus()
    bindings = runner_module._development_bindings(corpus)
    evidence = {
        "implementation-validation.json": validation,
        "retention-audit.json": retention,
        "phase-1-execution-claim.json": _fake_verified({}),
        "known-transform-diagnostic-108.json": _fake_verified(
            {"payload": {"eligible_modes": ["NEAREST"]}}
        ),
        "scope-audit.json": _fake_verified({"payload": {"bindings": bindings}}),
        "feature-ownership-oracle.json": _fake_verified({}),
    }
    state = VerifiedStudyState(
        StudyStatus(True, True, True, True, False, "PENDING", ()),
        tuple(evidence),
        (),
        MappingProxyType(evidence),
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: state)
    publication_events: list[str] = []
    _track_real_publication(monkeypatch, publication_events)
    corpus_calls = 0
    inference_calls = 0

    def unavailable_corpus() -> DevelopmentCorpus:
        nonlocal corpus_calls
        corpus_calls += 1
        raise RuntimeError("development corpus unavailable")

    def forbidden_inference(value: object) -> object:
        nonlocal inference_calls
        del value
        inference_calls += 1
        raise AssertionError("corpus authorization failure reached inference")

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        store=store,
        corpus=unavailable_corpus,
        inference=cast(InferenceRunner, forbidden_inference),
    )
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="development corpus unavailable"):
                runner.phase2()
        assert corpus_calls == 2
        assert inference_calls == 0
        assert publication_events == []
        assert not (protocol.artifact_root / "phase-2-execution-claim.json").exists()
        assert frozenset(_stored_paths(store)) == frozenset(
            runner_module._PRE_DECISION_PATHS[:6]
        )
    finally:
        store.close()


@pytest.mark.parametrize("drift", ("execution_commit", "eligible_modes", "scope_binding"))
def test_phase2_rechecks_authorization_state_before_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    _seed_phase2_prerequisite_packet(store)
    validation, retention = _base_phase_evidence()
    corpus = _fake_development_corpus()
    bindings = runner_module._development_bindings(corpus)

    def evidence_packet() -> dict[str, VerifiedStudyJson]:
        return {
            "implementation-validation.json": validation,
            "retention-audit.json": retention,
            "phase-1-execution-claim.json": _fake_verified({}),
            "known-transform-diagnostic-108.json": _fake_verified(
                {"payload": {"eligible_modes": ["NEAREST"]}}
            ),
            "scope-audit.json": _fake_verified({"payload": {"bindings": bindings}}),
            "feature-ownership-oracle.json": _fake_verified({}),
        }

    initial_evidence = evidence_packet()
    refreshed_evidence = evidence_packet()
    if drift == "execution_commit":
        refreshed_evidence["implementation-validation.json"] = _fake_verified(
            {
                "execution_commit": "9" * 40,
                "artifact_schema_sha256": "b" * 64,
                "implementation_projection_sha256": "c" * 64,
            }
        )
    elif drift == "eligible_modes":
        refreshed_evidence["known-transform-diagnostic-108.json"] = _fake_verified(
            {"payload": {"eligible_modes": ["BILINEAR"]}}
        )
    else:
        changed_bindings = [dict(binding) for binding in bindings]
        changed_bindings[0]["case_binding_sha256"] = sha256(
            b"authorization-state-drift"
        ).hexdigest()
        refreshed_evidence["scope-audit.json"] = _fake_verified(
            {"payload": {"bindings": changed_bindings}}
        )

    states = iter(
        (
            VerifiedStudyState(
                StudyStatus(True, True, True, True, False, "PENDING", ()),
                tuple(initial_evidence),
                (),
                MappingProxyType(initial_evidence),
            ),
            VerifiedStudyState(
                StudyStatus(True, True, True, True, False, "PENDING", ()),
                tuple(refreshed_evidence),
                (),
                MappingProxyType(refreshed_evidence),
            ),
        )
    )
    monkeypatch.setattr(runner_module, "inspect_state", lambda *args, **kwargs: next(states))
    publication_events: list[str] = []
    _track_real_publication(monkeypatch, publication_events)
    normalization_calls = 0
    inference_calls = 0

    def forbidden_normalize(*args: object, **kwargs: object) -> object:
        nonlocal normalization_calls
        del args, kwargs
        normalization_calls += 1
        raise AssertionError("authorization drift reached normalization")

    def forbidden_inference(value: object) -> object:
        nonlocal inference_calls
        del value
        inference_calls += 1
        raise AssertionError("authorization drift reached inference")

    runner = StudyRunner(
        protocol,
        repo_root=tmp_path,
        store=store,
        corpus=lambda: corpus,
        normalize=cast(NormalizeCallback, forbidden_normalize),
        inference=cast(InferenceRunner, forbidden_inference),
    )
    try:
        with pytest.raises(StudyStateError, match=r"authorization.*changed"):
            runner.phase2()
        assert normalization_calls == 0
        assert inference_calls == 0
        assert publication_events == []
        assert not (protocol.artifact_root / "phase-2-execution-claim.json").exists()
        assert frozenset(_stored_paths(store)) == frozenset(
            runner_module._PRE_DECISION_PATHS[:6]
        )
    finally:
        store.close()


def _upstream(path: str, evidence: VerifiedStudyJson) -> dict[str, str]:
    return {
        "path": path,
        "raw_sha256": evidence.raw_sha256,
        "record_sha256": evidence.record_sha256,
    }


def _bind_result_envelope(
    document: dict[str, object],
    validation: VerifiedStudyJson,
    upstreams: list[dict[str, str]],
) -> None:
    document["execution_commit"] = validation.document["execution_commit"]
    document["artifact_schema_sha256"] = validation.document[
        "artifact_schema_sha256"
    ]
    document["implementation_projection_sha256"] = validation.document[
        "implementation_projection_sha256"
    ]
    document["upstream_artifacts"] = upstreams


def _bind_reviewed_validation_executables(document: dict[str, object]) -> None:
    payload = cast(dict[str, object], document["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    expected_path = (
        f"{_ACCOUNT_HOME.as_posix()}/.local/bin:/opt/homebrew/bin:"
        "/usr/bin:/bin:/usr/sbin:/sbin"
    )
    for ordinal, command in enumerate(commands):
        command["executable_lookup_path"] = (
            (_ACCOUNT_HOME / ".local/bin/uv").as_posix()
            if ordinal < 4
            else "/opt/homebrew/bin/npm"
        )
        environment = cast(dict[str, object], command["sanitized_environment"])
        environment["PATH"] = expected_path


def _publish_semantic_packet(
    tmp_path: Path,
    *,
    tamper_diagnostic_reduction: bool = False,
    include_decision: bool = True,
    scope_mutation: Callable[[dict[str, object]], None] | None = None,
) -> StudyRunner:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    try:
        validation_document = minimal_valid_implementation_validation_record(protocol)
        _bind_reviewed_validation_executables(validation_document)
        store.publish_json("implementation-validation.json", validation_document)
        validation = store.verify_json_result(
            "implementation-validation.json",
            expected_record_type="implementation_validation",
        )
        for path in (
            "retained-inputs/candidate-a.json",
            "retained-inputs/candidate-b.json",
            "retained-inputs/task-4-report.md",
            "retained-inputs/sdd-progress.md",
        ):
            store.publish_bytes(path, b"retained", media_type="application/octet-stream")

        retention_document = minimal_valid_retention_audit_record(protocol)
        _bind_result_envelope(
            retention_document,
            validation,
            [_upstream("implementation-validation.json", validation)],
        )
        store.publish_json("retention-audit.json", retention_document)
        retention = store.verify_json_result(
            "retention-audit.json",
            expected_record_type="retention_audit",
        )

        phase1_claim_document = begin_phase_execution(
            phase="phase1",
            protocol=protocol,
            execution_commit=cast(str, validation.document["execution_commit"]),
            eligible_modes=(),
        ).as_record()
        store.publish_json("phase-1-execution-claim.json", phase1_claim_document)
        phase1_claim = store.verify_json_result(
            "phase-1-execution-claim.json",
            expected_record_type="phase_execution_claim",
        )

        diagnostic_document = minimal_valid_diagnostic_result_record(protocol)
        plans = runner_module.load_frozen_diagnostic_matrix()
        diagnostic_payload = cast(dict[str, object], diagnostic_document["payload"])
        cases = cast(list[dict[str, object]], diagnostic_payload["cases"])
        for case, plan in zip(cases, plans, strict=True):
            case["cad_revision"] = plan.cad_revision.value
            case["view_id"] = plan.view_id.value
            case["applied_transform"] = {
                "scale_factor": 1.0 + plan.scale_delta,
                "rotation_degrees": plan.rotation_degrees,
                "translation_x": float(plan.translation_x),
                "translation_y": float(plan.translation_y),
            }
            case["defect_type"] = plan.defect_type
            case["defect_severity"] = plan.defect_severity
            case["expected_feature_id"] = plan.expected_feature_id
        if tamper_diagnostic_reduction:
            observations = cast(
                list[dict[str, object]], diagnostic_payload["observations"]
            )
            observations[84 * 3]["study_recall"] = 0.0
        _bind_result_envelope(
            diagnostic_document,
            validation,
            [
                _upstream("retention-audit.json", retention),
                _upstream("phase-1-execution-claim.json", phase1_claim),
            ],
        )
        store.publish_json("known-transform-diagnostic-108.json", diagnostic_document)
        diagnostic = store.verify_json_result(
            "known-transform-diagnostic-108.json",
            expected_record_type="diagnostic_result",
        )

        scope_document = minimal_valid_scope_audit_record(protocol)
        if scope_mutation is not None:
            scope_mutation(scope_document)
        _bind_result_envelope(
            scope_document,
            validation,
            [
                _upstream("retention-audit.json", retention),
                _upstream("known-transform-diagnostic-108.json", diagnostic),
            ],
        )
        store.publish_json("scope-audit.json", scope_document)
        scope = store.verify_json_result(
            "scope-audit.json",
            expected_record_type="scope_audit",
        )

        oracle_document = minimal_valid_feature_oracle_record(protocol)
        _bind_result_envelope(
            oracle_document,
            validation,
            [
                _upstream("scope-audit.json", scope),
                _upstream("known-transform-diagnostic-108.json", diagnostic),
            ],
        )
        store.publish_json("feature-ownership-oracle.json", oracle_document)
        oracle = store.verify_json_result(
            "feature-ownership-oracle.json",
            expected_record_type="feature_oracle",
        )

        eligible = ("NEAREST", "BILINEAR", "BICUBIC")
        phase2_claim_document = begin_phase_execution(
            phase="phase2",
            protocol=protocol,
            execution_commit=cast(str, validation.document["execution_commit"]),
            eligible_modes=eligible,
        ).as_record()
        store.publish_json("phase-2-execution-claim.json", phase2_claim_document)
        phase2_claim = store.verify_json_result(
            "phase-2-execution-claim.json",
            expected_record_type="phase_execution_claim",
        )

        development_document = minimal_valid_development_result_record(
            protocol,
            eligible_modes=eligible,
            passing_modes=eligible,
        )
        development_payload = cast(dict[str, object], development_document["payload"])
        inference_records = cast(
            list[dict[str, object]], development_payload["inference_records"]
        )
        for record in inference_records:
            if record["group"] == "defect":
                ordinal = int(cast(str, record["case_id"]).rsplit("-", 1)[1])
                metrics = cast(dict[str, object], record["metrics"])
                metrics["severity"] = "LOW" if ordinal < 20 else "MEDIUM"
        _bind_result_envelope(
            development_document,
            validation,
            [
                _upstream("retention-audit.json", retention),
                _upstream("known-transform-diagnostic-108.json", diagnostic),
                _upstream("scope-audit.json", scope),
                _upstream("feature-ownership-oracle.json", oracle),
                _upstream("phase-2-execution-claim.json", phase2_claim),
            ],
        )
        store.publish_json(
            "known-transform-development-120.json",
            development_document,
        )
        development = store.verify_json_result(
            "known-transform-development-120.json",
            expected_record_type="development_result",
        )

        if include_decision:
            decision_document = minimal_valid_decision_record(protocol)
            _bind_result_envelope(
                decision_document,
                validation,
                [
                    _upstream("implementation-validation.json", validation),
                    _upstream("retention-audit.json", retention),
                    _upstream("phase-1-execution-claim.json", phase1_claim),
                    _upstream("known-transform-diagnostic-108.json", diagnostic),
                    _upstream("scope-audit.json", scope),
                    _upstream("feature-ownership-oracle.json", oracle),
                    _upstream("phase-2-execution-claim.json", phase2_claim),
                    _upstream("known-transform-development-120.json", development),
                ],
            )
            store.publish_json("decision.json", decision_document)
    finally:
        store.close()
    return StudyRunner(protocol, repo_root=tmp_path)


def test_semantic_inspection_accepts_complete_schema_valid_packet(tmp_path: Path) -> None:
    runner = _publish_semantic_packet(tmp_path)

    status = runner_module.inspect_state(
        runner.protocol,
        repo_root=tmp_path,
    ).status

    assert status.study_valid is True
    assert status.phase1_complete is True
    assert status.feature_oracle_complete is True
    assert status.phase2_authorized is False
    assert status.phase2_complete is True
    assert status.terminal_decision == "TRANSFORM_ESTIMATION_LIMITED"


def test_runtime_store_packet_uses_one_portable_artifact_root_identity(tmp_path: Path) -> None:
    """Catch runner inspection accepting checkout paths mixed with portable result roots."""

    runner = _publish_semantic_packet(tmp_path)
    assert runner.status().study_valid is True
    store = StudyArtifactStore.open_existing(
        runner.protocol.artifact_root,
        allowed_root=tmp_path,
    )
    assert store is not None
    record_types = {
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
    try:
        identities = {
            store.verify_json_result(path, expected_record_type=record_type).document[
                "artifact_root"
            ]
            for path, record_type in record_types.items()
        }
    finally:
        store.close()

    assert runner.protocol.artifact_root_identity == (
        "docs/evaluation/results/e1-feasibility-study"
    )
    assert identities == {runner.protocol.artifact_root_identity}


def test_semantic_inspection_recomputes_diagnostic_reduction(tmp_path: Path) -> None:
    runner = _publish_semantic_packet(tmp_path, tamper_diagnostic_reduction=True)

    status = runner.status()

    assert status.study_valid is False
    assert status.terminal_decision == "STUDY_INVALID"
    assert status.reasons == ("ARTIFACT_VERIFICATION_FAILED",)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("member_count", 119),
        ("group_counts.clean", 23),
        ("group_counts.nuisance", 29),
        ("group_counts.defect", 59),
        ("group_counts.trust_boundary", 5),
        ("group_counts.total", 119),
        ("scope_projection", []),
        ("external_request_count", 2),
        ("internal_membership_validation_count", 119),
        ("protected_emission_count", 1),
        ("legacy_v1_planning_caveat", "REAUTHORED"),
        ("passed", False),
    ),
)
def test_scope_store_rejects_every_fixed_payload_constant_mutation(
    tmp_path: Path,
    field: str,
    bad_value: object,
) -> None:
    protocol = replace(load_study_protocol_v2(), artifact_root=tmp_path / "artifacts")
    document = minimal_valid_scope_audit_record(protocol)
    payload = cast(dict[str, object], document["payload"])
    if field.startswith("group_counts."):
        group = field.rsplit(".", 1)[1]
        cast(dict[str, object], payload["group_counts"])[group] = bad_value
    else:
        payload[field] = bad_value
    store = StudyArtifactStore(protocol.artifact_root, allowed_root=tmp_path)
    try:
        with pytest.raises(StudyArtifactError, match="schema"):
            store.publish_json("scope-audit.json", document)
        assert store.inventory() == ()
    finally:
        store.close()


def _remove_later_phase_evidence(runner: StudyRunner) -> None:
    for relative in (
        "phase-2-execution-claim.json",
        "known-transform-development-120.json",
        "decision.json",
    ):
        (runner.protocol.artifact_root / relative).unlink()


def test_status_rejects_coherent_wrong_oracle_layout_without_generic_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _publish_semantic_packet(tmp_path)
    _remove_later_phase_evidence(runner)
    oracle_path = runner.protocol.artifact_root / "feature-ownership-oracle.json"
    oracle_document = cast(dict[str, object], json.loads(oracle_path.read_bytes()))
    _move_first_oracle_row_to_another_allowed_layout(oracle_document, runner.protocol)
    oracle_path.write_bytes(
        runner_module._canonical_json_bytes(finalize_study_record(oracle_document))
    )
    monkeypatch.setattr(
        artifacts_module,
        "_validate_oracle_semantics",
        lambda payload: None,
    )

    status = runner.status()

    assert status.study_valid is False
    assert status.terminal_decision == "STUDY_INVALID"
    assert status.reasons == ("ARTIFACT_VERIFICATION_FAILED",)


def test_scope_defect_mask_reauthoring_is_rejected_against_existing_oracle(
    tmp_path: Path,
) -> None:
    def mutate(document: dict[str, object]) -> None:
        payload = cast(dict[str, object], document["payload"])
        bindings = cast(list[dict[str, object]], payload["bindings"])
        bindings[54]["authoritative_mask_sha256"] = sha256(
            b"reauthored-defect-mask"
        ).hexdigest()

    runner = _publish_semantic_packet(tmp_path, scope_mutation=mutate)
    _remove_later_phase_evidence(runner)

    status = runner.status()

    assert status.study_valid is False
    assert status.terminal_decision == "STUDY_INVALID"
    assert status.reasons == ("ARTIFACT_VERIFICATION_FAILED",)


def test_scope_case_bindings_must_be_unique_before_phase2(
    tmp_path: Path,
) -> None:
    def mutate(document: dict[str, object]) -> None:
        payload = cast(dict[str, object], document["payload"])
        bindings = cast(list[dict[str, object]], payload["bindings"])
        bindings[1]["case_binding_sha256"] = bindings[0]["case_binding_sha256"]

    runner = _publish_semantic_packet(tmp_path, scope_mutation=mutate)
    _remove_later_phase_evidence(runner)

    status = runner.status()

    assert status.study_valid is False
    assert status.terminal_decision == "STUDY_INVALID"
    assert status.reasons == ("ARTIFACT_VERIFICATION_FAILED",)


def test_status_rejects_local_trace_hash_contradiction_in_diagnostic_packet(
    tmp_path: Path,
) -> None:
    runner = _publish_semantic_packet(tmp_path)
    _remove_later_phase_evidence(runner)
    diagnostic_path = runner.protocol.artifact_root / "known-transform-diagnostic-108.json"
    document = cast(dict[str, object], json.loads(diagnostic_path.read_bytes()))
    payload = cast(dict[str, object], document["payload"])
    observation = cast(list[dict[str, object]], payload["observations"])[0]
    inference = cast(dict[str, object], observation["inference_trace"])
    inference["predicted_mask_sha256"] = sha256(b"forged-diagnostic-mask").hexdigest()
    diagnostic_path.write_bytes(
        runner_module._canonical_json_bytes(finalize_study_record(document))
    )

    status = runner.status()

    assert status.study_valid is False
    assert status.terminal_decision == "STUDY_INVALID"
    assert status.reasons == ("ARTIFACT_VERIFICATION_FAILED",)


def test_status_and_verify_use_read_only_verifiers_without_execution_seams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _publish_semantic_packet(tmp_path)
    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        calls.append("called")
        raise AssertionError("read-only inspection invoked an execution seam")

    monkeypatch.setattr(
        runner_module,
        "verify_implementation_validation",
        lambda *args, **kwargs: calls.append("validation") or SimpleNamespace(),
    )
    monkeypatch.setattr(
        runner_module,
        "verify_retention_audit",
        lambda *args, **kwargs: calls.append("retention")
        or SimpleNamespace(evidence_commit="f" * 40),
    )
    monkeypatch.setattr(
        runner_module,
        "_verify_git_lineage",
        lambda *args, **kwargs: calls.append("git") or "f" * 40,
    )

    runner = StudyRunner(
        published.protocol,
        repo_root=tmp_path,
        command_runner=cast(CommandRunner, forbidden),
        executable_resolver=cast(runner_module.ExecutableResolver, forbidden),
        normalize=cast(NormalizeCallback, forbidden),
        diagnostic_matrix=cast(runner_module.DiagnosticMatrixLoader, forbidden),
        render=cast(DiagnosticRenderer, forbidden),
        corpus=cast(runner_module.CorpusLoader, forbidden),
        oracle=cast(OracleRunner, forbidden),
        inference=cast(InferenceRunner, forbidden),
        e1_protocol_loader=cast(Callable[[], E1V2Protocol], forbidden),
    )

    status = runner.status()
    report = runner.verify()

    assert status.terminal_decision == "TRANSFORM_ESTIMATION_LIMITED"
    assert report.status == status
    assert calls == [
        "validation",
        "retention",
        "git",
        "validation",
        "retention",
        "git",
    ]


def test_status_and_verify_reject_forged_validation_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_retention_fixture(tmp_path, monkeypatch)
    try:
        validation_path = fixture.protocol.artifact_root / "implementation-validation.json"
        document = cast(dict[str, object], json.loads(validation_path.read_bytes()))
        payload = cast(dict[str, object], document["payload"])
        commands = cast(list[dict[str, object]], payload["commands"])
        commands[0]["argv"] = ["uv", "run", "pytest", "-q", "tests/forged-validation.py"]
        validation_path.write_bytes(
            runner_module._canonical_json_bytes(finalize_study_record(document))
        )

        runner = StudyRunner(fixture.protocol, repo_root=fixture.repo_root)

        status = runner.status()
        report = runner.verify()

        assert status.study_valid is False
        assert status.phase2_authorized is False
        assert status.terminal_decision == "STUDY_INVALID"
        assert report.status == status
        assert report.verify_rate == 0.0
    finally:
        fixture.store.close()


def test_status_and_verify_allow_dirty_artifact_root_for_new_retention_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_retention_fixture(tmp_path, monkeypatch)
    try:
        run_retention_audit(
            fixture.protocol,
            fixture.store,
            execution_commit=fixture.execution_commit,
            repo_root=fixture.repo_root,
        )
        runner = StudyRunner(fixture.protocol, repo_root=fixture.repo_root)

        status = runner.status()
        report = runner.verify()

        assert status.study_valid is True
        assert status.phase1_complete is False
        assert status.phase2_authorized is False
        assert status.terminal_decision == "PENDING"
        assert report.status == status
    finally:
        fixture.store.close()


def test_status_and_verify_reject_mutated_retained_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_retention_fixture(tmp_path, monkeypatch)
    try:
        run_retention_audit(
            fixture.protocol,
            fixture.store,
            execution_commit=fixture.execution_commit,
            repo_root=fixture.repo_root,
        )
        (fixture.protocol.artifact_root / "retained-inputs/candidate-a.json").write_bytes(
            b'{"candidate":"A","outcome":"FORGED"}'
        )
        runner = StudyRunner(fixture.protocol, repo_root=fixture.repo_root)

        status = runner.status()
        report = runner.verify()

        assert status.study_valid is False
        assert status.phase2_authorized is False
        assert status.terminal_decision == "STUDY_INVALID"
        assert report.status == status
        assert report.verify_rate == 0.0
    finally:
        fixture.store.close()


def test_finalize_rejects_pending_without_creating_artifacts(tmp_path: Path) -> None:
    runner = _runner(tmp_path, root_name="missing-artifacts")

    with pytest.raises(StudyStateError, match="PENDING"):
        runner.finalize()

    assert not runner.protocol.artifact_root.exists()


def test_finalize_publishes_decision_before_deterministic_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _publish_semantic_packet(tmp_path, include_decision=False)
    snapshot = RepositorySnapshot(
        "f" * 40,
        (),
        _projection(runner.protocol.implementation_projection_paths()),
    )
    monkeypatch.setattr(runner, "_repository_state", lambda: snapshot)
    monkeypatch.setattr(
        StudyRunner,
        "_require_finalization_preflight",
        lambda *args, **kwargs: snapshot,
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )

    published = runner.finalize()

    assert published.path == "decision.json"
    assert runner.protocol.artifact_root.joinpath("decision.json").is_file()
    assert runner.protocol.artifact_root.joinpath("report.md").is_file()
    assert runner.status().terminal_decision == "TRANSFORM_ESTIMATION_LIMITED"
    first_report = runner.protocol.artifact_root.joinpath("report.md").read_bytes()

    repeated = runner.finalize()

    assert repeated.record_sha256 == published.record_sha256
    assert runner.protocol.artifact_root.joinpath("report.md").read_bytes() == first_report


def test_finalize_seals_semantically_invalid_packet_with_honest_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _publish_semantic_packet(
        tmp_path,
        tamper_diagnostic_reduction=True,
        include_decision=False,
    )
    before = runner.verify()
    assert before.status.terminal_decision == "STUDY_INVALID"
    snapshot = RepositorySnapshot(
        "f" * 40,
        (),
        _projection(runner.protocol.implementation_projection_paths()),
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_finalization_preflight",
        lambda *args, **kwargs: snapshot,
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )
    publications: list[str] = []
    original_publish_json = StudyArtifactStore.publish_json
    original_publish_bytes = StudyArtifactStore.publish_bytes

    def publish_json(
        store: StudyArtifactStore,
        relative_path: str,
        document: Mapping[str, object],
    ) -> StudyArtifactRecord:
        publications.append(f"json:{relative_path}")
        return original_publish_json(store, relative_path, document)

    def publish_bytes(
        store: StudyArtifactStore,
        relative_path: str,
        payload: bytes,
        *,
        media_type: str,
    ) -> StudyArtifactRecord:
        publications.append(f"bytes:{relative_path}")
        return original_publish_bytes(
            store,
            relative_path,
            payload,
            media_type=media_type,
        )

    monkeypatch.setattr(StudyArtifactStore, "publish_json", publish_json)
    monkeypatch.setattr(StudyArtifactStore, "publish_bytes", publish_bytes)

    published = runner.finalize()

    assert publications == [
        "json:decision.json",
        "bytes:decision.json",
        "bytes:report.md",
    ]
    store = StudyArtifactStore.open_existing(
        runner.protocol.artifact_root,
        allowed_root=tmp_path,
    )
    assert store is not None
    try:
        decision = store.verify_json_result(
            "decision.json",
            expected_record_type="decision",
        )
        report = store.read_bytes("report.md").decode("utf-8")
    finally:
        store.close()
    payload = cast(Mapping[str, object], decision.document["payload"])
    present_paths = cast(tuple[str, ...], payload["present_paths"])
    invalid_paths = cast(tuple[str, ...], payload["invalid_paths"])
    assert payload["decision"] == "STUDY_INVALID"
    assert payload["verified_artifact_count"] == 0
    assert payload["present_artifact_count"] == 8
    assert payload["study_artifact_verify_rate"] == 0.0
    assert invalid_paths == present_paths
    assert "Verified artifacts: 0/8 (0.0)" in report
    assert f"Invalid artifacts: {', '.join(invalid_paths)}" in report

    after = runner.verify()
    assert after.status.terminal_decision == "STUDY_INVALID"
    assert "decision.json" in after.verified_paths
    assert "report.md" in after.verified_paths
    publication_count = len(publications)

    repeated = runner.finalize()

    assert repeated.record_sha256 == published.record_sha256
    assert len(publications) == publication_count


def test_finalize_seals_orphaned_phase1_claim_with_verified_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _publish_semantic_packet(tmp_path, include_decision=False)
    for relative in (
        "known-transform-diagnostic-108.json",
        "scope-audit.json",
        "feature-ownership-oracle.json",
        "phase-2-execution-claim.json",
        "known-transform-development-120.json",
    ):
        (runner.protocol.artifact_root / relative).unlink()
    snapshot = RepositorySnapshot(
        "f" * 40,
        (),
        _projection(runner.protocol.implementation_projection_paths()),
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_finalization_preflight",
        lambda *args, **kwargs: snapshot,
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )

    published = runner.finalize()

    assert published.path == "decision.json"
    store = StudyArtifactStore.open_existing(
        runner.protocol.artifact_root,
        allowed_root=tmp_path,
    )
    assert store is not None
    try:
        decision = store.verify_json_result(
            "decision.json",
            expected_record_type="decision",
        )
    finally:
        store.close()
    payload = cast(Mapping[str, object], decision.document["payload"])
    assert payload["decision"] == "STUDY_INVALID"
    assert payload["verified_artifact_count"] == 2
    assert payload["present_artifact_count"] == 3
    assert cast(float, payload["study_artifact_verify_rate"]) == pytest.approx(2 / 3)
    assert payload["invalid_paths"] == ("phase-1-execution-claim.json",)
    assert runner.status().terminal_decision == "STUDY_INVALID"

    repeated = runner.finalize()

    assert repeated.record_sha256 == published.record_sha256


@pytest.mark.parametrize(
    "case",
    ("scope_oracle_orphan", "phase2_orphan", "partial_retention"),
)
def test_finalize_seals_other_safely_inspectable_relationship_invalid_packets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    runner = _publish_semantic_packet(tmp_path, include_decision=False)
    if case == "scope_oracle_orphan":
        for relative in (
            "feature-ownership-oracle.json",
            "phase-2-execution-claim.json",
            "known-transform-development-120.json",
        ):
            (runner.protocol.artifact_root / relative).unlink()
    elif case == "phase2_orphan":
        (runner.protocol.artifact_root / "known-transform-development-120.json").unlink()
    else:
        (runner.protocol.artifact_root / "retained-inputs/candidate-a.json").unlink()

    snapshot = RepositorySnapshot(
        "f" * 40,
        (),
        _projection(runner.protocol.implementation_projection_paths()),
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_finalization_preflight",
        lambda *args, **kwargs: snapshot,
    )
    monkeypatch.setattr(
        StudyRunner,
        "_require_phase_publication_state",
        lambda *args, **kwargs: None,
    )

    before = runner.verify()
    assert before.status.terminal_decision == "STUDY_INVALID"

    published = runner.finalize()

    assert published.path == "decision.json"
    assert runner.protocol.artifact_root.joinpath("report.md").is_file()
    assert runner.status().terminal_decision == "STUDY_INVALID"
