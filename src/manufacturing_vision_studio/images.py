"""Safe, deterministic PNG/JPEG ingestion."""

from __future__ import annotations

import io
import os
import stat
import warnings
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.canonical_png import encode_png
from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import UnsafeInputError

_FORMAT_MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg"}
_MEDIA_TYPE_FORMATS = {value: key for key, value in _FORMAT_MEDIA_TYPES.items()}


@dataclass(frozen=True, slots=True)
class IngestedImage:
    """Validated image with the exact upload and normalized RGB PNG bytes."""

    original_bytes: bytes
    canonical_bytes: bytes
    original_sha256: str
    canonical_sha256: str
    pixel_sha256: str
    width: int
    height: int
    source_format: str
    media_type: str
    filename: str

    def as_array(self) -> np.ndarray:
        with Image.open(io.BytesIO(self.canonical_bytes)) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)


def resolve_canonical_image_bytes(
    image: IngestedImage,
    *,
    expected_canonical_sha256: str,
    allow_legacy_source_png: bool = False,
) -> bytes | None:
    """Resolve the bytes that satisfy a declared canonical-image binding.

    New evidence must bind to the platform-independent encoder. The one legacy
    form accepted here is an explicitly authorized PNG whose source bytes were
    themselves declared canonical. Callers must authorize that form only for a
    recognized, already hash-verified evidence payload.
    """

    if image.canonical_sha256 == expected_canonical_sha256:
        return image.canonical_bytes
    if (
        allow_legacy_source_png
        and image.source_format == "PNG"
        and image.original_sha256 == expected_canonical_sha256
    ):
        return image.original_bytes
    return None


class ImageIngestor:
    """Validate hostile image input before it reaches the analysis pipeline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def ingest_path(
        self,
        path: Path,
        *,
        allowed_root: Path | None = None,
        declared_media_type: str | None = None,
    ) -> IngestedImage:
        """Read one regular non-symlink file, optionally restricted to a root."""

        candidate = path.expanduser()
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise UnsafeInputError(
                "Image path could not be read",
                code="NON_REGULAR_INPUT",
                details={"path": str(path)},
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise UnsafeInputError("Symbolic links are not accepted", code="SYMLINK_INPUT")
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafeInputError("Image input must be a regular file", code="NON_REGULAR_INPUT")
        resolved = candidate.resolve()
        if allowed_root is not None and not resolved.is_relative_to(allowed_root.resolve()):
            raise UnsafeInputError("Image path escapes the allowed root", code="UNSAFE_PATH")
        if metadata.st_size > self.settings.max_image_bytes:
            raise UnsafeInputError("Image exceeds byte limit", code="INPUT_TOO_LARGE")
        data = _read_regular_no_follow(
            resolved,
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            byte_limit=self.settings.max_image_bytes,
        )
        return self.ingest_bytes(
            data,
            filename=resolved.name,
            declared_media_type=declared_media_type,
        )

    def ingest_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        declared_media_type: str | None = None,
    ) -> IngestedImage:
        """Decode a bounded PNG/JPEG and normalize it to metadata-free RGB PNG."""

        safe_name = validate_client_filename(filename)
        if not data:
            raise UnsafeInputError("Image is empty", code="IMAGE_DECODE_FAILED")
        if len(data) > self.settings.max_image_bytes:
            raise UnsafeInputError(
                "Image exceeds byte limit",
                code="INPUT_TOO_LARGE",
                details={"limit": self.settings.max_image_bytes, "actual": len(data)},
            )
        normalized_declared = (
            declared_media_type.split(";", 1)[0].strip().lower() if declared_media_type else None
        )
        if normalized_declared and normalized_declared not in {
            *_MEDIA_TYPE_FORMATS,
            "application/octet-stream",
        }:
            raise UnsafeInputError(
                "Only PNG and JPEG images are accepted",
                code="UNSUPPORTED_FORMAT",
                details={"media_type": normalized_declared},
            )

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as probe:
                    source_format = (probe.format or "").upper()
                    if source_format not in _FORMAT_MEDIA_TYPES:
                        raise UnsafeInputError(
                            "Only PNG and JPEG images are accepted",
                            code="UNSUPPORTED_FORMAT",
                            details={"detected_format": source_format or None},
                        )
                    width, height = probe.size
                    self._validate_dimensions(width, height)
                    if getattr(probe, "n_frames", 1) != 1:
                        raise UnsafeInputError(
                            "Animated or multi-frame images are not accepted",
                            code="UNSUPPORTED_FORMAT",
                        )
                    if (
                        normalized_declared in _MEDIA_TYPE_FORMATS
                        and _MEDIA_TYPE_FORMATS[normalized_declared] != source_format
                    ):
                        raise UnsafeInputError(
                            "Declared and detected image formats differ",
                            code="UNSUPPORTED_FORMAT",
                            details={
                                "declared": normalized_declared,
                                "detected": _FORMAT_MEDIA_TYPES[source_format],
                            },
                        )
                    _validate_exact_container(data, source_format)
                    probe.verify()

                with Image.open(io.BytesIO(data)) as decoded:
                    normalized = ImageOps.exif_transpose(decoded).convert("RGB")
                    width, height = normalized.size
                    self._validate_dimensions(width, height)
                    normalized.load()
        except UnsafeInputError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise UnsafeInputError(
                "Image dimensions exceed the safe limit",
                code="IMAGE_DIMENSIONS_EXCEEDED",
            ) from exc
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            raise UnsafeInputError(
                "Image could not be decoded", code="IMAGE_DECODE_FAILED"
            ) from exc

        canonical = encode_png(normalized, mode="RGB")
        pixels = np.asarray(normalized, dtype=np.uint8)
        return IngestedImage(
            original_bytes=data,
            canonical_bytes=canonical,
            original_sha256=sha256_bytes(data),
            canonical_sha256=sha256_bytes(canonical),
            pixel_sha256=sha256_bytes(pixels.tobytes(order="C")),
            width=width,
            height=height,
            source_format=source_format,
            media_type=_FORMAT_MEDIA_TYPES[source_format],
            filename=safe_name,
        )

    def _validate_dimensions(self, width: int, height: int) -> None:
        if (
            width < 1
            or height < 1
            or width > self.settings.max_image_width
            or height > self.settings.max_image_height
            or width * height > self.settings.max_image_pixels
        ):
            raise UnsafeInputError(
                "Image dimensions exceed the safe limit",
                code="IMAGE_DIMENSIONS_EXCEEDED",
                details={
                    "width": width,
                    "height": height,
                    "max_width": self.settings.max_image_width,
                    "max_height": self.settings.max_image_height,
                    "max_pixels": self.settings.max_image_pixels,
                },
            )


def validate_client_filename(filename: str) -> str:
    """Require a basename without control characters or path semantics."""

    if not filename or len(filename.encode("utf-8")) > 160:
        raise UnsafeInputError("Filename is missing or too long", code="UNSAFE_PATH")
    if filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise UnsafeInputError("Filename must not contain a path", code="UNSAFE_PATH")
    if any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise UnsafeInputError("Filename contains control characters", code="UNSAFE_PATH")
    if Path(filename).name != filename:
        raise UnsafeInputError("Filename must be a basename", code="UNSAFE_PATH")
    return filename


def _read_regular_no_follow(
    path: Path,
    *,
    expected_device: int,
    expected_inode: int,
    byte_limit: int,
) -> bytes:
    """Open the validated path without following a swapped final symlink."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise UnsafeInputError("Image input must be a regular file", code="NON_REGULAR_INPUT")
        if (opened.st_dev, opened.st_ino) != (expected_device, expected_inode):
            raise UnsafeInputError("Image path changed during validation", code="SYMLINK_INPUT")
        chunks: list[bytes] = []
        remaining = byte_limit + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > byte_limit:
            raise UnsafeInputError("Image exceeds byte limit", code="INPUT_TOO_LARGE")
        return data
    except UnsafeInputError:
        raise
    except OSError as exc:
        # O_NOFOLLOW reports ELOOP for a swapped symlink on supported platforms.
        raise UnsafeInputError(
            "Image path changed during validation", code="SYMLINK_INPUT"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_exact_container(data: bytes, source_format: str) -> None:
    """Require the detected image container to terminate exactly at EOF."""

    if source_format == "PNG":
        _validate_png_container(data)
        return
    if source_format == "JPEG":
        _validate_jpeg_container(data)
        return
    raise ValueError("unsupported image container")


def _validate_png_container(data: bytes) -> None:
    """Validate PNG chunk framing, CRCs, and an EOF-aligned IEND chunk."""

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")

    view = memoryview(data)
    position = 8
    chunk_index = 0
    saw_idat = False
    while position < len(data):
        if len(data) - position < 12:
            raise ValueError("truncated PNG chunk")
        chunk_length = int.from_bytes(view[position : position + 4], "big")
        chunk_type = bytes(view[position + 4 : position + 8])
        if not all(
            ord("A") <= value <= ord("Z") or ord("a") <= value <= ord("z") for value in chunk_type
        ):
            raise ValueError("invalid PNG chunk type")
        chunk_end = position + 12 + chunk_length
        if chunk_end > len(data):
            raise ValueError("truncated PNG chunk")

        payload_start = position + 8
        payload_end = payload_start + chunk_length
        expected_crc = int.from_bytes(view[payload_end : payload_end + 4], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(view[payload_start:payload_end], actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("invalid PNG chunk CRC")

        if chunk_index == 0 and (chunk_type != b"IHDR" or chunk_length != 13):
            raise ValueError("invalid PNG header chunk")
        if chunk_index > 0 and chunk_type == b"IHDR":
            raise ValueError("duplicate PNG header chunk")
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if chunk_length != 0 or not saw_idat or chunk_end != len(data):
                raise ValueError("invalid PNG end chunk")
            return

        position = chunk_end
        chunk_index += 1

    raise ValueError("missing PNG end chunk")


def _validate_jpeg_container(data: bytes) -> None:
    """Walk JPEG markers and require the first real EOI marker at exact EOF."""

    if not data.startswith(b"\xff\xd8"):
        raise ValueError("invalid JPEG start marker")

    position = 2
    in_scan = False
    saw_scan = False
    while True:
        marker_from_scan = in_scan
        if in_scan:
            marker, position = _next_jpeg_scan_marker(data, position)
            in_scan = False
        else:
            marker, position = _next_jpeg_marker(data, position)

        if marker == 0xD9:  # EOI
            if not saw_scan or position != len(data):
                raise ValueError("JPEG end marker is not at EOF")
            return
        if marker == 0xD8:  # SOI may only occur at byte zero.
            raise ValueError("unexpected JPEG start marker")
        if 0xD0 <= marker <= 0xD7:  # Restart markers belong inside scan data.
            raise ValueError("JPEG restart marker outside scan data")
        if marker == 0x01:  # Standalone TEM marker.
            in_scan = marker_from_scan
            continue

        if len(data) - position < 2:
            raise ValueError("truncated JPEG segment")
        segment_length = int.from_bytes(data[position : position + 2], "big")
        if segment_length < 2:
            raise ValueError("invalid JPEG segment length")
        segment_end = position + segment_length
        if segment_end > len(data):
            raise ValueError("truncated JPEG segment")
        position = segment_end

        if marker == 0xDA:  # SOS starts entropy-coded scan data.
            saw_scan = True
            in_scan = True
        elif marker_from_scan and marker == 0xDC:  # DNL does not end the scan.
            in_scan = True


def _next_jpeg_marker(data: bytes, position: int) -> tuple[int, int]:
    """Read one marker outside entropy-coded scan data."""

    if position >= len(data) or data[position] != 0xFF:
        raise ValueError("missing JPEG marker prefix")
    while position < len(data) and data[position] == 0xFF:
        position += 1
    if position >= len(data) or data[position] == 0x00:
        raise ValueError("invalid JPEG marker")
    return data[position], position + 1


def _next_jpeg_scan_marker(data: bytes, position: int) -> tuple[int, int]:
    """Find the next unstuffed, non-restart marker in JPEG scan data."""

    while position < len(data):
        marker_prefix = data.find(b"\xff", position)
        if marker_prefix < 0:
            break
        position = marker_prefix + 1
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker == 0x00 or 0xD0 <= marker <= 0xD7:
            continue
        return marker, position
    raise ValueError("missing JPEG end marker")
