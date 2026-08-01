# E1 Feasibility and Separability Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only, fail-closed E1 study surface that proves whether the existing v2 image pipeline can pass under known geometric transforms, preserves the historical `HOLD` evidence, and emits one verified terminal decision without reopening Candidate A/B.

**Architecture:** Add a study-owned protocol, truth-free inference adapter, known-transform normalizer, offline truth/oracle layer, artifact verifier, and sealed runner around the existing retained v2 modules. Freeze the exact 108-row diagnostic matrix and the exact 120-member development binding, keep protected v2 scopes unreachable, and serialize every phase as immutable canonical evidence under a dedicated study root.

**Tech Stack:** Python 3.11+, NumPy, Pillow, JSON Schema Draft 2020-12, pytest, Ruff, Mypy, existing `manufacturing_vision_studio.e1` retained modules, canonical JSON/PNG helpers, Make, uv.

## Global Constraints

- Study base remains exact `9fd6d0c600206083fde4fafc874e0226b5df60b3`.
- Active branch is `codex/e1-feasibility-separability-study`.
- Current written-spec clarification commit is `f8f2c74b62c597377fed7f19b72426d72bb59edc`.
- Threshold stays exactly `0.0025`.
- Fixed resampling mode order is `NEAREST`, `BILINEAR`, `BICUBIC`.
- Phase 1 consumes only diagnostic IDs `e1-v2-development-diagnostic-000` through `e1-v2-development-diagnostic-107`.
- Phase 1 accepts no scope, seed override, row filter, resampling override, or output-dependent retry flag.
- Phase 1 identity is the raw canonical RGB absolute-difference mask `max(abs(reference - unnormalized_inspection)) >= 32`; it is not an identity-normalized inference pass.
- Phase 1 promotion gates are maximum per-case truth-pixel recall drop versus identity `<= 0.05`, aggregate median Dice drop versus identity `<= 0.01`, and medium/high classification recall `>= 0.90`.
- Feature oracle requires exact target-feature agreement for every evaluable synthetic defect (`100%`), at least 8 target-owned pixels per case, `owned + unmapped == authoritative positive pixels`, zero ambiguous/null/wrong-feature results, and exact ownership-map hash binding for every revision/view layout.
- Phase 2 fixed counts are clean `24`, nuisance `30`, defect `60`, trust boundary `6`, total `120`.
- Phase 2 runs only when Phase 0 passes, at least one Phase 1 mode is diagnostic-eligible, and the feature oracle passes.
- Phase 2 performance gates are medium/high defect recall `>= 0.90`, nuisance-only false-positive rate `<= 0.05`, positive-case median Dice `>= 0.70`, and affected-feature mapping accuracy `>= 0.95`.
- Trust-boundary members remain binding-only study entries; Phase 2 performs image inference on exactly `114` clean/nuisance/defect rows per eligible mode and excludes the 6 trust rows from all four performance denominators.
- The direct-import allowlist for study-owned production modules is limited to the new study modules plus retained `canonical`, `canonical_png`, `images`, `model`, `e1.domain`, `e1.model`, `e1.feature_mapping`, `e1.protocol_v2`, `e1.metrics_v2`, and offline-truth-only `e1.domain_v2`, `e1.generator`, `e1.generator_v2`, `e1.oracle`.
- Production study modules must not directly import `e1.policy_v2`, `e1.geometry`, `e1.geometry_search`, or `e1.diagnostics_v2`.
- `DevelopmentCorpusProvider` is the only wrapper around `E1V2Generator`; it has no scope argument and calls `plan_cases(EvaluationScope.DEVELOPMENT)` with a literal.
- The study will not modify, rerun, rank, or select Candidate A or Candidate B; it will not implement Candidate C; and it will not update `configs/evaluation/e1-v2-candidate-selection.json`.
- The study will not enumerate or render v2 calibration or release-test members, will not run smoke/calibration/release-test/Task 5/Task 6/Task 7, and will not connect to FreeCAD or modify `/Users/jangtaeho/freecad-live`.
- Every full phase execution is one-time only under one protocol hash and one artifact root. An incomplete claimed phase is `STUDY_INVALID` and cannot be retried under the same protocol/artifact root.
- Artifacts live under `docs/evaluation/results/e1-feasibility-study`; large local raw outputs remain ignored under `data/e1-feasibility-study`.
- The artifact root and all source paths are protocol-fixed. The production CLI exposes no output, scope, seed, row, mode, threshold, or gate override.
- Study JSON is exactly `canonical_json_bytes(document)` with no trailing newline; `record_sha256` excludes only itself.
- `scope-audit.json` is written by the feature-oracle phase after all 120 development bindings exist, not by Phase 0.
- Phase 0 copies Candidate A/B, the Task 4 report, and the SDD ledger into immutable `retained-inputs/` paths and binds both source and copied raw hashes.
- Normal tests, `make validate`, and implementation validation may run only unit/small-fixture controls; they must never execute Phase 1 or Phase 2.
- Terminal decisions are evaluated in this order: `STUDY_INVALID`, `FEATURE_CONTRACT_FAILED`, `KNOWN_TRANSFORM_DIAGNOSTIC_FAILED`, then `DIFFERENCE_BASELINE_LIMITED` or `TRANSFORM_ESTIMATION_LIMITED`.
- Design source of truth is `docs/superpowers/specs/2026-08-01-e1-feasibility-separability-study-design.md`.

---

## File Structure

- Create `configs/evaluation/e1-feasibility-study.v1.json`: closed study protocol with base bindings, gates, paths, allowed modes, frozen hashes, and phase settings.
- Create `configs/evaluation/e1-feasibility-diagnostic-108.json`: checked snapshot of all 108 diagnostic rows and seeds so Phase 1 does not import `e1.diagnostics_v2`.
- Create `schemas/e1-feasibility-study-config.v1.json`: schema for the study protocol and diagnostic matrix references.
- Create `schemas/e1-feasibility-study-artifact.v1.json`: schema for retention, scope, phase claims, oracle, diagnostic, development, and decision records.
- Create `scripts/export_e1_feasibility_matrix.py`: test/tool-only exporter and checker for byte-for-byte parity between the frozen matrix and `build_scale_diagnostic_matrix()`.
- Create `docs/evaluation/negative-results/e1-v2-task4-report.raw.txt`: immutable checked snapshot of the local Task 4 report whose raw SHA-256 is `b6a2093082aa63631adb233c282466539720281ab96b53bc3928cf292efc8835`.
- Create `docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt`: immutable checked snapshot of the local progress ledger whose raw SHA-256 is `fcef0c3b22b962f185911cc74bdad45f1bd2860c42ae8e59bac76d6741c13ea7`.
- Create `src/manufacturing_vision_studio/e1/study_protocol_v2.py`: strict loader, typed protocol objects, path binding, dependency projection helpers, and frozen diagnostic row loader.
- Create `src/manufacturing_vision_studio/e1/known_transform_v2.py`: canonical image validation, inverse-affine math, resampling, median-border fill, and fixed reference-boundary band helpers.
- Create `src/manufacturing_vision_studio/e1/study_inference_v2.py`: truth-free input/result types and retained-pipeline adapter.
- Create `src/manufacturing_vision_studio/e1/study_truth_v2.py`: diagnostic rendering, development corpus provider, applied-transform proof, truth joins, and feature-oracle reduction.
- Create `src/manufacturing_vision_studio/e1/study_artifacts_v2.py`: immutable canonical JSON writer/verifier, execution claims, gate serialization, and artifact inventory helpers.
- Create `src/manufacturing_vision_studio/e1/study_retention_v2.py`: historical HOLD verifier, immutable retained-input capture, implementation projection, and dependency-closure audit.
- Create `src/manufacturing_vision_studio/e1/study_runner_v2.py`: phase state machine, terminal decision table, validation control, and verification entry point.
- Create `src/manufacturing_vision_studio/e1/study_cli_v2.py`: argument-free production subcommands bound to the default study protocol.
- Create `tests/test_e1_feasibility_protocol_v2.py`: protocol/config/snapshot binding tests.
- Create `tests/test_e1_known_transform_v2.py`: inverse-math, parity, and residual-band tests.
- Create `tests/test_e1_study_inference_v2.py`: truth-free signature and pipeline parity tests.
- Create `tests/test_e1_study_truth_v2.py`: rendering, development provider, applied-transform proof, and feature-oracle tests.
- Create `tests/test_e1_study_artifacts_v2.py`: canonical artifact and execution-claim tests.
- Create `tests/test_e1_study_runner_v2.py`: phase gating, decision ordering, and no-rerun tests.
- Create `tests/test_e1_study_dependency_guard_v2.py`: direct-import allowlist and protected-scope guard tests.
- Create `tests/test_e1_study_retention_v2.py`: HOLD/null, raw-evidence, projection, and retained-input capture tests.
- Create `tests/test_e1_study_cli_v2.py`: exact command surface and override-rejection tests.
- Create `tests/test_e1_study_parity_v2.py`: test-only parity against forbidden historical modules.
- Create `docs/evaluation/e1-feasibility-study.md`: operator-facing command and artifact guide.
- Modify `pyproject.toml`: add the study CLI entry point.
- Modify `Makefile`: add study verification and per-phase helper targets without adding full-study execution to `make validate`.

### Task 1: Freeze the study protocol, diagnostic matrix, and preserved negative evidence

**Files:**
- Create: `configs/evaluation/e1-feasibility-study.v1.json`
- Create: `configs/evaluation/e1-feasibility-diagnostic-108.json`
- Create: `schemas/e1-feasibility-study-config.v1.json`
- Create: `scripts/export_e1_feasibility_matrix.py`
- Create: `docs/evaluation/negative-results/e1-v2-task4-report.raw.txt`
- Create: `docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt`
- Create: `src/manufacturing_vision_studio/e1/study_protocol_v2.py`
- Create: `tests/test_e1_feasibility_protocol_v2.py`

**Interfaces:**
- Produces: `StudyProtocolError` for bounded parse, schema, and semantic failures.
- Produces: `FrozenDiagnosticPlan` with fields `diagnostic_id`, `seed`, `combination`, `cad_revision`, `view_id`, `scale_delta`, `translation_x`, `translation_y`, `rotation_degrees`, `exposure_gain_delta`, `defect_type`, `defect_severity`, and `expected_feature_id`.
- Produces: `StudyProtocolV2` with properties `base_commit`, `configuration_sha256`, `diagnostic_matrix_sha256`, `artifact_root`, `raw_data_root`, `phase_1_modes`, `phase_1_limits`, `phase_2_counts`, and `source_hashes`.
- Produces: `DiagnosticGates(max_recall_drop: float, median_dice_drop: float, medium_high_recall: float)` and `DevelopmentGates(medium_high_recall: float, nuisance_fpr: float, median_dice: float, feature_accuracy: float)`.
- Produces: `load_study_protocol_v2(path: Path | str = DEFAULT_STUDY_PROTOCOL_PATH) -> StudyProtocolV2`.
- Produces: `load_frozen_diagnostic_matrix(path: Path | str = DEFAULT_DIAGNOSTIC_MATRIX_PATH) -> tuple[FrozenDiagnosticPlan, ...]`.
- Produces: `StudyProtocolV2.implementation_projection_paths() -> tuple[str, ...]`.
- Produces: `StudyProtocolV2.direct_import_allowlist() -> Mapping[str, tuple[str, ...]]`.
- Produces: `matrix_projection() -> list[dict[str, object]]` in the test/tool-only exporter.
- Test helpers: `walk_schema_nodes(value: object) -> Iterator[Mapping[str, object]]` recursively yields every mapping; `expand_declared_seed_blocks(blocks: Mapping[str, object]) -> set[int]` expands only declared start/count pairs.

- [ ] **Step 1: Write the failing protocol and snapshot-binding tests**

```python
def test_study_protocol_pins_base_commit_modes_and_hashes() -> None:
    protocol = load_study_protocol_v2()
    assert protocol.base_commit == "9fd6d0c600206083fde4fafc874e0226b5df60b3"
    assert protocol.phase_1_modes == ("NEAREST", "BILINEAR", "BICUBIC")
    assert protocol.phase_2_counts == {
        "clean": 24,
        "nuisance": 30,
        "defect": 60,
        "trust_boundary": 6,
        "total": 120,
    }
    assert protocol.source_hashes["candidate_a_raw_sha256"] == (
        "ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84"
    )
    assert protocol.source_hashes["candidate_b_raw_sha256"] == (
        "983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029"
    )
    assert protocol.source_hashes["selection_raw_sha256"] == (
        "92d3a2f86645a4d0fc33cfc39b769c6d2c4234383c7f132e803c449c7a66f2f3"
    )
    assert protocol.source_hashes["selection_record_sha256"] == (
        "3d4aa7e95240ed2bd4c018fb0762fdf788f919069cfbb935fd228de4b67dc2fe"
    )


def test_frozen_diagnostic_matrix_has_exact_ids_and_seed_block() -> None:
    matrix = load_frozen_diagnostic_matrix()
    assert len(matrix) == 108
    assert matrix[0].diagnostic_id == "e1-v2-development-diagnostic-000"
    assert matrix[-1].diagnostic_id == "e1-v2-development-diagnostic-107"
    assert tuple(plan.seed for plan in matrix[:3]) == (800000, 800001, 800002)
    assert {plan.seed for plan in matrix} == set(range(800000, 800108))


def test_frozen_matrix_matches_the_historical_builder_only_in_test_code() -> None:
    expected = matrix_projection()
    actual = [plan.as_record() for plan in load_frozen_diagnostic_matrix()]
    assert actual == expected


def test_diagnostic_seeds_do_not_overlap_any_declared_evaluation_block() -> None:
    e1 = load_e1_v2_protocol()
    diagnostic = {row.seed for row in load_frozen_diagnostic_matrix()}
    declared = expand_declared_seed_blocks(e1.document["generator"]["seed_blocks"])
    assert diagnostic.isdisjoint(declared)


def test_every_object_schema_is_closed() -> None:
    schema = json.loads(STUDY_SCHEMA_PATH.read_text())
    for node in walk_schema_nodes(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False


@pytest.mark.parametrize(
    "payload",
    [b'{"schema_version":"1.0.0","schema_version":"1.0.0"}', b'{"x":NaN}'],
)
def test_strict_loader_rejects_duplicate_and_nonfinite_json(
    tmp_path: Path, payload: bytes
) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(payload)
    with pytest.raises(StudyProtocolError):
        load_study_protocol_v2(path)
```

- [ ] **Step 2: Run the focused protocol test and record RED**

Run: `uv run pytest tests/test_e1_feasibility_protocol_v2.py -q`
Expected: FAIL because the study protocol loader, matrix snapshot, and negative-evidence snapshots do not exist.

- [ ] **Step 3: Implement the strict study protocol loader and matrix types**

```python
DEFAULT_STUDY_PROTOCOL_PATH = PROJECT_ROOT / "configs" / "evaluation" / "e1-feasibility-study.v1.json"
DEFAULT_DIAGNOSTIC_MATRIX_PATH = PROJECT_ROOT / "configs" / "evaluation" / "e1-feasibility-diagnostic-108.json"


@dataclass(frozen=True, slots=True)
class FrozenDiagnosticPlan:
    diagnostic_id: str
    seed: int
    combination: str
    cad_revision: CadRevision
    view_id: ViewId
    scale_delta: float
    translation_x: int
    translation_y: int
    rotation_degrees: float
    exposure_gain_delta: float
    defect_type: str | None
    defect_severity: str | None
    expected_feature_id: str | None


def load_study_protocol_v2(
    path: Path | str = DEFAULT_STUDY_PROTOCOL_PATH,
) -> StudyProtocolV2:
    return StudyProtocolV2.from_path(Path(path).expanduser().resolve())
```

The loader reads at most 4 MiB, rejects duplicate keys through an
`object_pairs_hook`, rejects `NaN`/`Infinity` through `parse_constant`, resolves
the local `$schema` under `PROJECT_ROOT`, validates with
`Draft202012Validator`, then enforces the semantic pins above. `document`
returns a deep defensive copy; all typed sequences are tuples and all mappings
are `MappingProxyType` instances.

- [ ] **Step 4: Add the immutable Task 4 raw snapshots and bind their hashes**

Copy the exact bytes from the fixed source worktree, then prove byte identity:

```bash
mkdir -p docs/evaluation/negative-results
cp /Users/jangtaeho/manufacturing-vision-studio-e1-v2/.superpowers/sdd/2026-08-01-e1-v2-scale-feature-remediation/task-4-report.md docs/evaluation/negative-results/e1-v2-task4-report.raw.txt
cp /Users/jangtaeho/manufacturing-vision-studio-e1-v2/.superpowers/sdd/2026-08-01-e1-v2-scale-feature-remediation/progress.md docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt
shasum -a 256 docs/evaluation/negative-results/e1-v2-task4-report.raw.txt docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt
```

Expected hashes, in order:

```text
b6a2093082aa63631adb233c282466539720281ab96b53bc3928cf292efc8835
fcef0c3b22b962f185911cc74bdad45f1bd2860c42ae8e59bac76d6741c13ea7
```

Store those digests, checked-in paths, and the original sibling paths as
provenance strings in the study config. Only the checked-in paths are runtime
inputs; the sibling paths are never dereferenced after this freeze step. The
loader recomputes the checked snapshot hashes and rejects drift.

- [ ] **Step 5: Freeze the exact 108 rows as checked data**

Implement the exporter so only this tool imports `e1.diagnostics_v2`:

```python
def matrix_projection() -> list[dict[str, object]]:
    protocol = load_e1_v2_protocol()
    return [
        {
            "diagnostic_id": row.diagnostic_id,
            "seed": row.seed,
            "combination": row.combination,
            "cad_revision": row.cad_revision.value,
            "view_id": row.view_id.value,
            **row.diagnostic_truth_record(),
        }
        for row in build_scale_diagnostic_matrix(protocol)
    ]
```

Give the exporter only `--write` and `--check`. `--write` serializes
`{"record_type":"e1_feasibility_diagnostic_matrix_v1","rows":matrix_projection()}`
with `canonical_json_bytes`; `--check` requires exact byte equality. Run:

```bash
uv run python scripts/export_e1_feasibility_matrix.py --write
uv run python scripts/export_e1_feasibility_matrix.py --check
```

The production loader rejects duplicates, out-of-order IDs, missing fields,
nonfinite values, wrong `48 + 5 * 12` combination counts, and any seed outside
`800000..800107`.

- [ ] **Step 6: Run the focused protocol test and snapshot hash checks**

Run: `uv run pytest tests/test_e1_feasibility_protocol_v2.py -q`
Expected: PASS with the exact 108-row sequence and the two raw snapshot hashes verified from checked files.

- [ ] **Step 7: Commit Task 1**

```bash
git add configs/evaluation/e1-feasibility-study.v1.json configs/evaluation/e1-feasibility-diagnostic-108.json schemas/e1-feasibility-study-config.v1.json scripts/export_e1_feasibility_matrix.py docs/evaluation/negative-results/e1-v2-task4-report.raw.txt docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt src/manufacturing_vision_studio/e1/study_protocol_v2.py tests/test_e1_feasibility_protocol_v2.py
git commit -m "feat(e1): freeze feasibility study protocol"
```

### Task 2: Implement known-transform normalization and the fixed reference-boundary band

**Files:**
- Create: `src/manufacturing_vision_studio/e1/known_transform_v2.py`
- Create: `tests/test_e1_known_transform_v2.py`

**Interfaces:**
- Produces: `ResamplingMode`, `AppliedAffineTransform`, `CorrectionAffineTransform`, `AffineCoefficients`, `StudyAlignmentObjective`, `ReferenceBoundaryBand`, `KnownTransformTrace`, and `KnownTransformResult`.
- Produces: `derive_correction(applied: AppliedAffineTransform) -> CorrectionAffineTransform`.
- Produces: `pillow_output_to_input_coefficients(image_size: tuple[int, int], correction: CorrectionAffineTransform) -> AffineCoefficients`.
- Produces: `normalize_known_transform(reference_bytes: bytes, inspection_bytes: bytes, *, reference_sha256: str, inspection_sha256: str, applied_transform: AppliedAffineTransform, resampling: ResamplingMode) -> KnownTransformResult`.
- Produces: `reference_boundary_band(reference_bytes: bytes) -> ReferenceBoundaryBand`.
- Produces: `measure_alignment(reference_bytes: bytes, inspection_bytes: bytes) -> StudyAlignmentObjective`.
- Test helpers: `asymmetric_png` is a canonical `512x384` RGB image with four unequal colored landmarks; `transformed_fixture` applies fixed scale/rotation/translation; `retained_geometry_objective()` is test-only and calls the three historical geometry primitives.

- [ ] **Step 1: Write failing inverse-math, parity, and boundary-band tests**

```python
def test_known_transform_uses_single_inverse_and_shared_fill() -> None:
    applied = AppliedAffineTransform(
        scale_factor=1.08,
        rotation_degrees=7.5,
        translation_x=9.0,
        translation_y=-4.0,
    )
    correction = derive_correction(applied)
    assert correction.scale == pytest.approx(1 / 1.08)
    assert correction.rotation_degrees == pytest.approx(-7.5)
    assert correction.dx != 0.0
    assert correction.dy != 0.0


def test_all_modes_share_coefficients_and_border_fill(asymmetric_png: bytes) -> None:
    results = tuple(
        normalize_known_transform(
            asymmetric_png,
            asymmetric_png,
            reference_sha256=sha256_bytes(asymmetric_png),
            inspection_sha256=sha256_bytes(asymmetric_png),
            applied_transform=AppliedAffineTransform(1.0, 0.0, 0.0, 0.0),
            resampling=mode,
        )
        for mode in ResamplingMode
    )
    assert len({result.trace.coefficients for result in results}) == 1
    assert len({result.trace.fill_rgb for result in results}) == 1


def test_reference_boundary_band_matches_frozen_three_pixel_rule() -> None:
    pixels = np.full((384, 512, 3), 240, dtype=np.uint8)
    pixels[40:340, 80:430] = 20
    reference = encode_png(Image.fromarray(pixels, mode="RGB"), mode="RGB")
    band = reference_boundary_band(reference)
    assert band.radius == 3
    assert band.boundary_positive_pixels > 0
    assert band.band_positive_pixels >= band.boundary_positive_pixels


def test_alignment_components_match_frozen_geometry_on_fixture(
    transformed_fixture: tuple[bytes, bytes],
) -> None:
    reference, inspection = transformed_fixture
    study = measure_alignment(reference, inspection)
    retained = retained_geometry_objective(reference, inspection)
    assert study.as_record() == retained.as_record()
```

- [ ] **Step 2: Run the focused normalizer test and record RED**

Run: `uv run pytest tests/test_e1_known_transform_v2.py -q`
Expected: FAIL because the known-transform module and helpers do not exist.

- [ ] **Step 3: Implement canonical validation, inverse math, and PNG normalization**

```python
@dataclass(frozen=True, slots=True)
class AppliedAffineTransform:
    scale_factor: float
    rotation_degrees: float
    translation_x: float
    translation_y: float


class ResamplingMode(StrEnum):
    NEAREST = "NEAREST"
    BILINEAR = "BILINEAR"
    BICUBIC = "BICUBIC"


@dataclass(frozen=True, slots=True)
class CorrectionAffineTransform:
    scale: float
    rotation_degrees: float
    dx: float
    dy: float


@dataclass(frozen=True, slots=True)
class AffineCoefficients:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float


@dataclass(frozen=True, slots=True)
class StudyAlignmentObjective:
    value: float
    silhouette_xor_rate: float
    normalized_edge_mae: float
    foreground_iou: float


@dataclass(frozen=True, slots=True)
class ReferenceBoundaryBand:
    radius: int
    foreground_positive_pixels: int
    boundary_positive_pixels: int
    band_positive_pixels: int
    band_mask_bytes: bytes
    band_mask_sha256: str


@dataclass(frozen=True, slots=True)
class KnownTransformTrace:
    applied_transform: AppliedAffineTransform
    correction: CorrectionAffineTransform
    coefficients: AffineCoefficients
    fill_rgb: tuple[int, int, int]
    resampling: ResamplingMode
    reference_sha256: str
    source_inspection_sha256: str
    normalized_sha256: str
    applied: bool
    objective_before: StudyAlignmentObjective
    objective_after: StudyAlignmentObjective


@dataclass(frozen=True, slots=True)
class KnownTransformResult:
    normalized_bytes: bytes
    normalized_sha256: str
    trace: KnownTransformTrace


def derive_correction(applied: AppliedAffineTransform) -> CorrectionAffineTransform:
    if not math.isfinite(applied.scale_factor) or applied.scale_factor <= 0:
        raise ValueError("scale_factor must be finite and positive")
    angle = math.radians(-applied.rotation_degrees)
    scale = 1.0 / applied.scale_factor
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    dx = -scale * (cos_angle * applied.translation_x - sin_angle * applied.translation_y)
    dy = -scale * (sin_angle * applied.translation_x + cos_angle * applied.translation_y)
    return CorrectionAffineTransform(scale=scale, rotation_degrees=-applied.rotation_degrees, dx=dx, dy=dy)
```

- [ ] **Step 4: Bind NEAREST parity to the frozen affine convention**

Implement the exact output-to-input coefficients once:

```python
def pillow_output_to_input_coefficients(
    image_size: tuple[int, int], correction: CorrectionAffineTransform
) -> AffineCoefficients:
    center_x = (image_size[0] - 1) / 2.0
    center_y = (image_size[1] - 1) / 2.0
    radians = math.radians(correction.rotation_degrees)
    cosine = math.cos(radians) / correction.scale
    sine = math.sin(radians) / correction.scale
    return AffineCoefficients(
        a=cosine,
        b=sine,
        c=center_x - cosine * (center_x + correction.dx) - sine * (center_y + correction.dy),
        d=-sine,
        e=cosine,
        f=center_y + sine * (center_x + correction.dx) - cosine * (center_y + correction.dy),
    )
```

Use that tuple directly in `Image.transform`; never invert it again. The test
imports `e1.geometry._inverse_affine` only from the test module and requires
NEAREST byte equality on asymmetric scale/rotation/translation fixtures. A
second fixture must fail if translation is applied before rotation or if the
correction is inverted twice.

- [ ] **Step 5: Implement canonical normalization and the frozen reference-boundary band**

Validate a maximum 8 MiB canonical one-frame `512x384` RGB PNG with empty
metadata and byte-identical `encode_png` re-encoding. Compute the fill from the
inspection border with corners once:

```python
border = np.concatenate(
    (pixels[0], pixels[-1], pixels[1:-1, 0], pixels[1:-1, -1]), axis=0
)
fill_rgb = tuple(int(value) for value in np.median(border, axis=0).astype(np.uint8))
```

Map the three enum values to `Image.Resampling.NEAREST`, `BILINEAR`, and
`BICUBIC`, encode the output with `encode_png`, and bind source/output hashes in
`KnownTransformTrace`. Set `trace.applied` only when the applied geometric
transform differs from `(1.0, 0.0, 0.0, 0.0)`.

For the reference boundary, use the same border reduction, foreground
`max(abs(pixel - median)) > 18`, the largest 8-connected component sorted by
`(-area, min_y, min_x, max_y, max_x)`, outside-image neighbors as background,
and Chebyshev dilation radius 3 clipped to image bounds. Raise on a missing
component. `ReferenceBoundaryBand` stores the immutable boolean band plus its
SHA-256 and positive-pixel count; row artifacts compute
`outside_boundary_residual = total_residual - boundary_residual`.

Study-own the retained silhouette objective without importing `e1.geometry`:
largest 8-connected foreground with threshold 18, 8-neighbor silhouette edges,
silhouette XOR rate, normalized edge MAE, foreground IoU, and value
`0.70 * xor_rate + 0.30 * edge_mae`. `KnownTransformTrace` records complete
pre- and post-normalization objectives. The test-only parity helper imports
`largest_component_silhouette`, `silhouette_edges`, and `alignment_objective`
from the historical geometry module and requires exact component equality.

- [ ] **Step 6: Run focused parity tests**

Run: `uv run pytest tests/test_e1_known_transform_v2.py -q`
Expected: PASS, including NEAREST parity, shared fill parity across all three modes, and exact 3-pixel boundary-band counts.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/manufacturing_vision_studio/e1/known_transform_v2.py tests/test_e1_known_transform_v2.py
git commit -m "feat(e1): add known-transform study normalizer"
```

### Task 3: Build the truth-free inference adapter and parity-bind it to the retained runtime pipeline

**Files:**
- Create: `src/manufacturing_vision_studio/e1/study_inference_v2.py`
- Create: `tests/test_e1_study_inference_v2.py`
- Create: `tests/test_e1_study_parity_v2.py`

**Interfaces:**
- Consumes: `StudyProtocolV2`, `E1V2Protocol`, and `KnownTransformResult`.
- Produces: `StudyInferenceInput`, `StudyModelRegistration`, `StudyInferenceResult`, and `StudyInferenceAdapter`.
- Produces: `StudyInferenceAdapter.inspect(inference: StudyInferenceInput) -> StudyInferenceResult`.
- Produces: `classify_study_score(score: float, threshold: float) -> Literal["NORMAL", "ANOMALY"]`.
- Test helpers: `SourceFixture` contains source bytes/hashes plus a `KnownTransformResult`; `AdapterSpies` contains the adapter and captured registered/postfilter/mapping values. Both are defined in `tests/test_e1_study_inference_v2.py` from the fixed asymmetric fixture.

- [ ] **Step 1: Write failing truth-free signature and source-binding tests**

```python
def test_study_inference_input_has_only_truth_free_fields() -> None:
    assert {field.name for field in dataclasses.fields(StudyInferenceInput)} == {
        "reference_bytes",
        "inspection_bytes",
        "reference_sha256",
        "inspection_sha256",
        "part_id",
        "cad_revision",
        "view_id",
        "normalized",
    }


def test_study_input_rejects_a_normalizer_result_from_another_source(
    source_fixture: SourceFixture,
) -> None:
    normalized = source_fixture.normalized
    with pytest.raises(ValueError, match="source inspection hash"):
        StudyInferenceInput(
            reference_bytes=source_fixture.reference_bytes,
            inspection_bytes=source_fixture.inspection_bytes + b"changed",
            reference_sha256=source_fixture.reference_sha256,
            inspection_sha256=sha256_bytes(source_fixture.inspection_bytes + b"changed"),
            part_id="mvs-e1-bracket",
            cad_revision=CadRevision.REV_A,
            view_id=ViewId.FRONT,
            normalized=normalized,
        )
```

- [ ] **Step 2: Run the focused inference tests and record RED**

Run: `uv run pytest tests/test_e1_study_inference_v2.py -q`
Expected: FAIL because `study_inference_v2` does not exist.

- [ ] **Step 3: Implement immutable input/result types and cross-binding**

```python
@dataclass(frozen=True, slots=True)
class StudyInferenceInput:
    reference_bytes: bytes
    inspection_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    part_id: str
    cad_revision: CadRevision
    view_id: ViewId
    normalized: KnownTransformResult

    def __post_init__(self) -> None:
        if not self.part_id:
            raise ValueError("part_id is required")
        validate_canonical_rgb_png(
            self.reference_bytes, self.reference_sha256, label="reference"
        )
        validate_canonical_rgb_png(
            self.inspection_bytes, self.inspection_sha256, label="inspection"
        )
        if self.normalized.trace.reference_sha256 != self.reference_sha256:
            raise ValueError("normalizer reference hash does not match input")
        if self.normalized.trace.source_inspection_sha256 != self.inspection_sha256:
            raise ValueError("normalizer source inspection hash does not match input")
        if sha256_bytes(self.normalized.normalized_bytes) != self.normalized.normalized_sha256:
            raise ValueError("normalized output hash does not match bytes")


@dataclass(frozen=True, slots=True)
class StudyModelRegistration:
    dx: int
    dy: int
    mean_absolute_error: float


@dataclass(frozen=True, slots=True)
class StudyInferenceResult:
    actual_outcome: Literal["NORMAL", "ANOMALY"]
    anomaly_score: float
    global_anomaly_score: float
    predicted_mask_bytes: bytes
    predicted_mask_sha256: str
    registered_inspection_sha256: str
    feature_mapping: FeatureMappingResult
    model_registration: StudyModelRegistration
    mask_postprocessing: MaskPostprocessing
    transform_trace: KnownTransformTrace
    source_hashes: Mapping[str, str]
```

Use `MappingProxyType` for `source_hashes`. `as_record()` must return fresh,
sorted dictionaries. Do not add `from_generated`; no generated case, seed,
case ID, nuisance metadata, expected label, or authoritative mask may enter this
module.

- [ ] **Step 4: Write failing pipeline-order, threshold, and parity tests**

```python
def test_adapter_uses_registered_bytes_then_final_mask(
    adapter_spies: AdapterSpies, inference: StudyInferenceInput
) -> None:
    result = adapter_spies.adapter.inspect(inference)
    assert adapter_spies.postfilter_inspection == adapter_spies.model_registered_bytes
    assert adapter_spies.mapping_mask == result.predicted_mask_bytes
    assert adapter_spies.normalization_applied is inference.normalized.trace.applied


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.002499999, "NORMAL"), (0.0025, "ANOMALY")],
)
def test_threshold_is_inclusive(score: float, expected: str) -> None:
    assert classify_study_score(score, 0.0025) == expected
```

Run: `uv run pytest tests/test_e1_study_inference_v2.py -q`
Expected: FAIL because the adapter pipeline has not been implemented.

- [ ] **Step 5: Implement the retained downstream composition without candidate alignment**

```python
class StudyInferenceAdapter:
    def __init__(
        self,
        study_protocol: StudyProtocolV2,
        e1_protocol: E1V2Protocol,
        *,
        model: DeterministicDifferenceModel | None = None,
        ingestor: ImageIngestor | None = None,
    ) -> None:
        self.study_protocol = study_protocol
        self.e1_protocol = e1_protocol
        self.model = model or DeterministicDifferenceModel(ModelConfig())
        self.ingestor = ingestor or ImageIngestor()

    def inspect(self, inference: StudyInferenceInput) -> StudyInferenceResult:
        reference = self.ingestor.ingest_bytes(
            inference.reference_bytes,
            filename="e1-study-reference.png",
            declared_media_type="image/png",
        )
        inspection = self.ingestor.ingest_bytes(
            inference.normalized.normalized_bytes,
            filename="e1-study-inspection.png",
            declared_media_type="image/png",
        )
        model_result = self.model.inspect(reference, inspection)
        postprocessing = filter_structural_residue(
            model_result.mask_bytes,
            reference_bytes=inference.reference_bytes,
            inspection_bytes=model_result.registered_bytes,
            normalization_applied=inference.normalized.trace.applied,
        )
        ownership = build_ownership_map(
            self.e1_protocol.feature_ownership(
                inference.cad_revision, inference.view_id
            ),
            (512, 384),
        )
        mapping = map_final_mask(postprocessing.mask_bytes, ownership)
        score = localized_anomaly_score(postprocessing.mask_bytes)
        return build_study_result(
            inference=inference,
            model_result=model_result,
            postprocessing=postprocessing,
            feature_mapping=mapping,
            actual_outcome=classify_study_score(score, 0.0025),
            anomaly_score=score,
        )
```

`build_study_result()` fills every `StudyInferenceResult` field, including model
registration and three source hashes. Do not catch decode, model, mapping, or
postfilter exceptions; the runner classifies them as study-integrity failures.

- [ ] **Step 6: Add test-only parity against the forbidden historical policy**

In `tests/test_e1_study_parity_v2.py`, import `e1.policy_v2`, monkeypatch
`E1V2InferencePolicy._align` to return the exact normalized bytes, and compare
mask bytes/hash, registered hash, postprocessing record, feature-mapping record,
localized score, and outcome. Also inspect the production module AST and prove
it does not import `policy_v2`, `geometry`, `geometry_search`, or
`diagnostics_v2`.

Run: `uv run pytest tests/test_e1_study_inference_v2.py tests/test_e1_study_parity_v2.py -q`
Expected: PASS with identical downstream outputs and no truth-bearing runtime
surface.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/manufacturing_vision_studio/e1/study_inference_v2.py tests/test_e1_study_inference_v2.py tests/test_e1_study_parity_v2.py
git commit -m "feat(e1): add truth-free study inference adapter"
```

### Task 4: Build the complete offline truth, metric, transform-proof, and feature-oracle layer

**Files:**
- Create: `src/manufacturing_vision_studio/e1/study_truth_v2.py`
- Create: `tests/test_e1_study_truth_v2.py`

**Interfaces:**
- Produces: `StudyTruthCase`, `DiagnosticObservation`, `DiagnosticModeSummary`, `DevelopmentCorpus`, `DevelopmentCorpusProvider`, `AppliedTransformProof`, `FeatureOracleResult`, and `DevelopmentModeSummary`.
- Produces: `render_diagnostic(plan: FrozenDiagnosticPlan, study_protocol: StudyProtocolV2, e1_protocol: E1V2Protocol) -> StudyTruthCase`.
- Produces: `prove_applied_transform(generated: E1V2GeneratedCase) -> AppliedTransformProof`.
- Produces: `DevelopmentCorpusProvider.load() -> DevelopmentCorpus`.
- Produces: `make_truth_free_input(case: StudyTruthCase, normalized: KnownTransformResult) -> StudyInferenceInput`.
- Produces: `observation_from_study(case: StudyTruthCase, result: StudyInferenceResult) -> E1V2EvaluationObservation`.
- Produces: `raw_identity_difference_mask(case: StudyTruthCase) -> bytes`.
- Produces: `diagnostic_observation(case: StudyTruthCase, result: StudyInferenceResult, identity_mask_bytes: bytes, boundary: ReferenceBoundaryBand) -> DiagnosticObservation`.
- Produces: `reduce_diagnostic_mode(mode: ResamplingMode, rows: Sequence[DiagnosticObservation], gates: DiagnosticGates) -> DiagnosticModeSummary`.
- Produces: `run_feature_ownership_oracle(corpus: DevelopmentCorpus, protocol: E1V2Protocol) -> FeatureOracleResult`.
- Produces: `reduce_development_mode(observations: Sequence[E1V2EvaluationObservation], gates: DevelopmentGates) -> DevelopmentModeSummary`.
- Test helpers: `complete_mode_rows` fabricates exactly 108 `DiagnosticObservation` values with 24 defect/medium-high rows; `decode_rgb` and `decode_mask` strictly decode canonical test images.

- [ ] **Step 1: Write failing diagnostic-render, development-binding, and oracle tests**

```python
def test_development_provider_requests_only_literal_development_scope() -> None:
    corpus = DevelopmentCorpusProvider(load_e1_v2_protocol()).load()
    assert corpus.scope_projection == ("development",)
    assert corpus.external_request_count == 1
    assert corpus.counts == {"clean": 24, "nuisance": 30, "defect": 60, "trust_boundary": 6, "total": 120}


def test_feature_oracle_requires_exact_target_feature_agreement() -> None:
    e1_protocol = load_e1_v2_protocol()
    corpus = DevelopmentCorpusProvider(e1_protocol).load()
    oracle = run_feature_ownership_oracle(corpus, e1_protocol)
    assert oracle.passed is True
    assert oracle.correct_cases == 60
    assert oracle.ambiguous_cases == 0


def test_identity_comparator_is_raw_rgb_threshold_not_an_inference_pass(
    diagnostic_case: StudyTruthCase,
) -> None:
    mask = decode_mask(raw_identity_difference_mask(diagnostic_case))
    reference = decode_rgb(diagnostic_case.reference_bytes).astype(np.int16)
    inspection = decode_rgb(diagnostic_case.inspection_bytes).astype(np.int16)
    assert np.array_equal(mask, np.max(np.abs(reference - inspection), axis=2) >= 32)


def test_diagnostic_reducer_uses_exact_defect_denominators(
    complete_mode_rows: tuple[DiagnosticObservation, ...],
) -> None:
    summary = reduce_diagnostic_mode(
        ResamplingMode.NEAREST,
        complete_mode_rows,
        DiagnosticGates(0.05, 0.01, 0.90),
    )
    assert summary.row_count == 108
    assert summary.defect_drop_denominator == 24
    assert summary.medium_high_classification_denominator == 24
```

- [ ] **Step 2: Run the focused truth/oracle test and record RED**

Run: `uv run pytest tests/test_e1_study_truth_v2.py -q`
Expected: FAIL because the offline truth layer and development provider do not exist.

- [ ] **Step 3: Implement diagnostic rendering and truth-free input conversion**

```python
@dataclass(frozen=True, slots=True)
class StudyTruthCase:
    case_id: str
    seed: int
    group: str
    expected_outcome: str
    part_id: str
    cad_revision: str
    view_id: str
    reference_bytes: bytes
    inspection_bytes: bytes
    authoritative_mask_bytes: bytes
    reference_sha256: str
    inspection_sha256: str
    authoritative_mask_sha256: str
    applied_transform: AppliedAffineTransform
    defect_type: str | None
    defect_severity: str | None
    expected_feature_id: str | None
    nuisance_types: tuple[str, ...]
    case_binding_sha256: str | None
    trust_boundary: bool = False


@dataclass(frozen=True, slots=True)
class DiagnosticObservation:
    diagnostic_id: str
    seed: int
    mode: ResamplingMode
    defect_row: bool
    medium_high_row: bool
    actual_outcome: str
    identity_recall: float
    study_recall: float
    identity_dice: float
    study_dice: float
    study_iou: float
    total_residual: int
    boundary_residual: int
    outside_boundary_residual: int
    record: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DiagnosticModeSummary:
    mode: ResamplingMode
    row_count: int
    defect_drop_denominator: int
    medium_high_classification_denominator: int
    maximum_recall_drop: float
    median_dice_drop: float
    medium_high_classification_recall: float
    eligible: bool


@dataclass(frozen=True, slots=True)
class DevelopmentCorpus:
    cases: tuple[StudyTruthCase, ...]
    counts: Mapping[str, int]
    scope_projection: tuple[str, ...]
    external_request_count: int
    internal_membership_validation_count: int


@dataclass(frozen=True, slots=True)
class AppliedTransformProof:
    case_id: str
    applied_transform: AppliedAffineTransform
    replay_sha256: str
    inspection_sha256: str
    replay_matches: bool


@dataclass(frozen=True, slots=True)
class FeatureOracleResult:
    case_count: int
    correct_cases: int
    ambiguous_cases: int
    null_cases: int
    wrong_cases: int
    ownership_hashes: Mapping[str, str]
    records: tuple[Mapping[str, object], ...]
    passed: bool


@dataclass(frozen=True, slots=True)
class DevelopmentModeSummary:
    mode: ResamplingMode
    member_count: int
    inference_count: int
    trust_binding_count: int
    medium_high_recall: float
    nuisance_false_positive_rate: float
    positive_median_dice: float
    feature_mapping_accuracy: float
    passed_all_gates: bool


def make_truth_free_input(
    case: StudyTruthCase,
    normalized: KnownTransformResult,
) -> StudyInferenceInput:
    return StudyInferenceInput(
        reference_bytes=case.reference_bytes,
        inspection_bytes=case.inspection_bytes,
        reference_sha256=case.reference_sha256,
        inspection_sha256=case.inspection_sha256,
        part_id=case.part_id,
        cad_revision=CadRevision(case.cad_revision),
        view_id=ViewId(case.view_id),
        normalized=normalized,
)
```

`render_diagnostic()` copies the retained diagnostic renderer into this offline
layer: choose the same v1 FULL template by revision/view, render pristine
reference, render optional defect truth, then apply scale, rotation,
translation, and exposure in that order. Only the parity test imports
`build_scale_diagnostic_matrix` and the historical renderer; the production
study reads `FrozenDiagnosticPlan` rows only.

- [ ] **Step 4: Implement `DevelopmentCorpusProvider` with one literal external scope request**

The provider has no scope argument and is the only production wrapper around
`E1V2Generator`:

```python
class DevelopmentCorpusProvider:
    def __init__(self, protocol: E1V2Protocol) -> None:
        self.protocol = protocol
        self._generator = E1V2Generator(protocol)
        self._cached: DevelopmentCorpus | None = None

    def load(self) -> DevelopmentCorpus:
        if self._cached is not None:
            return self._cached
        plans = self._generator.plan_cases(EvaluationScope.DEVELOPMENT)
        generated = tuple(self._generator.generate_case(plan) for plan in plans)
        self._cached = validate_development_corpus(
            generated,
            external_scope_projection=(EvaluationScope.DEVELOPMENT.value,),
            external_request_count=1,
        )
        return self._cached
```

`validate_development_corpus()` requires ordered groups `24/30/60/6`, total
120, unique IDs/seeds/bindings, scope `development` on every member, and no
protected emission. Instrumented tests record 120 internal membership
revalidation calls in addition to the one external request; all must still be
development-only. A dynamic test replaces calibration/release planning and
rendering with hard failures.

- [ ] **Step 5: Prove the applied transform from generator-owned data**

Read magnitudes from the preserved v1 nuisance specifications but derive signs
from the replaced v2 render seed:

```python
def applied_affine_from_plan(plan: E1V2CasePlan) -> AppliedAffineTransform:
    scale_factor = 1.0
    rotation_degrees = 0.0
    translation_x = 0.0
    translation_y = 0.0
    for nuisance in plan._render_plan.nuisances:
        values = {item.name: float(item.value) for item in nuisance.parameters}
        if nuisance.nuisance_type is NuisanceType.SCALE:
            delta = values["max_abs_scale_delta"]
            scale_factor = 1 + delta if _digest_bit(plan.seed, "scale-sign") else 1 - delta
        elif nuisance.nuisance_type is NuisanceType.ROTATION:
            magnitude = values["max_abs_rotation"]
            rotation_degrees = (
                magnitude if _digest_bit(plan.seed, "rotation-sign") else -magnitude
            )
        elif nuisance.nuisance_type is NuisanceType.TRANSLATION:
            magnitude = round(values["max_abs_shift"])
            translation_x = magnitude if _digest_bit(plan.seed, "translation-x-sign") else -magnitude
            half = max(1, magnitude // 2)
            translation_y = half if _digest_bit(plan.seed, "translation-y-sign") else -half
    return AppliedAffineTransform(
        scale_factor, rotation_degrees, translation_x, translation_y
    )
```

`prove_applied_transform()` recreates the pristine render, replays every
nuisance—geometric and nongeometric—in stored order through `_apply_nuisance`,
canonical-encodes it, and requires byte/hash equality with the generated
inspection. Recompute neither magnitude nor recipe values from the v2 ID.
Clean, defect, and trust rows receive explicit identity geometry. Trust rows
remain binding-only and never enter `StudyInferenceAdapter`.

- [ ] **Step 6: Join truth only after inference and run the oracle on authoritative masks**

Implement the raw comparator independently of normalization and the model:

```python
def raw_identity_difference_mask(case: StudyTruthCase) -> bytes:
    reference = decode_canonical_rgb(case.reference_bytes).astype(np.int16)
    inspection = decode_canonical_rgb(case.inspection_bytes).astype(np.int16)
    mask = np.max(np.abs(reference - inspection), axis=2) >= 32
    return encode_png(
        Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L"),
        mode="L",
    )
```

`diagnostic_observation()` joins truth only after inference, computes identity
and final-mask recall/Dice/IoU with empty denominators equal to `1.0`, and
records total, inside-boundary, and outside-boundary predicted positives.
`reduce_diagnostic_mode()` requires 108 unique complete rows, takes recall and
Dice drops over exactly 24 defect rows, takes classification recall over those
24 medium/high rows, and applies `<=0.05`, `<=0.01`, and `>=0.90` independently
per mode. It never ranks modes.

`observation_from_study()` constructs `E1V2EvaluationObservation` locally after
`StudyInferenceAdapter.inspect()` returns; do not call the historical
`observation_from_case` adapter. `reduce_development_mode()` delegates the four
mathematical reductions to `evaluate_v2_metrics()` and requires denominators
30 nuisance, 40 medium/high, 60 positive Dice, and 60 known-feature positives
before applying `<=0.05`, `>=0.90`, `>=0.70`, and `>=0.95`.

For the feature oracle, send only each of the 60 authoritative masks into:

```python
mapping = map_final_mask(
    generated.authoritative_mask_bytes,
    ownership,
    minimum_winner_pixels=8,
    ambiguity_margin=0.10,
)
```

Require the predicted owner to equal the generator target, target-owned pixels
at least 8, `owned + unmapped == authoritative positives`, and zero
null/ambiguous/wrong cases. Bind all six exact ownership hashes from
`tests/test_e1_v2_feature_mapping.py` into the study config and oracle result.

- [ ] **Step 7: Run focused truth/oracle tests**

Run: `uv run pytest tests/test_e1_study_truth_v2.py -q`
Expected: PASS with sampled diagnostic-render parity at ordinals
`0,48,60,72,84,96`, exact identity-comparator parity, exact `24/30/60/6`
development counts, one literal external request, byte-exact replay across all
nine nuisance families, exact diagnostic/development denominators, and oracle
pass on all 60 defect cases.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/manufacturing_vision_studio/e1/study_truth_v2.py tests/test_e1_study_truth_v2.py
git commit -m "feat(e1): add study truth and oracle layer"
```

### Task 5: Add canonical study artifacts, execution claims, and artifact verification

**Files:**
- Create: `schemas/e1-feasibility-study-artifact.v1.json`
- Create: `src/manufacturing_vision_studio/e1/study_artifacts_v2.py`
- Create: `tests/test_e1_study_artifacts_v2.py`

**Interfaces:**
- Produces: `StudyArtifactStore`, `StudyArtifactRecord`, `StudyGateRecord`, and `ExecutionClaim`.
- Produces: `StudyArtifactStore.publish_json(relative_path: str, document: Mapping[str, object]) -> StudyArtifactRecord` with no replacement option.
- Produces: `StudyArtifactStore.publish_bytes(relative_path: str, payload: bytes, *, media_type: str) -> StudyArtifactRecord` with no replacement option.
- Produces: `begin_phase_execution(*, phase: Literal["phase1", "phase2"], protocol: StudyProtocolV2, execution_commit: str, eligible_modes: tuple[str, ...]) -> ExecutionClaim`.
- Produces: `StudyArtifactStore.verify_json(relative_path: str, *, expected_record_type: str) -> dict[str, object]`.
- Test helper: `minimal_valid_study_record()` returns a complete closed-envelope validation record with zeroed-but-valid SHA fields before finalization.

- [ ] **Step 1: Write failing artifact-canonicalization and claim-immutability tests**

```python
def test_execution_claim_blocks_rerun_under_same_protocol_and_root(tmp_path: Path) -> None:
    store = StudyArtifactStore(tmp_path)
    claim = begin_phase_execution(
        phase="phase1",
        protocol=load_study_protocol_v2(),
        execution_commit="a" * 40,
        eligible_modes=(),
    )
    assert claim.expected_mode_count == 3
    store.publish_json("phase-1-execution-claim.json", claim.as_record())
    with pytest.raises(StudyArtifactError, match="immutable"):
        store.publish_json("phase-1-execution-claim.json", claim.as_record())


def test_not_applicable_gate_is_never_serialized_as_pass() -> None:
    gate = StudyGateRecord(
        name="bundle_verify_reimport_rate",
        status="NOT_APPLICABLE",
        numerator=None,
        denominator=None,
        observed=None,
        operator=None,
        threshold=None,
        reason="STUDY_PUBLISHES_NO_BUNDLE",
    )
    assert gate.status == "NOT_APPLICABLE"
    assert gate.observed is None


def test_canonical_study_json_has_no_trailing_newline(tmp_path: Path) -> None:
    store = StudyArtifactStore(tmp_path, allowed_root=tmp_path)
    record = store.publish_json("record.json", minimal_valid_study_record())
    payload = (tmp_path / record.path).read_bytes()
    assert payload == canonical_json_bytes(json.loads(payload))
    assert not payload.endswith(b"\n")
```

- [ ] **Step 2: Run the focused artifact test and record RED**

Run: `uv run pytest tests/test_e1_study_artifacts_v2.py -q`
Expected: FAIL because the study artifact store and claim types do not exist.

- [ ] **Step 3: Implement the study artifact store with exclusive-create writes**

```python
class StudyArtifactError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StudyArtifactRecord:
    path: str
    sha256: str
    byte_size: int
    media_type: str
    record_sha256: str | None


@dataclass(frozen=True, slots=True)
class StudyGateRecord:
    name: str
    status: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    numerator: int | None
    denominator: int | None
    observed: float | int | bool | str | None
    operator: Literal["ge", "le", "eq"] | None
    threshold: float | int | bool | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.status == "NOT_APPLICABLE" and any(
            value is not None
            for value in (self.numerator, self.denominator, self.observed, self.operator, self.threshold)
        ):
            raise ValueError("NOT_APPLICABLE gate cannot carry a passing observation")
        if self.status == "NOT_APPLICABLE" and not self.reason:
            raise ValueError("NOT_APPLICABLE gate requires a fixed reason")
        if self.status in {"PASS", "FAIL"} and (
            self.observed is None or self.operator is None or self.threshold is None
        ):
            raise ValueError("applicable gate requires observed/operator/threshold")


class StudyArtifactStore:
    def __init__(self, root: Path, *, allowed_root: Path | None = None) -> None:
        requested_root = root.expanduser().resolve()
        requested_allowed = (allowed_root or root).expanduser().resolve()
        if not requested_root.is_relative_to(requested_allowed):
            raise StudyArtifactError("artifact root escapes allowed root")
        requested_root.mkdir(parents=True, exist_ok=True)
        self.root = requested_root
        self.allowed_root = requested_allowed

    def publish_json(
        self, relative_path: str, document: Mapping[str, object]
    ) -> StudyArtifactRecord:
        finalized = finalize_study_record(document)
        validate_study_schema(finalized)
        payload = canonical_json_bytes(finalized)
        return self.publish_bytes(
            relative_path, payload, media_type="application/json"
        )
```

`publish_bytes()` validates a normalized relative path, rejects symlinks and
size-limit violations, writes and fsyncs a same-directory temporary file, then
uses `os.link(..., follow_symlinks=False)` for atomic no-overwrite publication.
It always removes only its own validated temporary name. There is no `replace`
parameter anywhere in the public study surface.

- [ ] **Step 4: Add self-hash, upstream-hash, and canonical verification helpers**

Every JSON record uses this common envelope:

```python
def finalize_study_record(document: Mapping[str, object]) -> dict[str, object]:
    finalized = deepcopy(dict(document))
    finalized.pop("record_sha256", None)
    finalized["record_sha256"] = canonical_json_hash(finalized)
    return finalized
```

Required envelope fields are `record_type`, `schema_version`, `study_id`,
`development_only=true`, `selection_eligible=false`,
`release_claim_allowed=false`, base SHA, execution SHA, protocol/config/schema
hashes, implementation projection hash, upstream artifact raw/self hashes,
payload, and `record_sha256`. Store exactly `canonical_json_bytes(finalized)`
with no newline. The bounded reader rejects duplicate keys, nonfinite values,
noncanonical bytes, mismatched self-hash, wrong closed schema variant, and any
upstream mismatch. The common schema has closed variants for implementation
validation, retention, scope, execution claim, diagnostic, oracle, development,
and decision records.

Diagnostic and development variants additionally require Python, NumPy, and
Pillow versions; exact case/seed/source/mask hashes; transform and resampling
trace; metric numerators/denominators/exclusions; upstream raw/self hashes; and
the three fixed eligibility booleans. Decision verification recomputes
`study_artifact_verify_rate = verified_present_artifacts / present_artifacts`
and requires exactly `1.0` before any performance conclusion.

- [ ] **Step 5: Encode Phase 1 and Phase 2 execution claims exactly**

Phase 1 claim fields must bind execution commit, protocol hash, artifact root, phase name, expected rows `108`, expected modes `("NEAREST", "BILINEAR", "BICUBIC")`, and expected mode count `3`. Phase 2 claim fields must additionally bind total members `120`, inference rows per eligible mode `114`, trust binding rows `6`, and the exact eligible-mode tuple.

```python
@dataclass(frozen=True, slots=True)
class ExecutionClaim:
    phase: Literal["phase1", "phase2"]
    execution_commit: str
    protocol_sha256: str
    artifact_root: str
    expected_members: int
    expected_modes: tuple[str, ...]
    expected_mode_count: int
    expected_inference_rows_per_mode: int
    trust_binding_rows: int


def begin_phase_execution(
    *,
    phase: Literal["phase1", "phase2"],
    protocol: StudyProtocolV2,
    execution_commit: str,
    eligible_modes: tuple[str, ...],
) -> ExecutionClaim:
    return ExecutionClaim(
        phase=phase,
        execution_commit=execution_commit,
        protocol_sha256=protocol.configuration_sha256,
        artifact_root=protocol.artifact_root.as_posix(),
        expected_members=108 if phase == "phase1" else 120,
        expected_modes=("NEAREST", "BILINEAR", "BICUBIC")
        if phase == "phase1"
        else eligible_modes,
        expected_mode_count=3 if phase == "phase1" else len(eligible_modes),
        expected_inference_rows_per_mode=108 if phase == "phase1" else 114,
        trust_binding_rows=0 if phase == "phase1" else 6,
    )
```

`ExecutionClaim.as_record()` emits the common artifact envelope with a
`phase_execution_claim` payload; `finalize_study_record()` adds its self-hash.

- [ ] **Step 6: Run focused artifact tests**

Run: `uv run pytest tests/test_e1_study_artifacts_v2.py -q`
Expected: PASS with exclusive-create semantics, path traversal/symlink rejection,
bounded reads/writes, duplicate/nonfinite rejection, closed-schema validation,
self/upstream tamper rejection, canonical byte verification, and explicit
`NOT_APPLICABLE` gate serialization.

- [ ] **Step 7: Commit Task 5**

```bash
git add schemas/e1-feasibility-study-artifact.v1.json src/manufacturing_vision_studio/e1/study_artifacts_v2.py tests/test_e1_study_artifacts_v2.py
git commit -m "feat(e1): add feasibility study artifact layer"
```

### Task 6: Implement Phase 0 retention, portable evidence capture, and dependency closure

**Files:**
- Create: `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Create: `tests/test_e1_study_retention_v2.py`
- Create: `tests/test_e1_study_dependency_guard_v2.py`

**Interfaces:**
- Consumes: `StudyProtocolV2`, `StudyArtifactStore`, the checked selection JSON, Candidate A/B raw JSON, the two Task 4 snapshots, and `verify_e1_v1_history()`.
- Produces: `ProjectionEntry`, `DependencyEdge`, `DependencyScanReport`, `HistoricalHoldAudit`, and `RetentionAudit`.
- Produces: `build_study_implementation_projection(protocol: StudyProtocolV2, *, repo_root: Path = PROJECT_ROOT) -> tuple[ProjectionEntry, ...]`.
- Produces: `scan_study_dependencies(protocol: StudyProtocolV2, *, repo_root: Path = PROJECT_ROOT) -> DependencyScanReport`.
- Produces: `verify_historical_hold(protocol: StudyProtocolV2, *, repo_root: Path = PROJECT_ROOT) -> HistoricalHoldAudit`.
- Produces: `run_retention_audit(protocol: StudyProtocolV2, store: StudyArtifactStore, *, execution_commit: str) -> RetentionAudit`.
- Produces: `verify_retention_audit(protocol: StudyProtocolV2, store: StudyArtifactStore) -> RetentionAudit`.
- Test helper: `RetentionFixture` owns a temp repo-shaped root, fixed test protocol, `StudyArtifactStore`, clean synthetic execution commit, validation record, selection record, and four source files with matching pinned hashes.

```python
@dataclass(frozen=True, slots=True)
class ProjectionEntry:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    source: str
    target: str
    kind: Literal["direct", "runtime_transitive", "type_checking"]


@dataclass(frozen=True, slots=True)
class DependencyScanReport:
    edges: tuple[DependencyEdge, ...]
    forbidden_direct_edges: tuple[DependencyEdge, ...]
    protected_scope_references: tuple[str, ...]
    projection_sha256: str


@dataclass(frozen=True, slots=True)
class HistoricalHoldAudit:
    selection_raw_sha256: str
    selection_record_sha256: str
    outcome: str
    selected_candidate_id: None
    v1_history_outcome: str


@dataclass(frozen=True, slots=True)
class RetainedInputRecord:
    name: str
    path: str
    source_sha256: str
    copied_sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class RetentionAudit:
    execution_commit: str
    history: HistoricalHoldAudit
    retained_inputs: tuple[RetainedInputRecord, ...]
    implementation_projection: tuple[ProjectionEntry, ...]
    dependency_report: DependencyScanReport
    passed: bool
```

- [ ] **Step 1: Write failing HOLD, source-hash, and portable-copy tests**

```python
def test_historical_selection_is_parsed_without_candidate_code() -> None:
    protocol = load_study_protocol_v2()
    audit = verify_historical_hold(protocol)
    assert audit.selection_raw_sha256 == (
        "92d3a2f86645a4d0fc33cfc39b769c6d2c4234383c7f132e803c449c7a66f2f3"
    )
    assert audit.selection_record_sha256 == (
        "3d4aa7e95240ed2bd4c018fb0762fdf788f919069cfbb935fd228de4b67dc2fe"
    )
    assert audit.outcome == "HOLD"
    assert audit.selected_candidate_id is None


def test_phase0_copies_all_four_raw_inputs_without_rerunning_candidates(
    retention_fixture: RetentionFixture,
) -> None:
    audit = run_retention_audit(
        retention_fixture.protocol,
        retention_fixture.store,
        execution_commit=retention_fixture.execution_commit,
    )
    assert tuple(item.path for item in audit.retained_inputs) == (
        "retained-inputs/candidate-a.json",
        "retained-inputs/candidate-b.json",
        "retained-inputs/task-4-report.md",
        "retained-inputs/sdd-progress.md",
    )
    assert all(item.source_sha256 == item.copied_sha256 for item in audit.retained_inputs)
```

Run: `uv run pytest tests/test_e1_study_retention_v2.py -q`
Expected: FAIL because the retention module does not exist.

- [ ] **Step 2: Implement an independent strict historical HOLD verifier**

Read `configs/evaluation/e1-v2-candidate-selection.json` with the bounded strict
JSON reader, validate `schemas/e1-candidate-selection.v2.json`, recompute its
self-excluding `record_sha256`, and require exact raw hash, exact self-hash,
`outcome == "HOLD"`, and `selected_candidate_id is None`. Do not import or call
`load_candidate_selection`, `repair_candidate_selection_from_preserved_run`,
candidate policies, comparison functions, or ranking code.

```python
def verify_historical_hold(
    protocol: StudyProtocolV2, *, repo_root: Path = PROJECT_ROOT
) -> HistoricalHoldAudit:
    path = repo_root / "configs/evaluation/e1-v2-candidate-selection.json"
    payload = read_bounded_bytes(path, maximum=4_000_000)
    document = load_strict_json_object(payload)
    validate_external_schema(
        document, repo_root / "schemas/e1-candidate-selection.v2.json"
    )
    verify_self_hash(document, field="record_sha256")
    if document["outcome"] != "HOLD" or document["selected_candidate_id"] is not None:
        raise StudyRetentionError("historical selection is not HOLD/null")
    return build_historical_hold_audit(payload, document, verify_e1_v1_history())
```

Call `verify_e1_v1_history()` and require `HOLD` with all nine historical
artifacts valid. Verify with git that base `9fd6d0c600206083fde4fafc874e0226b5df60b3`
is an ancestor of `execution_commit` and that local branch
`codex/e1-v2-scale-feature-remediation` still resolves exactly to that base.

- [ ] **Step 3: Capture immutable raw evidence with exact source/copy hashes**

Use only the protocol-fixed source paths:

```python
RETAINED_INPUTS = (
    ("candidate_a", "data/e1-v2-development/candidate-a.json", "retained-inputs/candidate-a.json"),
    ("candidate_b", "data/e1-v2-development/candidate-b.json", "retained-inputs/candidate-b.json"),
    (
        "task_4_report",
        "docs/evaluation/negative-results/e1-v2-task4-report.raw.txt",
        "retained-inputs/task-4-report.md",
    ),
    (
        "sdd_progress",
        "docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt",
        "retained-inputs/sdd-progress.md",
    ),
)
```

For each tuple, bounded-read the checked or repository-local source, require the
config-pinned raw hash, publish the same bytes through
`StudyArtifactStore.publish_bytes`, read them back, and require source/copy byte
equality and SHA equality. Phase 0 never dereferences the sibling-worktree
provenance strings. No source path is accepted from the CLI.

- [ ] **Step 4: Write failing direct/transitive/type-only dependency tests**

```python
def test_dependency_scan_classifies_edges_by_responsibility() -> None:
    report = scan_study_dependencies(load_study_protocol_v2())
    assert not report.forbidden_direct_edges
    assert any(
        edge.source.endswith("feature_mapping")
        and edge.target.endswith("oracle")
        and edge.kind == "runtime_transitive"
        for edge in report.edges
    )
    assert any(
        edge.source.endswith("metrics_v2")
        and edge.target.endswith("policy_v2")
        and edge.kind == "type_checking"
        for edge in report.edges
    )
```

Run: `uv run pytest tests/test_e1_study_dependency_guard_v2.py -q`
Expected: FAIL because dependency projection and edge classification do not
exist.

- [ ] **Step 5: Implement the complete implementation projection and guard**

Parse imports with `ast`, tracking whether each edge is direct from a
study-owned module, retained runtime-transitive, or under `if TYPE_CHECKING`.
Resolve only repository modules under `src/manufacturing_vision_studio`; record
sorted path, raw SHA, source module, target module, and edge kind. Include every
study module, CLI, config, matrix, schema, `pyproject.toml`, and `Makefile` even
when no import edge reaches it.

```python
def classify_edge(
    *, source: str, target: str, under_type_checking: bool, study_owned: frozenset[str]
) -> Literal["direct", "runtime_transitive", "type_checking"]:
    if under_type_checking:
        return "type_checking"
    if source in study_owned:
        return "direct"
    return "runtime_transitive"


PERFORMANCE_ROOTS = (
    "manufacturing_vision_studio.e1.study_cli_v2",
    "manufacturing_vision_studio.e1.study_runner_v2",
)
FORBIDDEN_DIRECT = frozenset(
    {
        "manufacturing_vision_studio.e1.policy_v2",
        "manufacturing_vision_studio.e1.geometry",
        "manufacturing_vision_studio.e1.geometry_search",
        "manufacturing_vision_studio.e1.diagnostics_v2",
    }
)
```

Fail when:

- a study production module directly imports `policy_v2`, `geometry`,
  `geometry_search`, or `diagnostics_v2`;
- a study module imports a retained module outside its config-declared direct
  allowlist;
- a projected path is missing, duplicated, untracked, or outside the repo;
- code outside `DevelopmentCorpusProvider` calls `E1V2Generator.plan_cases`;
- any production study AST references `EvaluationScope.SMOKE`,
  `CALIBRATION`, or `RELEASE_TEST`;
- any performance root reaches candidate comparison, candidate selection
  mutation, release entry points, or FreeCAD.

Permit and record the exact hashed retained edges `feature_mapping -> oracle`,
the generator-v2 legacy v1 planning chain, and the `metrics_v2 -> policy_v2`
type-only edge. A test monkeypatches protected planners/renderers to raise if
reached and proves normal study fixtures request only development.

- [ ] **Step 6: Assemble and verify the Phase 0 record**

`run_retention_audit()` first requires a verified
`implementation-validation.json` for the same execution commit, then captures
the four inputs and builds the projection. It writes `retention-audit.json`
only after every check passes. The record binds base SHA, execution SHA,
current evidence-only HEAD, selection raw/self hashes, A/B/report/ledger source
and copy hashes, v1 result, validation artifact raw/self hashes, projection,
dependency audit, and fixed classifications `Retain`, `Isolate`, `Re-review`.
It also expands every declared v2 evaluation seed block directly from protocol
data and records zero overlap with `800000..800107` without planning or
rendering a protected member.

```python
def run_retention_audit(
    protocol: StudyProtocolV2,
    store: StudyArtifactStore,
    *,
    execution_commit: str,
) -> RetentionAudit:
    validation = verify_implementation_validation(
        protocol, store, execution_commit=execution_commit
    )
    history = verify_historical_hold(protocol)
    projection = build_study_implementation_projection(protocol)
    dependencies = scan_study_dependencies(protocol)
    prepared_inputs = prepare_retained_inputs(protocol, store)
    verify_retention_prerequisites(
        protocol, validation, history, projection, dependencies, prepared_inputs
    )
    copied = publish_retained_inputs(store, prepared_inputs)
    audit = build_retention_record(
        protocol, validation, history, projection, dependencies, copied
    )
    store.publish_json("retention-audit.json", audit.as_record())
    return audit
```

`verify_retention_audit()` rechecks all portable bytes and requires the current
implementation projection to equal the audited projection. Later HEADs may
differ from the execution commit only under the fixed study artifact root;
source/config/schema changes invalidate the study.

Run:

```bash
uv run pytest tests/test_e1_study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py -q
```

Expected: PASS, including tamper rejection, missing/extra projection rejection,
type-only edge classification, no candidate calls, and immutable copies.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py
git commit -m "feat(e1): add feasibility retention audit"
```

### Task 7: Build the sealed runner, fixed CLI, Make targets, and terminal state machine

**Files:**
- Create: `src/manufacturing_vision_studio/e1/study_runner_v2.py`
- Create: `src/manufacturing_vision_studio/e1/study_cli_v2.py`
- Create: `tests/test_e1_study_runner_v2.py`
- Create: `tests/test_e1_study_cli_v2.py`
- Create: `docs/evaluation/e1-feasibility-study.md`
- Modify: `pyproject.toml`
- Modify: `Makefile`

**Interfaces:**
- Produces: `StudyRunner.from_default() -> StudyRunner` with protocol-fixed paths.
- Produces: `StudyRunner.validate_implementation() -> StudyArtifactRecord`.
- Produces: `StudyRunner.phase0() -> RetentionAudit`.
- Produces: `StudyRunner.phase1() -> DiagnosticStudyResult`.
- Produces: `StudyRunner.feature_oracle() -> FeatureOracleResult`.
- Produces: `StudyRunner.phase2() -> DevelopmentStudyResult`.
- Produces: `StudyRunner.status() -> StudyStatus` as a read-only prerequisite/authorization summary.
- Produces: `StudyRunner.finalize() -> TerminalDecisionRecord`.
- Produces: `StudyRunner.verify() -> StudyVerificationReport`.
- Produces: `run_small_fixture_determinism_control() -> DeterminismControl`.
- Produces: `main(argv: Sequence[str] | None = None) -> int` in `study_cli_v2.py`.
- Test helpers: `build_test_runner(tmp_path)` injects a temp store plus fabricated verified prerequisites; `build_runner_with_orphaned_phase1_claim(tmp_path)` adds only a valid claim and returns callback counters initialized to zero.

- [ ] **Step 1: Write failing state-machine, claim, and CLI tests**

```python
def test_phase_2_is_blocked_without_verified_phase_1_and_oracle(tmp_path: Path) -> None:
    runner = build_test_runner(tmp_path)
    with pytest.raises(StudyStateError, match="verified Phase 0, Phase 1, and oracle"):
        runner.phase2()


def test_orphaned_claim_prevents_every_performance_callback(tmp_path: Path) -> None:
    runner, spies = build_runner_with_orphaned_phase1_claim(tmp_path)
    status = runner.status()
    assert status.terminal_decision == "STUDY_INVALID"
    assert spies.render_calls == 0
    assert spies.normalize_calls == 0
    assert spies.inference_calls == 0


def test_cli_rejects_every_override() -> None:
    for args in (
        ["phase1", "--output-root", "/tmp/out"],
        ["phase1", "--mode", "NEAREST"],
        ["phase1", "--seed", "1"],
        ["phase2", "--scope", "development"],
    ):
        assert main(args) == 2
```

- [ ] **Step 2: Run the focused runner test and record RED**

Run: `uv run pytest tests/test_e1_study_runner_v2.py tests/test_e1_study_cli_v2.py -q`
Expected: FAIL because the runner and fixed CLI do not exist.

- [ ] **Step 3: Implement the runner state machine and terminal decision order**

```python
@dataclass(frozen=True, slots=True)
class DiagnosticStudyResult:
    row_count: int
    observation_count: int
    mode_summaries: tuple[DiagnosticModeSummary, ...]
    eligible_modes: tuple[ResamplingMode, ...]


@dataclass(frozen=True, slots=True)
class DevelopmentStudyResult:
    member_count: int
    mode_summaries: tuple[DevelopmentModeSummary, ...]
    passing_modes: tuple[ResamplingMode, ...]


@dataclass(frozen=True, slots=True)
class StudyStatus:
    study_valid: bool
    phase1_complete: bool
    feature_oracle_complete: bool
    phase2_authorized: bool
    phase2_complete: bool
    terminal_decision: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerminalDecisionRecord:
    decision: str
    allowed_next_action: str
    upstream_hashes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class StudyVerificationReport:
    verified_paths: tuple[str, ...]
    verify_rate: float
    status: StudyStatus


@dataclass(frozen=True, slots=True)
class VerifiedStudyState:
    study_valid: bool
    feature_oracle_passed: bool | None
    diagnostic_eligible_modes: tuple[ResamplingMode, ...]
    development_result: DevelopmentStudyResult | None
    development_passing_modes: tuple[ResamplingMode, ...]


DECISION_ORDER = (
    "STUDY_INVALID",
    "FEATURE_CONTRACT_FAILED",
    "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED",
    "DIFFERENCE_BASELINE_LIMITED",
    "TRANSFORM_ESTIMATION_LIMITED",
)


def choose_terminal_decision(state: VerifiedStudyState) -> str:
    if not state.study_valid:
        decision = "STUDY_INVALID"
    elif state.feature_oracle_passed is False:
        decision = "FEATURE_CONTRACT_FAILED"
    elif not state.diagnostic_eligible_modes:
        decision = "KNOWN_TRANSFORM_DIAGNOSTIC_FAILED"
    elif state.development_result is None:
        raise StudyStateError("authorized Phase 2 must complete before finalization")
    elif not state.development_passing_modes:
        decision = "DIFFERENCE_BASELINE_LIMITED"
    else:
        decision = "TRANSFORM_ESTIMATION_LIMITED"
    return decision
```

Implement this logic as `StudyRunner.finalize()` using verified artifacts, not
caller-supplied booleans. `status()` may report `PENDING`, but `decision.json`
must contain one of the five terminal values only.

`phase1()` verifies Phase 0, atomically publishes the claim before rendering
row 1, renders all 108 frozen rows, runs all three modes for 324 observations,
reduces each mode independently, and publishes the result only when complete.
An exception leaves the claim and no result; `status()` then returns
`STUDY_INVALID` without calling performance code.

`feature_oracle()` runs after a complete valid Phase 1 even when no mode is
eligible. It materializes the exact 120 development bindings, publishes
`scope-audit.json` and `feature-ownership-oracle.json`, and never calls image
inference.

`phase2()` verifies Phase 0, at least one eligible mode, and oracle PASS before
publishing its claim. It materializes the 120 bindings once, checks them against
the oracle/scope upstream hashes, records six trust rows with identity geometry
and `evaluation_status=NOT_APPLICABLE`, and calls the adapter exactly 114 times
per eligible mode. It records all modes; it does not rank or select one.

- [ ] **Step 4: Add the CLI entry point and per-phase subcommands**

Add this separate entry point to `pyproject.toml`:

```toml
mvs-e1-study = "manufacturing_vision_studio.e1.study_cli_v2:main"
```

Support only `validate-implementation`, `phase0`, `phase1`, `feature-oracle`,
`phase2`, `status`, `finalize`, and `verify`. The parser accepts a subcommand and
no other production argument. `StudyRunner.from_default()` loads the fixed
protocol and its fixed artifact root. Unit tests inject a temporary store
directly into `StudyRunner`; this test seam is never exposed by the CLI.

The operator guide records this order and labels `phase2` conditional:

```text
uv run mvs-e1-study validate-implementation
uv run mvs-e1-study phase0
uv run mvs-e1-study phase1
uv run mvs-e1-study feature-oracle
uv run mvs-e1-study status
uv run mvs-e1-study phase2
uv run mvs-e1-study finalize
uv run mvs-e1-study verify
```

It states that a claimed phase is never rerun, `status` is read-only, and
`phase2` is omitted unless status explicitly authorizes it.

- [ ] **Step 5: Add Make targets without widening normal validation**

Add these targets to `Makefile`: `validate-e1-study-implementation`,
`e1-study-phase0`, `e1-study-phase1`, `e1-study-feature-oracle`,
`e1-study-phase2`, `e1-study-status`, `finalize-e1-study`, and
`verify-e1-study`. Each invokes exactly one fixed subcommand. Do not add any
study execution target to `validate`, and do not add an umbrella target that
could rerun a claimed phase.

```make
validate-e1-study-implementation:
	uv run mvs-e1-study validate-implementation

e1-study-phase0:
	uv run mvs-e1-study phase0

e1-study-phase1:
	uv run mvs-e1-study phase1

e1-study-feature-oracle:
	uv run mvs-e1-study feature-oracle

e1-study-phase2:
	uv run mvs-e1-study phase2

e1-study-status:
	uv run mvs-e1-study status

finalize-e1-study:
	uv run mvs-e1-study finalize

verify-e1-study:
	uv run mvs-e1-study verify
```

- [ ] **Step 6: Implement fixed implementation validation and integrity-gate serialization**

`validate_implementation()` requires a clean worktree and runs these fixed
commands in order:

```python
IMPLEMENTATION_VALIDATION_COMMANDS = (
    ("ruff", ("uv", "run", "ruff", "check", ".")),
    ("mypy", ("uv", "run", "mypy", "src")),
    ("v0_1_regression", ("uv", "run", "pytest", "-q", "tests/test_e1_baseline.py")),
    ("pytest", ("uv", "run", "pytest", "-q")),
    ("web_check", ("npm", "--prefix", "web", "run", "check")),
    ("playwright", ("npm", "--prefix", "web", "run", "test:e2e")),
)
```

It records command argv, exit code, stdout/stderr SHA, start/end UTC metadata,
and the clean execution commit, and publishes
`implementation-validation.json` only if all six pass. Output timing is
diagnostic metadata, not a gate. Tests monkeypatch subprocess execution; they do
not run these commands or a full study.

Before publication, run two independent constructions of the fixed asymmetric
small fixture through all three resampling modes and require identical canonical
bytes and hashes mode-by-mode. Record both hash projections and PASS in the
validation artifact. This is the only repeated-run determinism control; no full
108- or 120-member execution is repeated.

Serialize the four incompatible controls—bundle reimport, split-member overlap,
FULL two-run equivalence, and publication count—as `NOT_APPLICABLE` with null
numerator, denominator, observed, operator, and threshold plus their fixed
reason. N/A must never satisfy an applicable gate.

- [ ] **Step 7: Run focused runner and CLI tests**

Run: `uv run pytest tests/test_e1_study_runner_v2.py tests/test_e1_study_cli_v2.py tests/test_e1_study_dependency_guard_v2.py -q`
Expected: PASS with Phase 2 blocked when prerequisites are absent, orphan claims
invalidating without callbacks, no CLI override, fixed validation commands,
correct decision priority, no forbidden direct imports, and explicit N/A gates.

- [ ] **Step 8: Commit Task 7**

```bash
git add src/manufacturing_vision_studio/e1/study_runner_v2.py src/manufacturing_vision_studio/e1/study_cli_v2.py tests/test_e1_study_runner_v2.py tests/test_e1_study_cli_v2.py docs/evaluation/e1-feasibility-study.md pyproject.toml Makefile
git commit -m "feat(e1): add feasibility study runner"
```

### Task 8: Run implementation verification before any one-time phase execution

**Files:**
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/implementation-validation.json`

**Interfaces:**
- Consumes: all Tasks 1-7 code, tests, schemas, config, and operator guide.
- Produces: a reviewed clean implementation commit plus immutable validation evidence for that exact commit.

- [ ] **Step 1: Run focused study test modules**

Run: `uv run pytest tests/test_e1_feasibility_protocol_v2.py tests/test_e1_known_transform_v2.py tests/test_e1_study_inference_v2.py tests/test_e1_study_parity_v2.py tests/test_e1_study_truth_v2.py tests/test_e1_study_artifacts_v2.py tests/test_e1_study_retention_v2.py tests/test_e1_study_runner_v2.py tests/test_e1_study_cli_v2.py tests/test_e1_study_dependency_guard_v2.py -q`
Expected: PASS.

- [ ] **Step 2: Run the full repository validation once**

Run: `make validate`
Expected: Ruff PASS, Mypy PASS, all Python tests PASS, web check PASS, and
Playwright PASS. Confirm no file exists at either execution-claim path.

- [ ] **Step 3: Perform the pre-experiment review gate**

Review only the implementation/config/schema diff for correctness, truth
leakage, protected-scope reachability, one-run semantics, denominator integrity,
and missing tests. Resolve every P0-P2 finding before proceeding, rerun Steps 1
and 2 after any edit, and commit the reviewed implementation. Do not execute
Phase 0, Phase 1, the oracle command, or Phase 2 during review.

- [ ] **Step 4: Prove the freeze state and the preserved source worktree**

Run:

```bash
git status --short
git rev-parse HEAD
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 rev-parse HEAD
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 status --short
```

Expected: the study worktree is clean; record its HEAD as the execution commit;
the preserved worktree is clean at
`9fd6d0c600206083fde4fafc874e0226b5df60b3`.

- [ ] **Step 5: Publish validation evidence for the clean execution commit**

Run:

```bash
uv run mvs-e1-study validate-implementation
uv run mvs-e1-study verify
```

Expected: the fixed six validation commands pass—including the named public
v0.1 regression—and exactly one canonical
`implementation-validation.json` is written; no phase claim or performance
artifact exists.

- [ ] **Step 6: Commit only the validation evidence**

```bash
git add docs/evaluation/results/e1-feasibility-study/implementation-validation.json
git commit -m "chore(e1): record study implementation validation"
```

### Task 9: Execute Phase 0 retention audit once and verify the artifact

**Files:**
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/retention-audit.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/retained-inputs/candidate-a.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/retained-inputs/candidate-b.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/retained-inputs/task-4-report.md`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/retained-inputs/sdd-progress.md`

**Interfaces:**
- Consumes: `StudyRunner.phase0()`, `StudyRunner.verify()`, and `StudyRunner.status()`.
- Produces: verified retention evidence and portable raw copies, or the terminal decision `STUDY_INVALID`.

- [ ] **Step 1: Confirm the clean evidence-only descendant and frozen execution SHA**

Run: `git status --short`
Expected: clean worktree before Phase 0. Recompute the four source hashes and
confirm the implementation-validation execution SHA still has an identical
implementation projection.

- [ ] **Step 2: Execute the retention audit**

Run: `uv run mvs-e1-study phase0`
Expected: PASS with verified base commit, Candidate A/B raw hashes, Task 4 raw snapshot hashes, preserved v1 history, dependency projection, and no forbidden runtime closure.

- [ ] **Step 3: Verify the retention artifacts immediately**

Run: `uv run mvs-e1-study verify`
Run: `uv run mvs-e1-study status`
Expected: PASS with the retention record and all four copies canonical/raw-hash
valid; status authorizes Phase 1 but reports Phase 1, oracle, and Phase 2 absent.

- [ ] **Step 4: Commit the Phase 0 evidence**

```bash
git add docs/evaluation/results/e1-feasibility-study/retention-audit.json docs/evaluation/results/e1-feasibility-study/retained-inputs/candidate-a.json docs/evaluation/results/e1-feasibility-study/retained-inputs/candidate-b.json docs/evaluation/results/e1-feasibility-study/retained-inputs/task-4-report.md docs/evaluation/results/e1-feasibility-study/retained-inputs/sdd-progress.md
git commit -m "chore(e1): record feasibility retention audit"
```

### Task 10: Execute Phase 1 diagnostic-108 and the independent feature oracle once

**Files:**
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/phase-1-execution-claim.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/known-transform-diagnostic-108.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/feature-ownership-oracle.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/scope-audit.json`

**Interfaces:**
- Consumes: `StudyRunner.phase1()`, `StudyRunner.feature_oracle()`, `StudyRunner.verify()`, and `StudyRunner.status()`.
- Produces: verified diagnostic evidence and oracle evidence or the terminal decision `STUDY_INVALID`.

- [ ] **Step 1: Publish the immutable Phase 1 claim and execute Phase 1**

Run: `uv run mvs-e1-study phase1`
Expected: one immutable claim plus one complete diagnostic result with exactly
`108 * 3 = 324` ordered observations, all three modes retained, exact defect
denominators, and no ranking/selection field. This command must never be rerun.

- [ ] **Step 2: Verify and commit Phase 1 before any later command**

Run: `uv run mvs-e1-study verify`
Expected: PASS with the claim/result self hashes, projection, 324 rows, and
mode-gate reductions consistent. If the claim exists without a complete result,
do not rerun Phase 1; run only `status` and proceed to final invalid evidence.

```bash
git add docs/evaluation/results/e1-feasibility-study/phase-1-execution-claim.json docs/evaluation/results/e1-feasibility-study/known-transform-diagnostic-108.json
git commit -m "chore(e1): record feasibility diagnostic evidence"
```

- [ ] **Step 3: Execute the independent feature oracle regardless of promotion**

Run: `uv run mvs-e1-study feature-oracle`
Expected: `scope-audit.json` binds exactly 120 development members, one external
request, only development internal revalidation calls, the documented legacy
v1 FULL template dependency, and zero protected v2 emissions.
`feature-ownership-oracle.json` evaluates all 60 defects even when no diagnostic
mode was eligible.

- [ ] **Step 4: Verify, commit, and read the Phase 2 authorization**

Run: `uv run mvs-e1-study verify`
Run: `uv run mvs-e1-study status`
Expected: verification PASS. Status reports `phase2_authorized=true` only when
retention is valid, at least one diagnostic mode is eligible, and the oracle
passes.

```bash
git add docs/evaluation/results/e1-feasibility-study/feature-ownership-oracle.json docs/evaluation/results/e1-feasibility-study/scope-audit.json
git commit -m "chore(e1): record feasibility feature oracle"
```

### Task 11: Conditionally execute Phase 2, write the terminal decision, and verify the final study packet

**Files:**
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/phase-2-execution-claim.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/known-transform-development-120.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/decision.json`
- Create at runtime: `docs/evaluation/results/e1-feasibility-study/report.md`

**Interfaces:**
- Consumes: `StudyRunner.status()`, `StudyRunner.phase2()`, `StudyRunner.finalize()`, and `StudyRunner.verify()`.
- Produces: the final verified terminal decision.

- [ ] **Step 1: Read authorization without writing a decision**

Run: `uv run mvs-e1-study status`
Expected: a read-only JSON summary. If `phase2_authorized=false`, confirm both
Phase 2 paths are absent and skip Step 2. If true, continue to Step 2. Never run
`finalize` before an authorized Phase 2 completes.

- [ ] **Step 2: If at least one mode is eligible and the oracle passed, execute Phase 2 once**

Run: `uv run mvs-e1-study phase2`
Expected: one immutable claim plus one result binding 120 members, exactly 114
inference rows per eligible mode, and six trust binding rows with no outcome and
no performance denominator. Every mode has the exact four gate numerators and
denominators; no best mode is selected. This command must never be rerun.

- [ ] **Step 3: Verify and commit conditional Phase 2 evidence**

When Step 2 ran, run `uv run mvs-e1-study verify`. Expected: PASS with claim,
120 bindings, eligible-mode set, 114-per-mode inference count, trust exclusions,
upstream hashes, and four gate reductions consistent. If a claim exists without
a complete result, do not rerun; `status` must report `STUDY_INVALID`.

When Phase 2 completed, commit:

```bash
git add docs/evaluation/results/e1-feasibility-study/phase-2-execution-claim.json docs/evaluation/results/e1-feasibility-study/known-transform-development-120.json
git commit -m "chore(e1): record feasibility development evidence"
```

- [ ] **Step 4: Write exactly one terminal decision and derived report**

Run: `uv run mvs-e1-study finalize`
Expected: `decision.json` resolves exactly one of `STUDY_INVALID`,
`FEATURE_CONTRACT_FAILED`, `KNOWN_TRANSFORM_DIAGNOSTIC_FAILED`,
`DIFFERENCE_BASELINE_LIMITED`, or `TRANSFORM_ESTIMATION_LIMITED` in top-down
priority. `report.md` is a deterministic human projection of that verified
record and starts with the development-only/non-release limitation.

- [ ] **Step 5: Verify the packet and preserved repository after finalization**

Run:

```bash
uv run mvs-e1-study verify
make validate
git diff --check
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 rev-parse HEAD
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 status --short
```

Expected: study verification PASS; normal validation PASS without executing a
study phase; preserved worktree still clean at `9fd6d0c`; no Candidate A/B
comparison, Candidate C, protected scope, FreeCAD, remote push, PR, tag, or
release action occurred.

- [ ] **Step 6: Commit the final decision and report**

```bash
git add docs/evaluation/results/e1-feasibility-study/decision.json docs/evaluation/results/e1-feasibility-study/report.md
git commit -m "chore(e1): record feasibility study decision"
```

- [ ] **Step 7: Perform a final evidence-only review**

Review the committed packet for artifact presence/absence matching the terminal
path, self/upstream hash validity, numerator/denominator accuracy, honest N/A
controls, and absence of selection/release claims. Run `git status --short` and
require a clean study worktree. Report the exact terminal decision and evidence
commit SHA to the user; do not publish remotely.

## Self-Review

- Spec coverage: Task 1 covers the closed protocol, exact 108-row snapshot, historical hashes, and negative evidence. Task 2 covers inverse math, canonical input, fixed fill, all three modes, and the boundary band. Task 3 covers truth erasure and downstream pipeline parity. Task 4 covers diagnostic rendering, raw identity semantics, exact reducers, development scope, transform proof, 120 bindings, 114 inference eligibility, and the feature oracle. Tasks 5-7 cover schemas, immutable evidence, execution claims, retention, direct/transitive dependency closure, fixed CLI, N/A controls, and the terminal state machine. Tasks 8-11 cover review/freeze, validation evidence, one-time Phase 0/1/2 execution, independent oracle execution, conditional promotion, terminal decision, report, and final verification.
- Content scan: every implementation action names concrete files, interfaces, commands, expected failures, expected passes, and commit boundaries. Ellipses remain only in valid Python variadic tuple type annotations and the concrete `os.link` call signature; no implementation body is elided.
- Type consistency: `StudyProtocolV2`, `FrozenDiagnosticPlan`, `ResamplingMode`, `KnownTransformResult`, `StudyInferenceInput`, `StudyTruthCase`, `DiagnosticModeSummary`, `DevelopmentCorpus`, `FeatureOracleResult`, `DevelopmentModeSummary`, `StudyArtifactStore`, `ExecutionClaim`, `RetentionAudit`, and every `StudyRunner` method retain one spelling and compatible input/output types from definition through execution.
- Gap check: the plan explicitly places `scope-audit.json` after 120-member materialization, keeps trust rows binding-only, records the public regression/full validation before Phase 0, copies all four raw retained inputs from checked snapshots rather than dereferencing a sibling worktree at runtime, binds the exact expected mode count in each execution claim, forbids output-root overrides, handles orphan claims without rerun, and never writes a decision before an authorized Phase 2 completes.
