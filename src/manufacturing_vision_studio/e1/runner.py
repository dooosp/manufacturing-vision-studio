"""End-to-end deterministic runner for the frozen E1 evaluation protocol."""

from __future__ import annotations

import io
import os
import platform
import subprocess
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import PIL
from PIL import Image

from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.artifacts import (
    DEFAULT_VOLATILE_FIELDS,
    ArtifactRecord,
    E1ArtifactError,
    E1ArtifactStore,
    finalize_case_manifest,
    finalize_evaluation_result,
    finalize_threshold_lock,
)
from manufacturing_vision_studio.e1.baseline import evaluate_v0_1_baseline
from manufacturing_vision_studio.e1.domain import (
    CaseGroup,
    DatasetProfile,
    DatasetSplit,
    E1CasePlan,
    E1GeneratedCase,
)
from manufacturing_vision_studio.e1.generator import E1Generator
from manufacturing_vision_studio.e1.metrics import (
    EvaluationChecks,
    EvaluationObservation,
    evaluate,
)
from manufacturing_vision_studio.e1.policy import E1CaseResult, E1InferencePolicy
from manufacturing_vision_studio.e1.protocol import E1Protocol, load_e1_protocol
from manufacturing_vision_studio.e1.trust_boundaries import (
    TrustBoundaryReport,
    TrustBoundaryResult,
    run_trust_boundary_suite,
)
from manufacturing_vision_studio.errors import UnsafeInputError
from manufacturing_vision_studio.images import ImageIngestor

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = "manifest.json"
CALIBRATION_RESULT_PATH = "calibration-result.json"
THRESHOLD_LOCK_PATH = "threshold-lock.json"
RESULT_PATH = "result.json"
INVENTORY_PATH = "inventory.json"
REPEATABILITY_MANIFEST_PATHS = (
    "repeatability/full-manifest-run-1.json",
    "repeatability/full-manifest-run-2.json",
)
ERROR_GALLERY_MAX_CASES = 12

GalleryCategory = Literal[
    "false_positive",
    "false_negative",
    "low_dice",
    "wrong_feature_mapping",
    "unsupported_view",
    "revision_mismatch",
    "bundle_verification_failure",
]

_GROUP_NAMES = ("clean", "nuisance", "defect", "trust_boundary")
_SPLIT_NAMES = ("development", "calibration", "test")
_GALLERY_PRIORITY: dict[GalleryCategory, int] = {
    "false_positive": 0,
    "false_negative": 1,
    "low_dice": 2,
    "wrong_feature_mapping": 3,
    "revision_mismatch": 4,
    "unsupported_view": 5,
    "bundle_verification_failure": 6,
}
_TRUST_GALLERY_CATEGORIES: tuple[tuple[str, GalleryCategory], ...] = (
    ("revision_mismatch", "revision_mismatch"),
    ("unsupported_view_or_extreme_nuisance", "unsupported_view"),
    ("incomplete_evidence_bundle", "bundle_verification_failure"),
)


@dataclass(frozen=True, slots=True)
class _GalleryCandidate:
    generated: E1GeneratedCase
    result: E1CaseResult
    category: GalleryCategory


@dataclass(frozen=True, slots=True)
class _SplitExecution:
    observations: tuple[EvaluationObservation, ...]
    result_records: tuple[dict[str, Any], ...]
    gallery_candidates: tuple[_GalleryCandidate, ...]


def run_e1_evaluation(
    profile: DatasetProfile | str,
    output_root: Path | str,
    *,
    bootstrap_replicates: int = 10_000,
    bootstrap_seed: int = 424_242,
    protocol: E1Protocol | None = None,
) -> dict[str, Any]:
    """Run one immutable mini or full E1 evaluation and return its verified result.

    The profile is published below ``output_root/<profile>``. Test inference and
    trust-boundary execution occur only after the four calibration gates produce
    a persisted ``LOCKED`` threshold artifact.
    """

    resolved_profile = DatasetProfile(profile)
    _validate_bootstrap_arguments(bootstrap_replicates, bootstrap_seed)
    active_protocol = protocol or load_e1_protocol()
    code = _code_binding()
    started = time.monotonic()
    run_id = f"e1-{resolved_profile.value}-{uuid.uuid4().hex}"

    allowed_root = Path(os.path.abspath(os.fspath(Path(output_root).expanduser())))
    profile_root = allowed_root / resolved_profile.value
    store = E1ArtifactStore(profile_root, allowed_root=allowed_root)
    generator = E1Generator(active_protocol)
    plans = generator.plan_cases(resolved_profile)

    first_manifest = _generate_manifest(generator, plans, resolved_profile, active_protocol)
    if resolved_profile is DatasetProfile.FULL:
        first_full_manifest = first_manifest
    else:
        full_plans = generator.plan_cases(DatasetProfile.FULL)
        first_full_manifest = _generate_manifest(
            generator, full_plans, DatasetProfile.FULL, active_protocol
        )
    second_full_manifest = _generate_manifest(
        generator,
        generator.plan_cases(DatasetProfile.FULL),
        DatasetProfile.FULL,
        active_protocol,
    )
    _verify_profile_manifest_binding(first_manifest, first_full_manifest)
    same_seed_manifest_equivalence = canonical_json_bytes(
        first_full_manifest
    ) == canonical_json_bytes(second_full_manifest)
    # The repeatability gate is deliberately the two-run FULL finalized-manifest
    # projection. It does not claim a second model/metric execution.
    full_manifest_projection_sha256s = [
        cast(str, first_full_manifest["manifest_sha256"]),
        cast(str, second_full_manifest["manifest_sha256"]),
    ]
    store.write_json(MANIFEST_PATH, first_manifest, schema_name="case-manifest")
    store.write_json(
        REPEATABILITY_MANIFEST_PATHS[0],
        first_full_manifest,
        schema_name="case-manifest",
    )
    store.write_json(
        REPEATABILITY_MANIFEST_PATHS[1],
        second_full_manifest,
        schema_name="case-manifest",
    )
    manifest_cases = {
        cast(str, case["case_id"]): case
        for case in cast(list[dict[str, Any]], first_manifest["cases"])
    }
    split_hash_overlap = _split_hash_overlap_count(
        cast(list[dict[str, Any]], first_manifest["cases"]), active_protocol
    )

    policy = E1InferencePolicy(active_protocol)
    calibration = _execute_inference_split(
        generator,
        policy,
        plans,
        DatasetSplit.CALIBRATION,
        manifest_cases,
        collect_gallery=False,
    )
    acceptance_gates = cast(list[dict[str, Any]], active_protocol.document["acceptance_gates"])
    calibration_metrics = evaluate(
        list(calibration.observations),
        EvaluationChecks(
            bundle_attempts=1,
            bundle_successes=0,
            split_hash_overlap=split_hash_overlap,
            same_seed_manifest_equivalence=same_seed_manifest_equivalence,
            v0_1_regression=False,
        ),
        acceptance_gates[:4],
        evaluation_split="calibration",
        bootstrap_seed=bootstrap_seed,
        bootstrap_replicates=bootstrap_replicates,
    )
    calibration_document = _calibration_result_document(
        resolved_profile,
        active_protocol,
        first_manifest,
        calibration,
        calibration_metrics,
    )
    calibration_record = store.write_json(CALIBRATION_RESULT_PATH, calibration_document)
    threshold_lock = _threshold_lock_document(
        resolved_profile,
        active_protocol,
        code,
        cast(str, first_manifest["manifest_sha256"]),
        calibration_record.sha256,
        calibration_metrics,
    )
    store.write_json(THRESHOLD_LOCK_PATH, threshold_lock, schema_name="threshold-lock")

    common = _result_document_common(
        resolved_profile,
        active_protocol,
        policy,
        code,
        first_manifest,
        threshold_lock,
        run_id=run_id,
        profile_root=store.root,
        full_manifest_projection_sha256s=full_manifest_projection_sha256s,
    )
    members = [
        MANIFEST_PATH,
        *REPEATABILITY_MANIFEST_PATHS,
        CALIBRATION_RESULT_PATH,
        THRESHOLD_LOCK_PATH,
    ]
    if threshold_lock["lock_status"] == "HOLD":
        result_document = {
            **common,
            "generated_at": _utc_now(),
            "duration_ms": _duration_ms(started),
            "evaluation_status": "CALIBRATION_HOLD",
            "metrics": None,
            "error_gallery": [],
            "verdict": "HOLD",
            "deterministic_projection_sha256": "0" * 64,
            "result_sha256": "0" * 64,
        }
        result = finalize_evaluation_result(result_document)
        store.write_json(RESULT_PATH, result, schema_name="evaluation-result")
        members.append(RESULT_PATH)
        store.write_inventory(INVENTORY_PATH, members)
        return verify_e1_results(store.root)

    # This branch is intentionally unreachable until the persisted lock allows it.
    test_execution = _execute_inference_split(
        generator,
        policy,
        plans,
        DatasetSplit.TEST,
        manifest_cases,
        collect_gallery=True,
    )
    with tempfile.TemporaryDirectory(prefix=".trust-boundary-", dir=store.root) as work_root:
        trust_report = run_trust_boundary_suite(Path(work_root), protocol=active_protocol)
    trust_observations, trust_results = _profile_trust_observations(plans, trust_report)
    baseline = evaluate_v0_1_baseline(active_protocol)
    checks = EvaluationChecks(
        bundle_attempts=baseline.bundle_attempts,
        bundle_successes=baseline.bundle_successes,
        split_hash_overlap=split_hash_overlap,
        same_seed_manifest_equivalence=same_seed_manifest_equivalence,
        v0_1_regression=baseline.v0_1_regression,
    )
    metrics = evaluate(
        [*test_execution.observations, *trust_observations],
        checks,
        acceptance_gates,
        bootstrap_seed=bootstrap_seed,
        bootstrap_replicates=bootstrap_replicates,
    )
    gallery, asset_members = _write_error_gallery(
        store,
        resolved_profile,
        generator,
        manifest_cases,
        test_execution.gallery_candidates,
        plans,
        trust_results,
        image_threshold=policy.image_threshold,
    )
    members.extend(asset_members)
    result_document = {
        **common,
        "generated_at": _utc_now(),
        "duration_ms": _duration_ms(started),
        "evaluation_status": "COMPLETED",
        "metrics": metrics,
        "error_gallery": gallery,
        "verdict": metrics["verdict"],
        "deterministic_projection_sha256": "0" * 64,
        "result_sha256": "0" * 64,
    }
    result = finalize_evaluation_result(result_document)
    store.write_json(RESULT_PATH, result, schema_name="evaluation-result")
    members.append(RESULT_PATH)
    store.write_inventory(INVENTORY_PATH, members)
    return verify_e1_results(store.root)


def verify_e1_results(profile_root: Path | str) -> dict[str, Any]:
    """Verify an E1 result directory, its inventory, and all cross-artifact bindings."""

    root = Path(os.path.abspath(os.fspath(Path(profile_root).expanduser())))
    if not os.path.lexists(root):
        raise E1ArtifactError(
            "E1 result directory is missing",
            code="EVIDENCE_INCOMPLETE",
            details={"path": str(root)},
        )
    store = E1ArtifactStore(root)
    inventory = {record.path: record for record in store.verify_inventory(INVENTORY_PATH)}
    required = {
        MANIFEST_PATH,
        CALIBRATION_RESULT_PATH,
        THRESHOLD_LOCK_PATH,
        RESULT_PATH,
        *REPEATABILITY_MANIFEST_PATHS,
    }
    missing = sorted(required - inventory.keys())
    if missing:
        raise E1ArtifactError(
            "E1 result inventory is incomplete",
            code="EVIDENCE_INCOMPLETE",
            details={"missing": missing},
        )
    if any(inventory[path].media_type != "application/json" for path in required):
        raise E1ArtifactError("E1 primary artifact media type is invalid", code="SCHEMA_INVALID")

    manifest = store.read_json(
        MANIFEST_PATH,
        schema_name="case-manifest",
        expected_sha256=inventory[MANIFEST_PATH].sha256,
    )
    calibration = store.read_json(
        CALIBRATION_RESULT_PATH,
        expected_sha256=inventory[CALIBRATION_RESULT_PATH].sha256,
    )
    threshold_lock = store.read_json(
        THRESHOLD_LOCK_PATH,
        schema_name="threshold-lock",
        expected_sha256=inventory[THRESHOLD_LOCK_PATH].sha256,
    )
    result = store.read_json(
        RESULT_PATH,
        schema_name="evaluation-result",
        expected_sha256=inventory[RESULT_PATH].sha256,
    )
    repeatability_manifests = tuple(
        store.read_json(
            path,
            schema_name="case-manifest",
            expected_sha256=inventory[path].sha256,
        )
        for path in REPEATABILITY_MANIFEST_PATHS
    )
    try:
        _verify_cross_artifact_bindings(
            manifest,
            calibration,
            threshold_lock,
            result,
            store=store,
            repeatability_manifests=repeatability_manifests,
            calibration_result_sha256=inventory[CALIBRATION_RESULT_PATH].sha256,
            inventory=inventory,
        )
    except E1ArtifactError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise E1ArtifactError(
            "E1 cross-artifact binding is malformed", code="SCHEMA_INVALID"
        ) from exc
    return result


def _generate_manifest(
    generator: E1Generator,
    plans: Sequence[E1CasePlan],
    profile: DatasetProfile,
    protocol: E1Protocol,
) -> dict[str, Any]:
    cases = [generator.generate_case(plan).as_manifest_record() for plan in plans]
    document = {
        "schema_version": "1.0.0",
        "manifest_id": f"e1-{profile.value}-case-manifest-v1",
        "protocol": _protocol_binding(protocol),
        "generator": _generator_binding(protocol),
        "profile": profile.value,
        "counts": _manifest_counts(cases),
        "cases": cases,
        "manifest_sha256": "0" * 64,
    }
    return finalize_case_manifest(document)


def _manifest_counts(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    group_counts = Counter(cast(str, case["group"]) for case in cases)
    split_counts: dict[str, dict[str, Any]] = {}
    for split in _SPLIT_NAMES:
        selected = [case for case in cases if case["split"] == split]
        selected_groups = Counter(cast(str, case["group"]) for case in selected)
        split_counts[split] = {
            "case_count": len(selected),
            "group_counts": {group: selected_groups[group] for group in _GROUP_NAMES},
        }
    trust_count = group_counts["trust_boundary"]
    return {
        "case_count": len(cases),
        "inference_case_count": len(cases) - trust_count,
        "trust_case_count": trust_count,
        "group_counts": {group: group_counts[group] for group in _GROUP_NAMES},
        "split_counts": split_counts,
    }


def _execute_inference_split(
    generator: E1Generator,
    policy: E1InferencePolicy,
    plans: Sequence[E1CasePlan],
    split: DatasetSplit,
    manifest_cases: Mapping[str, Mapping[str, Any]],
    *,
    collect_gallery: bool,
) -> _SplitExecution:
    observations: list[EvaluationObservation] = []
    records: list[dict[str, Any]] = []
    gallery: list[_GalleryCandidate] = []
    for plan in plans:
        if plan.split is not split or plan.group is CaseGroup.TRUST_BOUNDARY:
            continue
        generated = generator.generate_case(plan)
        _verify_generated_manifest_binding(generated, manifest_cases)
        result = policy.inspect(generated)
        observations.append(result.as_observation(generated))
        records.append(result.as_record())
        if collect_gallery:
            category = _inference_gallery_category(result)
            if category is not None:
                gallery.append(_GalleryCandidate(generated, result, category))
                gallery.sort(
                    key=lambda item: (_GALLERY_PRIORITY[item.category], item.result.case_id)
                )
                del gallery[ERROR_GALLERY_MAX_CASES:]
    if not observations:
        raise E1ArtifactError(
            "E1 inference split contains no executable cases",
            code="EVIDENCE_INCOMPLETE",
            details={"split": split.value},
        )
    return _SplitExecution(tuple(observations), tuple(records), tuple(gallery))


def _verify_generated_manifest_binding(
    generated: E1GeneratedCase,
    manifest_cases: Mapping[str, Mapping[str, Any]],
) -> None:
    expected = manifest_cases.get(generated.plan.case_id)
    if expected is None or generated.as_manifest_record() != expected:
        raise E1ArtifactError(
            "Generated case changed after manifest publication",
            code="HASH_MISMATCH",
            details={"case_id": generated.plan.case_id},
        )


def _calibration_result_document(
    profile: DatasetProfile,
    protocol: E1Protocol,
    manifest: Mapping[str, Any],
    execution: _SplitExecution,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "calibration_id": f"e1-{profile.value}-calibration-v1",
        "protocol": _protocol_binding(protocol),
        "profile": profile.value,
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "evaluation_split": "calibration",
        "threshold_candidate": protocol.section("threshold_selection")["locked_image_threshold"],
        "observation_count": len(execution.observations),
        "case_results": list(execution.result_records),
        "metrics": metrics,
    }


def _threshold_lock_document(
    profile: DatasetProfile,
    protocol: E1Protocol,
    code: dict[str, Any],
    manifest_sha256: str,
    calibration_result_sha256: str,
    calibration_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    selection = protocol.section("threshold_selection")
    gates = _calibration_gate_records(calibration_metrics)
    locked = all(cast(bool, gate["passed"]) for gate in gates)
    document = {
        "schema_version": "1.0.0",
        "lock_id": f"e1-{profile.value}-threshold-lock-v1",
        "protocol": _protocol_binding(protocol),
        "profile": profile.value,
        "code_commit_sha": code["code_commit_sha"],
        "dirty_worktree": code["dirty_worktree"],
        "calibration_manifest_sha256": manifest_sha256,
        "calibration_result_sha256": calibration_result_sha256,
        "threshold_source_split": selection["threshold_source_split"],
        "selection_method": selection["selection_method"],
        "selection_candidates": selection["selection_candidates"],
        "locked_image_threshold": selection["locked_image_threshold"],
        "calibration_gate_results": gates,
        "lock_status": "LOCKED" if locked else "HOLD",
        "test_execution_allowed": locked,
        "failure_action": cast(dict[str, Any], selection["calibration_confirmation"])[
            "failure_action"
        ],
        "threshold_lock_sha256": "0" * 64,
    }
    return finalize_threshold_lock(document)


def _calibration_gate_records(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_gates = metrics.get("gates")
    if not isinstance(raw_gates, list) or len(raw_gates) != 4:
        raise E1ArtifactError(
            "Calibration metrics do not contain the four lock gates",
            code="EVIDENCE_INCOMPLETE",
        )
    records: list[dict[str, Any]] = []
    for raw in raw_gates:
        if not isinstance(raw, dict):
            raise E1ArtifactError("Calibration gate is malformed", code="SCHEMA_INVALID")
        passed = cast(bool, raw["passed"])
        observed = raw["observed"]
        reason = None
        if not passed:
            reason = "metric_undefined" if observed is None else "gate_threshold_not_met"
        records.append(
            {
                "gate_id": raw["gate_id"],
                "operator": raw["operator"],
                "threshold": raw["threshold"],
                "observed": observed,
                "passed": passed,
                "reason": reason,
            }
        )
    return records


def _profile_trust_observations(
    plans: Sequence[E1CasePlan],
    report: TrustBoundaryReport,
) -> tuple[tuple[EvaluationObservation, ...], dict[str, TrustBoundaryResult]]:
    result_by_scenario = {result.scenario_id: result for result in report.results}
    observations: list[EvaluationObservation] = []
    selected: dict[str, TrustBoundaryResult] = {}
    for plan in plans:
        if plan.group is not CaseGroup.TRUST_BOUNDARY:
            continue
        specification = plan.trust_boundary
        if specification is None:  # defensive; the domain contract already rejects this
            raise E1ArtifactError("Trust plan is incomplete", code="EVIDENCE_INCOMPLETE")
        result = result_by_scenario.get(specification.scenario_id)
        if result is None or result.split != plan.split.value:
            raise E1ArtifactError(
                "Trust-boundary result is missing or split-mismatched",
                code="EVIDENCE_INCOMPLETE",
                details={"scenario_id": specification.scenario_id},
            )
        selected[result.scenario_id] = result
        observations.append(
            EvaluationObservation(
                case_id=plan.case_id,
                split=plan.split.value,
                group="trust_boundary",
                expected_outcome="ABSTAIN",
                actual_outcome=result.actual_outcome,
                anomaly_score=None,
                cad_revision=plan.cad_revision.value,
                view_id=plan.view_id.value,
                expected_abstention_reason=result.expected_error_code,
                abstention_reason=result.actual_error_code,
                trust_scenario=result.scenario_id,
                published=result.publication_count > 0,
            )
        )
    if len(observations) != sum(plan.group is CaseGroup.TRUST_BOUNDARY for plan in plans):
        raise E1ArtifactError("Trust observation count is incomplete", code="EVIDENCE_INCOMPLETE")
    return tuple(observations), selected


def _split_hash_overlap_count(cases: Sequence[Mapping[str, Any]], protocol: E1Protocol) -> int:
    leak_keys = cast(list[str], protocol.section("split_rules")["leak_keys"])
    owners: dict[tuple[str, str], set[str]] = {}
    for case in cases:
        source_hashes = cast(Mapping[str, Any], case["source_hashes"])
        for key in leak_keys:
            raw_value = source_hashes.get(key) if key.endswith("_sha256") else case.get(key)
            if not isinstance(raw_value, str) or not raw_value:
                raise E1ArtifactError(
                    "Split leak-key binding is incomplete",
                    code="EVIDENCE_INCOMPLETE",
                    details={"key": key, "case_id": case.get("case_id")},
                )
            owners.setdefault((key, raw_value), set()).add(cast(str, case["split"]))
    return sum(len(splits) * (len(splits) - 1) // 2 for splits in owners.values())


def _result_document_common(
    profile: DatasetProfile,
    protocol: E1Protocol,
    policy: E1InferencePolicy,
    code: dict[str, Any],
    manifest: Mapping[str, Any],
    threshold_lock: Mapping[str, Any],
    *,
    run_id: str,
    profile_root: Path,
    full_manifest_projection_sha256s: list[str],
) -> dict[str, Any]:
    model = policy.model_record()
    counts = cast(Mapping[str, Any], manifest["counts"])
    document = protocol.document
    return {
        "schema_version": "1.0.0",
        "result_id": f"e1-{profile.value}-result-v1",
        "evaluation_run_id": run_id,
        "local_absolute_paths": [str(profile_root)],
        "profile": profile.value,
        "protocol": _protocol_binding(protocol),
        "code": code,
        "generator": _generator_binding(protocol),
        "dataset": {
            "dataset_id": f"e1-{profile.value}",
            "dataset_version": "1.0.0",
            "dataset_manifest_sha256": manifest["manifest_sha256"],
            "case_count": counts["case_count"],
            "inference_case_count": counts["inference_case_count"],
            "trust_case_count": counts["trust_case_count"],
        },
        "pipeline": {
            "pipeline_id": model["pipeline_id"],
            "pipeline_version": model["pipeline_version"],
        },
        "model": {
            "model_id": model["model_id"],
            "model_version": model["model_version"],
            "model_artifact_sha256": model["model_artifact_sha256"],
        },
        "configuration_sha256": model["configuration_sha256"],
        "threshold": {
            "lock_id": threshold_lock["lock_id"],
            "threshold_lock_sha256": threshold_lock["threshold_lock_sha256"],
            "lock_status": threshold_lock["lock_status"],
            "locked_image_threshold": model["locked_image_threshold"],
            "threshold_source_split": model["threshold_source_split"],
        },
        "execution_environment": _execution_environment(),
        "reproducibility": {
            "repeat_count": 2,
            "equivalent": (
                full_manifest_projection_sha256s[0] == full_manifest_projection_sha256s[1]
            ),
            # Schema v1 retains this historical field name. Its values are the
            # two finalized FULL manifest canonical projection hashes.
            "deterministic_projection_sha256s": full_manifest_projection_sha256s,
            "volatile_fields_excluded": sorted(DEFAULT_VOLATILE_FIELDS),
        },
        "exclusions": cast(list[str], document["exclusions"]),
        "limitations": cast(list[str], document["limitations"]),
    }


def _inference_gallery_category(result: E1CaseResult) -> GalleryCategory | None:
    if result.expected_outcome == "NORMAL" and result.actual_outcome != "NORMAL":
        return "false_positive"
    if result.expected_outcome == "ANOMALY" and result.actual_outcome != "ANOMALY":
        return "false_negative"
    if result.expected_outcome != "ANOMALY":
        return None
    denominator = result.truth_positive_pixels + result.predicted_positive_pixels
    dice = 2 * result.intersection_pixels / denominator if denominator else 1.0
    if dice < 0.7:
        return "low_dice"
    if result.expected_feature_id != result.predicted_feature_id:
        return "wrong_feature_mapping"
    return None


def _write_error_gallery(
    store: E1ArtifactStore,
    profile: DatasetProfile,
    generator: E1Generator,
    manifest_cases: Mapping[str, Mapping[str, Any]],
    inference_candidates: Sequence[_GalleryCandidate],
    plans: Sequence[E1CasePlan],
    trust_results: Mapping[str, TrustBoundaryResult],
    *,
    image_threshold: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    gallery: list[dict[str, Any]] = []
    members: list[str] = []
    for candidate in inference_candidates[:ERROR_GALLERY_MAX_CASES]:
        record, paths = _write_inference_gallery_case(
            store, profile, candidate, image_threshold=image_threshold
        )
        gallery.append(record)
        members.extend(paths)

    plan_by_scenario = {
        plan.trust_boundary.scenario_id: plan for plan in plans if plan.trust_boundary is not None
    }
    for scenario_id, category in _TRUST_GALLERY_CATEGORIES:
        if len(gallery) >= ERROR_GALLERY_MAX_CASES:
            break
        plan = plan_by_scenario.get(scenario_id)
        trust_result = trust_results.get(scenario_id)
        if plan is None or trust_result is None:
            continue
        generated = generator.generate_case(plan)
        _verify_generated_manifest_binding(generated, manifest_cases)
        record, paths = _write_trust_gallery_case(
            store,
            profile,
            generated,
            trust_result,
            category,
            image_threshold=image_threshold,
        )
        gallery.append(record)
        members.extend(paths)
    return gallery, members


def _write_inference_gallery_case(
    store: E1ArtifactStore,
    profile: DatasetProfile,
    candidate: _GalleryCandidate,
    *,
    image_threshold: float,
) -> tuple[dict[str, Any], list[str]]:
    generated = candidate.generated
    result = candidate.result
    base = f"assets/{generated.plan.case_id}"
    payloads: list[tuple[str, bytes]] = [
        (f"{base}/reference.png", generated.reference_bytes),
        (f"{base}/inspection.png", generated.inspection_bytes),
        (f"{base}/authoritative-mask.png", generated.authoritative_mask_bytes),
    ]
    predicted_url: str | None = None
    overlay_url: str | None = None
    if result.predicted_mask_bytes is not None:
        predicted_path = f"{base}/predicted-mask.png"
        overlay_path = f"{base}/overlay.png"
        payloads.extend(
            [
                (predicted_path, result.predicted_mask_bytes),
                (
                    overlay_path,
                    _render_overlay(
                        generated.inspection_bytes,
                        generated.authoritative_mask_bytes,
                        result.predicted_mask_bytes,
                    ),
                ),
            ]
        )
        predicted_url = _asset_url(profile, generated.plan.case_id, "predicted-mask.png")
        overlay_url = _asset_url(profile, generated.plan.case_id, "overlay.png")
    for path, payload in payloads:
        store.write_bytes(path, payload)
    record = _gallery_record(
        generated,
        category=candidate.category,
        score=result.anomaly_score,
        threshold=image_threshold,
        expected_feature_id=result.expected_feature_id,
        predicted_feature_id=result.predicted_feature_id,
        failure_reason=result.abstention_reason or candidate.category,
        predicted_mask_sha256=result.predicted_mask_sha256,
        predicted_mask_url=predicted_url,
        overlay_url=overlay_url,
        profile=profile,
    )
    return record, [path for path, _ in payloads]


def _write_trust_gallery_case(
    store: E1ArtifactStore,
    profile: DatasetProfile,
    generated: E1GeneratedCase,
    result: TrustBoundaryResult,
    category: GalleryCategory,
    *,
    image_threshold: float,
) -> tuple[dict[str, Any], list[str]]:
    base = f"assets/{generated.plan.case_id}"
    payloads = [
        (f"{base}/reference.png", generated.reference_bytes),
        (f"{base}/inspection.png", generated.inspection_bytes),
        (f"{base}/authoritative-mask.png", generated.authoritative_mask_bytes),
    ]
    for path, payload in payloads:
        store.write_bytes(path, payload)
    record = _gallery_record(
        generated,
        category=category,
        score=None,
        threshold=image_threshold,
        expected_feature_id=None,
        predicted_feature_id=None,
        failure_reason=result.actual_error_code or "trust_boundary_was_not_rejected",
        predicted_mask_sha256=None,
        predicted_mask_url=None,
        overlay_url=None,
        profile=profile,
    )
    return record, [path for path, _ in payloads]


def _gallery_record(
    generated: E1GeneratedCase,
    *,
    category: GalleryCategory,
    score: float | None,
    threshold: float,
    expected_feature_id: str | None,
    predicted_feature_id: str | None,
    failure_reason: str | None,
    predicted_mask_sha256: str | None,
    predicted_mask_url: str | None,
    overlay_url: str | None,
    profile: DatasetProfile,
) -> dict[str, Any]:
    case_id = generated.plan.case_id
    return {
        "case_id": case_id,
        "category": category,
        "part_identity": {
            "part_id": generated.plan.part_id,
            "cad_revision": generated.plan.cad_revision.value,
        },
        "score": score,
        "threshold": threshold,
        "expected_feature_id": expected_feature_id,
        "predicted_feature_id": predicted_feature_id,
        "failure_reason": failure_reason,
        "source_hashes": {
            "reference_sha256": generated.reference_sha256,
            "inspection_sha256": generated.inspection_sha256,
            "authoritative_mask_sha256": generated.authoritative_mask_sha256,
            "predicted_mask_sha256": predicted_mask_sha256,
        },
        "assets": {
            "reference_image_url": _asset_url(profile, case_id, "reference.png"),
            "inspection_image_url": _asset_url(profile, case_id, "inspection.png"),
            "authoritative_mask_url": _asset_url(profile, case_id, "authoritative-mask.png"),
            "predicted_mask_url": predicted_mask_url,
            "overlay_url": overlay_url,
        },
    }


def _asset_url(profile: DatasetProfile, case_id: str, filename: str) -> str:
    return f"/api/v1/e1/evaluation/assets/{profile.value}/{case_id}/{filename}"


def _render_overlay(inspection: bytes, truth_mask: bytes, predicted_mask: bytes) -> bytes:
    with Image.open(io.BytesIO(inspection)) as inspection_image:
        base = np.asarray(inspection_image.convert("RGB"), dtype=np.uint8).copy()
    with Image.open(io.BytesIO(truth_mask)) as truth_image:
        truth = np.asarray(truth_image.convert("L"), dtype=np.uint8) > 0
    with Image.open(io.BytesIO(predicted_mask)) as predicted_image:
        predicted = np.asarray(predicted_image.convert("L"), dtype=np.uint8) > 0
    if base.shape[:2] != truth.shape or truth.shape != predicted.shape:
        raise E1ArtifactError("Gallery mask dimensions do not match", code="HASH_MISMATCH")
    truth_only = truth & ~predicted
    predicted_only = predicted & ~truth
    intersection = truth & predicted
    base[truth_only] = (0, 160, 255)
    base[predicted_only] = (255, 64, 64)
    base[intersection] = (255, 210, 0)
    return encode_png(Image.fromarray(base, mode="RGB"), mode="RGB")


def _verify_cross_artifact_bindings(
    manifest: Mapping[str, Any],
    calibration: Mapping[str, Any],
    threshold_lock: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    store: E1ArtifactStore,
    repeatability_manifests: Sequence[Mapping[str, Any]],
    calibration_result_sha256: str,
    inventory: Mapping[str, ArtifactRecord],
) -> None:
    profile = result["profile"]
    protocol = result["protocol"]
    if manifest["profile"] != profile or threshold_lock["profile"] != profile:
        raise E1ArtifactError("E1 artifact profiles do not match", code="HASH_MISMATCH")
    if manifest["protocol"] != protocol or threshold_lock["protocol"] != protocol:
        raise E1ArtifactError("E1 artifact protocol bindings do not match", code="HASH_MISMATCH")
    _verify_repeatability_bindings(result, manifest, repeatability_manifests)
    expected_calibration_keys = {
        "schema_version",
        "calibration_id",
        "protocol",
        "profile",
        "dataset_manifest_sha256",
        "evaluation_split",
        "threshold_candidate",
        "observation_count",
        "case_results",
        "metrics",
    }
    if set(calibration) != expected_calibration_keys:
        raise E1ArtifactError("Calibration artifact fields are invalid", code="SCHEMA_INVALID")
    case_results = calibration["case_results"]
    if not isinstance(case_results, list) or calibration["observation_count"] != len(case_results):
        raise E1ArtifactError("Calibration result count does not match", code="SCHEMA_INVALID")
    if any(
        not isinstance(item, dict) or item.get("split") != "calibration" for item in case_results
    ):
        raise E1ArtifactError("Calibration result contains another split", code="SCHEMA_INVALID")
    manifest_cases = cast(Sequence[Mapping[str, Any]], manifest["cases"])
    expected_calibration_cases = [
        case
        for case in manifest_cases
        if case["split"] == "calibration" and case["group"] != "trust_boundary"
    ]
    actual_case_ids = [cast(str, item["case_id"]) for item in case_results]
    expected_case_ids = [cast(str, case["case_id"]) for case in expected_calibration_cases]
    if actual_case_ids != expected_case_ids or len(actual_case_ids) != len(set(actual_case_ids)):
        raise E1ArtifactError("Calibration evidence is incomplete", code="EVIDENCE_INCOMPLETE")
    for case_result, manifest_case in zip(case_results, expected_calibration_cases, strict=True):
        source_hashes = cast(Mapping[str, Any], case_result["source_hashes"])
        manifest_hashes = cast(Mapping[str, Any], manifest_case["source_hashes"])
        if (
            case_result["group"] != manifest_case["group"]
            or case_result["expected_outcome"] != manifest_case["expected_outcome"]
            or any(
                source_hashes[field] != manifest_hashes[field]
                for field in (
                    "reference_sha256",
                    "inspection_sha256",
                    "authoritative_mask_sha256",
                )
            )
            or source_hashes["generator_configuration_sha256"]
            != cast(Mapping[str, Any], manifest_case["generator"])["generator_configuration_sha256"]
        ):
            raise E1ArtifactError(
                "Calibration case binding does not match the manifest",
                code="HASH_MISMATCH",
                details={"case_id": case_result["case_id"]},
            )
    if (
        calibration["schema_version"] != "1.0.0"
        or calibration["calibration_id"] != f"e1-{profile}-calibration-v1"
        or calibration["profile"] != profile
        or calibration["protocol"] != protocol
        or calibration["dataset_manifest_sha256"] != manifest["manifest_sha256"]
        or calibration["evaluation_split"] != "calibration"
    ):
        raise E1ArtifactError("Calibration bindings do not match", code="HASH_MISMATCH")
    calibration_metrics = calibration["metrics"]
    if (
        not isinstance(calibration_metrics, dict)
        or calibration_metrics.get("evaluation_split") != "calibration"
        or not isinstance(calibration_metrics.get("gate_summary"), dict)
        or calibration_metrics["gate_summary"].get("total") != 4
    ):
        raise E1ArtifactError("Calibration metrics are malformed", code="SCHEMA_INVALID")
    if _calibration_gate_records(calibration_metrics) != threshold_lock["calibration_gate_results"]:
        raise E1ArtifactError(
            "Threshold gates do not match calibration metrics", code="HASH_MISMATCH"
        )
    if (
        threshold_lock["calibration_manifest_sha256"] != manifest["manifest_sha256"]
        or threshold_lock["calibration_result_sha256"] != calibration_result_sha256
        or calibration["threshold_candidate"] != threshold_lock["locked_image_threshold"]
    ):
        raise E1ArtifactError(
            "Threshold-lock evidence binding does not match", code="HASH_MISMATCH"
        )
    dataset = cast(Mapping[str, Any], result["dataset"])
    counts = cast(Mapping[str, Any], manifest["counts"])
    if dataset["dataset_manifest_sha256"] != manifest["manifest_sha256"] or any(
        dataset[field] != counts[field]
        for field in ("case_count", "inference_case_count", "trust_case_count")
    ):
        raise E1ArtifactError("Result dataset binding does not match", code="HASH_MISMATCH")
    result_threshold = cast(Mapping[str, Any], result["threshold"])
    result_code = cast(Mapping[str, Any], result["code"])
    if (
        result_threshold["lock_id"] != threshold_lock["lock_id"]
        or result_threshold["threshold_lock_sha256"] != threshold_lock["threshold_lock_sha256"]
        or result_threshold["lock_status"] != threshold_lock["lock_status"]
        or result_threshold["locked_image_threshold"] != threshold_lock["locked_image_threshold"]
        or result_threshold["threshold_source_split"] != threshold_lock["threshold_source_split"]
        or result_code["code_commit_sha"] != threshold_lock["code_commit_sha"]
        or result_code["dirty_worktree"] != threshold_lock["dirty_worktree"]
    ):
        raise E1ArtifactError("Result threshold binding does not match", code="HASH_MISMATCH")
    _verify_result_scope(result, manifest)
    _verify_gallery_bindings(
        result,
        profile=cast(str, profile),
        inventory=inventory,
        store=store,
    )


def _verify_gallery_bindings(
    result: Mapping[str, Any],
    *,
    profile: str,
    inventory: Mapping[str, ArtifactRecord],
    store: E1ArtifactStore,
) -> None:
    gallery = cast(Sequence[Mapping[str, Any]], result["error_gallery"])
    if len(gallery) > ERROR_GALLERY_MAX_CASES:
        raise E1ArtifactError("Error gallery exceeds its bound", code="INPUT_TOO_LARGE")
    case_ids = [cast(str, item["case_id"]) for item in gallery]
    if len(case_ids) != len(set(case_ids)):
        raise E1ArtifactError("Error gallery case IDs are duplicated", code="SCHEMA_INVALID")
    prefix = f"/api/v1/e1/evaluation/assets/{profile}/"
    for item in gallery:
        assets = cast(Mapping[str, Any], item["assets"])
        hashes = cast(Mapping[str, Any], item["source_hashes"])
        filename_hashes = {
            "reference.png": hashes["reference_sha256"],
            "inspection.png": hashes["inspection_sha256"],
            "authoritative-mask.png": hashes["authoritative_mask_sha256"],
            "predicted-mask.png": hashes["predicted_mask_sha256"],
        }
        urls = {
            "reference.png": assets["reference_image_url"],
            "inspection.png": assets["inspection_image_url"],
            "authoritative-mask.png": assets["authoritative_mask_url"],
            "predicted-mask.png": assets["predicted_mask_url"],
            "overlay.png": assets["overlay_url"],
        }
        case_id = item["case_id"]
        payloads: dict[str, bytes] = {}
        for filename, url in urls.items():
            expected_hash = filename_hashes.get(filename)
            if url is None:
                if expected_hash is not None:
                    raise E1ArtifactError("Gallery URL/hash presence differs", code="HASH_MISMATCH")
                continue
            expected_url = f"{prefix}{case_id}/{filename}"
            if url != expected_url:
                raise E1ArtifactError("Gallery asset URL is invalid", code="SCHEMA_INVALID")
            relative = f"assets/{case_id}/{filename}"
            member = inventory.get(relative)
            if member is None:
                raise E1ArtifactError(
                    "Gallery asset is not inventoried", code="EVIDENCE_INCOMPLETE"
                )
            if member.media_type != "image/png" or not member.path.endswith(".png"):
                raise E1ArtifactError("Gallery asset media type is invalid", code="SCHEMA_INVALID")
            if expected_hash is not None and member.sha256 != expected_hash:
                raise E1ArtifactError(
                    "Gallery asset hash binding does not match", code="HASH_MISMATCH"
                )
            payloads[filename] = store.read_bytes(
                relative,
                expected_sha256=member.sha256,
            )
        predicted_present = urls["predicted-mask.png"] is not None
        if (urls["overlay.png"] is not None) != predicted_present:
            raise E1ArtifactError(
                "Gallery overlay/predicted-mask presence differs",
                code="HASH_MISMATCH",
            )
        if predicted_present:
            validator = ImageIngestor()
            for filename in (
                "inspection.png",
                "authoritative-mask.png",
                "predicted-mask.png",
            ):
                try:
                    validator.ingest_bytes(
                        payloads[filename],
                        filename=filename,
                        declared_media_type="image/png",
                    )
                except UnsafeInputError as exc:
                    raise E1ArtifactError(
                        "Gallery asset PNG could not be verified",
                        code=exc.code,
                        details={"filename": filename},
                    ) from exc
            expected_overlay = _render_overlay(
                payloads["inspection.png"],
                payloads["authoritative-mask.png"],
                payloads["predicted-mask.png"],
            )
            overlay_record = inventory[f"assets/{case_id}/overlay.png"]
            if overlay_record.sha256 != sha256_bytes(expected_overlay):
                raise E1ArtifactError(
                    "Gallery overlay does not match its source assets",
                    code="HASH_MISMATCH",
                )


def _verify_repeatability_bindings(
    result: Mapping[str, Any],
    published_manifest: Mapping[str, Any],
    manifests: Sequence[Mapping[str, Any]],
) -> None:
    if len(manifests) != 2 or any(manifest["profile"] != "full" for manifest in manifests):
        raise E1ArtifactError(
            "FULL repeatability manifests are incomplete", code="EVIDENCE_INCOMPLETE"
        )
    if (
        manifests[0]["protocol"] != result["protocol"]
        or manifests[1]["protocol"] != result["protocol"]
    ):
        raise E1ArtifactError("Repeatability protocol bindings do not match", code="HASH_MISMATCH")
    _verify_profile_manifest_binding(published_manifest, manifests[0])
    reproducibility = cast(Mapping[str, Any], result["reproducibility"])
    declared = reproducibility["deterministic_projection_sha256s"]
    observed = [manifest["manifest_sha256"] for manifest in manifests]
    equivalent = canonical_json_bytes(manifests[0]) == canonical_json_bytes(manifests[1])
    if (
        declared != observed
        or reproducibility["equivalent"] != equivalent
        or equivalent != (observed[0] == observed[1])
    ):
        raise E1ArtifactError(
            "FULL manifest repeatability binding does not match", code="HASH_MISMATCH"
        )


def _verify_profile_manifest_binding(
    published_manifest: Mapping[str, Any], full_manifest: Mapping[str, Any]
) -> None:
    if published_manifest["profile"] == "full":
        equivalent = canonical_json_bytes(published_manifest) == canonical_json_bytes(full_manifest)
    else:
        full_cases = {
            cast(str, case["case_id"]): case
            for case in cast(Sequence[Mapping[str, Any]], full_manifest["cases"])
        }
        published_cases = cast(Sequence[Mapping[str, Any]], published_manifest["cases"])
        equivalent = all(
            full_cases.get(cast(str, case["case_id"])) == case for case in published_cases
        )
    if not equivalent:
        raise E1ArtifactError(
            "Published profile manifest does not match the FULL corpus",
            code="HASH_MISMATCH",
        )


def _verify_result_scope(result: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    status = result["evaluation_status"]
    gallery = cast(Sequence[Mapping[str, Any]], result["error_gallery"])
    if status == "CALIBRATION_HOLD":
        if gallery:
            raise E1ArtifactError(
                "Calibration HOLD cannot contain test gallery evidence", code="SCHEMA_INVALID"
            )
        return
    metrics = result["metrics"]
    if not isinstance(metrics, dict):
        raise E1ArtifactError("Completed result metrics are missing", code="EVIDENCE_INCOMPLETE")
    cases = cast(Sequence[Mapping[str, Any]], manifest["cases"])
    expected_test_inference = sum(
        case["split"] == "test" and case["group"] != "trust_boundary" for case in cases
    )
    confusion = cast(Mapping[str, Any], metrics["image_level"])["confusion"]
    if not isinstance(confusion, dict) or confusion.get("sample_count") != expected_test_inference:
        raise E1ArtifactError("Test inference evidence is incomplete", code="EVIDENCE_INCOMPLETE")
    expected_trust = {
        cast(str, cast(Mapping[str, Any], case["trust_boundary"])["scenario_id"]): cast(
            str, case["case_id"]
        )
        for case in cases
        if case["group"] == "trust_boundary"
    }
    slices = cast(Mapping[str, Any], metrics["slices"])
    trust_slices = slices["trust_boundary_scenario"]
    if (
        not isinstance(trust_slices, dict)
        or {
            scenario: item.get("case_id")
            for scenario, item in trust_slices.items()
            if isinstance(item, dict)
        }
        != expected_trust
    ):
        raise E1ArtifactError(
            "Profile trust-boundary evidence is incomplete", code="EVIDENCE_INCOMPLETE"
        )


def _protocol_binding(protocol: E1Protocol) -> dict[str, str]:
    return {
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.protocol_version,
        "protocol_sha256": protocol.configuration_sha256,
    }


def _generator_binding(protocol: E1Protocol) -> dict[str, str]:
    return {
        "generator_id": protocol.generator_id,
        "generator_version": protocol.generator_version,
        "generator_configuration_sha256": protocol.generator_configuration_sha256,
    }


def _code_binding() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise E1ArtifactError(
            "E1 code identity could not be resolved",
            code="EVIDENCE_INCOMPLETE",
        ) from exc
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise E1ArtifactError("E1 code commit is malformed", code="EVIDENCE_INCOMPLETE")
    return {"code_commit_sha": commit, "dirty_worktree": dirty}


def _execution_environment() -> dict[str, str]:
    return {
        "runtime_id": "python-numpy",
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pillow_version": PIL.__version__,
        "platform": platform.platform(),
    }


def _validate_bootstrap_arguments(replicates: int, seed: int) -> None:
    if (
        isinstance(replicates, bool)
        or not isinstance(replicates, int)
        or not 1 <= replicates <= 100_000
    ):
        raise ValueError("bootstrap_replicates must be an integer within [1, 100000]")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFF:
        raise ValueError("bootstrap_seed must be a uint32 integer")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _duration_ms(started: float) -> int:
    return min(round((time.monotonic() - started) * 1000), 604_800_000)


__all__ = [
    "CALIBRATION_RESULT_PATH",
    "INVENTORY_PATH",
    "MANIFEST_PATH",
    "REPEATABILITY_MANIFEST_PATHS",
    "RESULT_PATH",
    "THRESHOLD_LOCK_PATH",
    "run_e1_evaluation",
    "verify_e1_results",
]
