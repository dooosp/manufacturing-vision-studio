# E1 v2 Scale and Feature Remediation Design

**Date:** 2026-08-01
**Status:** Approved for implementation
**Target product release:** `v0.2.0`
**Evaluation protocol and dataset:** `2.0.0`

## Purpose

This remediation preserves E1 v1.3 as an honest historical HOLD and creates a
narrowly scoped, stacked change that corrects three demonstrated problems:

1. scale-sensitive image-derived geometry normalization;
2. affected-feature mapping derived from a raw mask instead of the final mask;
3. PR smoke membership that exposed members of the v1 release corpus.

The result remains deterministic synthetic evidence for a local demonstration.
It does not claim real-camera, shop-floor, safety, shipment, production, or
`FIELD_READY` performance.

## Frozen Historical Boundary

The following evidence is immutable and must continue to verify:

| Item | Frozen value |
|---|---|
| Parent branch | `codex/e1-authoritative-mask-nuisance-evaluation-v0.2.0` |
| Parent HEAD / PR #12 head | `d7254cf8e09561a085def5cb9c914c31d79b9725` |
| E1 v1.3 evaluation freeze | `2f87b885b29c12468effea927279d27424eaa340` |
| Protocol | `mvs-e1` `1.3.0` |
| Outcome | `HOLD` |

The v1.3 calibration cases and every v1.3 mini test member have been observed.
They are retired from future release-gate use. They may be reused only as
development diagnostics. Existing v1 config, schemas, results, release HOLD
document, and verification paths remain readable and valid.

Implementation occurs in
`codex/e1-v2-scale-feature-remediation`, based exactly on the parent HEAD. Its
Draft stacked PR targets the parent branch, never `main`.

## Scope and Non-goals

In scope:

- an additive v2 protocol/config/schema path;
- four mutually disjoint data scopes;
- two bounded image-only normalization candidates and a development-only
  selection record;
- final-mask, exclusive affected-feature mapping;
- unambiguous multi-stage geometry traces;
- stage-specific freeze, calibration, and release-test guards;
- development/smoke CI and diagnostic UI evidence;
- an exact fresh calibration and, only after PASS, fresh release test.

Out of scope:

- changing image threshold `0.0025` or any existing acceptance gate;
- known-case, seed, revision, expected-feature, defect-label, truth-mask, or
  nuisance-metadata inference dependencies;
- adding more scale-residue filters;
- reusing observed v1 release cases;
- real cameras, shop-floor data, MVTec, deep learning, FreeCAD work, sibling
  repositories, or a v0.3 contract;
- allowing CI failures, merging to `main`, tagging `v0.2.0`, or publishing a
  release.

## Architecture

### Additive version boundary

The v1 module and artifact contracts remain the default `mvs-e1` path. The v2
implementation is additive:

- `configs/evaluation/e1-v2.json` and
  `schemas/e1-evaluation-protocol.v2.json` define the new contract;
- `e1/protocol_v2.py`, `e1/domain_v2.py`, and `e1/generator_v2.py` own v2
  planning without weakening v1 invariants;
- `e1/geometry.py` and `e1/geometry_search.py` expose independent candidate
  implementations behind the same immutable result type;
- `e1/feature_mapping.py` maps only a final postprocessed mask;
- `e1/registration_v2.py` reconstructs the core model's registered inspection
  in the reference coordinate frame without changing the v1 result contract;
- `e1/metrics_v2.py` and `e1/artifacts_v2.py` keep v2 metric/artifact dispatch
  out of the frozen v1 modules;
- `e1/runner_v2.py`, `e1/artifacts_v2.py`, and `e1/guard_v2.py` enforce stage
  sequencing and evidence seals;
- `mvs-e1-v2` provides explicit commands. Existing v1 commands continue to
  verify historical results unchanged.

V2 code may call existing pure v1 rendering primitives as read-only internal
dependencies, but it does not modify the v1 generator, normalizer, metrics, or
artifact modules. A checked-in v1-history integrity manifest pins SHA-256 values
for the v1 config, schemas, public result summaries, `E1_HOLD.md`, and v0.1
bundle. Fresh-checkout CI verifies this manifest without requiring ignored
runtime artifacts. The existing `make verify-e1-results` remains a local
runtime-artifact verifier when the preserved `data/e1-evaluation` directories
are available.

### Four disjoint data scopes

The v2 release-scale corpus remains 480 cases:

| Scope | Clean | Nuisance | Defect | Trust | Total | Normal use |
|---|---:|---:|---:|---:|---:|---|
| `development` | 24 | 30 | 60 | 6 | 120 | Free iteration and candidate selection |
| `calibration` | 24 | 30 | 60 | 6 | 120 | Once, after exact freeze |
| `release_test` | 48 | 60 | 120 | 12 | 240 | Only after calibration PASS |

An additional, separate PR-only smoke corpus has exactly 48 cases:

| Scope | Clean | Nuisance | Defect | Trust | Total |
|---|---:|---:|---:|---:|---:|
| `smoke` | 8 | 12 | 24 | 4 | 48 |

Thus v2 defines 528 cases in total while preserving the original 480-case
release-scale structure. Smoke is not a subset of those 480 cases and is never
reported as release accuracy.

Seed blocks are preregistered before model execution:

| Scope | Clean start | Nuisance start | Defect start | Trust start |
|---|---:|---:|---:|---:|
| `development` | 400000 | 410000 | 420000 | 430000 |
| `smoke` | 440000 | 450000 | 460000 | 470000 |
| `calibration` | 500000 | 510000 | 520000 | 530000 |
| `release_test` | 700000 | 710000 | 720000 | 730000 |

Every seed family carries a `v2` suffix and the v2 case ID format is
`e1-v2-{scope}-{group}-{ordinal:03d}`. Seeds are contiguous within their
declared blocks and cannot be changed after outcomes are observed.

An `overlap-proof.json` is recomputed from canonical membership rather than
trusting reported counters. It proves zero overlap for every pair among all
four v2 scopes separately on case ID, recipe ID, `(seed_family, seed)`, reference
hash, inspection hash, and case-binding hash. The case-binding hash includes
case identity and authoritative-mask hash. Raw authoritative-mask hashes are
reported but are not a universal zero-overlap key: the canonical empty mask is
expected to repeat only for declared clean/nuisance negatives. Non-empty
authoritative-mask hashes must have zero cross-scope overlap.

The proof also verifies v2 calibration/release membership against a checked-in,
self-hashed `e1-v1-retired-release-membership.json`. That artifact is bound to
the exact v1 protocol/config and historical mini/full manifest hashes and lists
all observed v1 calibration and mini-test member identities. Mutation or source
replacement fails verification.

The enforceable PR boundary is normal PR CI, normal Make targets, unit tests,
and API/UI diagnostic routes. Those surfaces may plan/render/load only
`development` and `smoke`. They may validate release scope counts and seed-block
declarations from the protocol but do not enumerate release members, render
release images, produce release manifests, execute release inference, or return
release IDs, seeds, hashes, images, manifests, or aggregate metrics. Formal
local/workflow commands remain intentionally explicit and separately guarded.

## Development-only Scale Diagnostic

The diagnostic matrix is a separate, non-gating development artifact, not a
fifth evaluation scope and not part of the 528-case corpus. It has exactly 108
cases with IDs `e1-v2-development-diagnostic-000` through `-107` and seeds
`800000` through `800107`, which cannot overlap any evaluation seed block.

It covers both revisions, all three views, and scale values
`-2.0%`, `-1.5%`, `-1.0%`, `-0.5%`, `+0.5%`, `+1.0%`, `+1.5%`, `+2.0%`.
Those 48 scale-only rows are followed by 12 rows each for scale+translation,
scale+rotation, scale+exposure, scale+medium-defect, and scale+high-defect. Each
12-row block covers both scale endpoint signs across every revision/view pair;
the two defect blocks rotate all six defect types across those pairs.

Each diagnostic record contains:

- true synthetic transform in a clearly labeled offline-truth section;
- image-derived rotation, scale, and shifts in an inference section;
- pre/post foreground fit, silhouette XOR, IoU, and edge error;
- residual pixels and component count;
- anomaly score and final predicted feature;
- whether normalization was applied, kept as identity, or abstained, with reason;
- elapsed normalization time for development comparison only.

The runtime normalization interface never accepts the offline-truth section.
Diagnostic truth is used only after inference to calculate comparison metrics.

## Geometry Normalization Candidates

Both candidates accept only canonical `512x384` reference/inspection RGB bytes
plus frozen config. Foreground is a pixel whose maximum absolute RGB difference
from the median of all border pixels is greater than the locked Chebyshev
threshold `18`. Components use 8-connectivity. The largest component is chosen
by `(-area, min_y, min_x, max_y, max_x)`, making equal-area ties deterministic.

Silhouette XOR is the XOR pixel count divided by the full canvas area. An edge
is a foreground pixel with at least one of its eight neighbors outside the
foreground or canvas. Normalized edge MAE is the mean absolute difference of
the two binary edge canvases. Empty inputs fail foreground validation. Candidate
scores use unrounded `float64` terms:

```text
objective = 0.70 * silhouette_xor_rate + 0.30 * normalized_edge_mae
```

Foreground IoU is a mandatory diagnostic but is not independently optimized.
`objective_before` is the strict identity transform `(0°, 1.0, 0, 0)`, not a
translation-compensated baseline. Improvement is
`(before-after)/max(before,1e-12)`; an exact zero baseline yields `IDENTITY`.
Exact objective comparisons use unrounded values; serialized metrics are
rounded to 8 decimal places. Exact ties use
`(objective, abs(rotation), abs(scale-1), abs(dy)+abs(dx), rotation, scale, dy, dx)`.

Every candidate parameter is a correction mapping inspection content into the
reference frame. With canvas center `C=((width-1)/2,(height-1)/2)`, source point
`p`, counter-clockwise rotation matrix `R`, and candidate `(r,s,dx,dy)`:

```text
q = C + s * R(r) * (p - C) + (dx, dy)
```

Thus positive `dx` moves inspection content right in reference coordinates and
positive `dy` moves it down. Rendering uses the inverse map
`p=C+R(-r)*(q-C-(dx,dy))/s`, Pillow affine transform with `NEAREST` resampling,
and the inspection border-median RGB fill. The exact Pillow version is bound by
the environment lock. Scale, then rotation, then translation is the semantic
order. The core difference model performs its separate translation registration
once after this correction.

### Candidate A — largest-component estimate plus bounded refinement

For each component, sorted x/y coordinates discard `floor(0.01 * area)` values
from each tail; retained integer extrema form the robust width/height. Initial
correction scale is the arithmetic median of `reference_width/inspection_width`
and `reference_height/inspection_height`. PCA orientation uses the analytic
two-by-two covariance formula, normalized to `[-90°,90°)`. When
`(lambda_major-lambda_minor)/max(lambda_major,1) < 0.05`, the initial rotation
is `0°`; otherwise correction rotation is reference angle minus inspection
angle, wrapped to `[-90°,90°)`. Initial translation aligns robust component
medians after scale/rotation. Any unbounded initial translation outside
`[-12,+12]` on either axis returns `TRANSLATION_OUT_OF_RANGE` rather than being
silently clamped.

Candidate A clamps rotation to `[-1.5,+1.5]` degrees and correction scale to
`[1/1.02, 1/0.98]` (`[0.9803921568627451,1.0204081632653061]`), then evaluates
at most 225 full-resolution refinements around the image-derived estimate:

- rotation offsets: `[-0.5, 0.0, +0.5]` degrees;
- scale offsets: `[-0.004, 0.0, +0.004]`;
- translation offsets: every integer pair in `[-2,+2]²`, retaining only final
  translations inside `[-12,+12]²`.

### Candidate B — bounded coarse-to-fine silhouette search

Candidate B obtains only the robust median-based initial translation above,
then downsamples each `512x384` silhouette into `128x96` using 4x4 block
occupancy (`foreground` when at least 8 of 16 pixels are set). It evaluates at
most 1,575 coarse candidates; full-resolution dx/dy are divided by four for the
low-resolution inverse transform:

- rotation: `[-1.5, -1.0, -0.5, 0.0, +0.5, +1.0, +1.5]` degrees;
- correction scale: `[1/1.02, 0.985, 0.990, 0.995, 1.000, 1.005, 1.010, 1.015, 1/0.98]`;
- translation offsets from the initial estimate: `[-4,-2,0,+2,+4]²` pixels,
  retaining only absolute translations inside `[-12,+12]²`.

The best distinct rendered coarse silhouette is refined at full resolution with rotation
offsets `[-0.25, 0, +0.25]`, scale offsets `[-0.002, 0, +0.002]`, and integer
translation offsets `[-1, 0, +1]²`, for at most 81 refinements. Duplicate
clamped parameter transforms and duplicate rendered normalized-image hashes are
evaluated/count once. Candidate counts are unique transforms after clamp/dedupe.
The deterministic worst-case scoring caps are 44,236,800 candidate pixels for A
and 35,278,848 candidate pixels for B; exceeding either declared cap makes that
implementation ineligible.

### Application, confidence, and abstention

The result status is one of `APPLIED`, `IDENTITY`, or `ABSTAIN`.

- `IDENTITY` means valid sufficient foreground but the best transform improves
  objective by less than `5%`; it preserves original bytes, records
  `IDENTITY_BASELINE`, and continues ordinary difference inference. A clean
  identity image must therefore remain eligible for a NORMAL prediction.
- `APPLIED` requires at least `5%` improvement, a distinct rendered runner-up,
  and confidence gap
  `(second_best-best)/max(second_best,1e-12) >= 0.01`.
- `ABSTAIN` is reserved for insufficient/malformed foreground, translation
  outside the supported bound, ambiguous improved alignment, or an unsafe
  optimum simultaneously on both the rotation and scale bounds.

For `APPLIED`, all are true:

- both largest components contain at least 512 pixels;
- the best objective improves on the identity transform by at least `5%`;
- a second-best *distinct normalized-image hash* exists and meets the gap;
- `at_scale_bound AND at_rotation_bound` is false.

Abstention reasons are `INSUFFICIENT_FOREGROUND`,
`TRANSLATION_OUT_OF_RANGE`, `AMBIGUOUS_ALIGNMENT`, and `BOUNDARY_OPTIMUM`.
The trace serializes `at_scale_bound` and `at_rotation_bound` separately.
Unexpected abstention on a supported nuisance is counted as a false positive;
unexpected abstention on a supported defect is counted as a false negative.
It can never hide a gate failure.

### Preregistered candidate selection

Only development data selects the candidate. A candidate is ineligible if it
is nondeterministic, violates dependency guards, exceeds its deterministic
candidate/work-pixel cap, fails any original development gate, worsens
medium/high defect recall below `0.90`, fails trust or v0.1 regression, reduces
any named medium/high diagnostic defect's truth-pixel recall by more than `0.05`
versus identity, or reduces aggregate diagnostic median Dice by more than
`0.01` versus identity.

Among eligible candidates, select the lexicographically best tuple:

1. fewest development nuisance false positives;
2. fewest medium/high defect false negatives;
3. fewest affected-feature mapping errors;
4. highest positive-case median Dice;
5. lowest median post-normalization objective;
6. lowest deterministic worst-case candidate-pixel evaluation count;
7. Candidate A if every prior term ties.

The selection record contains both candidates, rejected reasons, exact metrics,
operation counts, benchmark observations, configuration hashes, selected ID,
and an `implementation_projection_sha256`. That canonical path→SHA projection
includes v2 domain, protocol, generator, geometry A/B, feature mapping,
registration, policy, metrics, diagnostics, protocol/schema config, and the
frozen v1 core dependencies they call. It excludes the selection record, stage
runner/CLI/UI, and later evidence files. Checking in the selection record
therefore cannot create a git-SHA cycle. Freeze binds the final checkout SHA,
selection-record hash, and a recomputed implementation projection; it reruns
development/smoke and rejects a record produced by different implementation
bytes.

Wall-clock runtime is diagnostic, not a correctness/selection gate on variable
hosted hardware. Benchmark records use `perf_counter_ns`, five warmups, one
sample per 108 diagnostic cases, nearest-rank p95, fixed `512x384` inputs, and
CPU/Python/NumPy/Pillow/runner metadata. CI job timeout remains the operational
guard. Smoke is a gate on the already selected candidate; it is not a second
selection dataset. A smoke failure ends this protocol attempt in HOLD rather
than switching candidates.

## Final-mask Feature Mapping

The v2 inference order is:

```text
decode/validate reference and inspection
→ image-derived geometry correction
→ core model translation registration
→ raw difference mask and registered inspection in reference coordinates
→ unchanged structural postprocessing in reference coordinates
→ final predicted mask
→ exclusive ownership mapping
→ predicted feature
```

`feature_mapping.py` accepts final mask bytes, revision, view, and protocol
ownership config. It does not accept an expected feature or authoritative mask.

The protocol defines six ownership layouts (`2 revisions × 3 views`) as
normalized half-open boxes. Coordinates are rasterized with floor for lower
bounds and ceil for upper bounds, then clipped to the image. Pixels are assigned
once in this priority:

1. `hole_left`
2. `hole_right`
3. `top_edge`
4. `bottom_edge`
5. `top_face`

This priority resolves region ownership only; it never forces a prediction.
Revision B's right-hole ownership is shifted by its declared geometry delta.
The same protocol-owned revision/view geometry source drives renderer/oracle
geometry and ownership config; tests reject drift between them.

Ownership label `0` means unmapped. Feature codes `1..5` follow sorted feature
ID order, independent of ownership priority. The ownership-map hash input is
`canonical_json(header) + b"\0" + labels.astype(uint8).tobytes(order="C")`,
where the header contains algorithm `exclusive_half_open_boxes_v2`, revision,
view, width, height, sorted feature IDs, and the priority list. All six hashes
are independently golden-tested and reproducible from protocol bytes alone.

After counting final-mask pixels by owner, apply this exact decision order:

- zero total owned pixels returns `None` / `NO_OWNED_PIXELS`;
- winner-owned pixels fewer than 8 returns `None` /
  `INSUFFICIENT_MAPPED_PIXELS`, even when total owned pixels are at least 8;
- an exact top-count tie returns `None` / `AMBIGUOUS_FEATURE`;
- otherwise if `(winner - runner_up) / winner < 0.10`, return
  `None` / `AMBIGUOUS_FEATURE`;
- otherwise return the winning feature.

Margin uses integer counts without pre-rounding. Exactly `0.10` maps; a value
below `0.10` is ambiguous. The serialized margin is rounded to 8 decimals.
Every result satisfies `sum(owner_counts) + unmapped_positive_pixels ==
final_positive_pixels`.

Null and ambiguous positive cases stay in the feature-mapping denominator.
The trace records final-mask SHA-256, ownership-map SHA-256, sorted per-owner
counts, total owned, winner-owned, final-positive and unmapped counts,
winner/runner-up, margin, and decision reason. Feature ambiguity changes neither
pixel Dice nor IoU denominators.

Normal tests validate authoritative defect masks for development/smoke against
their revision/view ownership layouts. Formal freeze validation performs the
same test for calibration/release without publishing their members. For every
known-feature defect, its authoritative mask must own at least 8 pixels in and
select its declared target feature. This is an offline oracle cross-check, never
a runtime dependency.

## Trace Contract

Geometry trace fields are separate and have one meaning each:

- `pre_normalization_shift_x/y`: robust image-derived translation estimate
  before local search, expressed inspection-to-reference;
- `observed_rotation_degrees` and `observed_scale_ratio`: image-derived
  inspection geometry relative to reference;
- `correction_rotation_degrees` and `correction_scale`: chosen
  inspection-to-reference correction;
- `post_normalization_shift_x/y`: residual shift measured after applying the
  correction;
- `final_model_registration_x/y`: registration used by the difference model;
- `objective_before`, `objective_after`, `objective_improvement_ratio`;
- `confidence_gap`, `at_scale_bound`, `at_rotation_bound`,
  `normalization_status`, and nullable `abstention_reason`.

The old v1 `comparison_shift` remains readable in v1 artifacts but is never
emitted as a v2 final registration field.

## Frozen Thresholds and Gates

The following values are copied without weakening:

- image threshold `0.0025`;
- medium/high defect recall `>= 0.90`;
- nuisance-only false-positive rate `<= 0.05`;
- positive-case median Dice `>= 0.70`;
- affected-feature mapping accuracy `>= 0.95`;
- revision-mismatch publication count `== 0`;
- malformed/corrupted evidence publication count `== 0`;
- bundle verify/re-import `== 100%`;
- split hash overlap `== 0`;
- same-seed manifest equivalence `== true`;
- v0.1.0 regression `== true`.

Mask recall and per-class/per-view Dice remain mandatory diagnostics, not new
post-hoc v0.2 gates.

## Stage Machine and Evidence Seals

The v2 runner exposes separate commands:

```text
development → smoke → freeze-manifests → calibrate → release-test
```

Development and smoke render only their own scopes. `freeze-manifests` requires
a clean checkout and records an exact candidate code SHA, protocol/config hash,
generator version/hash, model/pipeline version/hash, environment lock hash,
development result hash, smoke result hash, threshold, and fresh calibration
and release manifest hashes. It performs no model inference.

Because a Markdown file cannot contain the hash of the commit that contains
itself, the canonical freeze is a sealed JSON artifact created from the clean
candidate code SHA. `E1_V2_FREEZE.md` is an evidence document committed later
and points to that candidate SHA and seal hash. Formal execution occurs from a
clean checkout of the recorded candidate SHA; later evidence commits do not
change the evaluated candidate.

`calibrate` verifies all seal bindings and permits at most one execution in a
formal workflow run/freeze-seal lineage or one sealed local evidence root. On
any gate failure it writes `E1_V2_HOLD`, does not render or execute release_test,
and marks both fresh seed families retired for any future release claim. With
read-only GitHub permissions and no external append-only registry, global
single-use across unrelated workflow reruns cannot be technically guaranteed;
the final evidence records workflow run ID, freeze-seal digest, and the
procedural one-run assertion without overstating enforcement.

`release-test` requires a persisted calibration PASS seal bound to the same
candidate, protocol, generator, model, threshold, and manifests. Any mismatch,
dirty worktree, missing artifact, or changed HEAD fails closed. It executes
release inference, trust boundaries, bundle roundtrip, v0.1 regression, and all
release gates. Artifact verification recomputes seals and overlap proof from
canonical members.

## CI, UI, and Review Boundary

Normal PR CI runs lint, typecheck, unit/integration/security tests, web build,
Chromium E2E, checked-in v1-history integrity verification, v2 development, and exact
48-case v2 smoke. It cannot invoke manifest freeze, calibration, or release
test. CI jobs must not use `continue-on-error` for these checks.

Formal calibration/release execution is one manual workflow with required full
40-hex `freeze_sha`, read-only contents permission, concurrency keyed by that
SHA, and three jobs. The `freeze` job checks out the exact SHA, proves a clean
tree, creates/verifies manifests and seal, and uploads the same-run artifact.
The dependent `calibration` job checks out and re-proves the SHA/tree, downloads
and independently verifies that freeze artifact, then uploads its verified
calibration artifact. The dependent `release-test` job starts only after a PASS
signal, but also downloads and independently verifies both seal lineages before
inference; it never trusts the job-output string alone. Checkout/upload/download
actions are pinned to commit SHAs, checkout uses `persist-credentials: false`,
and every formal job asserts `HEAD == freeze_sha` and an empty status. The
workflow creates no tag, release, comment, or merge.

The bilingual UI labels v2 smoke as diagnostic/non-release evidence and shows
stage status, protocol version, split isolation proof, selected normalization
candidate, trace fields, mapping decision, and limitations without readiness
overclaiming. Existing keyboard/accessibility behavior remains intact.

Before completion, independent read-only reviews cover methodology/leakage,
geometry and defect preservation, feature/denominator semantics, security and
artifact integrity, bilingual UI/accessibility, and release wording. No P0-P2
may remain. At least one actual submitted human GitHub review is required before
the parent PR can become Ready; Codex cannot fabricate that external approval.

## Terminal Decision

The work ends in exactly one state:

- `SHIP — REMEDIATION_READY_FOR_PARENT_INTEGRATION` only if fresh calibration
  and release test pass on the frozen candidate, all automated gates pass,
  overlap is zero, and independent reviews have no unresolved P0-P2; or
- `HOLD` if any calibration, test, trust, integrity, reproducibility,
  methodology, or review gate fails.

Neither state authorizes a merge to `main`, a tag, or a release.
