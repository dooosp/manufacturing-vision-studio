"""Inspection-only registration helper that pins the core model convention."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.e1.oracle import _decode_canonical_png

_IMAGE_SIZE = (512, 384)


def register_inspection_for_v2(
    inspection_bytes: bytes,
    *,
    shift_x: int,
    shift_y: int,
) -> bytes:
    """Apply ``registered[y,x] = inspection[y+dy,x+dx]``.

    The core model fills exposed pixels from the reference.  This inspection-only
    helper has no reference input, so it uses the inspection border median.  It is
    intentionally limited to sign/crop golden tests with a uniform background;
    runtime policy always consumes the core model's exact ``registered_bytes``.
    """

    if isinstance(shift_x, bool) or not isinstance(shift_x, int):
        raise ValueError("shift_x must be an integer")
    if isinstance(shift_y, bool) or not isinstance(shift_y, int):
        raise ValueError("shift_y must be an integer")
    pixels = _decode_canonical_png(
        inspection_bytes,
        mode="RGB",
        expected_size=_IMAGE_SIZE,
        mask=False,
    )
    height, width, _ = pixels.shape
    border = np.concatenate((pixels[0], pixels[-1], pixels[1:-1, 0], pixels[1:-1, -1]), axis=0)
    fill = np.median(border, axis=0).astype(np.uint8)
    registered = np.empty_like(pixels)
    registered[:] = fill

    output_y0 = max(0, -shift_y)
    output_y1 = min(height, height - shift_y)
    output_x0 = max(0, -shift_x)
    output_x1 = min(width, width - shift_x)
    if output_y0 < output_y1 and output_x0 < output_x1:
        registered[output_y0:output_y1, output_x0:output_x1] = pixels[
            output_y0 + shift_y : output_y1 + shift_y,
            output_x0 + shift_x : output_x1 + shift_x,
        ]
    return encode_png(Image.fromarray(registered, mode="RGB"), mode="RGB")


def decode_registered_rgb(payload: bytes) -> np.ndarray:
    """Decode canonical registered bytes for diagnostics without changing them."""

    with Image.open(io.BytesIO(payload)) as image:
        return np.asarray(image, dtype=np.uint8).copy()
