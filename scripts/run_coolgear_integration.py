#!/usr/bin/env python3
"""Reproduce the frozen, descriptive Coolgear synthetic evaluation (not E1)."""

from __future__ import annotations

import argparse
import io
import json
import platform
import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from manufacturing_vision_studio.adapters import FreeCADExportAdapter
from manufacturing_vision_studio.cad_binding import validate_cad_binding
from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import MVSError
from manufacturing_vision_studio.evidence import EvidenceService
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.model import DeterministicDifferenceModel, ModelConfig
from manufacturing_vision_studio.registry import CLASSIFICATION_THRESHOLD, CaseRegistry

ROOT = Path(__file__).resolve().parents[1]


def png_bytes(array):
    return encode_png(Image.fromarray(array), mode="RGB" if array.ndim == 3 else "L")


def validate_protocol(protocol):
    if protocol["schema_version"] != "coolgear-integration-protocol/v1":
        raise ValueError("Unknown evaluation protocol")
    if protocol["classification_threshold"] != CLASSIFICATION_THRESHOLD:
        raise ValueError("Frozen classification threshold must not be tuned")
    if (
        protocol["model_config"] != asdict(ModelConfig())
        or protocol["configuration_sha256"] != ModelConfig().config_hash
    ):
        raise ValueError("Frozen model configuration differs")
    if protocol["repeat_count"] != 2:
        raise ValueError("Two deterministic executions are required")
    cases = protocol["cases"]
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    groups = {
        split: {c["group_id"] for c in cases if c["split"] == split}
        for split in ["smoke", "evaluation"]
    }
    if groups["smoke"] & groups["evaluation"]:
        raise ValueError("A group crosses smoke/evaluation splits")
    for case in cases:
        if case["split"] not in groups or case["expected_cad_revision"] != "R1":
            raise ValueError("Defect generation must retain expected R1")
        if not isinstance(case["expected_anomaly"], bool):
            raise ValueError("Truth classification must be explicit")


def make_sample(reference, holes, case):
    """Generator-only truth; never receives predictions or model thresholds."""
    sample = reference.copy()
    height, width = reference.shape[:2]
    yy, xx = np.ogrid[:height, :width]
    params = case["parameters"]

    def circle(feature, dx=0, dy=0, extra=0):
        hole = holes[feature]
        x, y = hole["center_mm"]
        u, v, r = 10 * (x + 5) + dx, 10 * (79 - y) + dy, 10 * hole["radius_mm"] + extra
        return (xx + 0.5 - u) ** 2 + (yy + 0.5 - v) ** 2 <= r * r

    operation = case["operation"]
    outside = 0
    if operation == "normal":
        pass
    elif operation == "fill_holes":
        for feature in params["features"]:
            sample[circle(feature)] = 180
    elif operation == "move_hole":
        feature = params["feature"]
        sample[circle(feature)] = 180
        sample[circle(feature, params["dx_px"], params["dy_px"])] = 0
    elif operation == "enlarge_hole":
        sample[circle(params["feature"], extra=params["extra_radius_px"])] = 0
    elif operation == "patch":
        x0, y0, x1, y1 = params["box_px"]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("Patch outside image")
        sample[y0:y1, x0:x1] = params["value"]
    elif operation == "noise":
        rng = np.random.default_rng(params["seed"])
        amplitude = params["amplitude"]
        if params["distribution"] == "uniform":
            noise = rng.integers(-amplitude, amplitude + 1, reference.shape)
        else:
            noise = np.clip(
                np.rint(rng.normal(0, amplitude, reference.shape)), -3 * amplitude, 3 * amplitude
            )
        sample = np.clip(reference.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    elif operation == "translate":
        dx, dy = params["dx_px"], params["dy_px"]
        sample[:] = 0
        x0, x1, y0, y1 = max(0, -dx), min(width, width - dx), max(0, -dy), min(height, height - dy)
        sample[y0 + dy : y1 + dy, x0 + dx : x1 + dx] = reference[y0:y1, x0:x1]
        outside = width * height - (x1 - x0) * (y1 - y0)
    else:
        raise ValueError("Unsupported frozen generator operation")
    truth = (
        np.any(sample != reference, axis=2)
        if case["expected_anomaly"]
        else np.zeros((height, width), dtype=bool)
    )
    return (
        sample,
        truth,
        {
            "generator_operation": operation,
            "parameters": params,
            "expected_cad_revision": "R1",
            "defect_cad_revision": None,
            "defect_cad_sha256": None,
            "generation_kind": "raster_mutation",
            "out_of_frame_pixels": outside,
            "truth_frame": "reference_pixels",
            "statistical_independence": False,
        },
    )


def inspect_sample(model, reference, inspection, binding):
    """Inference boundary: exactly two images and preselected reference regions."""
    regions = binding.regions()
    result = model.inspect(reference, inspection, feature_regions=regions)
    repeated = model.inspect(reference, inspection, feature_regions=regions)
    equivalent = canonical_json_bytes(result.as_record()) == canonical_json_bytes(
        repeated.as_record()
    )
    if (
        not equivalent
        or result.mask_bytes != repeated.mask_bytes
        or result.registered_bytes != repeated.registered_bytes
    ):
        raise ValueError("MODEL_ABSTAINED: repeat mismatch")
    mask = np.asarray(Image.open(io.BytesIO(result.mask_bytes))) > 0
    union = np.zeros(mask.shape, dtype=bool)
    height, width = mask.shape
    for x0, y0, x1, y1 in regions.values():
        union[round(y0 * height) : round(y1 * height), round(x0 * width) : round(x1 * width)] = True
    return {
        "prediction": "anomaly" if result.anomaly_score >= CLASSIFICATION_THRESHOLD else "normal",
        "anomaly_score": result.anomaly_score,
        "threshold": CLASSIFICATION_THRESHOLD,
        "mapped_feature_ids": [s.feature_id for s in result.feature_scores if s.anomaly_pixels > 0],
        "unmapped_pixels": int(np.count_nonzero(mask & ~union)),
        "anomaly_pixels": result.anomaly_pixels,
        "registration": asdict(result.registration),
        "repeat_equivalent": True,
        "model_record": result.as_record(),
        "mask_bytes": result.mask_bytes,
        "registered_bytes": result.registered_bytes,
    }


def summarize(records, split):
    rows = [r for r in records if r["split"] == split]
    completed = [r for r in rows if r["status"] == "completed"]
    confusion = dict(true_positive=0, true_negative=0, false_positive=0, false_negative=0)
    for row in completed:
        positive, predicted = row["expected_anomaly"], row["prediction"] == "anomaly"
        key = (
            ("true_positive" if predicted else "false_negative")
            if positive
            else ("false_positive" if predicted else "true_negative")
        )
        confusion[key] += 1
    in_scope = [r for r in completed if r["expected_anomaly"] and r["expected_feature_ids"]]
    correct = sum(set(r["expected_feature_ids"]) == set(r["mapped_feature_ids"]) for r in in_scope)
    positive_count = confusion["true_positive"] + confusion["false_negative"]
    negative_count = confusion["true_negative"] + confusion["false_positive"]
    return {
        "sample_count": len(rows),
        "group_count": len({r["group_id"] for r in rows}),
        "executed_count": len(completed),
        "execution_failures": len(rows) - len(completed),
        "model_abstentions": sum("MODEL_ABSTAINED" in r.get("error", "") for r in rows),
        "human_reviewed_count": 0,
        "unreviewed_count": len(rows),
        "confusion": confusion,
        "evaluated_positive_count": positive_count,
        "evaluated_negative_count": negative_count,
        "recall": confusion["true_positive"] / positive_count if positive_count else None,
        "false_positive_rate": confusion["false_positive"] / negative_count
        if negative_count
        else None,
        "feature_mapping": {
            "in_scope_positive_cases": len(in_scope),
            "correct": correct,
            "incorrect_or_missing": len(in_scope) - correct,
            "outside_scope_positive_cases": sum(
                r["expected_anomaly"] and not r["expected_feature_ids"] for r in completed
            ),
            "unmapped_detected_cases": sum(r["unmapped_pixels"] > 0 for r in completed),
        },
        "statistical_independence": False,
        "performance_scope": "fixed correlated synthetic cases only",
    }


def integrity_probes(source_root, selected, out_dir, r2_root=None, r2_selection=None):
    settings = Settings(data_dir=out_dir / "revision-cases")
    registry = CaseRegistry(settings)
    sources = [selected]
    r2_binding = None
    if r2_root is not None:
        raw = FreeCADExportAdapter().validate(
            r2_root, expected_part_id="USB-REF-ADAPTER", expected_cad_revision="R2"
        )
        r2_binding = validate_cad_binding(
            raw.manifest_bytes, raw.artifacts, expected_source=r2_selection
        )
        sources.append(r2_selection)
    (settings.data_dir / "trusted-cad-sources.json").write_bytes(
        canonical_json_bytes({"schema_version": "mvs-cad-source-selection/v1", "sources": sources})
    )
    adapter = FreeCADExportAdapter(settings)
    results = []
    for name, part, revision, root, expected_code in [
        ("part_refusal", "WRONG-PART", "R1", source_root, "PART_ID_MISMATCH"),
        ("revision_refusal", "USB-REF-ADAPTER", "R2", source_root, "REVISION_MISMATCH"),
    ] + (
        [("r2_into_r1_refusal", "USB-REF-ADAPTER", "R1", r2_root, "REVISION_MISMATCH")]
        if r2_root
        else []
    ):
        registry.create_case(part_id=part, cad_revision=revision, case_id=name)
        before = registry.get_case_detail(name)
        try:
            adapter.import_reference(registry, name, root, expected_case_revision=1)
        except MVSError as exc:
            if exc.code != expected_code or registry.get_case_detail(name) != before:
                raise ValueError("Refusal code or atomicity did not match") from exc
            results.append(
                {
                    "probe": name,
                    "expected_code": expected_code,
                    "observed_code": exc.code,
                    "rejected": True,
                    "case_unchanged": True,
                }
            )
        else:
            raise AssertionError("Identity refusal failed")
    tampered = out_dir / "tampered-copy"
    tampered.mkdir()
    for name in [
        "reference.png",
        "feature-map.json",
        "cad-metadata.json",
        "freecad-export-adapter-manifest.json",
    ]:
        shutil.copyfile(source_root / name, tampered / name)
    with (tampered / "reference.png").open("ab") as handle:
        handle.write(b"tamper")
    try:
        adapter.validate(tampered)
    except MVSError as exc:
        if exc.code != "HASH_MISMATCH":
            raise ValueError("Tamper refusal used an unexpected code") from exc
        results.append(
            {"probe": "byte_tamper_refusal", "observed_code": exc.code, "rejected": True}
        )
    else:
        raise AssertionError("Tamper refusal failed")
    revision_demo = {"status": "not_run"}
    if r2_binding is not None:
        registry.create_case(
            part_id="USB-REF-ADAPTER", cad_revision="R2", case_id="r2-change-demo", locale="ko"
        )
        adapter.import_reference(registry, "r2-change-demo", r2_root, expected_case_revision=1)
        registry.add_inspection(
            "r2-change-demo",
            ImageIngestor(settings).ingest_bytes(
                (r2_root / "reference.png").read_bytes(), filename="r2-reference-self-check.png"
            ),
            expected_case_revision=2,
        )
        analysis = registry.analyze_case("r2-change-demo", expected_case_revision=3)[0]
        registry.add_disposition(
            "r2-change-demo",
            analysis_id=analysis["analysis_id"],
            decision="needs_review",
            reviewer_id="synthetic-revision-script",
            rationale=(
                "Change-control demonstration, not an approved design. "
                "R1 mounting requirement still requires review."
            ),
            reason_codes=["insufficient_evidence"],
            expected_case_revision=4,
        )
        bundle = EvidenceService(registry, settings).export_case(
            "r2-change-demo", expected_case_revision=5
        )
        revision_demo = {
            "status": "scripted_change_demo",
            "cad_revision": "R2",
            "binding": r2_binding.case_binding(),
            "reference_self_classification": analysis["completed_output"][
                "automated_classification"
            ],
            "human_approval": False,
            "manufacturing_release": False,
            "bundle": str(bundle.path.relative_to(out_dir)),
            "limitations": [
                "Visual self-consistency does not approve the R2 design "
                "or replace the R1 mounting-rule comparison."
            ],
        }
    return {"integrity_probes": results, "revision_demo": revision_demo}


def run(protocol_path, reference_root, out_dir, r2_root=None, r2_selection_path=None):
    started_at = datetime.now(UTC).isoformat()
    commit_at_start = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty_at_start = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    protocol_bytes = protocol_path.read_bytes()
    protocol = json.loads(protocol_bytes)
    validate_protocol(protocol)
    if (r2_root is None) != (r2_selection_path is None):
        raise ValueError(
            "R2 export and independent source-selection file must be supplied together"
        )
    out_dir = out_dir.resolve()
    if not out_dir.is_relative_to(ROOT / "output"):
        raise ValueError("Evaluation output must stay under this repository output/")
    validated = FreeCADExportAdapter().validate(
        reference_root, expected_part_id="USB-REF-ADAPTER", expected_cad_revision="R1"
    )
    binding = validate_cad_binding(
        validated.manifest_bytes, validated.artifacts, expected_source=protocol["selected_source"]
    )
    if binding.source_kind != "native_freecad":
        raise ValueError("This frozen run requires its selected native producer output")
    metadata = json.loads(validated.artifacts["cad-metadata.json"])
    holes = {h["feature_id"]: h for h in metadata["holes"]}
    reference = ImageIngestor().ingest_bytes(
        validated.artifacts["reference.png"], filename="reference.png"
    )
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "inputs").mkdir()
    (out_dir / "truth").mkdir()
    (out_dir / "predictions").mkdir()
    (out_dir / "protocol.json").write_bytes(protocol_bytes)
    (out_dir / "reference.png").write_bytes(validated.artifacts["reference.png"])
    records = []
    seen_images = {}
    model = DeterministicDifferenceModel()
    for case in protocol["cases"]:
        identifier = case["case_id"]
        row = {
            key: case[key]
            for key in [
                "case_id",
                "split",
                "group_id",
                "expected_anomaly",
                "expected_feature_ids",
                "expected_cad_revision",
            ]
        }
        try:
            sample, truth, generation = make_sample(reference.as_array(), holes, case)
            image_bytes = png_bytes(sample)
            digest = sha256_bytes(image_bytes)
            if digest in seen_images and seen_images[digest] != case["split"]:
                raise ValueError("Duplicate image crosses smoke/evaluation splits")
            seen_images[digest] = case["split"]
            (out_dir / "inputs" / f"{identifier}.png").write_bytes(image_bytes)
            truth_bytes = png_bytes(np.where(truth, 255, 0).astype(np.uint8))
            (out_dir / "truth" / f"{identifier}.png").write_bytes(truth_bytes)
            inspection = ImageIngestor().ingest_bytes(image_bytes, filename="sample.png")
            observed = inspect_sample(model, reference, inspection, binding)
            (out_dir / "predictions" / f"{identifier}-mask.png").write_bytes(
                observed.pop("mask_bytes")
            )
            (out_dir / "predictions" / f"{identifier}-registered.png").write_bytes(
                observed.pop("registered_bytes")
            )
            row.update(
                observed,
                status="completed",
                image_sha256=digest,
                truth_mask_sha256=sha256_bytes(truth_bytes),
                truth_positive_pixels=int(np.count_nonzero(truth)),
                generation_provenance=generation,
            )
        except Exception as exc:
            row.update(status="execution_failed", error=str(exc))
        records.append(row)
    r2_selection = json.loads(r2_selection_path.read_bytes()) if r2_selection_path else None
    controls = integrity_probes(
        reference_root, protocol["selected_source"], out_dir, r2_root, r2_selection
    )
    report = {
        "schema_version": "coolgear-integration-result/v1",
        "dataset_version": protocol["dataset_version"],
        "generated_at": datetime.now(UTC).isoformat(),
        "producer_commit": commit_at_start,
        "started_at": started_at,
        "dirty_at_start": dirty_at_start,
        "protocol_sha256": sha256_bytes(protocol_bytes),
        "source_binding": binding.analysis_binding(),
        "generator_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "model_source_sha256": sha256_bytes(
            (ROOT / "src/manufacturing_vision_studio/model.py").read_bytes()
        ),
        "configuration_sha256": model.config.config_hash,
        "classification_threshold": CLASSIFICATION_THRESHOLD,
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "smoke": summarize(records, "smoke"),
        "evaluation": summarize(records, "evaluation"),
        "cases": records,
        **controls,
        "physical_test": "not_tested",
        "manufacturing_release": False,
        "installed_load_rating_N": None,
        "fastening_torque_Nm": None,
        "limitations": [
            protocol["performance_scope"],
            protocol["grouping_rule"],
            "Case labels/masks/defect parameters are evaluator-only; "
            "model gets two images and pinned reference ROIs.",
            "Integrity refusal outcomes are not detection accuracy.",
            "No human approval is implied by scripted records.",
            "Symmetric geometry cannot establish 180-degree orientation or handedness from pixels.",
        ],
    }
    (out_dir / "results.json").write_bytes(canonical_json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument(
        "--reference-export",
        type=Path,
        default=Path("../freecad-automation/output/mvs-reference/coolgear-r1"),
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--r2-export", type=Path)
    parser.add_argument("--r2-selection", type=Path)
    args = parser.parse_args()
    report = run(
        args.protocol, args.reference_export, args.out_dir, args.r2_export, args.r2_selection
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in [
                    "protocol_sha256",
                    "smoke",
                    "evaluation",
                    "integrity_probes",
                    "revision_demo",
                ]
            },
            indent=2,
        )
    )
    raise SystemExit(
        1
        if report["smoke"]["execution_failures"] + report["evaluation"]["execution_failures"]
        else 0
    )
