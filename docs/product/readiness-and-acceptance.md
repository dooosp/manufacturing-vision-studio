# Readiness and acceptance

## 1. Readiness vocabulary

Readiness words describe different evidence. They are not interchangeable.

| State | Meaning | This project |
| --- | --- | --- |
| `IDEA` | Mission exists; boundaries are not testable | Passed |
| `RESEARCHED` | User need, adjacent work, and data options are understood | Passed |
| `SPEC_READY` | Contracts, acceptance criteria, data policy, and evaluation are defined | Requires all spec review findings resolved |
| `IMPLEMENTING` | The bounded slice is being built; readiness is not yet claimed | Expected during v0.1 work |
| `DEMO_READY` | The bounded synthetic/local demo and all release gates pass | v0.1 target |
| `HUMAN_VALIDATION` | Intended users have exercised a defined workflow | Future, not implied |
| `FIELD_READY` | A specific real process/site has supplied sufficient validation and controls | Future, out of scope |
| `ARCHIVED` | Work is intentionally stopped with evidence and rationale preserved | Not planned |

`HOLD` is a release decision, not maturity theater. Use it only when a specific
non-fabricable blocker remains after safe repair. Record the blocker, evidence,
and smallest next action.

## 2. DEMO_READY definition

`DEMO_READY` means all of the following are true for the versioned local demo:

- A clean local setup can run the seeded synthetic journey.
- Reference, nominal, and defective fixtures are deterministic where specified.
- Analysis results are tied to complete v1 identity and hashes.
- The four human dispositions work and remain separate from model output.
- Evidence export and re-import independently verify.
- Required failure cases fail closed and publish no accepted result.
- Unit, integration, full validation, and real-browser E2E commands pass.
- Repeated evaluation produces equivalent canonical metrics/artifacts.
- English and Korean core labels plus baseline accessibility checks pass.
- No private data, credential, network access, or optional dataset is required.
- Product, security, and accessibility reviews have no unresolved blocking
  findings.
- Results, sample counts, data origin, license, and limitations are visible.
- No wording claims production, shop-floor, safety, or real manufacturing
  validation.

Passing a tiny synthetic golden set is a deterministic software acceptance
test. It is not an accuracy estimate and must never be rendered as `100%
accurate` without the sample count and synthetic qualifier.

## 3. FIELD_READY definition

`FIELD_READY` is assessed for one named site, part family, camera/cell,
inspection instruction, and accountable process owner. It would require, at a
minimum:

- Authorized, representative real data covering seasons/shifts, lots,
  materials, machines, operators, cameras, and known defect modes
- A documented sampling plan and split that prevents lot/time/part leakage
- Ground truth adjudication by qualified reviewers and disagreement analysis
- Measurement system analysis, repeatability/reproducibility evidence, and
  calibrated capture controls where applicable
- Pre-agreed false-accept/false-reject costs and operating thresholds
- Confidence intervals, subgroup results, failure-mode coverage, and drift
  monitoring on data not used for development
- Integration validation for camera, PLC/MES/QMS, retention, identity, and
  recovery behavior
- Security/privacy review, access control, audit records, backup, incident
  response, and model/configuration change control
- Safe degraded/manual procedure, rollback, operator training, and accountable
  sign-off
- Applicable legal, contractual, regulatory, safety, and quality-system review

None of these is demonstrated by v0.1. Missing field data or hardware does not
block `DEMO_READY`; it blocks only a later field claim.

## 4. Acceptance criteria

Each release criterion must be linked in the final evidence packet to a command
or pytest node ID, fixture, expected machine code where relevant, and generated
artifact/hash. Narrative statements alone do not pass a criterion.

### Product journey

| ID | Observable criterion | Required evidence |
| --- | --- | --- |
| AC-P01 | A user completes create/open -> import -> analyze -> review -> export -> verify locally | Real-browser E2E plus bundle path/hash |
| AC-P02 | The case view continuously exposes part ID, CAD revision, case revision, pipeline/model versions, and configuration identity | Browser assertion or screenshot plus schema-validated result |
| AC-P03 | `accept`, `reject`, `needs_review`, and `model_error` round-trip using exact lowercase stored values | Parameterized API/persistence/UI test |
| AC-P04 | Model result remains unchanged after human disposition; both appear in evidence | Before/after artifact hashes and bundle assertion |
| AC-P05 | A missing justified feature mapping is shown as unmapped/unknown rather than a fabricated feature | Fixture and UI/API assertion |
| AC-P06 | Core journey labels work in English and Korean without changing stored contract values | Locale E2E and artifact equality assertion |

### Identity, data, and deterministic analysis

| ID | Observable criterion | Required evidence |
| --- | --- | --- |
| AC-I01 | Every published result validates against v1 schema and carries complete part/case/pipeline/model/configuration identity | Schema validation tests and one result artifact |
| AC-I02 | A part, CAD revision, case revision, pipeline/model, or configuration mismatch stops processing | Negative fixtures, stable machine codes, zero published artifacts |
| AC-D01 | Equivalent seeded fixture generation is byte-stable where the generator contract declares it stable | Two clean runs and SHA-256 comparison |
| AC-D02 | Equivalent canonical inputs and configuration produce identical deterministic result projections, mask bytes, and content hashes; run IDs/timestamps are excluded only by an explicit comparison contract | Two independent analysis runs and comparison artifact |
| AC-D03 | PNG/JPEG content and decoded limits are enforced: 25 MiB/file, 8192 px/edge, 40 MP, and 64 inspection images/case | Boundary tests including metadata/extension spoofing |
| AC-D04 | Unsupported, malformed, oversized, decompression-risk, non-regular, symlink, and unsafe-path inputs fail closed | Adversarial fixture matrix, stable machine codes, zero publication |
| AC-D05 | Dimension mismatch is rejected unless an explicit approved normalization is represented in the contract/configuration | Required negative test; positive/configuration-hash test only if normalization ships |
| AC-D06 | Masks are 8-bit single-channel PNG and match analyzed dimensions | Decoder/property assertions against exported mask |

### Evidence integrity

| ID | Observable criterion | Required evidence |
| --- | --- | --- |
| AC-E01 | A complete reviewed case exports a schema-valid bundle with all required payloads, limitations, and evaluation metadata | Export test, manifest, inventory, SHA-256 set |
| AC-E02 | Export -> independent verify -> re-import preserves the same manifest/payload SHA-256 set and case identity | Round-trip integration test and comparison artifact |
| AC-E03 | Payload/manifest tamper, omission, duplicate/conflicting path, unsafe archive path, symlink-like entry, unknown schema/pipeline, or hash mismatch fails closed | Adversarial archive matrix, stable machine codes, zero publication |
| AC-E04 | The 64 MiB ZIP, 100-payload, 25 MiB/member, 128 MiB uncompressed, and 100:1 compression-ratio bounds are enforced before unsafe allocation/extraction | Boundary tests or documented safe simulation |
| AC-E05 | Verification never treats a filename, archive order, or untrusted manifest alone as proof of identity | Mutation tests across ordering/naming/identity |

### Evaluation and claims

| ID | Observable criterion | Required evidence |
| --- | --- | --- |
| AC-V01 | The seeded suite contains at least one reference, one nominal inspection, and one synthetic defective inspection with declared truth | Dataset inventory and fixture hashes |
| AC-V02 | The nominal and defective seeded outcomes match their preregistered expected states; sample counts are reported | Evaluation report and golden assertions |
| AC-V03 | Two equivalent evaluation runs produce identical canonical metric values, deterministic result projections, masks, and content hashes named by the comparison contract | Run manifests and deterministic comparison |
| AC-V04 | Combined evaluation evidence records data origin, split/recipe, counts, versions, configuration hash, limitations, failures, and abstentions | Schema-valid evaluation report plus supporting run manifest |
| AC-V05 | Statistical metrics from tiny or single-class samples are omitted/null with a reason rather than misleadingly computed | Edge-case evaluation tests |
| AC-V06 | Optional MVTec execution is isolated, license-labeled, and not required by setup, demo, tests, or release | Clean offline run without dataset; optional adapter test if present |

### UX, safety, and release evidence

| ID | Observable criterion | Required evidence |
| --- | --- | --- |
| AC-U01 | Keyboard use, visible focus, accessible names, associated errors, and non-color-only status pass the defined browser checks | Automated accessibility/browser evidence plus manual checklist |
| AC-U02 | The UI and exported evidence state that the system is synthetic/demo-only and not a production release authority | Content assertions in UI and bundle |
| AC-S01 | No secret, private dataset, absolute local path, or personal information is present in tracked demo artifacts | Repository scan and bundle scan |
| AC-S02 | Required negative paths return stable machine-readable codes without stack traces or partial accepted publication | API/integration assertions and artifact count |
| AC-R01 | `uv run ruff check .`, `uv run mypy src`, `uv run pytest`, `npm --prefix web run check`, `npm --prefix web run test:e2e`, and `make validate` pass in the declared environment | Captured command output and exit codes |
| AC-R02 | Security, skeptical product, and accessibility reviews contain no unresolved blocking findings | Versioned review reports |
| AC-R03 | The final packet records files/commits, command results, evaluation/browser evidence, known limitations, and exactly one `DEMO_READY` or `HOLD` decision | Final packet review |

## 5. Decision rule

The release coordinator may declare `DEMO_READY` only when every applicable
criterion above is evidenced and all required commands pass at the same commit.
An optional adapter criterion is applicable only when that adapter ships.

If evidence is missing, use `HOLD` with the exact missing criterion. Do not
weaken a criterion, replace a failed command with narrative, or treat
`FIELD_READY` work as necessary for the bounded demo.

## 6. Release decision template

```text
Decision: DEMO_READY | HOLD
Commit: <full SHA>
Environment: <OS/runtime/browser summary>
Synthetic dataset fingerprint: <SHA-256 or manifest hash>
Evaluation report: <path and SHA-256>
Browser evidence: <path and SHA-256>
Passing commands: <commands and exit codes>
Acceptance map: <AC ID -> test/artifact>
Blocking findings: <none or IDs>
Known limitations: <versioned path>
Field readiness: NOT ASSESSED
Next milestone: <one bounded recommendation>
```
