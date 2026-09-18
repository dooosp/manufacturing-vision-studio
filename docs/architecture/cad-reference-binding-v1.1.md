# CAD reference binding and evidence v1.1

The `coolgear-plate-top/v1` profile binds the eight H/P holes of a declared
1520×840 top view. A selected source is copied into the existing content-addressed
blob store and published with its reference image in one SQLite transaction.
`cad_bindings` preserves the original adapter manifest, reference PNG, feature-map
and CAD metadata. Missing/corrupted CAD bindings fail closed. Legacy synthetic
cases retain their existing model regions.

## Source selection and immutable bytes

Before a new CAD reference or CAD ZIP import, the local operator must provide
`trusted-cad-sources.json` in the selected MVS data directory:

```json
{
  "schema_version": "mvs-cad-source-selection/v1",
  "sources": [
    {
      "manifest_sha256": "<independently selected adapter manifest SHA-256>",
      "source_manifest_sha256": "<selected upstream FreeCAD output-manifest SHA-256>",
      "config_sha256": "<selected config SHA-256>",
      "model_sha256": "<selected native model SHA-256>",
      "source_commit": "<selected producer-input commit>",
      "producer_commit": "<exporter commit>"
    }
  ]
}
```

This is an explicit local source-selection input, not an output manifest or a
signature. The manifest digest is required; other supplied fields are checked
against the validated snapshot. Select these values from the reviewed producer
run, not from an untrusted archive during import. A fully rehashed internally
consistent archive still cannot override the external selection.

The reference bytes and regions are immutable once imported; use a new case for
a different view, image, region map or CAD revision. Both deterministic model
executions receive the stored regions. Reusing a CAD analysis checks image,
model configuration and CAD-binding consistency.

## Versioning and round trip

- The FreeCAD adapter manifest stays `1.0.0`; its payload profile is versioned.
- Inspection cases use their existing optional v1 `freecad_adapter_binding`.
- CAD analysis results use `1.1.0` with a separate `cad_binding` object.
  `configuration_sha256` keeps its original model-config meaning.
- CAD evidence bundles use `1.1.0`, preserve the four original payload bytes
  beneath `cad-reference/`, and reuse existing `freecad_adapter_manifest` and
  `freecad_artifact` roles. Analysis and evaluation entries identify their actual
  document schema versions.
- CAD case evaluation summaries are explicitly `case_reproducibility_only`.
  Unknown ground-truth counts and classification metrics are `null`, the verdict
  is `inconclusive`, and no human approval is inferred. Separate labeled synthetic
  evaluation belongs to a frozen evaluation protocol, not these case summaries.
- All `schemas/v1/` files remain unchanged. The published v0.1.0 synthetic bundle
  remains verifiable, importable and exportable. Older image-only CAD records lack
  the required feature evidence and cannot silently resume with example regions.

Verification checks case/image/adapter/ROI/analysis/disposition bindings and
replays CAD analysis using the preserved regions. Re-import needs the ZIP and an
independently retained source selection; it does not open the original export
folder or execute FreeCAD. A failed restore leaves no case or newly created blob
files. A successful re-export preserves the verified ZIP bytes.

The UI shows actual feature IDs, CAD revision and binding digest in English and
Korean. Reference images and masks use the same `contain` geometry, preserving
the complete view. A scripted disposition is explicitly distinguished from a
person's approval. This workflow establishes software evidence consistency;
physical testing, dimensional metrology and manufacturing release remain outside
its scope.
