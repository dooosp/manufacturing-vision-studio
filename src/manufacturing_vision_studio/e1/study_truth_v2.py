"""Offline truth joins, transform proofs, and fixed study reductions."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from statistics import median
from types import MappingProxyType
from typing import Literal, cast

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain import (
    CadRevision,
    CaseGroup,
    DatasetProfile,
    NuisanceType,
    ViewId,
)
from manufacturing_vision_studio.e1.domain_v2 import (
    E1V2CasePlan,
    E1V2GeneratedCase,
    EvaluationScope,
)
from manufacturing_vision_studio.e1.feature_mapping import (
    FeatureOwnershipMap,
    build_ownership_map,
    map_final_mask,
)
from manufacturing_vision_studio.e1.generator import (
    E1Generator,
    _apply_nuisance,
    _digest_bit,
    _render_pristine,
    _scale_image,
    _translate_image,
)
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.known_transform_v2 import (
    AppliedAffineTransform,
    KnownTransformResult,
    ReferenceBoundaryBand,
    ResamplingMode,
)
from manufacturing_vision_studio.e1.metrics_v2 import (
    E1V2EvaluationObservation,
    evaluate_v2_metrics,
)
from manufacturing_vision_studio.e1.oracle import (
    _decode_canonical_png,
    geometry_for_case,
    render_defect_truth,
)
from manufacturing_vision_studio.e1.protocol_v2 import (
    E1V2Protocol,
    load_e1_v2_protocol,
)
from manufacturing_vision_studio.e1.study_inference_v2 import (
    StudyInferenceInput,
    StudyInferenceResult,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    DevelopmentGates,
    DiagnosticGates,
    FrozenDiagnosticPlan,
    StudyProtocolV2,
)

_IMAGE_SIZE = (512, 384)
_IMAGE_SHAPE = (384, 512)
_IDENTITY_TRANSFORM = AppliedAffineTransform(1.0, 0.0, 0.0, 0.0)
_DEVELOPMENT_COUNTS = {
    "clean": 24,
    "nuisance": 30,
    "defect": 60,
    "trust_boundary": 6,
    "total": 120,
}


@dataclass(frozen=True, slots=True)
class StudyTruthCase:
    case_id: str
    seed: int
    group: str
    expected_outcome: str
    part_id: str
    cad_revision: str
    view_id: str
    reference_bytes: bytes
    inspection_bytes: bytes
    authoritative_mask_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    authoritative_mask_sha256: str
    applied_transform: AppliedAffineTransform
    defect_type: str | None
    defect_severity: str | None
    expected_feature_id: str | None
    nuisance_types: tuple[str, ...]
    case_binding_sha256: str | None
    trust_boundary: bool = False


@dataclass(frozen=True, slots=True)
class DiagnosticObservation:
    diagnostic_id: str
    seed: int
    mode: ResamplingMode
    defect_row: bool
    medium_high_row: bool
    actual_outcome: str
    identity_recall: float
    study_recall: float
    identity_dice: float
    study_dice: float
    study_iou: float
    total_residual: int
    boundary_residual: int
    outside_boundary_residual: int
    record: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "record", MappingProxyType(dict(self.record)))


@dataclass(frozen=True, slots=True)
class DiagnosticModeSummary:
    mode: ResamplingMode
    row_count: int
    defect_drop_denominator: int
    medium_high_classification_denominator: int
    maximum_recall_drop: float
    median_dice_drop: float
    medium_high_classification_recall: float
    eligible: bool


@dataclass(frozen=True, slots=True)
class DevelopmentCorpus:
    cases: tuple[StudyTruthCase, ...]
    counts: Mapping[str, int]
    scope_projection: tuple[str, ...]
    external_request_count: int
    internal_membership_validation_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))


@dataclass(frozen=True, slots=True)
class AppliedTransformProof:
    case_id: str
    applied_transform: AppliedAffineTransform
    replay_sha256: str
    inspection_sha256: str
    replay_matches: bool


@dataclass(frozen=True, slots=True)
class FeatureOracleResult:
    case_count: int
    correct_cases: int
    ambiguous_cases: int
    null_cases: int
    wrong_cases: int
    ownership_hashes: Mapping[str, str]
    records: tuple[Mapping[str, object], ...]
    passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ownership_hashes",
            MappingProxyType(dict(sorted(self.ownership_hashes.items()))),
        )
        object.__setattr__(
            self,
            "records",
            tuple(MappingProxyType(dict(record)) for record in self.records),
        )


@dataclass(frozen=True, slots=True)
class DevelopmentModeSummary:
    mode: ResamplingMode
    member_count: int
    inference_count: int
    trust_binding_count: int
    medium_high_recall: float
    nuisance_false_positive_rate: float
    positive_median_dice: float
    feature_mapping_accuracy: float
    passed_all_gates: bool


class DevelopmentCorpusProvider:
    """The only production adapter allowed to request E1 v2 membership."""

    def __init__(self, protocol: E1V2Protocol) -> None:
        self.protocol = protocol
        self._generator = E1V2Generator(protocol)
        self._cached: DevelopmentCorpus | None = None

    def load(self) -> DevelopmentCorpus:
        if self._cached is not None:
            return self._cached
        plans = self._generator.plan_cases(EvaluationScope.DEVELOPMENT)
        generated = tuple(self._generator.generate_case(plan) for plan in plans)
        self._cached = _validate_development_corpus(
            generated,
            protocol=self.protocol,
            external_scope_projection=(EvaluationScope.DEVELOPMENT.value,),
            external_request_count=1,
        )
        return self._cached


def render_diagnostic(
    plan: FrozenDiagnosticPlan,
    study_protocol: StudyProtocolV2,
    e1_protocol: E1V2Protocol,
) -> StudyTruthCase:
    """Render one frozen diagnostic without importing candidate-comparison code."""

    seed_start = int(study_protocol.phase_1_limits["seed_start"])
    seed_end = int(study_protocol.phase_1_limits["seed_end"])
    if not seed_start <= plan.seed <= seed_end:
        raise ValueError("diagnostic seed is outside the frozen study range")
    ordinal = plan.seed - seed_start
    if plan.diagnostic_id != f"e1-v2-development-diagnostic-{ordinal:03d}":
        raise ValueError("diagnostic ID and seed binding do not match")

    v1_generator = E1Generator()
    templates = v1_generator.plan_cases(DatasetProfile.FULL)
    try:
        base = next(
            item
            for item in templates
            if item.cad_revision is plan.cad_revision and item.view_id is plan.view_id
        )
    except StopIteration as exc:
        raise ValueError("diagnostic render template is missing") from exc
    render_plan = replace(base, case_id=plan.diagnostic_id, seed=plan.seed)
    geometry = geometry_for_case(
        plan.cad_revision,
        plan.view_id,
        image_size=_IMAGE_SIZE,
        feature_regions=e1_protocol.feature_ownership(
            plan.cad_revision, plan.view_id
        ).feature_boxes,
    )
    reference = _render_pristine(render_plan, geometry)
    inspection = reference.copy()
    truth_image = Image.new("L", _IMAGE_SIZE, 0)
    if plan.defect_type is not None:
        try:
            source_defect = next(
                item.defect
                for item in templates
                if item.defect is not None
                and item.defect.defect_type.value == plan.defect_type
                and item.defect.severity.value == plan.defect_severity
            )
        except StopIteration as exc:
            raise ValueError("diagnostic defect template is missing") from exc
        if plan.expected_feature_id is None:
            raise ValueError("diagnostic defect target is missing")
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
            np.clip(np.rint(pixels * (1.0 + plan.exposure_gain_delta)), 0, 255).astype(
                np.uint8
            ),
            mode="RGB",
        )

    reference_bytes = encode_png(reference, mode="RGB")
    inspection_bytes = encode_png(inspection, mode="RGB")
    truth_bytes = encode_png(truth_image, mode="L")
    nuisance_types = ["scale"]
    if plan.rotation_degrees:
        nuisance_types.append("rotation")
    if plan.translation_x or plan.translation_y:
        nuisance_types.append("translation")
    if plan.exposure_gain_delta:
        nuisance_types.append("exposure")
    defect_row = plan.defect_type is not None
    return StudyTruthCase(
        case_id=plan.diagnostic_id,
        seed=plan.seed,
        group="defect" if defect_row else "nuisance",
        expected_outcome="ANOMALY" if defect_row else "NORMAL",
        part_id=render_plan.part_id,
        cad_revision=plan.cad_revision.value,
        view_id=plan.view_id.value,
        reference_bytes=reference_bytes,
        inspection_bytes=inspection_bytes,
        authoritative_mask_bytes=truth_bytes,
        reference_sha256=sha256_bytes(reference_bytes),
        inspection_sha256=sha256_bytes(inspection_bytes),
        authoritative_mask_sha256=sha256_bytes(truth_bytes),
        applied_transform=AppliedAffineTransform(
            1.0 + plan.scale_delta,
            plan.rotation_degrees,
            float(plan.translation_x),
            float(plan.translation_y),
        ),
        defect_type=plan.defect_type,
        defect_severity=plan.defect_severity,
        expected_feature_id=plan.expected_feature_id,
        nuisance_types=tuple(nuisance_types),
        case_binding_sha256=None,
    )


def applied_affine_from_plan(plan: E1V2CasePlan) -> AppliedAffineTransform:
    """Recover signed geometry from stored magnitudes and the v2 render seed."""

    render_plan = plan._render_plan
    if render_plan.seed != plan.seed:
        raise ValueError("v2 plan and retained render seed do not match")
    if plan.group is not CaseGroup.NUISANCE:
        return _IDENTITY_TRANSFORM
    scale_factor = 1.0
    rotation_degrees = 0.0
    translation_x = 0.0
    translation_y = 0.0
    for nuisance in render_plan.nuisances:
        values = {item.name: float(item.value) for item in nuisance.parameters}
        if nuisance.nuisance_type is NuisanceType.SCALE:
            delta = _stored_magnitude(values, "max_abs_scale_delta")
            scale_factor = 1 + delta if _digest_bit(plan.seed, "scale-sign") else 1 - delta
        elif nuisance.nuisance_type is NuisanceType.ROTATION:
            magnitude = _stored_magnitude(values, "max_abs_rotation")
            rotation_degrees = (
                magnitude if _digest_bit(plan.seed, "rotation-sign") else -magnitude
            )
        elif nuisance.nuisance_type is NuisanceType.TRANSLATION:
            magnitude = round(_stored_magnitude(values, "max_abs_shift"))
            translation_x = float(
                magnitude if _digest_bit(plan.seed, "translation-x-sign") else -magnitude
            )
            half = max(1, magnitude // 2)
            translation_y = float(
                half if _digest_bit(plan.seed, "translation-y-sign") else -half
            )
    return AppliedAffineTransform(
        scale_factor,
        rotation_degrees,
        translation_x,
        translation_y,
    )


def prove_applied_transform(generated: E1V2GeneratedCase) -> AppliedTransformProof:
    """Replay one generated case against the frozen default generator contract."""

    protocol, v1_generator = _default_replay_dependencies()
    return _prove_applied_transform(
        generated,
        protocol=protocol,
        v1_generator=v1_generator,
    )


def validate_development_corpus(
    generated: Sequence[E1V2GeneratedCase],
    *,
    external_scope_projection: tuple[str, ...],
    external_request_count: int,
) -> DevelopmentCorpus:
    """Validate externally supplied development members against the frozen contract."""

    return _validate_development_corpus(
        generated,
        protocol=load_e1_v2_protocol(),
        external_scope_projection=external_scope_projection,
        external_request_count=external_request_count,
    )


def make_truth_free_input(
    case: StudyTruthCase,
    normalized: KnownTransformResult,
) -> StudyInferenceInput:
    """Discard every truth-bearing field before the inference boundary."""

    if case.trust_boundary or case.group == CaseGroup.TRUST_BOUNDARY.value:
        raise ValueError("trust-boundary rows are binding-only and cannot enter inference")
    return StudyInferenceInput(
        reference_bytes=case.reference_bytes,
        inspection_bytes=case.inspection_bytes,
        reference_sha256=case.reference_sha256,
        inspection_sha256=case.inspection_sha256,
        part_id=case.part_id,
        cad_revision=CadRevision(case.cad_revision),
        view_id=ViewId(case.view_id),
        normalized=normalized,
    )


def raw_identity_difference_mask(case: StudyTruthCase) -> bytes:
    """Compute the fixed unnormalized RGB comparator without model inference."""

    _require_source_hashes(case)
    reference = _decode_rgb(case.reference_bytes).astype(np.int16)
    inspection = _decode_rgb(case.inspection_bytes).astype(np.int16)
    mask = np.max(np.abs(reference - inspection), axis=2) >= 32
    return encode_png(
        Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L"),
        mode="L",
    )


def diagnostic_observation(
    case: StudyTruthCase,
    result: StudyInferenceResult,
    identity_mask_bytes: bytes,
    boundary: ReferenceBoundaryBand,
) -> DiagnosticObservation:
    """Join diagnostic truth only after a completed truth-free inference."""

    _validate_result_binding(case, result)
    truth = _decode_mask(case.authoritative_mask_bytes)
    predicted = _decode_mask(result.predicted_mask_bytes)
    identity = _decode_mask(identity_mask_bytes)
    if boundary.radius != 3:
        raise ValueError("reference boundary radius is not the frozen value")
    if sha256_bytes(boundary.band_mask_bytes) != boundary.band_mask_sha256:
        raise ValueError("reference boundary band hash does not match bytes")
    if len(boundary.band_mask_bytes) != _IMAGE_SHAPE[0] * _IMAGE_SHAPE[1]:
        raise ValueError("reference boundary band shape is invalid")
    if not set(boundary.band_mask_bytes).issubset({0, 1}):
        raise ValueError("reference boundary band is not binary")
    band = np.frombuffer(boundary.band_mask_bytes, dtype=np.bool_).reshape(_IMAGE_SHAPE)
    if int(np.count_nonzero(band)) != boundary.band_positive_pixels:
        raise ValueError("reference boundary positive-pixel count does not match bytes")

    identity_recall = _recall(identity, truth)
    study_recall = _recall(predicted, truth)
    identity_dice = _dice(identity, truth)
    study_dice = _dice(predicted, truth)
    study_iou = _iou(predicted, truth)
    total_residual = int(np.count_nonzero(predicted))
    boundary_residual = int(np.count_nonzero(predicted & band))
    outside_boundary_residual = total_residual - boundary_residual
    defect_row = case.defect_type is not None
    medium_high_row = case.defect_severity in {"MEDIUM", "HIGH"}
    record: dict[str, object] = {
        "actual_outcome": result.actual_outcome,
        "authoritative_mask_sha256": case.authoritative_mask_sha256,
        "boundary_residual": boundary_residual,
        "diagnostic_id": case.case_id,
        "identity_dice": identity_dice,
        "identity_mask_sha256": sha256_bytes(identity_mask_bytes),
        "identity_recall": identity_recall,
        "inference_trace": result.as_record(),
        "mode": result.transform_trace.resampling.value,
        "outside_boundary_residual": outside_boundary_residual,
        "seed": case.seed,
        "study_dice": study_dice,
        "study_iou": study_iou,
        "study_recall": study_recall,
        "total_residual": total_residual,
    }
    return DiagnosticObservation(
        diagnostic_id=case.case_id,
        seed=case.seed,
        mode=result.transform_trace.resampling,
        defect_row=defect_row,
        medium_high_row=medium_high_row,
        actual_outcome=result.actual_outcome,
        identity_recall=identity_recall,
        study_recall=study_recall,
        identity_dice=identity_dice,
        study_dice=study_dice,
        study_iou=study_iou,
        total_residual=total_residual,
        boundary_residual=boundary_residual,
        outside_boundary_residual=outside_boundary_residual,
        record=record,
    )


def reduce_diagnostic_mode(
    mode: ResamplingMode,
    rows: Sequence[DiagnosticObservation],
    gates: DiagnosticGates,
) -> DiagnosticModeSummary:
    """Reduce one complete 108-row mode independently of every other mode."""

    checked = tuple(rows)
    expected_ids = {
        f"e1-v2-development-diagnostic-{ordinal:03d}" for ordinal in range(108)
    }
    if len(checked) != 108 or {row.diagnostic_id for row in checked} != expected_ids:
        raise ValueError("diagnostic rows are incomplete or duplicated")
    if {row.seed for row in checked} != set(range(800000, 800108)):
        raise ValueError("diagnostic seed coverage is incomplete or duplicated")
    rows_by_id = {row.diagnostic_id: row for row in checked}
    for ordinal in range(108):
        row = rows_by_id[f"e1-v2-development-diagnostic-{ordinal:03d}"]
        expected_defect = ordinal >= 84
        if row.seed != 800000 + ordinal:
            raise ValueError("diagnostic ID and seed binding changed")
        if row.defect_row is not expected_defect or row.medium_high_row is not expected_defect:
            raise ValueError("diagnostic truth-row binding changed")
    if any(row.mode is not mode for row in checked):
        raise ValueError("diagnostic row mode does not match the reduction mode")
    for row in checked:
        values = (
            row.identity_recall,
            row.study_recall,
            row.identity_dice,
            row.study_dice,
            row.study_iou,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("diagnostic metric is outside [0, 1]")
        if (
            row.total_residual < 0
            or not 0 <= row.boundary_residual <= row.total_residual
            or row.outside_boundary_residual != row.total_residual - row.boundary_residual
        ):
            raise ValueError("diagnostic residual counts are inconsistent")
    defect = [row for row in checked if row.defect_row]
    medium_high = [row for row in checked if row.medium_high_row]
    if len(defect) != 24 or len(medium_high) != 24 or any(
        not row.defect_row for row in medium_high
    ):
        raise ValueError("diagnostic defect denominators are not exactly 24")
    recall_drops = [row.identity_recall - row.study_recall for row in defect]
    dice_drops = [row.identity_dice - row.study_dice for row in defect]
    maximum_recall_drop = max(recall_drops)
    median_dice_drop = float(median(dice_drops))
    classification_recall = sum(
        row.actual_outcome == "ANOMALY" for row in medium_high
    ) / len(medium_high)
    eligible = (
        maximum_recall_drop <= gates.max_recall_drop
        and median_dice_drop <= gates.median_dice_drop
        and classification_recall >= gates.medium_high_recall
    )
    return DiagnosticModeSummary(
        mode=mode,
        row_count=len(checked),
        defect_drop_denominator=len(defect),
        medium_high_classification_denominator=len(medium_high),
        maximum_recall_drop=maximum_recall_drop,
        median_dice_drop=median_dice_drop,
        medium_high_classification_recall=classification_recall,
        eligible=eligible,
    )


def observation_from_study(
    case: StudyTruthCase,
    result: StudyInferenceResult,
) -> E1V2EvaluationObservation:
    """Construct a metric-only truth join after study inference returns."""

    if case.trust_boundary or case.group == CaseGroup.TRUST_BOUNDARY.value:
        raise ValueError("trust-boundary rows are binding-only and have no observation")
    if case.case_binding_sha256 is None:
        raise ValueError("development observation requires a generated case binding")
    _validate_result_binding(case, result)
    truth = _decode_mask(case.authoritative_mask_bytes)
    predicted = _decode_mask(result.predicted_mask_bytes)
    truth_count = int(np.count_nonzero(truth))
    predicted_count = int(np.count_nonzero(predicted))
    intersection = int(np.count_nonzero(truth & predicted))
    return E1V2EvaluationObservation(
        case_id=case.case_id,
        scope=EvaluationScope.DEVELOPMENT.value,
        group=case.group,
        expected_outcome=cast(
            Literal["NORMAL", "ANOMALY", "ABSTAIN"], case.expected_outcome
        ),
        actual_outcome=cast(
            Literal["NORMAL", "ANOMALY", "ABSTAIN"], result.actual_outcome
        ),
        anomaly_score=result.anomaly_score,
        defect_type=case.defect_type,
        severity=case.defect_severity,
        nuisance_types=case.nuisance_types,
        cad_revision=case.cad_revision,
        view_id=case.view_id,
        truth_positive_pixels=truth_count,
        predicted_positive_pixels=predicted_count,
        intersection_pixels=intersection,
        total_pixels=truth.size,
        expected_feature_id=case.expected_feature_id,
        predicted_feature_id=result.feature_mapping.predicted_feature_id,
    )


def reduce_development_mode(
    mode: ResamplingMode,
    observations: Sequence[E1V2EvaluationObservation],
    gates: DevelopmentGates,
) -> DevelopmentModeSummary:
    """Reduce exactly 114 inference rows plus six fixed binding-only members."""

    checked = tuple(observations)
    if len(checked) != 114 or len({row.case_id for row in checked}) != 114:
        raise ValueError("development inference membership is not exactly 114 unique rows")
    if any(row.scope != EvaluationScope.DEVELOPMENT.value for row in checked):
        raise ValueError("development reduction received a non-development scope")
    if Counter(row.group for row in checked) != {
        "clean": 24,
        "nuisance": 30,
        "defect": 60,
    }:
        raise ValueError("development inference group counts are invalid")
    metrics = evaluate_v2_metrics(list(checked))
    if (
        metrics.nuisance_denominator != 30
        or metrics.medium_high_defect_denominator != 40
        or len(metrics.positive_case_dice) != 60
        or metrics.feature_mapping_denominator != 60
    ):
        raise ValueError("development metric denominator is not 30/40/60/60")
    medium_high_recall = 1.0 - (
        metrics.medium_high_defect_false_negatives
        / metrics.medium_high_defect_denominator
    )
    nuisance_rate = metrics.nuisance_false_positives / metrics.nuisance_denominator
    positive_median_dice = float(median(metrics.positive_case_dice))
    feature_accuracy = metrics.feature_mapping_correct / metrics.feature_mapping_denominator
    passed = (
        medium_high_recall >= gates.medium_high_recall
        and nuisance_rate <= gates.nuisance_fpr
        and positive_median_dice >= gates.median_dice
        and feature_accuracy >= gates.feature_accuracy
    )
    return DevelopmentModeSummary(
        mode=mode,
        member_count=120,
        inference_count=len(checked),
        trust_binding_count=6,
        medium_high_recall=medium_high_recall,
        nuisance_false_positive_rate=nuisance_rate,
        positive_median_dice=positive_median_dice,
        feature_mapping_accuracy=feature_accuracy,
        passed_all_gates=passed,
    )


def run_feature_ownership_oracle(
    corpus: DevelopmentCorpus,
    protocol: E1V2Protocol,
    study_protocol: StudyProtocolV2,
) -> FeatureOracleResult:
    """Map only the 60 development truth masks against protocol-bound ownership."""

    _validate_corpus_projection(corpus)
    ownership_by_key: dict[str, FeatureOwnershipMap] = {}
    ownership_hashes: dict[str, str] = {}
    hash_matches: dict[str, bool] = {}
    for revision in CadRevision:
        for view in ViewId:
            key = f"{revision.value}/{view.value}"
            ownership = build_ownership_map(
                protocol.feature_ownership(revision, view),
                _IMAGE_SIZE,
            )
            ownership_by_key[key] = ownership
            ownership_hashes[key] = ownership.ownership_map_sha256
            hash_matches[key] = (
                ownership.ownership_map_sha256
                == study_protocol.ownership_map_hashes.get(key)
            )
    defects = [case for case in corpus.cases if case.group == CaseGroup.DEFECT.value]
    if len(defects) != 60:
        raise ValueError("feature oracle requires exactly 60 development defect cases")

    records: list[Mapping[str, object]] = []
    correct_cases = 0
    ambiguous_cases = 0
    null_cases = 0
    wrong_cases = 0
    for case in defects:
        if case.expected_feature_id is None:
            raise ValueError("feature oracle defect is missing its target feature")
        if sha256_bytes(case.authoritative_mask_bytes) != case.authoritative_mask_sha256:
            raise ValueError("feature oracle mask hash does not match bytes")
        key = f"{case.cad_revision}/{case.view_id}"
        case_ownership = ownership_by_key.get(key)
        if case_ownership is None:
            raise ValueError("feature oracle revision/view ownership is missing")
        mapping = map_final_mask(
            case.authoritative_mask_bytes,
            case_ownership,
            minimum_winner_pixels=8,
            ambiguity_margin=0.10,
        )
        target_pixels = mapping.owner_pixel_counts.get(case.expected_feature_id, 0)
        conserved = (
            mapping.owned_pixel_count + mapping.unmapped_pixel_count
            == mapping.final_positive_pixel_count
        )
        correct = (
            mapping.predicted_feature_id == case.expected_feature_id
            and target_pixels >= 8
            and conserved
            and hash_matches[key]
        )
        if correct:
            correct_cases += 1
        elif mapping.status == "AMBIGUOUS":
            ambiguous_cases += 1
        elif mapping.predicted_feature_id is None:
            null_cases += 1
        else:
            wrong_cases += 1
        records.append(
            {
                "authoritative_mask_sha256": case.authoritative_mask_sha256,
                "authoritative_positive_pixels": mapping.final_positive_pixel_count,
                "case_id": case.case_id,
                "correct": correct,
                "expected_feature_id": case.expected_feature_id,
                "hash_binding_matches": hash_matches[key],
                "owned_pixel_count": mapping.owned_pixel_count,
                "ownership_map_sha256": mapping.ownership_map_sha256,
                "predicted_feature_id": mapping.predicted_feature_id,
                "status": mapping.status,
                "target_owned_pixels": target_pixels,
                "unmapped_pixel_count": mapping.unmapped_pixel_count,
            }
        )
    passed = (
        correct_cases == 60
        and ambiguous_cases == 0
        and null_cases == 0
        and wrong_cases == 0
        and all(hash_matches.values())
    )
    return FeatureOracleResult(
        case_count=len(defects),
        correct_cases=correct_cases,
        ambiguous_cases=ambiguous_cases,
        null_cases=null_cases,
        wrong_cases=wrong_cases,
        ownership_hashes=ownership_hashes,
        records=tuple(records),
        passed=passed,
    )


def _validate_development_corpus(
    generated: Sequence[E1V2GeneratedCase],
    *,
    protocol: E1V2Protocol,
    external_scope_projection: tuple[str, ...],
    external_request_count: int,
) -> DevelopmentCorpus:
    members = tuple(generated)
    if external_scope_projection != (EvaluationScope.DEVELOPMENT.value,):
        raise ValueError("development corpus external scope projection is invalid")
    if external_request_count != 1:
        raise ValueError("development corpus must have exactly one external request")
    expected_groups = tuple(
        group
        for group, count in (
            (CaseGroup.CLEAN, 24),
            (CaseGroup.NUISANCE, 30),
            (CaseGroup.DEFECT, 60),
            (CaseGroup.TRUST_BOUNDARY, 6),
        )
        for _ in range(count)
    )
    if len(members) != 120 or tuple(item.plan.group for item in members) != expected_groups:
        raise ValueError("development corpus ordered group membership is invalid")
    if len({item.plan.case_id for item in members}) != 120:
        raise ValueError("development corpus case IDs are not unique")
    if len({item.plan.seed for item in members}) != 120:
        raise ValueError("development corpus seeds are not unique")
    if len({item.case_binding_sha256 for item in members}) != 120:
        raise ValueError("development corpus case bindings are not unique")

    v1_generator = E1Generator()
    cases: list[StudyTruthCase] = []
    for generated_case in members:
        plan = generated_case.plan
        render_plan = plan._render_plan
        if plan.scope is not EvaluationScope.DEVELOPMENT:
            raise ValueError("development corpus emitted a protected scope")
        expected_id = f"e1-v2-development-{plan.group.value}-{plan.ordinal:03d}"
        if plan.case_id != expected_id:
            raise ValueError("development corpus case ID binding is invalid")
        if (
            render_plan.case_id != plan.case_id
            or render_plan.seed != plan.seed
            or render_plan.group is not plan.group
        ):
            raise ValueError("development plan and render recipe binding is invalid")
        _validate_generated_hashes(generated_case)
        expected_binding = protocol.case_binding_sha256(
            scope=plan.scope,
            case_id=plan.case_id,
            recipe_id=plan.recipe_id,
            seed_family=plan.seed_family,
            seed=plan.seed,
            reference_sha256=generated_case.reference_sha256,
            inspection_sha256=generated_case.inspection_sha256,
            authoritative_mask_sha256=generated_case.authoritative_mask_sha256,
            expected_outcome=plan.expected_outcome.value,
            defect_id=plan.defect_id,
        )
        if generated_case.case_binding_sha256 != expected_binding:
            raise ValueError("development generated case binding does not match")
        proof = _prove_applied_transform(
            generated_case,
            protocol=protocol,
            v1_generator=v1_generator,
        )
        if not proof.replay_matches:
            raise ValueError("development generated case replay failed")
        defect = render_plan.defect
        cases.append(
            StudyTruthCase(
                case_id=plan.case_id,
                seed=plan.seed,
                group=plan.group.value,
                expected_outcome=plan.expected_outcome.value,
                part_id=render_plan.part_id,
                cad_revision=render_plan.cad_revision.value,
                view_id=render_plan.view_id.value,
                reference_bytes=generated_case.reference_bytes,
                inspection_bytes=generated_case.inspection_bytes,
                authoritative_mask_bytes=generated_case.authoritative_mask_bytes,
                reference_sha256=generated_case.reference_sha256,
                inspection_sha256=generated_case.inspection_sha256,
                authoritative_mask_sha256=generated_case.authoritative_mask_sha256,
                applied_transform=proof.applied_transform,
                defect_type=None if defect is None else defect.defect_type.value,
                defect_severity=None if defect is None else defect.severity.value,
                expected_feature_id=None if defect is None else defect.target_feature_id,
                nuisance_types=tuple(
                    nuisance.nuisance_type.value for nuisance in render_plan.nuisances
                ),
                case_binding_sha256=generated_case.case_binding_sha256,
                trust_boundary=plan.group is CaseGroup.TRUST_BOUNDARY,
            )
        )
    return DevelopmentCorpus(
        cases=tuple(cases),
        counts=_DEVELOPMENT_COUNTS,
        scope_projection=external_scope_projection,
        external_request_count=external_request_count,
        internal_membership_validation_count=len(members),
    )


@lru_cache(maxsize=1)
def _default_replay_dependencies() -> tuple[E1V2Protocol, E1Generator]:
    return load_e1_v2_protocol(), E1Generator()


def _prove_applied_transform(
    generated: E1V2GeneratedCase,
    *,
    protocol: E1V2Protocol,
    v1_generator: E1Generator,
) -> AppliedTransformProof:
    plan = generated.plan
    render_plan = plan._render_plan
    width, height = v1_generator.protocol.image_size
    geometry = geometry_for_case(
        render_plan.cad_revision,
        render_plan.view_id,
        image_size=(width, height),
        feature_regions=protocol.feature_ownership(
            render_plan.cad_revision, render_plan.view_id
        ).feature_boxes,
    )
    reference = _render_pristine(render_plan, geometry)
    reference_bytes = encode_png(reference, mode="RGB")
    if (
        reference_bytes != generated.reference_bytes
        or sha256_bytes(reference_bytes) != generated.reference_sha256
    ):
        raise ValueError("applied-transform proof reference replay does not match")
    mask = Image.new("L", (width, height), 0)
    if plan.group is CaseGroup.DEFECT:
        if render_plan.defect is None:
            raise ValueError("applied-transform proof defect truth is missing")
        inspection, mask = render_defect_truth(
            reference,
            render_plan.defect,
            seed=render_plan.seed,
            geometry=geometry,
        )
    elif plan.group is CaseGroup.NUISANCE:
        inspection = reference.copy()
        for nuisance in render_plan.nuisances:
            inspection = _apply_nuisance(inspection, nuisance, render_plan.seed, geometry)
    else:
        inspection = reference.copy()
    replay_bytes = encode_png(inspection, mode="RGB")
    replay_sha256 = sha256_bytes(replay_bytes)
    mask_bytes = encode_png(mask, mode="L")
    if (
        mask_bytes != generated.authoritative_mask_bytes
        or sha256_bytes(mask_bytes) != generated.authoritative_mask_sha256
    ):
        raise ValueError("applied-transform proof truth replay does not match")
    if sha256_bytes(generated.inspection_bytes) != generated.inspection_sha256:
        raise ValueError("applied-transform proof inspection hash does not match bytes")
    replay_matches = (
        replay_bytes == generated.inspection_bytes
        and replay_sha256 == generated.inspection_sha256
    )
    if not replay_matches:
        raise ValueError("applied-transform proof inspection replay does not match")
    return AppliedTransformProof(
        case_id=plan.case_id,
        applied_transform=applied_affine_from_plan(plan),
        replay_sha256=replay_sha256,
        inspection_sha256=generated.inspection_sha256,
        replay_matches=True,
    )


def _validate_generated_hashes(generated: E1V2GeneratedCase) -> None:
    bindings = (
        (generated.reference_bytes, generated.reference_sha256, "RGB", False),
        (generated.inspection_bytes, generated.inspection_sha256, "RGB", False),
        (
            generated.authoritative_mask_bytes,
            generated.authoritative_mask_sha256,
            "L",
            True,
        ),
    )
    for payload, declared, mode, mask in bindings:
        if sha256_bytes(payload) != declared:
            raise ValueError("development generated source hash does not match bytes")
        _decode_canonical_png(payload, mode=mode, expected_size=_IMAGE_SIZE, mask=mask)


def _validate_corpus_projection(corpus: DevelopmentCorpus) -> None:
    if dict(corpus.counts) != _DEVELOPMENT_COUNTS or len(corpus.cases) != 120:
        raise ValueError("development corpus count projection is invalid")
    if corpus.scope_projection != (EvaluationScope.DEVELOPMENT.value,):
        raise ValueError("development corpus scope projection is invalid")
    if corpus.external_request_count != 1 or corpus.internal_membership_validation_count != 120:
        raise ValueError("development corpus request accounting is invalid")
    if len({case.case_id for case in corpus.cases}) != 120:
        raise ValueError("development corpus case identity projection is invalid")


def _validate_result_binding(case: StudyTruthCase, result: StudyInferenceResult) -> None:
    _require_source_hashes(case)
    reference_sha256 = result.source_hashes.get("reference_sha256")
    inspection_sha256 = result.source_hashes.get("inspection_sha256")
    if (
        reference_sha256 != case.reference_sha256
        or inspection_sha256 != case.inspection_sha256
    ):
        raise ValueError("study result source hashes do not match truth case")
    trace = result.transform_trace
    if (
        trace.reference_sha256 != case.reference_sha256
        or trace.source_inspection_sha256 != case.inspection_sha256
        or trace.applied_transform != case.applied_transform
    ):
        raise ValueError("study result transform trace does not match truth case")
    if sha256_bytes(result.predicted_mask_bytes) != result.predicted_mask_sha256:
        raise ValueError("study result predicted-mask hash does not match bytes")
    if result.feature_mapping.final_mask_sha256 != result.predicted_mask_sha256:
        raise ValueError("study result feature mapping is not bound to the final mask")


def _require_source_hashes(case: StudyTruthCase) -> None:
    bindings = (
        (case.reference_bytes, case.reference_sha256),
        (case.inspection_bytes, case.inspection_sha256),
        (case.authoritative_mask_bytes, case.authoritative_mask_sha256),
    )
    if any(sha256_bytes(payload) != declared for payload, declared in bindings):
        raise ValueError("truth-case source hash does not match bytes")


def _decode_rgb(payload: bytes) -> np.ndarray:
    return _decode_canonical_png(
        payload,
        mode="RGB",
        expected_size=_IMAGE_SIZE,
        mask=False,
    )


def _decode_mask(payload: bytes) -> np.ndarray:
    pixels = _decode_canonical_png(
        payload,
        mode="L",
        expected_size=_IMAGE_SIZE,
        mask=True,
    )
    values = set(int(value) for value in np.unique(pixels))
    if not values.issubset({0, 255}):
        raise ValueError("study mask must contain only 0 and 255")
    return pixels > 0


def _stored_magnitude(values: Mapping[str, float], name: str) -> float:
    value = values.get(name)
    if value is None or not math.isfinite(value) or value < 0:
        raise ValueError(f"stored nuisance magnitude is invalid: {name}")
    return value


def _recall(predicted: np.ndarray, truth: np.ndarray) -> float:
    denominator = int(np.count_nonzero(truth))
    return 1.0 if denominator == 0 else float(np.count_nonzero(predicted & truth) / denominator)


def _dice(predicted: np.ndarray, truth: np.ndarray) -> float:
    denominator = int(np.count_nonzero(predicted) + np.count_nonzero(truth))
    return 1.0 if denominator == 0 else float(2 * np.count_nonzero(predicted & truth) / denominator)


def _iou(predicted: np.ndarray, truth: np.ndarray) -> float:
    union = int(np.count_nonzero(predicted | truth))
    return 1.0 if union == 0 else float(np.count_nonzero(predicted & truth) / union)
