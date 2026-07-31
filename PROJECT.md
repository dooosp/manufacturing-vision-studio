# Manufacturing Vision Studio

## Mission

Build a local-first visual inspection workbench that links image anomaly
evidence to a known part, CAD revision, and engineering feature, records an
explicit human disposition, and exports a reproducible evidence bundle.

The bounded v0.1 target is portfolio-grade `DEMO_READY` using deterministic
synthetic data. It is not a production inspection system and does not claim
shop-floor, safety, metrology, or real manufacturing validation.

## Product promise

A reviewer can complete this traceable journey without any cloud service:

1. Create or open an inspection case.
2. Select a declared part ID and CAD revision.
3. Import a reference image and one or more inspection images.
4. Run the versioned deterministic baseline.
5. Review the score, mask, and affected feature or an explicit unmapped state.
6. Record `accept`, `reject`, `needs_review`, or `model_error`.
7. Export an evidence bundle.
8. Re-import the bundle and verify its identity and SHA-256 inventory.

An automated result never releases a physical part. The disposition is the
reviewer's decision inside this demo case only.

## Current state

- Target: `DEMO_READY`
- Readiness decision: pending implementation and full validation
- Production/field state: explicitly not `FIELD_READY`
- Primary data: checked-in deterministic synthetic fixtures
- Optional external benchmark: locally supplied MVTec AD data, subject to its
  non-commercial license and never required for the distributable demo

Readiness is evidence-based. This file does not declare success; the release
packet must point to passing commands, evaluation artifacts, browser evidence,
and review findings.

## In scope for v0.1

- Python inspection and evaluation core
- Local API and local case registry
- TypeScript web UI with English and Korean core journey labels
- Strict versioned JSON contracts
- Deterministic synthetic reference, nominal, and defective images
- Part, CAD revision, case revision, pipeline, model, and configuration identity
- Deterministic registration, image differencing, anomaly scores, and masks
- Feature mapping with an honest unmapped/abstained state
- Explicit human disposition
- Evidence bundle export, re-import, and fail-closed verification
- Reproducible evaluation report
- Unit, integration, negative-path, and real-browser tests
- Local setup and demo commands

## Out of scope for v0.1

- Automated production accept/reject decisions or actuation
- Claims of defect coverage, process capability, safety, or production accuracy
- Live camera, PLC, MES, QMS, robot, or cloud integration
- Dimensional metrology or tolerance conformance from ordinary images
- Deep model training, online learning, or automatic model promotion
- Multi-user authorization, remote deployment, or high availability
- Inferring a trustworthy part or revision identity from image appearance
- Committing, redistributing, or commercially using MVTec AD data
- Modifying sibling `freecad-automation` or `b2b-lead-agent` repositories

## Product invariants

- Identity is declared and verified, never guessed from pixels.
- Every result is bound to `part_identity`, `case_revision`, pipeline, model,
  configuration, and source-image hashes.
- Every published result has a human disposition and explicit limitations.
- Unknown identity, feature, or model behavior is represented as unknown; it is
  never filled with a plausible value.
- Identity mismatch, malformed/unsafe input, incomplete evidence, or hash
  failure produces no accepted/published inspection artifact.
- The checked-in demo works without private data, MVTec AD, network access, or
  credentials.
- Synthetic smoke results demonstrate software behavior only, not field
  performance.

## Milestones

### M0 - SPEC_READY

- Product boundary, personas, journeys, non-goals, and readiness definitions
- Versioned contracts and trust boundaries
- Data/license inventory and evaluation protocol
- Acceptance criteria mapped to planned evidence

### M1 - Deterministic vertical slice

- One seeded case with a reference, a nominal inspection, and a defective
  inspection
- Analysis, feature mapping, human review, and local persistence
- Byte-stable outputs for equivalent repeated runs

### M2 - Evidence and failure closure

- Bundle export, verification, and deterministic re-import
- Negative-path coverage for identity, content, archive, and hash failures
- No publication on failed verification

### M3 - DEMO_READY decision

- Full validation and browser E2E pass from a clean setup
- Evaluation report generated twice with equivalent canonical metrics
- Security, skeptical product, and accessibility reviews have no unresolved
  blockers
- Known limitations and licensing are visible in product and evidence outputs
- Final release packet records either `DEMO_READY` or a concrete `HOLD`

### Future - FIELD_READY discovery

Field readiness is a separate project phase requiring real process ownership,
representative site data, measurement-system and process studies, operational
controls, and accountable approvals. It is not blocked work for v0.1 and must
not be implied by `DEMO_READY`.

## Source-of-truth documents

- [Product specification](docs/product/product-spec.md)
- [Readiness and acceptance criteria](docs/product/readiness-and-acceptance.md)
- [Data and licensing](docs/data/data-and-licensing.md)
- [Evaluation plan](docs/evaluation/evaluation-plan.md)
- `schemas/v1/*.schema.json` for machine-readable contract names and limits
- Test output, generated artifacts, `git status`, and commits for completion
  evidence

If prose and a v1 schema disagree, the schema is normative for machine
behavior and the discrepancy is a release blocker until the prose is corrected.
