# E1 Attempt 3 Finding-to-Test Matrix

## Purpose

This is the authoritative closure ledger for the eight deduplicated Attempt 3
repository findings at base
`ecec6e128ff560ab0e7b8ec403dca861ce0965ee`. It defines future tests and task
boundaries; it does not authorize their implementation.

Repository status transitions are:

```text
OPEN -> RED_PROVEN -> GREEN -> REVIEWED -> FINAL_CLOSED
```

- `RED_PROVEN` requires a focused public regression that fails at the exact
  pre-task SHA for the stated reason.
- `GREEN` requires the focused test and mandatory controls to pass at the task
  HEAD.
- `REVIEWED` requires an independent exact-range task review with zero
  unresolved P0/P1/P2.
- `FINAL_CLOSED` is permitted only after the exact ten-module suite, a fresh
  full `make validate`, POST identity audit, and all four whole-branch reviews
  approve the same `FINAL_HEAD`.

No repository row is closed merely because this documentation package is
approved.

## Summary matrix

| ID | Sev. | Invariant | Minimal RED | Required GREEN | Future allowlist | Projection impact | Initial state |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `A3-REPO-P1-01` | P1 | Current anchor; no complement proof | Nonempty inventory-invalid or malformed-anchor packet credits retained Candidate A | Same reason, `STUDY_INVALID`, every present path invalid, zero verified paths/rate; empty root unchanged | runner source + runner tests | runner member changes; aggregate changes; 47 paths unchanged | `OPEN` |
| `A3-REPO-P1-02` | P1 | Terminal integrity | Existing valid decision plus corrupt present report makes `finalize()` return success | Raise without overwrite/publication; absent report repair and exact idempotence survive | runner source + runner tests | runner member changes; aggregate changes; 47 paths unchanged | `OPEN` |
| `A3-REPO-P2-01` | P2 | Terminal integrity | Unauthorized Phase 2 with state-mismatched invalid terminal pair credits decision/report | Pair becomes invalid; exact honestly sealed invalid pair remains creditable | runner source + runner tests | runner member changes; aggregate changes; 47 paths unchanged | `OPEN` |
| `A3-REPO-P1-03` | P1 | Exact versus may | may-`sys` identity comparison folds to definite and hides reachable rebinding | may/incomplete/top is unknown; exact mismatch controls unchanged | retention source + dependency-guard tests | retention member changes; aggregate changes; 47 paths unchanged | `OPEN` |
| `A3-REPO-P1-04` | P1 | Reachability separation | Dead `If`/`IfExp` replacement erases protected scope or planner provenance | Only policy facts/deferred inspection escape dead arm; live and unknown controls unchanged | retention source + dependency-guard tests | retention member changes; aggregate changes; 47 paths unchanged | `OPEN` |
| `A3-REPO-P1-05` | P1 | Exact/may provenance | List/dict/subscript or unknown call erases protected scope/planner provenance | Two finite may bits survive carriers and only reject; exact approvals unchanged | retention source + dependency-guard tests | retention member changes; aggregate changes; 47 paths unchanged | `OPEN` |
| `A3-REPO-P1-06` | P1 | Uniform selection grammar | Sensitive direct/reflected/dunder/import-from families disagree | One finite classifier covers all four selection forms; harmless and exact-role controls pass | retention source + dependency-guard tests | retention member changes; aggregate changes; 47 paths unchanged | `OPEN` |
| `A3-REPO-P1-07` | P1 | Finite feasible validation | Literal request tuple still uses 1,800 at ordinal 3; current 7,200 record fails | Only ordinal 3 is 7,200; closed additive schema; legacy 1,800 is schema-only | retention source + schema + runner/retention/artifact tests | retention/schema members and aggregate change; runner member stays exact; 47 paths unchanged | `OPEN` |

## R1 — `A3-REPO-P1-01`: unanchored credit

**Base root cause:** `VerifiedStudyState.verified_paths` computes
`present_paths - invalid_paths`; early inventory/parse failures mark only the
offending path; `_public_state()` returns before deep verification when parsed
implementation validation is absent.

**RED test:**
`test_verify_zeroes_credit_for_nonempty_early_invalid_packet_without_validation_anchor`
parameterized for:

1. retained Candidate A plus `unknown.tmp`; and
2. retained Candidate A plus malformed `implementation-validation.json`.

**Before:** public decision is invalid but Candidate A appears in
`verified_paths` and rate is nonzero.

**After:** preserve `ARTIFACT_INVENTORY_INVALID` or
`ARTIFACT_VERIFICATION_FAILED`; expose `STUDY_INVALID`, `verified_paths == ()`,
and rate 0.0; run no callbacks and mutate no files.

**Mandatory controls:**

- `test_status_on_absent_root_is_pristine_and_creates_nothing`;
- `test_verify_on_absent_root_is_read_only`;
- deep anchored invalid-terminal rejection;
- honestly sealed invalid finalization.

**Focused command:**

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'zeroes_credit_for_nonempty_early_invalid or absent_root or deeply_rejects_validation_anchored or seals_semantically_invalid' -vv
```

**Task review range:** `R1_PRE_SHA..R1_HEAD`.

**Frozen:** no change to `verified_paths` property, schema, inventory grammar,
decision meaning, empty-root semantics, or retained raw bytes.

## R2 — `A3-REPO-P2-01`: unauthorized Phase 2 terminal bypass

**Base root cause:** the unauthorized-Phase-2 branch returns an invalid state
before either state-specific terminal validation or
`_verify_invalid_terminal_projection`.

**RED tests:**

- `test_unauthorized_phase2_rejects_mismatched_invalid_terminal_projection`;
- `test_unauthorized_phase2_accepts_honestly_sealed_invalid_terminal_projection`
  as an always-green positive control.

The negative fixture uses a failed oracle and present Phase-2 artifacts, then
seals a generic-schema-valid pair against a forged invalid-path state.

**Before:** forged `decision.json` and `report.md` remain verified.

**After:** both paths become invalid while the actual unauthorized status,
reason, and Phase-2 invalid paths remain exact. The honest pair remains
verified only against the actual state.

**Focused command:**

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'unauthorized_phase2 and (terminal_projection or honestly_sealed)' -vv
```

**Task review range:** `R2_PRE_SHA..R2_HEAD`.

**Frozen:** no Phase-2 authorization, interpretation, execution, new grammar,
or generic invalid-path substitution.

## R3 — `A3-REPO-P1-02`: corrupt report finalization

**Base root cause:** `finalize()` validates an existing decision and repairs an
absent report, but does not reject a report that is present in both
`present_paths` and `invalid_paths`.

**RED tests:**

- `test_finalize_rejects_present_corrupt_report_without_overwriting_projection`;
- `test_finalize_repairs_absent_report_for_existing_verified_decision` as a
  positive recovery control.

**Before:** corrupt present bytes remain, yet a decision record is returned as
success.

**After:** deep trust runs, then `StudyStateError` is raised; decision/report
bytes remain exact and publication is not called. An absent report is still
published deterministically and an exact pair remains idempotent.

**Focused command:**

```bash
uv run pytest tests/test_e1_study_runner_v2.py \
  -k 'finalize and (corrupt_report or absent_report or idempotent or semantically_invalid)' -vv
```

**Task review range:** `R3_PRE_SHA..R3_HEAD`.

**Frozen:** never overwrite a corrupt terminal path, never skip deep trust,
and never disable valid recovery.

## S1 — `A3-REPO-P1-03`: exact `sys` identity

**Base root cause:** capability union may retain `complete=True`, while pair
comparison checks whether `sys-module` is merely present in a may-set rather
than proving exact imported identity.

**RED tests:**

- `test_identity_comparison_does_not_treat_may_sys_as_exact_sys`;
- `test_may_sys_identity_fold_cannot_hide_pep562_import_module_rebinding`.

The public bypass uses a conditional `sys`/`sys.stdout` carrier followed by a
runtime-truthy comparison that rebinds `import_module` to a forged loader.

**Before:** comparison is folded false and the reachable rebinding disappears.

**After:** comparison is unknown and joined provenance makes the initializer
fail closed.

**Controls:** exact forward/reverse `sys` mismatch under `is`, exact mismatch
under `is not`, singleton comparisons, chained comparisons, and valid PEP 562
initializers.

**Focused command:**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'may_sys or identity_comparison or singleton or pep562' -vv
```

**Task review range:** `S1_PRE_SHA..S1_HEAD`.

**Frozen:** lattice dimensions, traversal bound, and every exact PEP 562 role.

## S2 — `A3-REPO-P1-04`: unreachable runtime effects

**Base root cause:** dead `If`/`IfExp` arms are scanned with an unreachable
context, but their complete expression/flow results are still joined into the
reachable projection.

**RED tests:**

- `test_unreachable_if_statement_does_not_erase_evaluation_scope_provenance`;
- `test_unreachable_if_expression_does_not_erase_evaluation_scope_provenance`;
- `test_unreachable_if_statement_does_not_erase_plan_cases_provenance`;
- `test_unreachable_if_expression_does_not_erase_plan_cases_provenance`;
- `test_unreachable_branch_still_emits_policy_facts`.

**Before:** dead assignment lowers protected identity to top and can hide a
later protected sink.

**After:** dead syntax still rejects `eval`, but assignments, values, writes,
raises, exits, and runtime edges do not escape. A live branch still mutates;
unknown conditions still join both arms.

**Focused command:**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'unreachable_if or unreachable_branch or TYPE_CHECKING' -vv
```

**Task review range:** `S2_PRE_SHA..S2_HEAD`.

**Frozen:** existing program-point join, comparison short-circuit behavior,
and policy inspection of dead source.

## S3 — `A3-REPO-P1-05`: protected carrier provenance

**Base root cause:** container conversion drops exact identity to top without
a protected may capability, and generic unknown-call returns discard protected
argument provenance.

**RED tests:**

- list/dict/subscript `EvaluationScope` provenance;
- unknown-call return `EvaluationScope` provenance;
- list/dict/subscript `plan_cases` provenance;
- unknown-call return `plan_cases` provenance;
- `test_protected_carrier_never_qualifies_as_exact_approved_plan`;
- `test_protected_provenance_depth_obeys_canonical_complexity_bound` at depths
  1, 2, 4, 8, 16, 32, and 64.

**Before:** a carrier returns an unprotected unknown value and the sink may be
accepted.

**After:** two may bits survive finite carriers and force rejection; neither
bit can approve a call.

**Controls:** harmless `sys.stdout` carriers, harmless containers, real
approved development/legacy plan calls, exact approved development scope, real
checkout scanner, and mandatory safe sources.

**Expected proof constants:** capability dimension `15 -> 17`; canonical
height bounds `69 -> 75`, `137 -> 149`, `807 -> 879`.

**Focused command:**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'container_subscript_preserves or unknown_call_return_preserves or protected_carrier or protected_provenance_depth or approved_plan' -vv
```

**Task review range:** `S3_PRE_SHA..S3_HEAD`.

**Frozen:** no arbitrary heap position, call summary, interprocedural identity,
or exact approval from may provenance.

## S4 — `A3-REPO-P1-06`: sensitive-member grammar

**Base root cause:** direct attributes, literal `getattr`, bound dunder access,
and import-from each derive capabilities through different incomplete rules.

**RED families:**

- `test_sys_registry_member_grammar_rejects_all_selection_forms` for
  `modules`, `meta_path`, and `path_hooks`;
- `test_dynamic_loader_member_grammar_rejects_direct_reflected_and_imported_forms`
  for `pkgutil.resolve_name` and `zipimport.zipimporter`;
- `test_operator_methodcaller_grammar_rejects_direct_reflected_and_imported_forms`;
- `test_universal_reflection_member_grammar_rejects_direct_getattr_and_dunder_forms`
  for `object.__subclasses__` and frame `f_globals`;
- `test_dunder_plan_cases_selection_retains_protected_provenance`;
- `test_nonliteral_dunder_member_selection_fails_closed`.

**Before:** at least one required selection form lacks the sensitive
capability and can reach a protected source.

**After:** all four forms use the design's finite grammar; imported harmless
members do not inherit their module's capability; nonliteral dunder access
fails closed.

**Controls:** direct/reflected/imported `sys.stdout`, harmless `getattr`,
`hasattr`, harmless literal dunder, builtins lookups, exact PEP 562/CLI roles,
both approved plan calls, package-resolution behavior, and depth-64 harmless
dunder complexity.

**Focused command:**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py \
  -k 'member_grammar or universal_reflection or dunder_plan_cases or nonliteral_dunder or harmless or approved_plan' -vv
```

**Task review range:** `S4_PRE_SHA..S4_HEAD`.

**Frozen:** no `__dict__` universal ban, general reflection evaluator, new
exact-role exemption, or arbitrary descriptor execution.

## I1 — `A3-REPO-P1-07`: validation deadline

**Base root cause:** sealed command ordinal 3 has a 1,800-second enforced
deadline while the same exact-HEAD test selection took 5,553.14 seconds.

**RED tests:**

1. runner request literals equal exactly
   `(300, 300, 600, 7200, 600, 900)`;
2. a record with 7,200 at ordinal 3 is current-semantics valid;
3. a legacy record with 1,800 at ordinal 3 is structurally schema-valid but
   current-semantics invalid;
4. 7,200 at any other ordinal is semantically invalid;
5. 7,199, 7,201, and other non-enum values are schema-invalid.

Tests must use independent literals, not import the production constant as the
oracle.

**Before:** ordinal 3 request is 1,800 and an explicit current 7,200 record is
rejected.

**After:** only tuple ordinal 3 changes; schema enum is exactly
`[300, 600, 900, 1800, 7200]`; current semantic verification requires the
exact six-value tuple.

**Focused commands:**

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
```

**Task review range:** `I1_PRE_SHA..I1_HEAD`.

**Frozen:** the other five tuple values; command names, argv, order, cwd,
environment, output cap, snapshot checks, `shell=False`, process-group kill;
schema ID/version; one-run/monotonic history; 47-path membership/order.

## Integrated regression gates

After all eight task reviews approve the future implementation HEAD:

1. Run the exact ten-module suite from the implementation plan and prove fresh
   collection is exactly 10 modules. Its base precedent is 1,508 passing tests;
   the successor count may only increase by the planned regressions.
2. Run fresh uninterrupted `make validate` from the beginning. Do not reuse the
   `ecec6e1` result or any interrupted/partial run.
3. Recompute all frozen hashes, selection semantics, 47-path
   membership/order, aggregate feasibility projection, prohibited-path
   absence, and sibling fingerprints.
4. Review the exact `8e4b3ff..FINAL_HEAD` package under Appendices A-D.

The ordinary test commands above do not authorize validation/oracle/finalize or
study CLI commands against a result root.

## Separate plan-review namespace

These items record the seven GPT review requirements that this documentation
package must close. They are not repository findings.

| ID | Sev. | Documentation risk | Closure evidence required | State |
| --- | --- | --- | --- | --- |
| `A3-PLAN-REVIEW-P1-01` | P1 | Treating automated green or `ecec6e1` as approved QA baseline | Explicit `REVIEW_REJECTED_CHECKPOINT`; QA only after future four-review gate and fresh Stage 1 | `READY_FOR_REVIEW` |
| `A3-PLAN-REVIEW-P1-02` | P1 | Allowing implementation under a documentation-only approval | Exact four-file authorization and repeated separate-approval gate | `READY_FOR_REVIEW` |
| `A3-PLAN-REVIEW-P1-03` | P1 | Conflating repository findings, runtime/trust tasks, timeout, and GPT review counts | Authoritative repository `P1=7/P2=1`; seven runtime/trust plus one timeout; separate seven-item plan namespace | `READY_FOR_REVIEW` |
| `A3-PLAN-REVIEW-P1-04` | P1 | Current evidence receiving credit from stale or merely present evidence | Current-anchor, `NONEMPTY != VERIFIED`, historical/current separation invariants and REDs | `READY_FOR_REVIEW` |
| `A3-PLAN-REVIEW-P1-05` | P1 | Reviewer drift from different ranges, prompts, hashes, or frozen claims | One package SHA, exact design/final ranges, common contract and four appendices | `READY_FOR_REVIEW` |
| `A3-PLAN-REVIEW-P2-01` | P2 | Unbounded repeat repairs after another structural finding | One focused repair maximum; mandatory A/B/C user decision on stop | `READY_FOR_REVIEW` |
| `A3-PLAN-REVIEW-P2-02` | P2 | Predetermining QA acceptance or silently reusing parked QA | Fresh QA worktree and Stage 1 returning either `BASELINE_ACCEPTED` or `BASELINE_HOLD`; separate QA approval | `READY_FOR_REVIEW` |

These rows become `CLOSED` only when the independent documentation reviewer
returns `APPROVE` for the exact `ecec6e1..DOC_HEAD` package. If a document is
changed afterward, every row returns to `READY_FOR_REVIEW` until the new
package is reviewed.

## Global frozen and stop conditions

Every task inherits all hashes, semantics, prohibited paths, sibling
fingerprints, and non-goals in the design. In particular, no task may change
Candidate Selection, Candidate A/B, thresholds, seed, protocol, gates, fixed
E1 results, `HOLD / null / UNVERIFIED`, projection membership/order, or study
execution meaning.

Stop before a second repair for the same task or before any out-of-allowlist
edit. A same blocker after the one focused repair, or a new structural or
out-of-scope P0/P1/P2, requires the user's explicit A/B/C decision. It must not
be silently converted into a ninth task.
