# Integrity and input safety

## Hash domains

All digests are SHA-256 rendered as 64 lowercase hexadecimal characters. A
digest is meaningful only with its declared domain:

- `sha256` on an image or artifact means the exact raw file bytes;
- `canonical_image_sha256` means the metadata-free RGB8 PNG produced by the
  pinned decoder after EXIF orientation is applied;
- `pixel_sha256` means tightly packed row-major RGB8 pixels, with no header,
  stride padding, or metadata;
- a JSON document digest means its exact `mvs-canonical-json/v1` bytes;
- `payload_sha256` means the evidence-inventory projection defined below, not
  concatenated artifact contents and not ZIP bytes;
- `bundle-manifest.sha256` means the exact canonical manifest bytes.

Code MUST use a domain-specific function or field name. It MUST NOT compare a
raw source hash with a canonical-image, pixel, JSON, inventory, or archive hash.
Hash equality establishes byte integrity, not source authenticity or reviewer
identity.

## `mvs-canonical-json/v1`

The v1 profile deliberately matches the implemented Python control plane. It is
**not RFC 8785/JCS**, and code and documentation MUST NOT claim JCS compliance.
The backend is the canonicalization authority; browser code displays hashes but
does not independently define them.

The input is an already schema-validated in-memory JSON value. The serializer:

1. accepts only JSON null, boolean, string, integer, finite floating-point,
   array, and string-keyed object values;
2. rejects duplicate object names during parsing and rejects NaN and positive or
   negative Infinity;
3. recursively sorts object member names in Python Unicode code-point order;
4. emits `,` and `:` separators with no other insignificant whitespace;
5. emits non-ASCII Unicode directly, encodes the result as UTF-8, and writes no
   BOM or trailing newline;
6. uses the Python 3.11+ standard JSON number rendering used by the reference
   implementation (`1` and `1.0`, and `0.0` and `-0.0`, remain distinct typed
   serializations).

Reference operation:

```python
json.dumps(
    value,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
```

Schema-backed typed producers MUST use integers for count/revision/size fields
and floats for measured ratio/score fields so a producer does not drift between
numerically equal but byte-distinct forms. Strings are preserved exactly; the
canonicalizer performs no Unicode normalization. Contract identifiers and
artifact paths are ASCII-restricted by schema.

Every exported JSON artifact MUST already equal its re-canonicalized bytes. A
verifier parses with duplicate-key rejection, validates the declared schema,
canonicalizes the typed document, and rejects byte inequality with
`CANONICAL_JSON_MISMATCH` before trusting its digest.

## Evidence bundle hash contract

The payload artifact array is sorted by `path` in ascending Python Unicode
code-point order. Paths are ASCII in v1, so this is also bytewise UTF-8 order.
For each artifact, the payload projection retains exactly `path`, `sha256`, and
`byte_size`; role, media type, and schema identity remain protected by the
separate manifest hash.

The exact preimage is the `mvs-canonical-json/v1` encoding of:

```json
{
  "algorithm": "sha256",
  "artifacts": [
    {
      "path": "artifacts/case.json",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "byte_size": 123
    }
  ]
}
```

`payload_sha256` is SHA-256 of those bytes. `artifact_count` MUST equal the array
length and `payload_byte_size` MUST equal the sum of artifact byte sizes. Paths
MUST be unique and already sorted. The two control files are:

- `bundle-manifest.json`: exact canonical manifest bytes;
- `bundle-manifest.sha256`: ASCII lowercase SHA-256 of those bytes followed by
  exactly one LF (`<64 hex>\n`).

Control files are excluded from `artifacts`, `artifact_count`,
`payload_byte_size`, and `payload_sha256`, avoiding a self-hash cycle.

Verification order is structural archive checks -> manifest sidecar -> canonical
manifest/schema -> inventory counts/order/roles -> each artifact raw size/hash ->
cross-document identity/revision/hash invariants. Failure at any step invalidates
the entire bundle; partial imports are not published.

## Path and filesystem safety

Artifact paths are server-generated relative POSIX paths of at most 240 ASCII
characters. They begin with an alphanumeric character and may contain only
letters, digits, `.`, `_`, `-`, and `/`. Empty segments, `.`/`..` segments,
leading/trailing slash, repeated slash, backslash, drive letters, NUL/control
characters, percent-encoded traversal, and absolute paths are rejected.

A regex is only the first check. For any operator-selected import root, the
runtime MUST:

1. resolve and pin the allowed root before processing members;
2. walk each existing component with `lstat`/no-follow semantics;
3. reject a symlink in the file or any ancestor and reject devices, sockets,
   FIFOs, directories-as-files, and other non-regular inputs;
4. open with no-follow semantics where available, then `fstat` the descriptor;
5. confirm the final resolved descriptor remains beneath the pinned root;
6. read into bounded staging storage and recheck size/hash before publication.

The service never joins a client filename to a destination. Output locators are
derived from validated IDs or SHA-256 digests. These rules address traversal,
symlink escape, and common check-then-open races; a schema-valid path alone is
not authorization.

## Image safety and deterministic decoding

The v1 source-image allowlist is single-frame PNG and JPEG. Extension and
declared MIME type are advisory; detected magic/decoder format is authoritative,
and a conflicting declared supported type is rejected. SVG, GIF, WebP, TIFF,
archives, video, and raw CAD formats are unsupported.

Limits are enforced before and during decoding:

| Limit | v1 value |
| --- | ---: |
| raw image bytes | 25 MiB |
| width or height | 8,192 px |
| decoded pixels | 40,000,000 |
| frames | exactly 1 |
| inspection images per case | 64 |

Decoder decompression-bomb warnings are errors. The decoder verifies the source,
applies EXIF orientation, converts to RGB8, strips metadata, loads all pixels
within limits, and emits a deterministic PNG. Width, height, pixel count,
decoder/version, raw hash, canonical PNG hash, and packed RGB pixel hash are
recorded in image metadata.

The model receives only the canonical decoded representation. Reference and
inspection dimensions MUST match unless the case configuration explicitly names
one approved deterministic normalization policy. The analysis records source
and target dimensions, method, authorization, and parameter hash. An implicit or
request-selected resize is `NORMALIZATION_NOT_APPROVED`.

An anomaly mask MUST be a one-frame, 8-bit, single-channel PNG; its dimensions
must equal the analyzed target; and every decoded value must be `0` or `255`.
Wrong dimensions, non-binary values, format mismatch, truncation, or hash
mismatch is `MASK_CORRUPT` and prevents disposition/export publication.

## Archive limits

The v1 evidence archive format is ZIP with only regular file members and UTF-8
safe relative paths. Import preflights the central directory before extracting
anything and enforces:

- compressed archive at most 64 MiB;
- total declared and actual uncompressed payload at most 128 MiB;
- at most 100 payload members plus the two control files;
- each payload member at most 25 MiB;
- compression ratio at most 100:1 per member and in aggregate;
- no duplicate names, encrypted members, data outside declared members,
  directories, symlink/special Unix modes, or conflicting local/central names.

Extraction streams each member through byte and hash counters into a newly
created staging file. It never calls an unrestricted `extract` operation. Export
uses normalized member names, a fixed member timestamp/mode, no archive comment,
and deterministic member ordering. Bundle integrity is determined by the
manifest contract, not by ZIP metadata or a hash of the ZIP container.
