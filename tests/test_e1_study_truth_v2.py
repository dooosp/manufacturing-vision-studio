from __future__ import annotations

import ast
import dataclasses
import io
from dataclasses import replace
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from PIL import Image

import manufacturing_vision_studio.e1.study_truth_v2 as truth_module
from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.diagnostics_v2 import (
    _render_diagnostic as historical_render_diagnostic,
)
from manufacturing_vision_studio.e1.diagnostics_v2 import build_scale_diagnostic_matrix
from manufacturing_vision_studio.e1.domain import CaseGroup, NuisanceType
from manufacturing_vision_studio.e1.domain_v2 import (
    E1V2GeneratedCase,
    EvaluationScope,
)
from manufacturing_vision_studio.e1.generator_v2 import E1V2Generator
from manufacturing_vision_studio.e1.known_transform_v2 import (
    AppliedAffineTransform,
    ResamplingMode,
    normalize_known_transform,
    reference_boundary_band,
)
from manufacturing_vision_studio.e1.metrics_v2 import E1V2EvaluationObservation
from manufacturing_vision_studio.e1.protocol_v2 import load_e1_v2_protocol
from manufacturing_vision_studio.e1.study_inference_v2 import (
    StudyInferenceAdapter,
    StudyInferenceResult,
)
from manufacturing_vision_studio.e1.study_protocol_v2 import (
    DevelopmentGates,
    DiagnosticGates,
    load_frozen_diagnostic_matrix,
    load_study_protocol_v2,
)
from manufacturing_vision_studio.e1.study_truth_v2 import (
    DevelopmentCorpus,
    DevelopmentCorpusProvider,
    DiagnosticObservation,
    StudyTruthCase,
    diagnostic_observation,
    make_truth_free_input,
    observation_from_study,
    prove_applied_transform,
    raw_identity_difference_mask,
    reduce_development_mode,
    reduce_diagnostic_mode,
    render_diagnostic,
    run_feature_ownership_oracle,
)

_IMAGE_SIZE = (512, 384)
_IDENTITY = AppliedAffineTransform(1.0, 0.0, 0.0, 0.0)
_OWNERSHIP_HASHES = {
    "rev-A/front": "eadc490b04f8240e8356b3e20e75db08d79dfc5e27af180574d707836b3b776f",
    "rev-A/oblique_left": (
        "2d2a52ecae44ccae98455180211aaf528078707948dbf83f792223c550d3a074"
    ),
    "rev-A/oblique_right": (
        "8c42a88c3ffdf3dda10b073665b6d7a565ddde54a7a7450ba3c0f4782be14477"
    ),
    "rev-B/front": "5f69348a9ce7b646054dce02f95a0ff8ebd420c641ab40f414b0afa645ef49bc",
    "rev-B/oblique_left": (
        "1fb2f752d738a7bf595f8cae97860452a3a8628ea5cb3eec4347d1f42fe43b8b"
    ),
    "rev-B/oblique_right": (
        "373337ec46da320dbbcdf0ffa14c22794db05208cd9491e5b272e0d34169830d"
    ),
}


def decode_rgb(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == _IMAGE_SIZE
        assert getattr(image, "n_frames", 1) == 1
        assert not image.info
        image.load()
        assert encode_png(image, mode="RGB") == payload
        return np.asarray(image, dtype=np.uint8).copy()


def decode_mask(payload: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(payload)) as image:
        assert image.format == "PNG"
        assert image.mode == "L"
        assert image.size == _IMAGE_SIZE
        assert getattr(image, "n_frames", 1) == 1
        assert not image.info
        image.load()
        assert encode_png(image, mode="L") == payload
        values = np.asarray(image, dtype=np.uint8).copy()
    assert set(int(value) for value in np.unique(values)) <= {0, 255}
    return values > 0


@pytest.fixture(scope="module")
def development_corpus() -> DevelopmentCorpus:
    return DevelopmentCorpusProvider(load_e1_v2_protocol()).load()


@pytest.fixture(scope="module")
def diagnostic_case() -> StudyTruthCase:
    return render_diagnostic(
        load_frozen_diagnostic_matrix()[48],
        load_study_protocol_v2(),
        load_e1_v2_protocol(),
    )


@pytest.fixture(scope="module")
def diagnostic_result(diagnostic_case: StudyTruthCase) -> StudyInferenceResult:
    normalized = normalize_known_transform(
        diagnostic_case.reference_bytes,
        diagnostic_case.inspection_bytes,
        reference_sha256=diagnostic_case.reference_sha256,
        inspection_sha256=diagnostic_case.inspection_sha256,
        applied_transform=diagnostic_case.applied_transform,
        resampling=ResamplingMode.NEAREST,
    )
    inference = make_truth_free_input(diagnostic_case, normalized)
    return StudyInferenceAdapter(load_study_protocol_v2(), load_e1_v2_protocol()).inspect(
        inference
    )


@pytest.fixture(scope="module")
def generated_nuisance_cases() -> tuple[E1V2GeneratedCase, ...]:
    generator = E1V2Generator(load_e1_v2_protocol())
    plans = generator.plan_cases(EvaluationScope.DEVELOPMENT)
    return tuple(
        generator.generate_case(plan) for plan in plans if plan.group is CaseGroup.NUISANCE
    )


@pytest.fixture
def complete_mode_rows() -> tuple[DiagnosticObservation, ...]:
    rows: list[DiagnosticObservation] = []
    for ordinal in range(108):
        defect = ordinal >= 84
        rows.append(
            DiagnosticObservation(
                diagnostic_id=f"e1-v2-development-diagnostic-{ordinal:03d}",
                seed=800000 + ordinal,
                mode=ResamplingMode.NEAREST,
                defect_row=defect,
                medium_high_row=defect,
                actual_outcome="ANOMALY" if not defect or ordinal != 84 else "NORMAL",
                identity_recall=1.0,
                study_recall=0.96 if defect else 1.0,
                identity_dice=0.90,
                study_dice=0.895 if defect else 0.90,
                study_iou=0.81,
                total_residual=10,
                boundary_residual=4,
                outside_boundary_residual=6,
                record={"ordinal": ordinal},
            )
        )
    return tuple(rows)


def _evaluation_observation(
    *,
    case_id: str,
    group: str,
    actual_outcome: str,
    severity: str | None = None,
) -> E1V2EvaluationObservation:
    positive = group == "defect"
    return E1V2EvaluationObservation(
        case_id=case_id,
        scope="development",
        group=group,
        expected_outcome="ANOMALY" if positive else "NORMAL",
        actual_outcome=actual_outcome,  # type: ignore[arg-type]
        anomaly_score=0.5,
        severity=severity,
        truth_positive_pixels=10 if positive else 0,
        predicted_positive_pixels=10 if positive else 0,
        intersection_pixels=8 if positive else 0,
        total_pixels=512 * 384,
        expected_feature_id="top_face" if positive else None,
        predicted_feature_id="top_face" if positive else None,
    )


@pytest.fixture
def complete_development_observations() -> tuple[E1V2EvaluationObservation, ...]:
    rows: list[E1V2EvaluationObservation] = []
    rows.extend(
        _evaluation_observation(
            case_id=f"e1-v2-development-clean-{ordinal:03d}",
            group="clean",
            actual_outcome="NORMAL",
        )
        for ordinal in range(24)
    )
    rows.extend(
        _evaluation_observation(
            case_id=f"e1-v2-development-nuisance-{ordinal:03d}",
            group="nuisance",
            actual_outcome="ANOMALY" if ordinal == 0 else "NORMAL",
        )
        for ordinal in range(30)
    )
    for ordinal in range(60):
        severity = ("LOW", "MEDIUM", "HIGH")[ordinal // 20]
        rows.append(
            _evaluation_observation(
                case_id=f"e1-v2-development-defect-{ordinal:03d}",
                group="defect",
                actual_outcome="ANOMALY",
                severity=severity,
            )
        )
    return tuple(rows)


def test_diagnostic_renderer_has_sampled_byte_parity_with_retained_renderer() -> None:
    e1_protocol = load_e1_v2_protocol()
    study_protocol = load_study_protocol_v2()
    frozen = load_frozen_diagnostic_matrix()
    historical = build_scale_diagnostic_matrix(e1_protocol)

    for ordinal in (0, 48, 60, 72, 84, 96):
        old_input, old_truth, old_truth_bytes = historical_render_diagnostic(
            historical[ordinal], e1_protocol
        )
        case = render_diagnostic(frozen[ordinal], study_protocol, e1_protocol)

        assert case.reference_bytes == old_input.reference_bytes
        assert case.inspection_bytes == old_input.inspection_bytes
        assert case.authoritative_mask_bytes == old_truth_bytes
        assert np.array_equal(decode_mask(case.authoritative_mask_bytes), old_truth)
        assert case.reference_sha256 == old_input.reference_sha256
        assert case.inspection_sha256 == old_input.inspection_sha256
        assert case.case_binding_sha256 is None
        assert case.applied_transform == AppliedAffineTransform(
            1.0 + frozen[ordinal].scale_delta,
            frozen[ordinal].rotation_degrees,
            float(frozen[ordinal].translation_x),
            float(frozen[ordinal].translation_y),
        )


def test_development_provider_requests_only_literal_development_scope(
    development_corpus: DevelopmentCorpus,
) -> None:
    assert development_corpus.scope_projection == ("development",)
    assert development_corpus.external_request_count == 1
    assert development_corpus.internal_membership_validation_count == 120
    assert development_corpus.counts == {
        "clean": 24,
        "nuisance": 30,
        "defect": 60,
        "trust_boundary": 6,
        "total": 120,
    }


def test_provider_revalidations_and_emissions_stay_development_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[EvaluationScope] = []
    emitted: list[EvaluationScope] = []
    real_plan_cases = E1V2Generator.plan_cases
    real_generate_case = E1V2Generator.generate_case

    def guarded_plan_cases(
        self: E1V2Generator, scope: EvaluationScope | str
    ) -> tuple[object, ...]:
        resolved = EvaluationScope(scope)
        if resolved is not EvaluationScope.DEVELOPMENT:
            raise AssertionError(f"protected planning reached: {resolved.value}")
        requested.append(resolved)
        return real_plan_cases(self, resolved)

    def guarded_generate_case(
        self: E1V2Generator, plan: object
    ) -> E1V2GeneratedCase:
        scope = plan.scope  # type: ignore[attr-defined]
        if scope is not EvaluationScope.DEVELOPMENT:
            raise AssertionError(f"protected rendering reached: {scope.value}")
        emitted.append(scope)
        return real_generate_case(self, plan)  # type: ignore[arg-type]

    monkeypatch.setattr(E1V2Generator, "plan_cases", guarded_plan_cases)
    monkeypatch.setattr(E1V2Generator, "generate_case", guarded_generate_case)
    provider = DevelopmentCorpusProvider(load_e1_v2_protocol())

    first = provider.load()
    second = provider.load()

    assert second is first
    assert requested == [EvaluationScope.DEVELOPMENT] * 121
    assert emitted == [EvaluationScope.DEVELOPMENT] * 120


def test_applied_transform_replay_covers_all_nine_stored_nuisance_families(
    generated_nuisance_cases: tuple[E1V2GeneratedCase, ...],
) -> None:
    families: set[NuisanceType] = set()
    proofs = {}
    for generated in generated_nuisance_cases:
        families.update(item.nuisance_type for item in generated.plan._render_plan.nuisances)
        proof = prove_applied_transform(generated)
        proofs[generated.plan.case_id] = proof
        assert proof.replay_matches is True
        assert proof.replay_sha256 == generated.inspection_sha256
        assert proof.inspection_sha256 == generated.inspection_sha256

    assert families == set(NuisanceType)
    assert proofs["e1-v2-development-nuisance-000"].applied_transform == (
        AppliedAffineTransform(1.0, 0.0, 1.0, 1.0)
    )
    assert proofs["e1-v2-development-nuisance-001"].applied_transform == (
        AppliedAffineTransform(1.0, 0.505784, 0.0, 0.0)
    )
    assert proofs["e1-v2-development-nuisance-002"].applied_transform == (
        AppliedAffineTransform(1.019846, 0.0, 0.0, 0.0)
    )


def test_transform_proof_fails_closed_on_nonreplayable_inspection(
    generated_nuisance_cases: tuple[E1V2GeneratedCase, ...],
) -> None:
    generated = generated_nuisance_cases[0]
    tampered = replace(
        generated,
        inspection_bytes=generated.reference_bytes,
        inspection_sha256=generated.reference_sha256,
    )

    with pytest.raises(ValueError, match="replay"):
        prove_applied_transform(tampered)


def test_non_nuisance_development_rows_bind_explicit_identity_geometry(
    development_corpus: DevelopmentCorpus,
) -> None:
    non_nuisance = [case for case in development_corpus.cases if case.group != "nuisance"]
    nongeometric_nuisance = [
        case
        for case in development_corpus.cases
        if case.group == "nuisance"
        and not ({"translation", "rotation", "scale"} & set(case.nuisance_types))
    ]

    assert len(non_nuisance) == 90
    assert len(nongeometric_nuisance) == 20
    assert all(case.applied_transform == _IDENTITY for case in non_nuisance)
    assert all(case.applied_transform == _IDENTITY for case in nongeometric_nuisance)


def test_make_truth_free_input_is_the_only_truth_discarding_projection(
    diagnostic_case: StudyTruthCase,
) -> None:
    normalized = normalize_known_transform(
        diagnostic_case.reference_bytes,
        diagnostic_case.inspection_bytes,
        reference_sha256=diagnostic_case.reference_sha256,
        inspection_sha256=diagnostic_case.inspection_sha256,
        applied_transform=diagnostic_case.applied_transform,
        resampling=ResamplingMode.NEAREST,
    )

    inference = make_truth_free_input(diagnostic_case, normalized)

    assert {field.name for field in dataclasses.fields(inference)} == {
        "reference_bytes",
        "inspection_bytes",
        "reference_sha256",
        "inspection_sha256",
        "part_id",
        "cad_revision",
        "view_id",
        "normalized",
    }
    assert inference.reference_bytes == diagnostic_case.reference_bytes
    assert inference.inspection_bytes == diagnostic_case.inspection_bytes


def test_truth_projection_rejects_binding_only_trust_rows(
    development_corpus: DevelopmentCorpus,
    diagnostic_case: StudyTruthCase,
) -> None:
    trust = next(case for case in development_corpus.cases if case.trust_boundary)
    normalized = normalize_known_transform(
        diagnostic_case.reference_bytes,
        diagnostic_case.inspection_bytes,
        reference_sha256=diagnostic_case.reference_sha256,
        inspection_sha256=diagnostic_case.inspection_sha256,
        applied_transform=diagnostic_case.applied_transform,
        resampling=ResamplingMode.NEAREST,
    )

    with pytest.raises(ValueError, match="binding-only"):
        make_truth_free_input(trust, normalized)


def test_identity_comparator_is_raw_rgb_threshold_not_an_inference_pass(
    diagnostic_case: StudyTruthCase,
) -> None:
    mask = decode_mask(raw_identity_difference_mask(diagnostic_case))
    reference = decode_rgb(diagnostic_case.reference_bytes).astype(np.int16)
    inspection = decode_rgb(diagnostic_case.inspection_bytes).astype(np.int16)
    assert np.array_equal(mask, np.max(np.abs(reference - inspection), axis=2) >= 32)


def test_diagnostic_observation_joins_truth_and_boundary_only_after_inference(
    diagnostic_case: StudyTruthCase,
    diagnostic_result: StudyInferenceResult,
) -> None:
    identity_bytes = raw_identity_difference_mask(diagnostic_case)
    boundary = reference_boundary_band(diagnostic_case.reference_bytes)

    row = diagnostic_observation(
        diagnostic_case,
        diagnostic_result,
        identity_bytes,
        boundary,
    )

    truth = decode_mask(diagnostic_case.authoritative_mask_bytes)
    predicted = decode_mask(diagnostic_result.predicted_mask_bytes)
    identity = decode_mask(identity_bytes)
    band = np.frombuffer(boundary.band_mask_bytes, dtype=np.bool_).reshape(truth.shape)
    truth_count = int(np.count_nonzero(truth))
    predicted_count = int(np.count_nonzero(predicted))
    identity_intersection = int(np.count_nonzero(identity & truth))
    predicted_intersection = int(np.count_nonzero(predicted & truth))
    predicted_union = int(np.count_nonzero(predicted | truth))

    assert row.identity_recall == (
        1.0 if truth_count == 0 else identity_intersection / truth_count
    )
    assert row.study_recall == (
        1.0 if truth_count == 0 else predicted_intersection / truth_count
    )
    assert row.study_iou == (
        1.0 if predicted_union == 0 else predicted_intersection / predicted_union
    )
    assert row.total_residual == predicted_count
    assert row.boundary_residual == int(np.count_nonzero(predicted & band))
    assert row.outside_boundary_residual == row.total_residual - row.boundary_residual
    assert row.mode is ResamplingMode.NEAREST


def test_diagnostic_observation_rejects_a_drifted_boundary_contract(
    diagnostic_case: StudyTruthCase,
    diagnostic_result: StudyInferenceResult,
) -> None:
    boundary = reference_boundary_band(diagnostic_case.reference_bytes)
    drifted = replace(boundary, radius=4)

    with pytest.raises(ValueError, match="boundary"):
        diagnostic_observation(
            diagnostic_case,
            diagnostic_result,
            raw_identity_difference_mask(diagnostic_case),
            drifted,
        )


def test_observation_from_study_constructs_the_offline_metric_join(
    development_corpus: DevelopmentCorpus,
) -> None:
    case = next(item for item in development_corpus.cases if item.group == "defect")
    normalized = normalize_known_transform(
        case.reference_bytes,
        case.inspection_bytes,
        reference_sha256=case.reference_sha256,
        inspection_sha256=case.inspection_sha256,
        applied_transform=case.applied_transform,
        resampling=ResamplingMode.NEAREST,
    )
    result = StudyInferenceAdapter(load_study_protocol_v2(), load_e1_v2_protocol()).inspect(
        make_truth_free_input(case, normalized)
    )

    observation = observation_from_study(case, result)

    truth = decode_mask(case.authoritative_mask_bytes)
    predicted = decode_mask(result.predicted_mask_bytes)
    assert observation.case_id == case.case_id
    assert observation.scope == "development"
    assert observation.truth_positive_pixels == int(np.count_nonzero(truth))
    assert observation.predicted_positive_pixels == int(np.count_nonzero(predicted))
    assert observation.intersection_pixels == int(np.count_nonzero(truth & predicted))
    assert observation.expected_feature_id == case.expected_feature_id
    assert observation.predicted_feature_id == result.feature_mapping.predicted_feature_id


def test_diagnostic_reducer_uses_exact_defect_denominators(
    complete_mode_rows: tuple[DiagnosticObservation, ...],
) -> None:
    summary = reduce_diagnostic_mode(
        ResamplingMode.NEAREST,
        complete_mode_rows,
        DiagnosticGates(0.05, 0.01, 0.90),
    )
    assert summary.row_count == 108
    assert summary.defect_drop_denominator == 24
    assert summary.medium_high_classification_denominator == 24
    assert summary.maximum_recall_drop == pytest.approx(0.04)
    assert summary.median_dice_drop == pytest.approx(0.005)
    assert summary.medium_high_classification_recall == pytest.approx(23 / 24)
    assert summary.eligible is True


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "wrong_mode", "swapped_seed", "swapped_truth"],
)
def test_diagnostic_reducer_rejects_incomplete_mode_rows(
    complete_mode_rows: tuple[DiagnosticObservation, ...],
    mutation: str,
) -> None:
    rows = list(complete_mode_rows)
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = replace(rows[-1], diagnostic_id=rows[0].diagnostic_id)
    elif mutation == "wrong_mode":
        rows[-1] = replace(rows[-1], mode=ResamplingMode.BILINEAR)
    elif mutation == "swapped_seed":
        rows[0] = replace(rows[0], seed=rows[1].seed)
        rows[1] = replace(rows[1], seed=complete_mode_rows[0].seed)
    else:
        rows[0] = replace(rows[0], defect_row=True, medium_high_row=True)
        rows[84] = replace(rows[84], defect_row=False, medium_high_row=False)

    with pytest.raises(ValueError, match="diagnostic"):
        reduce_diagnostic_mode(
            ResamplingMode.NEAREST,
            rows,
            DiagnosticGates(0.05, 0.01, 0.90),
        )


def test_development_reducer_uses_exact_fixed_denominators(
    complete_development_observations: tuple[E1V2EvaluationObservation, ...],
) -> None:
    summary = reduce_development_mode(
        ResamplingMode.BILINEAR,
        complete_development_observations,
        DevelopmentGates(0.90, 0.05, 0.70, 0.95),
    )

    assert summary.mode is ResamplingMode.BILINEAR
    assert summary.member_count == 120
    assert summary.inference_count == 114
    assert summary.trust_binding_count == 6
    assert summary.medium_high_recall == 1.0
    assert summary.nuisance_false_positive_rate == pytest.approx(1 / 30)
    assert summary.positive_median_dice == 0.8
    assert summary.feature_mapping_accuracy == 1.0
    assert summary.passed_all_gates is True


def test_development_reducer_rejects_a_changed_metric_denominator(
    complete_development_observations: tuple[E1V2EvaluationObservation, ...],
) -> None:
    wrong_severity = tuple(
        replace(row, severity="LOW")
        if row.case_id == "e1-v2-development-defect-020"
        else row
        for row in complete_development_observations
    )

    with pytest.raises(ValueError, match="denominator"):
        reduce_development_mode(
            ResamplingMode.NEAREST,
            wrong_severity,
            DevelopmentGates(0.90, 0.05, 0.70, 0.95),
        )


def test_feature_oracle_requires_exact_target_feature_agreement(
    development_corpus: DevelopmentCorpus,
) -> None:
    e1_protocol = load_e1_v2_protocol()
    oracle = run_feature_ownership_oracle(
        development_corpus,
        e1_protocol,
        load_study_protocol_v2(),
    )
    assert oracle.passed is True
    assert oracle.case_count == 60
    assert oracle.correct_cases == 60
    assert oracle.ambiguous_cases == 0
    assert oracle.null_cases == 0
    assert oracle.wrong_cases == 0
    assert oracle.ownership_hashes == _OWNERSHIP_HASHES
    assert len(oracle.records) == 60
    assert all(cast(int, record["target_owned_pixels"]) >= 8 for record in oracle.records)
    assert all(
        cast(int, record["owned_pixel_count"])
        + cast(int, record["unmapped_pixel_count"])
        == cast(int, record["authoritative_positive_pixels"])
        for record in oracle.records
    )


def test_feature_oracle_never_enters_truth_free_inference(
    monkeypatch: pytest.MonkeyPatch,
    development_corpus: DevelopmentCorpus,
) -> None:
    def forbidden_inference(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("feature oracle entered inference")

    monkeypatch.setattr(StudyInferenceAdapter, "inspect", forbidden_inference)

    oracle = run_feature_ownership_oracle(
        development_corpus,
        load_e1_v2_protocol(),
        load_study_protocol_v2(),
    )

    assert oracle.passed is True


def test_feature_oracle_fails_when_study_hash_binding_drifts(
    development_corpus: DevelopmentCorpus,
) -> None:
    study_protocol = load_study_protocol_v2()
    changed = dict(study_protocol.ownership_map_hashes)
    changed["rev-A/front"] = "0" * 64
    drifted = replace(study_protocol, ownership_map_hashes=changed)

    oracle = run_feature_ownership_oracle(
        development_corpus,
        load_e1_v2_protocol(),
        drifted,
    )

    assert oracle.passed is False
    assert oracle.wrong_cases > 0


def test_truth_layer_has_no_forbidden_or_protected_scope_imports() -> None:
    module_path = Path(truth_module.__file__ or "")
    tree = ast.parse(module_path.read_text())
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    protected_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "EvaluationScope"
    }

    assert imported_modules.isdisjoint(
        {
            "manufacturing_vision_studio.e1.diagnostics_v2",
            "manufacturing_vision_studio.e1.geometry",
            "manufacturing_vision_studio.e1.geometry_search",
            "manufacturing_vision_studio.e1.policy_v2",
        }
    )
    assert protected_attributes == {"DEVELOPMENT"}


def test_all_corpus_bindings_are_unique_and_byte_bound(
    development_corpus: DevelopmentCorpus,
) -> None:
    cases = development_corpus.cases
    assert len({case.case_id for case in cases}) == 120
    assert len({case.seed for case in cases}) == 120
    assert len({case.case_binding_sha256 for case in cases}) == 120
    assert all(case.reference_sha256 == sha256_bytes(case.reference_bytes) for case in cases)
    assert all(case.inspection_sha256 == sha256_bytes(case.inspection_bytes) for case in cases)
    assert all(
        case.authoritative_mask_sha256 == sha256_bytes(case.authoritative_mask_bytes)
        for case in cases
    )


def test_corpus_cases_are_in_frozen_group_order(
    development_corpus: DevelopmentCorpus,
) -> None:
    groups = tuple(case.group for case in development_corpus.cases)
    assert groups == (
        ("clean",) * 24
        + ("nuisance",) * 30
        + ("defect",) * 60
        + ("trust_boundary",) * 6
    )
