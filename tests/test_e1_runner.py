from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
from PIL import Image

import manufacturing_vision_studio.e1.runner as runner_module
from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.artifacts import E1ArtifactError, E1ArtifactStore
from manufacturing_vision_studio.e1.baseline import BaselineGateResult
from manufacturing_vision_studio.e1.domain import (
    CadRevision,
    CaseGroup,
    DatasetProfile,
    DatasetSplit,
    E1CasePlan,
    E1GeneratedCase,
    ExpectedOutcome,
    SupportBoundary,
    TrustBoundarySpec,
    ViewId,
)
from manufacturing_vision_studio.e1.generator import E1Generator
from manufacturing_vision_studio.e1.policy import E1CaseResult
from manufacturing_vision_studio.e1.protocol import load_e1_protocol
from manufacturing_vision_studio.e1.runner import (
    ERROR_GALLERY_MAX_CASES,
    _execute_inference_split,
    _GalleryCandidate,
    _profile_trust_observations,
    _render_overlay,
    _split_hash_overlap_count,
    _threshold_lock_document,
    _validate_bootstrap_arguments,
    _verify_cross_artifact_bindings,
    _verify_gallery_bindings,
    _write_error_gallery,
    run_e1_evaluation,
    verify_e1_results,
)
from manufacturing_vision_studio.e1.trust_boundaries import (
    TrustBoundaryReport,
    TrustBoundaryResult,
)


def _clean_plan(case_id: str, split: DatasetSplit) -> E1CasePlan:
    return E1CasePlan(
        case_id=case_id,
        profile_membership=(DatasetProfile.FULL, DatasetProfile.MINI),
        split=split,
        group=CaseGroup.CLEAN,
        ordinal=0,
        seed_family=f"family-{split.value}",
        seed=1,
        recipe_id=f"recipe-{case_id}",
        recipe_version="1.0.0",
        part_id="MVS-E1-PLATE-001",
        cad_revision=CadRevision.REV_A,
        view_id=ViewId.FRONT,
        expected_outcome=ExpectedOutcome.NORMAL,
        support_boundary=SupportBoundary.SUPPORTED_NORMAL_RANGE,
    )


def _trust_plan(case_id: str, split: DatasetSplit, scenario: str) -> E1CasePlan:
    return E1CasePlan(
        case_id=case_id,
        profile_membership=(DatasetProfile.FULL, DatasetProfile.MINI),
        split=split,
        group=CaseGroup.TRUST_BOUNDARY,
        ordinal=0,
        seed_family=f"trust-family-{split.value}",
        seed=2,
        recipe_id=f"recipe-{case_id}",
        recipe_version="1.0.0",
        part_id="MVS-E1-PLATE-001",
        cad_revision=CadRevision.REV_B,
        view_id=ViewId.OBLIQUE_LEFT,
        expected_outcome=ExpectedOutcome.ABSTAIN,
        support_boundary=SupportBoundary.UNSUPPORTED_OR_ABSTAIN_RANGE,
        trust_boundary=TrustBoundarySpec(
            scenario_id=scenario,
            expected_error_code="SCHEMA_INVALID",
            publication_allowed=False,
        ),
    )


def _generated(plan: E1CasePlan) -> E1GeneratedCase:
    rgb = encode_png(Image.new("RGB", (2, 2), (128, 128, 128)), mode="RGB")
    mask = encode_png(Image.new("L", (2, 2), 0), mode="L")
    return E1GeneratedCase(
        plan=plan,
        generator_id="test-generator",
        generator_version="1.0.0",
        generator_configuration_sha256="a" * 64,
        reference_bytes=rgb,
        inspection_bytes=rgb,
        authoritative_mask_bytes=mask,
        reference_sha256=sha256_bytes(rgb),
        inspection_sha256=sha256_bytes(rgb),
        authoritative_mask_sha256=sha256_bytes(mask),
        case_binding_sha256=sha256_bytes(plan.case_id.encode()),
    )


def _case_result(generated: E1GeneratedCase, *, actual: str = "NORMAL") -> E1CaseResult:
    return E1CaseResult(
        case_id=generated.plan.case_id,
        split=generated.plan.split.value,
        group=generated.plan.group.value,
        expected_outcome=generated.plan.expected_outcome.value,
        actual_outcome=cast(Any, actual),
        anomaly_score=None if actual == "ABSTAIN" else 0.0,
        global_anomaly_score=None,
        abstention_reason="MODEL_ABSTAINED" if actual == "ABSTAIN" else None,
        predicted_mask_bytes=None,
        predicted_mask_sha256=None,
        truth_positive_pixels=0,
        predicted_positive_pixels=0,
        intersection_pixels=0,
        total_pixels=4,
        expected_feature_id=None,
        predicted_feature_id=None,
        registration=None,
        normalization=None,
        mask_postprocessing=None,
        source_hashes={
            "reference_sha256": generated.reference_sha256,
            "inspection_sha256": generated.inspection_sha256,
            "authoritative_mask_sha256": generated.authoritative_mask_sha256,
            "generator_configuration_sha256": generated.generator_configuration_sha256,
        },
    )


class _FakeGenerator:
    def __init__(self, generated: dict[str, E1GeneratedCase]) -> None:
        self.generated = generated
        self.calls: list[str] = []

    def generate_case(self, plan: E1CasePlan) -> E1GeneratedCase:
        self.calls.append(plan.case_id)
        return self.generated[plan.case_id]


class _FakePolicy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inspect(self, generated: E1GeneratedCase) -> E1CaseResult:
        self.calls.append(generated.plan.case_id)
        return _case_result(generated)


class _MockCorpusGenerator:
    instances: ClassVar[list[_MockCorpusGenerator]] = []

    def __init__(self, protocol: Any = None) -> None:
        self.protocol = protocol or load_e1_protocol()
        self._planner = E1Generator(self.protocol)
        self.calls: list[str] = []
        self.__class__.instances.append(self)

    def plan_cases(
        self, profile: DatasetProfile | str = DatasetProfile.FULL
    ) -> tuple[E1CasePlan, ...]:
        return self._planner.plan_cases(profile)

    def generate_case(self, plan: E1CasePlan) -> E1GeneratedCase:
        self.calls.append(plan.case_id)
        digest = hashlib.sha256(plan.case_id.encode()).digest()
        reference_image = Image.frombytes("RGB", (2, 2), digest[:12])
        inspection_image = Image.frombytes("RGB", (2, 2), digest[12:24])
        mask_image = Image.new("L", (2, 2), 0)
        if plan.group is CaseGroup.DEFECT:
            mask_image.putpixel((0, 0), 255)
        reference = encode_png(reference_image, mode="RGB")
        inspection = encode_png(inspection_image, mode="RGB")
        mask = encode_png(mask_image, mode="L")
        reference_sha = sha256_bytes(reference)
        inspection_sha = sha256_bytes(inspection)
        mask_sha = sha256_bytes(mask)
        return E1GeneratedCase(
            plan=plan,
            generator_id=self.protocol.generator_id,
            generator_version=self.protocol.generator_version,
            generator_configuration_sha256=self.protocol.generator_configuration_sha256,
            reference_bytes=reference,
            inspection_bytes=inspection,
            authoritative_mask_bytes=mask,
            reference_sha256=reference_sha,
            inspection_sha256=inspection_sha,
            authoritative_mask_sha256=mask_sha,
            case_binding_sha256=self.protocol.case_binding_sha256(
                plan,
                reference_sha256=reference_sha,
                inspection_sha256=inspection_sha,
                authoritative_mask_sha256=mask_sha,
            ),
        )


class _MockInferencePolicy:
    instances: ClassVar[list[_MockInferencePolicy]] = []
    calibration_fails = False
    threshold_path: Path | None = None

    def __init__(self, protocol: Any) -> None:
        self.protocol = protocol
        self.image_threshold = float(
            protocol.section("threshold_selection")["locked_image_threshold"]
        )
        self.calls: list[E1CasePlan] = []
        self.__class__.instances.append(self)

    def inspect(self, generated: E1GeneratedCase) -> E1CaseResult:
        plan = generated.plan
        if plan.split is DatasetSplit.TEST:
            assert self.threshold_path is not None
            assert self.threshold_path.is_file(), "test ran before threshold lock publication"
        self.calls.append(plan)
        defect = plan.defect
        forced_failure = (
            self.calibration_fails
            and plan.split is DatasetSplit.CALIBRATION
            and plan.group is CaseGroup.NUISANCE
        )
        anomaly = defect is not None or forced_failure
        truth_pixels = 1 if defect is not None else 0
        predicted_pixels = 1 if anomaly else 0
        intersection = 1 if defect is not None else 0
        predicted_mask = generated.authoritative_mask_bytes
        return E1CaseResult(
            case_id=plan.case_id,
            split=plan.split.value,
            group=plan.group.value,
            expected_outcome=plan.expected_outcome.value,
            actual_outcome="ANOMALY" if anomaly else "NORMAL",
            anomaly_score=0.1 if anomaly else 0.0,
            global_anomaly_score=0.1 if anomaly else 0.0,
            abstention_reason=None,
            predicted_mask_bytes=predicted_mask,
            predicted_mask_sha256=sha256_bytes(predicted_mask),
            truth_positive_pixels=truth_pixels,
            predicted_positive_pixels=predicted_pixels,
            intersection_pixels=intersection,
            total_pixels=4,
            expected_feature_id=None if defect is None else defect.target_feature_id,
            predicted_feature_id=None if defect is None else defect.target_feature_id,
            registration=None,
            normalization=None,
            mask_postprocessing=None,
            source_hashes={
                "reference_sha256": generated.reference_sha256,
                "inspection_sha256": generated.inspection_sha256,
                "authoritative_mask_sha256": generated.authoritative_mask_sha256,
                "generator_configuration_sha256": generated.generator_configuration_sha256,
            },
        )

    def model_record(self) -> dict[str, Any]:
        pipeline = self.protocol.section("evaluation_pipeline")
        return {
            "pipeline_id": pipeline["pipeline_id"],
            "pipeline_version": pipeline["pipeline_version"],
            "model_id": pipeline["model_id"],
            "model_version": pipeline["model_version"],
            "model_artifact_sha256": pipeline["model_artifact_sha256"],
            "configuration_sha256": pipeline["configuration_sha256"],
            "locked_image_threshold": self.image_threshold,
            "threshold_source_split": "calibration",
        }


def _passing_trust_report() -> TrustBoundaryReport:
    cases = load_e1_protocol().section("taxonomies")["trust_boundary_cases"]
    return TrustBoundaryReport(
        tuple(
            TrustBoundaryResult(
                scenario_id=case["scenario_id"],
                split=case["split"],
                expected_outcome="ABSTAIN",
                actual_outcome="ABSTAIN",
                expected_error_code=case["expected_error_code"],
                actual_error_code=case["expected_error_code"],
                publication_count=0,
                passed=True,
            )
            for case in cases
        )
    )


def _install_mock_runtime(monkeypatch: pytest.MonkeyPatch, output_root: Path) -> None:
    _MockCorpusGenerator.instances = []
    _MockInferencePolicy.instances = []
    _MockInferencePolicy.threshold_path = output_root / "mini" / "threshold-lock.json"
    monkeypatch.setattr(runner_module, "E1Generator", _MockCorpusGenerator)
    monkeypatch.setattr(runner_module, "E1InferencePolicy", _MockInferencePolicy)


def _calibration_metrics(*, all_passed: bool) -> dict[str, Any]:
    contracts = load_e1_protocol().document["acceptance_gates"][:4]
    gates: list[dict[str, Any]] = []
    for index, contract in enumerate(contracts):
        operator = contract["operator"]
        observed = 0.0 if operator == "lte" else 1.0
        passed = True
        if index == 0 and not all_passed:
            observed = 0.0
            passed = False
        gates.append({**contract, "observed": observed, "passed": passed, "reason": None})
    return {"gates": gates}


def test_inference_executor_never_touches_another_split() -> None:
    plans = [
        _clean_plan("development-case", DatasetSplit.DEVELOPMENT),
        _clean_plan("calibration-case", DatasetSplit.CALIBRATION),
        _clean_plan("test-case", DatasetSplit.TEST),
    ]
    generated = {plan.case_id: _generated(plan) for plan in plans}
    generator = _FakeGenerator(generated)
    policy = _FakePolicy()
    manifest_cases = {case_id: item.as_manifest_record() for case_id, item in generated.items()}

    execution = _execute_inference_split(
        cast(Any, generator),
        cast(Any, policy),
        plans,
        DatasetSplit.CALIBRATION,
        manifest_cases,
        collect_gallery=False,
    )

    assert generator.calls == ["calibration-case"]
    assert policy.calls == ["calibration-case"]
    assert [item.case_id for item in execution.observations] == ["calibration-case"]


def test_calibration_lock_is_hold_on_any_failed_gate_and_locked_only_on_all_passed() -> None:
    protocol = load_e1_protocol()
    code = {"code_commit_sha": "c" * 40, "dirty_worktree": False}

    hold = _threshold_lock_document(
        DatasetProfile.MINI,
        protocol,
        code,
        "d" * 64,
        "e" * 64,
        _calibration_metrics(all_passed=False),
    )
    locked = _threshold_lock_document(
        DatasetProfile.MINI,
        protocol,
        code,
        "d" * 64,
        "e" * 64,
        _calibration_metrics(all_passed=True),
    )

    assert (hold["lock_status"], hold["test_execution_allowed"]) == ("HOLD", False)
    assert hold["calibration_gate_results"][0]["reason"] == "gate_threshold_not_met"
    assert (locked["lock_status"], locked["test_execution_allowed"]) == ("LOCKED", True)
    assert [gate["gate_id"] for gate in locked["calibration_gate_results"]] == [
        "medium_high_defect_recall",
        "nuisance_only_false_positive_rate",
        "positive_case_median_dice",
        "affected_feature_mapping_accuracy",
    ]


def test_split_overlap_counts_composite_bindings_but_not_empty_truth_hashes() -> None:
    protocol = load_e1_protocol()

    def case(split: str, suffix: str) -> dict[str, Any]:
        return {
            "case_id": f"case-{suffix}",
            "split": split,
            "recipe_id": f"recipe-{suffix}",
            "seed_family": f"seed-{suffix}",
            "source_hashes": {
                "reference_sha256": sha256_bytes(f"reference-{suffix}".encode()),
                "inspection_sha256": sha256_bytes(f"inspection-{suffix}".encode()),
                "authoritative_mask_sha256": "0" * 64,
                "case_binding_sha256": sha256_bytes(f"binding-{suffix}".encode()),
            },
        }

    cases = [case("development", "dev"), case("calibration", "cal"), case("test", "test")]
    assert _split_hash_overlap_count(cases, protocol) == 0

    cases[2]["source_hashes"]["case_binding_sha256"] = cases[0]["source_hashes"][
        "case_binding_sha256"
    ]
    cases[2]["recipe_id"] = cases[0]["recipe_id"]
    assert _split_hash_overlap_count(cases, protocol) == 2


def test_profile_trust_observations_use_only_selected_plan_cases() -> None:
    selected = _trust_plan(
        "e1-development-trust_boundary-000",
        DatasetSplit.DEVELOPMENT,
        "revision_mismatch",
    )
    report = TrustBoundaryReport(
        (
            TrustBoundaryResult(
                scenario_id="revision_mismatch",
                split="development",
                expected_outcome="ABSTAIN",
                actual_outcome="ABSTAIN",
                expected_error_code="SCHEMA_INVALID",
                actual_error_code="SCHEMA_INVALID",
                publication_count=0,
                passed=True,
            ),
            TrustBoundaryResult(
                scenario_id="outside_profile",
                split="test",
                expected_outcome="ABSTAIN",
                actual_outcome="ABSTAIN",
                expected_error_code="HASH_MISMATCH",
                actual_error_code="HASH_MISMATCH",
                publication_count=0,
                passed=True,
            ),
        )
    )

    observations, results = _profile_trust_observations([selected], report)

    assert [item.case_id for item in observations] == [selected.case_id]
    assert observations[0].trust_scenario == "revision_mismatch"
    assert set(results) == {"revision_mismatch"}


def test_error_gallery_is_bounded_and_writes_only_selected_assets(tmp_path: Path) -> None:
    candidates: list[_GalleryCandidate] = []
    for index in range(ERROR_GALLERY_MAX_CASES + 3):
        plan = _clean_plan(f"gallery-case-{index:03d}", DatasetSplit.TEST)
        generated = _generated(plan)
        candidates.append(
            _GalleryCandidate(
                generated=generated,
                result=_case_result(generated, actual="ABSTAIN"),
                category="false_positive",
            )
        )
    store = E1ArtifactStore(tmp_path / "mini")

    gallery, members = _write_error_gallery(
        store,
        DatasetProfile.MINI,
        cast(Any, _FakeGenerator({})),
        {},
        candidates,
        [],
        {},
        image_threshold=0.0025,
    )

    assert len(gallery) == ERROR_GALLERY_MAX_CASES
    assert len(members) == ERROR_GALLERY_MAX_CASES * 3
    assert all(path.startswith("assets/gallery-case-") for path in members)
    assert gallery[0]["assets"]["reference_image_url"].startswith(
        "/api/v1/e1/evaluation/assets/mini/gallery-case-000/"
    )
    assert gallery[0]["assets"]["predicted_mask_url"] is None
    assert gallery[0]["assets"]["overlay_url"] is None


def test_gallery_verifier_binds_source_assets_and_recomputes_overlay(
    tmp_path: Path,
) -> None:
    store = E1ArtifactStore(tmp_path / "mini")
    case_id = "gallery-case-000"
    reference = encode_png(Image.new("RGB", (2, 2), (40, 50, 60)), mode="RGB")
    inspection = encode_png(Image.new("RGB", (2, 2), (80, 90, 100)), mode="RGB")
    truth = encode_png(Image.new("L", (2, 2), 0), mode="L")
    predicted_image = Image.new("L", (2, 2), 0)
    predicted_image.putpixel((0, 0), 255)
    predicted = encode_png(predicted_image, mode="L")
    overlay = _render_overlay(inspection, truth, predicted)
    payloads = {
        f"assets/{case_id}/reference.png": reference,
        f"assets/{case_id}/inspection.png": inspection,
        f"assets/{case_id}/authoritative-mask.png": truth,
        f"assets/{case_id}/predicted-mask.png": predicted,
        f"assets/{case_id}/overlay.png": overlay,
    }
    for path, payload in payloads.items():
        store.write_bytes(path, payload)
    store.write_inventory("inventory.json", list(payloads))
    inventory = {record.path: record for record in store.verify_inventory("inventory.json")}
    prefix = f"/api/v1/e1/evaluation/assets/mini/{case_id}"
    result = {
        "error_gallery": [
            {
                "case_id": case_id,
                "source_hashes": {
                    "reference_sha256": sha256_bytes(reference),
                    "inspection_sha256": sha256_bytes(inspection),
                    "authoritative_mask_sha256": sha256_bytes(truth),
                    "predicted_mask_sha256": sha256_bytes(predicted),
                },
                "assets": {
                    "reference_image_url": f"{prefix}/reference.png",
                    "inspection_image_url": f"{prefix}/inspection.png",
                    "authoritative_mask_url": f"{prefix}/authoritative-mask.png",
                    "predicted_mask_url": f"{prefix}/predicted-mask.png",
                    "overlay_url": f"{prefix}/overlay.png",
                },
            }
        ]
    }

    _verify_gallery_bindings(
        result,
        profile="mini",
        inventory=inventory,
        store=store,
    )

    mismatched_source = copy.deepcopy(result)
    mismatched_source["error_gallery"][0]["source_hashes"]["reference_sha256"] = "0" * 64
    with pytest.raises(E1ArtifactError) as exc_info:
        _verify_gallery_bindings(
            mismatched_source,
            profile="mini",
            inventory=inventory,
            store=store,
        )
    assert exc_info.value.code == "HASH_MISMATCH"

    store.write_bytes(
        f"assets/{case_id}/overlay.png",
        encode_png(Image.new("RGB", (2, 2), (1, 2, 3)), mode="RGB"),
        replace=True,
    )
    store.write_json("inventory.json", store.build_inventory(list(payloads)), replace=True)
    tampered_inventory = {
        record.path: record for record in store.verify_inventory("inventory.json")
    }
    with pytest.raises(E1ArtifactError) as exc_info:
        _verify_gallery_bindings(
            result,
            profile="mini",
            inventory=tampered_inventory,
            store=store,
        )
    assert exc_info.value.code == "HASH_MISMATCH"


def test_mocked_public_runner_locks_before_test_and_publishes_verified_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "e1-output"
    _MockInferencePolicy.calibration_fails = False
    _install_mock_runtime(monkeypatch, output_root)
    monkeypatch.setattr(
        runner_module,
        "run_trust_boundary_suite",
        lambda *_args, **_kwargs: _passing_trust_report(),
    )
    monkeypatch.setattr(
        runner_module,
        "evaluate_v0_1_baseline",
        lambda _protocol: BaselineGateResult(1, 1, True, ()),
    )

    result = run_e1_evaluation("mini", output_root, bootstrap_replicates=10)

    assert result["evaluation_status"] == "COMPLETED"
    assert result["threshold"]["lock_status"] == "LOCKED"
    assert result["metrics"]["gate_summary"] == {
        "passed": 10,
        "total": 10,
        "all_passed": True,
    }
    assert result["verdict"] == "PASS"
    assert [item["category"] for item in result["error_gallery"]] == [
        "revision_mismatch",
        "unsupported_view",
        "bundle_verification_failure",
    ]
    assert verify_e1_results(output_root / "mini") == result

    store = E1ArtifactStore(output_root / "mini")
    inventory = {record.path: record for record in store.verify_inventory("inventory.json")}
    repeat_paths = (
        "repeatability/full-manifest-run-1.json",
        "repeatability/full-manifest-run-2.json",
    )
    repeat_manifests = [store.read_json(path, schema_name="case-manifest") for path in repeat_paths]
    assert [manifest["profile"] for manifest in repeat_manifests] == ["full", "full"]
    assert [manifest["manifest_sha256"] for manifest in repeat_manifests] == result[
        "reproducibility"
    ]["deterministic_projection_sha256s"]
    assert store.read_bytes(repeat_paths[0]) == store.read_bytes(repeat_paths[1])
    calibration = store.read_json("calibration-result.json")
    duplicated = copy.deepcopy(calibration)
    duplicated["case_results"][1] = copy.deepcopy(duplicated["case_results"][0])
    with pytest.raises(E1ArtifactError) as exc_info:
        _verify_cross_artifact_bindings(
            store.read_json("manifest.json", schema_name="case-manifest"),
            duplicated,
            store.read_json("threshold-lock.json", schema_name="threshold-lock"),
            result,
            store=store,
            repeatability_manifests=repeat_manifests,
            calibration_result_sha256=inventory["calibration-result.json"].sha256,
            inventory=inventory,
        )
    assert exc_info.value.code == "EVIDENCE_INCOMPLETE"

    generator = _MockCorpusGenerator.instances[0]
    policy = _MockInferencePolicy.instances[0]
    # A full-only case proves mini repeatability still rendered two independent
    # FULL manifests rather than comparing the published mini manifest.
    assert generator.calls.count("e1-development-clean-010") == 2
    splits = [plan.split for plan in policy.calls]
    assert splits.count(DatasetSplit.CALIBRATION) == 11
    assert splits.count(DatasetSplit.TEST) == 22
    assert splits == sorted(
        splits,
        key={DatasetSplit.CALIBRATION: 0, DatasetSplit.TEST: 1}.__getitem__,
    )


def test_mocked_public_runner_holds_without_any_test_or_trust_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "e1-output"
    _MockInferencePolicy.calibration_fails = True
    _install_mock_runtime(monkeypatch, output_root)

    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("post-lock evaluation ran after a calibration HOLD")

    monkeypatch.setattr(runner_module, "run_trust_boundary_suite", unexpected)
    monkeypatch.setattr(runner_module, "evaluate_v0_1_baseline", unexpected)

    result = run_e1_evaluation("mini", output_root, bootstrap_replicates=10)

    assert result["evaluation_status"] == "CALIBRATION_HOLD"
    assert result["threshold"]["lock_status"] == "HOLD"
    assert result["metrics"] is None
    assert result["error_gallery"] == []
    assert result["verdict"] == "HOLD"
    assert verify_e1_results(output_root / "mini") == result
    policy = _MockInferencePolicy.instances[0]
    assert len(policy.calls) == 11
    assert {plan.split for plan in policy.calls} == {DatasetSplit.CALIBRATION}
    assert not (output_root / "mini" / "assets").exists()


@pytest.mark.parametrize(
    ("replicates", "seed"),
    [(0, 1), (100_001, 1), (True, 1), (10, -1), (10, 2**32), (10, False)],
)
def test_bootstrap_arguments_are_bounded(replicates: int, seed: int) -> None:
    with pytest.raises(ValueError):
        _validate_bootstrap_arguments(replicates, seed)
