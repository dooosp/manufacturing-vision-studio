# Evaluation plan

## 1. Evaluation question

The v0.1 evaluation asks:

> Does the bounded local workflow behave deterministically and fail closed on
> known synthetic cases while preserving complete identity, review, and evidence
> lineage?

It does not ask whether the system is accurate enough for production, whether
it covers real defect modes, or whether it can replace a qualified inspector.

## 2. Claims and evidence classes

| Claim | Evidence allowed | Release significance |
| --- | --- | --- |
| The seeded workflow works | Checked-in deterministic synthetic golden cases | Release-blocking software gate |
| Equivalent runs are reproducible | Two clean runs, canonical outputs, masks, manifests, and hashes | Release-blocking integrity gate |
| Invalid evidence fails closed | Adversarial fixtures, stable machine codes, and zero publication | Release-blocking safety gate |
| The baseline localizes injected synthetic changes | Synthetic ground-truth mask/feature metrics with exact sample counts | Descriptive demo quality plus preregistered golden expectations |
| The method generalizes to industrial inspection | Representative real held-out field study | Not evaluated; no claim permitted |
| Optional MVTec benchmark performance | Separately acquired licensed data and isolated report | Descriptive non-commercial benchmark only; not a release prerequisite |

## 3. Evaluation units

- Case: one case ID/revision and one part ID/CAD revision.
- Inspection image: one canonical image analyzed against one reference.
- Pixel: included only when an authoritative synthetic/benchmark mask exists.
- Feature: a declared engineering feature or explicit unmapped state.
- Bundle: one exported case and its manifest/payload inventory.
- Run: one pinned code commit, environment, dataset fingerprint, pipeline/model
  version, and configuration hash.

No metric may mix different units without stating the aggregation rule.

## 4. Datasets and splits

### E0 - Seeded synthetic golden suite (required)

Minimum contents:

- One reference image
- At least one nominal inspection
- At least one deterministically defective inspection
- Expected image state, mask availability, and feature mapping state
- Complete recipe, seed, identity, and SHA-256 inventory

E0 is used for exact regression assertions and the end-to-end demo. Its tiny
sample size must be printed in every report and precludes a production accuracy
claim.

### E1 - Expanded synthetic robustness suite (recommended)

Use recipe-level splits with disjoint base assets/seed families. Include
nominal nuisance changes, detectable injected defects, supported registration
shifts, and out-of-bound cases expected to reject/abstain. Freeze its manifest
before tuning thresholds used for a reported evaluation.

### E2 - MVTec AD (optional)

Use only from a user-provided local copy under CC BY-NC-SA 4.0. Keep reports
separate from E0/E1, record category-level counts, and do not make it a setup,
CI, screenshot, hosted-demo, or `DEMO_READY` dependency. See the
[data and licensing policy](../data/data-and-licensing.md).

## 5. Preregistered v0.1 protocol

1. Pin the full Git commit and record whether the worktree is clean.
2. Record OS/architecture, Python/Node/browser versions, relevant dependency
   lock fingerprints, and locale/time-zone handling.
3. Generate or verify E0 from its versioned recipe.
4. Record the dataset/fixture manifest fingerprint.
5. Validate all inputs and v1 documents before analysis.
6. Run the configured deterministic baseline once in a clean artifact directory.
7. Run the same evaluation again in a second clean artifact directory.
8. Canonicalize reports according to the schema. Separate volatile execution
   metadata from deterministic metric content.
9. Compare deterministic result projections, mask bytes, metric values,
   referenced content SHA-256 values, and bundle inventory as declared by their
   determinism contracts. Run IDs and timestamps may differ only when the
   comparison contract names and excludes them.
10. Run the negative-path matrix and assert a stable machine-readable code plus
    zero accepted/published artifacts for every fail-closed case.
11. Export, independently verify, and re-import one fully reviewed case.
12. Compare the original and re-imported case identity and manifest/payload
    SHA-256 sets.
13. Run full validation and real-browser E2E on the same commit.
14. Publish the schema-valid report, comparison artifact, command evidence, and
    unresolved failures without hand-editing measured values.

Two runs are a reproducibility regression gate, not an estimate of long-term
stability across platforms.

## 6. Baseline configuration to report

The report must name the actual implementation values rather than relying on
this prose. For the deterministic image-difference baseline, include at least:

- Canonicalization and EXIF-orientation behavior
- Registration algorithm and maximum allowed shift
- Difference color space/channel aggregation
- Pixel threshold and morphology/post-processing, if any
- Image-level score definition and decision threshold
- Mask encoding and dimensions
- Feature-overlap/mapping rule and unmapped behavior
- Pipeline/model IDs and versions, model artifact hash, and configuration hash

Changing any result-affecting value requires a new `configuration_sha256` and a
fresh evaluation. Threshold selection on E0 must be disclosed because it makes
E0 unsuitable as independent accuracy evidence.

## 7. Metrics

### Release-blocking deterministic metrics

| ID | Metric | v0.1 threshold |
| --- | --- | --- |
| M-DET-01 | Seeded fixture byte equality where declared byte-stable | 100% matching SHA-256 across two clean generations |
| M-DET-02 | Canonical deterministic-result projection equality | Exact equality across two equivalent runs |
| M-DET-03 | Output mask byte/hash equality | Exact equality across two equivalent runs |
| M-DET-04 | Canonical evaluation metric equality | Exact equality across two equivalent runs |
| M-ID-01 | Required identity/schema completeness | 100% of published E0 results |
| M-RT-01 | Export/re-import payload SHA-256 set equality | Exact set equality |
| M-NEG-01 | Fail-closed negative cases with zero publication | 100% of the required negative matrix |

### Seeded golden expectations

- Every E0 inspection matches its preregistered expected nominal/defective state
  at the configured threshold.
- The nominal golden case must not produce a defect mask when its recipe declares
  no pixel change after canonicalization.
- The injected-defect golden case must produce a non-empty mask and score higher
  than the paired nominal case.
- When pixel ground truth exists, report intersection, union, IoU, Dice/F1,
  precision, and recall; the expected pass bound belongs in the frozen fixture
  manifest/test, not a post-hoc report edit.
- When feature truth exists, the mapping must equal the declared feature. When
  it does not exist or overlap is insufficient, the expected result is unmapped.

These exact golden outcomes are release gates. They are not percentages that
generalize beyond E0.

### Descriptive quality metrics

For E1/E2 with sufficient positive and negative samples, report:

- Image-level confusion matrix at the pinned threshold
- Precision, recall/sensitivity, specificity, F1, false-positive rate, and
  false-negative rate
- ROC-AUC and average precision only when both classes exist
- Pixel-level IoU/Dice, precision, and recall when authoritative masks exist
- Feature mapping exact-match rate and unmapped/abstention rate
- Score distribution by recipe/category and failure mode
- Registration failure/rejection rate
- Runtime distribution and peak memory as descriptive environment-specific
  values

Always show numerator, denominator, sample count, and aggregation method. Use
macro/category reporting when a combined number would hide subgroup failures.
Do not calculate AUC, precision, or another undefined statistic on an invalid
sample; emit `null` plus a machine-readable reason.

### Uncertainty and calibration

The tiny E0 suite has no meaningful confidence interval. For a later fixed E1
or field set, preselect confidence-interval/bootstrap methods and calibration
metrics before examining final results. Do not call a raw difference fraction a
probability or confidence score.

## 8. Required negative-path matrix

At minimum, test:

- Part ID, CAD revision, case revision, pipeline/model version, model artifact
  hash, and configuration mismatch
- Missing reference, missing required evidence, unknown schema/pipeline, and
  corrupt/incorrect mask
- Malformed PNG/JPEG, extension/content mismatch, unsupported format, oversized
  encoded file, decoded edge/pixel overflow, and excessive image count
- Dimension mismatch without approved normalization
- Absolute path, traversal, duplicate/conflicting normalized archive path,
  symlink/non-regular entry, compressed/payload/member/aggregate-size overflow,
  excessive compression ratio, omission, and SHA-256 mismatch
- Interrupted/failed publication and attempted partial re-import

For each row, record:

- Fixture ID and mutation from a known-good case
- Expected stable machine-readable code
- Observed code
- Expected/observed published artifact count (must be zero)
- Any temporary artifacts and cleanup evidence

Exception class or message text alone is not a stable acceptance contract.

## 9. Evaluation report contents

The v1 report and its human-readable rendering must include:

- Report/evaluation run ID and timestamp
- Dataset name/origin, synthetic qualifier, split/recipe, counts, and fingerprint
- Applicable license identifier
- Pipeline/model/configuration identity
- Metric definitions, values, numerator/denominator, and thresholds
- Abstentions, rejections, processing errors, and missing/undefined metrics
- Two-run determinism comparison and its result hashes
- Limitations and verdict

The supporting release packet/run manifest must additionally include:

- Full Git commit and clean/dirty state
- Environment and dependency identity
- Per-case outcomes or a content-addressed locator
- Negative-path summary and zero-publication assertion
- Export/re-import comparison
- Source/license notice beyond the v1 `license_id`, plus explicit prohibited
  claims
- Artifact inventory and SHA-256 values

Timestamps and local absolute paths must not be allowed to make otherwise
deterministic metric content change or leak personal filesystem information.

## 10. Claim language

Allowed when supported:

- "The v0.1 synthetic golden workflow passed all N preregistered cases."
- "Equivalent runs produced identical deterministic result projections and
  mask hashes."
- "The bundle verifier detected all N tested tamper/mismatch mutations and
  published zero accepted results."

Not allowed from this evaluation:

- "Production-ready" or "field-validated"
- "100% accurate" without synthetic qualifier, exact counts, and scope
- "Detects manufacturing defects" as a general real-world claim
- "Replaces inspectors" or "automatically approves parts"
- "Safe" based only on fail-closed software tests
- "Commercial benchmark" based on MVTec AD

## 11. Release evidence mapping

The final packet maps each `AC-*` criterion in
[readiness and acceptance](../product/readiness-and-acceptance.md) to:

- Test command and node ID
- Fixture and expected state/machine code
- Output artifact and SHA-256
- Result at the release commit

Any missing mapping is a failed gate, not a documentation TODO after the
`DEMO_READY` decision.
