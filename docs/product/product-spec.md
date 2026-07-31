# Product specification

## 1. Problem

Typical anomaly-detection demos stop at an image score or a red overlay. That
is insufficient for an engineering review because the output may not say which
part revision was inspected, which pipeline produced the result, what feature
was affected, who reviewed it, or whether the evidence still matches its
manifest.

Manufacturing Vision Studio demonstrates a traceable alternative:

```text
declared part and revision
  -> reference and inspection images
  -> deterministic anomaly evidence
  -> engineering feature or explicit unmapped state
  -> human disposition
  -> verifiable evidence bundle
```

The product is local-first and intentionally narrow. It demonstrates an
evidence contract and review workflow on synthetic data. It does not establish
fitness for a real inspection process.

## 2. Personas

### P1 - Manufacturing or quality engineer (primary)

- Goal: review an image for a known part revision and preserve why a decision
  was made.
- Needs: unambiguous identity, a readable overlay, access to the original
  image, model/configuration lineage, and a simple review decision.
- Risk: treating model output as final authority or reviewing the wrong
  revision.
- Product response: show identity throughout the journey, require an explicit
  disposition, and fail closed on mismatch.

### P2 - Engineering reviewer or evidence auditor (secondary)

- Goal: reproduce a case later and verify that no image, mask, decision, or
  configuration was silently replaced.
- Needs: canonical manifests, hashes, timestamps, limitations, and an
  independent verification action.
- Risk: a complete-looking ZIP that omits inputs or mixes identities.
- Product response: verify schema, inventory, relationships, safe paths, and
  SHA-256 values before accepting an imported bundle.

### P3 - Portfolio evaluator or developer (secondary)

- Goal: run the demo locally, understand what was measured, and distinguish
  implemented behavior from future industrial claims.
- Needs: deterministic fixtures, a short setup, automated tests, measured
  results with sample counts, and prominent limitations.
- Risk: reading a perfect tiny synthetic smoke test as production accuracy.
- Product response: separate release gates from statistical performance and
  label every result as synthetic/demo evidence.

### Explicitly not a target persona

An unattended production operator, safety controller, or automated part-release
system is not a v0.1 user. The application must not be placed in such a loop.

## 3. Core user journey

### J1 - Create and inspect a valid synthetic case

1. The user creates or opens a case and sees its case ID and case revision.
2. The user selects a declared `part_id` and `cad_revision`.
3. The user imports a PNG or JPEG reference plus inspection images.
4. The system validates content, decoded dimensions, count, regular-file/path
   safety, and identity before analysis.
5. The system canonicalizes supported inputs according to the v1 contract and
   records source/canonical hashes without overwriting the source evidence.
6. The user starts the deterministic baseline and sees the pinned pipeline,
   model, and configuration identity.
7. For each image, the user can inspect the original, reference, score, mask,
   and affected feature. If mapping is not justified, the UI says it is
   unmapped instead of inventing a feature.
8. The user records one disposition: `accept`, `reject`, `needs_review`, or
   `model_error`.
9. The system stores who/what recorded the decision and its timestamp without
   rewriting prior analysis lineage.

`accept` means accepted by the reviewer within this demo case. It is not a
physical-part release, certificate of conformance, or production instruction.

### J2 - Export and independently verify evidence

1. A reviewed case is exported only when required evidence is complete.
2. The bundle contains the case manifest, source identity and hashes,
   analysis, masks, feature mapping, disposition, evaluation metadata,
   limitations, and a payload inventory.
3. A verifier reads the archive without trusting archive paths or filenames.
4. It validates schema versions, allowed paths, required relationships, file
   counts/sizes, and hashes.
5. Re-import reconstructs the same evidence identity and reports verification
   success.
6. Any mismatch returns a stable machine-readable failure code and publishes
   no accepted case/result artifact.

### J3 - Handle a revision mismatch

1. The selected case declares one part and revision.
2. An imported manifest or result declares a different identity.
3. The UI explains the mismatch without offering a one-click bypass.
4. Analysis/export/import stops for the mismatched evidence.
5. No accepted/published result is created.
6. The user must correct the source or explicitly create a distinct case.

### J4 - Record model failure without hiding evidence

1. The reviewer sees a missing, misplaced, or misleading anomaly result.
2. The reviewer selects `model_error` and may add a concise note.
3. The original result remains immutable evidence linked to the review.
4. The case can be exported with the error and limitation visible.

### J5 - Run an optional external benchmark

1. The user separately obtains a permitted local copy of MVTec AD.
2. The optional benchmark runner reads it without copying data into the
   repository or importing it as a case fixture.
3. Results are isolated from the checked-in synthetic demo and identify the
   dataset/category and applicable license.
4. Public sharing or commercial use is not automated or implied.
5. Absence of MVTec AD never prevents the synthetic demo from working.

## 4. Supported use cases

| ID | Use case | Expected outcome |
| --- | --- | --- |
| UC-01 | Review a nominal synthetic image | Deterministic score/mask, honest feature state, human disposition |
| UC-02 | Review a seeded synthetic defect | Visible localized evidence linked to declared synthetic truth |
| UC-03 | Mark ambiguous output | `needs_review` persists without forced accept/reject |
| UC-04 | Mark incorrect model output | `model_error` preserves both automated and human evidence |
| UC-05 | Export/re-import a complete case | Inventory and identity verify exactly |
| UC-06 | Tamper with a bundle payload | Verification fails and publishes nothing |
| UC-07 | Import wrong revision evidence | Identity failure and no accepted result |
| UC-08 | Import malformed/unsafe content | Stable failure response and no partial publication |
| UC-09 | Run synthetic evaluation twice | Equivalent canonical metrics and hashes |
| UC-10 | Run a local optional MVTec benchmark | Separate, license-labeled benchmark output |

## 5. Functional requirements

### Case and identity

- Every machine-readable document uses `schema_version: "1.0.0"`.
- Identity follows the v1 schemas, including `part_identity.part_id`,
  `part_identity.cad_revision`, `case_revision`, versioned pipeline/model
  objects, `model_artifact_sha256`, and `configuration_sha256`.
- SHA-256 values are lowercase 64-character hexadecimal strings.
- Case revisions are explicit; an update does not silently mutate the identity
  of an earlier result.
- Identity is supplied by a trusted manifest/user action, not inferred from
  image pixels.

### Input and analysis

- Only content-validated PNG and JPEG images are accepted.
- The v1 boundary is at most 25 MiB per image, 8192 pixels on either edge, 40
  megapixels decoded, and 64 inspection images per case.
- EXIF or metadata cannot bypass decoded-image checks.
- Dimension differences require an explicit approved normalization path; they
  are rejected when that path is absent.
- The baseline is deterministic for the same canonical inputs, identity,
  versions, and configuration.
- Masks are 8-bit single-channel PNG files matching analyzed dimensions.
- Feature mapping uses declared synthetic/adapter geometry. Lack of justified
  mapping is an explicit unmapped state, not a guessed feature.

### Human review

- The stored v1 values are exactly `accept`, `reject`, `needs_review`, and
  `model_error`; UI labels may be localized.
- A result and a disposition remain distinguishable. Human review does not
  overwrite the model output.
- The UI explains that dispositions are demo-case decisions only.
- Review history includes timestamp and actor representation allowed by the
  local contract; it must not fabricate a real employee identity.

### Evidence

- The evidence contract is defined by `schemas/v1/evidence-bundle-manifest` and
  the referenced v1 documents.
- Every bundle includes explicit limitations and evaluation metadata.
- Verification covers manifest and payload hashes plus cross-document case,
  part, revision, pipeline, model, and configuration identity.
- Archive entries must be relative, normalized, non-symlink regular files.
- A bundle is limited to 64 MiB compressed, 100 payload files plus two control
  files, 25 MiB per payload file, 128 MiB aggregate uncompressed payload, and a
  100:1 maximum compression ratio per member and in aggregate.
- Verification failure cannot leave a published/accepted case or result.

### Language and accessibility

- The core journey is usable with English or Korean labels without changing
  stored enum values or hashes.
- Status is not conveyed by color alone.
- Interactive controls have names, keyboard access, visible focus, and
  associated error text.
- Mask overlays have a text alternative containing score, mapping state, and
  disposition.

## 6. Non-goals

- Production defect detection, defect-taxonomy completeness, or statistically
  representative accuracy
- Automatic physical accept/reject, machine stop, purchase, release, or report
  submission
- Optical calibration, dimensional measurement, or tolerance verification
- Guaranteeing registration under arbitrary viewpoint, lighting, focus,
  occlusion, material, or camera changes
- General CAD parsing or computer-vision inference of revision identity
- Training or evaluating a state-of-the-art anomaly model as the v0.1 goal
- Real-time throughput, high availability, regulated records retention, or
  enterprise authentication
- Cloud storage, telemetry, or transmission of user images
- Bundling third-party datasets in the repository

## 7. Honest limitations

- The checked-in dataset is synthetic and intentionally small. It validates a
  software path, not real defect coverage.
- The deterministic image-difference baseline is sensitive to registration,
  lighting, viewpoint, scale, focus, background, and harmless appearance
  variation.
- A nonzero difference is not proof of a defect, and a zero/low score is not
  proof of conformance.
- Feature mapping is only as trustworthy as the declared synthetic or adapter
  metadata. The model does not recover CAD semantics from pixels.
- Human review improves traceability but does not by itself validate reviewer
  competence, inspection instructions, or a manufacturing process.
- SHA-256 verification demonstrates byte/inventory integrity, not truth,
  safety, authenticity of the original capture, or correctness of the model.
- Local-first reduces data transmission but is not a substitute for a security
  assessment, access control, backup, audit retention, or incident response.
- Optional MVTec results are benchmark evidence under a non-commercial license;
  they do not validate this product on the owner's parts or process.

## 8. Future extensions that do not change v0.1 claims

- Read-only FreeCAD export-manifest adapter
- Larger synthetic nuisance/defect matrix and fixed train/validation/test
  recipe splits
- Pluggable anomaly model behind the existing evidence contract
- Camera ingest, only after capture identity and calibration are specified
- Field pilot planning, only under the separate `FIELD_READY` process
