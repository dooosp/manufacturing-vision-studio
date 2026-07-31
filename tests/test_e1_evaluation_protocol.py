from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas" / "e1-evaluation-protocol.v1.json"
CONFIG_PATH = ROOT / "configs" / "evaluation" / "e1-v1.json"


def load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def walk_json(value: Any, pointer: str = "") -> list[tuple[str, Any]]:
    walked = [(pointer, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            walked.extend(walk_json(child, f"{pointer}/{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walked.extend(walk_json(child, f"{pointer}/{index}"))
    return walked


def validator() -> Draft202012Validator:
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_e1_schema_is_strict_and_local_ref_only() -> None:
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/e1-evaluation-protocol.v1.json")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": "1.0.0"}

    for pointer, value in walk_json(schema):
        if isinstance(value, dict) and value.get("type") == "object":
            assert value.get("additionalProperties") is False, f"unbounded object at {pointer}"
        if isinstance(value, dict) and "$ref" in value:
            assert value["$ref"].startswith("#/"), f"external ref at {pointer}"


def test_frozen_config_validates_and_rejects_contract_drift() -> None:
    config = load_json(CONFIG_PATH)
    contract = validator()
    contract.validate(config)

    mutations: list[dict[str, Any]] = []
    unknown_root = copy.deepcopy(config)
    unknown_root["unregistered"] = True
    mutations.append(unknown_root)

    unknown_nested = copy.deepcopy(config)
    unknown_nested["baseline"]["unknown"] = True
    mutations.append(unknown_nested)

    bad_digest = copy.deepcopy(config)
    bad_digest["baseline"]["bundle_sha256"] = "not-a-digest"
    mutations.append(bad_digest)

    bad_profile = copy.deepcopy(config)
    bad_profile["dataset_profiles"]["mini"]["profile"] = "quick"
    mutations.append(bad_profile)

    missing_identity = copy.deepcopy(config)
    del missing_identity["protocol_id"]
    mutations.append(missing_identity)

    assert all(not contract.is_valid(mutated) for mutated in mutations)


def test_pretest_amendment_and_evaluation_pipeline_are_hash_bound() -> None:
    config = load_json(CONFIG_PATH)

    assert config["protocol_version"] == "1.1.0"
    assert config["protocol_history"] == [
        {
            "protocol_version": "1.0.0",
            "protocol_sha256": (
                "ddb17d07100bddf81b7a239220eac3a711976120c35d1f6ddd426be4dd3ce787"
            ),
            "outcome": "CALIBRATION_HOLD_WITHOUT_TEST_EXECUTION",
            "retention": "preserved_in_git_history",
        },
        {
            "protocol_version": "1.1.0",
            "change_reason": (
                "development-derived_geometry_normalization_and_localized_scoring"
            ),
            "threshold_changed": False,
            "test_cases_observed_before_freeze": False,
        },
    ]
    pipeline = config["evaluation_pipeline"]
    assert pipeline["pipeline_id"] == "e1-normalized-local-difference"
    assert pipeline["model_artifact_sha256"] == (
        "51f25d98c22a812996e8f2ce6207151a17ea393acf7cc30af11092477cb4557d"
    )
    assert pipeline["configuration_sha256"] == (
        "7ad7ad03e827973e2ece5c5a7c36c540c1327a60a8e253a1f55677ae4ddb058c"
    )
    normalization = pipeline["configuration"]["normalization"]
    assert normalization["prediction_dependency"] == "forbidden"
    assert normalization["nuisance_parameter_dependency"] == "forbidden"
    assert pipeline["configuration"]["scoring"] == {
        "algorithm": "max_global_and_coherent_local_density_v1",
        "local_window_size_px": 64,
        "minimum_connected_component_pixels": 32,
        "connectivity": 8,
    }


def test_exact_full_and_mini_composition_is_frozen() -> None:
    profiles = load_json(CONFIG_PATH)["dataset_profiles"]

    assert profiles["full"] == {
        "profile": "full",
        "case_count": 480,
        "inference_case_count": 456,
        "trust_case_count": 24,
        "group_counts": {
            "clean": 96,
            "nuisance": 120,
            "defect": 240,
            "trust_boundary": 24,
        },
    }
    assert profiles["mini"]["case_count"] == 48
    assert profiles["mini"]["inference_case_count"] == 44
    assert profiles["mini"]["trust_case_count"] == 4
    assert profiles["mini"]["group_counts"] == {
        "clean": 8,
        "nuisance": 12,
        "defect": 24,
        "trust_boundary": 4,
    }
    assert profiles["mini"]["subset_of"] == "full"
    assert profiles["mini_selection"]["rule"] == "frozen_exact_membership_v1"
    assert len(profiles["mini_selection"]["exact_case_ids"]) == 48
    assert len(set(profiles["mini_selection"]["exact_case_ids"])) == 48

    split_expected = {
        "development": (120, {"clean": 24, "nuisance": 30, "defect": 60, "trust_boundary": 6}),
        "calibration": (120, {"clean": 24, "nuisance": 30, "defect": 60, "trust_boundary": 6}),
        "test": (240, {"clean": 48, "nuisance": 60, "defect": 120, "trust_boundary": 12}),
    }
    for split, (total, groups) in split_expected.items():
        actual = profiles["split_composition"][split]
        assert actual["case_count"] == total
        assert actual["group_counts"] == groups
        assert sum(groups.values()) == total

    mini_splits = profiles["mini_selection"]["split_counts"]
    assert {name: split["case_count"] for name, split in mini_splits.items()} == {
        "development": 12,
        "calibration": 12,
        "test": 24,
    }
    assert sum(split["case_count"] for split in mini_splits.values()) == 48


def test_taxonomy_counts_and_ranges_are_complete() -> None:
    taxonomies = load_json(CONFIG_PATH)["taxonomies"]

    defects = taxonomies["defects"]
    assert {defect["type"] for defect in defects} == {
        "scratch",
        "stain",
        "edge_chip",
        "burr",
        "blocked_hole",
        "hole_geometry_deviation",
    }
    assert sum(defect["full_case_count"] for defect in defects) == 240
    assert sum(defect["mini_case_count"] for defect in defects) == 24
    for defect in defects:
        assert sum(defect["split_counts"].values()) == defect["full_case_count"]
        for parameter in defect["severity_parameters"]:
            assert parameter["LOW"] <= parameter["MEDIUM"] <= parameter["HIGH"]

    severities = taxonomies["severities"]
    assert [severity["severity"] for severity in severities] == ["LOW", "MEDIUM", "HIGH"]
    assert sum(severity["full_case_count"] for severity in severities) == 240
    assert sum(severity["mini_case_count"] for severity in severities) == 24
    assert [severity["primary_release_gate"] for severity in severities] == [False, True, True]

    nuisances = taxonomies["nuisances"]
    assert taxonomies["nuisance_case_cardinality"] == {
        "primary_nuisance_per_case": 1,
        "combined_nuisances_generated": False,
    }
    assert [nuisance["type"] for nuisance in nuisances] == [
        "translation",
        "rotation",
        "scale",
        "exposure",
        "directional_shading",
        "gaussian_blur",
        "sensor_noise",
        "jpeg_compression",
        "background_fixture",
    ]
    assert sum(nuisance["full_case_count"] for nuisance in nuisances) == 120
    assert sum(nuisance["mini_case_count"] for nuisance in nuisances) == 12
    assert {
        split: sum(nuisance["split_counts"][split] for nuisance in nuisances)
        for split in ("development", "calibration", "test")
    } == {"development": 30, "calibration": 30, "test": 60}
    for nuisance in nuisances:
        assert sum(nuisance["split_counts"].values()) == nuisance["full_case_count"]
        for parameter in nuisance["parameters"]:
            supported = parameter["supported_normal_range"]
            transition = parameter["excluded_transition_range"]
            abstain = parameter["unsupported_or_abstain_range"]
            assert supported["minimum"] <= supported["maximum"] < transition["minimum"]
            assert transition["minimum"] <= transition["maximum"] < abstain["minimum"]
            assert abstain["minimum"] <= abstain["maximum"]


def test_seed_families_and_seed_ranges_do_not_overlap_across_splits() -> None:
    seed_blocks = load_json(CONFIG_PATH)["generator"]["seed_blocks"]
    families: set[str] = set()
    allocated: set[int] = set()

    for split, groups in seed_blocks.items():
        for group, block in groups.items():
            assert block["seed_family"] not in families, (split, group)
            families.add(block["seed_family"])
            seeds = set(range(block["start"], block["start"] + block["count"]))
            assert allocated.isdisjoint(seeds), (split, group)
            allocated.update(seeds)

    assert len(allocated) == 480

    split_rules = load_json(CONFIG_PATH)["split_rules"]
    assert split_rules["leak_keys"] == [
        "recipe_id",
        "seed_family",
        "reference_sha256",
        "inspection_sha256",
        "case_binding_sha256",
    ]
    assert (
        split_rules["raw_empty_mask_overlap_policy"]
        == "allowed_only_for_declared_empty_clean_and_nuisance_truth"
    )


def test_trust_boundary_and_oracle_are_fail_closed() -> None:
    config = load_json(CONFIG_PATH)
    trust_cases = config["taxonomies"]["trust_boundary_cases"]

    assert len(trust_cases) == 24
    assert len({case["scenario_id"] for case in trust_cases}) == 24
    assert Counter(case["split"] for case in trust_cases) == {
        "development": 6,
        "calibration": 6,
        "test": 12,
    }
    assert sum(case["included_in_mini"] for case in trust_cases) == 4
    assert all(case["expected_outcome"] == "ABSTAIN" for case in trust_cases)
    assert all(case["publication_allowed"] is False for case in trust_cases)

    oracle = config["oracle_contract"]
    assert oracle["owner"] == "generator"
    assert oracle["prediction_dependency"] == "forbidden"
    assert oracle["publication_on_failure"] is False
    assert set(oracle["required_case_hash_fields"]) == {
        "reference_sha256",
        "inspection_sha256",
        "authoritative_mask_sha256",
        "generator_configuration_sha256",
    }


def test_acceptance_gates_are_exactly_preregistered() -> None:
    config = load_json(CONFIG_PATH)
    gates = {gate["gate_id"]: gate for gate in config["acceptance_gates"]}

    assert {gate_id: gate["threshold"] for gate_id, gate in gates.items()} == {
        "medium_high_defect_recall": 0.9,
        "nuisance_only_false_positive_rate": 0.05,
        "positive_case_median_dice": 0.7,
        "affected_feature_mapping_accuracy": 0.95,
        "revision_mismatch_publication_count": 0,
        "corrupted_evidence_publication_count": 0,
        "bundle_verify_reimport_rate": 1.0,
        "dataset_split_hash_overlap": 0,
        "same_seed_manifest_equivalence": True,
        "v0_1_regression": True,
    }
    assert config["threshold_selection"] == {
        "locked_image_threshold": 0.0025,
        "threshold_source_split": "calibration",
        "selection_method": "single_pre_registered_candidate_confirmed_on_calibration",
        "selection_candidates": [0.0025],
        "pixel_difference_threshold": 32,
        "registration_max_shift_px": 12,
        "registration_sample_stride": 4,
        "feature_mapping_min_mask_pixels": 1,
        "lock_before_test": True,
        "failure_rule": "calibration_failure_is_hold_not_post_hoc_threshold_search",
        "calibration_confirmation": {
            "required": True,
            "gate_ids": [
                "medium_high_defect_recall",
                "nuisance_only_false_positive_rate",
                "positive_case_median_dice",
                "affected_feature_mapping_accuracy",
            ],
            "thresholds": {
                "medium_high_defect_recall": 0.9,
                "nuisance_only_false_positive_rate": 0.05,
                "positive_case_median_dice": 0.7,
                "affected_feature_mapping_accuracy": 0.95,
            },
            "failure_action": "HOLD_WITHOUT_TEST_EXECUTION",
        },
    }


def test_implementation_sensitive_contracts_are_frozen() -> None:
    config = load_json(CONFIG_PATH)
    universe = config["universe"]
    regions = universe["feature_regions_by_view"]
    assert set(regions) == {"front", "oblique_left", "oblique_right"}
    for view_regions in regions.values():
        assert set(view_regions) == set(universe["feature_ids"])
        for x0, y0, x1, y1 in view_regions.values():
            assert 0 <= x0 < x1 <= 1
            assert 0 <= y0 < y1 <= 1

    projection = config["generator"]["configuration_projection"]
    assert projection["canonicalization"] == "mvs-canonical-json/v1"
    assert "universe" in projection["included_paths"]
    assert "metrics" in projection["excluded_paths"]

    uncertainty = config["metrics"]["uncertainty"]
    assert uncertainty["bootstrap_strata"] == {
        "ranking_metrics": ["expected_outcome"],
        "median_dice": ["defect_type"],
    }
    eligible = config["repeatability_contract"]["bundle_eligible_artifacts"]
    assert eligible == [
        {
            "artifact_id": "v0.1.0-golden-bundle",
            "kind": "published_release_bundle",
            "sha256": "1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7",
        }
    ]
    assert config["data_policy"]["error_gallery_max_cases"] == 12
