from __future__ import annotations

import hashlib
import io

from PIL import Image

from manufacturing_vision_studio.synthetic import generate_demo_images, generate_synthetic_part


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pixel_digest(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        return digest(image.convert("RGB").tobytes())


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
            15143,
            "3e0bdfc13a7d50869d992a5350dead932dd0808ff1e3208ac6e9eb23d7076fb1",
        ),
        "nominal": (
            15116,
            "99ff874ab057caa10f3ed95b007eaebb09e58d1f7b1b8e34dd4244a281aaa76f",
        ),
        "defect": (
            15744,
            "ca232dd29c89a83ff7e7ce6a88ab007fbf2412dc0ef3314cd6ee068128f62014",
        ),
    }
    assert {
        "reference": pixel_digest(first.reference),
        "nominal": pixel_digest(first.nominal),
        "defect": pixel_digest(first.defect),
    } == {
        "reference": "735bc2942eb7b79558c484243c5406882597294d442f5b4aae42c57275834ceb",
        "nominal": "cad81efc389e6cfe18740d7756b39dac159d12b91af3a372d99e7a4803dcb278",
        "defect": "c1646c067933c06fedf78b8cd86a696acaf9dacea6ad00c79c81ba3748e8b64b",
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
