from __future__ import annotations

import io

import pytest
from PIL import Image

from manufacturing_vision_studio.canonical_png import PNG_SIGNATURE, encode_png


@pytest.mark.parametrize("mode,channels", [("L", 1), ("RGB", 3)])
def test_canonical_png_round_trips_exact_pixels(mode: str, channels: int) -> None:
    width, height = 19, 13
    pixels = bytes((index * 73 + 19) % 256 for index in range(width * height * channels))
    source = Image.frombytes(mode, (width, height), pixels)

    first = encode_png(source, mode=mode)
    second = encode_png(source, mode=mode)

    assert first == second
    assert first.startswith(PNG_SIGNATURE)
    with Image.open(io.BytesIO(first)) as decoded:
        decoded.load()
        assert decoded.format == "PNG"
        assert decoded.mode == mode
        assert decoded.size == (width, height)
        assert decoded.tobytes() == pixels
        assert decoded.info == {}


def test_canonical_png_converts_to_declared_mode() -> None:
    source = Image.new("RGBA", (4, 3), (12, 34, 56, 255))

    encoded = encode_png(source, mode="RGB")

    with Image.open(io.BytesIO(encoded)) as decoded:
        assert decoded.mode == "RGB"
        assert decoded.getpixel((0, 0)) == (12, 34, 56)


def test_canonical_png_rejects_unsupported_mode() -> None:
    with pytest.raises(ValueError, match="mode must be L or RGB"):
        encode_png(Image.new("RGBA", (2, 2)), mode="RGBA")
