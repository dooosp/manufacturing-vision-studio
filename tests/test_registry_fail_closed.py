from __future__ import annotations

import hashlib
import io
import random
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import MVSError, UnsafeInputError
from manufacturing_vision_studio.images import ImageIngestor, IngestedImage
from manufacturing_vision_studio.model import DeterministicDifferenceModel, ModelConfig
from manufacturing_vision_studio.registry import CaseRegistry


def make_image(
    settings: Settings,
    *,
    filename: str,
    size: tuple[int, int] = (32, 24),
    color: tuple[int, int, int] = (32, 64, 96),
) -> IngestedImage:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG", compress_level=9)
    return ImageIngestor(settings).ingest_bytes(output.getvalue(), filename=filename)


def make_corner_fixture(
    settings: Settings,
    *,
    filename: str,
    defect: bool,
) -> IngestedImage:
    image = Image.new("RGB", (64, 48))
    rng = random.Random(20260731)
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel(
                (x, y),
                (rng.randrange(20, 220), rng.randrange(20, 220), rng.randrange(20, 220)),
            )
    if defect:
        ImageDraw.Draw(image).rectangle((0, 0, 4, 4), fill=(255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=9)
    return ImageIngestor(settings).ingest_bytes(output.getvalue(), filename=filename)


def blob_snapshot(settings: Settings) -> dict[str, str]:
    return {
        path.relative_to(settings.blob_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in settings.blob_dir.rglob("*")
        if path.is_file()
    }


def create_ready_case(
    registry: CaseRegistry,
    settings: Settings,
    *,
    reference_size: tuple[int, int] = (32, 24),
    inspection_size: tuple[int, int] = (32, 24),
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry.create_case(part_id="PART-001", cad_revision="A", case_id="case-ready")
    reference = registry.add_reference(
        "case-ready",
        make_image(settings, filename="reference.png", size=reference_size),
        expected_case_revision=1,
    )
    inspection = registry.add_inspection(
        "case-ready",
        make_image(
            settings,
            filename="inspection.png",
            size=inspection_size,
            color=(40, 64, 96),
        ),
        expected_case_revision=2,
    )
    return reference, inspection


def assert_failure_is_atomic(
    registry: CaseRegistry,
    settings: Settings,
    case_id: str,
    before_case: dict[str, Any],
    before_blobs: dict[str, str],
) -> None:
    assert registry.get_case_detail(case_id) == before_case
    assert blob_snapshot(settings) == before_blobs


def test_missing_reference_does_not_invoke_model_or_publish_result(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    registry.create_case(part_id="PART-001", cad_revision="A", case_id="case-no-reference")
    before_case = registry.get_case_detail("case-no-reference")
    before_blobs = blob_snapshot(settings)

    with pytest.raises(UnsafeInputError) as exc_info:
        registry.analyze_case("case-no-reference", expected_case_revision=1)

    assert exc_info.value.code == "MISSING_REFERENCE"
    assert_failure_is_atomic(
        registry,
        settings,
        "case-no-reference",
        before_case,
        before_blobs,
    )


def test_dimension_mismatch_does_not_publish_analysis_or_mask(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    create_ready_case(registry, settings, inspection_size=(31, 24))
    before_case = registry.get_case_detail("case-ready")
    before_blobs = blob_snapshot(settings)

    with pytest.raises(UnsafeInputError) as exc_info:
        registry.analyze_case("case-ready", expected_case_revision=3)

    assert exc_info.value.code == "IMAGE_DIMENSION_MISMATCH"
    assert_failure_is_atomic(registry, settings, "case-ready", before_case, before_blobs)


def test_stale_case_revision_publishes_no_analysis_or_artifact(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    create_ready_case(registry, settings)
    before_case = registry.get_case_detail("case-ready")
    before_blobs = blob_snapshot(settings)

    with pytest.raises(MVSError) as exc_info:
        registry.analyze_case("case-ready", expected_case_revision=2)

    assert exc_info.value.code == "REVISION_MISMATCH"
    assert exc_info.value.details == {
        "case_id": "case-ready",
        "expected_case_revision": 2,
        "actual_case_revision": 3,
    }
    assert_failure_is_atomic(registry, settings, "case-ready", before_case, before_blobs)


def test_anomaly_outside_declared_features_is_explicitly_unmapped(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    registry.create_case(part_id="PART-001", cad_revision="A", case_id="case-unmapped")
    registry.add_reference(
        "case-unmapped",
        make_corner_fixture(settings, filename="reference.png", defect=False),
        expected_case_revision=1,
    )
    registry.add_inspection(
        "case-unmapped",
        make_corner_fixture(settings, filename="inspection.png", defect=True),
        expected_case_revision=2,
    )

    analysis = registry.analyze_case("case-unmapped", expected_case_revision=3)[0]
    findings = analysis["completed_output"]["feature_findings"]

    assert analysis["completed_output"]["anomaly_score"] > 0
    assert findings == [
        {
            "mapping_status": "unmapped",
            "feature_id": None,
            "anomaly_score": analysis["completed_output"]["anomaly_score"],
            "mask_fraction": analysis["completed_output"]["anomaly_score"],
            "mapping_confidence": 0.0,
            "mapping_method": "unmapped",
        }
    ]


class UnknownPipelineModel(DeterministicDifferenceModel):
    pipeline_version = "mvs.difference-pipeline/v999"


class UnknownModelVersion(DeterministicDifferenceModel):
    model_version = "999.0.0"


@pytest.mark.parametrize(
    ("model", "expected_code"),
    [
        (UnknownPipelineModel(), "UNKNOWN_PIPELINE_VERSION"),
        (UnknownModelVersion(), "UNKNOWN_MODEL_VERSION"),
    ],
)
def test_unknown_pipeline_or_model_never_falls_back_or_publishes(
    model: DeterministicDifferenceModel,
    expected_code: str,
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    create_ready_case(registry, settings)
    before_case = registry.get_case_detail("case-ready")
    before_blobs = blob_snapshot(settings)

    with pytest.raises(UnsafeInputError) as exc_info:
        registry.analyze_case("case-ready", model=model, expected_case_revision=3)

    assert exc_info.value.code == expected_code
    assert_failure_is_atomic(registry, settings, "case-ready", before_case, before_blobs)


def test_configuration_mismatch_never_invokes_or_publishes(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    create_ready_case(registry, settings)
    before_case = registry.get_case_detail("case-ready")
    before_blobs = blob_snapshot(settings)
    mismatched_model = DeterministicDifferenceModel(ModelConfig(difference_threshold=31))

    with pytest.raises(UnsafeInputError) as exc_info:
        registry.analyze_case(
            "case-ready",
            model=mismatched_model,
            expected_case_revision=3,
        )

    assert exc_info.value.code == "HASH_MISMATCH"
    assert_failure_is_atomic(registry, settings, "case-ready", before_case, before_blobs)


def test_rejected_image_for_missing_case_leaves_no_orphan_blobs(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    image = make_image(settings, filename="orphan.png")
    before_blobs = blob_snapshot(settings)

    with pytest.raises(MVSError):
        registry.add_inspection(
            "case-does-not-exist",
            image,
            expected_case_revision=1,
        )

    assert blob_snapshot(settings) == before_blobs
    assert registry.list_cases() == []


def test_case_image_limit_failure_leaves_no_orphan_blobs_or_revision_bump(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data", max_images_per_case=1)
    registry = CaseRegistry(settings)
    registry.create_case(part_id="PART-001", cad_revision="A", case_id="case-bounded")
    registry.add_reference(
        "case-bounded",
        make_image(settings, filename="reference.png", color=(10, 20, 30)),
        expected_case_revision=1,
    )
    registry.add_inspection(
        "case-bounded",
        make_image(settings, filename="within-limit.png", color=(40, 50, 60)),
        expected_case_revision=2,
    )
    before_case = registry.get_case_detail("case-bounded")
    before_blobs = blob_snapshot(settings)

    with pytest.raises(UnsafeInputError) as exc_info:
        registry.add_inspection(
            "case-bounded",
            make_image(settings, filename="over-limit.png", color=(200, 100, 50)),
            expected_case_revision=3,
        )

    assert exc_info.value.code == "INPUT_TOO_LARGE"
    assert_failure_is_atomic(registry, settings, "case-bounded", before_case, before_blobs)
