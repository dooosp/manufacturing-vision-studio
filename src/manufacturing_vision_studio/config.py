"""Local backend configuration with conservative resource limits."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings; all storage remains beneath ``data_dir``."""

    data_dir: Path = Path("data")
    max_image_bytes: int = 25 * 1024 * 1024
    max_image_width: int = 8192
    max_image_height: int = 8192
    max_image_pixels: int = 40_000_000
    max_images_per_case: int = 64
    max_bundle_bytes: int = 64 * 1024 * 1024
    max_bundle_uncompressed_bytes: int = 128 * 1024 * 1024
    max_bundle_member_bytes: int = 25 * 1024 * 1024
    max_bundle_entries: int = 100
    max_compression_ratio: int = 100

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("MVS_DATA_DIR", "data"))
        return cls(data_dir=data_dir)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "cases.sqlite3"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    def prepare(self) -> None:
        root = self.data_dir.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        for child in (self.blob_dir, self.export_dir):
            resolved = child.expanduser().resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"Configured storage escapes data_dir: {child}")
            resolved.mkdir(parents=True, exist_ok=True)
