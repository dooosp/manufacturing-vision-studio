# Failure contract

## Fail-closed rule

An operation succeeds only after every schema, resource, identity, revision,
hash, semantic, and publication check completes. Failure leaves the prior
authoritative state intact.

For analysis, disposition, FreeCAD import, and bundle export/import, fail closed
means all of the following:

- no new final blob, analysis, disposition, accepted inspection, import, export
  record, or final archive is addressable;
- no case lifecycle advance is committed;
- staged bytes are removed or left only as unreachable bounded recovery data;
- an older valid artifact is not relabeled or rebound to the attempted request;
- the API returns one stable machine code in the standard error envelope.

Validation failures are expected product states, not evidence artifacts. Logs
may record code, operation ID, and safe identifiers, but MUST NOT record image
bytes, reviewer rationale, absolute source paths, or stack traces in an API
response.

## Stable v1 codes

| Code | Typical HTTP | Meaning and required outcome |
| --- | ---: | --- |
| `SCHEMA_INVALID` | 422 | JSON shape, type, enum, or runtime semantic invariant is invalid; no mutation. |
| `UNSUPPORTED_SCHEMA_VERSION` | 422 | Schema ID/version is absent, unknown, or mismatched; no compatibility guess. |
| `RESOURCE_NOT_FOUND` | 404 | Referenced local case/artifact does not exist; no placeholder is created. |
| `UNSAFE_PATH` | 400 | Absolute/traversal/control/invalid path or filename; path is not opened. |
| `SYMLINK_INPUT` | 422 | File or ancestor is a symlink; it is not followed. |
| `NON_REGULAR_INPUT` | 422 | Input is not a regular file; it is not read as payload. |
| `INPUT_TOO_LARGE` | 413 | Image or individual member exceeds a byte/pixel/resource cap; stream stops. |
| `BUNDLE_LIMIT_EXCEEDED` | 413 | Archive entry/count/expanded-size/ratio cap is exceeded; nothing is extracted durably. |
| `UNSUPPORTED_FORMAT` | 415 | Declared/detected image, archive, or artifact format is not allowlisted. |
| `IMAGE_DECODE_FAILED` | 422 | Allowed-format bytes are corrupt or cannot be fully verified/decoded. |
| `IMAGE_DIMENSIONS_EXCEEDED` | 413 | Width, height, or decoded pixel count exceeds limits. |
| `IMAGE_DIMENSION_MISMATCH` | 422 | Reference and inspection dimensions differ under reject-mismatch policy. |
| `NORMALIZATION_NOT_APPROVED` | 422 | A dimension transform was implicit, unsupported, or absent from case configuration. |
| `MISSING_REFERENCE` | 422 | Analysis has no valid current reference image. |
| `PART_ID_MISMATCH` | 409 | Repeated part IDs differ; no analysis/disposition/export is published. |
| `REVISION_MISMATCH` | 409 | CAD or case evidence revision is stale/different; no accepted result is published. |
| `HASH_MISMATCH` | 422 | Declared and computed raw/canonical/pixel/artifact digest differs. |
| `UNKNOWN_PIPELINE_VERSION` | 422 | Pipeline ID/version is not registered; model does not run. |
| `UNKNOWN_MODEL_VERSION` | 422 | Model ID/version/artifact hash is not registered; model does not run. |
| `MODEL_ABSTAINED` | 422 or typed result | Model intentionally could not decide; never supports `accept`/`reject`. |
| `MASK_CORRUPT` | 422 | Mask is malformed, non-binary, wrong-sized, or hash-invalid; no completed analysis is published. |
| `EVIDENCE_INCOMPLETE` | 422 | A required evidence role/document/binding is missing; no final bundle. |
| `DUPLICATE_ARTIFACT_PATH` | 422 | Two manifest/archive members share a path; entire bundle is rejected. |
| `CANONICAL_JSON_MISMATCH` | 422 | JSON bytes are not exact `mvs-canonical-json/v1`; document is rejected. |
| `STORAGE_CONFLICT` | 409 | Atomic create/unique constraint/current-state conflict; existing state wins unchanged. |
| `INTERNAL_ERROR` | 500 | Unexpected failure; no partial publication and no internal detail in response. |

The same cause MUST use the same code across Python, API, CLI, verification, and
tests. Message wording and safe `details` can vary. New codes require a versioned
contract update; callers MUST treat an unknown code as failure.

## Failure state by operation

### Image ingestion

Path, stream size, detected format, dimensions, complete decode, canonical
encoding, and all hashes are checked before image metadata is attached to a
case. A failed upload cannot become the selected reference or inspection input.

### Analysis

The current case and image records are loaded together. Missing reference,
identity/revision/hash mismatch, unknown versions, unapproved normalization, or
invalid model output publishes no completed analysis. A deliberate abstention is
either returned as `MODEL_ABSTAINED` with no artifact or stored as the explicit
`result_status: "abstained"` schema branch; an implementation MUST choose one
documented behavior consistently. Neither path is an automated acceptance.

### Human disposition

The service recomputes the analysis document hash and compares the case revision,
part/CAD identity, inspection image ID/hash, and current supersession state in a
transaction. Any mismatch rejects the entire disposition. `accept` and `reject`
require a completed, current analysis. `needs_review` and `model_error` are
non-accepting terminal review signals for that evidence revision.

### Evidence export and re-import

Export preflights the complete required role set and cross-document bindings,
then builds in staging. The staged archive must pass the same verifier used for
untrusted re-import before atomic publication. Re-import verifies structure,
sidecar, manifest, raw files, and identity without trusting an existing local
record. A single missing or extra unsafe member, duplicate, digest error, or
revision inconsistency rejects the entire bundle.

### FreeCAD adapter

The adapter checks policy constants, upstream manifest digest, part/CAD identity,
allowed roles/media, safe relative paths, regular files, and hashes before
copying. A source change observed between check and copy is a hash mismatch. It
never retries by following a new path, executes no source content, and performs
no source write-back.

## Recovery

On startup, recovery may remove old entries under the known staging directory
and may garbage-collect final digest paths that have no committed database
reference after a conservative grace period. It MUST NOT recursively clean an
operator-selected import root, sibling repository, home directory, or unresolved
path. A committed record with missing/corrupt bytes is quarantined and surfaced
as evidence failure; recovery MUST NOT fabricate or silently regenerate it.
