"""Truth-free E1 v2 inference policy and auditable geometry trace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.e1.domain import CadRevision, ViewId
from manufacturing_vision_studio.e1.domain_v2 import E1V2GeneratedCase
from manufacturing_vision_studio.e1.feature_mapping import (
    FeatureMappingResult,
    build_ownership_map,
    map_final_mask,
)
from manufacturing_vision_studio.e1.geometry import (
    AlignmentResult,
    AlignmentStatus,
    AlignmentTrace,
    align_largest_component,
    geometry_config_from_document,
)
from manufacturing_vision_studio.e1.geometry_search import align_coarse_to_fine
from manufacturing_vision_studio.e1.model import (
    MaskPostprocessing,
    filter_structural_residue,
    localized_anomaly_score,
)
from manufacturing_vision_studio.e1.oracle import _decode_canonical_png
from manufacturing_vision_studio.e1.protocol_v2 import (
    PROJECT_ROOT,
    E1V2Protocol,
    load_e1_v2_protocol,
)
from manufacturing_vision_studio.errors import MVSError
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.model import DeterministicDifferenceModel, ModelConfig

ActualOutcome = Literal["NORMAL", "ANOMALY", "ABSTAIN"]
DEFAULT_SELECTION_PATH = PROJECT_ROOT / "configs" / "evaluation" / "e1-v2-candidate-selection.json"


@dataclass(frozen=True, slots=True)
class E1V2InferenceInput:
    """The complete runtime surface after offline truth has been discarded."""

    reference_bytes: bytes
    inspection_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    part_id: str
    cad_revision: CadRevision
    view_id: ViewId

    def __post_init__(self) -> None:
        if not self.part_id:
            raise ValueError("part_id is required")
        _validate_source(
            self.reference_bytes,
            self.reference_sha256,
            source_name="reference",
        )
        _validate_source(
            self.inspection_bytes,
            self.inspection_sha256,
            source_name="inspection",
        )

    @classmethod
    def from_generated(cls, generated: E1V2GeneratedCase) -> E1V2InferenceInput:
        """Validate canonical source bindings, then structurally erase all truth."""

        render_plan = generated.plan._render_plan
        return cls(
            reference_bytes=generated.reference_bytes,
            inspection_bytes=generated.inspection_bytes,
            reference_sha256=generated.reference_sha256,
            inspection_sha256=generated.inspection_sha256,
            part_id=render_plan.part_id,
            cad_revision=render_plan.cad_revision,
            view_id=render_plan.view_id,
        )


@dataclass(frozen=True, slots=True)
class ModelRegistration:
    dx: int
    dy: int
    mean_absolute_error: float

    def as_record(self) -> dict[str, int | float]:
        return {
            "dx": self.dx,
            "dy": self.dy,
            "mean_absolute_error": self.mean_absolute_error,
        }


@dataclass(frozen=True, slots=True)
class E1V2GeometryTrace:
    """Wrap Task 3 alignment without conflating its three shift meanings."""

    alignment: AlignmentTrace
    final_model_registration: ModelRegistration | None

    @property
    def pre_normalization_shift(self) -> tuple[float, float]:
        return (
            self.alignment.pre_normalization_shift_x,
            self.alignment.pre_normalization_shift_y,
        )

    @property
    def post_normalization_shift(self) -> tuple[float, float]:
        return (
            self.alignment.post_normalization_shift_x,
            self.alignment.post_normalization_shift_y,
        )

    def as_record(self) -> dict[str, object]:
        record = self.alignment.as_record()
        record["final_model_registration_x"] = (
            None if self.final_model_registration is None else self.final_model_registration.dx
        )
        record["final_model_registration_y"] = (
            None if self.final_model_registration is None else self.final_model_registration.dy
        )
        record["final_model_registration_mean_absolute_error"] = (
            None
            if self.final_model_registration is None
            else self.final_model_registration.mean_absolute_error
        )
        return record


@dataclass(frozen=True, slots=True)
class E1V2CaseResult:
    actual_outcome: ActualOutcome
    anomaly_score: float | None
    global_anomaly_score: float | None
    abstention_reason: str | None
    predicted_mask_bytes: bytes | None
    predicted_mask_sha256: str | None
    geometry_trace: E1V2GeometryTrace
    feature_mapping: FeatureMappingResult | None
    model_registration: ModelRegistration | None
    registered_inspection_sha256: str | None
    postprocessing_inspection_sha256: str | None
    mask_postprocessing: MaskPostprocessing | None
    source_hashes: dict[str, str]

    @property
    def final_model_registration(self) -> ModelRegistration | None:
        return self.model_registration

    def as_record(self) -> dict[str, Any]:
        return {
            "actual_outcome": self.actual_outcome,
            "anomaly_score": self.anomaly_score,
            "global_anomaly_score": self.global_anomaly_score,
            "abstention_reason": self.abstention_reason,
            "predicted_mask_sha256": self.predicted_mask_sha256,
            "geometry_trace": self.geometry_trace.as_record(),
            "feature_mapping": (
                None if self.feature_mapping is None else self.feature_mapping.as_record()
            ),
            "model_registration": (
                None if self.model_registration is None else self.model_registration.as_record()
            ),
            "registered_inspection_sha256": self.registered_inspection_sha256,
            "postprocessing_inspection_sha256": self.postprocessing_inspection_sha256,
            "mask_postprocessing": (
                None if self.mask_postprocessing is None else self.mask_postprocessing.as_record()
            ),
            "source_hashes": dict(sorted(self.source_hashes.items())),
        }


class E1V2InferencePolicy:
    """Run one verified geometry candidate, then map only the persisted final mask."""

    def __init__(
        self,
        protocol: E1V2Protocol | None = None,
        *,
        selection_path: Path | str = DEFAULT_SELECTION_PATH,
        candidate_id: str | None = None,
        model: DeterministicDifferenceModel | None = None,
        ingestor: ImageIngestor | None = None,
    ) -> None:
        self.protocol = protocol or load_e1_v2_protocol()
        self.geometry_config = geometry_config_from_document(self.protocol.document)
        if candidate_id is None:
            from manufacturing_vision_studio.e1.diagnostics_v2 import load_candidate_selection

            selection = load_candidate_selection(selection_path)
            candidate_id = selection.selected_candidate_id
            if candidate_id is None:
                raise ValueError("candidate selection is HOLD")
        if candidate_id not in {"A", "B"}:
            raise ValueError("candidate_id must be A or B")
        self.candidate_id = candidate_id
        self.model = model or DeterministicDifferenceModel(ModelConfig())
        self.ingestor = ingestor or ImageIngestor()
        self.image_threshold = float(
            self.protocol.document["threshold_selection"]["locked_image_threshold"]
        )

    def inspect(self, inference: E1V2InferenceInput) -> E1V2CaseResult:
        """Perform truth-free inference; unsafe geometry fails closed before mapping."""

        try:
            alignment = self._align(inference)
        except (MVSError, ValueError):
            return self._abstain(inference, "GEOMETRY_INVALID")
        if alignment.status is AlignmentStatus.ABSTAIN:
            return self._abstain(
                inference,
                alignment.trace.abstention_reason or "GEOMETRY_INVALID",
                alignment=alignment,
            )

        try:
            normalized_bytes = (
                alignment.inspection_bytes
                if alignment.status is AlignmentStatus.APPLIED
                else inference.inspection_bytes
            )
            reference = self.ingestor.ingest_bytes(
                inference.reference_bytes,
                filename="e1-v2-reference.png",
                declared_media_type="image/png",
            )
            inspection = self.ingestor.ingest_bytes(
                normalized_bytes,
                filename="e1-v2-inspection.png",
                declared_media_type="image/png",
            )
            model_result = self.model.inspect(reference, inspection)
            registration = ModelRegistration(
                dx=model_result.registration.dx,
                dy=model_result.registration.dy,
                mean_absolute_error=model_result.registration.mean_absolute_error,
            )
            postprocessing = filter_structural_residue(
                model_result.mask_bytes,
                reference_bytes=inference.reference_bytes,
                inspection_bytes=model_result.registered_bytes,
                normalization_applied=alignment.status is AlignmentStatus.APPLIED,
            )
            ownership = build_ownership_map(
                self.protocol.feature_ownership(inference.cad_revision, inference.view_id),
                self.geometry_config.image_size,
            )
            feature_mapping = map_final_mask(postprocessing.mask_bytes, ownership)
            anomaly_score = localized_anomaly_score(postprocessing.mask_bytes)
            outcome = classify_v2_score(anomaly_score, self.image_threshold)
            trace = E1V2GeometryTrace(alignment.trace, registration)
            return E1V2CaseResult(
                actual_outcome=outcome,
                anomaly_score=anomaly_score,
                global_anomaly_score=model_result.anomaly_score,
                abstention_reason=None,
                predicted_mask_bytes=postprocessing.mask_bytes,
                predicted_mask_sha256=postprocessing.mask_sha256,
                geometry_trace=trace,
                feature_mapping=feature_mapping,
                model_registration=registration,
                registered_inspection_sha256=model_result.registered_sha256,
                postprocessing_inspection_sha256=model_result.registered_sha256,
                mask_postprocessing=postprocessing,
                source_hashes={
                    "reference_sha256": inference.reference_sha256,
                    "inspection_sha256": inference.inspection_sha256,
                },
            )
        except (MVSError, ValueError):
            return self._abstain(inference, "INFERENCE_INVALID", alignment=alignment)

    def _align(self, inference: E1V2InferenceInput) -> AlignmentResult:
        align = align_largest_component if self.candidate_id == "A" else align_coarse_to_fine
        return align(
            inference.reference_bytes,
            inference.inspection_bytes,
            self.geometry_config,
        )

    @staticmethod
    def _abstain(
        inference: E1V2InferenceInput,
        reason: str,
        *,
        alignment: AlignmentResult | None = None,
    ) -> E1V2CaseResult:
        alignment_trace = (
            AlignmentTrace(
                normalization_status=AlignmentStatus.ABSTAIN.value,
                status_reason=reason,
                abstention_reason=reason,
            )
            if alignment is None
            else alignment.trace
        )
        return E1V2CaseResult(
            actual_outcome="ABSTAIN",
            anomaly_score=None,
            global_anomaly_score=None,
            abstention_reason=reason,
            predicted_mask_bytes=None,
            predicted_mask_sha256=None,
            geometry_trace=E1V2GeometryTrace(alignment_trace, None),
            feature_mapping=None,
            model_registration=None,
            registered_inspection_sha256=None,
            postprocessing_inspection_sha256=None,
            mask_postprocessing=None,
            source_hashes={
                "reference_sha256": inference.reference_sha256,
                "inspection_sha256": inference.inspection_sha256,
            },
        )


def classify_v2_score(score: float, threshold: float) -> Literal["NORMAL", "ANOMALY"]:
    if not 0 <= score <= 1 or not 0 <= threshold <= 1:
        raise ValueError("score and threshold must be within [0, 1]")
    return "ANOMALY" if score >= threshold else "NORMAL"


def _validate_source(payload: bytes, claimed_sha256: str, *, source_name: str) -> None:
    if sha256_bytes(payload) != claimed_sha256:
        raise ValueError(f"{source_name} SHA-256 does not match source bytes")
    try:
        _decode_canonical_png(
            payload,
            mode="RGB",
            expected_size=(512, 384),
            mask=False,
        )
    except MVSError as exc:
        raise ValueError(f"{source_name} is not canonical 512x384 RGB PNG") from exc
