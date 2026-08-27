from __future__ import annotations

import dataclasses
import io
from dataclasses import dataclass

import pytest
from PIL import Image, ImageDraw

import manufacturing_vision_studio.e1.study_inference_v2 as study_module
from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.domain import CadRevision, ViewId
from manufacturing_vision_studio.e1.geometry import _inverse_affine
from manufacturing_vision_studio.e1.known_transform_v2 import (
    AppliedAffineTransform,
    KnownTransformResult,
    ResamplingMode,
    normalize_known_transform,
)
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol
from manufacturing_vision_studio.e1.study_inference_v2 import (
    StudyInferenceAdapter,
    StudyInferenceInput,
    classify_study_score,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import load_study_protocol_v2
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.model import DeterministicDifferenceModel

_IMAGE_SIZE = (512, 384)


@dataclass(frozen=True, slots=True)
class SourceFixture:
    reference_bytes: bytes
    inspection_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    normalized: KnownTransformResult


@dataclass(slots=True)
class AdapterSpies:
    adapter: StudyInferenceAdapter
    events: list[str]
    model_registered_bytes: bytes | None = None
    postfilter_inspection: bytes | None = None
    mapping_mask: bytes | None = None
    normalization_applied: bool | None = None
    classifier_arguments: tuple[float, float] | None = None


def make_source_fixture() -> SourceFixture:
    reference_image = Image.new("RGB", _IMAGE_SIZE, (17, 23, 31))
    draw = ImageDraw.Draw(reference_image)
    draw.polygon(((52, 44), (177, 61), (155, 161), (76, 139)), fill=(231, 37, 19))
    draw.rectangle((246, 89, 313, 137), fill=(29, 211, 83))
    draw.ellipse((355, 217, 411, 295), fill=(61, 97, 239))
    draw.polygon(((192, 257), (270, 243), (286, 328), (214, 311)), fill=(241, 197, 41))
    reference_bytes = encode_png(reference_image, mode="RGB")
    applied = AppliedAffineTransform(1.08, 7.5, 9.0, -4.0)
    with Image.open(io.BytesIO(reference_bytes)) as source:
        inspection_image = source.transform(
            source.size,
            Image.Transform.AFFINE,
            _inverse_affine(
                source.size,
                applied.rotation_degrees,
                applied.scale_factor,
                applied.translation_x,
                applied.translation_y,
            ),
            resample=Image.Resampling.NEAREST,
            fillcolor=(17, 23, 31),
        )
    inspection_bytes = encode_png(inspection_image, mode="RGB")
    reference_sha256 = sha256_bytes(reference_bytes)
    inspection_sha256 = sha256_bytes(inspection_bytes)
    normalized = normalize_known_transform(
        reference_bytes,
        inspection_bytes,
        reference_sha256=reference_sha256,
        inspection_sha256=inspection_sha256,
        applied_transform=applied,
        resampling=ResamplingMode.NEAREST,
    )
    return SourceFixture(
        reference_bytes=reference_bytes,
        inspection_bytes=inspection_bytes,
        reference_sha256=reference_sha256,
        inspection_sha256=inspection_sha256,
        normalized=normalized,
    )


@pytest.fixture(scope="module")
def source_fixture() -> SourceFixture:
    return make_source_fixture()


def inference_from(source: SourceFixture, **changes: object) -> StudyInferenceInput:
    values: dict[str, object] = {
        "reference_bytes": source.reference_bytes,
        "inspection_bytes": source.inspection_bytes,
        "reference_sha256": source.reference_sha256,
        "inspection_sha256": source.inspection_sha256,
        "part_id": "mvs-e1-bracket",
        "cad_revision": CadRevision.REV_A,
        "view_id": ViewId.FRONT,
        "normalized": source.normalized,
    }
    values.update(changes)
    return StudyInferenceInput(**values)  # type: ignore[arg-type]


@pytest.fixture
def inference(source_fixture: SourceFixture) -> StudyInferenceInput:
    return inference_from(source_fixture)


@pytest.fixture
def adapter_spies(monkeypatch: pytest.MonkeyPatch) -> AdapterSpies:
    events: list[str] = []
    model = DeterministicDifferenceModel()

    class RecordingIngestor(ImageIngestor):
        def ingest_bytes(
            self,
            data: bytes,
            *,
            filename: str,
            declared_media_type: str | None = None,
        ):
            events.append(f"ingest:{filename}")
            return super().ingest_bytes(
                data,
                filename=filename,
                declared_media_type=declared_media_type,
            )

    spies = AdapterSpies(
        adapter=StudyInferenceAdapter(
            load_study_protocol_v2(),
            load_e1_v2_protocol(),
            model=model,
            ingestor=RecordingIngestor(),
        ),
        events=events,
    )
    real_model_inspect = model.inspect
    real_filter = study_module.filter_structural_residue
    real_ownership = study_module.build_ownership_map
    real_mapper = study_module.map_final_mask
    real_score = study_module.localized_anomaly_score
    real_classify = study_module.classify_study_score

    def recording_model(*args, **kwargs):
        events.append("model")
        result = real_model_inspect(*args, **kwargs)
        spies.model_registered_bytes = result.registered_bytes
        return result

    def recording_filter(mask_bytes, **kwargs):
        events.append("postfilter")
        spies.postfilter_inspection = kwargs["inspection_bytes"]
        spies.normalization_applied = kwargs["normalization_applied"]
        return real_filter(mask_bytes, **kwargs)

    def recording_ownership(*args, **kwargs):
        events.append("ownership")
        return real_ownership(*args, **kwargs)

    def recording_mapper(mask_bytes, ownership, **kwargs):
        events.append("mapping")
        spies.mapping_mask = mask_bytes
        return real_mapper(mask_bytes, ownership, **kwargs)

    def recording_score(*args, **kwargs):
        events.append("score")
        return real_score(*args, **kwargs)

    def recording_classify(score: float, threshold: float):
        events.append("threshold")
        spies.classifier_arguments = (score, threshold)
        return real_classify(score, threshold)

    monkeypatch.setattr(model, "inspect", recording_model)
    monkeypatch.setattr(study_module, "filter_structural_residue", recording_filter)
    monkeypatch.setattr(study_module, "build_ownership_map", recording_ownership)
    monkeypatch.setattr(study_module, "map_final_mask", recording_mapper)
    monkeypatch.setattr(study_module, "localized_anomaly_score", recording_score)
    monkeypatch.setattr(study_module, "classify_study_score", recording_classify)
    return spies


def test_study_inference_input_has_only_truth_free_fields() -> None:
    assert {field.name for field in dataclasses.fields(StudyInferenceInput)} == {
        "reference_bytes",
        "inspection_bytes",
        "reference_sha256",
        "inspection_sha256",
        "part_id",
        "cad_revision",
        "view_id",
        "normalized",
    }


def test_study_input_rejects_a_normalizer_result_from_another_source(
    source_fixture: SourceFixture,
) -> None:
    changed = source_fixture.inspection_bytes + b"changed"
    with pytest.raises(ValueError, match="source inspection hash"):
        inference_from(
            source_fixture,
            inspection_bytes=changed,
            inspection_sha256=sha256_bytes(changed),
        )


def test_study_input_rejects_a_normalizer_result_from_another_reference(
    source_fixture: SourceFixture,
) -> None:
    mismatched = dataclasses.replace(
        source_fixture.normalized,
        trace=dataclasses.replace(
            source_fixture.normalized.trace,
            reference_sha256="0" * 64,
        ),
    )
    with pytest.raises(ValueError, match="normalizer reference hash"):
        inference_from(source_fixture, normalized=mismatched)


def test_study_input_rejects_normalized_bytes_with_a_false_hash(
    source_fixture: SourceFixture,
) -> None:
    mismatched = dataclasses.replace(
        source_fixture.normalized,
        normalized_sha256="f" * 64,
    )
    with pytest.raises(ValueError, match="normalized output hash"):
        inference_from(source_fixture, normalized=mismatched)


def test_study_input_rejects_a_normalized_trace_with_a_false_hash(
    source_fixture: SourceFixture,
) -> None:
    mismatched = dataclasses.replace(
        source_fixture.normalized,
        trace=dataclasses.replace(
            source_fixture.normalized.trace,
            normalized_sha256="f" * 64,
        ),
    )
    with pytest.raises(ValueError, match="normalizer trace normalized hash"):
        inference_from(source_fixture, normalized=mismatched)


def test_adapter_uses_registered_bytes_then_final_mask(
    adapter_spies: AdapterSpies,
    inference: StudyInferenceInput,
) -> None:
    result = adapter_spies.adapter.inspect(inference)
    assert adapter_spies.postfilter_inspection == adapter_spies.model_registered_bytes
    assert adapter_spies.mapping_mask == result.predicted_mask_bytes
    assert adapter_spies.normalization_applied is inference.normalized.trace.applied


def test_adapter_preserves_the_exact_retained_pipeline_order(
    adapter_spies: AdapterSpies,
    inference: StudyInferenceInput,
) -> None:
    adapter_spies.adapter.inspect(inference)
    assert adapter_spies.events == [
        "ingest:e1-study-reference.png",
        "ingest:e1-study-inspection.png",
        "model",
        "postfilter",
        "ownership",
        "mapping",
        "score",
        "threshold",
    ]


def test_result_binds_registered_mask_mapping_and_all_three_sources(
    adapter_spies: AdapterSpies,
    inference: StudyInferenceInput,
) -> None:
    result = adapter_spies.adapter.inspect(inference)
    assert result.registered_inspection_sha256 == sha256_bytes(
        adapter_spies.model_registered_bytes or b""
    )
    assert result.predicted_mask_sha256 == sha256_bytes(result.predicted_mask_bytes)
    assert result.feature_mapping.final_mask_sha256 == result.predicted_mask_sha256
    assert result.transform_trace is inference.normalized.trace
    assert result.source_hashes == {
        "inspection_sha256": inference.inspection_sha256,
        "normalized_inspection_sha256": inference.normalized.normalized_sha256,
        "reference_sha256": inference.reference_sha256,
    }
    with pytest.raises(TypeError):
        result.source_hashes["reference_sha256"] = "changed"  # type: ignore[index]


def test_result_record_returns_fresh_sorted_dictionaries(
    adapter_spies: AdapterSpies,
    inference: StudyInferenceInput,
) -> None:
    result = adapter_spies.adapter.inspect(inference)
    first = result.as_record()
    second = result.as_record()
    assert first is not second
    assert list(first["source_hashes"]) == sorted(result.source_hashes)
    assert first["source_hashes"] is not second["source_hashes"]
    assert first["feature_mapping"] is not second["feature_mapping"]
    assert first["model_registration"] == {
        "dx": result.model_registration.dx,
        "dy": result.model_registration.dy,
        "mean_absolute_error": result.model_registration.mean_absolute_error,
    }


def test_adapter_does_not_convert_downstream_failure_into_a_result(
    monkeypatch: pytest.MonkeyPatch,
    inference: StudyInferenceInput,
) -> None:
    adapter = StudyInferenceAdapter(load_study_protocol_v2(), load_e1_v2_protocol())

    def fail(*_args: object, **_kwargs: object) -> None:
        raise ValueError("model integrity failure")

    monkeypatch.setattr(adapter.model, "inspect", fail)
    with pytest.raises(ValueError, match="model integrity failure"):
        adapter.inspect(inference)


def test_adapter_uses_the_task_owned_exact_threshold(
    adapter_spies: AdapterSpies,
    inference: StudyInferenceInput,
) -> None:
    changed_limits = dict(adapter_spies.adapter.study_protocol.phase_1_limits)
    changed_limits["threshold"] = 0.75
    adapter_spies.adapter.study_protocol = dataclasses.replace(
        adapter_spies.adapter.study_protocol,
        phase_1_limits=changed_limits,
    )

    result = adapter_spies.adapter.inspect(inference)

    assert adapter_spies.classifier_arguments == (result.anomaly_score, 0.0025)


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.002499999, "NORMAL"), (0.0025, "ANOMALY")],
)
def test_threshold_is_inclusive(score: float, expected: str) -> None:
    assert classify_study_score(score, 0.0025) == expected


@pytest.mark.parametrize(("score", "threshold"), [(-0.1, 0.5), (0.1, 1.1)])
def test_threshold_rejects_values_outside_unit_interval(
    score: float,
    threshold: float,
) -> None:
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        classify_study_score(score, threshold)
