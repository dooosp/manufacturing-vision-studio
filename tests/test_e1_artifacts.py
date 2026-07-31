from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.e1.artifacts import (
    DEFAULT_VOLATILE_FIELDS,
    E1ArtifactError,
    E1ArtifactStore,
    bind_document_sha256,
    deterministic_projection,
    verify_document_sha256,
)


def _assert_error_code(exc_info: pytest.ExceptionInfo[E1ArtifactError], code: str) -> None:
    assert exc_info.value.code == code


def test_store_writes_canonical_json_atomically_and_immutably(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")
    first = {"z": 2, "a": "한글"}

    record = store.write_json("nested/result.json", first)

    expected = canonical_json_bytes(first)
    assert (store.root / "nested/result.json").read_bytes() == expected
    assert record.as_dict() == {
        "path": "nested/result.json",
        "sha256": sha256_bytes(expected),
        "byte_size": len(expected),
        "media_type": "application/json",
    }
    assert not list((store.root / "nested").glob("*.tmp"))

    with pytest.raises(E1ArtifactError) as exc_info:
        store.write_json("nested/result.json", {"replacement": False})
    _assert_error_code(exc_info, "STORAGE_CONFLICT")
    assert store.read_json("nested/result.json") == first

    replacement = {"replacement": True}
    store.write_json("nested/result.json", replacement, replace=True)
    assert store.read_json("nested/result.json") == replacement


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "",
        "../escape.json",
        "nested/../../escape.json",
        "/absolute.json",
        "nested\\windows.json",
        "nested/./alias.json",
        "nested//alias.json",
        "trailing/",
        "nul\x00.json",
        "line\nbreak.json",
    ],
)
def test_store_rejects_unsafe_or_noncanonical_paths(tmp_path: Path, unsafe_path: str) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.write_bytes(unsafe_path, b"evidence")

    _assert_error_code(exc_info, "UNSAFE_PATH")


def test_store_rejects_root_escape_and_symlinked_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    with pytest.raises(E1ArtifactError) as exc_info:
        E1ArtifactStore(tmp_path / "outside", allowed_root=allowed)
    _assert_error_code(exc_info, "UNSAFE_PATH")

    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(E1ArtifactError) as exc_info:
        E1ArtifactStore(linked_root)
    _assert_error_code(exc_info, "SYMLINK_INPUT")

    bridge = tmp_path / "bridge"
    bridge.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(E1ArtifactError) as exc_info:
        E1ArtifactStore(bridge / "nested")
    _assert_error_code(exc_info, "SYMLINK_INPUT")


def test_store_never_follows_parent_or_final_symlinks(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside")

    (store.root / "linked-parent").symlink_to(outside, target_is_directory=True)
    with pytest.raises(E1ArtifactError) as exc_info:
        store.write_bytes("linked-parent/new.txt", b"must-not-escape")
    _assert_error_code(exc_info, "SYMLINK_INPUT")
    assert not (outside / "new.txt").exists()

    (store.root / "linked-final.txt").symlink_to(outside / "secret.txt")
    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_bytes("linked-final.txt")
    _assert_error_code(exc_info, "SYMLINK_INPUT")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.write_bytes("linked-final.txt", b"replacement", replace=True)
    _assert_error_code(exc_info, "SYMLINK_INPUT")
    assert (outside / "secret.txt").read_bytes() == b"outside"


def test_store_rejects_nonregular_missing_and_oversized_artifacts(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts", max_artifact_bytes=8, max_total_bytes=16)

    with pytest.raises(E1ArtifactError) as exc_info:
        store.write_bytes("large.bin", b"123456789")
    _assert_error_code(exc_info, "INPUT_TOO_LARGE")

    (store.root / "directory").mkdir()
    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_bytes("directory")
    _assert_error_code(exc_info, "NON_REGULAR_INPUT")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_bytes("missing.bin")
    _assert_error_code(exc_info, "EVIDENCE_INCOMPLETE")


def test_read_json_requires_canonical_duplicate_free_object(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")
    noncanonical = store.root / "noncanonical.json"
    noncanonical.write_bytes(b'{"z": 1, "a": 2}')

    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_json("noncanonical.json")
    _assert_error_code(exc_info, "CANONICAL_JSON_MISMATCH")

    duplicate = store.root / "duplicate.json"
    duplicate.write_bytes(b'{"value":1,"value":2}')
    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_json("duplicate.json")
    _assert_error_code(exc_info, "SCHEMA_INVALID")

    array_root = store.root / "array.json"
    array_root.write_bytes(b"[]")
    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_json("array.json")
    _assert_error_code(exc_info, "SCHEMA_INVALID")


def test_read_bytes_checks_the_expected_digest(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")
    store.write_bytes("evidence.bin", b"trusted")

    assert store.read_bytes("evidence.bin", expected_sha256=sha256_bytes(b"trusted")) == b"trusted"
    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_bytes("evidence.bin", expected_sha256="0" * 64)
    _assert_error_code(exc_info, "HASH_MISMATCH")


def test_read_bytes_rejects_multiply_linked_artifact(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")
    store.write_bytes("evidence.bin", b"trusted")
    os.link(store.root / "evidence.bin", store.root / "second-name.bin")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.read_bytes("evidence.bin")

    _assert_error_code(exc_info, "NON_REGULAR_INPUT")


def test_inventory_is_sorted_bound_and_detects_member_tampering(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")
    store.write_bytes("z/mask.png", b"png")
    store.write_json("a/result.json", {"value": 1})

    record = store.write_inventory("inventory.json", ["z/mask.png", "a/result.json"])
    inventory = store.read_json("inventory.json")
    assert record.path == "inventory.json"
    assert inventory["artifact_count"] == 2
    assert inventory["payload_byte_size"] == sum(
        artifact["byte_size"] for artifact in inventory["artifacts"]
    )
    assert [artifact["path"] for artifact in inventory["artifacts"]] == [
        "a/result.json",
        "z/mask.png",
    ]
    assert [artifact["media_type"] for artifact in inventory["artifacts"]] == [
        "application/json",
        "image/png",
    ]
    assert [member.path for member in store.verify_inventory("inventory.json")] == [
        "a/result.json",
        "z/mask.png",
    ]

    (store.root / "z/mask.png").write_bytes(b"tampered")
    with pytest.raises(E1ArtifactError) as exc_info:
        store.verify_inventory("inventory.json")
    _assert_error_code(exc_info, "HASH_MISMATCH")


def test_inventory_rejects_duplicates_self_inclusion_and_total_overflow(
    tmp_path: Path,
) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts", max_artifact_bytes=8, max_total_bytes=10)
    store.write_bytes("a.bin", b"123456")
    store.write_bytes("b.bin", b"abcdef")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.build_inventory(["a.bin", "a.bin"])
    _assert_error_code(exc_info, "SCHEMA_INVALID")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.build_inventory([])
    _assert_error_code(exc_info, "SCHEMA_INVALID")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.write_inventory("inventory.json", ["inventory.json"])
    _assert_error_code(exc_info, "SCHEMA_INVALID")

    with pytest.raises(E1ArtifactError) as exc_info:
        store.build_inventory(["a.bin", "b.bin"])
    _assert_error_code(exc_info, "INPUT_TOO_LARGE")


def test_inventory_rejects_canonical_but_invalid_metadata(tmp_path: Path) -> None:
    store = E1ArtifactStore(tmp_path / "artifacts")
    store.write_bytes("member.bin", b"member")
    inventory = store.build_inventory(["member.bin"])
    artifacts = inventory["artifacts"]
    assert isinstance(artifacts, list)
    artifacts[0]["media_type"] = ""
    store.write_json("inventory.json", inventory)

    with pytest.raises(E1ArtifactError) as exc_info:
        store.verify_inventory("inventory.json")
    _assert_error_code(exc_info, "SCHEMA_INVALID")


def test_document_and_projection_hashes_are_self_excluding_and_deterministic() -> None:
    original: dict[str, Any] = {
        "payload": {"z": 2, "a": 1},
        "result_sha256": "0" * 64,
    }
    bound = bind_document_sha256(original, "result_sha256")

    verify_document_sha256(bound, "result_sha256")
    assert original["result_sha256"] == "0" * 64
    changed = json.loads(json.dumps(bound))
    changed["payload"]["a"] = 9
    with pytest.raises(E1ArtifactError) as exc_info:
        verify_document_sha256(changed, "result_sha256")
    _assert_error_code(exc_info, "HASH_MISMATCH")

    first = {
        "stable": {"value": 1, "generated_at": "nested-volatile"},
        "evaluation_run_id": "run-1",
        "generated_at": "2026-07-31T00:00:00Z",
        "duration_ms": 10,
        "local_absolute_paths": ["/first"],
    }
    second = {
        **first,
        "evaluation_run_id": "run-2",
        "generated_at": "2026-08-01T00:00:00Z",
        "duration_ms": 999,
        "local_absolute_paths": ["/second"],
    }
    first_projection = deterministic_projection(first)
    second_projection = deterministic_projection(second)
    assert first_projection == second_projection
    assert first_projection.document["stable"]["generated_at"] == "nested-volatile"
    assert DEFAULT_VOLATILE_FIELDS.isdisjoint(first_projection.document)
