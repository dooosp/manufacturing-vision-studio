from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical import canonical_json_bytes
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import MVSError
from manufacturing_vision_studio.images import ImageIngestor
from manufacturing_vision_studio.registry import CaseRegistry


def png_bytes(*, defect: bool) -> bytes:
    image = Image.new("RGB", (48, 32), (40, 50, 60))
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), ((x * 7) % 190, (y * 9) % 190, (x + y) % 190))
    if defect:
        ImageDraw.Draw(image).rectangle((20, 12, 27, 19), fill=(255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=9)
    return output.getvalue()


def analyzed_case(tmp_path: Path) -> tuple[CaseRegistry, dict[str, object]]:
    settings = Settings(data_dir=tmp_path / "data")
    registry = CaseRegistry(settings)
    ingestor = ImageIngestor(settings)
    registry.create_case(part_id="PART-DISPOSITION", cad_revision="A", case_id="case-review")
    registry.add_reference(
        "case-review",
        ingestor.ingest_bytes(png_bytes(defect=False), filename="reference.png"),
        expected_case_revision=1,
    )
    registry.add_inspection(
        "case-review",
        ingestor.ingest_bytes(png_bytes(defect=True), filename="inspection.png"),
        expected_case_revision=2,
    )
    analysis = registry.analyze_case("case-review", expected_case_revision=3)[0]
    return registry, analysis


@pytest.mark.parametrize(
    ("decision", "reason_code"),
    [
        ("accept", "visual_confirmation"),
        ("reject", "score_above_threshold"),
        ("needs_review", "insufficient_evidence"),
        ("model_error", "incorrect_mask"),
    ],
)
def test_all_human_dispositions_round_trip_without_changing_model_result(
    decision: str,
    reason_code: str,
    tmp_path: Path,
) -> None:
    registry, analysis = analyzed_case(tmp_path)
    analysis_before = canonical_json_bytes(analysis)

    disposition = registry.add_disposition(
        "case-review",
        analysis_id=str(analysis["analysis_id"]),
        decision=decision,
        reviewer_id="reviewer-001",
        rationale=f"Independent rationale for {decision}.",
        reason_codes=[reason_code],
        expected_case_revision=4,
    )
    detail = registry.get_case_detail("case-review")

    assert disposition["decision"] == decision
    assert disposition["scope_acknowledgement"] == "demo_only_not_production_validated"
    assert disposition["analysis_binding"]["analysis_id"] == analysis["analysis_id"]
    assert canonical_json_bytes(detail["analyses"][0]) == analysis_before
    assert detail["dispositions"] == [disposition]
    assert detail["case"]["status"] == "disposed"


def test_stale_revision_cannot_record_human_disposition(tmp_path: Path) -> None:
    registry, analysis = analyzed_case(tmp_path)
    before = registry.get_case_detail("case-review")

    with pytest.raises(MVSError) as exc_info:
        registry.add_disposition(
            "case-review",
            analysis_id=str(analysis["analysis_id"]),
            decision="accept",
            reviewer_id="reviewer-001",
            rationale="This stale decision must not be recorded.",
            reason_codes=["visual_confirmation"],
            expected_case_revision=3,
        )

    assert exc_info.value.code == "REVISION_MISMATCH"
    assert registry.get_case_detail("case-review") == before
    assert registry.get_case_detail("case-review")["dispositions"] == []


def test_unknown_disposition_value_is_rejected_without_state_change(tmp_path: Path) -> None:
    registry, analysis = analyzed_case(tmp_path)
    before = registry.get_case_detail("case-review")

    with pytest.raises(MVSError) as exc_info:
        registry.add_disposition(
            "case-review",
            analysis_id=str(analysis["analysis_id"]),
            decision="auto_accept",
            reviewer_id="reviewer-001",
            rationale="An automated decision must not be accepted as human review.",
            reason_codes=["visual_confirmation"],
            expected_case_revision=4,
        )

    assert exc_info.value.code == "SCHEMA_INVALID"
    assert registry.get_case_detail("case-review") == before
