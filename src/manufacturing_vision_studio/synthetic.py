"""Deterministic synthetic plate images used by the checked-in demo."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image, ImageDraw

from manufacturing_vision_studio.canonical_png import encode_png


@dataclass(frozen=True, slots=True)
class SyntheticDemoImages:
    reference: bytes
    nominal: bytes
    defect: bytes


def generate_synthetic_part(
    *,
    seed: int = 7,
    defect: bool = False,
    shift: tuple[int, int] = (0, 0),
    width: int = 512,
    height: int = 384,
) -> bytes:
    """Render a simple machined plate; this is illustrative, not shop-floor data."""

    if width < 128 or height < 96:
        raise ValueError("Synthetic image dimensions are too small")
    rng = random.Random(seed)
    background = (238, 241, 244)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    plate_box = (52, 64, width - 52, height - 64)
    draw.rounded_rectangle(
        (plate_box[0] + 8, plate_box[1] + 10, plate_box[2] + 8, plate_box[3] + 10),
        radius=20,
        fill=(174, 181, 187),
    )
    draw.rounded_rectangle(
        plate_box,
        radius=20,
        fill=(195, 203, 210),
        outline=(78, 88, 96),
        width=4,
    )
    for y in range(plate_box[1] + 12, plate_box[3] - 8, 13):
        shade = 202 + rng.randrange(-3, 4)
        draw.line((plate_box[0] + 15, y, plate_box[2] - 15, y), fill=(shade, shade + 4, shade + 7))

    hole_radius = 39
    for center_x in (156, width - 156):
        center_y = height // 2
        draw.ellipse(
            (
                center_x - hole_radius,
                center_y - hole_radius,
                center_x + hole_radius,
                center_y + hole_radius,
            ),
            fill=(57, 65, 72),
            outline=(24, 29, 33),
            width=5,
        )
        inner = hole_radius - 11
        draw.ellipse(
            (center_x - inner, center_y - inner, center_x + inner, center_y + inner),
            fill=background,
            outline=(121, 130, 137),
            width=3,
        )

    slot_width = 54
    draw.rounded_rectangle(
        (
            width // 2 - slot_width // 2,
            height // 2 - 66,
            width // 2 + slot_width // 2,
            height // 2 + 66,
        ),
        radius=20,
        fill=(133, 143, 151),
        outline=(69, 78, 85),
        width=4,
    )
    if defect:
        # A dark diagonal scratch on the top face, deliberately away from machined holes.
        draw.line((275, 110, 348, 151), fill=(91, 54, 46), width=9)
        draw.line((279, 108, 351, 148), fill=(231, 179, 161), width=2)

    if shift != (0, 0):
        image = _translate(image, dx=shift[0], dy=shift[1], fill=background)
    return encode_png(image, mode="RGB")


def generate_demo_images(seed: int = 7) -> SyntheticDemoImages:
    """Return one reference, one nominal view, and one visibly defective view."""

    return SyntheticDemoImages(
        reference=generate_synthetic_part(seed=seed),
        nominal=generate_synthetic_part(seed=seed, shift=(3, -2)),
        defect=generate_synthetic_part(seed=seed, defect=True, shift=(-4, 3)),
    )


def _translate(
    image: Image.Image,
    *,
    dx: int,
    dy: int,
    fill: tuple[int, int, int],
) -> Image.Image:
    output = Image.new("RGB", image.size, fill)
    width, height = image.size
    source_left = max(0, -dx)
    source_top = max(0, -dy)
    source_right = min(width, width - dx)
    source_bottom = min(height, height - dy)
    if source_left < source_right and source_top < source_bottom:
        crop = image.crop((source_left, source_top, source_right, source_bottom))
        output.paste(crop, (max(0, dx), max(0, dy)))
    return output
