from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from PIL import Image

from manufacturing_vision_studio.config import Settings
from manufacturing_vision_studio.errors import UnsafeInputError
from manufacturing_vision_studio.images import ImageIngestor

ADVERSARIAL = Path(__file__).parents[1] / "fixtures" / "adversarial"


def png_bytes(
    *,
    size: tuple[int, int] = (8, 6),
    color: tuple[int, int, int] = (17, 34, 51),
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (17, 34, 51)).save(output, format="JPEG", quality=90)
    return output.getvalue()


def assert_rejected(exc_info: pytest.ExceptionInfo[UnsafeInputError], code: str) -> None:
    assert exc_info.value.code == code


@pytest.mark.parametrize("name", ["fake-signature.png", "truncated.png", "corrupt-mask.png"])
def test_malformed_images_fail_closed(name: str, tmp_path: Path) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path / "data"))

    with pytest.raises(UnsafeInputError) as exc_info:
        ingestor.ingest_bytes((ADVERSARIAL / name).read_bytes(), filename=name)

    assert_rejected(exc_info, "IMAGE_DECODE_FAILED")
    assert not (tmp_path / "data").exists()


def test_valid_but_unsupported_image_format_is_rejected(tmp_path: Path) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path / "data"))

    with pytest.raises(UnsafeInputError) as exc_info:
        ingestor.ingest_bytes(
            (ADVERSARIAL / "unsupported.pgm").read_bytes(),
            filename="unsupported.pgm",
        )

    assert_rejected(exc_info, "UNSUPPORTED_FORMAT")


def test_multiframe_image_is_rejected_without_processing_frames(tmp_path: Path) -> None:
    output = io.BytesIO()
    first = Image.new("RGB", (8, 6), (10, 20, 30))
    second = Image.new("RGB", (8, 6), (200, 210, 220))
    first.save(output, format="GIF", save_all=True, append_images=[second])

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path)).ingest_bytes(
            output.getvalue(),
            filename="animated.gif",
        )

    assert_rejected(exc_info, "UNSUPPORTED_FORMAT")


@pytest.mark.parametrize(
    ("filename", "image"),
    [
        ("polyglot.png", png_bytes()),
        ("polyglot.jpg", jpeg_bytes()),
    ],
)
def test_image_with_trailing_nonimage_payload_is_rejected(
    filename: str,
    image: bytes,
    tmp_path: Path,
) -> None:
    polyglot = image + b"<script>non-image-payload</script>"

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path)).ingest_bytes(
            polyglot,
            filename=filename,
        )

    assert_rejected(exc_info, "IMAGE_DECODE_FAILED")


def test_encoded_byte_limit_is_enforced_before_decode(tmp_path: Path) -> None:
    image = png_bytes()
    settings = Settings(data_dir=tmp_path / "data", max_image_bytes=len(image) - 1)

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(settings).ingest_bytes(image, filename="bounded.png")

    assert_rejected(exc_info, "INPUT_TOO_LARGE")
    assert exc_info.value.details == {"limit": len(image) - 1, "actual": len(image)}


@pytest.mark.parametrize(
    ("size", "limit_overrides"),
    [
        ((3, 2), {"max_image_width": 2}),
        ((2, 3), {"max_image_height": 2}),
        ((3, 3), {"max_image_pixels": 8}),
    ],
)
def test_decoded_dimension_limits_are_enforced(
    size: tuple[int, int],
    limit_overrides: dict[str, int],
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data", **limit_overrides)

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(settings).ingest_bytes(png_bytes(size=size), filename="large.png")

    assert_rejected(exc_info, "IMAGE_DIMENSIONS_EXCEEDED")


def test_detected_content_must_match_declared_media_type(tmp_path: Path) -> None:
    ingestor = ImageIngestor(Settings(data_dir=tmp_path / "data"))

    with pytest.raises(UnsafeInputError) as exc_info:
        ingestor.ingest_bytes(
            png_bytes(),
            filename="misdeclared.jpg",
            declared_media_type="image/jpeg",
        )

    assert_rejected(exc_info, "UNSUPPORTED_FORMAT")


@pytest.mark.parametrize(
    "filename",
    [
        "../inspection.png",
        "..\\inspection.png",
        "/absolute.png",
        "nested/inspection.png",
        "nested\\inspection.png",
        ".",
        "..",
        "nul\x00.png",
        "line\nbreak.png",
    ],
)
def test_client_filename_path_semantics_are_rejected(filename: str, tmp_path: Path) -> None:
    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path)).ingest_bytes(
            png_bytes(),
            filename=filename,
        )

    assert_rejected(exc_info, "UNSAFE_PATH")


def test_allowed_root_check_resists_prefix_collision(tmp_path: Path) -> None:
    allowed_root = tmp_path / "images"
    outside_root = tmp_path / "images-other"
    allowed_root.mkdir()
    outside_root.mkdir()
    outside_image = outside_root / "inspection.png"
    outside_image.write_bytes(png_bytes())

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path / "data")).ingest_path(
            outside_image,
            allowed_root=allowed_root,
        )

    assert_rejected(exc_info, "UNSAFE_PATH")


@pytest.mark.parametrize("target_inside_root", [True, False])
def test_symlink_is_rejected_before_target_is_read(
    target_inside_root: bool,
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    target_root = allowed_root if target_inside_root else tmp_path / "outside"
    target_root.mkdir(exist_ok=True)
    target = target_root / "target.png"
    target.write_bytes(png_bytes())
    link = allowed_root / "linked.png"
    try:
        link.symlink_to(target)
    except OSError as exc:  # pragma: no cover - platform permission guard
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path / "data")).ingest_path(
            link,
            allowed_root=allowed_root,
        )

    assert_rejected(exc_info, "SYMLINK_INPUT")


def test_symlink_swap_between_validation_and_read_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    candidate = allowed_root / "candidate.png"
    candidate.write_bytes(png_bytes(color=(1, 2, 3)))
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes(color=(250, 251, 252)))
    original_open = os.open
    swapped = False

    def swap_then_open(
        path: Path | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(path) == candidate and not swapped:
            swapped = True
            candidate.unlink()
            candidate.symlink_to(outside)
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_then_open)

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path / "data")).ingest_path(
            candidate,
            allowed_root=allowed_root,
        )

    assert swapped
    assert_rejected(exc_info, "SYMLINK_INPUT")


def test_directory_input_is_rejected_as_non_regular(tmp_path: Path) -> None:
    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path / "data")).ingest_path(tmp_path)

    assert_rejected(exc_info, "NON_REGULAR_INPUT")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is not available on this platform")
def test_fifo_input_is_rejected_without_opening_it(tmp_path: Path) -> None:
    fifo = tmp_path / "image.fifo"
    os.mkfifo(fifo)

    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path / "data")).ingest_path(fifo)

    assert_rejected(exc_info, "NON_REGULAR_INPUT")


def test_missing_path_is_rejected_as_non_regular(tmp_path: Path) -> None:
    with pytest.raises(UnsafeInputError) as exc_info:
        ImageIngestor(Settings(data_dir=tmp_path / "data")).ingest_path(tmp_path / "missing.png")

    assert_rejected(exc_info, "NON_REGULAR_INPUT")


def test_ingestion_is_byte_deterministic_and_preserves_source_hash(tmp_path: Path) -> None:
    source = png_bytes()
    ingestor = ImageIngestor(Settings(data_dir=tmp_path / "data"))

    first = ingestor.ingest_bytes(source, filename="reference.png")
    second = ingestor.ingest_bytes(source, filename="reference.png")

    assert first == second
    assert first.original_bytes == source
    assert first.original_sha256 == second.original_sha256
    assert first.canonical_bytes == second.canonical_bytes
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.pixel_sha256 == second.pixel_sha256
    assert len(first.canonical_bytes) == 73
    assert first.canonical_sha256 == (
        "f4964d5a742835220a007070497db4b06271719e5b22d134bfba4975ee6ee224"
    )
