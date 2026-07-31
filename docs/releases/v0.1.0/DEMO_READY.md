# Manufacturing Vision Studio v0.1.0 release packet

## Decision

**DEMO_READY** for the bounded, local-first synthetic portfolio scope.

This decision means the deterministic synthetic journey, evidence contracts,
browser flow, adversarial checks, and clean-checkout setup pass. It does **not**
mean `FIELD_READY`, production inspection accuracy, safety validation,
shop-floor approval, regulatory approval, or authorization to release parts.

Release ref: annotated local tag `v0.1.0` after final review.
Validation base: `0e0566b2111b00181d34eda1c85a683d4055ebc5` on `main`.
No remote was configured, so nothing was pushed or deployed.

## Product summary

Manufacturing Vision Studio is a single-user loopback workbench for a quality
engineer reviewing images for a declared part and CAD revision. It imports a
reference and inspection images, runs a transparent registered-image-difference
baseline, displays the score/mask/feature mapping, records an explicit human
disposition, and exports a reproducible evidence bundle.

The distributable demo is project-owned synthetic data. A separately licensed,
user-supplied MVTec AD adapter is optional and is neither downloaded nor needed
for setup, tests, screenshots, or this release decision. Existing
`freecad-automation` and `b2b-lead-agent` repositories remained read-only.

## Architecture summary

- Python 3.11+ core with a versioned model interface and deterministic
  registration/image-difference implementation.
- FastAPI loopback API with strict request models, numeric `If-Match` case
  revisions, safe error envelopes, and external-Origin mutation rejection.
- SQLite registry plus content-addressed local blobs.
- Draft 2020-12 closed JSON Schemas at contract version `1.0.0`.
- React/TypeScript bilingual workbench with exact analysis-to-image evidence
  binding, keyboard support, mask text alternatives, and human-owned review.
- Deterministic ZIP export, strict independent verifier, fail-atomic re-import,
  and byte-identical re-export for the same disposed case.
- Optional read-only FreeCAD export-manifest adapter and optional local MVTec
  inventory adapter.

The exact trust boundaries are documented in
[`docs/architecture`](../../architecture/README.md).

## Implementation and commits

| Area | Evidence |
| --- | --- |
| Product, data, license, evaluation | `48a5a46` |
| Schemas and trust contracts | `8d4e162` |
| Initial bilingual workbench | `3c0cac1` |
| Core, API, registry, evidence, adapters | `64e6f0f` |
| External mutation-Origin defense | `e7bbea8` |
| UI binding, accessibility, redaction, contrast | `50667fa` through `27119cc` |
| Exact PNG/JPEG container termination | `ae32e91` |
| Adversarial and Chromium validation | `0e0566b` |

Primary implementation paths are `src/manufacturing_vision_studio`, `web/src`,
`schemas/v1`, `tests`, and `web/e2e`.

## Validation results

`make validate` was rerun from the integration workspace and from a clean,
detached worktree at the validation base:

- Ruff: pass.
- Mypy: pass for 14 source files.
- Pytest: **108 passed**, one non-blocking third-party
  FastAPI/Starlette `TestClient` deprecation warning.
- TypeScript typecheck and Vite production build: pass, 39 transformed modules.
- Real Chromium E2E: **4 passed** covering review/export/verify, English/Korean
  parity and reflow, keyboard upload/focus, multi-image evidence binding, and
  malformed-upload fail-closed behavior.
- Clean worktree: `make setup` and `make validate` pass; npm audit reports
  **0 vulnerabilities**. `make setup` installs the locked Python/web packages
  and the Chromium test runtime.

Validated environment:

- Darwin 25.5.0 arm64
- uv 0.10.12; Python 3.12.13
- Node 25.8.0; npm 11.11.0
- Playwright 1.62.1, Chromium project
- `uv.lock` SHA-256:
  `0c3504b978359b387b09c58bd48809268589e7607900da1f0f9b7bb44c89427c`
- `web/package-lock.json` SHA-256:
  `4799de255f589d2f3d4bd886c478a68a37c2b848e641fbfb4c1d363d6216fdbb`

## Evaluation and evidence round trip

The E0 evaluation contains exactly two synthetic inspections: one positive and
one negative. Results were `TP=1`, `TN=1`, `FP=0`, `FN=0`; both
pre-registered classification expectations passed. Two pre-publication
executions produced the same deterministic result SHA-256 at tolerance `0.0`.
These are **2/2 synthetic golden cases**, not an estimate of field accuracy.
No pixel-level benchmark IoU or Dice was evaluated.

The final disposed case is revision 8. Export and independent verification
report 15 payload artifacts. Import into an empty registry followed by
re-export produced byte-identical ZIP files.

- Bundle SHA-256:
  `1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7`
- Payload SHA-256:
  `35606fde93bf07e3e9814fb0ce1b0f87e19ec66e16345bde61502b4145061cd7`
- Evaluation report SHA-256:
  `38c79c5e571720610274076941f587625052c306ca0f52ec8b4efd3b4ab35a59`

Artifacts:

- [`evidence-bundle.zip`](evidence-bundle.zip)
- [`bundle-manifest.json`](bundle-manifest.json)
- [`synthetic evaluation`](../../evaluation/results/v0.1.0-synthetic.json)

## Browser, security, and skeptical review

- [Automated Chromium verification screenshot](../../screenshots/e2e-verified-evidence.png),
  SHA-256
  `6a57a5ee58e698285857c23472590de3550ddbdecc6547dff6f77bb980264e3c`.
- [English workbench screenshot](../../screenshots/workbench-en.png).
- [Korean verified-export screenshot](../../screenshots/evidence-verified-ko.png).
- [Security and accessibility review](../../reviews/SECURITY_ACCESSIBILITY_CHECKLIST.md):
  PASS for the bounded demo; no open blocker or major finding.
- [Skeptical product review](../../reviews/SKEPTICAL_REVIEW.md): SHIP for
  `DEMO_READY`; no production or field-readiness claim.

The review-driven fixes include configuration-substitution rejection,
no-follow image reads, orphan-blob cleanup, archive special-file rejection,
exact analysis/image/hash binding, client error redaction, keyboard focus,
nonvisual mask context, readable contrast, loopback mutation confinement, and
PNG/JPEG trailing-payload rejection.

## Known limitations

- The detector is a transparent synthetic baseline, not a trained or
  field-calibrated production model.
- The two-case evaluation is intentionally too small for generalization,
  confidence intervals, calibration, or production accuracy claims.
- Segmentation benchmark IoU/Dice and representative real defect modes were
  not evaluated.
- Feature mapping uses declared 2D regions; it is not a proven 3D CAD
  correspondence.
- Real camera variability, lighting, viewpoint, measurement-system analysis,
  operator UAT, multi-user authorization/load, and deployment hardening remain
  outside the bounded scope.
- Screen-reader and axe certification were not run; browser roles, names,
  keyboard behavior, mask alternatives, contrast, and narrow reflow were
  checked without making a WCAG conformance claim.
- MVTec AD remains non-commercial CC BY-NC-SA 4.0 optional data and is not
  included in this release.

## Next recommended milestone

Keep this project `DEMO_READY` and avoid expanding it into unrelated features.
The next evidence-bearing milestone should be an **E1 expanded synthetic
robustness suite** with frozen recipe-level splits, authoritative segmentation
masks, nuisance variation, pixel/feature metrics, and explicit abstention
analysis. Real camera/site validation remains a separate `FIELD_READY` program.
