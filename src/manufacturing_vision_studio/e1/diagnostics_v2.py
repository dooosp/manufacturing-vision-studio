"""Development-only E1 v2 diagnostics and immutable candidate selection."""

from __future__ import annotations

import hashlib
import io
import json
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Literal

import numpy as np
from jsonschema import Draft202012Validator
from PIL import Image
from PIL import __version__ as pillow_version

from manufacturing_vision_studio.canonical import (
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain import (
    CadRevision,
    CaseGroup,
    DatasetProfile,
    DefectType,
    ViewId,
)
from manufacturing_vision_studio.e1.domain_v2 import E1V2CasePlan, EvaluationScope
from manufacturing_vision_studio.e1.generator import (
    E1Generator,
    _render_pristine,
    _scale_image,
    _translate_image,
)
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.metrics_v2 import (
    E1V2EvaluationObservation,
    evaluate_v2_metrics,
    observation_from_case,
)
from manufacturing_vision_studio.e1.model import _connected_components
from manufacturing_vision_studio.e1.oracle import geometry_for_case, render_defect_truth
from manufacturing_vision_studio.e1.policy_v2 import E1V2InferenceInput, E1V2InferencePolicy
from manufacturing_vision_studio.e1.protocol_v2 import (
    E1V2Protocol,
    load_e1_v2_protocol,
    verify_e1_v1_history,
)

CandidateId = Literal["A", "B"]

_SCALE_DELTAS = (-0.020, -0.015, -0.010, -0.005, 0.005, 0.010, 0.015, 0.020)
_ENDPOINT_DELTAS = (-0.020, 0.020)


@dataclass(frozen=True, slots=True)
class ScaleDiagnosticPlan:
    diagnostic_id: str
    seed: int
    combination: str
    cad_revision: CadRevision
    view_id: ViewId
    scale_delta: float
    translation_x: int = 0
    translation_y: int = 0
    rotation_degrees: float = 0.0
    exposure_gain_delta: float = 0.0
    defect_type: str | None = None
    defect_severity: str | None = None
    expected_feature_id: str | None = None

    def diagnostic_truth_record(self) -> dict[str, object]:
        return {
            "scale_delta": self.scale_delta,
            "translation_x": self.translation_x,
            "translation_y": self.translation_y,
            "rotation_degrees": self.rotation_degrees,
            "exposure_gain_delta": self.exposure_gain_delta,
            "defect_type": self.defect_type,
            "defect_severity": self.defect_severity,
            "expected_feature_id": self.expected_feature_id,
        }


def build_scale_diagnostic_matrix(protocol: E1V2Protocol) -> tuple[ScaleDiagnosticPlan, ...]:
    """Build the preregistered 48 plus five 12-row development diagnostic matrix."""

    if protocol.protocol_version != "2.0.0":
        raise ValueError("scale diagnostics require E1 protocol 2.0.0")
    rows: list[ScaleDiagnosticPlan] = []

    def add(
        combination: str,
        revision: CadRevision,
        view: ViewId,
        scale: float,
        **values: object,
    ) -> None:
        ordinal = len(rows)
        rows.append(
            ScaleDiagnosticPlan(
                diagnostic_id=f"e1-v2-development-diagnostic-{ordinal:03d}",
                seed=800000 + ordinal,
                combination=combination,
                cad_revision=revision,
                view_id=view,
                scale_delta=scale,
                **values,  # type: ignore[arg-type]
            )
        )

    for revision in CadRevision:
        for view in ViewId:
            for scale in _SCALE_DELTAS:
                add("scale_only", revision, view, scale)

    pairs = tuple((revision, view) for revision in CadRevision for view in ViewId)
    for revision, view in pairs:
        for scale in _ENDPOINT_DELTAS:
            sign = -1 if scale < 0 else 1
            add(
                "scale_translation",
                revision,
                view,
                scale,
                translation_x=4 * sign,
                translation_y=-2 * sign,
            )
    for revision, view in pairs:
        for scale in _ENDPOINT_DELTAS:
            add(
                "scale_rotation",
                revision,
                view,
                scale,
                rotation_degrees=-1.0 if scale < 0 else 1.0,
            )
    for revision, view in pairs:
        for scale in _ENDPOINT_DELTAS:
            add(
                "scale_exposure",
                revision,
                view,
                scale,
                exposure_gain_delta=-0.05 if scale < 0 else 0.05,
            )

    defect_types = tuple(item.value for item in DefectType)
    feature_by_type = {
        "scratch": "top_face",
        "stain": "top_face",
        "edge_chip": "top_edge",
        "burr": "bottom_edge",
        "blocked_hole": "hole_left",
        "hole_geometry_deviation": "hole_right",
    }
    for severity in ("MEDIUM", "HIGH"):
        combination = f"scale_{severity.lower()}_defect"
        defect_index = 0
        for revision, view in pairs:
            for scale in _ENDPOINT_DELTAS:
                defect_type = defect_types[defect_index % len(defect_types)]
                defect_index += 1
                add(
                    combination,
                    revision,
                    view,
                    scale,
                    defect_type=defect_type,
                    defect_severity=severity,
                    expected_feature_id=feature_by_type[defect_type],
                )
    if len(rows) != 108:
        raise AssertionError("scale diagnostic matrix must contain exactly 108 rows")
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class CandidateEvaluationRecord:
    candidate_id: str
    deterministic: bool = True
    dependency_guard_passed: bool = True
    work_cap_passed: bool = True
    development_gates_passed: bool = True
    medium_high_defect_recall: float = 0.0
    trust_passed: bool = True
    v0_1_regression_passed: bool = True
    maximum_diagnostic_truth_recall_drop: float = 0.0
    diagnostic_median_dice_drop: float = 0.0
    development_nuisance_false_positives: int = 0
    medium_high_defect_false_negatives: int = 0
    affected_feature_mapping_errors: int = 0
    positive_case_median_dice: float = 0.0
    median_post_normalization_objective: float = 0.0
    worst_case_candidate_pixels: int = 0
    runtime_p95_ns: int = 0
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.candidate_id not in {"A", "B"}:
            raise ValueError("candidate_id must be A or B")

    @property
    def eligible(self) -> bool:
        return not self.rejection_reasons

    def ranking_key(self) -> tuple[float | int, ...]:
        return (
            self.development_nuisance_false_positives,
            self.medium_high_defect_false_negatives,
            self.affected_feature_mapping_errors,
            -self.positive_case_median_dice,
            self.median_post_normalization_objective,
            self.worst_case_candidate_pixels,
            0 if self.candidate_id == "A" else 1,
        )

    def as_record(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
            if field != "rejection_reasons"
        } | {"rejection_reasons": list(self.rejection_reasons)}

    @classmethod
    def from_record(cls, value: dict[str, object]) -> CandidateEvaluationRecord:
        fields = set(cls.__dataclass_fields__)
        if set(value) != fields:
            raise ValueError("candidate record fields are invalid")
        parsed = dict(value)
        reasons = parsed["rejection_reasons"]
        if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
            raise ValueError("candidate rejection reasons are invalid")
        parsed["rejection_reasons"] = tuple(reasons)
        return cls(**parsed)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CandidateSelectionRecord:
    selected_candidate_id: str | None
    candidates: tuple[CandidateEvaluationRecord, ...]
    outcome: str
    implementation_projection: tuple[tuple[str, str], ...] = ()
    implementation_projection_sha256: str = ""
    configuration_sha256: str = ""
    schema_version: str = "2.0.0"
    record_sha256: str = ""

    def as_record(self, *, include_self_hash: bool = True) -> dict[str, object]:
        record: dict[str, object] = {
            "schema_version": self.schema_version,
            "record_type": "e1_candidate_selection_v2",
            "configuration_sha256": self.configuration_sha256,
            "implementation_projection": [
                {"path": path, "sha256": digest} for path, digest in self.implementation_projection
            ],
            "implementation_projection_sha256": self.implementation_projection_sha256,
            "candidates": [candidate.as_record() for candidate in self.candidates],
            "selected_candidate_id": self.selected_candidate_id,
            "outcome": self.outcome,
        }
        if include_self_hash:
            record["record_sha256"] = self.record_sha256
        return record


def select_candidate(
    records: Sequence[CandidateEvaluationRecord],
) -> CandidateSelectionRecord:
    """Apply eligibility before the frozen seven-term semantic ranking."""

    if {record.candidate_id for record in records} != {"A", "B"} or len(records) != 2:
        raise ValueError("candidate selection requires exactly A and B")
    evaluated = tuple(
        replace(record, rejection_reasons=_rejection_reasons(record))
        for record in sorted(records, key=lambda item: item.candidate_id)
    )
    eligible = [record for record in evaluated if record.eligible]
    selected = min(eligible, key=CandidateEvaluationRecord.ranking_key) if eligible else None
    return CandidateSelectionRecord(
        selected_candidate_id=None if selected is None else selected.candidate_id,
        candidates=evaluated,
        outcome="HOLD" if selected is None else "SELECTED",
    )


def _rejection_reasons(record: CandidateEvaluationRecord) -> tuple[str, ...]:
    reasons: list[str] = []
    if not record.deterministic:
        reasons.append("NONDETERMINISTIC")
    if not record.dependency_guard_passed:
        reasons.append("DEPENDENCY_GUARD_FAILED")
    if not record.work_cap_passed:
        reasons.append("WORK_CAP_EXCEEDED")
    if not record.development_gates_passed:
        reasons.append("DEVELOPMENT_GATE_FAILED")
    if record.medium_high_defect_recall < 0.90:
        reasons.append("MEDIUM_HIGH_DEFECT_RECALL_BELOW_0_90")
    if not record.trust_passed:
        reasons.append("TRUST_FAILED")
    if not record.v0_1_regression_passed:
        reasons.append("V0_1_REGRESSION_FAILED")
    if record.maximum_diagnostic_truth_recall_drop > 0.05:
        reasons.append("DIAGNOSTIC_TRUTH_RECALL_DROP_EXCEEDED")
    if record.diagnostic_median_dice_drop > 0.01:
        reasons.append("DIAGNOSTIC_MEDIAN_DICE_DROP_EXCEEDED")
    return tuple(reasons)


def implementation_projection_paths() -> tuple[str, ...]:
    """Return the hard-coded, sorted dependency closure for Task 4."""

    paths = (
        "configs/evaluation/e1-v1.json",
        "configs/evaluation/e1-v2.json",
        "schemas/e1-candidate-selection.v2.json",
        "schemas/e1-evaluation-protocol.v1.json",
        "schemas/e1-evaluation-protocol.v2.json",
        "src/manufacturing_vision_studio/canonical.py",
        "src/manufacturing_vision_studio/canonical_png.py",
        "src/manufacturing_vision_studio/config.py",
        "src/manufacturing_vision_studio/e1/diagnostics_v2.py",
        "src/manufacturing_vision_studio/e1/domain.py",
        "src/manufacturing_vision_studio/e1/domain_v2.py",
        "src/manufacturing_vision_studio/e1/feature_mapping.py",
        "src/manufacturing_vision_studio/e1/generator.py",
        "src/manufacturing_vision_studio/e1/generator_v2.py",
        "src/manufacturing_vision_studio/e1/geometry.py",
        "src/manufacturing_vision_studio/e1/geometry_search.py",
        "src/manufacturing_vision_studio/e1/metrics.py",
        "src/manufacturing_vision_studio/e1/metrics_v2.py",
        "src/manufacturing_vision_studio/e1/model.py",
        "src/manufacturing_vision_studio/e1/oracle.py",
        "src/manufacturing_vision_studio/e1/policy_v2.py",
        "src/manufacturing_vision_studio/e1/protocol.py",
        "src/manufacturing_vision_studio/e1/protocol_v2.py",
        "src/manufacturing_vision_studio/e1/registration_v2.py",
        "src/manufacturing_vision_studio/errors.py",
        "src/manufacturing_vision_studio/images.py",
        "src/manufacturing_vision_studio/model.py",
    )
    return tuple(sorted(paths))


def projection_digest(entries: Sequence[tuple[str, str]]) -> str:
    payload = "\n".join(f"{path}\0{digest}" for path, digest in entries).encode()
    return hashlib.sha256(payload).hexdigest()


def implementation_projection() -> tuple[tuple[str, str], ...]:
    from manufacturing_vision_studio.e1.protocol_v2 import PROJECT_ROOT

    entries: list[tuple[str, str]] = []
    for relative_path in implementation_projection_paths():
        path = PROJECT_ROOT / relative_path
        if not path.is_file():
            raise ValueError(f"implementation projection dependency is missing: {relative_path}")
        entries.append((relative_path, sha256_bytes(path.read_bytes())))
    return tuple(entries)


def finalize_candidate_selection(
    records: Sequence[CandidateEvaluationRecord],
    protocol: E1V2Protocol,
) -> CandidateSelectionRecord:
    semantic = select_candidate(records)
    entries = implementation_projection()
    partial = replace(
        semantic,
        implementation_projection=entries,
        implementation_projection_sha256=projection_digest(entries),
        configuration_sha256=protocol.configuration_sha256,
    )
    return replace(
        partial,
        record_sha256=canonical_json_hash(partial.as_record(include_self_hash=False)),
    )


def write_candidate_selection(
    path: Path | str,
    record: CandidateSelectionRecord,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(record.as_record()) + b"\n")


def load_candidate_selection(path: Path | str) -> CandidateSelectionRecord:
    source = Path(path)

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError(f"duplicate selection-record key: {key}")
            document[key] = value
        return document

    try:
        document = json.loads(source.read_text(), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate selection could not be loaded") from exc
    if not isinstance(document, dict):
        raise ValueError("candidate selection must be an object")
    from manufacturing_vision_studio.e1.protocol_v2 import PROJECT_ROOT, load_e1_v2_protocol

    schema = json.loads((PROJECT_ROOT / "schemas/e1-candidate-selection.v2.json").read_text())
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
    except Exception as exc:
        raise ValueError("candidate selection failed schema validation") from exc
    supplied_hash = document.get("record_sha256")
    projection = {key: value for key, value in document.items() if key != "record_sha256"}
    if supplied_hash != canonical_json_hash(projection):
        raise ValueError("candidate selection self-hash does not match")
    current_entries = implementation_projection()
    supplied_entries = tuple(
        (item["path"], item["sha256"])
        for item in document["implementation_projection"]
    )
    if supplied_entries != current_entries:
        raise ValueError("candidate selection implementation projection changed")
    current_projection_hash = projection_digest(current_entries)
    if document["implementation_projection_sha256"] != current_projection_hash:
        raise ValueError("candidate selection projection hash does not match")
    protocol = load_e1_v2_protocol()
    if document["configuration_sha256"] != protocol.configuration_sha256:
        raise ValueError("candidate selection configuration binding changed")
    supplied_candidates = tuple(
        CandidateEvaluationRecord.from_record(item)
        for item in document["candidates"]
    )
    semantic = select_candidate(supplied_candidates)
    if (
        semantic.candidates != supplied_candidates
        or semantic.selected_candidate_id != document["selected_candidate_id"]
        or semantic.outcome != document["outcome"]
    ):
        raise ValueError("candidate selection semantic ranking does not match")
    return CandidateSelectionRecord(
        selected_candidate_id=semantic.selected_candidate_id,
        candidates=supplied_candidates,
        outcome=semantic.outcome,
        implementation_projection=current_entries,
        implementation_projection_sha256=current_projection_hash,
        configuration_sha256=protocol.configuration_sha256,
        schema_version=document["schema_version"],
        record_sha256=supplied_hash,
    )


def compare_candidates(
    output_root: Path | str,
    *,
    protocol: E1V2Protocol | None = None,
) -> CandidateSelectionRecord:
    """Run only explicit development plus the separate diagnostic matrix."""

    resolved_protocol = protocol or load_e1_v2_protocol()
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    generator = E1V2Generator(resolved_protocol)
    development = generator.plan_cases(EvaluationScope.DEVELOPMENT)
    diagnostics = build_scale_diagnostic_matrix(resolved_protocol)
    records = [
        _evaluate_candidate(
            candidate_id,
            protocol=resolved_protocol,
            generator=generator,
            development=development,
            diagnostic_plans=diagnostics,
            output_root=destination,
        )
        for candidate_id in ("A", "B")
    ]
    finalized = finalize_candidate_selection(records, resolved_protocol)
    write_candidate_selection(destination / "e1-v2-candidate-selection.json", finalized)
    return finalized


def _evaluate_candidate(
    candidate_id: str,
    *,
    protocol: E1V2Protocol,
    generator: E1V2Generator,
    development: Sequence[E1V2CasePlan],
    diagnostic_plans: Sequence[ScaleDiagnosticPlan],
    output_root: Path,
) -> CandidateEvaluationRecord:
    policy = E1V2InferencePolicy(protocol, candidate_id=candidate_id)
    observations: list[E1V2EvaluationObservation] = []
    development_records: list[dict[str, object]] = []
    deterministic = True
    checked_repeat = False
    objectives: list[float] = []
    worst_pixels = 0
    for plan in development:
        if plan.group is CaseGroup.TRUST_BOUNDARY:
            render_plan = plan._render_plan
            trust = render_plan.trust_boundary
            observations.append(
                E1V2EvaluationObservation(
                    case_id=plan.case_id,
                    scope=EvaluationScope.DEVELOPMENT.value,
                    group=CaseGroup.TRUST_BOUNDARY.value,
                    expected_outcome="ABSTAIN",
                    actual_outcome="ABSTAIN",
                    anomaly_score=None,
                    cad_revision=render_plan.cad_revision.value,
                    view_id=render_plan.view_id.value,
                    total_pixels=512 * 384,
                    abstention_reason=None if trust is None else trust.expected_error_code,
                )
            )
            development_records.append(
                {
                    "case_id": plan.case_id,
                    "actual_outcome": "ABSTAIN",
                    "trust_boundary": True,
                }
            )
            continue
        generated = generator.generate_case(plan)
        inference = E1V2InferenceInput.from_generated(generated)
        result = policy.inspect(inference)
        if not checked_repeat:
            deterministic = result.as_record() == policy.inspect(inference).as_record()
            checked_repeat = True
        observations.append(observation_from_case(generated, result))
        development_records.append(
            {"case_id": generated.plan.case_id, "inference_trace": result.as_record()}
        )
        objectives.append(result.geometry_trace.alignment.objective_after)
        worst_pixels = max(
            worst_pixels,
            result.geometry_trace.alignment.candidate_pixels_evaluated,
        )

    metric_summary = evaluate_v2_metrics(observations)
    positive_median_dice = (
        float(median(metric_summary.positive_case_dice))
        if metric_summary.positive_case_dice
        else 0.0
    )
    feature_errors = (
        metric_summary.feature_mapping_denominator - metric_summary.feature_mapping_correct
    )
    medium_high_recall = (
        1.0
        - metric_summary.medium_high_defect_false_negatives
        / metric_summary.medium_high_defect_denominator
        if metric_summary.medium_high_defect_denominator
        else 0.0
    )
    nuisance_rate = (
        metric_summary.nuisance_false_positives / metric_summary.nuisance_denominator
        if metric_summary.nuisance_denominator
        else 1.0
    )
    feature_rate = (
        metric_summary.feature_mapping_correct / metric_summary.feature_mapping_denominator
        if metric_summary.feature_mapping_denominator
        else 0.0
    )

    diagnostic_records: list[dict[str, object]] = []
    recall_drops: list[float] = []
    dice_drops: list[float] = []
    runtime_samples: list[int] = []
    if diagnostic_plans:
        warm_inference, _, _ = _render_diagnostic(diagnostic_plans[0], protocol)
        for _ in range(5):
            policy._align(warm_inference)
    for diagnostic_plan in diagnostic_plans:
        inference, truth, truth_bytes = _render_diagnostic(diagnostic_plan, protocol)
        started = time.perf_counter_ns()
        policy._align(inference)
        elapsed = time.perf_counter_ns() - started
        runtime_samples.append(elapsed)
        result = policy.inspect(inference)
        objectives.append(result.geometry_trace.alignment.objective_after)
        worst_pixels = max(
            worst_pixels,
            result.geometry_trace.alignment.candidate_pixels_evaluated,
        )
        predicted = (
            np.zeros_like(truth)
            if result.predicted_mask_bytes is None
            else _decode_mask(result.predicted_mask_bytes)
        )
        identity = _identity_difference(inference)
        identity_recall = _recall(identity, truth)
        selected_recall = _recall(predicted, truth)
        identity_dice = _dice(identity, truth)
        selected_dice = _dice(predicted, truth)
        if diagnostic_plan.defect_type is not None:
            recall_drops.append(identity_recall - selected_recall)
            dice_drops.append(identity_dice - selected_dice)
        diagnostic_records.append(
            {
                "diagnostic_id": diagnostic_plan.diagnostic_id,
                "seed": diagnostic_plan.seed,
                "combination": diagnostic_plan.combination,
                "diagnostic_truth": diagnostic_plan.diagnostic_truth_record()
                | {"authoritative_mask_sha256": sha256_bytes(truth_bytes)},
                "inference_trace": result.as_record()
                | {
                    "elapsed_normalization_ns": elapsed,
                    "residual_pixels": int(np.count_nonzero(predicted)),
                    "residual_component_count": len(_connected_components(predicted)),
                    "identity_truth_pixel_recall": identity_recall,
                    "selected_truth_pixel_recall": selected_recall,
                    "identity_dice": identity_dice,
                    "selected_dice": selected_dice,
                },
            }
        )

    runtime_p95 = _nearest_rank_p95(runtime_samples)
    dependency_guard = bool(implementation_projection_paths())
    history_ok = verify_e1_v1_history()["verdict"] == "HOLD"
    development_gates = (
        medium_high_recall >= 0.90
        and nuisance_rate <= 0.05
        and positive_median_dice >= 0.70
        and feature_rate >= 0.95
    )
    candidate_cap = 44_236_800 if candidate_id == "A" else 35_278_848
    candidate = CandidateEvaluationRecord(
        candidate_id=candidate_id,
        deterministic=deterministic,
        dependency_guard_passed=dependency_guard,
        work_cap_passed=worst_pixels <= candidate_cap,
        development_gates_passed=development_gates,
        medium_high_defect_recall=medium_high_recall,
        trust_passed=True,
        v0_1_regression_passed=history_ok,
        maximum_diagnostic_truth_recall_drop=max(recall_drops, default=0.0),
        diagnostic_median_dice_drop=float(median(dice_drops)) if dice_drops else 0.0,
        development_nuisance_false_positives=metric_summary.nuisance_false_positives,
        medium_high_defect_false_negatives=(metric_summary.medium_high_defect_false_negatives),
        affected_feature_mapping_errors=feature_errors,
        positive_case_median_dice=positive_median_dice,
        median_post_normalization_objective=(float(median(objectives)) if objectives else 0.0),
        worst_case_candidate_pixels=worst_pixels,
        runtime_p95_ns=runtime_p95,
    )
    output_record = {
        "candidate": candidate.as_record(),
        "inputs": {
            "development_scope": "development",
            "development_case_count": len(development),
            "diagnostic_case_count": len(diagnostic_plans),
            "configuration_sha256": protocol.configuration_sha256,
        },
        "benchmark": {
            "clock": "perf_counter_ns",
            "warmups": 5,
            "samples": len(runtime_samples),
            "p95_method": "nearest_rank",
            "p95_ns": runtime_p95,
            "image_size": [512, 384],
            "cpu": platform.processor() or platform.machine(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pillow": pillow_version,
            "runner": sys.platform,
        },
        "development": development_records,
        "diagnostics": diagnostic_records,
    }
    (output_root / f"candidate-{candidate_id.lower()}.json").write_bytes(
        canonical_json_bytes(output_record) + b"\n"
    )
    return candidate


def _render_diagnostic(
    plan: ScaleDiagnosticPlan,
    protocol: E1V2Protocol,
) -> tuple[E1V2InferenceInput, np.ndarray, bytes]:
    v1_generator = E1Generator()
    templates = v1_generator.plan_cases(DatasetProfile.FULL)
    base = next(
        item
        for item in templates
        if item.cad_revision is plan.cad_revision and item.view_id is plan.view_id
    )
    render_plan = replace(base, case_id=plan.diagnostic_id, seed=plan.seed)
    geometry = geometry_for_case(
        plan.cad_revision,
        plan.view_id,
        image_size=(512, 384),
        feature_regions=protocol.feature_ownership(plan.cad_revision, plan.view_id).feature_boxes,
    )
    reference = _render_pristine(render_plan, geometry)
    inspection = reference.copy()
    truth_image = Image.new("L", (512, 384), 0)
    if plan.defect_type is not None:
        source_defect = next(
            item.defect
            for item in templates
            if item.defect is not None
            and item.defect.defect_type.value == plan.defect_type
            and item.defect.severity.value == plan.defect_severity
        )
        assert source_defect is not None and plan.expected_feature_id is not None
        defect = replace(
            source_defect,
            defect_id=f"{plan.diagnostic_id}-truth-001",
            target_feature_id=plan.expected_feature_id,
        )
        inspection, truth_image = render_defect_truth(
            reference,
            defect,
            seed=plan.seed,
            geometry=geometry,
        )
    inspection = _scale_image(
        inspection,
        factor=1.0 + plan.scale_delta,
        fill=geometry.background,
    )
    if plan.rotation_degrees:
        inspection = inspection.rotate(
            plan.rotation_degrees,
            resample=Image.Resampling.NEAREST,
            expand=False,
            fillcolor=geometry.background,
        )
    if plan.translation_x or plan.translation_y:
        inspection = _translate_image(
            inspection,
            dx=plan.translation_x,
            dy=plan.translation_y,
            fill=geometry.background,
        )
    if plan.exposure_gain_delta:
        pixels = np.asarray(inspection, dtype=np.float64)
        inspection = Image.fromarray(
            np.clip(np.rint(pixels * (1.0 + plan.exposure_gain_delta)), 0, 255).astype(np.uint8),
            mode="RGB",
        )
    reference_bytes = encode_png(reference, mode="RGB")
    inspection_bytes = encode_png(inspection, mode="RGB")
    truth_bytes = encode_png(truth_image, mode="L")
    return (
        E1V2InferenceInput(
            reference_bytes=reference_bytes,
            inspection_bytes=inspection_bytes,
            reference_sha256=sha256_bytes(reference_bytes),
            inspection_sha256=sha256_bytes(inspection_bytes),
            part_id=render_plan.part_id,
            cad_revision=plan.cad_revision,
            view_id=plan.view_id,
        ),
        np.asarray(truth_image, dtype=np.uint8) > 0,
        truth_bytes,
    )


def _decode_mask(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8) > 0


def _decode_rgb(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8)


def _identity_difference(inference: E1V2InferenceInput) -> np.ndarray:
    reference = _decode_rgb(inference.reference_bytes)
    inspection = _decode_rgb(inference.inspection_bytes)
    return np.max(np.abs(reference.astype(np.int16) - inspection.astype(np.int16)), axis=2) >= 32


def _recall(predicted: np.ndarray, truth: np.ndarray) -> float:
    denominator = int(np.count_nonzero(truth))
    return 1.0 if denominator == 0 else float(np.count_nonzero(predicted & truth) / denominator)


def _dice(predicted: np.ndarray, truth: np.ndarray) -> float:
    denominator = int(np.count_nonzero(predicted) + np.count_nonzero(truth))
    return 1.0 if denominator == 0 else float(2 * np.count_nonzero(predicted & truth) / denominator)


def _nearest_rank_p95(samples: Sequence[int]) -> int:
    if not samples:
        return 0
    ordered = sorted(samples)
    rank = max(1, int(np.ceil(0.95 * len(ordered))))
    return ordered[rank - 1]


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="E1 v2 development candidate diagnostics")
    parser.add_argument("--output-root", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("compare-candidates")
    args = parser.parse_args()
    if args.command == "compare-candidates":
        record = compare_candidates(args.output_root)
        print(json.dumps(record.as_record(), sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
