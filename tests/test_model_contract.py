from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import UnsafeInputError
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.model import DeterministicDifferenceModel, ModelConfig


def image_bytes(
    *,
    size: tuple[int, int] = (32, 24),
    defect: tuple[int, int, int, int] | None = None,
) -> bytes:
    image = Image.new("RGB", size, (32, 32, 32))
    if defect is not None:
        ImageDraw.Draw(image).rectangle(defect, fill=(255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def test_dimension_mismatch_is_rejected_without_implicit_normalization(tmp_path: Path) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path))
    reference = ingestor.ingest_bytes(image_bytes(size=(32, 24)), filename="reference.png")
    inspection = ingestor.ingest_bytes(image_bytes(size=(31, 24)), filename="inspection.png")

    with pytest.raises(UnsafeInputError) as exc_info:
        DeterministicDifferenceModel(ModelConfig(registration_max_shift=0)).inspect(
            reference,
            inspection,
        )

    assert exc_info.value.code == "IMAGE_DIMENSION_MISMATCH"
    assert exc_info.value.details == {"reference": [32, 24], "inspection": [31, 24]}


def test_repeated_inspection_is_byte_and_metric_deterministic(tmp_path: Path) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path))
    reference = ingestor.ingest_bytes(image_bytes(), filename="reference.png")
    inspection = ingestor.ingest_bytes(
        image_bytes(defect=(8, 6, 15, 11)),
        filename="inspection.png",
    )
    model = DeterministicDifferenceModel(
        ModelConfig(
            registration_max_shift=0,
            difference_threshold=32,
            registration_sample_stride=1,
        )
    )
    regions = {
        "hole3": (0.20, 0.20, 0.55, 0.60),
        "outside": (0.70, 0.70, 0.95, 0.95),
    }

    first = model.inspect(reference, inspection, feature_regions=regions)
    second = model.inspect(reference, inspection, feature_regions=regions)

    assert first == second
    assert first.as_record() == second.as_record()
    assert first.mask_bytes == second.mask_bytes
    assert first.registered_bytes == second.registered_bytes
    assert first.mask_sha256 == hashlib.sha256(first.mask_bytes).hexdigest()
    assert first.registered_sha256 == hashlib.sha256(first.registered_bytes).hexdigest()
    assert first.reference_sha256 == reference.original_sha256
    assert first.inspection_sha256 == inspection.original_sha256
    assert first.config_hash == model.config.config_hash
    assert first.pipeline_id == "registered-difference"
    assert first.pipeline_version == "1.0.0"
    assert first.model_version == "1.0.0"
    assert first.dominant_feature == "hole3"
    assert first.anomaly_pixels > 0
    assert first.anomaly_score == round(first.anomaly_pixels / first.total_pixels, 8)

    with Image.open(io.BytesIO(first.mask_bytes)) as mask:
        assert mask.mode == "L"
        assert mask.size == (32, 24)
        mask_values = (
            mask.get_flattened_data() if hasattr(mask, "get_flattened_data") else mask.getdata()
        )
        assert set(mask_values) <= {0, 255}


def test_identical_images_have_zero_anomaly_and_no_dominant_feature(tmp_path: Path) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path))
    reference = ingestor.ingest_bytes(image_bytes(), filename="reference.png")
    model = DeterministicDifferenceModel(ModelConfig(registration_max_shift=0))

    result = model.inspect(reference, reference)

    assert result.anomaly_pixels == 0
    assert result.anomaly_score == 0
    assert result.dominant_feature is None
    assert all(score.anomaly_pixels == 0 for score in result.feature_scores)


def test_small_valid_images_never_emit_non_finite_registration_metrics(tmp_path: Path) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path))
    reference = ingestor.ingest_bytes(image_bytes(size=(4, 3)), filename="reference.png")

    result = DeterministicDifferenceModel().inspect(reference, reference)

    assert math.isfinite(result.registration.mean_absolute_error)
    assert abs(result.registration.dx) < reference.width
    assert abs(result.registration.dy) < reference.height


@pytest.mark.parametrize(
    "regions",
    [
        {},
        {"": (0.0, 0.0, 1.0, 1.0)},
        {"bad": (-0.1, 0.0, 1.0, 1.0)},
        {"bad": (0.0, 0.0, 1.1, 1.0)},
        {"bad": (0.5, 0.0, 0.5, 1.0)},
    ],
)
def test_invalid_feature_mapping_contract_is_rejected(
    regions: dict[str, tuple[float, float, float, float]],
    tmp_path: Path,
) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path))
    reference = ingestor.ingest_bytes(image_bytes(), filename="reference.png")

    with pytest.raises(UnsafeInputError) as exc_info:
        DeterministicDifferenceModel(ModelConfig(registration_max_shift=0)).inspect(
            reference,
            reference,
            feature_regions=regions,
        )

    assert exc_info.value.code == "SCHEMA_INVALID"


def test_configuration_hash_changes_with_any_model_setting() -> None:
    baseline = ModelConfig()

    assert baseline.config_hash != ModelConfig(registration_max_shift=11).config_hash
    assert baseline.config_hash != ModelConfig(difference_threshold=31).config_hash
    assert baseline.config_hash != ModelConfig(registration_sample_stride=3).config_hash
