# Model interface

## Purpose

The model boundary allows the deterministic registered-image-difference baseline
to be replaced later without changing case, image, disposition, evaluation, or
evidence-bundle contracts. A model computes observations; the case service owns
identity, policy, persistence, and publication.

## Registered model identity

A model is installed code registered at process startup, not code or weights
loaded from an upload. Its registry entry contains:

```text
interface_version = "mvs.vision-model/v1"
pipeline_id
pipeline_version            # SemVer
model_id
model_version               # SemVer
model_artifact_sha256        # exact installed artifact/package fingerprint
supported_configuration_schema
```

`pipeline_id` is a stable name and `pipeline_version` is a SemVer value such as
`1.0.0`; a namespaced value such as `mvs.difference-pipeline/v1` is not a valid
SemVer version. The same separation applies to model ID/version. The server
rejects an unregistered interface, pipeline, model, or artifact digest before
any invocation.

The configuration is schema-validated, encoded with
`mvs-canonical-json/v1`, and identified by `configuration_sha256`. Every value
that can change pixels, registration, thresholding, mask generation, score
rounding, or feature mapping belongs in that configuration or the versioned
runtime identity.

## Request contract

The service constructs an immutable request after validation:

```text
ModelRequest
  case_id, case_revision
  part_id, cad_revision
  reference: ValidatedImage
    original_sha256, canonical_image_sha256, pixel_sha256
    width, height, RGB8 row-major pixels
  inspection: ValidatedImage
    original_sha256, canonical_image_sha256, pixel_sha256
    width, height, RGB8 row-major pixels
  normalized feature regions (bounded, sorted by feature_id)
  validated configuration
  normalization record
```

No request field is a filesystem path, URL, database handle, user credential, or
mutable storage object. Input arrays are read-only. Image decoding, orientation,
normalization authorization, identity selection, and hash calculation happen
outside the model.

Feature regions use normalized inclusive-exclusive rectangles
`0 <= x_min < x_max <= 1` and `0 <= y_min < y_max <= 1`. The service verifies
that every feature ID exists in the current case/adapter binding and sorts IDs
before invocation. A future pixel feature map can be added only through a new
versioned interface; v1 models cannot reinterpret arbitrary JSON.

## Output contract

A model returns one of two typed outcomes:

```text
Completed
  anomaly_score in [0, 1]
  threshold in [0, 1]
  automated_classification: normal | anomaly | indeterminate
  binary uint8 mask matching target dimensions
  zero or more bounded feature findings
  warnings

Abstained
  reason_code
  bounded human-readable message
```

The model does not return case/part/revision identity and cannot return a human
disposition. The service validates finite scores, mask dimensions/values,
feature IDs, and output size; deterministically encodes the mask; attaches the
authoritative identity and registered model metadata; and constructs the
`analysis-result` document. Model-supplied bytes are never published directly.

An abstention may be recorded as an immutable `analysis-result` with
`result_status: "abstained"`. It cannot support `accept` or `reject`; a reviewer
may record only `needs_review` or `model_error` if the product flow chooses to
retain it. An exception, timeout, malformed output, non-finite value, or resource
violation is a failed invocation and publishes no analysis result.

## Deterministic baseline

The v1 checked-in baseline performs bounded translation registration, absolute
RGB difference, binary thresholding, and feature-region overlap. Its contract
requires:

- fixed registration search bounds and sampling stride in configuration;
- deterministic iteration and tie-breaking;
- fixed score rounding;
- pinned decoder, array, and PNG encoder versions in execution metadata;
- fixed PNG mode/compression parameters;
- no network, clock, process-global random state, GPU nondeterminism, or hidden
  mutable cache;
- a recorded random seed if a later conforming implementation uses randomness.

Repeated invocation over identical canonical pixel hashes, feature regions,
registered component versions, and configuration hash MUST produce equal
canonical result fields and mask bytes. `produced_at` and generated IDs are
service envelope fields and are excluded when checking model-output equivalence.

## Normalization

V1 defaults to `reject_mismatch`. If source dimensions differ, only a
normalization method already named in the case configuration may run. The
service, not the model, performs the deterministic transform and records its
source/target dimensions and parameter hash. Arbitrary interpolation, automatic
aspect-ratio guesses, or a per-request override fails with
`NORMALIZATION_NOT_APPROVED`.

The baseline supports `none` without authorization and may support only these
explicit policies when implemented and tested: letterbox, center crop, or
nearest-neighbor resize. Unsupported declared policies remain fail closed.

## Security and resource contract

The v1 model executes in-process and is therefore trusted installed code. The
interface limits accidental authority but is not a sandbox. Models MUST NOT
perform filesystem or network I/O, spawn processes, mutate inputs, or load
artifacts selected by an untrusted request. A future third-party model plugin
system requires a separate process/sandbox design and a new trust review; it is
not implied by this interface.
