# Independent validation matrix

Status: implemented; all evidence must be rerun at the final release commit.

This matrix translates the bounded `DEMO_READY` goal into independently
observable checks. Tests use public APIs, CLI entry points, and exported
artifacts. They must not depend on implementation-private helpers. A rejected
operation only passes when it also leaves no accepted or published inspection
result.

## Evidence conventions

- Every automated row is linked to one or more pytest node IDs in the final
  validation packet.
- Rejection assertions prefer a stable machine-readable error code. Human
  error text is not treated as the contract.
- Unless a row explicitly says otherwise, a failure must preserve the previous
  valid case state and must not publish a bundle, accepted result, or partial
  replacement artifact.
- SHA-256 is represented as 64 lowercase hexadecimal characters and is
  calculated over file bytes, not decoded image pixels.
- Determinism means semantic equivalence for runtime timestamps and byte
  equality for artifacts declared canonical or byte-stable. Runtime timestamps
  are excluded only by an explicit canonicalization rule.
- A test that needs a resource limit uses the configured limit plus one, not an
  arbitrary machine-dependent allocation.

## Matrix

| ID | Requirement | Input or fault | Required observation | Layer | Planned automated evidence |
| --- | --- | --- | --- | --- | --- |
| VAL-001 | Deterministic synthetic fixtures | Generate the same named fixture twice with the same seed/configuration | Declared stable image, mask, and metadata bytes and SHA-256 values are identical | Unit/integration | `tests/test_synthetic_determinism.py` |
| VAL-002 | Deterministic evaluation | Evaluate the same immutable dataset twice | Canonical metrics, counts, sample ordering, configuration hash, and dataset fingerprint are equivalent | Integration | `tests/test_evidence_bundles.py` |
| VAL-003 | Malformed image fails closed | Truncated/fake PNG bytes | Stable malformed-image code; no case image, result, or bundle is published | Unit/integration | `tests/test_input_safety.py` |
| VAL-004 | Oversized image fails closed | Encoded bytes, pixel dimensions, or decoded-pixel count one unit above each configured limit | Stable size-limit code occurs before expensive processing; no publication | Unit/integration | `tests/test_input_safety.py` |
| VAL-005 | Unsupported format fails closed | Valid GIF/text payload and extension/content-type disagreement | Stable unsupported-format code derived from decoded content, not filename alone | Unit/integration | `tests/test_input_safety.py` |
| VAL-006 | Path traversal fails closed | `../`, absolute path, encoded separator, and prefix-collision variants | Stable unsafe-path code; no read/write outside the configured root | Unit/integration | `tests/test_input_safety.py`, `tests/test_evidence_bundles.py` |
| VAL-007 | Symlink input fails closed | Symlink inside the root targeting a regular file inside and outside the root | Both are rejected; no target is read or modified | Integration | `tests/test_input_safety.py`, `tests/test_evidence_bundles.py` |
| VAL-008 | Non-regular input fails closed | Directory and FIFO/socket where supported | Stable non-regular-input code and no blocking read | Integration | `tests/test_input_safety.py`, `tests/test_evidence_bundles.py` |
| VAL-009 | Missing reference fails closed | Inspection case with no reference asset | Pipeline is not invoked; no inspection result or bundle is accepted | Integration | `tests/test_registry_fail_closed.py`, `tests/test_api_fail_closed.py` |
| VAL-010 | Revision mismatch fails closed | Reference and inspection identity differ by revision | No accepted result is created; mismatch is explicit and auditable | Integration | `tests/test_registry_fail_closed.py`, `tests/test_api_fail_closed.py`, `tests/test_evidence_bundles.py` |
| VAL-011 | Part mismatch fails closed | Reference and inspection identity differ by part ID | Same guarantees as VAL-010 | Integration | `tests/test_evidence_bundles.py` |
| VAL-012 | Dimension mismatch requires approval | Reference and inspection dimensions differ without an approved normalization record | Stable dimension-mismatch code; no implicit resize and no accepted result | Integration | `tests/test_model_contract.py`, `tests/test_registry_fail_closed.py` |
| VAL-013 | Unknown pipeline fails closed | Unregistered pipeline ID/version | Stable unknown-pipeline code; no fallback to a different version | Integration | `tests/test_registry_fail_closed.py`, `tests/test_evidence_bundles.py` |
| VAL-014 | Corrupt mask is detected | Truncated mask, wrong dimensions, or non-binary/out-of-contract values | Verification or import rejects the result; disposition cannot make it accepted | Integration | `tests/test_model_contract.py`, `tests/test_evidence_bundles.py` |
| VAL-015 | Hash mismatch is detected | Modify one covered payload byte after export | Verification and re-import reject the bundle and identify the covered member | Integration | `tests/test_evidence_bundles.py` |
| VAL-016 | Incomplete bundle is detected | Remove each required member/manifest field in turn | Every omission is rejected; no partial import or registry mutation | Integration | `tests/test_evidence_bundles.py` |
| VAL-017 | Export and re-import are reproducible | Export a complete disposed case, verify, import into an empty registry, and re-export | Manifest identity, covered member path set, hashes, scores, mapping, disposition, and evaluation metadata are equivalent | Integration | `tests/test_evidence_bundles.py` |
| VAL-018 | Bundle paths are confined | Archive member contains absolute/traversal/symlink-like path or colliding normalized names | Import rejects before extraction; nothing is written outside staging | Integration | `tests/test_evidence_bundles.py` |
| VAL-019 | Disposition is explicit | Attempt export before a valid human disposition; exercise all four values | Missing/unknown value is rejected; Accept, Reject, Needs Review, and Model Error round-trip exactly | Integration | `tests/test_dispositions.py`, `tests/test_evidence_bundles.py` |
| VAL-020 | Bundle completeness | Export a valid case | All required identity, lineage, input hashes, pipeline/model/config, scores, masks, feature mapping, disposition, timestamps, evaluation, limitations, and bundle hashes are present and schema-valid | Integration | `tests/test_schema_contracts.py`, `tests/test_evidence_bundles.py` |
| VAL-021 | Honest limitations | Inspect API/UI/exported bundle | Explicit synthetic/demo-only limitation is present; no production, safety, shop-floor, or measured real-world accuracy claim | Unit/E2E/review | `tests/test_evidence_bundles.py`, `web/e2e/core-flow.spec.ts`, review checklist |
| VAL-022 | English/Korean core journey | Run the core journey in both locales and a 640 px reflow viewport | Controls, statuses, dispositions, limitations, identity, and document width remain usable without mixed-language dead ends | Browser E2E | `web/e2e/core-flow.spec.ts` |
| VAL-023 | Keyboard and semantic accessibility | Open native file chooser with keyboard; operate locale/disposition/submit controls; inspect roles/names/states/focus and mask alternative | Visible focus; programmatic labels/status/errors; mask meaning, area, and location are not color-only | Browser E2E/review | `web/e2e/core-flow.spec.ts`, `docs/reviews/SECURITY_ACCESSIBILITY_CHECKLIST.md` |
| VAL-024 | Local-only/no secret leakage | Exercise external/`null`/loopback mutation Origins and scan error/artifact output | External mutation gets 403 with zero state; loopback/CLI works; no credentials, stacks, SQLite details, or absolute paths appear | Integration/E2E/review | `tests/test_api_fail_closed.py`, `web/e2e/core-flow.spec.ts`, security review |
| VAL-025 | Clean setup | Fresh checkout using documented commands | Setup, fixture generation, tests, demo, and evaluation succeed from declared prerequisites | System | final coordinator validation |
| VAL-026 | Configuration identity is authoritative | Invoke a registered pipeline/model with a different result-affecting configuration | Stable hash-mismatch code before invocation/publication; case and blobs unchanged | Integration | `tests/test_registry_fail_closed.py` |
| VAL-027 | Analysis display binding is exact | Analyze a case with two inspection images | Displayed filename, mask context, and full input hash match the analysis `inspection_image_id`, not array position | Browser E2E | `web/e2e/core-flow.spec.ts` |
| VAL-028 | Trailing-payload polyglot fails closed | Append non-image bytes after valid PNG IEND or JPEG EOI | Stable decode-failure code; source never reaches case state or model | Unit/integration | `tests/test_input_safety.py` |
| VAL-029 | Mutation Origin is loopback-confined | POST with external, `null`, deceptive prefix, exact loopback, IPv6 loopback, and no Origin | External/deceptive origins receive 403 and zero mutation; exact loopback and CLI calls succeed | API integration | `tests/test_api_fail_closed.py` |

## Mutation and fault-injection priorities

The initial mutation pass should target conditions that could turn a rejected
inspection into an accepted one:

1. invert part/revision equality checks;
2. skip one bundle member or hash verification;
3. replace registered pipeline lookup with a default fallback;
4. allow implicit dimension normalization;
5. resolve input paths before checking symlink status;
6. commit registry state before bundle verification completes;
7. treat a corrupt or missing mask as an empty valid mask.

Surviving mutations in these trust boundaries are blocking findings for
`DEMO_READY`.
