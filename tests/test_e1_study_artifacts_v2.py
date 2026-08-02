from __future__ import annotations

import inspect
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
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
    assert claim.artifact_root == protocol.artifact_root.as_posix()
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


def test_schema_has_only_the_execution_claim_variant(
    protocol: StudyProtocolV2,
) -> None:
    schema = load_strict_json_object(STUDY_ARTIFACT_SCHEMA_PATH.read_bytes())
    definitions = cast(dict[str, object], schema["$defs"])
    assert "phaseExecutionClaim" in definitions
    assert not {
        "implementationValidation",
        "retentionAudit",
        "scopeAudit",
        "diagnosticStudy",
        "featureOwnershipOracle",
        "developmentStudy",
        "terminalDecision",
    }.intersection(definitions)

    wrong_variant = minimal_valid_execution_claim_record(protocol)
    wrong_variant["record_type"] = "retention_audit"
    wrong_variant = finalize_study_record(wrong_variant)
    with pytest.raises(StudyArtifactError, match="schema"):
        validate_study_schema(wrong_variant)


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
