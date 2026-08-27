# E1 v2 Scale and Feature Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and honestly evaluate an additive E1 protocol v2 that fixes scale normalization and final-mask feature mapping while making PR smoke, calibration, and release-test membership mutually disjoint.

**Architecture:** Preserve the complete v1.3 HOLD path, then add versioned v2 domain/protocol/generator modules, two image-only alignment candidates, exclusive final-mask ownership mapping, and a sealed stage runner. Normal PR CI can render only development and exactly 48 smoke cases; formal calibration and conditional release test operate only on a clean, exact frozen candidate SHA.

**Tech Stack:** Python 3.11+, NumPy, Pillow, JSON Schema Draft 2020-12, pytest, Ruff, Mypy, FastAPI, React/TypeScript/Vite, Playwright Chromium, GitHub Actions.

## Global Constraints

- Parent branch is `codex/e1-authoritative-mask-nuisance-evaluation-v0.2.0` at exact immutable HEAD `d7254cf8e09561a085def5cb9c914c31d79b9725`.
- Preserve evaluation freeze `2f87b885b29c12468effea927279d27424eaa340`, E1 v1.3 config/schemas/results, and outcome `HOLD` without rewrite, rebase, amend, delete, or overwrite.
- Implement on `codex/e1-v2-scale-feature-remediation`; its Draft stacked PR base is the parent branch, not `main`.
- Use `protocol_version: 2.0.0`, `dataset_version: 2.0.0`, `generator_version: 2.0.0`, `recipe_version: 2.0.0`, and `pipeline/model version: 1.2.0`; target product release remains `v0.2.0`.
- Keep locked image threshold exactly `0.0025`.
- Keep medium/high defect recall `>= 0.90`, nuisance-only false-positive rate `<= 0.05`, positive-case median Dice `>= 0.70`, and affected-feature mapping accuracy `>= 0.95`.
- Keep revision-mismatch publication count `== 0`, malformed/corrupted evidence publication count `== 0`, bundle verify/re-import `== 100%`, split hash overlap `== 0`, same-seed manifest equivalence `== true`, and v0.1.0 regression `== true`.
- Four v2 scopes are pairwise disjoint: development 120, smoke exactly 48, calibration 120, release_test 240. The 480 release-scale cases are development + calibration + release_test; smoke is an additional non-release corpus.
- Seed starts are fixed: development `400000/410000/420000/430000`, smoke `440000/450000/460000/470000`, calibration `500000/510000/520000/530000`, release_test `700000/710000/720000/730000` for clean/nuisance/defect/trust respectively.
- V1 calibration and mini-test cases are development diagnostics only and can never support a v2 release claim.
- Normal PR tests/Make/CI/API/UI may inspect release counts and seed-block declarations but may not enumerate or render release members; release-record unit tests use fabricated fixtures.
- Runtime inference may not access case IDs, seeds, revision-specific correction constants, expected features, defect labels, truth masks, authoritative masks, or nuisance metadata. Revision and view are allowed only for selecting the declared part geometry and ownership layout.
- Do not add a new hardcoded image-space residue filter; retain the existing structural postprocessor unchanged except for adapting trace types.
- Valid identity geometry returns non-abstaining `IDENTITY` and continues ordinary prediction; only unsafe/insufficient alignment returns `ABSTAIN`.
- Null and ambiguous feature results remain in the feature-mapping denominator.
- Smoke or calibration failure cannot select a different candidate, change a seed, change a threshold, or weaken a gate; it produces `HOLD` for this protocol attempt.
- In the chosen formal lineage/evidence root, calibration runs once after exact freeze; release_test may run only after a bound calibration PASS on the same candidate. The final packet records the procedural one-run assertion without claiming cross-rerun enforcement that read-only infrastructure cannot provide.
- Normal PR CI must neither render nor execute calibration/release_test and must not use `continue-on-error` for required checks.
- No real cameras, shop-floor data, MVTec, deep learning, FreeCAD work, sibling-repository changes, `FIELD_READY` claims, `main` merge, v0.2.0 tag, or GitHub Release.
- All code changes follow TDD: record a focused RED failure before implementation and a focused GREEN pass afterward.
- Design source of truth: `docs/superpowers/specs/2026-08-01-e1-v2-scale-feature-remediation-design.md`.

---

### Task 1: Add the versioned v2 protocol, corpus planner, and overlap proof

**Files:**
- Create: `schemas/e1-evaluation-protocol.v2.json`
- Create: `schemas/e1-case-manifest.v2.json`
- Create: `configs/evaluation/e1-v2.json`
- Create: `src/manufacturing_vision_studio/e1/domain_v2.py`
- Create: `src/manufacturing_vision_studio/e1/protocol_v2.py`
- Create: `src/manufacturing_vision_studio/e1/generator_v2.py`
- Create: `src/manufacturing_vision_studio/e1/overlap_v2.py`
- Create: `configs/evaluation/e1-v1-retired-release-membership.json`
- Create: `configs/evaluation/e1-v1-history-integrity.json`
- Create: `scripts/verify_e1_v1_history.py`
- Create: `tests/test_e1_v2_protocol.py`
- Create: `tests/test_e1_v2_generator.py`
- Create: `tests/test_e1_v2_overlap.py`
- Create: `tests/test_e1_v1_history_integrity.py`
- Create: `docs/evaluation/e1-protocol-v2.md`

**Interfaces:**
- Produces: `EvaluationScope`, `E1V2CasePlan`, and `E1V2GeneratedCase` in `domain_v2.py`.
- Produces: `E1V2Protocol` and `load_e1_v2_protocol(path: Path | str = DEFAULT_E1_V2_CONFIG_PATH) -> E1V2Protocol`.
- Produces: `E1V2Generator.plan_cases(scope: EvaluationScope | str) -> tuple[E1V2CasePlan, ...]` and `E1V2Generator.generate_case(plan: E1V2CasePlan) -> E1V2GeneratedCase`.
- Produces: `build_overlap_proof(scope_cases: Mapping[EvaluationScope, Sequence[Mapping[str, object]]], retired_v1_cases: Sequence[Mapping[str, object]]) -> dict[str, object]` and `verify_overlap_proof(document: Mapping[str, object]) -> None`.
- Consumes: existing deterministic v1 rendering primitives as read-only internal dependencies; Task 1 does not modify a v1 module.
- Produces: self-hashed retired-v1 membership bound to exact v1 config/protocol and historical mini/full manifest hashes.
- Produces: `verify_e1_v1_history() -> dict[str, object]`, which verifies fixed hashes and identities without ignored runtime artifacts.

- [ ] **Step 1: Write protocol/schema tests that pin versions, counts, seeds, and the four-scope vocabulary**

```python
def test_v2_protocol_pins_versions_counts_and_seed_blocks() -> None:
    protocol = load_e1_v2_protocol()
    assert protocol.protocol_version == "2.0.0"
    assert protocol.dataset_version == "2.0.0"
    assert protocol.pipeline_version == "1.2.0"
    assert protocol.model_version == "1.2.0"
    assert protocol.scope_counts == {
        EvaluationScope.DEVELOPMENT: 120,
        EvaluationScope.SMOKE: 48,
        EvaluationScope.CALIBRATION: 120,
        EvaluationScope.RELEASE_TEST: 240,
    }
    assert protocol.seed_starts == {
        "development": (400000, 410000, 420000, 430000),
        "smoke": (440000, 450000, 460000, 470000),
        "calibration": (500000, 510000, 520000, 530000),
        "release_test": (700000, 710000, 720000, 730000),
    }
```

- [ ] **Step 2: Run the focused protocol test and record RED**

Run: `uv run pytest tests/test_e1_v2_protocol.py -q`
Expected: FAIL because `protocol_v2`, schema v2, and config v2 do not exist.

- [ ] **Step 3: Implement strict v2 domain/config/schema loading**

Define `EvaluationScope` with exactly `development`, `smoke`, `calibration`,
and `release_test`. Validate exact group counts, all version constants, local
schema resolution, no duplicate JSON keys, the frozen seed blocks, the 48-case
smoke contract, and the unchanged threshold/gate values. Keep v1 loader defaults
and schema dispatch unchanged.

```python
class EvaluationScope(StrEnum):
    DEVELOPMENT = "development"
    SMOKE = "smoke"
    CALIBRATION = "calibration"
    RELEASE_TEST = "release_test"


def load_e1_v2_protocol(
    path: Path | str = DEFAULT_E1_V2_CONFIG_PATH,
) -> E1V2Protocol:
    return E1V2Protocol.from_path(Path(path).expanduser().resolve())
```

- [ ] **Step 4: Write planner tests for exact membership and deterministic bytes**

```python
@pytest.mark.parametrize(
    ("scope", "expected"),
    [(EvaluationScope.DEVELOPMENT, 120), (EvaluationScope.SMOKE, 48)],
)
def test_v2_planner_has_exact_scope_counts(scope: EvaluationScope, expected: int) -> None:
    plans = E1V2Generator().plan_cases(scope)
    assert len(plans) == expected
    assert {plan.scope for plan in plans} == {scope}
    assert len({plan.case_id for plan in plans}) == expected


def test_v2_same_plan_renders_identical_case_bytes() -> None:
    generator = E1V2Generator()
    plan = generator.plan_cases(EvaluationScope.SMOKE)[0]
    first = generator.generate_case(plan)
    second = generator.generate_case(plan)
    assert first.reference_sha256 == second.reference_sha256
    assert first.inspection_sha256 == second.inspection_sha256
    assert first.authoritative_mask_sha256 == second.authoritative_mask_sha256
```

- [ ] **Step 5: Implement deterministic v2 planning and rendering**

Use config-driven counts and seed blocks. Normal tests enumerate and render only
development/smoke; release scope counts and seed declarations are schema-tested
without planning their members. The generator must accept only a plan
present in the requested v2 contract. Reuse or extract the established pristine,
nuisance, defect, oracle, and PNG paths so v1 output remains unchanged. V2 case
bindings include `scope`, `case_id`, `recipe_id`, `seed_family`, `seed`, all
three source hashes, expected outcome, and defect ID.

- [ ] **Step 6: Write overlap tests, including retired v1 exclusion and tampering**

```python
def test_fabricated_disjoint_membership_and_retired_set_have_zero_overlap() -> None:
    scope_cases = fabricated_disjoint_scope_records_with_repeated_empty_masks()
    proof = build_overlap_proof(scope_cases, valid_retired_v1_membership())
    verify_overlap_proof(proof)
    assert proof["all_pairwise_zero"] is True
    assert proof["retired_v1_release_overlap_count"] == 0
    assert proof["raw_empty_authoritative_mask_duplicates"] > 0


def test_overlap_verifier_recomputes_instead_of_trusting_reported_zero() -> None:
    proof = valid_overlap_proof()
    proof["pairs"][0]["case_binding_overlap_count"] = 0
    proof["pairs"][0]["left_members"][0]["case_binding_sha256"] = proof["pairs"][0]["right_members"][0]["case_binding_sha256"]
    with pytest.raises(E1V2ProtocolError, match="overlap"):
        verify_overlap_proof(proof)
```

- [ ] **Step 7: Implement canonical overlap recomputation and historical retirement declaration**

The proof must enumerate every pair of v2 scopes and v2
calibration/release_test against the checked-in retired v1 membership. Require
zero on case ID, recipe ID, `(seed_family, seed)`, reference SHA, inspection SHA,
case-binding SHA, and non-empty authoritative-mask SHA. Permit a repeated raw
empty-mask SHA only for declared clean/nuisance negatives. Hash the canonical
proof, reject duplicate member identities, and reject any document whose claimed
counts differ from recomputation. Unit tests use fabricated records; Task 5's
formal freeze performs the only generated calibration/release integration.

- [ ] **Step 8: Pin and test v1 history plus retired membership**

The history integrity document pins SHA-256 and expected identity/verdict fields
for `configs/evaluation/e1-v1.json`, every `schemas/e1-*.v1.json`, both public v1
result summaries, `docs/releases/v0.2.0/E1_HOLD.md`, the v0.1 bundle, and the
preflight tag/commit identities. The retirement document lists all v1
calibration and exact mini-test identities and binds v1 config hash plus
historical manifests `00e6ac243217a90f04776855354c2d30de387245b9306c46c22ef992fa0159e3`
and `1a8f6a32b7e98fe51c72f711f172effcbf04eeda00d0d4fdc8fe5f3ba36dbbc2`.

```python
def test_v1_history_and_retirement_artifacts_fail_on_mutation(tmp_path: Path) -> None:
    assert verify_e1_v1_history()["verdict"] == "HOLD"
    retired = load_retired_v1_release_membership()
    assert retired.calibration_member_count == 120
    assert retired.mini_test_member_count == 24
    tamper_copy(retired.source_path, tmp_path / "retired.json", "members", 0)
    with pytest.raises(E1V2ProtocolError, match="retired"):
        load_retired_v1_release_membership(tmp_path / "retired.json")
```

- [ ] **Step 9: Document v1 retirement and v2 split semantics**

Include this exact statement:

```text
E1 v1.3 calibration and mini test results were observed. Their calibration/test
cases are retired from future release-gate use. They may be reused only as
development diagnostics.
```

- [ ] **Step 10: Run focused and v1 regression tests**

Run: `uv run pytest tests/test_e1_v2_protocol.py tests/test_e1_v2_generator.py tests/test_e1_v2_overlap.py tests/test_e1_v1_history_integrity.py tests/test_e1_evaluation_protocol.py tests/test_e1_generator.py -q`
Run: `uv run python scripts/verify_e1_v1_history.py`
Expected: all pass with no new warnings.

- [ ] **Step 11: Commit Task 1**

```bash
git add schemas/e1-evaluation-protocol.v2.json schemas/e1-case-manifest.v2.json configs/evaluation/e1-v2.json configs/evaluation/e1-v1-retired-release-membership.json configs/evaluation/e1-v1-history-integrity.json scripts/verify_e1_v1_history.py src/manufacturing_vision_studio/e1/domain_v2.py src/manufacturing_vision_studio/e1/protocol_v2.py src/manufacturing_vision_studio/e1/generator_v2.py src/manufacturing_vision_studio/e1/overlap_v2.py tests/test_e1_v2_protocol.py tests/test_e1_v2_generator.py tests/test_e1_v2_overlap.py tests/test_e1_v1_history_integrity.py docs/evaluation/e1-protocol-v2.md
git commit -m "feat(e1): add isolated v2 evaluation corpus"
```

### Task 2: Map affected features from the final mask with exclusive ownership

**Files:**
- Create: `src/manufacturing_vision_studio/e1/feature_mapping.py`
- Create: `tests/test_e1_v2_feature_mapping.py`
- Modify: `src/manufacturing_vision_studio/e1/domain_v2.py`
- Modify: `src/manufacturing_vision_studio/e1/protocol_v2.py`
- Modify: `configs/evaluation/e1-v2.json`
- Modify: `schemas/e1-evaluation-protocol.v2.json`

**Interfaces:**
- Produces: immutable `FeatureOwnershipConfig` in `domain_v2.py` and `E1V2Protocol.feature_ownership(cad_revision: CadRevision | str, view_id: ViewId | str) -> FeatureOwnershipConfig` in `protocol_v2.py`.
- Consumes: Task 1's protocol-owned revision/view geometry and v2 renderer/oracle projection; tests reject drift between that geometry and ownership boxes.
- Produces: `build_ownership_map(config: FeatureOwnershipConfig, image_size: tuple[int, int]) -> FeatureOwnershipMap`.
- Produces: `map_final_mask(mask_bytes: bytes, ownership: FeatureOwnershipMap, *, minimum_winner_pixels: int = 8, ambiguity_margin: float = 0.10) -> FeatureMappingResult`.
- `FeatureMappingResult` exposes `predicted_feature_id`, `status`, `reason`, `owner_pixel_counts`, `owned_pixel_count`, `winner_owned_pixel_count`, `final_positive_pixel_count`, `unmapped_pixel_count`, `winner_margin`, `final_mask_sha256`, and `ownership_map_sha256`.

- [ ] **Step 1: Write RED tests for six exclusive ownership layouts**

```python
@pytest.mark.parametrize("revision", [CadRevision.REV_A, CadRevision.REV_B])
@pytest.mark.parametrize("view", list(ViewId))
def test_ownership_is_exclusive_and_conserves_owned_pixels(
    revision: CadRevision,
    view: ViewId,
) -> None:
    protocol = load_e1_v2_protocol()
    ownership = build_ownership_map(protocol.feature_ownership(revision, view), (512, 384))
    assert ownership.labels.shape == (384, 512)
    assert ownership.ownership_map_sha256 == EXPECTED_OWNERSHIP_HASHES[(revision, view)]
    assert set(np.unique(ownership.labels)) <= {0, 1, 2, 3, 4, 5}
    assert ownership.label_at(*hole_over_face_coordinate(revision, view)) == "hole_left"
    assert ownership.label_at(*edge_over_face_coordinate(revision, view)) == "top_edge"


def test_revision_b_right_hole_layout_differs_from_revision_a() -> None:
    protocol = load_e1_v2_protocol()
    rev_a = build_ownership_map(protocol.feature_ownership("rev-A", "front"), (512, 384))
    rev_b = build_ownership_map(protocol.feature_ownership("rev-B", "front"), (512, 384))
    assert rev_a.ownership_map_sha256 != rev_b.ownership_map_sha256
```

- [ ] **Step 2: Run ownership tests and record RED**

Run: `uv run pytest tests/test_e1_v2_feature_mapping.py -q`
Expected: FAIL because `feature_mapping.py` and ownership protocol fields are absent.

- [ ] **Step 3: Implement half-open rasterization and one-owner priority**

Rasterize lower bounds with floor and upper bounds with ceil, clip to the image,
and assign only previously unowned pixels in this exact order:

```python
FEATURE_OWNERSHIP_PRIORITY = (
    "hole_left",
    "hole_right",
    "top_edge",
    "bottom_edge",
    "top_face",
)
```

Store normalized boxes for each revision/view in the same protocol geometry
source used by the v2 renderer/oracle. Revision B's right-hole box reflects the
declared +4 px geometry delta rather than a runtime correction heuristic. Label
0 is unmapped; codes 1..5 follow sorted feature IDs. Hash
`canonical_json({algorithm,revision,view,width,height,feature_ids,priority}) +
b"\0" + C-order uint8 labels`. Rebuilding from protocol bytes must reproduce
the golden hash.

- [ ] **Step 4: Write RED mapping-semantic tests**

```python
def test_mapping_uses_only_pixels_present_in_final_mask() -> None:
    raw_mask = mask_for("bottom_edge") | mask_for("top_face", pixels=20)
    final_mask = raw_mask & ~mask_for("bottom_edge")
    result = map_final_mask(png(final_mask), front_rev_a_ownership())
    assert result.predicted_feature_id == "top_face"
    assert result.final_mask_sha256 == sha256_bytes(png(final_mask))


@pytest.mark.parametrize(
    ("mask", "reason"),
    [
        (empty_mask(), "NO_OWNED_PIXELS"),
        (mask_outside_all_owners(20), "NO_OWNED_PIXELS"),
        (mask_with_owner_counts(7, 0), "INSUFFICIENT_MAPPED_PIXELS"),
        (mask_with_owner_counts(5, 4), "INSUFFICIENT_MAPPED_PIXELS"),
        (mask_split_equally("hole_left", "top_face", 20), "AMBIGUOUS_FEATURE"),
        (mask_with_ratio("hole_left", 100, "top_face", 91), "AMBIGUOUS_FEATURE"),
    ],
)
def test_null_and_ambiguous_mapping(mask: np.ndarray, reason: str) -> None:
    result = map_final_mask(png(mask), front_rev_a_ownership())
    assert result.predicted_feature_id is None
    assert result.reason == reason
```

- [ ] **Step 5: Implement mapping decisions and trace hashing**

Decode only canonical grayscale PNG masks. Count each positive pixel at most
once, sort serialized owner counts by feature ID, retain unmapped pixels, and
apply decisions in order: zero owned, winner fewer than 8, exact tie, margin
below 0.10, winner. Assert 100/90 maps at the exact 0.10 boundary while 100/91
is ambiguous; compute from integer counts without pre-rounding and serialize to
8 decimals. Exact ties are ambiguous; ownership priority never forces a winning
prediction. Every result must satisfy `owned + unmapped == final positive`.

- [ ] **Step 6: Add regression coverage for all required semantic slices**

Cover raw winner removal, hole/top-face overlap, edge/top-face overlap, a mask
crossing two owners, zero/7/0/5+4/exactly-8 boundaries, winner 8 with a
runner-up, exact 0.10 and just-under margins, a bottom-edge scale residual, all
six revision/view layouts, corrupt masks, deterministic ties, conservation, and
repeated-call hash equality. For every development/smoke defect case, map the
authoritative mask offline and assert at least 8 target-owned pixels and the
declared target winner. Task 5 repeats this cross-check inside formal freeze for
calibration/release without publishing members.

Task 4's `metrics_v2.py` test consumes these exact mapping results and proves
that a null/ambiguous known-feature positive contributes numerator 0 and
denominator 1 without changing pixel Dice/IoU denominators.

- [ ] **Step 7: Run focused tests and static checks**

Run: `uv run pytest tests/test_e1_v2_feature_mapping.py -q`
Run: `uv run ruff check src/manufacturing_vision_studio/e1/feature_mapping.py tests/test_e1_v2_feature_mapping.py`
Run: `uv run mypy src/manufacturing_vision_studio/e1/feature_mapping.py`
Expected: all pass with pristine output.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/manufacturing_vision_studio/e1/feature_mapping.py src/manufacturing_vision_studio/e1/domain_v2.py src/manufacturing_vision_studio/e1/protocol_v2.py tests/test_e1_v2_feature_mapping.py configs/evaluation/e1-v2.json schemas/e1-evaluation-protocol.v2.json
git commit -m "fix(e1): map features from exclusive final-mask owners"
```

### Task 3: Implement bounded geometry candidates A and B

**Files:**
- Create: `src/manufacturing_vision_studio/e1/geometry.py`
- Create: `src/manufacturing_vision_studio/e1/geometry_search.py`
- Create: `tests/test_e1_v2_geometry.py`
- Create: `tests/test_e1_v2_geometry_search.py`
- Modify: `configs/evaluation/e1-v2.json`
- Modify: `schemas/e1-evaluation-protocol.v2.json`

**Interfaces:**
- Produces: immutable `AlignmentCandidate`, `AlignmentTrace`, `AlignmentResult`, and `AlignmentStatus` in `geometry.py`.
- Produces: `align_largest_component(reference_bytes: bytes, inspection_bytes: bytes, config: GeometryConfig) -> AlignmentResult`.
- Produces: `align_coarse_to_fine(reference_bytes: bytes, inspection_bytes: bytes, config: GeometryConfig) -> AlignmentResult`.
- Produces: `alignment_objective(reference_silhouette: np.ndarray, candidate_silhouette: np.ndarray, reference_edges: np.ndarray, candidate_edges: np.ndarray) -> AlignmentObjective`.
- Later policy code consumes corrected bytes for `APPLIED`, original bytes for non-abstaining `IDENTITY`, and fails closed only for `ABSTAIN`.

- [ ] **Step 1: Write RED tests for silhouette extraction and the exact objective**

```python
def test_silhouette_uses_only_largest_component() -> None:
    image = rgb_with_plate_and_small_fixture()
    silhouette = largest_component_silhouette(image, chebyshev_threshold=18)
    assert silhouette[plate_center_y, plate_center_x]
    assert not silhouette[fixture_center_y, fixture_center_x]


def test_alignment_objective_uses_preregistered_weights() -> None:
    objective = alignment_objective(ref_mask, candidate_mask, ref_edges, candidate_edges)
    assert objective.value == pytest.approx(
        0.70 * objective.silhouette_xor_rate + 0.30 * objective.normalized_edge_mae
    )


def test_transform_sign_order_and_fill_on_asymmetric_image() -> None:
    transformed = apply_correction(labelled_asymmetric_png(), rotation=1.0, scale=1.01, dx=2, dy=-3)
    assert transformed == EXPECTED_ASYMMETRIC_GOLDEN_PNG
```

- [ ] **Step 2: Run geometry tests and record RED**

Run: `uv run pytest tests/test_e1_v2_geometry.py tests/test_e1_v2_geometry_search.py -q`
Expected: FAIL because both candidate modules are absent.

- [ ] **Step 3: Implement shared image-only geometry primitives**

Implement border-median foreground extraction at threshold 18; deterministic
8-connected components ordered by `(-area,min_y,min_x,max_y,max_x)`; 1%-tail
trimmed integer bounds; component median; analytic 2x2 PCA wrapped to
`[-90,90)` with eigengap `<0.05` fallback; the design's inspection-to-reference
inverse affine formula; silhouette XOR/full-canvas; 8-neighbor boundary
MAE/full-canvas; IoU diagnostics; and unrounded lexicographic resolution. Do not
accept truth or nuisance objects in any runtime signature. Golden-test equal
component ties, low eigengap, correction signs/order, inverse scale endpoints,
border fill, and canonical PNG bytes.

- [ ] **Step 4: Write RED tests for Candidate A's 225-candidate cap and corrections**

```python
@pytest.mark.parametrize("observed_scale", [0.98, 0.985, 0.99, 1.005, 1.01, 1.015, 1.02])
def test_candidate_a_reduces_scale_objective(observed_scale: float) -> None:
    reference, inspection = rendered_scale_pair(observed_scale)
    result = align_largest_component(reference, inspection, geometry_config())
    assert result.trace.candidates_evaluated <= 225
    assert result.trace.candidate_pixels_evaluated <= 44_236_800
    assert result.trace.objective_after < result.trace.objective_before
    assert 1 / 1.02 <= result.trace.correction_scale <= 1 / 0.98


def test_candidate_a_is_byte_deterministic() -> None:
    first = align_largest_component(reference_png, inspection_png, geometry_config())
    second = align_largest_component(reference_png, inspection_png, geometry_config())
    assert first == second
```

- [ ] **Step 5: Implement Candidate A exactly as preregistered**

Use robust bounds/center/PCA, reject initial translations outside ±12 px,
clamp rotation to ±1.5° and correction scale to `[1/1.02, 1/0.98]`, then
refine offsets `[-0.5, 0, 0.5]`,
`[-0.004, 0, 0.004]`, and integer translations `[-2,+2]²`. Deduplicate
clamped transforms and rendered hashes before evaluation. Test supported
translations at ±12 on both axes and out-of-range abstention.

- [ ] **Step 6: Write RED tests for Candidate B's bounded coarse/refine search**

```python
def test_candidate_b_obeys_search_caps_and_grid() -> None:
    result = align_coarse_to_fine(reference_png, inspection_png, geometry_config())
    assert result.trace.coarse_candidates_evaluated <= 1575
    assert result.trace.refine_candidates_evaluated <= 81
    assert result.trace.candidate_pixels_evaluated <= 35_278_848
    assert result.trace.search_size == (128, 96)


def test_candidate_b_reduces_combined_scale_rotation_translation() -> None:
    reference, inspection = rendered_affine_pair(scale=1.015, rotation=1.0, dx=2, dy=-2)
    result = align_coarse_to_fine(reference, inspection, geometry_config())
    assert result.trace.objective_after < result.trace.objective_before
```

- [ ] **Step 7: Implement Candidate B exactly as preregistered**

Compute robust initial translation, downsample with the declared 4x4 majority
rule, evaluate the 1,575-point coarse grid at `128x96` using offsets around that
initial translation, retain the best distinct rendered silhouette, and
evaluate at most 81 full-resolution refinements using the design's exact
rotation, scale, and translation offsets. Use the same objective and tie tuple
as Candidate A. Assert full-resolution dx/dy convert to coarse units by division
by four and absolute final translations never exceed ±12 px.

- [ ] **Step 8: Test abstention and defect preservation**

```python
def test_identity_is_non_abstaining_and_continues_inference() -> None:
    reference, inspection = identity_pair()
    result = align_largest_component(reference, inspection, geometry_config())
    assert result.status is AlignmentStatus.IDENTITY
    assert result.trace.status_reason == "IDENTITY_BASELINE"
    assert result.inspection_bytes == inspection


@pytest.mark.parametrize(
    ("fixture", "reason"),
    [
        (tiny_foreground_pair(), "INSUFFICIENT_FOREGROUND"),
        (out_of_range_translation_pair(), "TRANSLATION_OUT_OF_RANGE"),
        (symmetric_ambiguous_improvement_pair(), "AMBIGUOUS_ALIGNMENT"),
        (double_boundary_optimum_pair(), "BOUNDARY_OPTIMUM"),
    ],
)
def test_alignment_abstains_fail_closed(fixture: tuple[bytes, bytes], reason: str) -> None:
    result = align_largest_component(*fixture, geometry_config())
    assert result.status is AlignmentStatus.ABSTAIN
    assert result.trace.abstention_reason == reason
    assert result.inspection_bytes == fixture[1]
```

Assert a single scale-bound optimum is not rejected, while simultaneous scale
and rotation bounds are `BOUNDARY_OPTIMUM`; serialize both booleans. Add fixed
development-diagnostic medium/high scratch, stain, edge-chip, burr, blocked-hole,
and hole-deviation fixtures spanning revisions/views. Offline truth may be used
only by the test: every candidate's per-case truth-pixel recall may fall by at
most 0.05 versus identity, aggregate median Dice may fall by at most 0.01, and
medium/high classification recall remains at least 0.90.

- [ ] **Step 9: Run focused tests and static checks**

Run: `uv run pytest tests/test_e1_v2_geometry.py tests/test_e1_v2_geometry_search.py -q`
Run: `uv run ruff check src/manufacturing_vision_studio/e1/geometry.py src/manufacturing_vision_studio/e1/geometry_search.py tests/test_e1_v2_geometry.py tests/test_e1_v2_geometry_search.py`
Run: `uv run mypy src/manufacturing_vision_studio/e1/geometry.py src/manufacturing_vision_studio/e1/geometry_search.py`
Expected: all pass with pristine output.

- [ ] **Step 10: Commit Task 3**

```bash
git add src/manufacturing_vision_studio/e1/geometry.py src/manufacturing_vision_studio/e1/geometry_search.py tests/test_e1_v2_geometry.py tests/test_e1_v2_geometry_search.py configs/evaluation/e1-v2.json schemas/e1-evaluation-protocol.v2.json
git commit -m "feat(e1): add bounded scale alignment candidates"
```

### Task 4: Compare candidates on development and integrate the selected v2 policy

**Files:**
- Create: `src/manufacturing_vision_studio/e1/diagnostics_v2.py`
- Create: `src/manufacturing_vision_studio/e1/policy_v2.py`
- Create: `src/manufacturing_vision_studio/e1/registration_v2.py`
- Create: `src/manufacturing_vision_studio/e1/metrics_v2.py`
- Create: `schemas/e1-candidate-selection.v2.json`
- Create after development comparison: `configs/evaluation/e1-v2-candidate-selection.json`
- Create: `tests/test_e1_v2_diagnostics.py`
- Create: `tests/test_e1_v2_policy.py`
- Create: `tests/test_e1_v2_metrics.py`
- Do not modify: `src/manufacturing_vision_studio/e1/model.py`, `src/manufacturing_vision_studio/e1/metrics.py`, `src/manufacturing_vision_studio/e1/artifacts.py`

**Interfaces:**
- Consumes: Candidate A/B alignment functions, `map_final_mask`, v2 generator/protocol, existing difference model, and unchanged structural postprocessor.
- Produces: `build_scale_diagnostic_matrix(protocol: E1V2Protocol) -> tuple[ScaleDiagnosticPlan, ...]`.
- Produces: `compare_candidates(output_root: Path | str, *, protocol: E1V2Protocol | None = None) -> CandidateSelectionRecord`.
- Produces: `load_candidate_selection(path: Path | str) -> CandidateSelectionRecord` with schema/hash verification.
- Produces: `E1V2InferenceInput.from_generated(generated: E1V2GeneratedCase) -> E1V2InferenceInput`; the projection retains only reference/inspection bytes and hashes, part ID, CAD revision, and view.
- Produces: `E1V2InferencePolicy.inspect(inference: E1V2InferenceInput) -> E1V2CaseResult`.
- Produces: `register_inspection_for_v2(inspection_bytes: bytes, *, shift_x: int, shift_y: int) -> bytes`, golden-tested against the core model's shift convention.
- Produces: v2 observation/metric construction in `metrics_v2.py`; it delegates unchanged mathematical primitives without changing v1 dispatch.
- `E1V2CaseResult` carries final mask bytes/hash, anomaly score/outcome, v2 geometry trace, feature mapping result, and final model registration.

- [ ] **Step 1: Write RED tests for the exact diagnostic matrix and truth separation**

```python
def test_scale_matrix_covers_revisions_views_and_preregistered_scales() -> None:
    plans = build_scale_diagnostic_matrix(load_e1_v2_protocol())
    assert len(plans) == 108
    assert [plan.seed for plan in plans] == list(range(800000, 800108))
    assert len({plan.seed for plan in plans} & all_evaluation_seeds()) == 0
    primary = [plan for plan in plans if plan.combination == "scale_only"]
    assert {(p.cad_revision, p.view_id, p.scale_delta) for p in primary} == {
        (revision, view, scale)
        for revision in CadRevision
        for view in ViewId
        for scale in (-0.020, -0.015, -0.010, -0.005, 0.005, 0.010, 0.015, 0.020)
    }


def test_runtime_input_has_no_diagnostic_truth_field() -> None:
    signature = inspect.signature(E1V2InferencePolicy.inspect)
    assert tuple(signature.parameters) == ("self", "inference")
    assert "diagnostic_truth" not in E1V2InferenceInput.__annotations__
    assert "expected_feature_id" not in E1V2InferenceInput.__annotations__
    assert "authoritative_mask_bytes" not in E1V2InferenceInput.__annotations__
    assert "nuisances" not in E1V2InferenceInput.__annotations__
```

- [ ] **Step 2: Run diagnostic/policy tests and record RED**

Run: `uv run pytest tests/test_e1_v2_diagnostics.py tests/test_e1_v2_policy.py -q`
Expected: FAIL because v2 diagnostic and policy modules do not exist.

- [ ] **Step 3: Implement the diagnostic matrix and record schema**

Generate exactly 48 scale-only rows plus 12 each for deterministic
scale+translation, scale+rotation, scale+exposure, scale+medium-defect, and
scale+high-defect rows, using IDs `e1-v2-development-diagnostic-000..107` and
seeds `800000..800107`. This non-gating diagnostic artifact is outside all four
evaluation scopes and every acceptance denominator.
Serialize offline truth under `diagnostic_truth` and image-derived results under
`inference_trace`. Record every field listed in the design, including runtime.

- [ ] **Step 4: Write RED tests for candidate eligibility and lexicographic selection**

```python
def test_selection_rejects_work_cap_or_gate_failure_before_ranking() -> None:
    records = [candidate_record("A", nuisance_fp=0, work_cap_passed=False), candidate_record("B", nuisance_fp=1, work_cap_passed=True)]
    selected = select_candidate(records)
    assert selected.selected_candidate_id == "B"
    assert selected.candidates[0].rejection_reasons == ("WORK_CAP_EXCEEDED",)


def test_selection_tie_prefers_candidate_a() -> None:
    record = select_candidate([eligible_record("B"), eligible_record("A")])
    assert record.selected_candidate_id == "A"
```

- [ ] **Step 5: Implement candidate comparison and immutable selection records**

Run both candidates over development plus the non-gating diagnostic only. Apply
the exact eligibility filters and seven-term ordering from the design. Store
inputs, configuration hashes, candidate metrics, work counts, benchmark sample
protocol/metadata, rejected reasons, selected ID, and a canonical self-hash. The
record binds `implementation_projection_sha256` over exact path→SHA entries for
v2 domain/protocol/generator, geometry A/B, feature mapping, registration,
policy, metrics, diagnostics, protocol/schema config, and frozen v1 core
dependencies. It excludes itself, stage/CLI/UI, and evidence and does not claim
the pre-commit checkout SHA. Do not read smoke, calibration, or release_test.

- [ ] **Step 6: Write RED policy regression tests for final-mask mapping and trace meanings**

```python
def test_policy_recomputes_feature_after_structural_postprocessing(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_mapping_inputs: list[bytes] = []
    monkeypatch.setattr(policy_module, "map_final_mask", recording_mapper(observed_mapping_inputs))
    result = policy.inspect(inference_whose_bottom_edge_residue_is_removed())
    assert result.feature_mapping.predicted_feature_id == "top_face"
    assert result.feature_mapping.final_mask_sha256 == result.predicted_mask_sha256
    assert observed_mapping_inputs == [result.predicted_mask_bytes]


def test_geometry_shifts_are_not_conflated() -> None:
    result = policy.inspect(scale_translation_inference())
    trace = result.geometry_trace
    assert trace.pre_normalization_shift != trace.post_normalization_shift
    assert trace.final_model_registration == result.model_registration
    assert "comparison_shift" not in trace.as_record()


def test_postfilter_uses_registered_inspection_in_reference_coordinates() -> None:
    result = policy.inspect(nonzero_registration_rev_b_right_hole_inference())
    assert result.postprocessing_inspection_sha256 == result.registered_inspection_sha256
    assert result.feature_mapping.predicted_feature_id == "hole_right"
```

- [ ] **Step 7: Implement v2 policy flow without changing the old postfilter rules**

Project each generated diagnostic/evaluation case into `E1V2InferenceInput`
before policy invocation so truth, expected feature, defect, nuisance, seed, and
case ID are structurally unavailable. Load the hashed selection record; dispatch
only its candidate. `IDENTITY` continues with original bytes; `ABSTAIN` returns
fail-closed without feature mapping. Pass corrected/original bytes to the
established difference/translation-registration model, reconstruct its
registered inspection bytes with the exact core shift convention, and pass
those reference-frame bytes plus the raw reference-frame mask to the unchanged
structural predicates. Map only the resulting persisted final mask; compute
score/outcome; expose separate pre/post normalization and final model shifts.
Expected feature and authoritative mask are used only by offline metrics after
inference returns. A spy test proves the mapper receives the exact persisted
final-mask bytes and no forbidden field appears in either call surface.

- [ ] **Step 8: Make ambiguity/null mapping denominator-explicit**

In `metrics_v2.py`, make a positive case with no predicted feature contribute
one denominator and zero correct numerator without changing its pixel Dice/IoU
denominators. Count unexpected `ABSTAIN` on a supported nuisance as FP and on a
supported defect as FN. Retain mask recall and per-class/per-view Dice as
diagnostics without creating a gate. Add exact one-case numerator/denominator
tests for all three rules.

- [ ] **Step 9: Execute the full development comparison once and check in the selected record**

Run: `uv run python -m manufacturing_vision_studio.e1.diagnostics_v2 --output-root data/e1-v2-development compare-candidates`
Expected: both candidate records are complete; exactly one eligible candidate is selected according to preregistered criteria. If neither is eligible, record `HOLD` and stop formal progression without changing the criteria.

Copy the verified canonical selection record to
`configs/evaluation/e1-v2-candidate-selection.json`; load it again and verify its
self-hash and implementation projection before committing. After the commit,
recompute the projection and assert it is unchanged; Task 7 reruns
development/smoke on the final candidate and the freeze seal binds selection
record hash, projection hash, and checkout SHA separately.

- [ ] **Step 10: Run focused and v1 regression tests**

Run: `uv run pytest tests/test_e1_v2_diagnostics.py tests/test_e1_v2_policy.py tests/test_e1_v2_metrics.py tests/test_e1_model.py tests/test_e1_policy.py tests/test_e1_metrics.py tests/test_e1_artifacts.py -q`
Run: `uv run ruff check src/manufacturing_vision_studio/e1 tests/test_e1_v2_diagnostics.py tests/test_e1_v2_policy.py`
Run: `uv run mypy src`
Expected: all pass with no new warnings.

- [ ] **Step 11: Commit Task 4**

```bash
git add src/manufacturing_vision_studio/e1/diagnostics_v2.py src/manufacturing_vision_studio/e1/policy_v2.py src/manufacturing_vision_studio/e1/registration_v2.py src/manufacturing_vision_studio/e1/metrics_v2.py schemas/e1-candidate-selection.v2.json configs/evaluation/e1-v2-candidate-selection.json tests/test_e1_v2_diagnostics.py tests/test_e1_v2_policy.py tests/test_e1_v2_metrics.py
git commit -m "fix(e1): integrate selected geometry and final-mask mapping"
```

### Task 5: Enforce sealed development, smoke, freeze, calibration, and release stages

**Files:**
- Create: `src/manufacturing_vision_studio/e1/artifacts_v2.py`
- Create: `src/manufacturing_vision_studio/e1/guard_v2.py`
- Create: `src/manufacturing_vision_studio/e1/runner_v2.py`
- Create: `schemas/e1-overlap-proof.v2.json`
- Create: `schemas/e1-stage-result.v2.json`
- Create: `schemas/e1-freeze-seal.v2.json`
- Create: `schemas/e1-calibration-seal.v2.json`
- Create: `tests/test_e1_v2_artifacts.py`
- Create: `tests/test_e1_v2_guard.py`
- Create: `tests/test_e1_v2_runner.py`

**Interfaces:**
- Produces: `run_v2_development(output_root: Path | str, *, protocol: E1V2Protocol | None = None, selection_path: Path | str = DEFAULT_SELECTION_PATH) -> dict[str, object]`.
- Produces: `run_v2_smoke(output_root: Path | str, *, protocol: E1V2Protocol | None = None, selection_path: Path | str = DEFAULT_SELECTION_PATH) -> dict[str, object]`.
- Produces: `freeze_v2_manifests(output_root: Path | str, *, formal_context: FormalRunContext, protocol: E1V2Protocol | None = None, selection_path: Path | str = DEFAULT_SELECTION_PATH) -> dict[str, object]`.
- Produces: `run_v2_calibration(output_root: Path | str, *, formal_context: FormalRunContext, freeze_seal_path: Path | str, protocol: E1V2Protocol | None = None) -> dict[str, object]`.
- Produces: `run_v2_release_test(output_root: Path | str, *, formal_context: FormalRunContext, freeze_seal_path: Path | str, calibration_seal_path: Path | str, protocol: E1V2Protocol | None = None) -> dict[str, object]`.
- Produces: `verify_v2_evidence(root: Path | str, *, required_stage: EvaluationStage | None = None) -> dict[str, object]`.
- Formal functions require `FormalRunContext(candidate_sha: str, lineage_id: str, authorization: Literal["explicit-local", "github-actions"])`; normal PR/API code never constructs it.
- Guard functions reject a dirty tree, HEAD mismatch, protocol/model/generator/selection/projection mismatch, artifact tampering, overlap, a second calibration in the same lineage/evidence root, and release execution without bound calibration PASS.

- [ ] **Step 1: Write RED tests proving PR stages cannot touch release scopes**

```python
@pytest.mark.parametrize("stage", ["development", "smoke"])
def test_pr_stage_never_generates_calibration_or_release_cases(stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    touched: list[EvaluationScope] = []
    monkeypatch.setattr(E1V2Generator, "generate_case", recording_generator(touched))
    run_stage(stage, tmp_path)
    assert set(touched) <= {EvaluationScope.DEVELOPMENT, EvaluationScope.SMOKE}
    assert EvaluationScope.CALIBRATION not in touched
    assert EvaluationScope.RELEASE_TEST not in touched


def test_smoke_manifest_has_exactly_48_cases(tmp_path: Path) -> None:
    result = run_v2_smoke(tmp_path)
    manifest = read_json(tmp_path / "smoke" / "manifest.json")
    assert result["evaluation_scope"] == "smoke"
    assert len(manifest["cases"]) == 48


def test_pr_make_target_contains_no_release_material(tmp_path: Path) -> None:
    completed = run_make("verify-e1-v2-pr", output_root=tmp_path)
    assert completed.returncode == 0
    assert find_release_material(tmp_path) == []
```

- [ ] **Step 2: Run runner tests and record RED**

Run: `uv run pytest tests/test_e1_v2_runner.py tests/test_e1_v2_guard.py tests/test_e1_v2_artifacts.py -q`
Expected: FAIL because stage runner, guards, and schemas do not exist.

- [ ] **Step 3: Implement development/smoke stage isolation and artifacts**

Each stage generates only its declared scope, computes metrics against unchanged
gates, writes a canonical manifest/result/inventory, and verifies its own
roundtrip. Development may include the separate offline diagnostic. Smoke never
loads a release manifest or includes release hashes in UI/API payloads.

- [ ] **Step 4: Write RED freeze guard tests**

```python
def test_freeze_requires_clean_exact_head(tmp_path: Path, git_repo: Path) -> None:
    dirty_file = git_repo / "dirty.txt"
    dirty_file.write_text("dirty", encoding="utf-8")
    with pytest.raises(E1V2GuardError, match="clean"):
        freeze_v2_manifests(tmp_path, formal_context=valid_formal_context())


def test_freeze_builder_seals_fabricated_manifests_without_model_inference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(E1V2InferencePolicy, "inspect", forbidden_call)
    seal = build_freeze_seal_from_records(tmp_path, fabricated_fresh_release_records())
    assert seal["calibration_manifest_sha256"]
    assert seal["release_test_manifest_sha256"]
    assert seal["candidate_dirty"] is False
```

- [ ] **Step 5: Implement the self-hashed freeze seal and canonical overlap proof**

Unit tests use fabricated release records and never enumerate/render real v2
release members. The explicitly authorized formal command alone renders fresh
manifests. Bind exact candidate SHA, formal lineage ID,
protocol/config/schema hashes, generator/recipe versions and hashes,
selection-record hash plus recomputed implementation projection, model/pipeline IDs and versions,
model artifact/config hashes, threshold `0.0025`, environment/lock hashes,
development/smoke result hashes, both fresh manifests, and overlap proof. Verify
all member hashes on every later stage. Formal generation cross-checks every
calibration/release authoritative defect mask against its revision/view
ownership layout without publishing member details.

- [ ] **Step 6: Write RED fail-closed calibration/release sequencing tests**

```python
def test_calibration_hold_never_executes_release_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    freeze = frozen_fixture(tmp_path)
    monkeypatch.setattr(metrics, "calibration_gates_pass", lambda _: False)
    calibration = run_v2_calibration(tmp_path, formal_context=valid_formal_context(), freeze_seal_path=freeze)
    assert calibration["verdict"] == "HOLD"
    assert not (tmp_path / "release_test").exists()


def test_release_requires_bound_pass_on_same_candidate(tmp_path: Path) -> None:
    freeze, calibration = pass_fixtures(tmp_path)
    tamper_json(calibration, {"candidate_sha": "f" * 40})
    with pytest.raises(E1V2GuardError, match="candidate"):
        run_v2_release_test(tmp_path, formal_context=valid_formal_context(), freeze_seal_path=freeze, calibration_seal_path=calibration)
```

- [ ] **Step 7: Implement per-lineage single calibration and conditional release execution**

Calibration runs only inference cases in its sealed manifest, checks the four
calibration gates, and persists a bound `PASS` or `HOLD` seal. If HOLD, no
release directory is created. Release verifies the PASS seal and exact checkout,
then runs release inference, trust boundaries, v0.1 regression, bundle
roundtrip, all gates, and deterministic verification. Existing stage artifacts
make a second calibration in the same formal lineage/evidence root fail. Seals
record lineage/workflow-run identity. The implementation does not claim to stop
a repository owner from starting an unrelated new root or workflow rerun; the
final packet records the procedural one-run evidence for the chosen lineage.

- [ ] **Step 8: Add artifact-tampering and denominator tests**

Tamper every binding one at a time: candidate SHA, protocol hash, generator
hash, selection hash, threshold, manifest hash, case binding, overlap proof,
calibration status, inventory, and final self-hash. Assert fail-closed error
codes. Assert calibration nuisance denominator is 30, release nuisance
denominator is 60, ambiguous feature cases remain denominators, supported
nuisance abstention is FP, and supported defect abstention is FN. Assert a valid
population of repeated empty negative masks passes while duplicated non-empty
mask, inspection, or case-binding identities fail.

- [ ] **Step 9: Run focused and security regressions**

Run: `uv run pytest tests/test_e1_v2_artifacts.py tests/test_e1_v2_guard.py tests/test_e1_v2_runner.py tests/test_e1_trust_boundaries.py tests/test_e1_result_schemas.py tests/test_api_fail_closed.py tests/test_input_safety.py -q`
Run: `uv run ruff check src/manufacturing_vision_studio/e1 tests/test_e1_v2_artifacts.py tests/test_e1_v2_guard.py tests/test_e1_v2_runner.py`
Run: `uv run mypy src`
Expected: all pass with no new warnings.

- [ ] **Step 10: Commit Task 5**

```bash
git add src/manufacturing_vision_studio/e1/artifacts_v2.py src/manufacturing_vision_studio/e1/guard_v2.py src/manufacturing_vision_studio/e1/runner_v2.py schemas/e1-overlap-proof.v2.json schemas/e1-stage-result.v2.json schemas/e1-freeze-seal.v2.json schemas/e1-calibration-seal.v2.json tests/test_e1_v2_artifacts.py tests/test_e1_v2_guard.py tests/test_e1_v2_runner.py
git commit -m "feat(e1): seal v2 evaluation stage transitions"
```

### Task 6: Separate CLI/CI release boundaries and expose bilingual diagnostics

**Files:**
- Modify: `src/manufacturing_vision_studio/cli.py`
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/e1-v2-frozen-evaluation.yml`
- Modify: `src/manufacturing_vision_studio/api.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/types.ts`
- Modify: `web/src/copy.ts`
- Modify: `web/src/components/EvaluationWorkspace.tsx`
- Modify: `web/src/styles.css`
- Create: `tests/test_e1_v2_cli.py`
- Create: `tests/test_e1_v2_api.py`
- Modify: `web/e2e/e1-evaluation.spec.ts`

**Interfaces:**
- Adds script `mvs-e1-v2 = manufacturing_vision_studio.cli:e1_v2`.
- Adds commands `development`, `smoke`, `freeze-manifests`, `calibrate`, `release-test`, and `verify`; formal commands require explicit candidate SHA, lineage ID, and authorization flag plus artifact paths.
- Adds Make targets `verify-e1-v1-history`, `evaluate-e1-v2-development`, `evaluate-e1-v2-smoke`, `verify-e1-v2-pr`, and formal stage targets that are absent from `validate` and normal PR CI.
- API returns a diagnostic projection only; it never starts formal evaluation.

- [ ] **Step 1: Write RED CLI tests for explicit commands and unsafe sequencing**

```python
def test_v2_cli_smoke_uses_only_smoke_stage(tmp_path: Path) -> None:
    completed = run_cli("mvs-e1-v2", "--output-root", str(tmp_path), "smoke")
    assert completed.returncode == 0
    assert read_json(tmp_path / "smoke" / "manifest.json")["case_count"] == 48
    assert not (tmp_path / "calibration").exists()
    assert not (tmp_path / "release_test").exists()


def test_v2_cli_release_without_pass_seal_fails_closed(tmp_path: Path) -> None:
    completed = run_cli("mvs-e1-v2", "--output-root", str(tmp_path), "release-test")
    assert completed.returncode != 0
    assert "formal authorization" in completed.stderr
```

- [ ] **Step 2: Run CLI/API/web tests and record RED**

Run: `uv run pytest tests/test_e1_v2_cli.py tests/test_e1_v2_api.py -q`
Run: `npm --prefix web run test:e2e -- --grep "E1 v2"`
Expected: FAIL because the CLI/API/UI surface is absent.

- [ ] **Step 3: Implement CLI and Make boundaries**

Wire every command directly to one runner function. Default output root is
`data/e1-v2-evaluation`. Require explicit freeze/calibration seal paths for
formal stages plus `--candidate-sha`, `--lineage-id`, and `--formal`. `make
validate` may include v2 unit tests but never a formal freeze, calibration, or
release command. `verify-e1-v1-history` verifies checked-in hashes; existing
`verify-e1-results` remains local-only for preserved ignored runtime artifacts.

- [ ] **Step 4: Change normal CI to development/smoke only**

Replace any E1 job that evaluates v1 mini calibration/test on every PR with:

```yaml
- name: Verify preserved E1 v1 HOLD evidence
  run: make verify-e1-v1-history
- name: Run E1 v2 development and isolated 48-case smoke
  run: make verify-e1-v2-pr
```

No v2 calibration/release command, release manifest path, or allowed-failure
setting may occur in the normal PR workflow.

- [ ] **Step 5: Add a manual frozen-evaluation workflow**

Use `workflow_dispatch` with required full-40-hex `freeze_sha`, read-only contents
permission, and concurrency group keyed by that SHA with cancellation disabled.
Pin checkout/upload/download actions to commit SHAs and use
`persist-credentials: false`. Build three jobs in one run:

1. `freeze`: exact-SHA checkout, `HEAD` equality and empty status assertions,
   locked setup, development/smoke verification, formal manifest/seal creation,
   independent seal verification, artifact upload;
2. `calibration`: exact-SHA clean checkout, same-run freeze artifact download and
   independent verification, calibration, verified artifact upload;
3. `release-test`: dependent on calibration PASS, exact-SHA clean checkout,
   downloads both same-run artifacts, independently verifies seal lineage and
   persisted PASS before inference.

The release condition may use a job output to avoid starting after HOLD, but the
release command must not trust that string without artifact verification. Every
seal includes GitHub run/attempt lineage. The workflow creates no tags, releases,
comments, or merges.

- [ ] **Step 6: Write RED API/UI semantic and accessibility tests**

```python
def test_api_marks_smoke_as_non_release_diagnostic(client: TestClient, v2_smoke_result: Path) -> None:
    payload = client.get("/api/evaluation/e1-v2").json()
    assert payload["protocol_version"] == "2.0.0"
    assert payload["stage"] == "smoke"
    assert payload["release_evidence"] is False
    assert payload["limitations"]
    forbidden = {"case_id", "seed", "manifest_sha256", "release_test", "calibration"}
    assert forbidden.isdisjoint(recursive_keys(payload))


def test_api_rejects_release_roots_symlinks_and_traversal(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/evaluation/e1-v2?root=../release_test").status_code == 400
    assert client.get("/api/evaluation/e1-v2", headers={"X-Test-Root": str(release_symlink(tmp_path))}).status_code == 400
```

```ts
test("shows isolated smoke evidence without readiness overclaim", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("48-case isolated smoke")).toBeVisible();
  await expect(page.getByText("Release evidence", { exact: true })).toHaveCount(0);
  await expect(page.getByText("출시 정확도가 아닌 진단 결과")).toBeVisible();
});
```

- [ ] **Step 7: Implement diagnostic API and bilingual UI projection**

Show protocol/stage, selected candidate, zero-overlap status, objective before/
after, pre/post/final shifts, feature owner counts and ambiguity reason, weakest
slices, mandatory mask-recall diagnostics, and deterministic-synthetic
limitations. Preserve keyboard navigation, visible focus, semantic headings,
table labels, and English/Korean copy parity. Do not expose release member IDs,
seeds, images, or manifest hashes in smoke UI payloads.

- [ ] **Step 8: Validate workflow guards and full web surface**

Run: `rg -n "continue-on-error|calibrat|release-test|release_test" .github/workflows/ci.yml`
Expected: no allowed-failure setting and no formal v2 stage in normal CI.

Run: `uv run pytest tests/test_e1_v2_cli.py tests/test_e1_v2_api.py tests/test_e1_cli.py tests/test_e1_api.py -q`
Run: `npm --prefix web run check`
Run: `npm --prefix web run test:e2e`
Expected: all pass with pristine output.

- [ ] **Step 9: Commit Task 6**

```bash
git add src/manufacturing_vision_studio/cli.py pyproject.toml Makefile .github/workflows/ci.yml .github/workflows/e1-v2-frozen-evaluation.yml src/manufacturing_vision_studio/api.py web/src/api.ts web/src/types.ts web/src/copy.ts web/src/components/EvaluationWorkspace.tsx web/src/styles.css tests/test_e1_v2_cli.py tests/test_e1_v2_api.py web/e2e/e1-evaluation.spec.ts
git commit -m "ci(e1): isolate smoke from frozen release stages"
```

### Task 7: Validate, freeze, execute the fresh evaluation, and publish truthful evidence

**Files:**
- Create after freeze: `docs/releases/v0.2.0/E1_V2_FREEZE.md`
- Create after development/smoke: `docs/evaluation/results/e1-v2-development-v0.2.0.json`
- Create after development/smoke: `docs/evaluation/results/e1-v2-smoke-v0.2.0.json`
- Create after calibration: `docs/evaluation/results/e1-v2-calibration-v0.2.0.json`
- Create only after executed release_test: `docs/evaluation/results/e1-v2-release-test-v0.2.0.json`
- Create exactly one terminal report: `docs/releases/v0.2.0/E1_V2_REMEDIATION_READY.md` or `docs/releases/v0.2.0/E1_V2_HOLD.md`
- Create: `docs/reviews/E1_V2_REMEDIATION_REVIEW.md`
- Create browser evidence under: `docs/screenshots/e1-v2-*.png`

**Interfaces:**
- Consumes: all previous commands and seals.
- Produces: a final packet with candidate SHA and evidence-commit SHA kept distinct.
- Produces: exactly one terminal decision string: `SHIP — REMEDIATION_READY_FOR_PARENT_INTEGRATION` or `HOLD`.

- [ ] **Step 1: Run the complete pre-freeze validation from a clean worktree**

Run:

```bash
git status --short
make validate
make verify-e1-v1-history
make verify-e1-v2-pr
git diff --check
git status --short
```

Expected: clean before and after, all lint/type/unit/security/web/E2E checks pass,
historical v1 HOLD verifies, development passes, exact 48-case smoke passes, and
no release case is rendered. A failing development or smoke gate produces HOLD
without freeze.

- [ ] **Step 2: Record the exact candidate SHA and generate sealed manifests without inference**

```bash
CANDIDATE_SHA=$(git rev-parse HEAD)
LINEAGE_ID="local-2026-08-01-${CANDIDATE_SHA}"
test -z "$(git status --porcelain --untracked-files=all)"
uv run mvs-e1-v2 --output-root data/e1-v2-evaluation freeze-manifests --formal --candidate-sha "$CANDIDATE_SHA" --lineage-id "$LINEAGE_ID"
uv run mvs-e1-v2 --output-root data/e1-v2-evaluation verify --required-stage freeze
```

Expected: clean candidate binding; checked-in selection record's implementation
projection recomputes on the final candidate; fresh calibration/release
manifests and zero-overlap proof are sealed; all target ownership cross-checks
pass; model inference call count is zero.

- [ ] **Step 3: Run fresh calibration once in the recorded local lineage**

```bash
uv run mvs-e1-v2 --output-root data/e1-v2-evaluation calibrate --formal --candidate-sha "$CANDIDATE_SHA" --lineage-id "$LINEAGE_ID" --freeze-seal data/e1-v2-evaluation/freeze/freeze-seal.json
uv run mvs-e1-v2 --output-root data/e1-v2-evaluation verify --required-stage calibration
```

Expected: nuisance denominator 30, at most one nuisance false positive for PASS,
and all four calibration gates recorded. If any gate fails, confirm there is no
release_test directory, write the HOLD documents, and do not execute Step 4.

- [ ] **Step 4: Execute release_test only when the persisted calibration seal is PASS**

```bash
uv run mvs-e1-v2 --output-root data/e1-v2-evaluation release-test --formal --candidate-sha "$CANDIDATE_SHA" --lineage-id "$LINEAGE_ID" --freeze-seal data/e1-v2-evaluation/freeze/freeze-seal.json --calibration-seal data/e1-v2-evaluation/calibration/calibration-seal.json
uv run mvs-e1-v2 --output-root data/e1-v2-evaluation verify --required-stage release_test
```

Expected: nuisance denominator 60, at most three nuisance false positives,
threshold remains `0.0025`, all trust/integrity/reproducibility/regression gates
pass, and the release result is bound to the same candidate SHA.

- [ ] **Step 5: Capture bilingual browser evidence**

Start the local app against verified v2 evidence, then use Playwright Chromium
to capture the overview, isolated-smoke notice, geometry trace, feature mapping,
and terminal decision in both Korean and English. Run the complete E2E suite
after screenshots.

- [ ] **Step 6: Create the freeze, result, review, and terminal documents from verified artifacts**

The freeze document records candidate SHA, formal lineage ID, procedural
single-run assertion and its technical per-lineage boundary, seal SHA,
protocol/config/schema,
generator/recipe, model/pipeline, selection, manifest, threshold, environment,
development, smoke, and overlap hashes. Results include numerator/denominator,
weakest nuisance/revision/view/defect slices, mask recall, per-class/per-view
Dice, runtime, and candidate comparison. The terminal document preserves v1.3
HOLD evidence and states why release_test did or did not execute.

Use exact terminal wording:

```text
SHIP — REMEDIATION_READY_FOR_PARENT_INTEGRATION
```

only when every required fresh gate passes; otherwise use:

```text
HOLD
```

Neither wording authorizes a main merge, tag, or release.

- [ ] **Step 7: Run final local verification of the committed evidence projection**

Run: `make validate`
Run: `make verify-e1-v1-history`
Run: `uv run mvs-e1-v2 --output-root data/e1-v2-evaluation verify`
Run: `git diff --check`
Expected: all pass; formal artifact bytes still bind to the earlier candidate SHA.

- [ ] **Step 8: Commit Task 7 evidence separately from the candidate**

```bash
git add docs/releases/v0.2.0 docs/evaluation/results docs/reviews/E1_V2_REMEDIATION_REVIEW.md docs/screenshots
git diff --cached --name-only
git commit -m "docs(e1): record frozen v2 remediation evidence"
```

Stage only the result/terminal files that actually exist. Never create a
release-test result when calibration held, and never create both terminal
documents.

## Final Controller Verification and Handoff

After all applicable tasks complete:

1. Run a whole-branch review package from
   `d7254cf8e09561a085def5cb9c914c31d79b9725` to HEAD.
2. Obtain independent read-only reviews for methodology/leakage, geometry and
   defect preservation, feature/denominator semantics, security/artifact
   boundaries, UI/accessibility, and release wording.
3. Resolve every P0-P2 and rerun affected checks.
4. Run `make validate`, checked-in v1-history integrity verification, optional
   preserved-runtime v1 verification in its artifact-bearing worktree, v2
   evidence verification, clean-checkout validation, and `git diff --check` on
   the reviewed HEAD.
5. Push the remediation branch and open a Draft PR with base
   `codex/e1-authoritative-mask-nuisance-evaluation-v0.2.0`.
6. Confirm PR #12 is still Draft/unmerged at the immutable parent head and that
   neither `v0.2.0` tag nor release exists.
7. Report both candidate and evidence SHAs, the exact terminal decision, and
   the smallest next human action. A real submitted human GitHub review remains
   required before the parent PR can become Ready.
