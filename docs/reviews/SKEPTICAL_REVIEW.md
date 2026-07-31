# Skeptical product review

Status: **SHIP for the bounded local `DEMO_READY` portfolio demo.** The result
does not establish production inspection fitness, field accuracy, safety
validation, regulatory approval, or `FIELD_READY` status.

## Final validation snapshot

- Repository: `manufacturing-vision-studio`
- Branch: `main`
- Validation commit: recorded by the final validation commit containing this
  review.
- Python: `uv run pytest -q` -> **108 passed**; one third-party
  FastAPI/Starlette TestClient deprecation warning remains non-blocking.
- Validation lint/format: Ruff check and format-check -> **pass**.
- Web: `npm --prefix web run check` -> **pass**.
- Browser: `npm --prefix web run test:e2e` -> **4 passed** in real Chromium.
- Browser artifact:
  `output/playwright/test-results/core-flow-engineer-reviews-4a50d-d-exports-a-verified-bundle-chromium/verified-evidence-workbench.png`.

The commands above must be rerun after any source, schema, dependency, or
evidence-contract change.

## Blocking product questions

- [x] Create/open -> image import -> analyze -> review -> export -> independent
      verify runs locally in Chromium; verified bundle re-import/re-export is
      covered by the integration suite without manual file edits.
- [x] Part ID, CAD revision, case revision, pipeline/model versions,
      configuration hash, and source image hashes remain inspectable at review.
      Full hashes stay in the DOM and in exported evidence.
- [x] Model verdict and human disposition are distinct documents and separate
      UI regions; all four exact lowercase values persist with reviewer,
      rationale, revision, and timestamp.
- [x] Part, CAD revision, case revision, pipeline, model, configuration, image,
      and bundle mismatch paths stop with stable codes and zero publication.
- [x] `needs_review` and `model_error` remain exact disposition states and are
      never converted to `accept`; the demo exposes no misleading aggregate
      "accepted" counter.
- [x] Feature evidence is bounded to declared regions. An anomaly without a
      justified overlap produces an explicit `unmapped` finding rather than a
      fabricated CAD feature.
- [x] Incomplete export and failed verification cannot produce a verified
      package or mutate an import target.
- [x] Re-import performs structural, resource, schema, inventory, hash,
      cross-document identity, mask, and reproducibility checks before registry
      restoration.
- [x] Synthetic demo evidence and optional MVTec evaluation are separated.
      MVTec is not committed or downloaded by default; its CC BY-NC-SA 4.0
      non-commercial restriction is documented.
- [x] UI, API description, documents, evaluation, and bundles state the
      synthetic/demo-only boundary and avoid production accuracy, safety,
      shop-floor release, regulatory, or `FIELD_READY` claims.
- [x] Evaluation output includes data origin/fingerprint, sample counts,
      pipeline/model/configuration identity, metric definitions, limitations,
      and deterministic comparison evidence.

## Adversarial reviewer answers

1. **Which bytes were inspected and displayed?** Image documents retain raw,
   canonical-image, and pixel SHA-256 values; analysis input binding repeats all
   three domains; mask metadata covers exact mask bytes. Bundle inventory and
   sidecar cover every payload. The multi-image E2E proves the displayed file
   and hash follow `inspection_image_id`, not list position. Evidence:
   `tests/test_evidence_bundles.py`, `tests/test_model_contract.py`, and
   `web/e2e/core-flow.spec.ts`.
2. **Can revision A evidence be reused for revision B?** No. Exact part/CAD and
   case revisions are checked at mutation, disposition, export, verify, and
   import. Mutated part/revision manifests fail atomically. Evidence:
   `tests/test_registry_fail_closed.py`, `tests/test_api_fail_closed.py`, and
   `tests/test_evidence_bundles.py`.
3. **What if a required bundle member is corrupt?** Verification/import returns
   `HASH_MISMATCH`, `MASK_CORRUPT`, or `EVIDENCE_INCOMPLETE` as applicable; the
   target registry has zero cases and blobs. Evidence:
   `test_adversarial_bundle_is_rejected_before_import_publication`.
4. **Can extension/content-type tricks bypass decoding?** No. Fake signatures,
   declared/detected mismatch, unsupported and multi-frame formats, truncated
   bytes, oversized images, and bytes after PNG/JPEG terminators fail closed.
   Evidence: `tests/test_input_safety.py` and
   `fixtures/adversarial/README.md`.
5. **Can an unknown pipeline or model silently use the default?** No. Unknown
   interface/pipeline/model versions and mismatched configuration hashes stop
   before model invocation and leave the case/blobs unchanged. Evidence:
   `tests/test_registry_fail_closed.py` and
   `tests/test_evidence_bundles.py`.
6. **Why can two exports differ?** They do not for the same disposed case: ZIP
   metadata is canonicalized and the byte-stability test compares full bundle
   bytes. Evaluation projection is independently deterministic. Runtime IDs and
   timestamps are part of their declared contracts, not silently stripped.
   Evidence: `test_export_is_byte_stable_and_evaluation_projection_is_deterministic`.
7. **Is a zero mask distinct from a corrupt mask?** Yes. A valid zero-anomaly
   model result produces a dimension-matched 8-bit binary PNG and zero score;
   corrupt, missing, wrong-sized, or non-reproducible masks fail verification.
   Evidence: `tests/test_model_contract.py` and
   `tests/test_evidence_bundles.py`.
8. **Can a human accept before evidence checks pass?** No. Disposition requires
   an existing analysis, exact current revision, and bound analysis identity.
   Export additionally requires a disposition and complete evidence. Evidence:
   `tests/test_dispositions.py` and `tests/test_evidence_bundles.py`.
9. **Does Korean retain the English warnings and controls?** Yes for the core
   journey. Chromium asserts identity persistence, all four dispositions,
   evidence/disposition regions, safe limitations, narrow reflow, and locale
   labels. Stored enum/hash values do not change. Evidence:
   `web/e2e/core-flow.spec.ts`.
10. **Does the demo work offline?** Yes. Checked-in fixtures, generation,
    analysis, API, SPA, evaluation, and evidence operations use local files and
    loopback servers only. Optional public data is not a default dependency.

## Resolved findings

The adversarial pass found and drove fixes for configuration substitution,
image-path TOCTOU, rejected-operation orphan blobs, incorrect inspection-count
accounting, special ZIP members, incomplete re-import restoration, explicit
unmapped findings, incomplete provenance hashes, external mutation Origins,
analysis/display binding, unsafe UI error propagation, keyboard focus,
nonvisual mask context, bilingual hardcoded strings, truncated hashes,
functional-text contrast, and trailing-payload image polyglots.

## Residual limits

- The only test warning is a third-party TestClient deprecation warning; it does
  not affect runtime behavior or evidence bytes.
- Screen-reader/axe certification, OS-level 200% zoom recording, multi-user
  concurrency/load, remote authentication, and production deployment hardening
  were not claimed. They are gates for a future scope, not evidence for this
  local single-user demo.
- MVTec licensing and domain gap prevent using its optional results as a
  production accuracy claim. Synthetic evaluation remains a deterministic
  pipeline and evidence-contract check only.

## Exit rule result

Every blocking item above has automated or browser evidence. No unresolved
blocker or major finding remains in the bounded demo scope. Any expansion to
shared networking, real customer data, automated release decisions, or field
deployment resets this review to open.
