"""Executable v0.1.0 regression and published-bundle gates for E1."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.e1.protocol import E1Protocol
from manufacturing_vision_studio.evidence import EvidenceService
from manufacturing_vision_studio.registry import CaseRegistry
from manufacturing_vision_studio.schema_validation import validate_document

PROJECT_ROOT = Path(__file__).resolve().parents[3]
V010_BUNDLE = PROJECT_ROOT / "docs" / "releases" / "v0.1.0" / "evidence-bundle.zip"
V010_RESULT = PROJECT_ROOT / "docs" / "evaluation" / "results" / "v0.1.0-synthetic.json"


@dataclass(frozen=True, slots=True)
class BaselineGateResult:
    """Evidence for the bundle denominator and v0.1 regression gate."""

    bundle_attempts: int
    bundle_successes: int
    v0_1_regression: bool
    checks: tuple[dict[str, Any], ...]

    def as_record(self) -> dict[str, Any]:
        return {
            "bundle_attempts": self.bundle_attempts,
            "bundle_successes": self.bundle_successes,
            "bundle_verify_reimport_rate": self.bundle_successes / self.bundle_attempts,
            "v0_1_regression": self.v0_1_regression,
            "checks": list(self.checks),
        }


def evaluate_v0_1_baseline(protocol: E1Protocol) -> BaselineGateResult:
    """Verify, clean-import, re-export, and validate the immutable baseline."""

    baseline = protocol.section("baseline")
    expected_bundle_sha = cast(str, baseline["bundle_sha256"])
    checks: list[dict[str, Any]] = []
    bundle_ok = False
    try:
        bundle_bytes = V010_BUNDLE.read_bytes()
        observed_bundle_sha = sha256_bytes(bundle_bytes)
        hash_ok = observed_bundle_sha == expected_bundle_sha
        checks.append(
            {
                "check_id": "published_bundle_sha256",
                "passed": hash_ok,
                "expected": expected_bundle_sha,
                "observed": observed_bundle_sha,
            }
        )
        with tempfile.TemporaryDirectory(prefix="mvs-e1-v010-") as temporary:
            settings = Settings(data_dir=Path(temporary) / "registry")
            registry = CaseRegistry(settings)
            service = EvidenceService(registry, settings)
            verified = service.verify_bundle(
                bundle_bytes,
                expected_part_id="MVS-DEMO-001",
                expected_cad_revision="rev-A",
            )
            imported = service.import_bundle(bundle_bytes)
            reexported = service.export_case(
                imported.case_id,
                expected_case_revision=imported.case_revision,
            )
            roundtrip_ok = (
                verified.valid
                and verified.bundle_sha256 == expected_bundle_sha
                and reexported.path.read_bytes() == bundle_bytes
                and reexported.bundle_sha256 == expected_bundle_sha
            )
            checks.append(
                {
                    "check_id": "strict_verify_clean_reimport_reexport",
                    "passed": roundtrip_ok,
                    "case_id": imported.case_id,
                    "payload_sha256": imported.payload_sha256,
                }
            )
            bundle_ok = hash_ok and roundtrip_ok
    except Exception as exc:  # a gate failure is evidence, not a partial publication
        checks.append(
            {
                "check_id": "strict_verify_clean_reimport_reexport",
                "passed": False,
                "error_type": type(exc).__name__,
            }
        )

    result_ok = False
    try:
        result_document = json.loads(V010_RESULT.read_bytes())
        if not isinstance(result_document, dict):
            raise ValueError("v0.1 result root must be an object")
        validate_document(result_document, "evaluation-report")
        metrics = cast(dict[str, Any], result_document["classification_metrics"])
        dataset = cast(dict[str, Any], result_document["dataset"])
        result_ok = (
            result_document["verdict"] == "pass"
            and dataset["sample_count"] == 2
            and dataset["positive_count"] == 1
            and dataset["negative_count"] == 1
            and metrics["true_positive"] == 1
            and metrics["true_negative"] == 1
            and metrics["false_positive"] == 0
            and metrics["false_negative"] == 0
            and result_document["configuration_sha256"] == baseline["configuration_sha256"]
        )
        checks.append(
            {
                "check_id": "v0_1_schema_and_golden_counts",
                "passed": result_ok,
                "sample_count": dataset["sample_count"],
                "confusion": {
                    name: metrics[name]
                    for name in (
                        "true_positive",
                        "true_negative",
                        "false_positive",
                        "false_negative",
                    )
                },
            }
        )
    except Exception as exc:
        checks.append(
            {
                "check_id": "v0_1_schema_and_golden_counts",
                "passed": False,
                "error_type": type(exc).__name__,
            }
        )

    return BaselineGateResult(
        bundle_attempts=1,
        bundle_successes=int(bundle_ok),
        v0_1_regression=bundle_ok and result_ok,
        checks=tuple(checks),
    )
