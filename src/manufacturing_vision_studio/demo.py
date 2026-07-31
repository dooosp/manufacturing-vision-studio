"""Seed the deterministic synthetic demonstration through public backend boundaries."""

from __future__ import annotations

from typing import Any

from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.registry import CaseRegistry
from manufacturing_vision_studio.synthetic import generate_demo_images

DEMO_CASE_ID = "case-MVS-DEMO-001"


def seed_demo(
    registry: CaseRegistry,
    *,
    reset: bool = False,
    seed: int = 7,
) -> dict[str, Any]:
    """Create one reference plus nominal/defect inspections and human decisions."""

    if reset:
        registry.reset()
    try:
        return registry.get_case_detail(DEMO_CASE_ID)
    except Exception as exc:
        from manufacturing_vision_studio.errors import NotFoundError

        if not isinstance(exc, NotFoundError):
            raise

    detail = registry.create_case(
        part_id="MVS-DEMO-001",
        cad_revision="rev-A",
        locale="en",
        case_id=DEMO_CASE_ID,
    )
    ingestor = ImageIngestor(registry.settings)
    images = generate_demo_images(seed)

    revision = int(detail["case"]["case_revision"])
    registry.add_reference(
        DEMO_CASE_ID,
        ingestor.ingest_bytes(
            images.reference, filename="reference.png", declared_media_type="image/png"
        ),
        source_kind="synthetic_fixture",
        fixture_id="demo-reference",
        expected_case_revision=revision,
    )
    revision += 1
    nominal = registry.add_inspection(
        DEMO_CASE_ID,
        ingestor.ingest_bytes(
            images.nominal, filename="nominal.png", declared_media_type="image/png"
        ),
        source_kind="synthetic_fixture",
        fixture_id="demo-nominal",
        expected_case_revision=revision,
    )
    revision += 1
    defect = registry.add_inspection(
        DEMO_CASE_ID,
        ingestor.ingest_bytes(
            images.defect, filename="defect.png", declared_media_type="image/png"
        ),
        source_kind="synthetic_fixture",
        fixture_id="demo-defect",
        expected_case_revision=revision,
    )
    revision += 1
    analyses = registry.analyze_case(
        DEMO_CASE_ID,
        expected_case_revision=revision,
    )
    revision += len(analyses)
    by_image = {analysis["input_binding"]["inspection_image_id"]: analysis for analysis in analyses}
    registry.add_disposition(
        DEMO_CASE_ID,
        analysis_id=by_image[nominal["image_id"]]["analysis_id"],
        decision="accept",
        reviewer_id="demo-reviewer",
        reviewer_display_name="Synthetic Demo Reviewer",
        rationale="Synthetic nominal fixture visually matches the registered reference.",
        reason_codes=["visual_confirmation", "score_below_threshold"],
        expected_case_revision=revision,
    )
    revision += 1
    registry.add_disposition(
        DEMO_CASE_ID,
        analysis_id=by_image[defect["image_id"]]["analysis_id"],
        decision="reject",
        reviewer_id="demo-reviewer",
        reviewer_display_name="Synthetic Demo Reviewer",
        rationale=(
            "Synthetic scratch fixture is visible and the anomaly mask overlaps the top face."
        ),
        reason_codes=["visual_confirmation", "score_above_threshold"],
        expected_case_revision=revision,
    )
    return registry.get_case_detail(DEMO_CASE_ID)
