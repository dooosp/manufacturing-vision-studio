# E1 Whole-Branch Review Blocker Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` to execute this plan task by task.

**Goal:** Close the four whole-branch review blockers without changing checked
Candidate Selection evidence, fixed E1 results, or any evaluation behavior.

**Architecture:** Keep the source-flow fixes inside the existing finite
abstract interpreter, preserving exact resolved identity only for the two
policy-sensitive cases. Route malformed declared-JSON packets through the
existing invalid-terminal verifier. Treat Candidate Selection and its four
downstream mirrors as immutable inputs, not repair outputs.

**Tech Stack:** Python 3.12, `ast`, immutable dataclasses, pytest, Ruff, Mypy,
uv, Make, npm/Vite, Playwright, Git worktrees.

**Spec:**
`docs/superpowers/specs/2026-08-22-e1-review-blocker-repair-design.md`

## Global constraints

- Work only in
  `/Users/jangtaeho/manufacturing-vision-studio-e1-review-blocker-repair` on
  `codex/e1-review-blocker-repair`.
- The implementation base is exactly
  `c68930986ebc88f08d501d6204ee5727f7abcee9` plus the two documentation-only
  commits created by this plan.
- Never touch the user's dirty file in
  `/Users/jangtaeho/manufacturing-vision-studio-e1-dataflow-redesign`.
- Preserve edits by other workers. Tasks 1 and 2 intentionally share source
  and test files and therefore run sequentially, never concurrently.
- Follow RED/GREEN: add the narrow regression test, run it and observe the
  intended failure, make the minimum production change, then rerun focused and
  adjacent tests.
- Do not weaken a scanner rule, trust check, test, threshold, seed, schema,
  projection membership, or phase gate.
- Do not call Candidate Selection repair, candidate comparison, search,
  inference, benchmark, implementation validation, feature oracle,
  finalization, verification, or any study phase.
- Do not create or copy `data/e1-v2-development/candidate-a.json`,
  `data/e1-feasibility-study`, or
  `docs/evaluation/results/e1-feasibility-study`.
- Do not edit the Candidate Selection or any of its four downstream mirror
  files. Do not Push or open a PR.
- Each implementation task gets a fresh implementer, a clean commit, and a
  task-scoped review of that commit. A review finding is repaired by the same
  implementer, committed, and re-reviewed before the next task begins.

## Pre-implementation evidence

- [ ] Record repo root, branch, HEAD, default branch, worktree list, status,
      build/test commands, and the user-dirty worktree status/diff/blob/raw
      hashes in the ignored SDD ledger.
- [ ] Record the design-approval ruling: the user's in-chat approval covers the
      equivalent tracked design; the recoverable cost of a wrong ruling is
      documentation/implementation rework.
- [ ] Record the worktree ruling: the user's explicit request for a new sibling
      repair cycle overrides reuse of the earlier clean repair worktree.
- [ ] Record the identity ruling: the changed production files are outside the
      selection's fixed 47-path projection, so no selection rebind is allowed.
- [ ] Run and record the clean-base focused baseline:

```bash
uv run pytest \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_dependency_guard_v2.py -q
```

Expected: PASS at the plan-pinned base before new regression tests.

---

### Task 1: Preserve Python comparison semantics and short-circuit state

**Files:**

- Modify:
  `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Test:
  `tests/test_e1_study_dependency_guard_v2.py`

- [ ] **Step 1: Add narrow RED tests for pairwise comparison truth.**

Add internal analyzer cases proving:

```text
None is None       -> TRUE
None is not None   -> FALSE
1 == 1             -> TRUE
1 is 1             -> UNKNOWN
```

Include a public scanner regression where `1 is True` must not prune the real
`sys` carrier before a later `.modules` access.

- [ ] **Step 2: Add RED tests for chained-comparison transfer.**

Cover all of these behaviors:

- `0 > 1 < (carrier := carrier.stdout)` does not commit the unreachable write;
- a definitely false prefix does not execute a later state-mutating arm;
- a definitely true prefix reaches the arm and its sensitive state is visible;
- unreachable later syntax is still policy-inspected even though its state
  writes and runtime edges do not enter the reachable state.

- [ ] **Step 3: Run only the new selectors and prove RED.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'comparison or compare or chained or short_circuit' -vv
```

Record the exact failing assertions. A syntax error, fixture error, or failure
unrelated to the reviewed behavior is not an acceptable RED.

- [ ] **Step 4: Implement singleton-safe pair truth.**

Keep the implementation finite and local to compare transfer:

- `Eq`/`NotEq` may fold literal equality;
- `Is`/`IsNot` may fold only literal `None`, `True`, `False`, or `Ellipsis`;
- equal non-singleton literals remain `UNKNOWN`;
- preserve the existing exact `sys` versus complete non-`sys` mismatch rule;
- unsupported operations remain `UNKNOWN`.

- [ ] **Step 5: Implement sequential chained transfer.**

Evaluate the left operand once. For each pair, retain falsy exits and advance
only the truthy continuation. When the continuation is dead, scan the remaining
comparator syntax with the existing unreachable context and retain policy facts
and deferred inspection without reachable state writes or runtime edges.

- [ ] **Step 6: Prove GREEN and adjacent scanner stability.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'comparison or compare or chained or short_circuit' -vv
uv run pytest tests/test_e1_study_dependency_guard_v2.py -q
uv run ruff check \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
uv run mypy src/manufacturing_vision_studio/e1/study_retention_v2.py
git diff --check
```

- [ ] **Step 7: Self-review, commit, and task review.**

Stage only the two owned paths and commit:

```bash
git add \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
git commit -m "fix(e1): preserve Python comparison flow semantics"
```

Obtain the task-scoped review against the pre-task SHA. Repair and re-review
any validated finding before Task 2.

---

### Task 2: Preserve protected identity and `plan_cases` provenance

**Files:**

- Modify:
  `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Test:
  `tests/test_e1_study_dependency_guard_v2.py`

- [ ] **Step 1: Add protected-scope RED tests.**

Require rejection for:

- ordinary assignment alias of the exact imported `EvaluationScope`;
- `from ...domain_v2 import EvaluationScope as Scope`;
- literal `getattr(Scope, "CALIBRATION")`;
- computed `getattr(Scope, name)` when a protected member cannot be excluded.

Keep the existing direct protected-member rejection as a positive policy
control.

- [ ] **Step 2: Add `plan_cases` alias RED tests.**

Acquire `generator.plan_cases` into an ordinary alias and call it both outside
and inside `DevelopmentCorpusProvider`. Both calls must be rejected. Keep the
existing exact direct provider expression and legacy-v1 expression accepted.

- [ ] **Step 3: Run only the new selectors and prove RED.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'protected_scope or evaluation_scope or plan_cases' -vv
```

Each new case must fail at the intended provenance gap.

- [ ] **Step 4: Extend protected-member recognition narrowly.**

Reuse the current finite `_ResolvedIdentity` carried by exact imports. Detect
protected attribute access through either the legacy literal spelling or the
exact imported `EvaluationScope` identity. Apply the same rule to literal
`getattr`; fail closed for a computed member on that exact receiver. Do not add
generic heap, reflection, or arbitrary attribute provenance.

- [ ] **Step 5: Preserve acquired `plan_cases` identity narrowly.**

Tag `.plan_cases` acquisition with a dedicated finite resolved callable
identity. Reject calls based on that function-value identity as well as the
existing syntactic call name. Only the two existing exact AST allowlists may
authorize a call; being textually inside the provider class is insufficient.

- [ ] **Step 6: Prove GREEN and adjacent scanner stability.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'protected_scope or evaluation_scope or plan_cases' -vv
uv run pytest tests/test_e1_study_dependency_guard_v2.py -q
uv run ruff check \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
uv run mypy src/manufacturing_vision_studio/e1/study_retention_v2.py
git diff --check
```

- [ ] **Step 7: Self-review, commit, and task review.**

```bash
git add \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
git commit -m "fix(e1): preserve protected callable provenance"
```

Obtain the task-scoped review against the pre-task SHA. Repair and re-review
any validated finding before Task 3.

---

### Task 3: Invalidate stale derived evidence after malformed upstream JSON

**Files:**

- Modify:
  `src/manufacturing_vision_studio/e1/study_runner_v2.py`
- Test:
  `tests/test_e1_study_runner_v2.py`

- [ ] **Step 1: Add the exact 14-path RED regression.**

Use `_publish_semantic_packet`, materialize the canonical valid report, corrupt
`known-transform-development-120.json`, and assert:

```text
study_valid == False
terminal_decision == STUDY_INVALID
reasons == (ARTIFACT_VERIFICATION_FAILED,)
invalid == malformed upstream + decision.json + report.md
present count == 14
verified count == 11
verify rate == 11 / 14
```

Also assert the stale decision and report receive no verification credit.

- [ ] **Step 2: Run the regression and prove RED.**

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'malformed_upstream or stale_derived' -vv
```

Expected pre-fix evidence is stale credit for 13/14 paths.

- [ ] **Step 3: Route only malformed declared JSON through the existing helper.**

In `_inspect_open_store`, build the existing invalid state for `invalid_json`,
then pass it to `_verify_invalid_terminal_projection(protocol, store, invalid,
present_set)`. Do not change the separate `inventory_invalid` early return or
duplicate terminal-projection logic.

- [ ] **Step 4: Prove GREEN and honest-invalid preservation.**

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'malformed_upstream or stale_derived or does_not_credit_report or semantically_invalid_packet' -vv
uv run pytest tests/test_e1_study_runner_v2.py -q
uv run ruff check \
  src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
uv run mypy src/manufacturing_vision_studio/e1/study_runner_v2.py
git diff --check
```

- [ ] **Step 5: Self-review, commit, and task review.**

```bash
git add \
  src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
git commit -m "fix(e1): invalidate stale derived study evidence"
```

Obtain the task-scoped review against the pre-task SHA. Repair and re-review
any validated finding before integrated validation.

---

### Task 4: Prove identity preservation and restart integrated gates

**Files:** No tracked edits expected.

- [ ] **Step 1: Prove Candidate Selection and mirrors are byte-identical.**

```bash
git diff --exit-code c68930986ebc88f08d501d6204ee5727f7abcee9 -- \
  configs/evaluation/e1-v2-candidate-selection.json \
  configs/evaluation/e1-feasibility-study.v1.json \
  src/manufacturing_vision_studio/e1/study_protocol_v2.py \
  tests/test_e1_feasibility_protocol_v2.py \
  tests/test_e1_study_retention_v2.py
```

Recompute and record selection raw/record/projection hashes, load it through the
pure loader, and require `HOLD` / `None` / `UNVERIFIED`. Confirm Candidate A/B
and original execution identities remain exact. Compute the new
feasibility-study projection read-only and prove the two changed production
source hashes are represented without writing any result artifact.

- [ ] **Step 2: Run the exact Task 7 ten-module suite from the beginning.**

```bash
uv run pytest \
  tests/test_e1_feasibility_protocol_v2.py \
  tests/test_e1_known_transform_v2.py \
  tests/test_e1_study_inference_v2.py \
  tests/test_e1_study_parity_v2.py \
  tests/test_e1_study_truth_v2.py \
  tests/test_e1_study_artifacts_v2.py \
  tests/test_e1_study_retention_v2.py \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_cli_v2.py \
  tests/test_e1_study_dependency_guard_v2.py -q
```

- [ ] **Step 3: Run full validation from the beginning.**

```bash
make validate
```

Record Ruff, Mypy, complete Pytest, web build/check, and Playwright evidence.

- [ ] **Step 4: Prove the repair worktree is clean after validation.**

Run `git diff --check`, require no tracked or untracked validation side effect,
and require the repair worktree clean at the validated implementation HEAD.

- [ ] **Step 5: Repeat identity checks and prove every protected
      fingerprint.**

Repeat Step 1 after both integrated gates so a side effect cannot escape the
identity gate. Then require these exact SHA-256 values:

```text
docs/releases/v0.1.0/evidence-bundle.zip
  1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7
docs/evaluation/results/e1-mini-v0.2.0-hold.json
  f026d1fccb34711b82bcda30eab399558c418f9e3ca33f1c754ed8117d624764
docs/evaluation/results/e1-full-v0.2.0-hold.json
  557ea17abe655f82e5974ab7121de4ed905755ee4f1ff02976a0ed62a01f964c
docs/releases/v0.2.0/E1_HOLD.md
  91d3c3dbb3241fd7c5b3d697f08ee9b239ff347e8cebb1e3aa6b6a842d4dc62d
```

Require all three prohibited paths from Global constraints to remain absent
after validation. Then re-prove the original dirty worktree's exact
HEAD/status/diff/blob/raw fingerprints. Re-prove the prior repair, parked QA,
and preserved-run sibling against every HEAD/status/tree/file fingerprint
recorded at preflight, including the preserved original selection and
Candidate A/B raw hashes. A clean-status hash is evidence but does not replace
the pinned content hashes.

---

### Task 5: Obtain four fresh whole-branch approvals

**Files:** No tracked edits expected unless a separately approved repair loop
is required.

- [ ] **Step 1: Review the exact range.**

Run four independent read-only reviews of
`8e4b3ff52461c907c728fb2eae6660dafba7c53a..HEAD`:

1. artifact state, one-run behavior, invalidity propagation, recovery;
2. truth boundary, protected reachability, declared-source capabilities,
   PEP 562;
3. evidence identity, paths, hashes, schemas, gates, denominators;
4. CLI, Make, tests, configuration integration, operator semantics,
   regressions.

- [ ] **Step 2: Apply the review gate.**

All four must return approval with zero unresolved P0/P1/P2 findings. If a
finding is valid, stop the gate, create one focused RED/GREEN repair wave,
repeat relevant task review, then restart Task 4 and all four reviews from the
beginning. Do not make speculative fixes.

- [ ] **Step 3: Final completion check.**

Use `superpowers:verification-before-completion` and
`superpowers:finishing-a-development-branch`. Report the clean final commit,
full validation counts, four review outcomes, protected evidence, and remaining
npm warning. Do not Push, open a PR, start QA work, or claim production/shop-
floor validation. Report whether the result is eligible to become the base of
a new QA task/worktree; QA may begin only when explicitly based on that
approved SHA.
