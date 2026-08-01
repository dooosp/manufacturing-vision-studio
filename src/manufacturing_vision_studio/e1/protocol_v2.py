"""Strict loader and immutable historical bindings for E1 v2."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from manufacturing_vision_studio.canonical import canonical_json_hash
from manufacturing_vision_studio.e1.domain import CadRevision, CaseGroup, FeatureRegion, ViewId
from manufacturing_vision_studio.e1.domain_v2 import EvaluationScope, FeatureOwnershipConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_E1_V2_CONFIG_PATH = PROJECT_ROOT / "configs" / "evaluation" / "e1-v2.json"
DEFAULT_RETIRED_V1_MEMBERSHIP_PATH = (
    PROJECT_ROOT / "configs" / "evaluation" / "e1-v1-retired-release-membership.json"
)
DEFAULT_V1_HISTORY_INTEGRITY_PATH = (
    PROJECT_ROOT / "configs" / "evaluation" / "e1-v1-history-integrity.json"
)

_EXPECTED_COUNTS = {
    EvaluationScope.DEVELOPMENT: (24, 30, 60, 6, 120),
    EvaluationScope.SMOKE: (8, 12, 24, 4, 48),
    EvaluationScope.CALIBRATION: (24, 30, 60, 6, 120),
    EvaluationScope.RELEASE_TEST: (48, 60, 120, 12, 240),
}
_EXPECTED_SEED_STARTS = {
    "development": (400000, 410000, 420000, 430000),
    "smoke": (440000, 450000, 460000, 470000),
    "calibration": (500000, 510000, 520000, 530000),
    "release_test": (700000, 710000, 720000, 730000),
}
_EXPECTED_GATES = {
    "medium_high_defect_recall": ("gte", 0.9),
    "nuisance_only_false_positive_rate": ("lte", 0.05),
    "positive_case_median_dice": ("gte", 0.7),
    "affected_feature_mapping_accuracy": ("gte", 0.95),
    "revision_mismatch_publication_count": ("eq", 0),
    "corrupted_evidence_publication_count": ("eq", 0),
    "bundle_verify_reimport_rate": ("gte", 1.0),
    "dataset_split_hash_overlap": ("eq", 0),
    "same_seed_manifest_equivalence": ("is_true", True),
    "v0_1_regression": ("is_true", True),
}


class E1V2ProtocolError(ValueError):
    """A v2 protocol or immutable v1 historical record is malformed."""


@dataclass(frozen=True, slots=True)
class E1V2Protocol:
    source_path: Path
    schema_path: Path
    _document: dict[str, Any] = field(repr=False)
    configuration_sha256: str

    @classmethod
    def from_path(cls, path: Path) -> E1V2Protocol:
        document = _load_json_object(path)
        schema_path = _local_schema_path(path, document)
        schema = _load_json_object(schema_path)
        try:
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(document)
        except Exception as exc:
            raise E1V2ProtocolError(f"E1 v2 configuration failed schema validation: {exc}") from exc
        _validate_protocol_document(document)
        return cls(
            source_path=path,
            schema_path=schema_path,
            _document=document,
            configuration_sha256=canonical_json_hash(document),
        )

    @property
    def document(self) -> dict[str, Any]:
        return deepcopy(self._document)

    @property
    def protocol_version(self) -> str:
        return _string(self._document, "protocol_version")

    @property
    def dataset_version(self) -> str:
        return _string(self._document, "dataset_version")

    @property
    def pipeline_version(self) -> str:
        return _string(_object(self._document, "evaluation_pipeline"), "pipeline_version")

    @property
    def model_version(self) -> str:
        return _string(_object(self._document, "evaluation_pipeline"), "model_version")

    @property
    def generator_version(self) -> str:
        return _string(_object(self._document, "generator"), "generator_version")

    @property
    def scope_counts(self) -> dict[EvaluationScope, int]:
        scopes = _object(self._document, "scopes")
        return {
            scope: _integer(_object(scopes, scope.value), "case_count") for scope in EvaluationScope
        }

    @property
    def seed_starts(self) -> dict[str, tuple[int, int, int, int]]:
        blocks = _object(_object(self._document, "generator"), "seed_blocks")
        return {
            scope.value: cast(
                tuple[int, int, int, int],
                tuple(
                    _integer(_object(_object(blocks, scope.value), group.value), "start")
                    for group in CaseGroup
                ),
            )
            for scope in EvaluationScope
        }

    @property
    def case_id_format(self) -> str:
        return _string(_object(self._document, "generator"), "case_id_format")

    @property
    def recipe_version(self) -> str:
        return _string(_object(self._document, "generator"), "recipe_version")

    def feature_ownership(
        self,
        cad_revision: CadRevision | str,
        view_id: ViewId | str,
    ) -> FeatureOwnershipConfig:
        """Return the protocol-owned exclusive feature layout for one rendered view."""

        try:
            revision = CadRevision(cad_revision)
            view = ViewId(view_id)
        except ValueError as exc:
            raise E1V2ProtocolError("feature ownership revision or view is invalid") from exc
        ownership = _object(self._document, "feature_ownership")
        feature_ids = tuple(_string_list(ownership, "feature_ids"))
        priority = tuple(_string_list(ownership, "priority"))
        raw_boxes = _object(_object(_object(ownership, "by_revision"), revision.value), view.value)
        boxes: dict[str, FeatureRegion] = {}
        for feature_id in feature_ids:
            raw_box = raw_boxes.get(feature_id)
            if (
                not isinstance(raw_box, list)
                or len(raw_box) != 4
                or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    for value in raw_box
                )
            ):
                raise E1V2ProtocolError(f"feature ownership box is invalid for {feature_id!r}")
            boxes[feature_id] = cast(FeatureRegion, tuple(float(value) for value in raw_box))
        return FeatureOwnershipConfig(
            algorithm=_string(ownership, "algorithm"),
            cad_revision=revision,
            view_id=view,
            feature_ids=feature_ids,
            priority=priority,
            feature_boxes=boxes,
        )

    def scope_group_count(self, scope: EvaluationScope, group: CaseGroup) -> int:
        return _integer(_object(_object(self._document, "scopes"), scope.value), group.value)

    def seed_block(self, scope: EvaluationScope, group: CaseGroup) -> tuple[str, int, int]:
        raw = _object(_object(_object(self._document, "generator"), "seed_blocks"), scope.value)
        block = _object(raw, group.value)
        return _string(block, "seed_family"), _integer(block, "start"), _integer(block, "count")

    def case_binding_sha256(
        self,
        *,
        scope: EvaluationScope,
        case_id: str,
        recipe_id: str,
        seed_family: str,
        seed: int,
        reference_sha256: str,
        inspection_sha256: str,
        authoritative_mask_sha256: str,
        expected_outcome: str,
        defect_id: str | None,
    ) -> str:
        return canonical_json_hash(
            {
                "scope": scope.value,
                "case_id": case_id,
                "recipe_id": recipe_id,
                "seed_family": seed_family,
                "seed": seed,
                "reference_sha256": reference_sha256,
                "inspection_sha256": inspection_sha256,
                "authoritative_mask_sha256": authoritative_mask_sha256,
                "expected_outcome": expected_outcome,
                "defect_id": defect_id,
            }
        )


@dataclass(frozen=True, slots=True)
class RetiredV1ReleaseMembership:
    source_path: Path
    members: tuple[dict[str, object], ...]
    calibration_member_count: int
    mini_test_member_count: int


def load_e1_v2_protocol(path: Path | str = DEFAULT_E1_V2_CONFIG_PATH) -> E1V2Protocol:
    return E1V2Protocol.from_path(Path(path).expanduser().resolve())


def load_retired_v1_release_membership(
    path: Path | str = DEFAULT_RETIRED_V1_MEMBERSHIP_PATH,
) -> RetiredV1ReleaseMembership:
    source_path = Path(path).expanduser().resolve()
    document = _load_json_object(source_path)
    claimed_hash = document.get("membership_sha256")
    if not isinstance(claimed_hash, str):
        raise E1V2ProtocolError("retired v1 membership lacks a self hash")
    projection = {key: value for key, value in document.items() if key != "membership_sha256"}
    if canonical_json_hash(projection) != claimed_hash:
        raise E1V2ProtocolError("retired v1 membership self hash does not match")
    if document.get("v1_protocol_id") != "mvs-e1":
        raise E1V2ProtocolError("retired v1 membership protocol ID binding is invalid")
    if document.get("v1_protocol_version") != "1.3.0":
        raise E1V2ProtocolError("retired v1 membership protocol binding is invalid")
    if document.get("v1_configuration_sha256") != (
        "140887fb9e9980c8f7854d2d9f8b0a927aee4994fb74ee2535aa109f19fa7d99"
    ):
        raise E1V2ProtocolError("retired v1 membership config binding is invalid")
    if document.get("mini_manifest_sha256") != (
        "00e6ac243217a90f04776855354c2d30de387245b9306c46c22ef992fa0159e3"
    ) or document.get("full_manifest_sha256") != (
        "1a8f6a32b7e98fe51c72f711f172effcbf04eeda00d0d4fdc8fe5f3ba36dbbc2"
    ):
        raise E1V2ProtocolError("retired v1 membership historical manifest binding is invalid")
    members = document.get("members")
    if not isinstance(members, list) or not all(isinstance(item, dict) for item in members):
        raise E1V2ProtocolError("retired v1 membership members are invalid")
    canonical_members = tuple(cast(dict[str, object], item) for item in members)
    _validate_retired_members(canonical_members)
    calibration_count = sum(item["kind"] == "calibration" for item in canonical_members)
    mini_count = sum(item["kind"] == "mini_test" for item in canonical_members)
    if calibration_count != 120 or mini_count != 24:
        raise E1V2ProtocolError("retired v1 membership counts are invalid")
    return RetiredV1ReleaseMembership(source_path, canonical_members, calibration_count, mini_count)


def verify_e1_v1_history(
    path: Path | str = DEFAULT_V1_HISTORY_INTEGRITY_PATH,
) -> dict[str, object]:
    document = _load_json_object(Path(path).expanduser().resolve())
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list):
        raise E1V2ProtocolError("v1 history integrity artifacts are invalid")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise E1V2ProtocolError("v1 history integrity artifact is invalid")
        relative_path = artifact.get("path")
        expected_sha = artifact.get("sha256")
        if not isinstance(relative_path, str) or not isinstance(expected_sha, str):
            raise E1V2ProtocolError("v1 history integrity artifact binding is invalid")
        actual_sha = hashlib.sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise E1V2ProtocolError(f"v1 history hash mismatch: {relative_path}")
        expected_fields = artifact.get("expected_fields", {})
        if expected_fields:
            parsed = _load_json_object(PROJECT_ROOT / relative_path)
            if not isinstance(expected_fields, dict) or any(
                parsed.get(key) != value for key, value in expected_fields.items()
            ):
                raise E1V2ProtocolError(f"v1 history identity mismatch: {relative_path}")
    preflight = document.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("v0_1_tag") != "v0.1.0":
        raise E1V2ProtocolError("v1 history preflight identity is invalid")
    if preflight.get("v0_1_tag_object") != "67bd8af8d6bfdbcb5ff2654fd37b797dc7c75f3d":
        raise E1V2ProtocolError("v1 history v0.1 tag object is invalid")
    if preflight.get("v0_1_commit") != "cf7b9ac37d0533f656068199d3275410cf8cc2f8":
        raise E1V2ProtocolError("v1 history v0.1 commit is invalid")
    if preflight.get("e1_evaluation_commit") != "2f87b885b29c12468effea927279d27424eaa340":
        raise E1V2ProtocolError("v1 history evaluation commit is invalid")
    if _git_identity("v0.1.0^{tag}") != preflight["v0_1_tag_object"]:
        raise E1V2ProtocolError("v1 history v0.1 tag object does not resolve")
    if _git_identity("v0.1.0^{commit}") != preflight["v0_1_commit"]:
        raise E1V2ProtocolError("v1 history v0.1 commit does not resolve")
    if (
        _git_identity("2f87b885b29c12468effea927279d27424eaa340^{commit}")
        != preflight["e1_evaluation_commit"]
    ):
        raise E1V2ProtocolError("v1 history evaluation commit does not resolve")
    return {"verdict": "HOLD", "artifact_count": len(artifacts)}


def _validate_protocol_document(document: Mapping[str, Any]) -> None:
    if document.get("protocol_version") != "2.0.0" or document.get("dataset_version") != "2.0.0":
        raise E1V2ProtocolError("v2 protocol and dataset versions must be 2.0.0")
    if (
        _string(_object(document, "evaluation_pipeline"), "pipeline_version") != "1.2.0"
        or _string(_object(document, "evaluation_pipeline"), "model_version") != "1.2.0"
    ):
        raise E1V2ProtocolError("v2 pipeline and model versions must be 1.2.0")
    scopes = _object(document, "scopes")
    generator = _object(document, "generator")
    blocks = _object(generator, "seed_blocks")
    for scope, expected in _EXPECTED_COUNTS.items():
        scope_record = _object(scopes, scope.value)
        count_names = (*(group.value for group in CaseGroup), "case_count")
        actual = tuple(_integer(scope_record, name) for name in count_names)
        if actual != expected or sum(actual[:4]) != actual[4]:
            raise E1V2ProtocolError(f"v2 scope counts are invalid for {scope.value}")
        starts = tuple(
            _integer(_object(_object(blocks, scope.value), group.value), "start")
            for group in CaseGroup
        )
        if starts != _EXPECTED_SEED_STARTS[scope.value]:
            raise E1V2ProtocolError(f"v2 seed starts are invalid for {scope.value}")
        for group in CaseGroup:
            family, _, count = _seed_block(_object(blocks, scope.value), group)
            if count != _integer(scope_record, group.value) or not family.endswith("-v2"):
                raise E1V2ProtocolError(f"v2 seed block is invalid for {scope.value}/{group.value}")
    if _number(_object(document, "threshold_selection"), "locked_image_threshold") != 0.0025:
        raise E1V2ProtocolError("v2 locked image threshold must remain 0.0025")
    _validate_feature_ownership(_object(document, "feature_ownership"))
    gates = document.get("acceptance_gates")
    if not isinstance(gates, list):
        raise E1V2ProtocolError("v2 acceptance gates are invalid")
    actual_gates = {
        _string(cast(dict[str, Any], gate), "gate_id"): (
            _string(cast(dict[str, Any], gate), "operator"),
            cast(dict[str, Any], gate).get("threshold"),
        )
        for gate in gates
        if isinstance(gate, dict)
    }
    if actual_gates != _EXPECTED_GATES:
        raise E1V2ProtocolError("v2 acceptance gates changed from the v1 HOLD boundary")


def _validate_feature_ownership(ownership: Mapping[str, Any]) -> None:
    expected_ids = ("bottom_edge", "hole_left", "hole_right", "top_edge", "top_face")
    expected_priority = ("hole_left", "hole_right", "top_edge", "bottom_edge", "top_face")
    if _string(ownership, "algorithm") != "exclusive-final-mask-owner-v1":
        raise E1V2ProtocolError("v2 feature ownership algorithm is invalid")
    if tuple(_string_list(ownership, "feature_ids")) != expected_ids:
        raise E1V2ProtocolError("v2 feature ownership feature IDs are invalid")
    if tuple(_string_list(ownership, "priority")) != expected_priority:
        raise E1V2ProtocolError("v2 feature ownership priority is invalid")
    by_revision = _object(ownership, "by_revision")
    configs: dict[tuple[CadRevision, ViewId], FeatureOwnershipConfig] = {}
    for revision in CadRevision:
        for view in ViewId:
            raw_boxes = _object(_object(by_revision, revision.value), view.value)
            boxes: dict[str, FeatureRegion] = {}
            for feature_id in expected_ids:
                raw_box = raw_boxes.get(feature_id)
                if (
                    not isinstance(raw_box, list)
                    or len(raw_box) != 4
                    or any(
                        isinstance(value, bool) or not isinstance(value, (int, float))
                        for value in raw_box
                    )
                ):
                    raise E1V2ProtocolError(
                        f"v2 feature ownership box is invalid for {feature_id!r}"
                    )
                boxes[feature_id] = cast(FeatureRegion, tuple(float(value) for value in raw_box))
            try:
                configs[(revision, view)] = FeatureOwnershipConfig(
                    algorithm=_string(ownership, "algorithm"),
                    cad_revision=revision,
                    view_id=view,
                    feature_ids=expected_ids,
                    priority=expected_priority,
                    feature_boxes=boxes,
                )
            except ValueError as exc:
                raise E1V2ProtocolError("v2 feature ownership layout is invalid") from exc
    for view in ViewId:
        rev_a = configs[(CadRevision.REV_A, view)].feature_boxes
        rev_b = configs[(CadRevision.REV_B, view)].feature_boxes
        for feature_id in expected_ids:
            expected = (
                tuple(
                    value + (4 / 512 if index in {0, 2} else 0)
                    for index, value in enumerate(rev_a[feature_id])
                )
                if feature_id == "hole_right"
                else rev_a[feature_id]
            )
            if rev_b[feature_id] != expected:
                raise E1V2ProtocolError(
                    "v2 revision geometry does not match the declared +4 px delta"
                )


def _validate_retired_members(members: Sequence[dict[str, object]]) -> None:
    keys = ("case_id", "recipe_id", "seed_family", "seed", "kind", "group", "expected_outcome")
    identities: set[tuple[object, ...]] = set()
    for member in members:
        if any(key not in member for key in keys) or member.get("kind") not in {
            "calibration",
            "mini_test",
        }:
            raise E1V2ProtocolError("retired v1 member is malformed")
        identity = (member["case_id"], member["recipe_id"], member["seed_family"], member["seed"])
        if identity in identities:
            raise E1V2ProtocolError("retired v1 membership has duplicate identities")
        identities.add(identity)


def _load_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        loaded: dict[str, Any] = {}
        for key, value in pairs:
            if key in loaded:
                raise ValueError(f"duplicate JSON key: {key}")
            loaded[key] = value
        return loaded

    try:
        loaded = json.loads(
            path.read_bytes(),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise E1V2ProtocolError(f"E1 JSON could not be loaded from {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise E1V2ProtocolError(f"E1 JSON root must be an object: {path}")
    return cast(dict[str, Any], loaded)


def _local_schema_path(config_path: Path, document: Mapping[str, Any]) -> Path:
    reference = document.get("$schema")
    if (
        not isinstance(reference, str)
        or not reference
        or "://" in reference
        or reference.startswith("/")
    ):
        raise E1V2ProtocolError("v2 schema reference must be a local relative path")
    schema_path = (config_path.parent / reference).resolve()
    if PROJECT_ROOT not in schema_path.parents:
        raise E1V2ProtocolError("v2 schema reference escapes the project")
    return schema_path


def _git_identity(revision: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", revision],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise E1V2ProtocolError(f"v1 history git identity does not resolve: {revision}")
    return completed.stdout.strip()


def _object(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise E1V2ProtocolError(f"{key} must be an object")
    return cast(dict[str, Any], item)


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise E1V2ProtocolError(f"{key} must be a non-empty string")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise E1V2ProtocolError(f"{key} must be an integer")
    return item


def _string_list(value: Mapping[str, Any], key: str) -> list[str]:
    item = value.get(key)
    if (
        not isinstance(item, list)
        or not item
        or not all(isinstance(entry, str) and entry for entry in item)
    ):
        raise E1V2ProtocolError(f"{key} must be a non-empty string array")
    return cast(list[str], item)


def _number(value: Mapping[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise E1V2ProtocolError(f"{key} must be numeric")
    return float(item)


def _seed_block(value: Mapping[str, Any], group: CaseGroup) -> tuple[str, int, int]:
    block = _object(value, group.value)
    return _string(block, "seed_family"), _integer(block, "start"), _integer(block, "count")
