# Data strategy, lineage, and licensing

## 1. Policy

The distributable demo uses only deterministic, project-generated synthetic
data. External datasets and user images are optional local inputs and are not
prerequisites for setup, tests, screenshots, or `DEMO_READY`.

This design has two purposes:

- Anyone can reproduce the bounded behavior without credentials or a dataset
  download.
- Benchmark licenses and real-world privacy/ownership questions cannot silently
  contaminate tracked demo artifacts.

Synthetic data still does not prove field performance. It exercises known
software paths under declared rendering and defect recipes.

## 2. Data inventory

| Data source | Role | Tracked in repository | Rights/terms | Release rule |
| --- | --- | --- | --- | --- |
| Project-generated synthetic reference/inspection images | Primary demo and tests | Yes, when generated/tracked intentionally | Project-owned generator and artifact terms must be covered by the repository's release license/data notice | Allowed after deterministic hashes, provenance, and license coverage are verified |
| Project-generated masks, feature truth, recipes, manifests | Ground truth and evaluation | Yes | Same project release terms as the synthetic dataset unless explicitly marked otherwise | Required for the seeded demo; no private source paths |
| User-supplied local images/manifests | Local case experimentation | No by default | User retains rights and is responsible for authorization, privacy, and contractual limits | Never auto-commit, upload, or publish; evidence export is an explicit local user action |
| Read-only FreeCAD export manifest | Optional identity/feature adapter | No external repository content copied by default | Rights follow the user's source files and repository terms | Import manifest only; validate identity and hashes; do not modify sibling repositories |
| MVTec AD | Optional non-commercial benchmark | No | CC BY-NC-SA 4.0; MVTec explicitly prohibits commercial use | Local opt-in only; isolated results; no data/derived media committed without separate license review |

Before a public release, confirm that the root `LICENSE` (and a data notice if
needed) explicitly covers the checked-in synthetic fixtures and metadata. If it
does not, do not assume that a source-code license automatically answers the
generated-data question.

The current Python package metadata declares MIT for the software package. A
public release still needs the corresponding license text and an explicit
decision about generated fixture/data terms; dependency and dataset licenses
remain separate.

## 3. Synthetic dataset contract

### Seeded v0.1 minimum

The checked-in/locally generated golden suite contains at least:

- One case with a stable case ID and `case_revision`
- One declared `part_id` and `cad_revision`
- One reference image
- One nominal inspection image
- One inspection image with a deterministic injected defect
- Declared expected image state for each inspection
- A ground-truth defect mask or explicit reason when pixel truth is unavailable
- A declared feature mapping for the injected defect, or an explicit expected
  unmapped state
- Generator version, recipe ID, seed, parameters, and SHA-256 values

The minimum suite is a smoke/golden test, not a representative evaluation
sample. Reports must show the exact counts.

### Recommended expanded synthetic matrix

A later quality study should generate independent recipes across:

- Nominal appearance variation that should not trigger a defect
- Defect type, size, contrast, count, and engineering feature
- Translation within the supported registration envelope
- Lighting/color perturbation, blur, noise, and compression within declared
  bounds
- Out-of-bound conditions expected to abstain or fail, such as excessive shift,
  dimension mismatch, crop, unsupported encoding, or missing feature identity

Recipes, not individual rendered siblings, define splits. Images derived from
the same base geometry/texture/seed family must not cross development and
held-out evaluation splits because that would leak nearly identical pixels.

### Determinism rules

- A seed alone is not provenance. Record generator ID/version, recipe, inputs,
  runtime/library versions where they affect bytes, and canonical parameters.
- Declare which artifacts are required to be byte-identical across supported
  environments. For other artifacts, define semantic equivalence explicitly.
- Canonical JSON uses the project serialization rules before hashing.
- SHA-256 is computed over bytes, stored as lowercase 64-hex, and paired with a
  logical role/path.
- Never overwrite a fixture while retaining its old fingerprint or expected
  result. A deliberate fixture change is a versioned dataset change.

## 4. Required lineage

Each inspection/evaluation record must be able to recover:

- `schema_version`
- Case ID and integer `case_revision`
- `part_identity.part_id` and `part_identity.cad_revision`
- Source role (reference, inspection, mask, ground truth, or report)
- Source bytes SHA-256 and canonical bytes SHA-256 when canonicalization occurs
- Original media type and decoded width/height/channels
- Generator/adapter/dataset origin and recipe/category identifier
- Pipeline ID/version
- Model ID/version and `model_artifact_sha256`
- `configuration_sha256`
- Analysis result and output mask SHA-256
- Feature mapping source and confidence/status, including explicit unmapped
- Human disposition and timestamp when reviewed
- Evaluation run ID, split/recipe, and report fingerprint
- Applicable license/source notice and explicit limitations

Machine-readable field names are normative in `schemas/v1/*.schema.json`.
Prose must not introduce aliases that weaken those contracts.

## 5. Input governance

- Accept only PNG/JPEG content validated after decoding, not by extension alone.
- Enforce 25 MiB per image, at most 8192 pixels per edge, at most 40 MP decoded,
  and at most 64 inspection images per case.
- Strip or avoid publishing unnecessary metadata. EXIF orientation handling
  must be deterministic and cannot bypass decoded dimension checks.
- Reject path traversal, absolute paths where disallowed, symlinks, devices,
  non-regular files, malformed images, unsupported formats, and archive bombs.
- Evidence ZIP input is additionally bounded to 64 MiB compressed, 100 payload
  members plus two controls, 25 MiB per payload member, 128 MiB uncompressed,
  and a 100:1 compression ratio per member and in aggregate.
- Reject inconsistent analyzed dimensions unless an explicit normalization
  operation is approved and bound into the configuration identity.
- Do not send images, metadata, or hashes to a network service in the default
  workflow.
- Treat filenames and embedded metadata as untrusted labels, not identity proof.

## 6. MVTec AD license inventory

Verified against primary sources on 2026-07-31:

- MVTec describes MVTec AD as an industrial anomaly-detection benchmark with
  more than 5,000 high-resolution images in 15 object/texture categories,
  including defect-free training images, defective/non-defective test images,
  and pixel-precise anomaly annotations.
- MVTec publishes the data under Creative Commons
  Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) and
  explicitly says commercial use is not allowed. MVTec asks users to contact
  them if the non-commercial clause is uncertain.
- The CC legal code grants reproduction/sharing and adaptation only for
  non-commercial purposes. Sharing requires attribution/license notices and an
  indication of modifications; shared adapted material is subject to the
  ShareAlike conditions.

Primary sources:

- [MVTec AD dataset and license terms](https://www.mvtec.com/research-teaching/datasets/mvtec-ad)
- [CC BY-NC-SA 4.0 legal code](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode)

This summary is an engineering control, not legal advice.

### Repository controls for MVTec AD

- Do not download it during default setup, tests, demo, or CI.
- Do not commit raw images, annotations, archives, thumbnails, transformed
  images, or caches.
- Require the user to provide a local dataset path and acknowledge the dataset
  identity/license before the optional adapter runs.
- Mark reports with dataset name, category/split, version or acquisition date,
  source URL, license identifier, and non-commercial-only warning.
- Keep MVTec results in an external/local artifact directory excluded by git.
- Do not mix MVTec-derived metrics or media into the primary synthetic evidence
  without an explicit provenance boundary.
- Treat public screenshots, example bundles, hosted demos, and derivative
  annotations as sharing that needs a separate license/compliance review.
- Do not describe MVTec as endorsing the project.
- For any commercial or ambiguous use, stop and obtain appropriate permission
  or replace the data; do not infer permission from repository visibility.

## 7. User-supplied and real data

Real workshop images are not part of v0.1. If a user supplies local images:

- The product must not claim the user has rights merely because import worked.
- The user controls whether the source is included in a local evidence export.
- The application must avoid automatic upload, telemetry, or repository copy.
- Faces, badges, screens, serial numbers, locations, customer markings, and
  confidential geometry may create privacy, security, export-control, or
  contractual obligations.
- A later field study needs documented authorization, retention/deletion rules,
  access control, redaction policy, and ground-truth governance before capture.

## 8. Data limitations

- Synthetic rendering cannot reproduce the open-ended distribution of real
  materials, optics, surfaces, contamination, wear, assembly variation, and
  defect mechanisms.
- A seeded anomaly can make localization artificially easy because generator
  truth exactly identifies changed pixels.
- A small golden set is vulnerable to overfitting through code and fixture
  co-development.
- MVTec categories are not evidence for the owner's parts, cameras, line, or
  defect costs.
- Hashes preserve byte identity, not semantic correctness, capture authenticity,
  or lawful provenance.
- Human labels may disagree; v0.1 does not measure inter-rater agreement.
