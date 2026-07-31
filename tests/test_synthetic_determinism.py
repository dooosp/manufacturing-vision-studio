from __future__ import annotations

import hashlib
import io

from PIL import Image

from manufacturing_vision_studio.synthetic import generate_demo_images, generate_synthetic_part


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_demo_fixture_generation_is_byte_stable_for_a_fixed_seed() -> None:
    first = generate_demo_images(seed=7)
    second = generate_demo_images(seed=7)

    assert first == second
    assert first.reference == second.reference
    assert first.nominal == second.nominal
    assert first.defect == second.defect
    assert digest(first.reference) == digest(second.reference)
    assert digest(first.nominal) == digest(second.nominal)
    assert digest(first.defect) == digest(second.defect)
    assert len({digest(first.reference), digest(first.nominal), digest(first.defect)}) == 3
    assert {
        "reference": (len(first.reference), digest(first.reference)),
        "nominal": (len(first.nominal), digest(first.nominal)),
        "defect": (len(first.defect), digest(first.defect)),
    } == {
        "reference": (
            3227,
            "0f5292fac23f3ba4dcaeb32ea67766d136e60661c29fd47eb13e09699cd1276c",
        ),
        "nominal": (
            3227,
            "7444709a82219ae3f2386517921ab4b3166e54b42649a18b0337ce9b8cc1a028",
        ),
        "defect": (
            3554,
            "9512e5c64b8cac718de62c8d1b663e0fc315ddaf81d8fee526eee26b228ce074",
        ),
    }


def test_seed_changes_rendered_fixture_bytes() -> None:
    first = generate_demo_images(seed=7)
    second = generate_demo_images(seed=8)

    assert digest(first.reference) != digest(second.reference)
    assert digest(first.nominal) != digest(second.nominal)
    assert digest(first.defect) != digest(second.defect)


def test_generated_fixture_is_single_frame_rgb_png_without_embedded_metadata() -> None:
    generated = generate_synthetic_part(seed=7, defect=True)

    with Image.open(io.BytesIO(generated)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (512, 384)
        assert getattr(image, "n_frames", 1) == 1
        assert image.info == {}
