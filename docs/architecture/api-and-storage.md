# Local API and storage boundary

## API boundary

The v1 API listens on loopback by default. Remote binding requires an explicit
operator choice and is outside the supported demo security boundary. The web UI
has no direct filesystem or database access; all mutations pass through the case
service and its validation gates.

The resource-oriented surface is:

| Method and path | Behavior |
| --- | --- |
| `POST /api/v1/cases` | Create a case with part/CAD and analysis configuration identity. |
| `GET /api/v1/cases/{case_id}` | Return the current schema-valid case projection. |
| `POST /api/v1/cases/{case_id}/images` | Stream, validate, and ingest one reference or inspection image. |
| `POST /api/v1/cases/{case_id}/analyses` | Analyze one inspection image against the selected reference. |
| `POST /api/v1/cases/{case_id}/dispositions` | Record an immutable human decision for one completed analysis. |
| `POST /api/v1/cases/{case_id}/exports` | Build, self-verify, then publish an evidence bundle. |
| `POST /api/v1/bundles/verify` | Verify an exported bundle without importing case state. |
| `POST /api/v1/freecad-exports/import` | Copy and validate an inert read-only export manifest and artifacts. |

The server allocates IDs and internal storage paths. A client-supplied filename
is display metadata only; it MUST be a basename and MUST NOT select a destination.
The API does not accept absolute source paths from a browser.

Every evidence-affecting mutation includes `expected_case_revision` (or an
equivalent strong `If-Match` value). The server compares it inside the same
database transaction that records the mutation. Missing or stale values fail
with `REVISION_MISMATCH`.

Errors have one closed envelope:

```json
{
  "error": {
    "code": "REVISION_MISMATCH",
    "message": "The case evidence revision changed.",
    "details": {
      "case_id": "case-001",
      "expected_case_revision": 3,
      "actual_case_revision": 4
    }
  }
}
```

`code` is stable; `message` is human-facing and not stable. `details` is always
an object and MUST NOT expose stack traces, SQL, absolute paths, environment
variables, source-repository locations, or input bytes. The complete code set is
in [the failure contract](failure-contract.md).

## Schema validation is necessary, not sufficient

JSON request and persisted documents MUST validate against the exact v1 schema.
The service additionally enforces cross-document invariants JSON Schema cannot
express:

- `pixel_count == width_px * height_px`;
- dataset positive and negative counts sum to sample count;
- confusion-matrix counts and derived metrics agree;
- normalized feature bounds have `min < max`;
- artifact paths are unique and sorted;
- manifest counts and byte totals equal the artifact inventory;
- referenced image, analysis, mask, and disposition objects exist and their raw
  or canonical hashes match;
- all repeated case, part, CAD, pipeline, model, and configuration identities
  match current authoritative records;
- status transitions and supersession rules are legal.

Validation order is version -> syntax/schema -> local resource limits ->
identity/revision -> referenced hashes -> operation-specific invariants. This
order limits work on hostile input and prevents a valid hash from bypassing an
identity mismatch.

## Storage model

The storage root is operator-configured once and resolved before use. All
runtime-owned files are descendants of that root:

```text
data/
  cases.sqlite3
  blobs/
    sha256/<first-two-hex>/<remaining-hex>
  exports/
  staging/
```

SQLite stores current case state, immutable artifact metadata, dispositions,
and publication records. File bytes live in the content-addressed blob store.
Database rows store a digest and server-generated relative locator, never a
user-controlled absolute path.

Blob publication is copy-on-ingest:

1. stream into a newly created staging file with a running byte limit and hash;
2. close, decode/validate, and compare any declared digest;
3. write derived canonical bytes to a distinct staged file when required;
4. re-open staged files without following symlinks and verify digest and size;
5. atomically rename to the digest-derived blob locator on the same filesystem;
6. commit metadata only after the final locator is present and verified.

Blobs are immutable. A duplicate digest reuses the existing verified blob. A
different byte sequence never overwrites an existing digest path. Failed and
crash-abandoned staging files are not addressable as artifacts and are removed
by bounded startup recovery.

## Transaction and publication rules

Analysis results, dispositions, and exports are written to staging first. The
service holds a database transaction while it rechecks the authoritative case
revision and identity. Publication uses an atomic same-filesystem rename. If the
transaction fails after a rename, recovery treats the unreferenced target as an
orphan; it never infers a valid database record from file presence alone.

An accepted human disposition is never inferred from an automated result. A
disposition row and JSON document are inserted only after its analysis hash,
inspection-image hash, part/CAD identity, case revision, and decision-specific
rules pass in the same transaction.

Evidence export follows the same rule: the final archive path and successful
export record do not exist until a verifier has read the staged bundle through
the untrusted-import path. Existing exports are immutable and are never replaced
in place.

## Revision mismatch is fail closed

`case_revision` is the revision of evidence-affecting inputs. The service MUST
increment it whenever any of these change:

- `part_id` or `cad_revision`;
- reference or inspection image selection/content;
- feature IDs or FreeCAD adapter binding;
- pipeline ID/version;
- model ID/version/artifact hash;
- configuration hash or normalization policy.

An analysis records the revision it actually read. Before recording a
disposition or export, the service reloads current state and compares the full
binding tuple. A mismatch produces no replacement analysis, no disposition, no
`accept` state, no export record, and no final bundle. Staged output is removed.

| Mismatch | Code | Allowed durable effect |
| --- | --- | --- |
| `part_id` | `PART_ID_MISMATCH` | failure audit metadata only |
| CAD or case evidence revision | `REVISION_MISMATCH` | failure audit metadata only |
| source/config/artifact digest | `HASH_MISMATCH` | failure audit metadata only |
| pipeline/model version | `UNKNOWN_PIPELINE_VERSION` or `UNKNOWN_MODEL_VERSION` | failure audit metadata only |

Old artifacts remain immutable for audit but are marked superseded by the
current case projection. They cannot be rebound by editing IDs or hashes.

## Read-only FreeCAD adapter

The import caller selects one allowed import root controlled by the local
operator. The adapter reads a
`freecad-export-adapter-manifest.schema.json` document, resolves only its safe
relative members below that root, rejects symlinks and non-regular files,
verifies all hashes, and copies accepted bytes into MVS storage. It closes source
handles before any database publication.

The v1 allowlist is deliberately inert: JSON metadata/feature maps and PNG
reference renders. Raw CAD documents, Python macros, executables, archives,
external URLs, and paths outside the selected root are unsupported. The adapter
never modifies FreeCAD Automation, its manifests, or its repository.
