# E1 authoritative synthetic evaluation protocol v1

Status: `frozen_before_test`

Normative identity:

- Protocol: `mvs-e1` version `1.0.0`
- Suite: `e1-authoritative-synthetic` version `1.0.0`
- Target: v0.2.0 `DEMO_READY_E1_SYNTHETIC_ONLY`
- Schema: [`schemas/e1-evaluation-protocol.v1.json`](../../schemas/e1-evaluation-protocol.v1.json)
- Configuration: [`configs/evaluation/e1-v1.json`](../../configs/evaluation/e1-v1.json)

The JSON configuration is normative for values and counts. This document
defines their evaluation meaning. E1 remains synthetic portfolio evidence; it
does not claim shop-floor accuracy, safety, shipment approval, production
release authority, or `FIELD_READY` status.

## 1. Frozen baseline

E1 is evaluated above the immutable v0.1.0 baseline:

| Binding | Frozen value |
| --- | --- |
| Git commit | `cf7b9ac37d0533f656068199d3275410cf8cc2f8` |
| Tag | `v0.1.0` |
| Golden bundle SHA-256 | `1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7` |
| Pipeline | `registered-difference` `1.0.0` |
| Model | `registered-absolute-difference` `1.0.0` |
| Model artifact SHA-256 | `fb11440ef8cf47e64e17f5f41d50993bab1a386d9ed465f5ac5d49eae26925f8` |
| Baseline configuration SHA-256 | `0a6d7cdf32feeed5aa54b16018af5519adb4a2fa9188f86c259969b88b5129b8` |
| Image threshold | `0.0025` |

The baseline configuration digest covers registration shift, pixel difference
threshold, and registration sample stride. It does not cover the separately
hardcoded image threshold. The downstream E1 protocol/configuration digest must
bind the complete E1 configuration, including `0.0025` and the feature-mapping
rule. The protocol document does not contain its own digest, avoiding a
self-hash cycle; manifests and results bind the canonical protocol digest.

## 2. Dataset composition

E1-full contains exactly 480 cases. E1-mini contains exactly 48 case IDs and is
an intentional strict subset of E1-full.

| Group | E1-mini | E1-full | Evaluation role |
| --- | ---: | ---: | --- |
| Clean controls | 8 | 96 | Normal controls |
| Nuisance-only negatives | 12 | 120 | Supported normal variation |
| Defect positives | 24 | 240 | Detection, mask, and feature truth |
| Trust-boundary cases | 4 | 24 | Fail-closed and abstention behavior |
| Total | 48 | 480 | Frozen profile count |

Trust cases are not inserted into the binary confusion matrix. Therefore the
inference denominators are exactly 44 for mini and 456 for full.

### Split composition

| Split | Clean | Nuisance | Defect | Trust | Total | Permitted use |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Development | 24 | 30 | 60 | 6 | 120 | Algorithm changes and debugging |
| Calibration | 24 | 30 | 60 | 6 | Lock/confirm threshold only |
| Test | 48 | 60 | 120 | 12 | Immutable final evaluation |

Mini selects 12 development, 12 calibration, and 24 test cases, with group
counts `2/3/6/1`, `2/3/6/1`, and `4/6/12/2` respectively. The exact 48 case
IDs are frozen in `dataset_profiles.mini_selection.exact_case_ids`; selection
is not left to implementation-defined ranking. The frozen strata cover both
revisions, all three views, all defect types, all severities, all nuisance
types, and every defect-type/severity pair.

### Leakage rule

The assignment unit is a recipe/seed family, not an individual rendered image.
Development, calibration, and test must have zero overlap for:

- recipe ID;
- seed family;
- reference-image SHA-256;
- inspection-image SHA-256; and
- the canonical case-binding SHA-256 projection, which includes the
  authoritative-mask SHA-256 and case identity.

Clean and nuisance cases intentionally share the one canonical empty-mask
byte representation, so raw empty-mask SHA overlap is expected and explicitly
reported. It is not treated as leakage. Positive-mask hashes and the complete
case-binding projection remain split-disjoint.

Mini/full overlap is required because mini is a subset; it is not split
leakage. Test results may not drive threshold or case-manifest changes. A failed
implementation is repaired using the development set, recorded under a new code
SHA, and rerun without changing the locked test contract. Any protocol,
threshold, generator, split, metric, or gate change requires version 2 and
preservation of v1 configuration and results.

## 3. Deterministic generator and universe

The required generator identity is `mvs-e1-generator` `1.0.0` with recipe
version `1.0.0`. Each split/group owns a non-overlapping uint32 seed block. A
case seed equals its block start plus its zero-based group ordinal. Case IDs use
`e1-{split}-{group}-{ordinal:03d}`.

Every case manifest must bind `case_id`, profile membership, dataset split,
seed family, seed, recipe ID/version, part/revision, view, expected outcome,
support boundary, nullable defect truth, sorted nuisance entries, generator
identity/configuration hash, and source hashes.

The image contract is 512 x 384 pixels. PNG and JPEG are allowed source media;
the canonical model input is metadata-free RGB8 PNG. The authoritative mask is
an 8-bit single-channel PNG of the same dimensions with values only 0 or 255.

The universe contains part `MVS-E1-PLATE-001`, two deliberately distinct
revisions (`rev-A` and `rev-B`), and three views (`front`, `oblique_left`, and
`oblique_right`). Feature IDs are `top_face`, `hole_left`, `hole_right`,
`top_edge`, and `bottom_edge`. The normalized feature boxes are frozen per view
in `universe.feature_regions_by_view` and are part of the generator digest.
The v0.1 identity is used only for release regression; E1 case identity uses
the explicit E1 part and revisions and never substitutes one scope for another.

## 4. Defect taxonomy

Each type has 40 full cases and 4 mini cases. Full allocation is 10 development,
10 calibration, and 20 test cases per type. LOW, MEDIUM, and HIGH each have 80
full and 8 mini positives.

| Type | Roadmap meaning | Family | Target feature set |
| --- | --- | --- | --- |
| `scratch` | Scratch | Appearance | `top_face` |
| `stain` | Stain or discoloration | Appearance | `top_face` |
| `edge_chip` | Edge chip or missing material | Geometry | `top_edge`, `bottom_edge` |
| `burr` | Burr or extra material | Geometry | `top_edge`, `bottom_edge` |
| `blocked_hole` | Blocked or missing hole | Geometry | `hole_left`, `hole_right` |
| `hole_geometry_deviation` | Hole position or diameter deviation | Geometry | `hole_left`, `hole_right` |

The exact LOW/MEDIUM/HIGH pixel/ratio parameters are frozen in the JSON config.
LOW is exploratory but always reported. MEDIUM and HIGH form the primary recall
gate. Each positive has expected outcome `ANOMALY` and a non-empty independent
authoritative mask bound to one defect ID and target feature.

## 5. Nuisance and abstention taxonomy

The nine nuisance types are translation, rotation, scale, exposure,
directional shading, Gaussian blur, sensor noise, JPEG compression, and benign
background/fixture variation. All 120 nuisance-only cases contain only values
from `SUPPORTED_NORMAL_RANGE`, have expected outcome `NORMAL`, and require an
empty authoritative mask. E1 v1 assigns exactly one primary nuisance to each
nuisance case; combined nuisances are deferred to a later protocol version.

For each nuisance parameter, the config freezes three disjoint intervals:

1. supported normal range;
2. an excluded transition interval, which E1 v1 does not generate; and
3. an unsupported/abstain range.

An unsupported case has expected outcome `ABSTAIN` and must publish no accepted
inspection result. Reasons are `UNSUPPORTED_VIEW`, `NUISANCE_OUT_OF_RANGE`,
`REGISTRATION_OUT_OF_RANGE`, `INSUFFICIENT_REFERENCE_COVERAGE`, or
`INVALID_OR_UNTRUSTED_EVIDENCE`. The implementation must not label an extreme,
cropped, unidentified, or unsupported view as normal.

The nuisance marginal allocation is exact: translation, rotation, and scale
have 14 full cases and 2 mini cases each; the other six types have 13 full and
1 mini case each. Combined nuisance cases may use one to three sorted entries,
but all entries in a nuisance-only negative must remain in supported ranges.

## 6. Authoritative mask oracle

Authoritative truth belongs exclusively to the generator. The mask is derived
directly from the defect-generation operation before model execution and may
never read or transform predicted output.

Each case binds these separate lowercase SHA-256 fields:

- `reference_sha256`;
- `inspection_sha256`;
- `authoritative_mask_sha256`; and
- `generator_configuration_sha256`.

Positive masks must be non-empty, binary, dimension-bound, defect-bound, and
feature-bound. Clean and supported-nuisance masks must be valid and empty.
Unexpected emptiness, non-binary values, shape mismatch, corrupt bytes, hash
mismatch, or missing truth binding invalidates the case/run and publishes
nothing. It is never treated as a metric exclusion.

## 7. Threshold lock

The only v1 image-threshold candidate is `0.0025`. Calibration may confirm this
single preregistered value; it may not search alternatives. Pixel difference
threshold 32/255, registration shift 12 px, sample stride 4, and minimum mapped
mask overlap of one pixel are also frozen.

The lock artifact must exist before test execution. If calibration fails, the
v1 result is `HOLD` and the test split is not executed. Calibration confirmation
uses the same four primary performance thresholds frozen in
`threshold_selection.calibration_confirmation`. Post-hoc threshold search,
threshold weakening, or test-set tuning is forbidden. A new value requires a
new protocol version.

## 8. Metrics and formulas

Metrics use the immutable test split for release point estimates unless a gate
explicitly names all trust cases, all splits, or the v0.1 suite. Raw counts and
all slices are always emitted.

### Image level

- `precision = TP / (TP + FP)`
- `recall = TP / (TP + FN)`
- `specificity = TN / (TN + FP)`
- `F1 = 2 * precision * recall / (precision + recall)`
- nuisance-only false-positive rate is anomalous predictions plus unexpected
  abstentions divided by all supported nuisance-only test cases. This
  conservative gate prevents abstention from hiding normal-range failures.
- Average Precision and AUROC use raw anomaly scores on scored test inference
  cases and are accompanied by score coverage.
- Recall is reported by severity and defect type.

An unexpected abstention on a supported positive counts as a false negative for
the gated recall. An unexpected abstention on a supported negative counts as a
false positive for the conservative gated confusion/FPR and is also reported as
an abstention error. AP/AUROC omit an unscored abstention only with an explicit
reason and coverage count; these ranking metrics are not gates.

### Pixel level

- `IoU = intersection / union`
- `Dice = 2 * intersection / (predicted_positive + truth_positive)`
- mask precision and recall use pixel TP/FP/FN.
- A missing or empty predicted mask on a positive receives Dice 0.
- For valid empty truth, an empty predicted mask is correct; a non-empty mask is
  incorrect. Empty-mask accuracy is reported over clean and nuisance cases.

### Engineering and trust level

- Feature accuracy is exact target-feature matches divided by positive test
  cases with known feature truth; wrong, absent, or unmapped output is incorrect.
- Part/revision binding accuracy is exact binding divided by applicable cases.
- Abstention correctness requires the expected reason and zero accepted result.
- Human-disposition/evidence binding uses explicitly synthetic test fixtures
  only and cannot be presented as human UAT.
- Bundle verify/re-import rate is successes divided by all attempted eligible
  bundles, with a nonzero denominator.

Undefined metrics are `null` with a stable reason and raw numerator/denominator.
Proportions receive 95% Wilson intervals. Ranking metrics and median Dice use a
95% stratified percentile bootstrap with seed 424242 and 10,000 replicates.
Ranking resampling is stratified by expected outcome; median Dice resampling is
stratified by defect type. Reports include defect, severity, nuisance, revision,
view, abstention, and trust-scenario slices; weak slices may not be hidden behind
aggregates.

## 9. Locked acceptance gates

| Gate | Operator | Threshold |
| --- | --- | ---: |
| MEDIUM/HIGH defect recall | `>=` | 0.90 |
| Nuisance-only false-positive rate | `<=` | 0.05 |
| Positive-case median Dice | `>=` | 0.70 |
| Affected-feature mapping accuracy | `>=` | 0.95 |
| Revision-mismatch result publications | `==` | 0 |
| Corrupted/malformed-evidence publications | `==` | 0 |
| Evidence bundle verify/re-import rate | `>=` | 1.00 |
| Dataset split hash overlap | `==` | 0 |
| Same-seed manifest equivalence | `is` | true |
| v0.1.0 regression suite | `is` | passing |

Thresholds may not be weakened after calibration or test observation.

## 10. Trust-boundary suite

The 24 cases are frozen in config: 6 development, 6 calibration, and 12 test;
four are in mini. They cover wrong revision/part identity, authoritative-mask
corruption/non-binary/empty/shape failures, unknown feature/pipeline, hash
mismatch, duplicate identity, split leakage, missing reference/disposition,
malformed/oversized image, traversal/symlink/non-regular input, incomplete or
modified bundle, invalid UTF-8/duplicate JSON keys/wrong schema, and unsupported
view/extreme nuisance.

Every trust case expects `ABSTAIN`, a stable machine error code, and zero
accepted publication. Hardlinks are a supplemental platform-specific security
test because portable semantics vary; they are not silently represented as one
of the 24 portable cases.

## 11. Repeatability and evidence

Generate full twice in clean output roots. Canonical dataset/case projections,
source and mask hashes, metrics, and deterministic result projection must match.
Run IDs, timestamps, duration, and absolute paths are excluded only through the
declared projection and must never leak into tracked artifacts.

Each final run records Git SHA and dirty state, canonical protocol digest,
generator version/configuration digest, dataset manifest digest, pipeline/model
identity, threshold source, result digest, environment, every exclusion and
abstention, raw counts, slices, and gate verdicts.

The generator digest projection is frozen in `generator.configuration_projection`.
The bundle gate denominator is the non-empty artifact list in
`repeatability_contract.bundle_eligible_artifacts`; v1 contains the immutable
published v0.1.0 golden bundle. A bounded gallery may contain at most 12 cases.

## 12. Exclusions and limitations

Trust cases remain outside binary/pixel denominators and are reported
separately. Development/calibration are outside release point estimates. LOW is
outside the primary recall gate but inside reports and the Dice gate. Invalid
truth invalidates the run rather than disappearing. Gray transition nuisance
ranges, MVTec, real/private images, and unregistered post-freeze cases are not
E1 inputs.

E1 covers one synthetic part family, two revisions, three rendered views, and a
transparent image-difference baseline. Synthetic masks are easier than
human-labeled real defects. Hash integrity does not prove truth, provenance,
conformance, safety, or legal permission. `DEMO_READY_E1` remains distinct from
human validation and `FIELD_READY`.
