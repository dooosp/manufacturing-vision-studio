from __future__ import annotations

import inspect
import json
import os
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.e1 import study_artifacts_v2 as artifacts_module
from manufacturing_vision_studio.e1.study_artifacts_v2 import (
    STUDY_ARTIFACT_SCHEMA_PATH,
    StudyArtifactError,
    StudyArtifactStore,
    StudyGateRecord,
    begin_phase_execution,
    finalize_study_record,
    load_strict_json_object,
    validate_study_schema,
    verify_self_hash,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    StudyProtocolV2,
    load_study_protocol_v2,
)

ZERO_SHA256 = "0" * 64
EXECUTION_COMMIT = "a" * 40
EXPECTED_CLAIM_FIELDS = {
    "artifact_root",
    "base_commit",
    "development_only",
    "execution_commit",
    "payload",
    "protocol_sha256",
    "record_sha256",
    "record_type",
    "release_claim_allowed",
    "schema_version",
    "selection_eligible",
    "study_id",
}
EXPECTED_PAYLOAD_FIELDS = {
    "expected_inference_rows_per_mode",
    "expected_members",
    "expected_mode_count",
    "expected_modes",
    "phase",
    "trust_binding_rows",
}

EXPECTED_VALIDATION_COMMANDS = (
    ("ruff", ["uv", "run", "ruff", "check", "."]),
    ("mypy", ["uv", "run", "mypy", "src"]),
    ("v0_1_regression", ["uv", "run", "pytest", "-q", "tests/test_e1_baseline.py"]),
    ("pytest", ["uv", "run", "pytest", "-q"]),
    ("web_check", ["npm", "--prefix", "web", "run", "check"]),
    ("playwright", ["npm", "--prefix", "web", "run", "test:e2e"]),
)
EXPECTED_VALIDATION_TIMEOUTS = (300, 300, 600, 1800, 600, 900)
EXPECTED_VALIDATION_EXECUTABLE_LOOKUP_PATHS = (
    "/opt/e1-study/uv/bin/uv",
    "/opt/e1-study/uv/bin/uv",
    "/opt/e1-study/uv/bin/uv",
    "/opt/e1-study/uv/bin/uv",
    "/opt/e1-study/npm/bin/npm",
    "/opt/e1-study/npm/bin/npm",
)
EXPECTED_SANITIZED_ENVIRONMENT = {
    "HOME": "/tmp/e1-study-home",
    "PATH": "/opt/e1-study/uv/bin:/opt/e1-study/npm/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    "TMPDIR": "/tmp/e1-study",
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
EXPECTED_NOT_APPLICABLE_CONTROLS = (
    ("bundle_verify_reimport_rate", "STUDY_PUBLISHES_NO_BUNDLE"),
    ("dataset_split_hash_overlap", "PROTECTED_SPLIT_MEMBERS_NOT_ENUMERATED"),
    ("same_seed_manifest_equivalence", "FULL_TWO_RUN_EQUIVALENCE_NOT_AUTHORIZED"),
    ("revision_mismatch_publication_count", "STUDY_HAS_NO_RUNTIME_PUBLICATION_PATH"),
    ("corrupted_evidence_publication_count", "STUDY_HAS_NO_RUNTIME_PUBLICATION_PATH"),
)


def _nonzero_sha(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def _task_7a_validation_command_audit_metadata(ordinal: int) -> dict[str, object]:
    return {
        "executable_lookup_path": EXPECTED_VALIDATION_EXECUTABLE_LOOKUP_PATHS[ordinal],
        "cwd": ".",
        "shell": False,
        "timeout_seconds": EXPECTED_VALIDATION_TIMEOUTS[ordinal],
        "output_limit_bytes": 4_194_304,
        "timed_out": False,
        "stdout_byte_count": 0,
        "stderr_byte_count": 0,
        "sanitized_environment": dict(EXPECTED_SANITIZED_ENVIRONMENT),
    }


def _task_7a_add_validation_command_audit_metadata(record: dict[str, object]) -> None:
    payload = cast(dict[str, object], record["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    for ordinal, command in enumerate(commands):
        command.update(_task_7a_validation_command_audit_metadata(ordinal))


def _task_7a_set_validation_executable_contract(
    record: dict[str, object],
    *,
    uv_lookup_path: str,
    npm_lookup_path: str,
    environment_path: str,
) -> None:
    payload = cast(dict[str, object], record["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    for ordinal, command in enumerate(commands):
        command["executable_lookup_path"] = (
            uv_lookup_path if ordinal < 4 else npm_lookup_path
        )
        environment = cast(dict[str, object], command["sanitized_environment"])
        environment["PATH"] = environment_path


def minimal_valid_implementation_validation_record(
    protocol: StudyProtocolV2,
) -> dict[str, object]:
    command_records = [
        {
            "name": name,
            "argv": argv,
            "exit_code": 0,
            "stdout_sha256": _nonzero_sha(f"{name}-stdout"),
            "stderr_sha256": _nonzero_sha(f"{name}-stderr"),
            "started_at_utc": "2026-08-01T00:00:00Z",
            "ended_at_utc": "2026-08-01T00:00:01Z",
            **_task_7a_validation_command_audit_metadata(ordinal),
        }
        for ordinal, (name, argv) in enumerate(EXPECTED_VALIDATION_COMMANDS)
    ]
    controls = [
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
        for name, reason in EXPECTED_NOT_APPLICABLE_CONTROLS
    ]
    mode_hashes = {mode: _nonzero_sha(mode) for mode in ("NEAREST", "BILINEAR", "BICUBIC")}
    return {
        "record_type": "implementation_validation",
        "schema_version": "1.0.0",
        "study_id": "e1-feasibility-separability",
        "development_only": True,
        "selection_eligible": False,
        "release_claim_allowed": False,
        "base_commit": protocol.base_commit,
        "execution_commit": EXECUTION_COMMIT,
        "protocol_sha256": protocol.configuration_sha256,
        "artifact_root": protocol.artifact_root_identity,
        "artifact_schema_sha256": _nonzero_sha("artifact-schema"),
        "implementation_projection_sha256": _nonzero_sha("implementation-projection"),
        "upstream_artifacts": [],
        "payload": {
            "worktree_clean": True,
            "commands": command_records,
            "determinism_control": {
                "first_projection": mode_hashes,
                "second_projection": dict(mode_hashes),
                "passed": True,
            },
            "not_applicable_controls": controls,
            "passed": True,
        },
        "record_sha256": ZERO_SHA256,
    }


def minimal_valid_retention_audit_record(
    protocol: StudyProtocolV2,
) -> dict[str, object]:
    projection = [{"path": "Makefile", "sha256": _nonzero_sha("Makefile")}]
    projection_sha256 = canonical_json_hash(projection)
    retained = [
        ("candidate_a", "retained-inputs/candidate-a.json"),
        ("candidate_b", "retained-inputs/candidate-b.json"),
        ("task_4_report", "retained-inputs/task-4-report.md"),
        ("sdd_progress", "retained-inputs/sdd-progress.md"),
    ]
    return {
        "record_type": "retention_audit",
        "schema_version": "1.0.0",
        "study_id": "e1-feasibility-separability",
        "development_only": True,
        "selection_eligible": False,
        "release_claim_allowed": False,
        "base_commit": protocol.base_commit,
        "execution_commit": EXECUTION_COMMIT,
        "evidence_commit": "b" * 40,
        "protocol_sha256": protocol.configuration_sha256,
        "artifact_root": protocol.artifact_root_identity,
        "artifact_schema_sha256": _nonzero_sha("artifact-schema"),
        "implementation_projection_sha256": projection_sha256,
        "upstream_artifacts": [
            {
                "path": "implementation-validation.json",
                "raw_sha256": _nonzero_sha("validation-raw"),
                "record_sha256": _nonzero_sha("validation-record"),
            }
        ],
        "payload": {
            "history": {
                "selection_raw_sha256": protocol.source_hashes["selection_raw_sha256"],
                "selection_record_sha256": protocol.source_hashes[
                    "selection_record_sha256"
                ],
                "outcome": "HOLD",
                "selected_candidate_id": None,
                "v1_history_outcome": "HOLD",
                "v1_history_artifact_count": 9,
            },
            "retained_inputs": [
                {
                    "name": name,
                    "path": path,
                    "source_sha256": _nonzero_sha(name),
                    "copied_sha256": _nonzero_sha(name),
                    "byte_size": 1,
                }
                for name, path in retained
            ],
            "implementation_projection": projection,
            "dependency_report": {
                "edges": [],
                "forbidden_direct_edges": [],
                "protected_scope_references": [],
                "projection_sha256": projection_sha256,
                "direct_import_allowlist": {
                    name: list(imports)
                    for name, imports in protocol.direct_import_allowlist().items()
                },
            },
            "seed_disjointness": {
                "diagnostic_seed_start": 800000,
                "diagnostic_seed_end": 800107,
                "diagnostic_seed_count": 108,
                "declared_evaluation_seed_count": 528,
                "overlap_count": 0,
                "overlap_seeds": [],
            },
            "classifications": {
                "Retain": [
                    "development diagnostic matrix",
                    "split guards",
                    "canonical metric calculations",
                    "truth-erasing runtime input",
                    "final-mask ownership mapping",
                    "v1 history verification",
                    "Task 4 negative evidence",
                ],
                "Isolate": [
                    "Candidate A/B search and normalization",
                    "candidate ranking",
                    "candidate selection loader",
                    "candidate work caps",
                    "candidate-specific benchmarking and constants",
                ],
                "Re-review": [
                    "candidate-coupled protocol fields",
                    "legacy development-template planning",
                    "ownership assumptions",
                    "any source whose change would invalidate the historical "
                    "implementation projection",
                ],
            },
            "passed": True,
        },
        "record_sha256": ZERO_SHA256,
    }


@pytest.fixture(scope="module")
def protocol() -> StudyProtocolV2:
    return load_study_protocol_v2()


def minimal_valid_execution_claim_record(
    protocol: StudyProtocolV2,
    *,
    phase: str = "phase1",
) -> dict[str, object]:
    eligible_modes = () if phase == "phase1" else ("NEAREST", "BICUBIC")
    claim = begin_phase_execution(
        phase=cast(Literal["phase1", "phase2"], phase),
        protocol=protocol,
        execution_commit=EXECUTION_COMMIT,
        eligible_modes=eligible_modes,
    )
    return claim.as_record()


def _write_direct(root: Path, relative_path: str, payload: bytes) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _published_document(
    store: StudyArtifactStore,
    protocol: StudyProtocolV2,
    relative_path: str = "claim.json",
) -> dict[str, object]:
    store.publish_json(relative_path, minimal_valid_execution_claim_record(protocol))
    return load_strict_json_object(store.read_bytes(relative_path))


def _store_with_replaced_lexical_path(
    tmp_path: Path,
    *,
    replacement: Literal["ancestor", "root"],
    nested: bool,
) -> tuple[StudyArtifactStore, Path, Path, str, str]:
    allowed = tmp_path / "allowed"
    root = allowed / "artifacts"
    outside_root = tmp_path / "outside" / "artifacts"
    root.mkdir(parents=True)
    outside_root.mkdir(parents=True)
    store = StudyArtifactStore(root, allowed_root=allowed)
    read_path = "nested/read.bin" if nested else "read.bin"
    write_path = "nested/write.bin" if nested else "write.bin"
    store.publish_bytes(read_path, b"trusted", media_type="application/octet-stream")

    if replacement == "ancestor":
        pinned_allowed = tmp_path / "pinned-allowed"
        allowed.rename(pinned_allowed)
        allowed.symlink_to(tmp_path / "outside", target_is_directory=True)
        pinned_root = pinned_allowed / "artifacts"
    else:
        pinned_root = allowed / "pinned-artifacts"
        root.rename(pinned_root)
        root.symlink_to(outside_root, target_is_directory=True)

    outside_read = outside_root / read_path
    outside_read.parent.mkdir(parents=True, exist_ok=True)
    outside_read.write_bytes(b"untrusted")
    (outside_root / write_path).parent.mkdir(parents=True, exist_ok=True)
    return store, pinned_root, outside_root, read_path, write_path


def test_phase_1_execution_claim_binds_exact_contract(protocol: StudyProtocolV2) -> None:
    claim = begin_phase_execution(
        phase="phase1",
        protocol=protocol,
        execution_commit=EXECUTION_COMMIT,
        eligible_modes=(),
    )

    assert claim.phase == "phase1"
    assert claim.execution_commit == EXECUTION_COMMIT
    assert claim.protocol_sha256 == protocol.configuration_sha256
    assert claim.artifact_root == protocol.artifact_root_identity
    assert claim.expected_members == 108
    assert claim.expected_modes == ("NEAREST", "BILINEAR", "BICUBIC")
    assert claim.expected_mode_count == 3
    assert claim.expected_inference_rows_per_mode == 108
    assert claim.trust_binding_rows == 0
    record = claim.as_record()
    assert set(record) == EXPECTED_CLAIM_FIELDS
    assert record["record_sha256"] == ZERO_SHA256
    assert record["record_type"] == "phase_execution_claim"
    assert record["schema_version"] == "1.0.0"
    assert record["study_id"] == "e1-feasibility-separability"
    assert record["development_only"] is True
    assert record["selection_eligible"] is False
    assert record["release_claim_allowed"] is False
    assert record["base_commit"] == protocol.base_commit
    assert set(cast(dict[str, object], record["payload"])) == EXPECTED_PAYLOAD_FIELDS


def test_execution_claim_keeps_portable_identity_when_runtime_root_is_replaced(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    """Catch a claim that records its active checkout path instead of portable identity."""

    runtime_protocol = replace(protocol, artifact_root=tmp_path / "artifacts")

    claim = begin_phase_execution(
        phase="phase1",
        protocol=runtime_protocol,
        execution_commit=EXECUTION_COMMIT,
        eligible_modes=(),
    )

    assert runtime_protocol.artifact_root_identity == (
        "docs/evaluation/results/e1-feasibility-study"
    )
    assert claim.artifact_root == runtime_protocol.artifact_root_identity


def test_phase_2_execution_claim_binds_exact_eligible_subset(
    protocol: StudyProtocolV2,
) -> None:
    claim = begin_phase_execution(
        phase="phase2",
        protocol=protocol,
        execution_commit="b" * 40,
        eligible_modes=("NEAREST", "BICUBIC"),
    )

    assert claim.expected_members == 120
    assert claim.expected_modes == ("NEAREST", "BICUBIC")
    assert claim.expected_mode_count == 2
    assert claim.expected_inference_rows_per_mode == 114
    assert claim.trust_binding_rows == 6


@pytest.mark.parametrize(
    "phase,eligible_modes,error",
    [
        ("phase1", ("NEAREST",), "phase1.*eligible"),
        ("phase2", (), "phase2.*nonempty"),
        ("phase2", ("NEAREST", "NEAREST"), "duplicate"),
        ("phase2", ("BICUBIC", "NEAREST"), "protocol order"),
        ("phase2", ("NEAREST", "LANCZOS"), "protocol mode"),
    ],
)
def test_execution_claim_rejects_invalid_mode_sets(
    protocol: StudyProtocolV2,
    phase: str,
    eligible_modes: tuple[str, ...],
    error: str,
) -> None:
    with pytest.raises(StudyArtifactError, match=error):
        begin_phase_execution(
            phase=cast(Literal["phase1", "phase2"], phase),
            protocol=protocol,
            execution_commit=EXECUTION_COMMIT,
            eligible_modes=eligible_modes,
        )


@pytest.mark.parametrize("execution_commit", ["a" * 39, "A" * 40, "g" * 40, ""])
def test_execution_claim_rejects_noncanonical_commit_sha(
    protocol: StudyProtocolV2,
    execution_commit: str,
) -> None:
    with pytest.raises(StudyArtifactError, match="execution commit"):
        begin_phase_execution(
            phase="phase1",
            protocol=protocol,
            execution_commit=execution_commit,
            eligible_modes=(),
        )


def test_execution_claim_blocks_rerun_under_same_protocol_and_root(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    claim = begin_phase_execution(
        phase="phase1",
        protocol=protocol,
        execution_commit=EXECUTION_COMMIT,
        eligible_modes=(),
    )
    first = store.publish_json("phase-1-execution-claim.json", claim.as_record())

    with pytest.raises(StudyArtifactError, match="immutable"):
        store.publish_json("phase-1-execution-claim.json", claim.as_record())

    assert store.read_bytes(first.path) == canonical_json_bytes(
        finalize_study_record(claim.as_record())
    )
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_publication_surface_has_no_replacement_option() -> None:
    assert "replace" not in inspect.signature(StudyArtifactStore.publish_json).parameters
    assert "replace" not in inspect.signature(StudyArtifactStore.publish_bytes).parameters


def test_not_applicable_gate_is_never_serialized_as_pass() -> None:
    gate = StudyGateRecord(
        name="bundle_verify_reimport_rate",
        status="NOT_APPLICABLE",
        numerator=None,
        denominator=None,
        observed=None,
        operator=None,
        threshold=None,
        reason="STUDY_PUBLISHES_NO_BUNDLE",
    )

    assert gate.status == "NOT_APPLICABLE"
    assert gate.observed is None
    assert gate.as_record() == {
        "name": "bundle_verify_reimport_rate",
        "status": "NOT_APPLICABLE",
        "numerator": None,
        "denominator": None,
        "observed": None,
        "operator": None,
        "threshold": None,
        "reason": "STUDY_PUBLISHES_NO_BUNDLE",
    }


@pytest.mark.parametrize(
    "override",
    [
        {"numerator": 1},
        {"denominator": 1},
        {"observed": 1.0},
        {"operator": "eq"},
        {"threshold": 1.0},
    ],
)
def test_not_applicable_gate_rejects_every_observation_field(
    override: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "name": "bundle_verify_reimport_rate",
        "status": "NOT_APPLICABLE",
        "numerator": None,
        "denominator": None,
        "observed": None,
        "operator": None,
        "threshold": None,
        "reason": "STUDY_PUBLISHES_NO_BUNDLE",
    }
    values.update(override)

    with pytest.raises(ValueError, match="cannot carry"):
        StudyGateRecord(**cast(Any, values))


def test_gate_requires_reason_or_applicable_observation() -> None:
    with pytest.raises(ValueError, match="requires a fixed reason"):
        StudyGateRecord(
            "bundle_verify_reimport_rate",
            "NOT_APPLICABLE",
            None,
            None,
            None,
            None,
            None,
            None,
        )
    with pytest.raises(ValueError, match="applicable gate requires"):
        StudyGateRecord("recall", "PASS", 9, 10, None, "ge", 0.9, None)


def test_canonical_study_json_has_no_trailing_newline(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path, allowed_root=tmp_path)
    record = store.publish_json("record.json", minimal_valid_execution_claim_record(protocol))
    payload = (tmp_path / record.path).read_bytes()

    assert payload == canonical_json_bytes(json.loads(payload))
    assert not payload.endswith(b"\n")
    assert record.sha256 == sha256_bytes(payload)
    assert record.byte_size == len(payload)
    assert record.media_type == "application/json"
    assert record.record_sha256 == cast(dict[str, object], json.loads(payload))["record_sha256"]


def test_verify_json_checks_canonical_schema_type_and_self_hash(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    expected = finalize_study_record(minimal_valid_execution_claim_record(protocol))
    store.publish_json("claim.json", expected)

    assert store.verify_json("claim.json", expected_record_type="phase_execution_claim") == expected
    with pytest.raises(StudyArtifactError, match="record type"):
        store.verify_json("claim.json", expected_record_type="retention_audit")


def test_verify_json_rejects_changed_body_with_stale_self_hash(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    document = _published_document(store, protocol)
    payload = cast(dict[str, object], document["payload"])
    payload["expected_members"] = 120
    _write_direct(tmp_path, "claim.json", canonical_json_bytes(document))

    with pytest.raises(StudyArtifactError, match="self-hash"):
        store.verify_json("claim.json", expected_record_type="phase_execution_claim")


def test_verify_json_rejects_internally_wrong_self_hash(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    document = _published_document(store, protocol)
    document["record_sha256"] = "f" * 64
    _write_direct(tmp_path, "claim.json", canonical_json_bytes(document))

    with pytest.raises(StudyArtifactError, match="self-hash"):
        store.verify_json("claim.json", expected_record_type="phase_execution_claim")


def test_verify_json_rejects_noncanonical_bytes(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    document = finalize_study_record(minimal_valid_execution_claim_record(protocol))
    pretty = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    _write_direct(tmp_path, "claim.json", pretty)

    with pytest.raises(StudyArtifactError, match="canonical"):
        store.verify_json("claim.json", expected_record_type="phase_execution_claim")


def test_strict_reader_rejects_duplicate_keys(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    payload = canonical_json_bytes(
        finalize_study_record(minimal_valid_execution_claim_record(protocol))
    )
    duplicated = payload.replace(
        b'"record_type":"phase_execution_claim"',
        b'"record_type":"phase_execution_claim","record_type":"phase_execution_claim"',
        1,
    )
    assert duplicated != payload
    _write_direct(tmp_path, "claim.json", duplicated)

    with pytest.raises(StudyArtifactError, match=r"duplicate|malformed"):
        store.verify_json("claim.json", expected_record_type="phase_execution_claim")


@pytest.mark.parametrize("nonfinite", [b"NaN", b"Infinity", b"-Infinity", b"1e999"])
def test_strict_reader_rejects_every_nonfinite_number(
    tmp_path: Path,
    nonfinite: bytes,
) -> None:
    store = StudyArtifactStore(tmp_path)
    _write_direct(tmp_path, "claim.json", b'{"value":' + nonfinite + b"}")

    with pytest.raises(StudyArtifactError, match=r"finite|malformed"):
        store.verify_json("claim.json", expected_record_type="phase_execution_claim")


def test_publish_json_wraps_nonfinite_input_as_artifact_error(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    document = minimal_valid_execution_claim_record(protocol)
    cast(dict[str, object], document["payload"])["expected_members"] = float("nan")

    with pytest.raises(StudyArtifactError, match="finite"):
        store.publish_json("claim.json", document)


def test_schema_is_closed_at_envelope_and_payload(
    protocol: StudyProtocolV2,
) -> None:
    valid = finalize_study_record(minimal_valid_execution_claim_record(protocol))
    validate_study_schema(valid)

    envelope_extra = deepcopy(valid)
    envelope_extra["implementation_projection_sha256"] = "0" * 64
    envelope_extra = finalize_study_record(envelope_extra)
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(envelope_extra)

    payload_extra = deepcopy(valid)
    cast(dict[str, object], payload_extra["payload"])["upstream_artifacts"] = []
    payload_extra = finalize_study_record(payload_extra)
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(payload_extra)


def test_schema_preserves_the_task_6_variants(
    protocol: StudyProtocolV2,
) -> None:
    schema = load_strict_json_object(STUDY_ARTIFACT_SCHEMA_PATH.read_bytes())
    definitions = cast(dict[str, object], schema["$defs"])
    assert {
        "phaseExecutionClaim",
        "implementationValidation",
        "retentionAudit",
    }.issubset(definitions)

    wrong_variant = minimal_valid_execution_claim_record(protocol)
    wrong_variant["record_type"] = "retention_audit"
    wrong_variant = finalize_study_record(wrong_variant)
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(wrong_variant)


@pytest.mark.parametrize(
    "builder",
    [minimal_valid_implementation_validation_record, minimal_valid_retention_audit_record],
)
def test_task_6_schema_variants_are_closed_at_envelope_and_payload(
    protocol: StudyProtocolV2,
    builder: Any,
) -> None:
    valid = finalize_study_record(builder(protocol))
    validate_study_schema(valid)

    envelope_extra = deepcopy(valid)
    envelope_extra["unexpected"] = True
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(envelope_extra))

    payload_extra = deepcopy(valid)
    cast(dict[str, object], payload_extra["payload"])["unexpected"] = True
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(payload_extra))


def test_task_7a_fix1_validation_command_audit_contract_accepts_closed_metadata(
    protocol: StudyProtocolV2,
) -> None:
    record = minimal_valid_implementation_validation_record(protocol)
    _task_7a_add_validation_command_audit_metadata(record)

    validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize(
    "variant",
    [
        "missing_environment_key",
        "extra_environment_key",
        "poisoned_fixed_environment",
        "relative_home",
        "control_tmpdir",
        "path_suffix",
        "cwd",
        "shell",
        "timeout",
        "output_limit",
        "timed_out",
        "stdout_overflow",
        "stderr_overflow",
    ],
)
def test_task_7a_fix1_validation_command_audit_contract_rejects_schema_tamper(
    protocol: StudyProtocolV2,
    variant: str,
) -> None:
    record = minimal_valid_implementation_validation_record(protocol)
    _task_7a_add_validation_command_audit_metadata(record)
    payload = cast(dict[str, object], record["payload"])
    command = cast(list[dict[str, object]], payload["commands"])[0]
    environment = cast(dict[str, object], command["sanitized_environment"])
    if variant == "missing_environment_key":
        environment.pop("HOME")
    elif variant == "extra_environment_key":
        environment["PYTEST_ADDOPTS"] = "-x"
    elif variant == "poisoned_fixed_environment":
        environment["LANG"] = "en_US.UTF-8"
    elif variant == "relative_home":
        environment["HOME"] = "relative/home"
    elif variant == "control_tmpdir":
        environment["TMPDIR"] = "/tmp/e1\npoisoned"
    elif variant == "path_suffix":
        environment["PATH"] = "/opt/e1-study/bin"
    elif variant == "cwd":
        command["cwd"] = "/tmp"
    elif variant == "shell":
        command["shell"] = True
    elif variant == "timeout":
        command["timeout_seconds"] = 301
    elif variant == "output_limit":
        command["output_limit_bytes"] = 1024
    elif variant == "timed_out":
        command["timed_out"] = True
    elif variant == "stdout_overflow":
        command["stdout_byte_count"] = 4_194_305
    else:
        command["stderr_byte_count"] = 4_194_305

    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(record))


def test_task_7a_fix2_schema_rejects_unbound_validation_path_prefix(
    protocol: StudyProtocolV2,
) -> None:
    record = minimal_valid_implementation_validation_record(protocol)
    _task_7a_add_validation_command_audit_metadata(record)
    payload = cast(dict[str, object], record["payload"])
    commands = cast(list[dict[str, object]], payload["commands"])
    for command in commands:
        environment = cast(dict[str, object], command["sanitized_environment"])
        current_path = environment["PATH"]
        assert isinstance(current_path, str)
        environment["PATH"] = f"/tmp/evil-bin:{current_path}"

    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize(
    ("uv_lookup_path", "npm_lookup_path", "environment_path"),
    [
        (
            "/opt/e1-uv/bin/uv",
            "/opt/e1-node/bin/npm",
            "/opt/e1-uv/bin:/opt/e1-node/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ),
        (
            "/opt/e1-tools/bin/uv",
            "/opt/e1-tools/bin/npm",
            "/opt/e1-tools/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ),
        (
            "/Users/study/.local/bin/uv",
            "/opt/homebrew/bin/npm",
            "/Users/study/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ),
    ],
    ids=("distinct-parents", "same-parent", "homebrew-lexical-path"),
)
def test_task_7a_fix2_schema_accepts_closed_executable_lookup_contract(
    protocol: StudyProtocolV2,
    uv_lookup_path: str,
    npm_lookup_path: str,
    environment_path: str,
) -> None:
    record = minimal_valid_implementation_validation_record(protocol)
    _task_7a_add_validation_command_audit_metadata(record)
    _task_7a_set_validation_executable_contract(
        record,
        uv_lookup_path=uv_lookup_path,
        npm_lookup_path=npm_lookup_path,
        environment_path=environment_path,
    )

    validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize(
    ("variant", "lookup_path"),
    [
        ("missing", None),
        ("extra", "/opt/e1-study/uv/bin/uv"),
        ("empty", ""),
        ("relative", "opt/e1-study/uv/bin/uv"),
        ("control", "/opt/e1-study/uv\n/bin/uv"),
        ("colon", "/opt/e1-study:shadow/uv"),
        ("empty-component", "/opt/e1-study//bin/uv"),
        ("dot-component", "/opt/e1-study/./bin/uv"),
        ("dot-dot-component", "/opt/e1-study/tools/../bin/uv"),
    ],
)
def test_task_7a_fix2_schema_rejects_unsafe_executable_lookup_path(
    protocol: StudyProtocolV2,
    variant: str,
    lookup_path: str | None,
) -> None:
    record = minimal_valid_implementation_validation_record(protocol)
    _task_7a_add_validation_command_audit_metadata(record)
    payload = cast(dict[str, object], record["payload"])
    command = cast(list[dict[str, object]], payload["commands"])[0]
    if variant == "missing":
        command.pop("executable_lookup_path")
    elif variant == "extra":
        command["canonical_executable_path"] = lookup_path
    else:
        command["executable_lookup_path"] = lookup_path

    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(record))


def test_task_6_upstream_items_are_closed_and_validation_has_none(
    protocol: StudyProtocolV2,
) -> None:
    validation = minimal_valid_implementation_validation_record(protocol)
    validation["upstream_artifacts"] = [
        {
            "path": "unexpected.json",
            "raw_sha256": _nonzero_sha("raw"),
            "record_sha256": _nonzero_sha("record"),
        }
    ]
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(validation))

    retention = minimal_valid_retention_audit_record(protocol)
    upstream = cast(list[dict[str, object]], retention["upstream_artifacts"])[0]
    upstream["unexpected"] = True
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(retention))


def test_schema_rejects_phase_contract_drift(protocol: StudyProtocolV2) -> None:
    for key, value in (
        ("expected_members", 107),
        ("expected_modes", ["NEAREST", "BILINEAR"]),
        ("expected_mode_count", 2),
        ("expected_inference_rows_per_mode", 107),
        ("trust_binding_rows", 1),
    ):
        document = minimal_valid_execution_claim_record(protocol)
        cast(dict[str, object], document["payload"])[key] = value
        document = finalize_study_record(document)
        with pytest.raises(StudyArtifactError, match="schema"):
            validate_study_schema(document)


def test_finalize_is_defensive_and_verify_self_hash_is_exact(
    protocol: StudyProtocolV2,
) -> None:
    source = minimal_valid_execution_claim_record(protocol)
    source_copy = deepcopy(source)
    finalized = finalize_study_record(source)

    assert source == source_copy
    assert finalized is not source
    assert finalized["record_sha256"] == canonical_json_hash(
        {key: value for key, value in finalized.items() if key != "record_sha256"}
    )
    verify_self_hash(finalized)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "",
        ".",
        "./claim.json",
        "../claim.json",
        "nested/../claim.json",
        "nested//claim.json",
        "/absolute/claim.json",
        "nested\\claim.json",
        "nul\x00claim.json",
        "line\nclaim.json",
    ],
)
def test_store_rejects_unsafe_relative_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    store = StudyArtifactStore(tmp_path)

    with pytest.raises(StudyArtifactError, match="unsafe"):
        store.publish_bytes(unsafe_path, b"payload", media_type="text/plain")


def test_store_rejects_root_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"

    with pytest.raises(StudyArtifactError, match="escapes allowed root"):
        StudyArtifactStore(outside, allowed_root=allowed)


def test_store_rejects_symlink_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(StudyArtifactError, match="symlink"):
        StudyArtifactStore(linked, allowed_root=tmp_path)


def test_store_rejects_symlink_parent_on_write(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    store = StudyArtifactStore(root, allowed_root=tmp_path)

    with pytest.raises(StudyArtifactError, match="symlink"):
        store.publish_bytes("linked/escape.txt", b"payload", media_type="text/plain")
    assert not (outside / "escape.txt").exists()


def test_store_rejects_final_symlink_on_read_and_write(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    outside.write_bytes(b"outside")
    (root / "claim.txt").symlink_to(outside)
    store = StudyArtifactStore(root, allowed_root=tmp_path)

    with pytest.raises(StudyArtifactError, match="symlink"):
        store.read_bytes("claim.txt")
    with pytest.raises(StudyArtifactError, match="symlink"):
        store.publish_bytes("claim.txt", b"payload", media_type="text/plain")
    assert outside.read_bytes() == b"outside"


@pytest.mark.parametrize("replacement", ["ancestor", "root"])
@pytest.mark.parametrize("nested", [False, True], ids=["flat", "nested"])
def test_store_read_stays_pinned_after_lexical_path_is_replaced_by_symlink(
    tmp_path: Path,
    replacement: Literal["ancestor", "root"],
    nested: bool,
) -> None:
    store, _, _, read_path, _ = _store_with_replaced_lexical_path(
        tmp_path,
        replacement=replacement,
        nested=nested,
    )

    assert store.read_bytes(read_path) == b"trusted"


@pytest.mark.parametrize("replacement", ["ancestor", "root"])
@pytest.mark.parametrize("nested", [False, True], ids=["flat", "nested"])
def test_store_write_stays_pinned_after_lexical_path_is_replaced_by_symlink(
    tmp_path: Path,
    replacement: Literal["ancestor", "root"],
    nested: bool,
) -> None:
    store, pinned_root, outside_root, _, write_path = _store_with_replaced_lexical_path(
        tmp_path,
        replacement=replacement,
        nested=nested,
    )

    record = store.publish_bytes(
        write_path,
        b"trusted-write",
        media_type="application/octet-stream",
    )

    assert record.path == write_path
    assert (pinned_root / write_path).read_bytes() == b"trusted-write"
    assert not (outside_root / write_path).exists()


def test_store_fails_closed_after_its_pinned_root_descriptor_is_closed(
    tmp_path: Path,
) -> None:
    store = StudyArtifactStore(tmp_path)
    store.publish_bytes("read.bin", b"trusted", media_type="application/octet-stream")

    store.close()
    store.close()

    with pytest.raises(StudyArtifactError, match="closed"):
        store.read_bytes("read.bin")
    with pytest.raises(StudyArtifactError, match="closed"):
        store.publish_bytes("write.bin", b"blocked", media_type="application/octet-stream")
    assert not (tmp_path / "write.bin").exists()


def test_store_enforces_bounded_writes_and_reads(tmp_path: Path) -> None:
    write_root = tmp_path / "write"
    write_store = StudyArtifactStore(write_root, max_artifact_bytes=4)
    with pytest.raises(StudyArtifactError, match="byte limit"):
        write_store.publish_bytes("large.bin", b"12345", media_type="application/octet-stream")
    assert not (write_root / "large.bin").exists()

    read_root = tmp_path / "read"
    read_store = StudyArtifactStore(read_root, max_artifact_bytes=4)
    (read_root / "large.bin").write_bytes(b"12345")
    with pytest.raises(StudyArtifactError, match="byte limit"):
        read_store.read_bytes("large.bin")


def test_publish_bytes_is_exclusive_and_preserves_original(tmp_path: Path) -> None:
    store = StudyArtifactStore(tmp_path)
    first = store.publish_bytes("evidence.bin", b"first", media_type="application/octet-stream")

    with pytest.raises(StudyArtifactError, match="immutable"):
        store.publish_bytes("evidence.bin", b"second", media_type="application/octet-stream")

    assert store.read_bytes(first.path) == b"first"
    assert first.record_sha256 is None
    assert first.sha256 == sha256_bytes(b"first")
    assert first.byte_size == 5
    assert not [name for name in os.listdir(tmp_path) if name.endswith(".tmp")]


def test_task_7a_contract_registers_exactly_eight_closed_variants() -> None:
    schema = load_strict_json_object(STUDY_ARTIFACT_SCHEMA_PATH.read_bytes())

    assert schema["oneOf"] == [
        {"$ref": "#/$defs/phaseExecutionClaim"},
        {"$ref": "#/$defs/implementationValidation"},
        {"$ref": "#/$defs/retentionAudit"},
        {"$ref": "#/$defs/scopeAudit"},
        {"$ref": "#/$defs/diagnosticResult"},
        {"$ref": "#/$defs/featureOracle"},
        {"$ref": "#/$defs/developmentResult"},
        {"$ref": "#/$defs/decision"},
    ]


def test_task_7a_open_existing_missing_root_is_pristine_and_no_create(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing" / "artifacts"

    store = StudyArtifactStore.open_existing(root, allowed_root=tmp_path)

    assert store is None
    assert not root.exists()


def test_task_7a_verified_json_result_exposes_one_read_evidence(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    expected = finalize_study_record(minimal_valid_execution_claim_record(protocol))
    published = store.publish_json("claim.json", expected)

    verified = store.verify_json_result(
        "claim.json",
        expected_record_type="phase_execution_claim",
    )

    assert verified.raw_bytes == canonical_json_bytes(expected)
    assert verified.raw_sha256 == published.sha256
    assert verified.record_sha256 == expected["record_sha256"]
    assert verified.document["record_type"] == expected["record_type"]
    assert store.verify_json(
        "claim.json", expected_record_type="phase_execution_claim"
    ) == expected


TASK_7A_OWNERSHIP_HASHES = {
    "rev-A/front": "eadc490b04f8240e8356b3e20e75db08d79dfc5e27af180574d707836b3b776f",
    "rev-A/oblique_left": "2d2a52ecae44ccae98455180211aaf528078707948dbf83f792223c550d3a074",
    "rev-A/oblique_right": "8c42a88c3ffdf3dda10b073665b6d7a565ddde54a7a7450ba3c0f4782be14477",
    "rev-B/front": "5f69348a9ce7b646054dce02f95a0ff8ebd420c641ab40f414b0afa645ef49bc",
    "rev-B/oblique_left": "1fb2f752d738a7bf595f8cae97860452a3a8628ea5cb3eec4347d1f42fe43b8b",
    "rev-B/oblique_right": "373337ec46da320dbbcdf0ffa14c22794db05208cd9491e5b272e0d34169830d",
}
TASK_7A_PRE_DECISION_PATHS = (
    "implementation-validation.json",
    "retention-audit.json",
    "phase-1-execution-claim.json",
    "known-transform-diagnostic-108.json",
    "scope-audit.json",
    "feature-ownership-oracle.json",
    "phase-2-execution-claim.json",
    "known-transform-development-120.json",
)


def _task_7a_upstream(path: str) -> dict[str, object]:
    return {
        "path": path,
        "raw_sha256": _nonzero_sha(f"{path}-raw"),
        "record_sha256": _nonzero_sha(f"{path}-record"),
    }


def _task_7a_result_record(
    protocol: StudyProtocolV2,
    *,
    record_type: str,
    upstream_paths: tuple[str, ...],
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "record_type": record_type,
        "schema_version": "1.0.0",
        "study_id": "e1-feasibility-separability",
        "development_only": True,
        "selection_eligible": False,
        "release_claim_allowed": False,
        "base_commit": protocol.base_commit,
        "execution_commit": EXECUTION_COMMIT,
        "protocol_sha256": protocol.configuration_sha256,
        "artifact_root": protocol.artifact_root_identity,
        "artifact_schema_sha256": _nonzero_sha("task-7a-artifact-schema"),
        "implementation_projection_sha256": _nonzero_sha("task-7a-projection"),
        "upstream_artifacts": [_task_7a_upstream(path) for path in upstream_paths],
        "payload": payload,
        "record_sha256": ZERO_SHA256,
    }


def _task_7a_development_binding(group: str, ordinal: int) -> dict[str, object]:
    starts = {
        "clean": 400000,
        "nuisance": 410000,
        "defect": 420000,
        "trust_boundary": 430000,
    }
    case_id = f"e1-v2-development-{group}-{ordinal:03d}"
    return {
        "case_id": case_id,
        "seed": starts[group] + ordinal,
        "group": group,
        "reference_sha256": _nonzero_sha(f"{case_id}-reference"),
        "inspection_sha256": _nonzero_sha(f"{case_id}-inspection"),
        "authoritative_mask_sha256": _nonzero_sha(f"{case_id}-mask"),
        "case_binding_sha256": _nonzero_sha(f"{case_id}-binding"),
    }


def _task_7a_development_bindings() -> list[dict[str, object]]:
    return [
        _task_7a_development_binding(group, ordinal)
        for group, count in (
            ("clean", 24),
            ("nuisance", 30),
            ("defect", 60),
            ("trust_boundary", 6),
        )
        for ordinal in range(count)
    ]


def minimal_valid_scope_audit_record(
    protocol: StudyProtocolV2,
) -> dict[str, object]:
    return _task_7a_result_record(
        protocol,
        record_type="scope_audit",
        upstream_paths=("retention-audit.json", "known-transform-diagnostic-108.json"),
        payload={
            "member_count": 120,
            "bindings": _task_7a_development_bindings(),
            "group_counts": {
                "clean": 24,
                "nuisance": 30,
                "defect": 60,
                "trust_boundary": 6,
                "total": 120,
            },
            "scope_projection": ["development"],
            "external_request_count": 1,
            "internal_membership_validation_count": 120,
            "protected_emission_count": 0,
            "legacy_v1_planning_caveat": (
                "LEGACY_V1_FULL_TEMPLATES_FILTERED_TO_V2_DEVELOPMENT_ONLY"
            ),
            "passed": True,
        },
    )


def _task_7a_applied_transform(*, identity: bool = False) -> dict[str, object]:
    return {
        "scale_factor": 1.0 if identity else 1.01,
        "rotation_degrees": 0.0 if identity else 0.5,
        "translation_x": 0.0 if identity else 1.0,
        "translation_y": 0.0 if identity else -1.0,
    }


def _task_7a_alignment_objective(value: float) -> dict[str, object]:
    return {
        "value": value,
        "silhouette_xor_rate": value,
        "normalized_edge_mae": value,
        "foreground_iou": 1.0 - value,
    }


def _task_7a_transform_trace(mode: str, label: str) -> dict[str, object]:
    return {
        "applied": True,
        "applied_transform": _task_7a_applied_transform(),
        "coefficients": {"a": 1.0, "b": 0.0, "c": 0.0, "d": 0.0, "e": 1.0, "f": 0.0},
        "correction": {"dx": -1.0, "dy": 1.0, "rotation_degrees": -0.5, "scale": 0.99},
        "fill_rgb": [240, 240, 240],
        "normalized_sha256": _nonzero_sha(f"{label}-normalized"),
        "objective_after": _task_7a_alignment_objective(0.01),
        "objective_before": _task_7a_alignment_objective(0.02),
        "reference_sha256": _nonzero_sha(f"{label}-reference"),
        "resampling": mode,
        "source_inspection_sha256": _nonzero_sha(f"{label}-inspection"),
    }


def _task_7a_inference_trace(mode: str, label: str) -> dict[str, object]:
    predicted_mask_sha256 = _nonzero_sha(f"{label}-predicted-mask")
    return {
        "actual_outcome": "ANOMALY",
        "anomaly_score": 0.8,
        "feature_mapping": {
            "predicted_feature_id": "top_face",
            "status": "MAPPED",
            "reason": "FEATURE_OWNERSHIP_WINNER",
            "owner_pixel_counts": {
                "bottom_edge": 0,
                "hole_left": 0,
                "hole_right": 0,
                "top_edge": 0,
                "top_face": 16,
            },
            "owned_pixel_count": 16,
            "winner_owned_pixel_count": 16,
            "final_positive_pixel_count": 16,
            "unmapped_pixel_count": 0,
            "winner_margin": "1.00000000",
            "final_mask_sha256": predicted_mask_sha256,
            "ownership_map_sha256": TASK_7A_OWNERSHIP_HASHES["rev-A/front"],
        },
        "global_anomaly_score": 0.1,
        "mask_postprocessing": {
            "algorithm": "structural_residue_filter_v2",
            "removed_component_count": 0,
            "removed_pixel_count": 0,
            "filtered_mask_sha256": predicted_mask_sha256,
        },
        "model_registration": {"dx": 0, "dy": 0, "mean_absolute_error": 0.0},
        "predicted_mask_sha256": predicted_mask_sha256,
        "registered_inspection_sha256": _nonzero_sha(f"{label}-registered"),
        "source_hashes": {
            "inspection_sha256": _nonzero_sha(f"{label}-inspection"),
            "normalized_inspection_sha256": _nonzero_sha(f"{label}-normalized"),
            "reference_sha256": _nonzero_sha(f"{label}-reference"),
        },
        "transform_trace": _task_7a_transform_trace(mode, label),
    }


def _task_7a_applicable_gate(
    name: str,
    *,
    status: str,
    numerator: int | None,
    denominator: int,
    exclusions: int,
    observed: float,
    operator: str,
    threshold: float,
) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "numerator": numerator,
        "denominator": denominator,
        "exclusions": exclusions,
        "observed": observed,
        "operator": operator,
        "threshold": threshold,
        "reason": None,
    }


def _task_7a_diagnostic_case(ordinal: int) -> dict[str, object]:
    diagnostic_id = f"e1-v2-development-diagnostic-{ordinal:03d}"
    defect = ordinal >= 84
    return {
        "diagnostic_id": diagnostic_id,
        "seed": 800000 + ordinal,
        "expected_outcome": "ANOMALY" if defect else "NORMAL",
        "part_id": "plate-demo",
        "cad_revision": "rev-A" if ordinal % 2 == 0 else "rev-B",
        "view_id": "front",
        "reference_sha256": _nonzero_sha(f"{diagnostic_id}-reference"),
        "inspection_sha256": _nonzero_sha(f"{diagnostic_id}-inspection"),
        "authoritative_mask_sha256": _nonzero_sha(f"{diagnostic_id}-mask"),
        "applied_transform": _task_7a_applied_transform(),
        "defect_type": "scratch" if defect else None,
        "defect_severity": "MEDIUM" if defect else None,
        "expected_feature_id": "top_face" if defect else None,
    }


def _task_7a_diagnostic_observation(ordinal: int, mode: str) -> dict[str, object]:
    diagnostic_id = f"e1-v2-development-diagnostic-{ordinal:03d}"
    label = f"{diagnostic_id}-{mode}"
    defect = ordinal >= 84
    inference_trace = _task_7a_inference_trace(mode, label)
    source_hashes = cast(dict[str, object], inference_trace["source_hashes"])
    source_hashes["reference_sha256"] = _nonzero_sha(f"{diagnostic_id}-reference")
    source_hashes["inspection_sha256"] = _nonzero_sha(f"{diagnostic_id}-inspection")
    transform_trace = cast(dict[str, object], inference_trace["transform_trace"])
    transform_trace["reference_sha256"] = source_hashes["reference_sha256"]
    transform_trace["source_inspection_sha256"] = source_hashes["inspection_sha256"]
    return {
        "diagnostic_id": diagnostic_id,
        "seed": 800000 + ordinal,
        "mode": mode,
        "defect_row": defect,
        "medium_high_row": defect,
        "authoritative_mask_sha256": _nonzero_sha(f"{diagnostic_id}-mask"),
        "identity_mask_sha256": _nonzero_sha(f"{diagnostic_id}-identity-mask"),
        "boundary_band": {
            "radius": 3,
            "foreground_positive_pixels": 100,
            "boundary_positive_pixels": 20,
            "band_positive_pixels": 60,
            "band_mask_sha256": _nonzero_sha(f"{diagnostic_id}-boundary-band"),
        },
        "actual_outcome": "ANOMALY" if defect else "NORMAL",
        "identity_recall": 1.0,
        "study_recall": 1.0,
        "identity_dice": 1.0,
        "study_dice": 1.0,
        "study_iou": 1.0,
        "total_residual": 16 if defect else 0,
        "boundary_residual": 0,
        "outside_boundary_residual": 16 if defect else 0,
        "inference_trace": inference_trace,
    }


def _task_7a_diagnostic_summary(mode: str, *, eligible: bool = True) -> dict[str, object]:
    status = "PASS" if eligible else "FAIL"
    maximum_drop = 0.0 if eligible else 0.2
    return {
        "mode": mode,
        "row_count": 108,
        "defect_drop_denominator": 24,
        "defect_drop_exclusions": 84,
        "medium_high_classification_denominator": 24,
        "medium_high_classification_exclusions": 84,
        "maximum_recall_drop": maximum_drop,
        "median_dice_drop": 0.0,
        "medium_high_classification_recall": 1.0,
        "gates": [
            _task_7a_applicable_gate(
                "maximum_recall_drop",
                status=status,
                numerator=None,
                denominator=24,
                exclusions=84,
                observed=maximum_drop,
                operator="le",
                threshold=0.05,
            ),
            _task_7a_applicable_gate(
                "median_dice_drop",
                status="PASS",
                numerator=None,
                denominator=24,
                exclusions=84,
                observed=0.0,
                operator="le",
                threshold=0.01,
            ),
            _task_7a_applicable_gate(
                "medium_high_classification_recall",
                status="PASS",
                numerator=24,
                denominator=24,
                exclusions=84,
                observed=1.0,
                operator="ge",
                threshold=0.9,
            ),
        ],
        "eligible": eligible,
    }


def minimal_valid_diagnostic_result_record(
    protocol: StudyProtocolV2,
    *,
    eligible_modes: tuple[str, ...] = ("NEAREST", "BILINEAR", "BICUBIC"),
) -> dict[str, object]:
    modes = ("NEAREST", "BILINEAR", "BICUBIC")
    return _task_7a_result_record(
        protocol,
        record_type="diagnostic_result",
        upstream_paths=("retention-audit.json", "phase-1-execution-claim.json"),
        payload={
            "runtime_versions": {"python": "3.12.11", "numpy": "2.3.2", "pillow": "11.3.0"},
            "row_count": 108,
            "observation_count": 324,
            "cases": [_task_7a_diagnostic_case(ordinal) for ordinal in range(108)],
            "observations": [
                _task_7a_diagnostic_observation(ordinal, mode)
                for ordinal in range(108)
                for mode in modes
            ],
            "mode_summaries": [
                _task_7a_diagnostic_summary(mode, eligible=mode in eligible_modes)
                for mode in modes
            ],
            "eligible_modes": list(eligible_modes),
        },
    )


def _task_7a_oracle_record(ordinal: int, *, correct: bool = True) -> dict[str, object]:
    case_id = f"e1-v2-development-defect-{ordinal:03d}"
    return {
        "case_id": case_id,
        "seed": 420000 + ordinal,
        "authoritative_mask_sha256": _nonzero_sha(f"{case_id}-mask"),
        "authoritative_positive_pixels": 16,
        "expected_feature_id": "top_face",
        "predicted_feature_id": "top_face" if correct else "hole_left",
        "status": "MAPPED",
        "correct": correct,
        "hash_binding_matches": True,
        "ownership_map_sha256": TASK_7A_OWNERSHIP_HASHES["rev-A/front"],
        "target_owned_pixels": 16,
        "owned_pixel_count": 16,
        "unmapped_pixel_count": 0,
        "conserved": True,
    }


def minimal_valid_feature_oracle_record(
    protocol: StudyProtocolV2,
    *,
    passed: bool = True,
) -> dict[str, object]:
    records = [_task_7a_oracle_record(ordinal) for ordinal in range(60)]
    if not passed:
        records[0] = _task_7a_oracle_record(0, correct=False)
    return _task_7a_result_record(
        protocol,
        record_type="feature_oracle",
        upstream_paths=("scope-audit.json", "known-transform-diagnostic-108.json"),
        payload={
            "case_count": 60,
            "correct_cases": 60 if passed else 59,
            "ambiguous_cases": 0,
            "null_cases": 0,
            "wrong_cases": 0 if passed else 1,
            "minimum_winner_pixels": 8,
            "ambiguity_margin": 0.1,
            "ownership_hashes": dict(TASK_7A_OWNERSHIP_HASHES),
            "records": records,
            "passed": passed,
        },
    )


def _task_7a_set_first_oracle_class(
    record: dict[str, object],
    classification: Literal["wrong", "unmapped", "ambiguous"],
) -> dict[str, object]:
    payload = cast(dict[str, object], record["payload"])
    first = cast(list[dict[str, object]], payload["records"])[0]
    first["correct"] = False
    if classification == "wrong":
        first["status"] = "MAPPED"
        first["predicted_feature_id"] = "hole_left"
        first["target_owned_pixels"] = 16
        first["owned_pixel_count"] = 16
        first["unmapped_pixel_count"] = 0
    elif classification == "unmapped":
        first["status"] = "UNMAPPED"
        first["predicted_feature_id"] = None
        first["target_owned_pixels"] = 0
        first["owned_pixel_count"] = 0
        first["unmapped_pixel_count"] = 16
    else:
        first["status"] = "AMBIGUOUS"
        first["predicted_feature_id"] = None
        first["target_owned_pixels"] = 8
        first["owned_pixel_count"] = 16
        first["unmapped_pixel_count"] = 0
    first["conserved"] = True
    payload["correct_cases"] = 59
    payload["ambiguous_cases"] = 1 if classification == "ambiguous" else 0
    payload["null_cases"] = 1 if classification == "unmapped" else 0
    payload["wrong_cases"] = 1 if classification == "wrong" else 0
    payload["passed"] = False
    return first


def _task_7a_development_inference_record(
    binding: dict[str, object],
    mode: str,
) -> dict[str, object]:
    case_id = cast(str, binding["case_id"])
    group = cast(str, binding["group"])
    defect = group == "defect"
    inference_trace = _task_7a_inference_trace(mode, f"{case_id}-{mode}")
    source_hashes = cast(dict[str, object], inference_trace["source_hashes"])
    source_hashes["reference_sha256"] = binding["reference_sha256"]
    source_hashes["inspection_sha256"] = binding["inspection_sha256"]
    transform_trace = cast(dict[str, object], inference_trace["transform_trace"])
    transform_trace["reference_sha256"] = binding["reference_sha256"]
    transform_trace["source_inspection_sha256"] = binding["inspection_sha256"]
    return {
        "case_id": case_id,
        "seed": binding["seed"],
        "group": group,
        "mode": mode,
        "case_binding_sha256": binding["case_binding_sha256"],
        "evaluation_status": "APPLICABLE",
        "inference_trace": inference_trace,
        "metrics": {
            "expected_outcome": "ANOMALY" if defect else "NORMAL",
            "actual_outcome": "ANOMALY" if defect else "NORMAL",
            "anomaly_score": 0.8 if defect else 0.0,
            "defect_type": "scratch" if defect else None,
            "severity": "MEDIUM" if defect else None,
            "nuisance_types": ["brightness"] if group == "nuisance" else [],
            "cad_revision": "rev-A",
            "view_id": "front",
            "truth_positive_pixels": 16 if defect else 0,
            "predicted_positive_pixels": 16 if defect else 0,
            "intersection_pixels": 16 if defect else 0,
            "total_pixels": 196608,
            "expected_feature_id": "top_face" if defect else None,
            "predicted_feature_id": "top_face" if defect else None,
        },
    }


def _task_7a_trust_binding(binding: dict[str, object]) -> dict[str, object]:
    return {
        **binding,
        "applied_transform": _task_7a_applied_transform(identity=True),
        "evaluation_status": "NOT_APPLICABLE",
        "actual_outcome": None,
        "anomaly_score": None,
        "denominator_exclusion": "TRUST_BOUNDARY_BINDING_ONLY",
    }


def _task_7a_development_summary(mode: str, *, passed: bool = True) -> dict[str, object]:
    nuisance_observed = 0.0 if passed else 0.1
    return {
        "mode": mode,
        "member_count": 120,
        "inference_count": 114,
        "trust_binding_count": 6,
        "medium_high_recall": 1.0,
        "nuisance_false_positive_rate": nuisance_observed,
        "positive_median_dice": 1.0,
        "feature_mapping_accuracy": 1.0,
        "gates": [
            _task_7a_applicable_gate(
                "medium_high_defect_recall",
                status="PASS",
                numerator=40,
                denominator=40,
                exclusions=74,
                observed=1.0,
                operator="ge",
                threshold=0.9,
            ),
            _task_7a_applicable_gate(
                "nuisance_only_false_positive_rate",
                status="PASS" if passed else "FAIL",
                numerator=0 if passed else 3,
                denominator=30,
                exclusions=84,
                observed=nuisance_observed,
                operator="le",
                threshold=0.05,
            ),
            _task_7a_applicable_gate(
                "positive_case_median_dice",
                status="PASS",
                numerator=None,
                denominator=60,
                exclusions=54,
                observed=1.0,
                operator="ge",
                threshold=0.7,
            ),
            _task_7a_applicable_gate(
                "affected_feature_mapping_accuracy",
                status="PASS",
                numerator=60,
                denominator=60,
                exclusions=54,
                observed=1.0,
                operator="ge",
                threshold=0.95,
            ),
        ],
        "passed_all_gates": passed,
    }


def minimal_valid_development_result_record(
    protocol: StudyProtocolV2,
    *,
    eligible_modes: tuple[str, ...] = ("NEAREST", "BILINEAR"),
    passing_modes: tuple[str, ...] = ("NEAREST", "BILINEAR"),
) -> dict[str, object]:
    bindings = _task_7a_development_bindings()
    inference_bindings = [binding for binding in bindings if binding["group"] != "trust_boundary"]
    trust_bindings = [binding for binding in bindings if binding["group"] == "trust_boundary"]
    return _task_7a_result_record(
        protocol,
        record_type="development_result",
        upstream_paths=(
            "retention-audit.json",
            "known-transform-diagnostic-108.json",
            "scope-audit.json",
            "feature-ownership-oracle.json",
            "phase-2-execution-claim.json",
        ),
        payload={
            "runtime_versions": {"python": "3.12.11", "numpy": "2.3.2", "pillow": "11.3.0"},
            "member_count": 120,
            "bindings": bindings,
            "eligible_modes": list(eligible_modes),
            "inference_records": [
                _task_7a_development_inference_record(binding, mode)
                for mode in eligible_modes
                for binding in inference_bindings
            ],
            "trust_bindings": [_task_7a_trust_binding(binding) for binding in trust_bindings],
            "mode_summaries": [
                _task_7a_development_summary(mode, passed=mode in passing_modes)
                for mode in eligible_modes
            ],
            "passing_modes": list(passing_modes),
        },
    )


TASK_7A_ALLOWED_NEXT_ACTIONS = {
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
TASK_7A_PERFORMANCE_DECISION_BRANCHES = {
    "FEATURE_CONTRACT_FAILED": (
        TASK_7A_PRE_DECISION_PATHS[:6],
        "FEATURE_ORACLE_FAILED",
    ),
    "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED": (
        TASK_7A_PRE_DECISION_PATHS[:6],
        "NO_DIAGNOSTIC_MODE_ELIGIBLE",
    ),
    "DIFFERENCE_BASELINE_LIMITED": (
        TASK_7A_PRE_DECISION_PATHS,
        "NO_DEVELOPMENT_MODE_PASSED",
    ),
    "TRANSFORM_ESTIMATION_LIMITED": (
        TASK_7A_PRE_DECISION_PATHS,
        "DEVELOPMENT_MODE_PASSED",
    ),
}


def minimal_valid_decision_record(
    protocol: StudyProtocolV2,
    *,
    decision: str = "TRANSFORM_ESTIMATION_LIMITED",
) -> dict[str, object]:
    if decision == "STUDY_INVALID":
        present_paths: tuple[str, ...] = ()
        invalid_paths: tuple[str, ...] = ()
        verified_count = 0
        verify_rate = 0.0
        reason = "ARTIFACT_VERIFICATION_FAILED"
    else:
        present_paths, reason = TASK_7A_PERFORMANCE_DECISION_BRANCHES[decision]
        invalid_paths = ()
        verified_count = len(present_paths)
        verify_rate = 1.0
    return _task_7a_result_record(
        protocol,
        record_type="decision",
        upstream_paths=tuple(path for path in present_paths if path not in invalid_paths),
        payload={
            "decision": decision,
            "allowed_next_action": TASK_7A_ALLOWED_NEXT_ACTIONS[decision],
            "reasons": [reason],
            "verified_artifact_count": verified_count,
            "present_artifact_count": len(present_paths),
            "study_artifact_verify_rate": verify_rate,
            "present_paths": list(present_paths),
            "invalid_paths": list(invalid_paths),
        },
    )


def _task_7a_set_decision_inventory(
    record: dict[str, object],
    present_paths: tuple[str, ...],
    *,
    invalid_paths: tuple[str, ...] = (),
) -> None:
    payload = cast(dict[str, object], record["payload"])
    verified_paths = tuple(path for path in present_paths if path not in invalid_paths)
    payload["present_paths"] = list(present_paths)
    payload["invalid_paths"] = list(invalid_paths)
    payload["present_artifact_count"] = len(present_paths)
    payload["verified_artifact_count"] = len(verified_paths)
    payload["study_artifact_verify_rate"] = (
        len(verified_paths) / len(present_paths) if present_paths else 0.0
    )
    record["upstream_artifacts"] = [_task_7a_upstream(path) for path in verified_paths]


@pytest.mark.parametrize(
    "builder",
    [
        minimal_valid_scope_audit_record,
        minimal_valid_diagnostic_result_record,
        minimal_valid_feature_oracle_record,
        minimal_valid_development_result_record,
        minimal_valid_decision_record,
    ],
)
def test_task_7a_full_cardinality_result_variants_validate(
    protocol: StudyProtocolV2,
    builder: Any,
) -> None:
    validate_study_schema(finalize_study_record(builder(protocol)))


PORTABLE_ROOT_RECORD_BUILDERS = (
    ("phase_execution_claim", minimal_valid_execution_claim_record),
    ("implementation_validation", minimal_valid_implementation_validation_record),
    ("retention_audit", minimal_valid_retention_audit_record),
    ("scope_audit", minimal_valid_scope_audit_record),
    ("diagnostic_result", minimal_valid_diagnostic_result_record),
    ("feature_oracle", minimal_valid_feature_oracle_record),
    ("development_result", minimal_valid_development_result_record),
    ("decision", minimal_valid_decision_record),
)


@pytest.mark.parametrize(("record_type", "builder"), PORTABLE_ROOT_RECORD_BUILDERS)
@pytest.mark.parametrize(
    "wrong_root",
    (
        "/tmp/checkout/docs/evaluation/results/e1-feasibility-study",
        "docs/evaluation/results/alternate-e1-study",
    ),
    ids=("absolute-checkout", "second-relative-root"),
)
def test_every_artifact_schema_family_rejects_nonportable_root_identity(
    protocol: StudyProtocolV2,
    record_type: str,
    builder: Any,
    wrong_root: str,
) -> None:
    """Catch any closed artifact variant that still permits a mixed root identity."""

    document = builder(protocol)
    assert document["record_type"] == record_type
    document["artifact_root"] = wrong_root

    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(document))


@pytest.mark.parametrize(("record_type", "builder"), PORTABLE_ROOT_RECORD_BUILDERS)
@pytest.mark.parametrize(
    "wrong_root",
    (
        "/tmp/checkout/docs/evaluation/results/e1-feasibility-study",
        "docs/evaluation/results/alternate-e1-study",
    ),
    ids=("absolute-checkout", "second-relative-root"),
)
def test_store_verifier_rejects_nonportable_root_in_every_artifact_family(
    tmp_path: Path,
    protocol: StudyProtocolV2,
    record_type: str,
    builder: Any,
    wrong_root: str,
) -> None:
    """Catch a real store verification path that accepts mixed envelope identity."""

    document = builder(protocol)
    document["artifact_root"] = wrong_root
    _write_direct(tmp_path, "record.json", canonical_json_bytes(finalize_study_record(document)))
    store = StudyArtifactStore(tmp_path)

    with pytest.raises(StudyArtifactError, match="schema"):
        store.verify_json_result("record.json", expected_record_type=record_type)


def test_task_7a_negative_performance_results_remain_valid_records(
    protocol: StudyProtocolV2,
) -> None:
    records = (
        minimal_valid_diagnostic_result_record(protocol, eligible_modes=()),
        minimal_valid_feature_oracle_record(protocol, passed=False),
        minimal_valid_development_result_record(protocol, passing_modes=()),
        minimal_valid_decision_record(protocol, decision="DIFFERENCE_BASELINE_LIMITED"),
    )

    for record in records:
        validate_study_schema(finalize_study_record(record))


def test_task_7a_every_declared_object_schema_is_closed() -> None:
    schema = load_strict_json_object(STUDY_ARTIFACT_SCHEMA_PATH.read_bytes())
    open_objects: list[str] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object" and value.get("additionalProperties") is not False:
                open_objects.append(path)
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(schema, "$")
    assert open_objects == []


@pytest.mark.parametrize(
    "builder,nested_path",
    [
        (minimal_valid_scope_audit_record, ("payload", "bindings", 0)),
        (
            minimal_valid_diagnostic_result_record,
            (
                "payload",
                "observations",
                0,
                "inference_trace",
                "transform_trace",
                "objective_before",
            ),
        ),
        (minimal_valid_feature_oracle_record, ("payload", "records", 0)),
        (
            minimal_valid_development_result_record,
            ("payload", "inference_records", 0, "metrics"),
        ),
        (minimal_valid_decision_record, ("payload",)),
    ],
)
def test_task_7a_new_variants_reject_extra_nested_keys(
    protocol: StudyProtocolV2,
    builder: Any,
    nested_path: tuple[object, ...],
) -> None:
    record = builder(protocol)
    target: Any = record
    for part in nested_path:
        target = target[part]
    target["unexpected"] = True

    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(record))


def test_task_7a_upstream_paths_reject_wrong_order_path_and_count(
    protocol: StudyProtocolV2,
) -> None:
    wrong_order = minimal_valid_diagnostic_result_record(protocol)
    cast(list[object], wrong_order["upstream_artifacts"]).reverse()

    wrong_path = minimal_valid_scope_audit_record(protocol)
    cast(list[dict[str, object]], wrong_path["upstream_artifacts"])[0]["path"] = (
        "implementation-validation.json"
    )

    wrong_count = minimal_valid_feature_oracle_record(protocol)
    cast(list[object], wrong_count["upstream_artifacts"]).pop()

    for record in (wrong_order, wrong_path, wrong_count):
        with pytest.raises(StudyArtifactError, match="schema"):
            validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize("forbidden", ["best_mode", "ranked_modes", "selected_mode"])
def test_task_7a_development_schema_forbids_mode_selection_fields(
    protocol: StudyProtocolV2,
    forbidden: str,
) -> None:
    record = minimal_valid_development_result_record(protocol)
    cast(dict[str, object], record["payload"])[forbidden] = "NEAREST"

    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(finalize_study_record(record))


def test_task_7a_decision_requires_exact_action_inventory_and_full_performance_rate(
    protocol: StudyProtocolV2,
) -> None:
    wrong_action = minimal_valid_decision_record(protocol)
    cast(dict[str, object], wrong_action["payload"])["allowed_next_action"] = "Start Candidate C"

    wrong_rate = minimal_valid_decision_record(protocol)
    cast(dict[str, object], wrong_rate["payload"])["study_artifact_verify_rate"] = 0.5

    wrong_inventory = minimal_valid_decision_record(protocol)
    cast(list[str], cast(dict[str, object], wrong_inventory["payload"])["present_paths"]).reverse()

    for record in (wrong_action, wrong_rate, wrong_inventory):
        with pytest.raises(StudyArtifactError, match=r"schema|decision"):
            validate_study_schema(finalize_study_record(record))


def test_task_7a_semantics_rejects_case_and_observation_order_drift(
    protocol: StudyProtocolV2,
) -> None:
    scope = minimal_valid_scope_audit_record(protocol)
    scope_bindings = cast(list[object], cast(dict[str, object], scope["payload"])["bindings"])
    scope_bindings[0], scope_bindings[1] = scope_bindings[1], scope_bindings[0]

    diagnostic = minimal_valid_diagnostic_result_record(protocol)
    observations = cast(
        list[object], cast(dict[str, object], diagnostic["payload"])["observations"]
    )
    observations[0], observations[1] = observations[1], observations[0]

    oracle = minimal_valid_feature_oracle_record(protocol)
    oracle_records = cast(list[object], cast(dict[str, object], oracle["payload"])["records"])
    oracle_records[0], oracle_records[1] = oracle_records[1], oracle_records[0]

    for record in (scope, diagnostic, oracle):
        with pytest.raises(StudyArtifactError, match=r"scope|diagnostic|oracle"):
            validate_study_schema(finalize_study_record(record))


def test_task_7a_semantics_rejects_declared_summary_and_total_drift(
    protocol: StudyProtocolV2,
) -> None:
    diagnostic = minimal_valid_diagnostic_result_record(protocol)
    cast(list[object], cast(dict[str, object], diagnostic["payload"])["eligible_modes"]).reverse()

    oracle = minimal_valid_feature_oracle_record(protocol)
    cast(dict[str, object], oracle["payload"])["correct_cases"] = 59

    development = minimal_valid_development_result_record(protocol)
    cast(list[object], cast(dict[str, object], development["payload"])["inference_records"]).pop()

    passing = minimal_valid_development_result_record(protocol)
    cast(list[object], cast(dict[str, object], passing["payload"])["passing_modes"]).reverse()

    for record in (diagnostic, oracle, development, passing):
        with pytest.raises(StudyArtifactError, match=r"diagnostic|oracle|development"):
            validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize(
    "variant",
    [
        "reason",
        "denominator",
        "exclusions",
        "operator",
        "threshold",
        "statistic_numerator",
        "ratio_numerator_bound",
        "ratio_arithmetic",
        "summary_observed",
        "status",
        "eligibility",
    ],
)
def test_task_7a_fix1_applicable_gate_contract_rejects_diagnostic_forgery(
    protocol: StudyProtocolV2,
    variant: str,
) -> None:
    record = minimal_valid_diagnostic_result_record(protocol)
    payload = cast(dict[str, object], record["payload"])
    summaries = cast(list[dict[str, object]], payload["mode_summaries"])
    summary = summaries[0]
    gates = cast(list[dict[str, object]], summary["gates"])
    statistic = gates[0]
    ratio = gates[2]
    if variant == "reason":
        statistic["reason"] = "FORGED"
    elif variant == "denominator":
        statistic["denominator"] = 25
    elif variant == "exclusions":
        statistic["exclusions"] = 83
    elif variant == "operator":
        statistic["operator"] = "ge"
    elif variant == "threshold":
        statistic["threshold"] = 0.06
    elif variant == "statistic_numerator":
        statistic["numerator"] = 0
    elif variant == "ratio_numerator_bound":
        ratio["numerator"] = 25
    elif variant == "ratio_arithmetic":
        ratio["numerator"] = 23
    elif variant == "summary_observed":
        statistic["observed"] = 0.01
    elif variant == "status":
        statistic["status"] = "FAIL"
    else:
        summary["eligible"] = False
        payload["eligible_modes"] = ["BILINEAR", "BICUBIC"]

    with pytest.raises(StudyArtifactError, match=r"schema|diagnostic.*gate|eligible"):
        validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize(
    "variant",
    [
        "reason",
        "denominator",
        "exclusions",
        "operator",
        "threshold",
        "statistic_numerator",
        "ratio_numerator_bound",
        "ratio_arithmetic",
        "summary_observed",
        "status",
        "passing",
    ],
)
def test_task_7a_fix1_applicable_gate_contract_rejects_development_forgery(
    protocol: StudyProtocolV2,
    variant: str,
) -> None:
    record = minimal_valid_development_result_record(protocol)
    payload = cast(dict[str, object], record["payload"])
    summaries = cast(list[dict[str, object]], payload["mode_summaries"])
    summary = summaries[0]
    gates = cast(list[dict[str, object]], summary["gates"])
    ratio = gates[0]
    statistic = gates[2]
    if variant == "reason":
        ratio["reason"] = "FORGED"
    elif variant == "denominator":
        ratio["denominator"] = 41
    elif variant == "exclusions":
        ratio["exclusions"] = 73
    elif variant == "operator":
        ratio["operator"] = "le"
    elif variant == "threshold":
        ratio["threshold"] = 0.91
    elif variant == "statistic_numerator":
        statistic["numerator"] = 60
    elif variant == "ratio_numerator_bound":
        ratio["numerator"] = 41
    elif variant == "ratio_arithmetic":
        ratio["numerator"] = 39
    elif variant == "summary_observed":
        statistic["observed"] = 0.99
    elif variant == "status":
        ratio["status"] = "FAIL"
    else:
        summary["passed_all_gates"] = False
        payload["passing_modes"] = ["BILINEAR"]

    with pytest.raises(StudyArtifactError, match=r"schema|development.*gate|passing"):
        validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize("classification", ["wrong", "unmapped", "ambiguous"])
def test_task_7a_fix1_oracle_row_contract_accepts_each_legal_negative_class(
    protocol: StudyProtocolV2,
    classification: Literal["wrong", "unmapped", "ambiguous"],
) -> None:
    record = minimal_valid_feature_oracle_record(protocol)
    _task_7a_set_first_oracle_class(record, classification)

    validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize(
    "variant",
    [
        "status",
        "expected_feature",
        "predicted_feature",
        "ownership_hash",
        "mapped_null",
        "unmapped_prediction",
        "ambiguous_prediction",
        "unmapped_minimum",
        "target_exceeds_owned",
        "owned_exceeds_positive",
        "false_correct_formula",
        "true_illegal_status",
    ],
)
def test_task_7a_fix1_oracle_row_contract_rejects_forged_failure_row(
    protocol: StudyProtocolV2,
    variant: str,
) -> None:
    record = minimal_valid_feature_oracle_record(protocol)
    payload = cast(dict[str, object], record["payload"])
    first = cast(list[dict[str, object]], payload["records"])[0]
    if variant == "status":
        first = _task_7a_set_first_oracle_class(record, "unmapped")
        first["status"] = "FORGED"
    elif variant == "expected_feature":
        first["expected_feature_id"] = "forged_feature"
        first["predicted_feature_id"] = "forged_feature"
    elif variant == "predicted_feature":
        first = _task_7a_set_first_oracle_class(record, "wrong")
        first["predicted_feature_id"] = "forged_feature"
    elif variant == "ownership_hash":
        first = _task_7a_set_first_oracle_class(record, "wrong")
        first["ownership_map_sha256"] = _nonzero_sha("unfrozen-ownership-map")
    elif variant == "mapped_null":
        first = _task_7a_set_first_oracle_class(record, "unmapped")
        first["status"] = "MAPPED"
    elif variant == "unmapped_prediction":
        first = _task_7a_set_first_oracle_class(record, "wrong")
        first["status"] = "UNMAPPED"
    elif variant == "ambiguous_prediction":
        first = _task_7a_set_first_oracle_class(record, "wrong")
        first["status"] = "AMBIGUOUS"
        payload["ambiguous_cases"] = 1
        payload["wrong_cases"] = 0
    elif variant == "unmapped_minimum":
        first = _task_7a_set_first_oracle_class(record, "unmapped")
        first["target_owned_pixels"] = 8
    elif variant == "target_exceeds_owned":
        first = _task_7a_set_first_oracle_class(record, "wrong")
        first["target_owned_pixels"] = 17
    elif variant == "owned_exceeds_positive":
        first = _task_7a_set_first_oracle_class(record, "wrong")
        first["owned_pixel_count"] = 17
        first["conserved"] = False
    elif variant == "false_correct_formula":
        first["correct"] = False
        payload["correct_cases"] = 59
        payload["wrong_cases"] = 1
        payload["passed"] = False
    else:
        first["status"] = "UNMAPPED"

    with pytest.raises(StudyArtifactError, match=r"schema|oracle"):
        validate_study_schema(finalize_study_record(record))


def test_task_7a_decision_semantics_bind_counts_invalid_inventory_and_upstreams(
    protocol: StudyProtocolV2,
) -> None:
    wrong_count = minimal_valid_decision_record(protocol)
    cast(dict[str, object], wrong_count["payload"])["verified_artifact_count"] = 7

    invalid_not_present = minimal_valid_decision_record(protocol, decision="STUDY_INVALID")
    cast(dict[str, object], invalid_not_present["payload"])["invalid_paths"] = [
        "retention-audit.json"
    ]

    fabricated_upstream = minimal_valid_decision_record(protocol, decision="STUDY_INVALID")
    fabricated_upstream["upstream_artifacts"] = [
        _task_7a_upstream("implementation-validation.json")
    ]

    for record in (wrong_count, invalid_not_present, fabricated_upstream):
        with pytest.raises(StudyArtifactError, match="decision"):
            validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize(
    "decision",
    [
        "FEATURE_CONTRACT_FAILED",
        "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED",
        "DIFFERENCE_BASELINE_LIMITED",
        "TRANSFORM_ESTIMATION_LIMITED",
    ],
)
def test_task_7a_fix1_decision_branch_contract_accepts_exact_performance_branch(
    protocol: StudyProtocolV2,
    decision: str,
) -> None:
    validate_study_schema(
        finalize_study_record(minimal_valid_decision_record(protocol, decision=decision))
    )


@pytest.mark.parametrize(
    "decision,present_paths",
    [
        ("FEATURE_CONTRACT_FAILED", TASK_7A_PRE_DECISION_PATHS[:7]),
        ("KNOWN_TRANSFORM_DIAGNOSTIC_FAILED", TASK_7A_PRE_DECISION_PATHS),
        ("DIFFERENCE_BASELINE_LIMITED", TASK_7A_PRE_DECISION_PATHS[:7]),
        (
            "TRANSFORM_ESTIMATION_LIMITED",
            (*TASK_7A_PRE_DECISION_PATHS[:6], TASK_7A_PRE_DECISION_PATHS[7]),
        ),
    ],
)
def test_task_7a_fix1_decision_branch_contract_rejects_wrong_performance_inventory(
    protocol: StudyProtocolV2,
    decision: str,
    present_paths: tuple[str, ...],
) -> None:
    record = minimal_valid_decision_record(protocol, decision=decision)
    _task_7a_set_decision_inventory(record, present_paths)

    with pytest.raises(StudyArtifactError, match=r"schema|decision"):
        validate_study_schema(finalize_study_record(record))


@pytest.mark.parametrize("decision", list(TASK_7A_PERFORMANCE_DECISION_BRANCHES))
def test_task_7a_fix1_decision_branch_contract_rejects_performance_reason_forgery(
    protocol: StudyProtocolV2,
    decision: str,
) -> None:
    record = minimal_valid_decision_record(protocol, decision=decision)
    payload = cast(dict[str, object], record["payload"])
    payload["reasons"] = ["FORGED_REASON", "EXTRA_REASON"]

    with pytest.raises(StudyArtifactError, match=r"schema|decision"):
        validate_study_schema(finalize_study_record(record))


def test_task_7a_fix1_decision_branch_contract_closes_invalid_reason_and_inventory(
    protocol: StudyProtocolV2,
) -> None:
    valid = minimal_valid_decision_record(protocol, decision="STUDY_INVALID")
    _task_7a_set_decision_inventory(
        valid,
        TASK_7A_PRE_DECISION_PATHS[:4],
        invalid_paths=("retention-audit.json",),
    )
    validate_study_schema(finalize_study_record(valid))

    forged_reason = deepcopy(valid)
    cast(dict[str, object], forged_reason["payload"])["reasons"] = ["FORGED_REASON"]
    with pytest.raises(StudyArtifactError, match=r"schema|decision"):
        validate_study_schema(finalize_study_record(forged_reason))


def test_task_7a_new_variant_rejects_forged_self_hash(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    store = StudyArtifactStore(tmp_path)
    document = finalize_study_record(minimal_valid_scope_audit_record(protocol))
    document["record_sha256"] = "f" * 64
    _write_direct(tmp_path, "scope-audit.json", canonical_json_bytes(document))

    with pytest.raises(StudyArtifactError, match="self-hash"):
        store.verify_json_result("scope-audit.json", expected_record_type="scope_audit")


def test_task_7a_open_existing_reads_existing_root_without_creation(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "present.bin").write_bytes(b"present")

    store = StudyArtifactStore.open_existing(root, allowed_root=tmp_path)

    assert store is not None
    assert store.read_bytes("present.bin") == b"present"


def test_task_7a_open_existing_distinguishes_unsafe_root_from_absence(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    not_a_directory = tmp_path / "file"
    not_a_directory.write_bytes(b"file")

    with pytest.raises(StudyArtifactError, match=r"unsafe|symlink"):
        StudyArtifactStore.open_existing(linked, allowed_root=tmp_path)
    with pytest.raises(StudyArtifactError, match=r"unsafe|directory"):
        StudyArtifactStore.open_existing(not_a_directory, allowed_root=tmp_path)


def test_task_7a_lexical_root_replacement_is_detectable(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    pinned = tmp_path / "pinned"
    root.rename(pinned)
    root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(StudyArtifactError, match=r"lexical.*identity|symlink"):
        store.verify_lexical_root_identity()


def test_task_7a_verified_json_result_is_deeply_immutable_and_single_read(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    class CountingStore(StudyArtifactStore):
        reads = 0

        def read_bytes(self, relative_path: str) -> bytes:
            self.reads += 1
            return super().read_bytes(relative_path)

    store = CountingStore(tmp_path)
    expected = finalize_study_record(minimal_valid_scope_audit_record(protocol))
    store.publish_json("scope-audit.json", expected)

    verified = store.verify_json_result(
        "scope-audit.json",
        expected_record_type="scope_audit",
    )

    assert store.reads == 1
    assert verified.raw_sha256 == sha256_bytes(verified.raw_bytes)
    assert verified.record_sha256 == verified.document["record_sha256"]
    with pytest.raises(TypeError):
        cast(Any, verified.document)["record_type"] = "forged"
    with pytest.raises(TypeError):
        cast(Any, verified.document["payload"])["passed"] = False
    assert isinstance(cast(Any, verified.document["payload"])["bindings"], tuple)


def test_task_7a_verify_json_delegates_to_verified_result(
    tmp_path: Path,
    protocol: StudyProtocolV2,
) -> None:
    class DelegationStore(StudyArtifactStore):
        result_calls = 0

        def verify_json_result(
            self,
            relative_path: str,
            *,
            expected_record_type: str,
        ) -> Any:
            self.result_calls += 1
            return super().verify_json_result(
                relative_path,
                expected_record_type=expected_record_type,
            )

    store = DelegationStore(tmp_path)
    expected = finalize_study_record(minimal_valid_execution_claim_record(protocol))
    store.publish_json("claim.json", expected)

    assert store.verify_json(
        "claim.json", expected_record_type="phase_execution_claim"
    ) == expected
    assert store.result_calls == 1


def test_task_7a_fix1_inventory_contract_returns_frozen_global_byte_order(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    assert store.inventory() == ()
    (root / "a").mkdir()
    (root / "a" / "child").write_bytes(b"child")
    (root / "a-plain").write_bytes(b"plain")

    inventory = store.inventory()

    assert tuple(entry.path for entry in inventory) == ("a", "a-plain", "a/child")
    assert tuple(entry.kind for entry in inventory) == ("directory", "file", "file")
    assert tuple(entry.byte_size for entry in inventory[1:]) == (5, 5)
    assert tuple(entry.link_count for entry in inventory[1:]) == (1, 1)
    with pytest.raises(FrozenInstanceError):
        cast(Any, inventory[0]).kind = "other"


def test_task_7a_fix1_inventory_contract_never_follows_links_and_reports_node_kinds(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "child").write_bytes(b"outside")
    outside_file = tmp_path / "outside.bin"
    outside_file.write_bytes(b"outside")
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    (root / "linked-file").symlink_to(outside_file)
    (root / "hard-a").write_bytes(b"hard")
    os.link(root / "hard-a", root / "hard-b")
    os.mkfifo(root / "fifo")

    inventory = {entry.path: entry for entry in store.inventory()}

    assert inventory["linked-dir"].kind == "symlink"
    assert inventory["linked-file"].kind == "symlink"
    assert "linked-dir/child" not in inventory
    assert inventory["hard-a"].kind == "file"
    assert inventory["hard-a"].link_count == 2
    assert inventory["hard-b"].link_count == 2
    assert inventory["fifo"].kind == "other"


def test_task_7a_fix1_inventory_contract_enforces_entry_limit(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    for ordinal in range(257):
        (root / f"entry-{ordinal:03d}").write_bytes(b"")

    with pytest.raises(StudyArtifactError, match=r"entry.*limit"):
        store.inventory()


def test_task_7a_fix1_inventory_contract_enforces_depth_limit(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    too_deep = root.joinpath(*("d" for _ in range(9)))
    too_deep.mkdir(parents=True)

    with pytest.raises(StudyArtifactError, match="depth"):
        store.inventory()


@pytest.mark.parametrize("name", ["x" * 241, "control\nname"])
def test_task_7a_fix1_inventory_contract_enforces_path_policy(
    tmp_path: Path,
    name: str,
) -> None:
    root = tmp_path / "artifacts"
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    (root / name).write_bytes(b"unsafe")

    with pytest.raises(StudyArtifactError, match=r"path.*unsafe"):
        store.inventory()


def test_task_7a_fix1_inventory_contract_detects_concurrent_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    (root / "initial").write_bytes(b"initial")
    real_names = getattr(
        artifacts_module,
        "_inventory_directory_names",
        lambda descriptor: tuple(entry.name for entry in os.scandir(descriptor)),
    )
    mutated = False

    def mutate_after_names(descriptor: int) -> tuple[str, ...]:
        nonlocal mutated
        names = real_names(descriptor)
        if not mutated:
            (root / "late").write_bytes(b"late")
            mutated = True
        return names

    monkeypatch.setattr(
        artifacts_module,
        "_inventory_directory_names",
        mutate_after_names,
        raising=False,
    )

    with pytest.raises(StudyArtifactError, match=r"changed|mutation"):
        store.inventory()


def test_task_7a_fix1_inventory_contract_rejects_lexical_replacement_and_closed_store(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    root.rename(tmp_path / "pinned")
    root.mkdir()

    with pytest.raises(StudyArtifactError, match=r"lexical.*identity"):
        store.inventory()

    store.close()
    with pytest.raises(StudyArtifactError, match="closed"):
        store.inventory()


def test_task_7a_fix1_inventory_contract_does_not_leak_descriptors(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    store = StudyArtifactStore(root, allowed_root=tmp_path)
    (root / "nested").mkdir()
    (root / "nested" / "artifact.bin").write_bytes(b"artifact")
    descriptor_directory = Path("/dev/fd")
    if not descriptor_directory.is_dir():
        pytest.skip("descriptor inventory is unavailable")
    before = len(os.listdir(descriptor_directory))

    for _ in range(50):
        store.inventory()

    assert len(os.listdir(descriptor_directory)) == before
