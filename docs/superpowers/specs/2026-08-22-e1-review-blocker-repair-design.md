# E1 Whole-Branch Review Blocker Repair Design

## Status and authority

This design records the focused repair cycle approved by the user in the
current Codex session on 2026-08-22. It succeeds, but does not rewrite, the
current-identity repair design at
`docs/superpowers/specs/2026-08-17-e1-task7-current-identity-repair-design.md`.

- Repository: `manufacturing-vision-studio`
- Pinned base and preserved checkpoint:
  `c68930986ebc88f08d501d6204ee5727f7abcee9`
- Repair branch: `codex/e1-review-blocker-repair`
- Repair worktree:
  `/Users/jangtaeho/manufacturing-vision-studio-e1-review-blocker-repair`
- Original dirty worktree:
  `/Users/jangtaeho/manufacturing-vision-studio-e1-dataflow-redesign`
- Preserved current-identity worktree:
  `/Users/jangtaeho/manufacturing-vision-studio-e1-current-identity-repair`
- Parked QA worktree:
  `/Users/jangtaeho/manufacturing-vision-studio-quality-evidence-change-review-v0.3.0`
- Preserved historical-run sibling:
  `/Users/jangtaeho/manufacturing-vision-studio-e1-v2`

The `c689309...` checkpoint remains a `REVIEW_BLOCKED_CHECKPOINT`, not a
`QA_APPROVED_BASELINE`. QA work remains unauthorized until this repair has
passed all integrated validation and all four whole-branch reviews.

The user-approved in-chat design is the requirements source. Its binding
sequence is:

```text
preserve c689309 checkpoint
  -> create an isolated repair branch/worktree
  -> reproduce four review findings as RED tests
  -> repair scanner policy and study verification independently
  -> prove the checked Candidate Selection identity remains byte-identical
  -> bind later study validation only to the new feasibility-study projection
  -> restart all Task 7 gates
  -> require four of four whole-branch reviews
  -> authorize QA only from the newly approved SHA
```

## Problem statement

The prior repair resolved all 19 known repository test failures and produced a
clean automated-validation result. The mandatory whole-branch review then
found four evidence-backed fail-open conditions:

1. The source-flow analyzer evaluates constant `is`/`is not` comparisons with
   equality/inequality semantics. A false runtime identity comparison can be
   modeled true and can erase a sensitive capability before a later sink.
2. The analyzer transfers every operand of a chained comparison eagerly.
   Python stops evaluating later comparators after a false comparison, so an
   unreachable named-expression write can incorrectly replace the state that
   actually reaches a protected sink.
3. Protected `EvaluationScope` members and acquired `plan_cases` callables are
   recognized by surface spelling rather than durable value provenance.
   Literal `getattr`, import aliases, or a callable alias can evade the exact
   protected-scope and provider-only call rules.
4. If a pre-decision JSON artifact becomes malformed after a valid decision
   and report were written, JSON verification returns before the optional
   invalid-terminal projection is checked. The stale decision and report can
   remain in `verified_paths`, overstating the current verification rate.

The first two findings were introduced by the immutable source-flow rewrite at
`50249414ba154fab8caa2760744ac162453a579a`. The third behavior existed in the
former visitor and was retained by that rewrite. The fourth behavior predates
the whole-branch review base, while `fc4c9546d78a2001062b9167a61cce4db96b0b00`
only closed the narrower malformed-decision dependency case. Regardless of
origin, all four are load-bearing review blockers for the current branch.

## Goals

1. Model constant equality and identity comparisons without conflating their
   Python semantics.
2. Preserve Python chained-comparison short-circuit state while still
   policy-inspecting unreachable source without committing its runtime effects.
3. Carry protected-scope and `plan_cases` provenance through aliases and reject
   every call form except the already approved exact provider expression.
4. Exclude a stale decision and report from current verification credit when a
   declared upstream JSON artifact is malformed, while still permitting a
   separately generated and fully validated `STUDY_INVALID` decision/report.
5. Preserve the checked Candidate Selection and its downstream source-hash
   mirrors byte-for-byte because the changed study files are outside that
   selection's 47-path projection.
6. Re-run every integrated Task 7 gate and obtain four independent approving
   whole-branch reviews.

## Non-goals

- Candidate comparison, ranking, search, inference, benchmark execution, or a
  new candidate
- implementation validation, feature-oracle execution, finalization, or any
  study phase
- changes to projection membership/order, schemas, public APIs, thresholds,
  seeds, evaluation modes, candidate metrics, or phase authorization
- deletion or rewriting of stale historical decision/report bytes
- changing the separate inventory-invalid early-return behavior, which is not
  implicated by the reviewed malformed-declared-JSON finding
- copying, generating, or tracking ignored Candidate A/B raw files
- result-root creation, FreeCAD execution, sibling modification, Push, PR, or
  remote mutation
- resolving the existing Starlette/httpx warning or npm advisory in this repair
- QA Layer implementation or semiconductor example work

## Selected architecture

### 1. Source-flow comparison semantics

The comparison transfer remains inside the existing finite abstract
interpreter. It does not execute projected source.

Single comparisons derive truth through a dedicated finite helper:

- `Eq` and `NotEq` use equality semantics for literal constants.
- `Is` and `IsNot` never reuse equality. Identity is proven only where the
  finite model can do so soundly: both operands must be literal `None`,
  `True`, `False`, or `Ellipsis`. Equal non-singleton literals remain unknown
  rather than inheriting parser/interpreter object interning.
- Existing exact `sys` versus complete non-`sys` identity reasoning remains.
- Unsupported comparison operations remain unknown.

Chained comparisons transfer the left operand once, then process each
comparator in order on only the preceding comparison's truthy continuation.
Each false or possible-false result is retained as an overall falsy exit. If a
continuation is unreachable, later syntax is inspected with the existing
`unreachable` transfer context so forbidden source remains visible, but its
binding writes and runtime dependency edges do not enter the reachable state.
The existing finite convergence and exceptional-exit rules remain binding.

### 2. Durable protected identity provenance

The analyzer uses its existing finite resolved-identity lattice rather than
adding an unbounded name or object graph.

- An exact import of
  `manufacturing_vision_studio.e1.domain_v2.EvaluationScope` already carries a
  resolved identity. Protected-member checks use that identity as well as the
  legacy literal spelling, so ordinary assignment and import aliases remain
  visible.
- Attribute access and literal `getattr` both recognize protected members.
- A computed member name on an `EvaluationScope` value fails closed because it
  cannot prove that a protected member is excluded.
- Acquiring `.plan_cases` produces a dedicated finite resolved callable
  identity that survives ordinary alias assignment.
- Invoking that identity is rejected unless the call node itself matches the
  existing exact `DevelopmentCorpusProvider` or legacy-v1 allowlisted form.
  Merely originating inside the provider class does not authorize an alias.

No general reflection engine, object-sensitive heap, or new public interface is
introduced.

### 3. Malformed-upstream terminal projection

The JSON verification loop continues collecting every parse/schema failure.
When `invalid_json` is non-empty, it first builds the existing invalid state and
then passes that state through `_verify_invalid_terminal_projection`, just as
relationship and semantic failures already do.

This gives two distinct outcomes:

- A stale performance decision/report fails its `STUDY_INVALID` projection and
  both paths are invalidated.
- A separately created `STUDY_INVALID` decision/report may retain credit only
  after identity, upstream bindings, payload counts, invalid paths, rate, and
  rendered report bytes all verify against the current malformed packet.

For the 14-path regression fixture with malformed
`known-transform-development-120.json`, the stale packet must expose exactly 11
verified paths: the malformed upstream, stale decision, and stale report are
all excluded.

### 4. Identity preservation without a Candidate Selection rebind

Both production files changed by this repair are members of the separate
feasibility-study implementation projection:

- `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- `src/manufacturing_vision_studio/e1/study_runner_v2.py`

They are not members of `configs/evaluation/e1-v2-candidate-selection.json`'s
fixed 47-path current projection. The approved `d8cf9e6...` selection rebind is
therefore already complete and must not be reopened.

Relative to `c689309...`, the Candidate Selection semantic allowlist is empty:
its raw bytes, record hash, current implementation projection, Candidate A/B
evidence, provenance, result, and audit status all remain identical. The
following existing downstream mirror locations also remain byte-identical:

- `configs/evaluation/e1-feasibility-study.v1.json`
- `src/manufacturing_vision_studio/e1/study_protocol_v2.py`
- `tests/test_e1_feasibility_protocol_v2.py`
- `tests/test_e1_study_retention_v2.py`

The later Task 7 implementation-validation flow, which this design still stops
before executing, is responsible for binding a future study packet to the new
feasibility-study projection. No configuration hash, selection hash, projection
membership, or downstream mirror changes in this repair.

## Test strategy

### Scanner RED/GREEN tests

Tests use the real source-flow analyzer and existing synthetic-repository or
`_analyze_source` helpers.

1. `1 is True` followed by a short-circuited carrier replacement must leave
   the real `sys` carrier reachable and reject `.modules` as `import-registry`.
2. Positive controls for `None is None` and `None is not None` must preserve
   the correct reachable branch without inventing a protected capability.
3. `0 > 1 < (carrier := carrier.stdout)` must retain the false path and reject
   the later `.modules` access.
4. An unreachable later comparator containing a prohibited operation remains
   policy-inspected, but a named-expression write in that comparator does not
   alter reachable state.
5. Direct, assignment-aliased, import-aliased, and literal-`getattr` protected
   scope access are rejected.
6. Computed `getattr` on `EvaluationScope` fails closed.
7. An acquired `plan_cases` callable invoked through an alias is rejected both
   outside and inside the provider class.
8. The exact existing direct development-provider call remains accepted.

Every regression test must be observed failing for its intended reason before
production code changes.

### Verification RED/GREEN tests

The existing `_publish_semantic_packet` helper creates the real 14-path packet.
The test writes the canonical report for the valid decision, corrupts
`known-transform-development-120.json`, then asserts:

- `study_valid is False`;
- terminal decision is `STUDY_INVALID`;
- the malformed upstream, `decision.json`, and `report.md` are invalid;
- none of those paths receives verification credit;
- the report exposes 11 verified paths and rate `11 / 14`.

Existing valid `STUDY_INVALID` projection tests remain the positive control.

### Identity-preservation tests

Post-repair checks must prove:

- the checked selection raw SHA remains
  `32868450a349379e8e548854217c69035b7972ab75acc7f02295e5fae8a76242`;
- its record and projection hashes remain
  `7392d4d1d9078b44dac0c9dc777d7622f1f145c2e3b6bf9fffb9a58be407ae5a`
  and `7ccc656be191d0216480da4ad6536d4f50995a446a45f6810b1133a64583cbfa`;
- the four downstream mirror files are byte-identical to `c689309...`;
- the pure loader still returns `HOLD`/`null`/`UNVERIFIED`;
- Candidate A/B raw hashes and embedded envelopes are byte-identical;
- original snapshot/raw/record identities and comparison inputs are identical;
- the feasibility configuration and protocol documents remain byte-identical;
- a newly computed feasibility-study projection contains the changed source
  hashes without writing an implementation-validation or result artifact.

## Integrated validation and review

After all three repair domains and their per-task reviews approve:

1. run the exact Task 7 ten-module suite from the beginning;
2. run `make validate` from the beginning;
3. run `git diff --check` and prove the repair worktree clean;
4. prove both result roots and ignored Candidate A remain absent;
5. verify the protected anchors:
   - v0.1.0 bundle:
     `1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7`;
   - E1-mini:
     `f026d1fccb34711b82bcda30eab399558c418f9e3ca33f1c754ed8117d624764`;
   - E1-full:
     `557ea17abe655f82e5974ab7121de4ed905755ee4f1ff02976a0ed62a01f964c`;
   - HOLD packet:
     `91d3c3dbb3241fd7c5b3d697f08ee9b239ff347e8cebb1e3aa6b6a842d4dc62d`;
6. prove the original dirty, prior repair, QA, and preserved-run worktrees retain
   their pinned HEAD/status/hash evidence;
7. run four fresh whole-branch reviews from
   `8e4b3ff52461c907c728fb2eae6660dafba7c53a` through the new HEAD in these
   domains:
   - artifact state, one-run behavior, invalidity propagation, recovery;
   - truth boundary, protected reachability, declared-source capabilities,
     PEP 562;
   - evidence identity, paths, hashes, schemas, gates, denominators;
   - CLI, Make, tests, configuration integration, operator semantics,
     regressions.

All four reviews must approve with zero unresolved P0, P1, or P2 findings.

## Stop conditions

Stop without Push, PR, QA work, or an approval claim if any of the following is
true:

1. Any protected worktree or preserved evidence fingerprint changes.
2. A RED test does not fail for the reviewed behavior.
3. A fix requires general execution of projected source or unbounded analysis.
4. Execution reaches Candidate Selection repair, candidate comparison, search,
   inference, benchmark, implementation validation, or a study phase.
5. Any Candidate Selection or downstream mirror byte changes from `c689309...`.
6. Either selection or feasibility-study projection membership/order changes.
7. Candidate A/B, original execution evidence, result, thresholds, seeds, gates,
   or `HOLD`/`null`/`UNVERIFIED` meaning changes.
8. A result root or ignored raw candidate appears.
9. Any focused test, static gate, integrated validation, protected hash check,
   or whole-branch review fails after its allowed repair loop.
10. An operation requires destructive cleanup, remote mutation, or broader
    authority than this design grants.

## Commit boundaries

1. Design documentation.
2. Implementation-plan documentation.
3. Scanner comparison-semantics repair with its RED/GREEN tests.
4. Scanner protected-identity and callable-provenance repair with its
   RED/GREEN tests.
5. Malformed-upstream evidence-credit repair with its RED/GREEN tests.
6. Integrated identity-preservation evidence only; no identity commit is
   created unless a tracked documentation correction is independently required.

No Push or PR is authorized. The `c689309...` checkpoint and its worktree remain
preserved after this branch is complete.
