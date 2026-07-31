# Architecture and trust contracts

This directory is the normative v1 architecture contract for Manufacturing
Vision Studio. The product is a local-first, portfolio-grade inspection demo;
it is not a production, safety, or shop-floor release system.

- [System architecture](system-architecture.md) defines components, trust
  boundaries, evidence lineage, and versioning.
- [API and storage](api-and-storage.md) defines the local API, case-revision
  behavior, immutable blobs, and atomic publication.
- [Integrity and input safety](integrity-and-input-safety.md) defines canonical
  JSON, hashes, evidence bundles, paths, symlinks, image limits, and archive
  handling.
- [Model interface](model-interface.md) defines the replaceable deterministic
  baseline boundary.
- [Failure contract](failure-contract.md) defines stable error codes and the
  required fail-closed outcome.

The machine-readable contracts are the seven Draft 2020-12 schemas in
[`schemas/v1`](../../schemas/v1). A runtime invariant in these documents can be
stricter than JSON Schema; schema validation alone never establishes that a
file, hash, revision, or human decision is trustworthy.

## Normative language

`MUST`, `MUST NOT`, `SHOULD`, and `MAY` describe the bounded v1 contract. A
component that cannot satisfy a `MUST` condition fails closed and returns a
stable code from [the failure contract](failure-contract.md).

## Version policy

Every v1 JSON document has `schema_version: "1.0.0"`, a Draft 2020-12 `$schema`,
and an immutable `$id` below
`https://schemas.manufacturing-vision-studio.local/v1/`. Every object is closed
with `additionalProperties: false`.

The accepted instance set of a published v1 schema is immutable. Editorial
changes that do not change validation may be made before v1 release. Any later
field addition, removal, enum change, limit change, or changed invariant creates
a new major schema directory and `$id` (for example `schemas/v2`) and requires an
explicit, tested migration. Producers MUST NOT silently emit a new shape under
`1.0.0`; consumers MUST reject unknown versions with
`UNSUPPORTED_SCHEMA_VERSION`.
