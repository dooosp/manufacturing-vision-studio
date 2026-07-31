# Security and accessibility review

Status: **PASS for the bounded local `DEMO_READY` scope.** No blocker or major
finding remains open. This is not a production-security assessment or a WCAG
conformance claim.

## Release evidence

- `uv run pytest -q`: **108 passed** across the adversarial, API, persistence,
  model, schema, evidence, and determinism suite.
- `uv run ruff check tests` and `uv run ruff format --check tests`: validation
  code quality.
- `npm --prefix web run check`: TypeScript and production build.
- `npm --prefix web run test:e2e`: real Chromium core flow, English/Korean
  parity, keyboard file chooser/focus, multi-image evidence binding, safe
  upload failure, export, and verification.
- Passing browser screenshot:
  `docs/screenshots/e2e-verified-evidence.png`.
  SHA-256: `6a57a5ee58e698285857c23472590de3550ddbdecc6547dff6f77bb980264e3c`.
- Adversarial corpus hashes are locked by
  `tests/test_adversarial_fixtures.py`; the corpus is local and network-free.

The final command counts and snapshot SHA are recorded in
`docs/reviews/SKEPTICAL_REVIEW.md` after the release rerun.

## Security and integrity

### Files, paths, and local mutation boundary

- [x] Component-aware containment rejects absolute paths, `..`, mixed
      separators, NUL/control bytes, prefix collisions, archive traversal, and
      normalized duplicate paths.
- [x] Symlinks inside and outside an allowed root, final-component symlink
      swaps, directories, and FIFOs fail closed without following or blocking.
- [x] Import verification applies archive member/count/size/ratio limits before
      registry publication; every rejected import leaves zero cases and zero
      blobs in the target registry.
- [x] Registry failures clean up newly created blobs and preserve the prior case
      revision and documents.
- [x] External and `null` mutation Origins, including deceptive localhost
      prefixes, receive `403 SCHEMA_INVALID` with zero state change. Origin-less
      CLI calls and exact `localhost`, `127.0.0.1`, and `[::1]` origins work.

Evidence: `tests/test_input_safety.py`, `tests/test_evidence_bundles.py`,
`tests/test_registry_fail_closed.py`, and `tests/test_api_fail_closed.py`.

### Images and resource handling

- [x] Detected decoded content, not extension or declared media type alone,
      selects PNG/JPEG handling.
- [x] Encoded-byte, edge, total-pixel, inspection-count, archive-byte,
      member-count, aggregate-size, and compression-ratio limits have boundary
      tests.
- [x] Fake signatures, truncation, unsupported formats, multi-frame images,
      PNG/JPEG trailing-payload polyglots, and decompression-risk dimensions
      fail with stable machine codes.
- [x] Reference/inspection dimension mismatch fails without implicit resize or
      normalization and publishes no analysis or mask.
- [x] Missing, malformed, wrong-hash, or non-reproducible masks cannot become a
      completed imported result.

Evidence: `tests/test_input_safety.py`, `tests/test_model_contract.py`,
`tests/test_registry_fail_closed.py`, and `tests/test_evidence_bundles.py`.

### Identity, state, pipeline, and evidence

- [x] Part ID, CAD revision, case revision, image IDs and raw/canonical/pixel
      hashes are authoritative document fields, never inferred from filenames.
- [x] Unknown pipeline/model versions and configuration-hash mismatch stop
      before invocation/publication; there is no default fallback.
- [x] Stale mutation revisions fail with `REVISION_MISMATCH` and preserve state.
- [x] All four human dispositions round-trip exactly; disposition never mutates
      the model result and cannot be recorded without a valid analysis binding.
- [x] Strict, version-pinned schemas and SHA-256 inventory verification precede
      re-import. Tamper, omission, duplicate path, unsafe member type, unknown
      version, corrupt mask, and identity substitution are fail-atomic.
- [x] Export -> verify -> import -> re-export preserves payload SHA-256,
      identity, scores, mapping, disposition, evaluation, and limitations.
- [x] API errors use the stable `{error:{code,message,details}}` envelope without
      stack traces, SQLite internals, or absolute paths; the browser also bounds
      and redacts every parsed server-message branch.
- [x] Synthetic fixtures and the complete demo require no network or secrets.
      The optional MVTec path is explicit and its non-commercial license is
      documented rather than bundled.

Evidence: `tests/test_api_fail_closed.py`, `tests/test_dispositions.py`,
`tests/test_registry_fail_closed.py`, `tests/test_schema_contracts.py`,
`tests/test_evidence_bundles.py`, and `docs/data/data-and-licensing.md`.

## Accessibility and bilingual experience

### Verified

- [x] Native buttons, inputs, checkbox, and labelled radio controls expose
      programmatic names. Headings, regions, figures, and evidence definition
      lists preserve semantic relationships.
- [x] The keyboard test focuses the hidden native upload input, confirms the
      visible focus proxy, opens the real file chooser with Enter, changes the
      disposition with Space, and records it with Enter.
- [x] Error and completed-export outcomes use `role="alert"` and `role="status"`;
      status and disposition are not communicated by color alone.
- [x] The inspection image alternative includes anomaly score, model verdict,
      mask area, mapped/unmapped location, affected feature, and human
      disposition. The visible overlay is supplemental.
- [x] English/Korean switching preserves case identity and exposes equivalent
      core controls, dispositions, lineage, status, safe-failure meaning, and
      demo limitations without changing stored enum values.
- [x] Full hashes remain in the DOM for selection/copy while CSS constrains
      visual overflow; the multi-image E2E proves the displayed filename and
      input hash match the analyzed image binding.
- [x] Functional small text and focus indicators use contrast-checked palette
      tokens; required demo limitations remain text in both the panel and
      footer.
- [x] A 640 px reflow check (1280 CSS-pixel desktop at a 200% proxy) keeps the
      Korean evidence and limitation journey without horizontal document
      overflow. Responsive breakpoints and reduced-motion CSS are present.

Evidence: `web/e2e/core-flow.spec.ts`, `web/src/App.tsx`,
`web/src/components/InspectionWorkspace.tsx`,
`web/src/components/EvidencePanel.tsx`, `web/src/copy.ts`, and
`web/src/styles.css`.

### Residual limits (non-blocking for this local demo)

- A real screen-reader session and an automated axe-style scan were not run.
  Browser role/name assertions cover the core semantics, but they are not a
  WCAG certification.
- The 640 px test is a deterministic reflow proxy, not a recording at every OS
  browser zoom/font setting.
- No concurrent multi-user load or authorization test is claimed. The shipped
  boundary is a single-user loopback demo; concurrency/authentication must be a
  new gate before any shared or remotely reachable deployment.
- Public-dataset downloading is not part of the default demo, so network,
  credential, and license propagation for a future downloader require a
  separate review.

## Findings resolved during review

1. Unknown pipeline/model and configuration mismatch previously risked
   provenance substitution; exact allow-list/config-hash checks and atomic
   regression tests now stop them.
2. Image path validation had a final-component swap window; no-follow open plus
   inode/device recheck and a race injection test close it.
3. Rejected case/image operations could leave orphan blobs; cleanup and count
   boundary tests now prove zero publication.
4. Archive special-file handling and re-import restoration had fail-open/broken
   paths; FIFO/symlink/duplicate/tamper tests and round-trip re-export now pass.
5. The UI initially paired analyses and evidence hashes with the first
   inspection image; the binding now follows `inspection_image_id` and has a
   multi-image Chromium regression test.
6. Upload focus, mask nonvisual context, hardcoded locale text, full-hash
   selection, client error redaction, and low-contrast functional text were
   corrected and exercised in the final browser suite.
7. PNG/JPEG decoders initially accepted bytes after the image terminator; the
   source validator now rejects trailing-payload polyglots before publication.
