"""Safe, deterministic PNG/JPEG ingestion."""

from __future__ import annotations

import io
import os
import stat
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from manufacturing_vision_studio.canonical import sha256_bytes
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

        output = io.BytesIO()
        normalized.save(output, format="PNG", optimize=False, compress_level=9)
        canonical = output.getvalue()
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
