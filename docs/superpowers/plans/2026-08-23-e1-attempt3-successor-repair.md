# E1 Attempt 3 Successor Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans`, `superpowers:test-driven-development`, and
> `superpowers:verification-before-completion` to execute this plan one task at
> a time. **DO NOT EXECUTE THIS PLAN UNTIL THE USER GIVES A SEPARATE EXPLICIT
> IMPLEMENTATION AUTHORIZATION.**

**Goal:** Close all eight Attempt 3 repository findings while preserving every
fixed E1 result, Candidate Selection meaning, historical artifact, and study
authorization boundary.

**Architecture:** Harden three runner trust boundaries in place, then repair
four finite-abstract-interpreter boundaries without adding an unbounded object
model, then update only the full-pytest validation deadline and its closed
schema/semantic contract. Each task is a separate RED/GREEN commit and exact-
range review. Integrated evidence and all four final reviews restart on every
HEAD change.

**Tech Stack:** Python 3.12, `ast`, immutable dataclasses, JSON Schema, pytest,
Ruff, Mypy, uv, Make, npm/Vite, Playwright, Git worktrees.

**Spec:**
`docs/superpowers/specs/2026-08-23-e1-attempt3-successor-repair-design.md`

**Matrix:**
`docs/superpowers/plans/2026-08-23-e1-attempt3-finding-to-test-matrix.md`

**Review contract:**
`docs/superpowers/plans/2026-08-23-e1-attempt3-review-contract.md`

## Authorization gate

The user has authorized only the four-document package. Until a later message
explicitly authorizes implementation:

- do not modify production source, tests, schemas, fixtures, or artifacts;
- do not stage or commit any non-document path;
- do not execute candidate comparison, search, inference, evaluation, or any
  study implementation-validation/oracle/finalization/phase command; ordinary
  read-only inspection and focused repository tests remain permitted;
- do not create QA work, Push, or open a PR.

Documentation review approval is a prerequisite for requesting implementation
authority; it is not itself that authority.

## Global implementation constraints

If implementation is later approved:

- Work only in
  `/Users/jangtaeho/manufacturing-vision-studio-e1-attempt3-successor-repair`
  on `codex/e1-attempt3-successor-repair`.
- Pin the reviewed four-document commit as `DOC_HEAD`. Start only if HEAD is
  exactly `DOC_HEAD` and the worktree is clean.
- Treat `ecec6e128ff560ab0e7b8ec403dca861ce0965ee` as an immutable
  `REVIEW_REJECTED_CHECKPOINT`; never amend, reset, replace, or relabel it.
- Preserve user and other-agent edits. Never touch the dirty Candidate
  Selection worktree or copy its file.
- Execute tasks strictly `R1 -> R2 -> R3 -> S1 -> S2 -> S3 -> S4 -> I1`.
  Shared files make parallel implementation unsafe.
- Every task follows RED first, minimal GREEN, adjacent controls, clean commit,
  and exact pre-task-SHA review.
- Each task gets one initial implementation. A validated task-review finding
  permits one focused repair maximum, then one fresh review.
- Never weaken a test, scanner rule, trust check, schema closure, threshold,
  seed, protocol, gate, decision meaning, or phase authorization.
- Never create or modify `data/e1-v2-development/candidate-a.json`,
  `data/e1-feasibility-study`, or
  `docs/evaluation/results/e1-feasibility-study`.
- Never run a study CLI or write a result-root artifact during repair or
  verification.
- Do not Push, open a PR, or start QA.

## Task 0: Re-prove authority, identity, and clean baseline

**Files:** No tracked edits.

### Step 1: Record exact authorization and repository identity

Record in an ignored local ledger:

```bash
pwd -P
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git rev-parse HEAD^{tree}
git status --short --branch
git remote show origin
git worktree list --porcelain
```

Require the successor root/branch, exact reviewed `DOC_HEAD`, clean status, and
default branch discovered from real Git state. Record these supported commands:

```text
uv sync --all-groups
uv run ruff check .
uv run mypy src
uv run pytest
npm --prefix web install
npm --prefix web run check
npm --prefix web run test:e2e
make validate
```

Do not infer the default branch or reuse a prior preflight record.

### Step 2: Re-prove sibling preservation

Record HEAD, tree, status hash, and relevant file/diff hashes for every sibling
listed in the design. The original dirty worktree must still be `3ced81c` with:

```text
git status --porcelain=v1 --untracked-files=all | shasum -a 256
80ce51d494c8a145d99ec671b778af0248f4ea512f4761e853e76c6737c1182c

git diff | shasum -a 256
d1395bf9d4036547fd5a2ae26788a8fc27fa74eb81b4803868e457a7183d50c8

git diff --binary --full-index | shasum -a 256
37d09fc9970a9426be57d01ea714a3a5f74af6de6ac46b2ebef81187b3efd3c0

git hash-object configs/evaluation/e1-v2-candidate-selection.json
fd85188fa27e9a9e8b9ca40be1ee88f43eb1b4e7
```

Run those commands from the original dirty worktree; the two diff digests are
deliberately different representations of the same one-file change. If any
protected sibling differs under the same recorded command, stop before
implementation and report the drift. Do not repair the sibling.

### Step 3: Recompute frozen identity

Recompute, do not transcribe, the Selection raw/record/projection hashes,
loader semantics, Candidate A/B hashes, historical identities and counts, four
protected artifact hashes, feasibility config, and 47-path projection
membership/order. Require all frozen values in the design.

Record the base feasibility fingerprints for comparison:

```text
aggregate
b426178abe769390fde21689ca0df311b8ac28a291665cb4c74a9d828f61fe2f

artifact schema
f74717cd9b44f3ef66cb965b394b38fe7ff19da3204da36fd1a2c6ce14fae171

study_retention_v2.py
20349aed863c7095f43b3a99d8ecc523f070f47ac3620e29004edb38eebaf0d1

study_runner_v2.py
baf4ce83848920d6fbf23777e13d0d50405bffe15e0f9fff29b584f9c18bc377
```

### Step 4: Run the focused clean baseline

```bash
uv run pytest -q \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
```

Require PASS at `DOC_HEAD` before adding regressions. This is ordinary test
execution, not study execution. If it fails unexpectedly, diagnose but do not
implement any planned repair until the baseline discrepancy is resolved and
reviewed.

### Step 5: Pin implementation start

Record `IMPLEMENTATION_START_SHA=DOC_HEAD`, exact tree, clean status hash, and
`git diff --check`. Every following task records its own `PRE_SHA` before any
edit.

## Task R1: Deny complement credit without a current anchor

**Finding:** `A3-REPO-P1-01`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_runner_v2.py`
- Test: `tests/test_e1_study_runner_v2.py`

### Step 1: Pin `R1_PRE_SHA` and prove allowed diff

Require clean status and no diff from `DOC_HEAD` outside the documents. Record
`R1_PRE_SHA=$(git rev-parse HEAD)`.

### Step 2: Add the parameterized RED

Add
`test_verify_zeroes_credit_for_nonempty_early_invalid_packet_without_validation_anchor`
with inventory-invalid and malformed-validation-anchor cases exactly as
specified in the matrix. Make callbacks and publication forbidden so the test
also proves read-only behavior.

### Step 3: Prove RED for the public defect

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'zeroes_credit_for_nonempty_early_invalid_packet_without_validation_anchor' -vv
```

Accept RED only when a retained present path incorrectly appears verified and
the rate is nonzero. A fixture, import, syntax, or unrelated assertion failure
is not RED evidence.

### Step 4: Implement the minimum boundary repair

In `StudyRunner._public_state`:

- return pristine pending unchanged only when the anchor is absent and the
  present-path set is empty;
- when the anchor is absent and the packet is nonempty, return an invalid state
  with all present paths invalid while preserving the existing reason;
- use `ARTIFACT_VERIFICATION_FAILED` only as a defensive unreachable fallback;
- leave every anchored packet on the existing deep-verification path.

Do not modify `VerifiedStudyState.verified_paths`.

### Step 5: Prove GREEN and adjacent behavior

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'zeroes_credit_for_nonempty_early_invalid or absent_root or deeply_rejects_validation_anchored or seals_semantically_invalid' -vv
uv run pytest tests/test_e1_study_runner_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
uv run mypy src
git diff --check
```

### Step 6: Commit and task-review exact range

```bash
git add src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
git commit -m "fix(e1): deny unanchored study verification credit"
```

Pin `R1_HEAD`. Obtain an independent read-only review of
`R1_PRE_SHA..R1_HEAD` under the common contract and Appendix A. If approved,
mark R1 `REVIEWED`. If not, apply at most one focused in-scope repair, commit,
and restart the exact-range review from `R1_PRE_SHA` to the new head.

## Task R2: Verify unauthorized-Phase-2 terminal evidence

**Finding:** `A3-REPO-P2-01`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_runner_v2.py`
- Test: `tests/test_e1_study_runner_v2.py`

### Step 1: Pin clean `R2_PRE_SHA`

Require R1 `REVIEWED`, clean status, and no out-of-scope path. Record HEAD.

### Step 2: Add negative and honest-positive fixtures

Extend the test-only semantic-packet helper with `oracle_passed: bool = True`.
Add:

- `test_unauthorized_phase2_rejects_mismatched_invalid_terminal_projection`;
- `test_unauthorized_phase2_accepts_honestly_sealed_invalid_terminal_projection`.

Build the negative decision/report against a forged invalid state, not malformed
JSON, so the test isolates state-specific projection verification.

### Step 3: Prove the negative RED and positive control

```bash
uv run pytest \
  tests/test_e1_study_runner_v2.py::test_unauthorized_phase2_rejects_mismatched_invalid_terminal_projection \
  tests/test_e1_study_runner_v2.py::test_unauthorized_phase2_accepts_honestly_sealed_invalid_terminal_projection \
  -vv
```

The negative pair must currently appear in `verified_paths`; the honest pair
must pass before and after.

### Step 4: Implement the minimum branch repair

In the unauthorized-Phase-2 branch, construct the existing invalid state and
pass it through `_verify_invalid_terminal_projection`. Do not change the actual
reason, Phase-2 invalid paths, terminal grammar, or authorization.

### Step 5: Prove GREEN and adjacent invalid projection behavior

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'unauthorized_phase2 or invalid_terminal_projection or malformed_upstream' -vv
uv run pytest tests/test_e1_study_runner_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
uv run mypy src
git diff --check
```

### Step 6: Commit and review

```bash
git add src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
git commit -m "fix(e1): verify unauthorized phase2 terminal evidence"
```

Review `R2_PRE_SHA..R2_HEAD` under Appendix A. Apply the same one-focused-repair
maximum and stop rule.

## Task R3: Reject a present corrupt report

**Finding:** `A3-REPO-P1-02`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_runner_v2.py`
- Test: `tests/test_e1_study_runner_v2.py`

### Step 1: Pin clean `R3_PRE_SHA`

Require R2 `REVIEWED` and record exact HEAD/tree/status.

### Step 2: Add corrupt and absent-report tests

Add:

- `test_finalize_rejects_present_corrupt_report_without_overwriting_projection`;
- `test_finalize_repairs_absent_report_for_existing_verified_decision` if an
  equally explicit positive control is not already present.

Capture both terminal byte strings. Forbid `publish_bytes` in the corrupt case.

### Step 3: Prove RED

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'finalize and (present_corrupt_report or absent_report)' -vv
```

The corrupt test must fail because `finalize()` returns success, not because
deep trust was omitted or the fixture is invalid.

### Step 4: Implement the three-state terminal rule

After `_require_finalization_evidence(state)` and before returning an existing
projection, raise `StudyStateError("existing terminal report is invalid")` when
`report.md` is both present and invalid. Do not overwrite it. Keep absent
recovery and exact idempotence.

### Step 5: Prove GREEN and the full runner module

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'finalize or deterministic_report or semantically_invalid' -vv
uv run pytest tests/test_e1_study_runner_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
uv run mypy src
git diff --check
```

### Step 6: Commit and review

```bash
git add src/manufacturing_vision_studio/e1/study_runner_v2.py \
  tests/test_e1_study_runner_v2.py
git commit -m "fix(e1): reject corrupt terminal reports"
```

Review `R3_PRE_SHA..R3_HEAD` under Appendix A with the same repair budget.

## Task S1: Separate may-`sys` from exact `sys`

**Finding:** `A3-REPO-P1-03`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Test: `tests/test_e1_study_dependency_guard_v2.py`

### Step 1: Pin clean `S1_PRE_SHA`

Require all runner tasks `REVIEWED`. Record HEAD/tree/status and current
canonical complexity constants.

### Step 2: Add the internal and public REDs

Add the two named S1 tests from the matrix. Also pin pair-truth controls for
exact `sys`, definitely non-`sys`, may-`sys`, incomplete, and identity-top in
`test_exact_sys_identity_comparison_controls_remain_folded`.

### Step 3: Prove RED

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_identity_comparison_does_not_treat_may_sys_as_exact_sys \
  tests/test_e1_study_dependency_guard_v2.py::test_may_sys_identity_fold_cannot_hide_pep562_import_module_rebinding \
  -vv
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_sys_identity_comparison_controls_remain_folded \
  -vv
```

The public failure must demonstrate a reachable protected rebinding hidden by
an incorrect definite fold.

### Step 4: Implement exact-identity helpers

Add finite helpers equivalent to `_sys_module_identity()` and
`_has_exact_sys_module()`. Replace may-capability XOR folding with exact
imported-`sys` versus complete definitely-non-`sys` reasoning. Leave every
uncertain case unknown.

### Step 5: Prove GREEN and adjacent controls

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_identity_comparison_does_not_treat_may_sys_as_exact_sys \
  tests/test_e1_study_dependency_guard_v2.py::test_may_sys_identity_fold_cannot_hide_pep562_import_module_rebinding \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_sys_identity_comparison_controls_remain_folded \
  tests/test_e1_study_dependency_guard_v2.py::test_compare_pair_truth_preserves_python_singleton_semantics \
  tests/test_e1_study_dependency_guard_v2.py::test_compare_short_circuit_keeps_real_sys_carrier_visible_to_public_scanner \
  tests/test_e1_study_dependency_guard_v2.py::test_chained_compare_short_circuit_preserves_state_and_policy \
  tests/test_e1_study_dependency_guard_v2.py::test_real_pep562_initializers_preserve_complete_dependency_closure \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_initializer_rejects_import_module_rebinding \
  -vv
uv run pytest tests/test_e1_study_dependency_guard_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
uv run mypy src
git diff --check
```

### Step 6: Commit and review

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
git commit -m "fix(e1): require exact sys identity for folding"
```

Review `S1_PRE_SHA..S1_HEAD` under Appendix B with the same repair budget.

## Task S2: Isolate unreachable runtime effects

**Finding:** `A3-REPO-P1-04`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Test: `tests/test_e1_study_dependency_guard_v2.py`

### Step 1: Pin clean `S2_PRE_SHA`

Require S1 `REVIEWED` and record HEAD/tree/status.

### Step 2: Add five RED/control tests

Add all named S2 statement, expression, EvaluationScope, `plan_cases`, and
policy-fact cases. Explicitly assert dead writes and raises do not enter final
state while dead `eval` still rejects. Add
`test_live_if_statement_preserves_runtime_effects_and_raises` and
`test_unknown_if_condition_joins_both_runtime_effects` as exact positive
controls.

### Step 3: Prove RED for state leakage

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_statement_does_not_erase_evaluation_scope_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_expression_does_not_erase_evaluation_scope_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_statement_does_not_erase_plan_cases_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_expression_does_not_erase_plan_cases_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_branch_still_emits_policy_facts \
  -vv
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_live_if_statement_preserves_runtime_effects_and_raises \
  tests/test_e1_study_dependency_guard_v2.py::test_unknown_if_condition_joins_both_runtime_effects \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_expression_suffix_remains_policy_inspected \
  tests/test_e1_study_dependency_guard_v2.py::test_chained_compare_short_circuit_preserves_state_and_policy \
  tests/test_e1_study_dependency_guard_v2.py::test_type_checking_cycle_between_study_owned_modules_is_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_shadowed_type_checking_is_treated_as_runtime_code \
  -vv
```

### Step 4: Implement policy-only dead-arm projections

Create bounded expression and statement policy-only helpers. When an arm is
unreachable, merge only policy facts and still-required deferred inspection;
never place the complete dead `_ExprResult` or `_FlowResult` in reachable
branches.

### Step 5: Prove GREEN, liveness, and module stability

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_statement_does_not_erase_evaluation_scope_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_expression_does_not_erase_evaluation_scope_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_statement_does_not_erase_plan_cases_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_if_expression_does_not_erase_plan_cases_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_branch_still_emits_policy_facts \
  tests/test_e1_study_dependency_guard_v2.py::test_live_if_statement_preserves_runtime_effects_and_raises \
  tests/test_e1_study_dependency_guard_v2.py::test_unknown_if_condition_joins_both_runtime_effects \
  tests/test_e1_study_dependency_guard_v2.py::test_unreachable_expression_suffix_remains_policy_inspected \
  tests/test_e1_study_dependency_guard_v2.py::test_chained_compare_short_circuit_preserves_state_and_policy \
  tests/test_e1_study_dependency_guard_v2.py::test_type_checking_cycle_between_study_owned_modules_is_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_shadowed_type_checking_is_treated_as_runtime_code \
  -vv
uv run pytest tests/test_e1_study_dependency_guard_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
uv run mypy src
git diff --check
```

### Step 6: Commit and review

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
git commit -m "fix(e1): isolate unreachable scanner effects"
```

Review `S2_PRE_SHA..S2_HEAD` under Appendix B with the same repair budget.

## Task S3: Preserve finite protected provenance

**Finding:** `A3-REPO-P1-05`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Test: `tests/test_e1_study_dependency_guard_v2.py`

### Step 1: Pin clean `S3_PRE_SHA`

Require S2 `REVIEWED`. Record the exact capability dimension and canonical
height-bound test values before editing.

### Step 2: Add carrier, approval, and depth REDs

Add all list, dict, subscript, unknown-call, exact-approval, and depth cases in
the matrix. Add
`test_harmless_container_and_unknown_call_carriers_remain_allowed` for
`sys.stdout`, harmless list/dict values, and an unknown identity call. Keep the
real approved-plan, checkout, and independent complexity controls adjacent.

### Step 3: Prove RED and current finite controls

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_container_subscript_preserves_evaluation_scope_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unknown_call_return_preserves_evaluation_scope_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_container_subscript_preserves_plan_cases_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unknown_call_return_preserves_plan_cases_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_protected_carrier_never_qualifies_as_exact_approved_plan \
  tests/test_e1_study_dependency_guard_v2.py::test_protected_provenance_depth_obeys_canonical_complexity_bound \
  -vv
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_container_and_unknown_call_carriers_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_mandatory_safe_source_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_cases_sites_allow_harmless_line_shifts \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_calls_reject_same_location_clones \
  tests/test_e1_study_dependency_guard_v2.py::test_real_task_7_checkout_has_the_exact_reviewed_dependency_closure \
  tests/test_e1_study_dependency_guard_v2.py::test_analysis_stats_are_canonical_for_straight_line_dunder_chains \
  tests/test_e1_study_dependency_guard_v2.py::test_branch_state_join_uses_canonical_program_point_counters \
  tests/test_e1_study_dependency_guard_v2.py::test_retained_loop_point_growth_uses_canonical_update_counters \
  tests/test_e1_study_dependency_guard_v2.py::test_computed_height_uses_one_real_program_point_shape \
  -vv
```

### Step 4: Add exactly two may-capability bits

Add `evaluation-scope` and `plan-cases-callable`. Seed them from exact imports
and direct/literal planner acquisition, preserve them through existing
container flattening, and conservatively pass only these bits from unknown-call
arguments into an incomplete non-exact return. Require exact identity plus
exact call site for approved plan calls.

### Step 5: Prove mechanical bounds and GREEN

Update the independent helper formula in
`_assert_canonical_complexity_bounds` from the 15-capability coefficient to the
17-capability coefficient, and update the explicit expected-bound assertions
in the straight-line dunder, branch join, retained-loop, and one-real-program-
point tests. The only resulting expected values are 75, 149, and 879. Then run:

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_container_subscript_preserves_evaluation_scope_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unknown_call_return_preserves_evaluation_scope_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_container_subscript_preserves_plan_cases_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_unknown_call_return_preserves_plan_cases_may_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_protected_carrier_never_qualifies_as_exact_approved_plan \
  tests/test_e1_study_dependency_guard_v2.py::test_protected_provenance_depth_obeys_canonical_complexity_bound \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_container_and_unknown_call_carriers_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_mandatory_safe_source_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_cases_sites_allow_harmless_line_shifts \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_calls_reject_same_location_clones \
  tests/test_e1_study_dependency_guard_v2.py::test_real_task_7_checkout_has_the_exact_reviewed_dependency_closure \
  tests/test_e1_study_dependency_guard_v2.py::test_analysis_stats_are_canonical_for_straight_line_dunder_chains \
  tests/test_e1_study_dependency_guard_v2.py::test_branch_state_join_uses_canonical_program_point_counters \
  tests/test_e1_study_dependency_guard_v2.py::test_retained_loop_point_growth_uses_canonical_update_counters \
  tests/test_e1_study_dependency_guard_v2.py::test_computed_height_uses_one_real_program_point_shape \
  -vv
uv run pytest tests/test_e1_study_dependency_guard_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
uv run mypy src
git diff --check
```

### Step 6: Commit and review

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
git commit -m "fix(e1): retain protected carrier provenance"
```

Review `S3_PRE_SHA..S3_HEAD` under Appendix B. Reject any hidden expansion to a
heap graph, general call summary, or approval-by-may.

## Task S4: Centralize sensitive-member selection

**Finding:** `A3-REPO-P1-06`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Test: `tests/test_e1_study_dependency_guard_v2.py`

### Step 1: Pin clean `S4_PRE_SHA`

Require S3 `REVIEWED` and record HEAD/tree/status.

### Step 2: Add every required-negative family before production changes

Add the six named S4 families from the matrix. Parameterize all specified
owners, members, and direct/reflected/dunder/import-from forms so no form can be
silently omitted. The dynamic-loader family must include both
`pkgutil.get_loader` and `pkgutil.resolve_name` plus
`zipimport.zipimporter`. The operator family must include both
`operator.attrgetter` and `operator.methodcaller`. Add the symmetric positive
`test_sys_stdout_member_grammar_allows_all_selection_forms` and
`test_harmless_literal_dunder_member_selection_remains_allowed`.

### Step 3: Run RED plus required-positive controls

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_sys_registry_member_grammar_rejects_all_selection_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_dynamic_loader_member_grammar_rejects_direct_reflected_and_imported_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_operator_reflection_member_grammar_rejects_direct_reflected_and_imported_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_universal_reflection_member_grammar_rejects_direct_getattr_and_dunder_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_dunder_plan_cases_selection_retains_protected_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_nonliteral_dunder_member_selection_fails_closed \
  -vv
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_sys_stdout_member_grammar_allows_all_selection_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_literal_dunder_member_selection_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_mandatory_safe_source_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_real_pep562_initializers_preserve_complete_dependency_closure \
  tests/test_e1_study_dependency_guard_v2.py::test_pep562_initializer_requires_exact_capability_structure \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_initializer_rejects_import_module_rebinding \
  tests/test_e1_study_dependency_guard_v2.py::test_real_cli_namespace_reflection_bindings_are_rejected \
  tests/test_e1_study_dependency_guard_v2.py::test_cli_dataclass_exception_rejects_local_shadow_at_protected_call \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_builtins_attribute_acquisition_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_builtins_mapping_subscript_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_literal_mapping_get_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_builtins_origin_mapping_harmless_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_builtins_mapping_get_literal_default_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_package_object_attribute_access_is_rejected_fail_closed \
  tests/test_e1_study_dependency_guard_v2.py::test_runtime_package_object_import_is_rejected_at_source \
  tests/test_e1_study_dependency_guard_v2.py::test_explicit_real_submodule_import_uses_normal_closure \
  tests/test_e1_study_dependency_guard_v2.py::test_analysis_stats_are_canonical_for_straight_line_dunder_chains \
  tests/test_e1_study_dependency_guard_v2.py::test_structural_expression_families_obey_the_canonical_complexity_bound \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_cases_sites_allow_harmless_line_shifts \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_calls_reject_same_location_clones \
  tests/test_e1_study_dependency_guard_v2.py::test_real_task_7_checkout_has_the_exact_reviewed_dependency_closure \
  -vv
```

The first command must fail on the intended missing capabilities. The second
must remain green before implementation.

### Step 4: Implement one finite classifier

Implement the exact table in the design and route direct attribute, exact
builtin `getattr`, bound literal `__getattribute__`, and import-from selection
through it. Apply exact PEP 562 and CLI exemptions before the classifier. Fail
closed for nonliteral bound dunder names. Do not universally deny `__dict__`.

### Step 5: Prove GREEN and complete scanner module

```bash
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_sys_registry_member_grammar_rejects_all_selection_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_dynamic_loader_member_grammar_rejects_direct_reflected_and_imported_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_operator_reflection_member_grammar_rejects_direct_reflected_and_imported_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_universal_reflection_member_grammar_rejects_direct_getattr_and_dunder_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_dunder_plan_cases_selection_retains_protected_provenance \
  tests/test_e1_study_dependency_guard_v2.py::test_nonliteral_dunder_member_selection_fails_closed \
  -vv
uv run pytest \
  tests/test_e1_study_dependency_guard_v2.py::test_sys_stdout_member_grammar_allows_all_selection_forms \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_literal_dunder_member_selection_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_mandatory_safe_source_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_real_pep562_initializers_preserve_complete_dependency_closure \
  tests/test_e1_study_dependency_guard_v2.py::test_pep562_initializer_requires_exact_capability_structure \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_initializer_rejects_import_module_rebinding \
  tests/test_e1_study_dependency_guard_v2.py::test_real_cli_namespace_reflection_bindings_are_rejected \
  tests/test_e1_study_dependency_guard_v2.py::test_cli_dataclass_exception_rejects_local_shadow_at_protected_call \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_builtins_attribute_acquisition_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_builtins_mapping_subscript_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_harmless_literal_mapping_get_remains_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_builtins_origin_mapping_harmless_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_builtins_mapping_get_literal_default_controls_remain_allowed \
  tests/test_e1_study_dependency_guard_v2.py::test_package_object_attribute_access_is_rejected_fail_closed \
  tests/test_e1_study_dependency_guard_v2.py::test_runtime_package_object_import_is_rejected_at_source \
  tests/test_e1_study_dependency_guard_v2.py::test_explicit_real_submodule_import_uses_normal_closure \
  tests/test_e1_study_dependency_guard_v2.py::test_analysis_stats_are_canonical_for_straight_line_dunder_chains \
  tests/test_e1_study_dependency_guard_v2.py::test_structural_expression_families_obey_the_canonical_complexity_bound \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_cases_sites_allow_harmless_line_shifts \
  tests/test_e1_study_dependency_guard_v2.py::test_exact_approved_plan_calls_reject_same_location_clones \
  tests/test_e1_study_dependency_guard_v2.py::test_real_task_7_checkout_has_the_exact_reviewed_dependency_closure \
  -vv
uv run pytest tests/test_e1_study_dependency_guard_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
uv run mypy src
git diff --check
```

### Step 6: Commit and review

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py
git commit -m "fix(e1): unify sensitive member provenance"
```

Review `S4_PRE_SHA..S4_HEAD` under Appendix B with the same repair budget.

## Task I1: Make sealed full-pytest validation feasible

**Finding:** `A3-REPO-P1-07`

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Modify: `schemas/e1-feasibility-study-artifact.v1.json`
- Test: `tests/test_e1_study_runner_v2.py`
- Test: `tests/test_e1_study_retention_v2.py`
- Test: `tests/test_e1_study_artifacts_v2.py`
- Read only: `src/manufacturing_vision_studio/e1/study_runner_v2.py`
- Read only: `src/manufacturing_vision_studio/e1/study_cli_v2.py`
- Read only: `Makefile`

### Step 1: Pin clean `I1_PRE_SHA` and command identity

Require S4 `REVIEWED`. Record the exact six command names, argv, order,
timeouts, cwd, environment, output caps, snapshot checks, `shell=False`, and
process-group kill code. Reconfirm the historical 5,553.14-second measurement.

### Step 2: Add independent literal REDs

Do not import the production timeout tuple as the test oracle. Add:

```python
assert tuple(request.timeout_seconds for request in requests) == (
    300,
    300,
    600,
    7200,
    600,
    900,
)
```

Add schema and semantic tests for current ordinal-3 7,200, legacy structural
1,800, wrong-ordinal 7,200, and non-enum 7,199/7,201.

### Step 3: Prove RED for the exact intended reasons

```bash
uv run pytest \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_retention_v2.py \
  tests/test_e1_study_artifacts_v2.py \
  -k 'timeout or validation_request or implementation_validation' -vv
```

Accept RED only for ordinal 3's `1800 != 7200` and the current schema/semantic
expectations. Do not create a test that sleeps for either deadline.

### Step 4: Change the tuple and closed enum only

- Change exactly tuple ordinal 3 from 1,800 to 7,200.
- Add 7,200 to the v1 closed enum while retaining 1,800 for historical
  structural compatibility.
- Keep the semantic verifier pinned to the exact current tuple, making legacy
  1,800 non-current.
- Do not edit runner production code, schema version, command order, or any
  execution safeguard.

### Step 5: Prove GREEN and adjacent compatibility

```bash
uv run pytest \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_retention_v2.py \
  tests/test_e1_study_artifacts_v2.py \
  -k 'timeout or validation_request or implementation_validation' -vv
uv run pytest \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_retention_v2.py \
  tests/test_e1_study_artifacts_v2.py -q
uv run ruff check \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_retention_v2.py \
  tests/test_e1_study_artifacts_v2.py
uv run mypy src
git diff --check
```

Recompute projection read-only. Require exactly two production/schema member
hash changes from I1, unchanged runner member hash for this task, and unchanged
47-path membership/order.

### Step 6: Commit and review

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py \
  schemas/e1-feasibility-study-artifact.v1.json \
  tests/test_e1_study_runner_v2.py \
  tests/test_e1_study_retention_v2.py \
  tests/test_e1_study_artifacts_v2.py
git commit -m "fix(e1): extend sealed pytest deadline"
```

Review `I1_PRE_SHA..I1_HEAD` under Appendices C and D. Apply the same
one-focused-repair maximum.

## Task 9: Restart integrated validation and identity evidence

**Files:** No tracked edits expected.

### Step 1: Require all task reviews and a clean implementation HEAD

All eight rows must be `REVIEWED`. Pin `FINAL_CANDIDATE_SHA`, tree, clean status
hash, and `git diff --check`. Confirm the successor-only range
`ecec6e128ff560ab0e7b8ec403dca861ce0965ee..FINAL_CANDIDATE_SHA` contains only
the four documentation paths and the union of task allowlists. Do not apply
that narrow path assertion to the required whole-branch review range
`8e4b3ff52461c907c728fb2eae6660dafba7c53a..FINAL_HEAD`.

### Step 2: Run PRE-validation identity audit

Recompute every frozen identity and sibling fingerprint from Task 0. Confirm
the only allowed byte changes are planned source/schema/tests and the
deterministic feasibility projection hash. Confirm all prohibited paths absent.

### Step 3: Run the exact ten-module suite from the beginning

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

Record fresh collection count and exit code. The `ecec6e1` precedent was 10
modules and 1,508 passing tests; the expected difference is only newly added
regressions. A partial or interrupted run is non-evidence.

### Step 4: Run full validation from the beginning

```bash
make validate
```

Record Ruff, Mypy source count, complete Pytest count/warnings/duration, web
typecheck/build, and Playwright count/duration. Do not run the sealed study
validation entrypoint; `make validate` is the repository's ordinary validation
command.

### Step 5: Run POST-validation identity and side-effect audit

Immediately re-pin HEAD/tree/status and repeat every PRE audit. Require:

- `git diff --check` PASS and clean status;
- exact Selection/A/B/history/protected hashes and semantics;
- exact feasibility membership/order of 47 paths;
- deterministic aggregate hash matching a fresh second read-only computation;
- all prohibited paths absent;
- every sibling fingerprint exact;
- no result root or generated study evidence.

Any HEAD change or side effect invalidates Steps 2-5 and requires a full
restart after an authorized repair.

## Task 10: Obtain four whole-branch approvals

**Files:** No tracked edits expected.

### Step 1: Pin `FINAL_HEAD` and build one package

Create the read-only package required by the review contract for exactly:

```text
8e4b3ff52461c907c728fb2eae6660dafba7c53a..FINAL_HEAD
```

Record its SHA-256. Never use `ecec6e1..FINAL_HEAD` as a substitute.

### Step 2: Dispatch four independent read-only reviews

Use the same common package and one appendix each:

1. Appendix A — artifact state;
2. Appendix B — truth boundary;
3. Appendix C — evidence identity;
4. Appendix D — integration and timeout.

Require the exact verdict format, correct package hash, correct range, and
before/after clean-state proof.

### Step 3: Deduplicate and apply the gate

Merge duplicates under the existing finding ID and retain the highest supported
severity. Approval requires four of four `APPROVE` and a deduplicated unresolved
total `P0=0/P1=0/P2=0`.

If any reviewer reports a valid finding:

- do not call the branch complete;
- do not retain any review or validation approval on a changed HEAD;
- apply a repair only if it belongs to an already authorized task and remains
  within that task's single-repair budget;
- otherwise stop for the user's A/B/C decision;
- after any authorized change, restart Task 9 and all four reviews.

### Step 4: Mark repository findings closed only at the approved SHA

Only after Step 3 may the eight matrix rows become `FINAL_CLOSED`. Record the
clean final commit, tree, validation counts, four verdicts, package hash,
protected identities, deterministic feasibility projection hash, and known
unrelated warning/advisory.

### Step 5: Request QA Stage 1 authorization

Do not reuse the parked QA worktree and do not claim `BASELINE_ACCEPTED`.
Report only that the approved `FINAL_HEAD` is eligible for a new QA worktree
and fresh read-only Stage 1 audit. Stage 1 may return
`BASELINE_ACCEPTED` or `BASELINE_HOLD`; QA Core still requires another explicit
user authorization.

## Mandatory stop response

If the task repair budget is exhausted, the same blocker persists, or a new
structural/out-of-scope P0/P1/P2 appears, preserve the clean evidence and ask
the user to choose exactly one direction:

```text
A. redesign a smaller Trusted Core
B. freeze E1 as HOLD and stop QA
C. reevaluate whether further investment is justified
```

Do not create an automatic Attempt 4/5, broaden the task allowlist, or make a
speculative fix while awaiting that choice.
