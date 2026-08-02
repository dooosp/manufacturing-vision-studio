from __future__ import annotations

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
        "artifact_root": protocol.artifact_root.as_posix(),
        "artifact_schema_sha256": sha256_bytes(
            (repo_root / "schemas/e1-feasibility-study-artifact.v1.json").read_bytes()
        ),
        "implementation_projection_sha256": projection_sha256,
        "upstream_artifacts": [],
        "payload": {
            "worktree_clean": True,
            "commands": [
                {
                    "name": name,
                    "argv": list(argv),
                    "exit_code": 0,
                    "stdout_sha256": sha256_bytes(f"{name}-stdout".encode()),
                    "stderr_sha256": sha256_bytes(f"{name}-stderr".encode()),
                    "started_at_utc": "2026-08-01T00:00:00Z",
                    "ended_at_utc": "2026-08-01T00:00:01Z",
                }
                for name, argv in EXPECTED_COMMANDS
            ],
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
    cast(dict[str, object], document["paths"])["artifact_root"] = "artifacts"
    cast(dict[str, object], document["paths"])["raw_data_root"] = "raw"
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
        "verify_e1_v1_history",
        lambda: {"verdict": "HOLD", "artifact_count": 9},
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
    retention_fixture: RetentionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retention_module,
        "verify_e1_v1_history",
        lambda: {"verdict": "HOLD", "artifact_count": 8},
    )

    with pytest.raises(StudyRetentionError, match="nine"):
        verify_historical_hold(
            retention_fixture.protocol,
            repo_root=retention_fixture.repo_root,
        )


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
