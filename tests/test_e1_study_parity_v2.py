from __future__ import annotations

import ast
from pathlib import Path

import pytest
from test_e1_study_inference_v2 import inference_from, make_source_fixture

import manufacturing_vision_studio.e1.study_inference_v2 as study_module
from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.e1.geometry import (
    AlignmentResult,
    AlignmentStatus,
    AlignmentTrace,
)
from manufacturing_vision_studio.e1.policy_v2 import (
    E1V2InferenceInput,
    E1V2InferencePolicy,
)
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol
from manufacturing_vision_studio.e1.study_inference_v2 import (
    StudyInferenceAdapter,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import load_study_protocol_v2


def test_study_adapter_matches_the_retained_historical_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source_fixture()
    inference = inference_from(source)
    e1_protocol = load_e1_v2_protocol()
    study_result = StudyInferenceAdapter(load_study_protocol_v2(), e1_protocol).inspect(inference)

    status = (
        AlignmentStatus.APPLIED if source.normalized.trace.applied else AlignmentStatus.IDENTITY
    )

    def exact_known_transform(
        _self: E1V2InferencePolicy,
        _inference: E1V2InferenceInput,
    ) -> AlignmentResult:
        return AlignmentResult(
            status=status,
            inspection_bytes=source.normalized.normalized_bytes,
            inspection_sha256=source.normalized.normalized_sha256,
            trace=AlignmentTrace(
                normalization_status=status.value,
                status_reason="KNOWN_TRANSFORM_TEST_PARITY",
                abstention_reason=None,
            ),
        )

    monkeypatch.setattr(E1V2InferencePolicy, "_align", exact_known_transform)
    historical_input = E1V2InferenceInput(
        reference_bytes=source.reference_bytes,
        inspection_bytes=source.inspection_bytes,
        reference_sha256=source.reference_sha256,
        inspection_sha256=source.inspection_sha256,
        part_id="mvs-e1-bracket",
        cad_revision=inference.cad_revision,
        view_id=inference.view_id,
    )
    historical = E1V2InferencePolicy(e1_protocol, candidate_id="A").inspect(historical_input)

    assert historical.predicted_mask_bytes == study_result.predicted_mask_bytes
    assert historical.predicted_mask_sha256 == study_result.predicted_mask_sha256
    assert historical.registered_inspection_sha256 == (study_result.registered_inspection_sha256)
    assert historical.mask_postprocessing is not None
    assert historical.mask_postprocessing.as_record() == (
        study_result.mask_postprocessing.as_record()
    )
    assert historical.feature_mapping is not None
    assert historical.feature_mapping.as_record() == study_result.feature_mapping.as_record()
    assert historical.anomaly_score == study_result.anomaly_score
    assert historical.actual_outcome == study_result.actual_outcome
    assert sha256_bytes(study_result.predicted_mask_bytes) == study_result.predicted_mask_sha256


def test_production_adapter_has_no_forbidden_historical_imports() -> None:
    module_path = Path(study_module.__file__ or "")
    tree = ast.parse(module_path.read_text())
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = {
        "manufacturing_vision_studio.e1.policy_v2",
        "manufacturing_vision_studio.e1.geometry",
        "manufacturing_vision_studio.e1.geometry_search",
        "manufacturing_vision_studio.e1.diagnostics_v2",
    }
    assert imported_modules.isdisjoint(forbidden)
