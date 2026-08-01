# E1 Feasibility and Separability Study Design

**Date:** 2026-08-01

**Status:** Approved written specification

**Study base:** `9fd6d0c600206083fde4fafc874e0226b5df60b3`

**Branch:** `codex/e1-feasibility-separability-study`

**Workspace:** `/Users/jangtaeho/manufacturing-vision-studio-e1-feasibility-separability`

## 1. Decision and purpose

The E1 v2 remediation stopped correctly at `HOLD`: Candidate A and Candidate B
both failed the preregistered development criteria, no candidate was selected,
and Tasks 5–7 did not run. This study does not reopen that selection or attempt
Candidate C. It asks two narrower questions:

1. Does the existing image, threshold, difference model, postprocessor, and
   feature mapper contain enough information to pass when the applied geometric
   transform is known?
2. If not, is the limiting factor geometric raster resampling, the registered
   absolute-difference baseline, or the feature-ownership contract?

The output is a causal diagnosis and a terminal decision, not a release
candidate.

## 2. Non-goals

This study will not:

- modify, rerun, rank, or select Candidate A or Candidate B;
- implement or tune Candidate C;
- change threshold `0.0025`, any acceptance gate, any seed, or any split;
- enumerate or render v2 calibration or release-test members;
- run smoke, calibration, release-test, Task 5, Task 6, or Task 7;
- update `configs/evaluation/e1-v2-candidate-selection.json`;
- claim that a known-parameter inverse is a deployable inference algorithm;
- connect to FreeCAD or modify `/Users/jangtaeho/freecad-live`;
- push, open a PR, merge, tag, or publish a release.

## 3. Provenance and preservation

The study is a new local stacked branch from exact E1 v2 `HOLD` commit
`9fd6d0c`. The source branch `codex/e1-v2-scale-feature-remediation` remains
unchanged.

After the study code, schemas, and protocol are implemented and frozen—but
before any Phase 1 or Phase 2 execution—a retention audit binds:

- the base commit;
- the checked selection record and its self-hash;
- Candidate A and Candidate B raw artifact hashes;
- the Task 4 report, progress ledger, and negative-result evidence;
- the v1 historical `HOLD` integrity result;
- the protocol, schema, generator, model, feature-mapping, and metric hashes used
  by the study.
- a study-specific complete implementation projection covering every study
  module, config, schema, and retained dependency reachable from the performance
  commands.

The audit classifies code and evidence at function or responsibility level:

| Classification | Content |
| --- | --- |
| Retain | development diagnostic matrix, split guards, canonical metric calculations, truth-erasing runtime input, final-mask ownership mapping, v1 history verification, Task 4 negative evidence |
| Isolate | Candidate A/B search and normalization, candidate ranking, candidate selection loader, candidate work caps, candidate-specific benchmarking and constants |
| Re-review | candidate-coupled protocol fields, legacy development-template planning, ownership assumptions, and any source whose change would invalidate the historical implementation projection |

Isolation means the study runner cannot call Candidate A/B alignment or
comparison functions. It does not mean deleting historical source or evidence.
The retention verifier may parse the historical selection record solely to
verify its `HOLD/null` semantics; no performance runner may load it as an
executable selection.

## 4. Terminology and upper-bound limitation

The implementation uses the name **known-transform upper bound**, not "perfect
oracle normalization." The generator's scale operation uses rounded resize and
integer crop/paste, while the correction is a continuous inverse affine. The
forward rasterization loses information and cannot be perfectly inverted even
when its parameters are known.

For the diagnostic forward transform

```text
q = C + f R(a) (p - C) + t
```

the correction parameters are fixed as

```text
s = 1 / f
r = -a
d = -(1 / f) R(-a) t
```

These are correction parameters. The Pillow output-to-input affine calculation
must not invert them a second time.

## 5. Selected two-stage approach

Three approaches were considered:

1. **Selected:** validate the exact 108-row diagnostic matrix, then conditionally
   run the 120-row development study.
2. Modify the development generator first and run all 120 rows immediately.
   This is more invasive and makes inverse-math or resampling defects harder to
   distinguish from generator-provenance defects.
3. Use a notebook or one-off script. This is quicker but does not provide a
   reviewable, hash-bound, fail-closed evidence trail.

The selected approach creates a small, standalone, development-only study
surface. It accepts no arbitrary evaluation scope. Its constrained dependency
closure excludes candidate selection and formal release entry points, while
tests and audit evidence acknowledge that broader repository modules still
contain those capabilities.

## 6. Architecture

The implementation plan will create focused components with these boundaries:

### 6.1 Study protocol

A checked, closed-schema study configuration fixes:

- base commit and historical evidence hashes;
- exact 108 diagnostic IDs and seed bindings;
- conditional development scope and exact 120-case counts;
- resampling modes in the fixed order `NEAREST`, `BILINEAR`, `BICUBIC`;
- inverse-transform formula/version and border-fill rule;
- threshold `0.0025`;
- diagnostic preservation criteria and existing development gates;
- feature-oracle requirements;
- artifact paths, schemas, and single-run policy.

No command-line option may replace these fields.

### 6.2 Known-transform normalizer

A standalone study module will:

- consume an explicit diagnostic plan or offline applied-transform proof;
- validate canonical `512x384` RGB inputs;
- derive the fixed correction parameters;
- use identical inverse coefficients and median-border fill for all three
  resampling modes;
- canonicalize output PNG bytes;
- return immutable normalized bytes and a complete transform trace.

It will not import or invoke Candidate A/B alignment entry points. NEAREST output
must match the existing shared affine convention on fixed fixtures.

### 6.3 Study inference adapter

The offline adapter receives only reference bytes, inspection bytes, a
precomputed normalized result, revision/view identity, and frozen protocol
configuration. It composes the unchanged difference model, core integer
registration, structural postprocessing, final-mask ownership mapping, score
calculation, and threshold classification.

Generator truth, case IDs, seeds, expected labels, nuisance metadata, and
authoritative masks cannot enter the model, postprocessor, mapper, or scoring
calls. Truth is joined only after the prediction returns. Runtime modules do not
import the study package.

Historical implementation-projection files will not be edited merely to expose
a study seam. If orchestration must be duplicated in the study adapter, parity
tests will bind it to the unchanged runtime pipeline.

The study code is split into explicit layers:

- `study_inference_v2`: truth-free input, unchanged model/postfilter/mapper
  composition, and result types;
- `known_transform_v2`: inverse coefficients, resampling, canonical output, and
  transform trace;
- `study_truth_v2`: diagnostic/development rendering, applied-transform proof,
  authoritative-mask joins, and metric observations;
- `study_protocol_v2`: closed configuration and frozen gates;
- `study_artifacts_v2`: canonical evidence writing and verification;
- `study_runner_v2`: Phase 0/1/2 state machine with no scope parameter.

The performance-command dependency allowlist is limited to those study modules
and these retained modules:

- `canonical`, `canonical_png`, `images`, and the core `model`;
- `e1.domain`, `e1.model`, `e1.feature_mapping`, `e1.protocol_v2`, and
  `e1.metrics_v2`;
- `e1.domain_v2`, `e1.generator`, `e1.generator_v2`, and `e1.oracle` only inside
  the offline truth layer.

This is the direct-import allowlist for study-owned production modules. The
complete implementation projection additionally records every retained
transitive repository dependency. For example, the unchanged feature mapper
reaches the canonical decoder through `e1.oracle`, and `e1.generator_v2`
reaches legacy generator/protocol modules. These retained transitive imports are
permitted only when the projected bytes and expected path are exact; they do not
authorize study-owned direct access to truth or protected scopes.

Production study modules must not directly import `e1.policy_v2`, `e1.geometry`,
`e1.geometry_search`, or `e1.diagnostics_v2`. Test-only parity/matrix checks may
import them but cannot be dependencies of an experiment command. The frozen
108-row config carries the complete plan projection so Phase 1 does not import
the candidate-comparison module at runtime.

`DevelopmentCorpusProvider` is the only wrapper around `E1V2Generator`. It has
no scope argument and calls `plan_cases(EvaluationScope.DEVELOPMENT)` with a
literal. Static dependency checks reject forbidden imports and protected-scope
enum references; dynamic tests replace protected planning/rendering with hard
failures and record the actual requested scope.

### 6.4 Evidence writer and verifier

The writer produces canonical JSON with duplicate-key rejection, finite-number
validation, closed schemas, self-hashes, input hashes, code projections, and
deterministic ordering. A separate verifier recomputes every portable binding.
Elapsed time is diagnostic metadata and never a gate.

## 7. Phase 0 — Retention audit

Phase 0 runs only after the study-owned code, config, and schemas are frozen. It
writes `retention-audit.json` before any performance experiment command can run.
The audit must prove:

- base `9fd6d0c` and the source HOLD outcome;
- selected candidate remains `null`;
- Candidate A raw SHA-256 is
  `ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84`;
- Candidate B raw SHA-256 is
  `983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029`;
- the local Task 4 report raw SHA-256 is
  `b6a2093082aa63631adb233c282466539720281ab96b53bc3928cf292efc8835`;
- the local SDD progress ledger raw SHA-256 is
  `fcef0c3b22b962f185911cc74bdad45f1bd2860c42ae8e59bac76d6741c13ea7`;
- the complete study implementation projection matches the frozen allowlist;
- the performance-command closure contains no forbidden imports or call sites
  for candidate comparison, selection mutation, calibration, release test, or
  FreeCAD;
- `DevelopmentCorpusProvider` is the only reachable v2 planning adapter and has
  no externally supplied scope;
- v1 historical evidence remains unchanged and verifies as `HOLD`.

Failure produces `STUDY_INVALID` and blocks every later phase.

## 8. Phase 1 — Exact 108-row diagnostic ablation

### 8.1 Input boundary

Phase 1 consumes only the existing exact `ScaleDiagnosticPlan` matrix with IDs
`e1-v2-development-diagnostic-000` through `-107`. The command accepts no scope,
seed override, row filter, resampling override, or output-dependent retry flag.

It hard-checks:

- exactly 108 unique IDs and the preregistered seed bindings;
- disjointness from v2 evaluation seed blocks;
- transform bounds and finite values;
- canonical reference, inspection, and authoritative-mask bytes;
- no requested or emitted v2 calibration/release members.

### 8.2 Execution

Every row runs all three fixed resampling modes. The forward order remains
scale, rotation, translation, then exposure. The study reverses geometry only;
it does not erase or compensate exposure.

The comparison called `identity` retains the existing diagnostic definition; it
is not a second inference pass with identity correction. Decode the canonical
reference and unnormalized inspection RGB bytes, compute the per-channel
absolute difference in signed integer arithmetic, and mark a pixel when the
maximum channel difference is `>= 32`. Identity recall and Dice are calculated
from that mask. Study recall and Dice are calculated from the verified final
postprocessed prediction mask. Recall-drop and Dice-drop denominators include
defect rows only, while medium/high classification recall includes every
medium/high diagnostic defect row.

Each mode records:

- exact forward and correction parameters;
- normalized image hash;
- pre/post alignment objective and components;
- core registration and postprocessing trace;
- anomaly classification and feature mapping;
- truth recall, Dice, IoU, and classification metrics computed offline;
- residual pixels overall and in the fixed reference-boundary band.

The reference-boundary band is frozen as follows: compute the median RGB of the
one-pixel image border with each corner included once; mark foreground where the
maximum absolute channel distance from that median is greater than `18`; retain
the largest 8-connected component using `(-area, min_y, min_x, max_y, max_x)`
ordering; mark its pixels that touch background in any 8-neighbor direction;
and Chebyshev-dilate that boundary by exactly 3 pixels. The boundary residual is
the count of final predicted-mask positives inside this band. The artifact also
records total positives and `outside_boundary_residual = total - boundary`.

The three modes are ablations, not candidates. They are not ranked or selected.

### 8.3 Promotion rule

A resampling mode is diagnostic-eligible only when all rows complete, every
portable binding verifies, and it satisfies the existing diagnostic preservation
rules:

- maximum per-case truth-pixel recall drop versus identity `<= 0.05`;
- aggregate median Dice drop versus identity `<= 0.01`;
- medium/high classification recall `>= 0.90`.

If no fixed mode is diagnostic-eligible, the study records
`KNOWN_TRANSFORM_DIAGNOSTIC_FAILED` and stops before Phase 2. Candidate C is
forbidden.

If at least one mode is diagnostic-eligible, every mode's evidence is retained
and Phase 2 becomes authorized. Eligibility does not select or freeze a runtime
candidate.

Pre-execution repeated-fixture tests establish deterministic implementation
behavior. The single full 108-row execution does not make a cross-run
determinism claim.

Immediately before its first diagnostic row, Phase 1 atomically publishes an
immutable execution claim binding the execution commit, protocol hash, fixed
artifact root, phase name, and expected row/mode counts. The existence of that
claim blocks another Phase 1 attempt even if the process later fails. An
incomplete claimed phase is `STUDY_INVALID`; a retry requires a separately
approved protocol version and artifact root rather than an output-dependent
rerun.

## 9. Feature-ownership oracle

The feature oracle is candidate-independent and runs after Phase 0 regardless of
whether Phase 1 promotes to Phase 2. For every development defect case, it sends
the authoritative mask directly to the frozen exclusive ownership map outside
runtime inference and compares the result with the generator target feature.

It requires:

- exact target-feature agreement for every evaluable synthetic defect (`100%`);
- at least 8 target-owned pixels per case;
- `owned + unmapped == authoritative positive pixels` for every case;
- zero ambiguous, null, or wrong-feature results;
- exact ownership-map hash binding for every revision/view layout.

The `100%` threshold resolves the earlier phrase "near 100%": deterministic
synthetic truth and its own ownership contract must agree exactly.

Any violation records `FEATURE_CONTRACT_FAILED`, blocks Phase 2 interpretation,
and requires a separately versioned protocol/ownership repair before model work.

Predicted-feature analysis, when present, uses only the known-transform study
output. Candidate A/B policies are not rerun.

## 10. Phase 2 — Conditional 120-row development upper bound

Phase 2 runs only when Phase 0 passes, at least one Phase 1 mode is
diagnostic-eligible, and the feature oracle passes.

### 10.1 Scope guard

The runner requests exactly `EvaluationScope.DEVELOPMENT` and verifies the
fixed counts:

- clean: 24;
- nuisance: 30;
- defect: 60;
- trust boundary: 6;
- total: 120.

No study API exposes a scope argument. Tests replace calibration and release
planning or rendering with hard failures and assert zero calls and zero emitted
members. This constrains the study command; it does not claim those capabilities
are absent from the repository's general generator.

The scope audit records the ordered unique v2 scope projection as exactly
`['development']` and records one external request made by
`DevelopmentCorpusProvider`. Calls made internally by the unchanged generator
to revalidate a development plan's membership remain development-only and are
recorded separately; they do not change the external request count and are not
misreported as protected-scope requests.

The existing v2 generator internally obtains retired v1 templates by planning a
legacy FULL profile and filtering it. This study treats that as a documented
legacy template dependency, not as v2 calibration/release authorization. It may
emit only v2 development IDs and cannot use a retired v1 member as formal v2
evidence. The scope audit records this caveat explicitly.

### 10.2 Applied-transform proof

The development generator does not expose a public signed transform. A
study-only immutable sidecar derives the actual sign and magnitude from the
generator-owned render plan, nuisance specification, and seed logic—not from
case IDs or expected results.

Before normalization, the sidecar must reproduce the generated nuisance image
byte-for-byte using the frozen generator primitive. Any hash mismatch records
`APPLIED_TRANSFORM_PROOF_FAILED` and invalidates the run.

Geometric nuisance rows receive their known correction. Non-geometric nuisance,
clean, defect, and trust rows receive an explicit identity correction. For the
six trust-boundary rows this is a binding-only sidecar record; it is never sent
to image inference because those rows represent dedicated validation stimuli,
not model-performance images. The sidecar is never added to
`E1V2InferenceInput` or any runtime API.

### 10.3 Development evaluation

Every Phase 1-eligible resampling mode binds the exact 120-member development
set. The 114 clean, nuisance, and defect image members run through the unchanged
threshold and pipeline. The six trust-boundary members are retained as
binding/integrity entries with explicit identity-correction records; they are
not inferred, do not enter the four performance denominators, and make no new
trust-boundary outcome claim. This preserves the existing dedicated-executor
boundary instead of treating identity images as adversarial trust stimuli. The
study evaluates only the frozen performance/separability gates whose
denominators are present in that 120-row artifact, without changing thresholds
or denominator semantics:

- medium/high defect recall `>= 0.90`;
- nuisance-only false-positive rate `<= 0.05`;
- positive-case median Dice `>= 0.70`;
- affected-feature mapping accuracy `>= 0.95`.

It separately requires this exact study integrity set:

- historical selection remains `HOLD/null` with the pinned record hash;
- v1 history verification remains `HOLD`;
- the public v0.1 regression suite passes;
- development case bindings verify for exactly 120 emitted cases;
- requested v2 scopes equal `['development']` and protected emissions equal 0;
- the 108 diagnostic seeds have zero overlap with every declared evaluation seed
  block, checked from protocol declarations without rendering protected members;
- every checked study artifact verifies (`study_artifact_verify_rate == 1.0`);
- repeated small fixtures produce identical canonical bytes and hashes.

The following original gates are explicitly `NOT_APPLICABLE` and cannot be used
to claim study or candidate eligibility:

- `bundle_verify_reimport_rate`, because the study publishes no bundle;
- `dataset_split_hash_overlap` over development/calibration/test members, because
  protected members are not enumerated; only declared seed-block disjointness is
  checked;
- `same_seed_manifest_equivalence` over two FULL-profile runs, because the study
  authorizes one full execution per phase;
- publication-count gates, because the local study publishes nothing.

A failed retained integrity control makes the study invalid; it is not counted
as model performance. A `NOT_APPLICABLE` control is never serialized as PASS.

These controls demonstrate a known-transform upper bound, not candidate
eligibility. The study never upgrades unretained execution-time proof, claims a
second full-run determinism check, or marks a resampling mode as selectable.

No best mode is selected. The result records the set of fixed modes that pass
all gates.

Phase 2 uses the same immutable execution-claim rule as Phase 1, binding 120
members, 114 inference rows per eligible mode, six binding-only trust rows, and
the exact eligible-mode set before the first performance inference. An
incomplete claimed Phase 2 is `STUDY_INVALID` and cannot be retried under the
same protocol/artifact root.

## 11. Terminal decision table

| Condition | Terminal decision | Allowed next action |
| --- | --- | --- |
| Retention, provenance, scope, or evidence verification fails | `STUDY_INVALID` | Repair evidence machinery only; no performance conclusion |
| Feature oracle fails | `FEATURE_CONTRACT_FAILED` | New protocol/ownership design; do not alter model |
| No Phase 1 mode is eligible | `KNOWN_TRANSFORM_DIAGNOSTIC_FAILED` | End affine-candidate search; analyze resampling/baseline residual evidence |
| Phase 1 passes but no Phase 2 mode passes | `DIFFERENCE_BASELINE_LIMITED` | Preserve negative result; Candidate C prohibited; a new model family needs a new protocol |
| At least one Phase 2 mode passes and feature oracle passes | `TRANSFORM_ESTIMATION_LIMITED` | A separate approved plan may design exactly one evidence-based Candidate C |

The table is evaluated top-to-bottom: study validity has first priority and a
feature-contract failure has priority over transform-performance conclusions.
If Phase 1 fails, the independent feature-oracle result is still retained even
though Phase 2 remains forbidden.

No decision automatically starts Candidate C, smoke, calibration, release test,
FreeCAD integration, or publication.

## 12. Artifacts

The checked evidence set is separated by responsibility:

- `retention-audit.json`;
- `scope-audit.json`;
- `phase-1-execution-claim.json`;
- `known-transform-diagnostic-108.json`;
- `feature-ownership-oracle.json`;
- conditional `phase-2-execution-claim.json`;
- conditional `known-transform-development-120.json`;
- `decision.json`;
- a concise human-readable study report.

Each canonical result binds:

- base and execution commit SHAs as distinct fields;
- protocol/configuration/schema hashes;
- complete study-specific implementation projection and explicit dependency
  allowlist;
- exact case/seed/input-image hashes;
- resampling mode and Pillow/NumPy/Python versions;
- numerator, denominator, exclusions, and per-slice metrics;
- upstream artifact hashes;
- self-hash and terminal eligibility flags.

Large diagnostic images remain ignored local data. Their manifest, hashes, and
reconstruction recipe are checked evidence. Every result is marked
`development_only=true`, `selection_eligible=false`, and
`release_claim_allowed=false`.

## 13. Fail-closed behavior

The study aborts without a performance conclusion on:

- missing or changed base artifacts;
- noncanonical or oversized input;
- duplicate JSON keys or nonfinite values;
- transform proof mismatch;
- an unexpected ID, seed, count, or scope;
- any calibration/release planning or rendering attempt;
- incomplete rows or denominator mismatch;
- artifact schema, self-hash, projection, or dependency mismatch;
- an attempt to overwrite an existing completed experiment artifact.

An infrastructure failure is `STUDY_INVALID`, not a failed model gate. A model
gate is evaluated only from a complete verified artifact.

## 14. Test strategy

Before the first full experiment, tests must prove:

- inverse scale/rotation/translation sign, order, center, and endpoint behavior;
- NEAREST byte parity with the frozen affine convention;
- identical affine coefficients/fill across NEAREST/BILINEAR/BICUBIC;
- asymmetric fixtures catch double inversion and translation-order errors;
- source and nested evidence are immutable and defensively exported;
- runtime signatures and imports contain no truth/seed/transform sidecar;
- production study imports match the allowlist and forbidden modules occur only
  in parity/contract tests;
- truth joins only after inference;
- exact 108-row membership and development 120-row membership;
- calibration/release functions fail if reached;
- original bundle, full-profile same-seed, split-member-overlap, and publication
  gates are recorded as `NOT_APPLICABLE`, never silently passed;
- feature ownership conservation, thresholds, ties, and all six layout hashes;
- artifact canonicalization, tamper rejection, and overwrite refusal;
- Phase 2 cannot run without verified Phase 0, Phase 1, and feature-oracle gates;
- existing selection remains `HOLD/null` and A/B comparison is never called;
- preserved v1 history and the complete existing test suite still pass.

Unit and small-fixture tests may run freely. The full 108-row study runs once
after preregistration and implementation review. The conditional 120-row study
runs once only if its verified prerequisite artifact authorizes it. A complete
performance artifact is never rerun to search for a favorable result.

## 15. Completion boundary

The implementation is complete when it produces one verified terminal decision
from the table above, preserves the base HOLD history, and leaves no path to
formal release stages. The branch remains local until the user separately
authorizes remote publication and the unpublished E1 v2 base is pinned.
