"""Platform-independent PNG encoding for reproducible synthetic evidence."""

from __future__ import annotations

import binascii
import struct
import zlib

from PIL import Image

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_LENGTH_BASES = (
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    13,
    15,
    17,
    19,
    23,
    27,
    31,
    35,
    43,
    51,
    59,
    67,
    83,
    99,
    115,
    131,
    163,
    195,
    227,
    258,
)
_LENGTH_EXTRA_BITS = (
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    1,
    1,
    1,
    1,
    2,
    2,
    2,
    2,
    3,
    3,
    3,
    3,
    4,
    4,
    4,
    4,
    5,
    5,
    5,
    5,
    0,
)
_DISTANCE_BASES = (
    1,
    2,
    3,
    4,
    5,
    7,
    9,
    13,
    17,
    25,
    33,
    49,
    65,
    97,
    129,
    193,
    257,
    385,
    513,
    769,
    1025,
    1537,
    2049,
    3073,
    4097,
    6145,
    8193,
    12289,
    16385,
    24577,
)
_DISTANCE_EXTRA_BITS = (
    0,
    0,
    0,
    0,
    1,
    1,
    2,
    2,
    3,
    3,
    4,
    4,
    5,
    5,
    6,
    6,
    7,
    7,
    8,
    8,
    9,
    9,
    10,
    10,
    11,
    11,
    12,
    12,
    13,
    13,
)


def encode_png(image: Image.Image, *, mode: str) -> bytes:
    """Encode an 8-bit image with fixed filters and a fixed-Huffman DEFLATE stream.

    Pillow's compressed PNG bytes can vary with the platform's zlib build even
    when the decoded pixels are identical. Evidence hashes need a stronger
    contract, so this encoder fixes the scanline filter, zlib framing, DEFLATE
    block boundaries, and PNG chunk layout explicitly.
    """

    if mode not in {"L", "RGB"}:
        raise ValueError("Canonical PNG mode must be L or RGB")
    converted = image if image.mode == mode else image.convert(mode)
    width, height = converted.size
    if width <= 0 or height <= 0:
        raise ValueError("Canonical PNG dimensions must be positive")

    channels = 1 if mode == "L" else 3
    pixels = converted.tobytes()
    stride = width * channels
    expected = stride * height
    if len(pixels) != expected:
        raise ValueError("Canonical PNG pixel buffer has an unexpected length")

    scanlines = bytearray(expected + height)
    source_offset = 0
    target_offset = 0
    for _row in range(height):
        scanlines[target_offset] = 0  # PNG filter method: None
        target_offset += 1
        scanlines[target_offset : target_offset + stride] = pixels[
            source_offset : source_offset + stride
        ]
        source_offset += stride
        target_offset += stride

    color_type = 0 if mode == "L" else 2
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"".join(
        (
            PNG_SIGNATURE,
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", _fixed_zlib(bytes(scanlines))),
            _chunk(b"IEND", b""),
        )
    )


class _BitWriter:
    def __init__(self) -> None:
        self.output = bytearray()
        self.buffer = 0
        self.count = 0

    def write(self, value: int, bit_count: int) -> None:
        self.buffer |= (value & ((1 << bit_count) - 1)) << self.count
        self.count += bit_count
        while self.count >= 8:
            self.output.append(self.buffer & 0xFF)
            self.buffer >>= 8
            self.count -= 8

    def finish(self) -> bytes:
        if self.count:
            self.output.append(self.buffer & 0xFF)
            self.buffer = 0
            self.count = 0
        return bytes(self.output)


def _fixed_zlib(payload: bytes) -> bytes:
    """Return a canonical zlib stream with a deterministic fixed-Huffman LZ77 block."""

    writer = _BitWriter()
    writer.write(0b011, 3)  # final block, fixed Huffman coding
    last_position: dict[bytes, int] = {}
    offset = 0
    while offset < len(payload):
        match_length = 0
        match_distance = 0
        if offset + 3 <= len(payload):
            key = payload[offset : offset + 3]
            previous = last_position.get(key)
            if previous is not None and offset - previous <= 32_768:
                limit = min(258, len(payload) - offset)
                length = 3
                while length < limit and payload[previous + length] == payload[offset + length]:
                    length += 1
                if length >= 4:
                    match_length = length
                    match_distance = offset - previous

        if match_length:
            _write_length_distance(writer, match_length, match_distance)
            end = offset + match_length
            for position in range(offset, end):
                if position + 3 <= len(payload):
                    last_position[payload[position : position + 3]] = position
            offset = end
        else:
            _write_fixed_symbol(writer, payload[offset])
            if offset + 3 <= len(payload):
                last_position[payload[offset : offset + 3]] = offset
            offset += 1

    _write_fixed_symbol(writer, 256)
    compressed = writer.finish()
    return b"\x78\x01" + compressed + struct.pack(">I", zlib.adler32(payload) & 0xFFFFFFFF)


def _write_length_distance(writer: _BitWriter, length: int, distance: int) -> None:
    length_index = (
        len(_LENGTH_BASES) - 1
        if length == 258
        else _range_index(length, _LENGTH_BASES, _LENGTH_EXTRA_BITS)
    )
    _write_fixed_symbol(writer, 257 + length_index)
    length_extra = _LENGTH_EXTRA_BITS[length_index]
    if length_extra:
        writer.write(length - _LENGTH_BASES[length_index], length_extra)

    distance_index = _range_index(distance, _DISTANCE_BASES, _DISTANCE_EXTRA_BITS)
    writer.write(_reverse_bits(distance_index, 5), 5)
    distance_extra = _DISTANCE_EXTRA_BITS[distance_index]
    if distance_extra:
        writer.write(distance - _DISTANCE_BASES[distance_index], distance_extra)


def _range_index(value: int, bases: tuple[int, ...], extra_bits: tuple[int, ...]) -> int:
    for index, (base, bits) in enumerate(zip(bases, extra_bits, strict=True)):
        if value <= base + (1 << bits) - 1:
            return index
    raise ValueError("Canonical DEFLATE value is outside the supported range")


def _write_fixed_symbol(writer: _BitWriter, symbol: int) -> None:
    if 0 <= symbol <= 143:
        code, bit_count = symbol + 0x30, 8
    elif symbol <= 255:
        code, bit_count = symbol - 144 + 0x190, 9
    elif symbol <= 279:
        code, bit_count = symbol - 256, 7
    elif symbol <= 287:
        code, bit_count = symbol - 280 + 0xC0, 8
    else:
        raise ValueError("Canonical DEFLATE symbol is outside the fixed table")
    writer.write(_reverse_bits(code, bit_count), bit_count)


def _reverse_bits(value: int, bit_count: int) -> int:
    reversed_value = 0
    for _index in range(bit_count):
        reversed_value = (reversed_value << 1) | (value & 1)
        value >>= 1
    return reversed_value


def _chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)
