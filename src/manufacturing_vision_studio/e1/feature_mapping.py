"""Exclusive feature mapping from canonical final anomaly masks."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

import numpy as np

from manufacturing_vision_studio.canonical import canonical_json_bytes, sha256_bytes
from manufacturing_vision_studio.e1.domain_v2 import FeatureOwnershipConfig
from manufacturing_vision_studio.e1.oracle import _decode_canonical_png
from manufacturing_vision_studio.errors import UnsafeInputError

FEATURE_OWNERSHIP_PRIORITY = (
    "hole_left",
    "hole_right",
    "top_edge",
    "bottom_edge",
    "top_face",
)


@dataclass(frozen=True, slots=True)
class FeatureOwnershipMap:
    """A deterministic one-label-per-pixel ownership raster."""

    config: FeatureOwnershipConfig
    width: int
    height: int
    labels: np.ndarray
    ownership_map_sha256: str

    def label_at(self, x: int, y: int) -> str | None:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise ValueError("ownership coordinate is outside the image")
        label = int(self.labels[y, x])
        return None if label == 0 else self.config.feature_ids[label - 1]


@dataclass(frozen=True, slots=True)
class FeatureMappingResult:
    """Traceable decision made from a final canonical mask only."""

    predicted_feature_id: str | None
    status: str
    reason: str
    owner_pixel_counts: Mapping[str, int]
    owned_pixel_count: int
    winner_owned_pixel_count: int
    final_positive_pixel_count: int
    unmapped_pixel_count: int
    winner_margin: float | None
    final_mask_sha256: str
    ownership_map_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owner_pixel_counts", MappingProxyType(dict(self.owner_pixel_counts))
        )

    def as_record(self) -> dict[str, object]:
        """Return an auditable JSON projection with a fixed margin representation."""

        return {
            "predicted_feature_id": self.predicted_feature_id,
            "status": self.status,
            "reason": self.reason,
            "owner_pixel_counts": dict(sorted(self.owner_pixel_counts.items())),
            "owned_pixel_count": self.owned_pixel_count,
            "winner_owned_pixel_count": self.winner_owned_pixel_count,
            "final_positive_pixel_count": self.final_positive_pixel_count,
            "unmapped_pixel_count": self.unmapped_pixel_count,
            "winner_margin": None if self.winner_margin is None else f"{self.winner_margin:.8f}",
            "final_mask_sha256": self.final_mask_sha256,
            "ownership_map_sha256": self.ownership_map_sha256,
        }


def build_ownership_map(
    config: FeatureOwnershipConfig,
    image_size: tuple[int, int],
) -> FeatureOwnershipMap:
    """Rasterize normalized boxes into an exclusive, priority-owned label map."""

    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError("ownership image dimensions must be positive")
    if config.priority != FEATURE_OWNERSHIP_PRIORITY:
        raise ValueError("feature ownership priority does not match the frozen algorithm")
    labels = np.zeros((height, width), dtype=np.uint8)
    codes = {feature_id: index + 1 for index, feature_id in enumerate(config.feature_ids)}
    for feature_id in config.priority:
        left, top, right, bottom = config.feature_boxes[feature_id]
        x0 = max(0, min(width, int(np.floor(left * width))))
        y0 = max(0, min(height, int(np.floor(top * height))))
        x1 = max(0, min(width, int(np.ceil(right * width))))
        y1 = max(0, min(height, int(np.ceil(bottom * height))))
        target = labels[y0:y1, x0:x1]
        target[target == 0] = codes[feature_id]
    labels.setflags(write=False)
    digest_input = (
        canonical_json_bytes(
            {
                "algorithm": config.algorithm,
                "revision": config.cad_revision.value,
                "view": config.view_id.value,
                "width": width,
                "height": height,
                "feature_ids": list(config.feature_ids),
                "priority": list(config.priority),
            }
        )
        + b"\0"
        + labels.tobytes(order="C")
    )
    return FeatureOwnershipMap(
        config=config,
        width=width,
        height=height,
        labels=labels,
        ownership_map_sha256=hashlib.sha256(digest_input).hexdigest(),
    )


def map_final_mask(
    mask_bytes: bytes,
    ownership: FeatureOwnershipMap,
    *,
    minimum_winner_pixels: int = 8,
    ambiguity_margin: float = 0.10,
) -> FeatureMappingResult:
    """Map only final-mask pixels, retaining unmapped pixels in the trace."""

    if minimum_winner_pixels < 1:
        raise ValueError("minimum winner pixels must be positive")
    margin = Fraction(str(ambiguity_margin))
    if not 0 <= margin <= 1:
        raise ValueError("ambiguity margin must be in [0, 1]")
    pixels = _decode_canonical_png(
        mask_bytes,
        mode="L",
        expected_size=(ownership.width, ownership.height),
        mask=True,
    )
    if not set(int(value) for value in np.unique(pixels)).issubset({0, 255}):
        raise UnsafeInputError("Final mask must contain only 0 and 255", code="MASK_CORRUPT")
    final_positive = pixels == 255
    labels = ownership.labels[final_positive]
    counts_by_code = np.bincount(labels, minlength=len(ownership.config.feature_ids) + 1)
    owner_counts = {
        feature_id: int(counts_by_code[index + 1])
        for index, feature_id in enumerate(ownership.config.feature_ids)
    }
    owned_count = sum(owner_counts.values())
    final_count = int(np.count_nonzero(final_positive))
    unmapped_count = int(counts_by_code[0])
    if owned_count + unmapped_count != final_count:
        raise AssertionError("feature ownership does not conserve final-mask pixels")
    ordered = sorted(owner_counts.items(), key=lambda item: (-item[1], item[0]))
    winner_id, winner_count = ordered[0]
    runner_count = ordered[1][1] if len(ordered) > 1 else 0
    winner_margin = (
        None if owned_count == 0 else round((winner_count - runner_count) / winner_count, 8)
    )
    final_hash = sha256_bytes(mask_bytes)
    if owned_count == 0:
        return _result(
            None,
            "UNMAPPED",
            "NO_OWNED_PIXELS",
            owner_counts,
            owned_count,
            winner_count,
            final_count,
            unmapped_count,
            winner_margin,
            final_hash,
            ownership.ownership_map_sha256,
        )
    if winner_count < minimum_winner_pixels:
        return _result(
            None,
            "UNMAPPED",
            "INSUFFICIENT_MAPPED_PIXELS",
            owner_counts,
            owned_count,
            winner_count,
            final_count,
            unmapped_count,
            winner_margin,
            final_hash,
            ownership.ownership_map_sha256,
        )
    if winner_count == runner_count:
        return _result(
            None,
            "AMBIGUOUS",
            "AMBIGUOUS_FEATURE",
            owner_counts,
            owned_count,
            winner_count,
            final_count,
            unmapped_count,
            winner_margin,
            final_hash,
            ownership.ownership_map_sha256,
        )
    if (winner_count - runner_count) * margin.denominator < margin.numerator * winner_count:
        return _result(
            None,
            "AMBIGUOUS",
            "AMBIGUOUS_FEATURE",
            owner_counts,
            owned_count,
            winner_count,
            final_count,
            unmapped_count,
            winner_margin,
            final_hash,
            ownership.ownership_map_sha256,
        )
    return _result(
        winner_id,
        "MAPPED",
        "MAPPED",
        owner_counts,
        owned_count,
        winner_count,
        final_count,
        unmapped_count,
        winner_margin,
        final_hash,
        ownership.ownership_map_sha256,
    )


def _result(
    predicted_feature_id: str | None,
    status: str,
    reason: str,
    owner_pixel_counts: Mapping[str, int],
    owned_pixel_count: int,
    winner_owned_pixel_count: int,
    final_positive_pixel_count: int,
    unmapped_pixel_count: int,
    winner_margin: float | None,
    final_mask_sha256: str,
    ownership_map_sha256: str,
) -> FeatureMappingResult:
    return FeatureMappingResult(
        predicted_feature_id=predicted_feature_id,
        status=status,
        reason=reason,
        owner_pixel_counts=dict(sorted(owner_pixel_counts.items())),
        owned_pixel_count=owned_pixel_count,
        winner_owned_pixel_count=winner_owned_pixel_count,
        final_positive_pixel_count=final_positive_pixel_count,
        unmapped_pixel_count=unmapped_pixel_count,
        winner_margin=winner_margin,
        final_mask_sha256=final_mask_sha256,
        ownership_map_sha256=ownership_map_sha256,
    )
