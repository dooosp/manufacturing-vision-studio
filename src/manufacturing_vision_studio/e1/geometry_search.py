"""Bounded coarse-to-fine image-only geometry Candidate B."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from manufacturing_vision_studio.canonical import sha256_bytes
from manufacturing_vision_studio.e1.geometry import (
    AlignmentObjective,
    AlignmentResult,
    GeometryConfig,
    _abstain,
    _clamp,
    _component_estimate,
    _component_median_shift,
    _evaluate_full_candidates,
    _identity,
    _normalized_transform,
    _parameter_tie,
    _prepare,
    _render_silhouette,
    _resolve_candidates,
    alignment_objective,
    silhouette_edges,
)


@dataclass(frozen=True, slots=True)
class _CoarseCandidate:
    rotation: float
    scale: float
    dx: float
    dy: float
    objective: AlignmentObjective
    silhouette_sha256: str


def align_coarse_to_fine(
    reference_bytes: bytes,
    inspection_bytes: bytes,
    config: GeometryConfig,
) -> AlignmentResult:
    """Search the frozen 1,575-point coarse grid and at most 81 refinements."""

    prepared = _prepare(reference_bytes, inspection_bytes, config)
    if isinstance(prepared, AlignmentResult):
        return prepared
    _reference_image, inspection_image, reference_geometry, inspection_geometry, before = prepared
    estimate = _component_estimate(reference_geometry, inspection_geometry, config)
    _, _, _, _, observed_rotation, observed_scale = estimate
    initial_dx = reference_geometry.median_x - inspection_geometry.median_x
    initial_dy = reference_geometry.median_y - inspection_geometry.median_y
    search_size = config.search_size
    if (
        abs(initial_dx) > config.translation_bound_pixels
        or abs(initial_dy) > config.translation_bound_pixels
    ):
        return _abstain(
            inspection_bytes,
            "TRANSLATION_OUT_OF_RANGE",
            pre_shift=(initial_dx, initial_dy),
            observed=(observed_rotation, observed_scale),
            before=before,
            search_size=search_size,
        )
    if before.value == 0.0:
        return _identity(
            inspection_bytes,
            before,
            pre_shift=(initial_dx, initial_dy),
            observed=(observed_rotation, observed_scale),
            search_size=search_size,
            post_shift=_component_median_shift(reference_geometry, inspection_geometry),
        )

    reference_coarse = _downsample_majority(
        reference_geometry.silhouette,
        config.downsample_block_size,
        config.downsample_majority_pixels,
    )
    inspection_coarse = _downsample_majority(
        inspection_geometry.silhouette,
        config.downsample_block_size,
        config.downsample_majority_pixels,
    )
    coarse_candidates = _evaluate_coarse_grid(
        reference_coarse,
        inspection_coarse,
        initial_dx,
        initial_dy,
        config,
    )
    if len(coarse_candidates) > config.coarse_candidate_cap:
        raise AssertionError("Candidate B exceeded its frozen coarse candidate cap")
    if not coarse_candidates:
        return _abstain(
            inspection_bytes,
            "AMBIGUOUS_ALIGNMENT",
            pre_shift=(initial_dx, initial_dy),
            observed=(observed_rotation, observed_scale),
            before=before,
            search_size=search_size,
        )
    coarse_candidates.sort(key=_coarse_tie)
    coarse_best = coarse_candidates[0]

    transforms: set[tuple[float, float, float, float]] = set()
    for rotation_offset in config.refine_rotation_offsets:
        rotation = _clamp(
            coarse_best.rotation + rotation_offset,
            *config.rotation_bounds_degrees,
        )
        for scale_offset in config.refine_scale_offsets:
            scale = _clamp(
                coarse_best.scale + scale_offset,
                *config.correction_scale_bounds,
            )
            for y_offset in config.refine_translation_offsets:
                dy = coarse_best.dy + y_offset
                if abs(dy) > config.translation_bound_pixels:
                    continue
                for x_offset in config.refine_translation_offsets:
                    dx = coarse_best.dx + x_offset
                    if abs(dx) <= config.translation_bound_pixels:
                        transforms.add(_normalized_transform(rotation, scale, dx, dy))
    full_candidates = _evaluate_full_candidates(
        transforms,
        inspection_image,
        inspection_geometry.silhouette,
        reference_geometry.silhouette,
        config,
    )
    if len(full_candidates) > config.refine_candidate_cap:
        raise AssertionError("Candidate B exceeded its frozen refine candidate cap")
    coarse_pixels = len(coarse_candidates) * search_size[0] * search_size[1]
    refine_pixels = len(full_candidates) * config.image_size[0] * config.image_size[1]
    candidate_pixels = coarse_pixels + refine_pixels
    if candidate_pixels > config.candidate_b_pixel_cap:
        raise AssertionError("Candidate B exceeded its frozen candidate-pixel cap")
    return _resolve_candidates(
        inspection_bytes,
        full_candidates,
        before,
        config,
        pre_shift=(initial_dx, initial_dy),
        observed=(observed_rotation, observed_scale),
        counts=(
            len(coarse_candidates) + len(full_candidates),
            len(coarse_candidates),
            len(full_candidates),
            candidate_pixels,
        ),
        search_size=search_size,
        reference_geometry=reference_geometry,
        identity_post_shift=_component_median_shift(reference_geometry, inspection_geometry),
    )


def _downsample_majority(mask: np.ndarray, block_size: int, minimum_pixels: int) -> np.ndarray:
    height, width = mask.shape
    if width % block_size or height % block_size:
        raise ValueError("silhouette dimensions must be divisible by the block size")
    reshaped = mask.reshape(
        height // block_size,
        block_size,
        width // block_size,
        block_size,
    )
    return np.sum(reshaped, axis=(1, 3)) >= minimum_pixels


def _evaluate_coarse_grid(
    reference: np.ndarray,
    inspection: np.ndarray,
    initial_dx: float,
    initial_dy: float,
    config: GeometryConfig,
) -> list[_CoarseCandidate]:
    reference_edges = silhouette_edges(reference)
    seen_parameters: set[tuple[float, float, float, float]] = set()
    seen_silhouettes: set[str] = set()
    candidates: list[_CoarseCandidate] = []
    transforms: list[tuple[float, float, float, float]] = []
    for rotation in config.coarse_rotations:
        for scale in config.coarse_scales:
            for y_offset in config.coarse_translation_offsets:
                dy = initial_dy + y_offset
                if abs(dy) > config.translation_bound_pixels:
                    continue
                for x_offset in config.coarse_translation_offsets:
                    dx = initial_dx + x_offset
                    if abs(dx) <= config.translation_bound_pixels:
                        transform = _normalized_transform(rotation, scale, dx, dy)
                        if transform not in seen_parameters:
                            seen_parameters.add(transform)
                            transforms.append(transform)
    for rotation, scale, dx, dy in sorted(transforms, key=lambda item: _parameter_tie(*item)):
        rendered = _render_silhouette(
            inspection,
            rotation,
            scale,
            dx / config.downsample_block_size,
            dy / config.downsample_block_size,
        )
        rendered_sha = sha256_bytes(rendered.astype(np.uint8).tobytes())
        if rendered_sha in seen_silhouettes:
            continue
        seen_silhouettes.add(rendered_sha)
        objective = alignment_objective(
            reference,
            rendered,
            reference_edges,
            silhouette_edges(rendered),
        )
        candidates.append(_CoarseCandidate(rotation, scale, dx, dy, objective, rendered_sha))
    return candidates


def _coarse_tie(candidate: _CoarseCandidate) -> tuple[float, ...]:
    return (
        candidate.objective.value,
        *_parameter_tie(candidate.rotation, candidate.scale, candidate.dx, candidate.dy),
    )
