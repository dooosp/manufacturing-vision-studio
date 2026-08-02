# E1 feasibility-separability study operator guide

This study has a fixed command surface and writes only beneath
`docs/evaluation/results/e1-feasibility-study`. Run it from the repository root
on the reviewed study commit. The commands accept no path, mode, seed, or phase
overrides.

## Command order

Run the mutating commands in this order. After every successful mutating
command, inspect and commit its evidence before invoking the next mutating
command.

1. `make validate-e1-study-implementation`
2. Commit `implementation-validation.json`.
3. `make e1-study-phase0`
4. Commit `retention-audit.json` and the four files under `retained-inputs/`.
5. `make e1-study-phase1`
6. Commit `phase-1-execution-claim.json` and
   `known-transform-diagnostic-108.json`.
7. `make e1-study-feature-oracle`
8. Commit `scope-audit.json` and `feature-ownership-oracle.json`.
9. `make e1-study-status`
10. Run `make e1-study-phase2` only when status reports
    `phase2_authorized: true`. If Phase 2 runs, commit
    `phase-2-execution-claim.json` and
    `known-transform-development-120.json`, then run status again.
11. `make finalize-e1-study`
12. Commit `decision.json` and `report.md`.
13. `make verify-e1-study`

If status does not authorize Phase 2, skip it and proceed directly to
finalization. Never infer authorization from the mere presence of earlier
files; the semantic status result is authoritative.

`status` and `verify` are read-only. They can be run at any time and do not
create the result directory when it is absent. `finalize` publishes and
verifies `decision.json` before it publishes `report.md`; an existing valid
decision/report pair is idempotent.

## Claims and interrupted runs

The Phase 1 and Phase 2 execution claims are permanent on-disk evidence that a
phase started. Each claim is published and reopened before the first render,
normalization, corpus, oracle, or inference callback. A phase must not be rerun
once its claim exists, even when the result is absent. Repairing evidence does
not authorize repeating study computation.

Any partial or orphaned packet is invalid. Examples include a phase claim
without its result, a result without its claim, only one of the scope/oracle
pair, only some retained inputs, or a report without its verified decision.
Stop and preserve the packet for diagnosis; do not delete files to make the
state appear pending.

There is one unavoidable filesystem-only limitation: manual deletion of an
uncommitted claim cannot be detected when no external append-only ledger or
committed Git object records that claim. Commit evidence immediately after each
mutating command. If an uncommitted claim is deleted, treat the study as
procedurally compromised rather than rerunning the phase.
