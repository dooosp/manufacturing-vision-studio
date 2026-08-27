# E1 Attempt 3 Successor Repair Review Contract

## Authority and use

This contract governs two different review gates:

1. the current four-document design review; and
2. the future four-domain whole-branch implementation review, if and only if
   the user separately authorizes implementation.

It does not authorize implementation, study execution, QA, Push, or PR.

## Pinned ranges

### Documentation review

```text
BASE = ecec6e128ff560ab0e7b8ec403dca861ce0965ee
HEAD = DOC_HEAD
RANGE = ecec6e128ff560ab0e7b8ec403dca861ce0965ee..DOC_HEAD
```

The range must contain exactly these four tracked documents and no other path:

- `docs/superpowers/specs/2026-08-23-e1-attempt3-successor-repair-design.md`;
- `docs/superpowers/plans/2026-08-23-e1-attempt3-successor-repair.md`;
- `docs/superpowers/plans/2026-08-23-e1-attempt3-finding-to-test-matrix.md`;
- `docs/superpowers/plans/2026-08-23-e1-attempt3-review-contract.md`.

Any documentation repair changes `DOC_HEAD`. Re-pin the exact range, rebuild
the package, and restart the review; no prior approval transfers.

### Future final whole-branch review

```text
BASE = 8e4b3ff52461c907c728fb2eae6660dafba7c53a
HEAD = FINAL_HEAD
RANGE = 8e4b3ff52461c907c728fb2eae6660dafba7c53a..FINAL_HEAD
```

The base is intentionally earlier than `ecec6e1`. The checkpoint already
contains 39 predecessor commits whose cumulative trust boundary is part of the
claim. A review limited to `ecec6e1..FINAL_HEAD` is invalid.

## Required review package

Before dispatch, the coordinator must create one read-only package containing:

- exact base SHA, head SHA, and both tree SHAs;
- `git diff --binary --full-index BASE..HEAD`;
- `git diff --stat BASE..HEAD`;
- `git log --oneline --decorate BASE..HEAD`;
- changed-path list and SHA-256;
- package SHA-256;
- this common contract;
- the applicable appendix below;
- PRE identity, validation, hash, and side-effect evidence required by the
  relevant gate.

Every reviewer receives the same package bytes and package SHA. A reviewer may
read repository context and run read-only/focused diagnostic tests, but must
not edit, stage, commit, execute a study phase, or mutate a sibling worktree.

Each reviewer records before and after:

```text
git rev-parse HEAD
git rev-parse HEAD^{tree}
git status --porcelain=v1 --untracked-files=all | shasum -a 256
git diff --check
```

The before and after values must match. An unexpected mutation invalidates the
review even when its substantive verdict is `APPROVE`.

## Common severity scale

- **P0:** immediate destructive, security, evidence-integrity, or execution
  failure capable of invalidating protected artifacts or crossing the frozen
  product boundary.
- **P1:** a realistic trust-boundary, current-credit, identity, validation, or
  approval defect that blocks the branch's stated evidence claim.
- **P2:** a bounded correctness or contract defect that does not currently
  create P0/P1 impact but must be resolved before approval.
- **P3:** non-blocking maintainability or clarity note with no present claim or
  trust-boundary impact.

Only P0/P1/P2 are approval blockers. Reviewers must not downgrade a finding
because another reviewer may cover it.

## Finding evidence standard

A blocking finding must include:

1. a unique ID or the applicable existing `A3-REPO-*` ID;
2. severity and affected invariant;
3. exact file and line or function boundary;
4. reachable data/control flow from input to incorrect public result;
5. a minimal reproduction or deterministic proof;
6. observed result and required result;
7. why existing tests or guards do not close it;
8. whether it is introduced, aggravated, or merely exposed by the reviewed
   range;
9. the smallest safe repair boundary, without implementing it.

Speculation without a reachable path is not a blocking finding. A duplicate is
merged under the existing ID and keeps the highest supported severity. A
finding seen in more than one domain is counted once in the deduplicated total.

## Common frozen claims

Every review must treat these as binding:

- Candidate Selection remains `HOLD / null / UNVERIFIED` and its raw, record,
  and projection hashes remain exact;
- embedded Candidate A/B and historical 120/108 evidence remain exact;
- thresholds, seed, protocol, acceptance gates, fixed E1 results, and study
  phase authorization remain unchanged;
- feasibility implementation-projection membership/order remains 47 unique
  paths in protocol order;
- the successor aggregate projection hash may change only as a deterministic
  consequence of authorized member edits;
- the four protected artifacts remain byte-identical;
- historical evidence remains auditable but never grants current credit;
- the dirty Candidate Selection file and every sibling worktree remain
  untouched;
- prohibited study-result paths remain absent;
- no study, candidate comparison, search, inference, evaluation, oracle,
  finalization, Push, PR, or QA operation occurs.

## Verdict format

The first line must be exactly one of:

```text
APPROVE
NEEDS FIXES
```

`APPROVE` is legal only when the reviewer has zero unresolved P0/P1/P2.
The remainder must contain:

```text
Range: <exact BASE..HEAD>
Package SHA-256: <exact digest>
Appendix: <DESIGN, A, B, C, or D>
Blocking findings: P0=<n>, P1=<n>, P2=<n>
Findings: <ordered evidence or NONE>
Required tests/checks inspected: <evidence>
Frozen claims checked: <evidence>
Before/after repository state: <evidence>
Residual P3 notes: <ordered notes or NONE>
```

An ambiguous verdict, missing package hash, wrong range, wrong HEAD, or missing
repository-state proof is `NEEDS FIXES` regardless of prose.

## Documentation-review appendix

The independent design reviewer must establish all of the following:

- the authorization is documentation-only and limited to four paths;
- `ecec6e1` is consistently classified as `REVIEW_REJECTED_CHECKPOINT`;
- repository findings are exactly `P0=0/P1=7/P2=1`, including timeout P1;
- plan-review findings use a separate namespace and are never added to the
  repository total;
- all eight invariants are normative and testable;
- all seven runtime/trust tasks and one timeout task have independent RED,
  GREEN, controls, path allowlists, commit/review boundaries, and stop rules;
- timeout changes only tuple ordinal 3 from 1,800 to 7,200, keeps a closed
  additive v1 enum, and denies current credit to legacy 1,800 semantics;
- the design, plan, matrix, and this contract agree on base, branch, review
  ranges, hashes, frozen scope, prohibited paths, and QA handoff;
- no wording pre-approves `BASELINE_ACCEPTED`, QA Core, Push, or PR;
- there are no placeholders or unresolved material choices left for an
  implementer.

## Final Appendix A — Artifact state

Review current-state computation and terminal publication end to end:

- empty-root `PENDING` remains read-only zero of zero;
- a nonempty packet without a verified anchor receives zero credit;
- anchored invalid packets run deep validation;
- honestly sealed `STUDY_INVALID` evidence can receive exact credit;
- forged, stale, mismatched, or corrupt terminal evidence receives none;
- unauthorized Phase 2 remains invalid and its terminal pair is checked;
- absent report recovery, exact report idempotence, and corrupt present report
  rejection are mutually consistent;
- historical evidence remains preserved but is not current evidence.

Inspect `study_runner_v2.py`, its schemas and artifact helpers, all focused
RED/GREEN tests, and adjacent malformed/invalid/finalization controls.

## Final Appendix B — Truth boundary

Review the finite abstract interpreter as one trust boundary:

- exact `sys`, may-`sys`, incomplete, and identity-top remain distinct;
- dead `If`/`IfExp` syntax contributes policy facts but no runtime effects;
- may protected provenance survives list/dict/subscript and unknown-call
  carriers without becoming an approval identity;
- direct, `getattr`, bound `__getattribute__`, and import-from paths share the
  finite sensitive-member grammar;
- PEP 562, CLI dataclass, two approved plan roles, harmless reflected access,
  safe source, and depth/complexity controls remain exact;
- capability dimension and canonical bounds change only as designed;
- no general reflection evaluator, object graph, or unbounded state is added.

Inspect `study_retention_v2.py`, dependency-guard tests, the real checkout
scanner, required-negative families, and required-positive families.

## Final Appendix C — Evidence identity

Recompute rather than copy:

- current Selection raw/record/projection hashes and
  `HOLD / null / UNVERIFIED` semantics;
- Candidate A/B hashes and historical raw/record/projection/snapshot hashes;
- historical 120/108 counts, denominators, paths, schema IDs, and gates;
- all four protected artifact hashes;
- feasibility config and exact 47-path projection membership/order;
- before/after feasibility member hashes and aggregate projection hash;
- zero overlap between changed feasibility members and Candidate Selection;
- prohibited-path absence and every sibling worktree fingerprint, using the
  exact recorded command for each status/diff digest. In particular, keep the
  original dirty sibling's plain `git diff` digest distinct from its
  `git diff --binary --full-index` digest.

This review must explicitly distinguish an allowed deterministic feasibility
projection hash change from a forbidden projection membership/order change or
Candidate Selection rebind.

## Final Appendix D — Integration and timeout

Review the actual supported entrypoints and full system evidence:

- exactly six sealed commands retain name, argv, cwd, environment, order,
  output cap, snapshot checks, `shell=False`, and process-group kill behavior;
- only ordinal 3 changes from 1,800 to 7,200 seconds;
- schema v1 structurally accepts legacy 1,800 and current 7,200 while semantic
  verification accepts 7,200 only at ordinal 3;
- 7,200 is rejected at every other ordinal and non-enum values are rejected;
- exact ten-module suite and a fresh uninterrupted `make validate` pass at
  `FINAL_HEAD`;
- CLI, Make, config, web, documentation, and operator claims remain aligned;
- the validation run does not create result roots or prohibited artifacts;
- unrelated npm advisory or warning evidence is reported without being hidden
  or silently absorbed into this scope.

## Repair budget and restart rule

Each task gets one initial implementation. A valid task-review finding permits
at most one focused repair for that task, followed by a fresh review. If the
same blocker remains, or a new structural/out-of-scope P0/P1/P2 appears, stop
and request the user's A/B/C decision defined in the design.

Any change after integrated validation invalidates that validation and every
review tied to the prior HEAD. Repair only if it remains within an already
authorized task and budget; otherwise stop. Then rerun the exact ten-module
suite, full `make validate`, POST audit, package creation, and all four reviews
from the beginning on the new HEAD.

## QA gate

Four `APPROVE` verdicts make `FINAL_HEAD` eligible only for a fresh QA Stage 1
audit in a new worktree. Stage 1 must independently return either
`BASELINE_ACCEPTED` or `BASELINE_HOLD`; neither is preselected. QA Core work
requires a later explicit user approval even after `BASELINE_ACCEPTED`.
