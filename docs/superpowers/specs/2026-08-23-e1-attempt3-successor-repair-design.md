# E1 Attempt 3 Successor Repair Design

## Status and authority

This document defines a documentation-only successor cycle approved by the
user in the current Codex session on 2026-08-23. It does not authorize any
production, test, schema, fixture, evidence, or generated-artifact change.

- Repository: `manufacturing-vision-studio`
- Immutable base: `ecec6e128ff560ab0e7b8ec403dca861ce0965ee`
- Base tree: `c27b47ebea3ecab343eb2be61c6315422ec7413d`
- Base classification: `REVIEW_REJECTED_CHECKPOINT`
- Documentation branch: `codex/e1-attempt3-successor-repair`
- Documentation worktree:
  `/Users/jangtaeho/manufacturing-vision-studio-e1-attempt3-successor-repair`
- Whole-branch review base:
  `8e4b3ff52461c907c728fb2eae6660dafba7c53a`

The current authorization covers exactly four tracked files:

1. this design;
2. `docs/superpowers/plans/2026-08-23-e1-attempt3-successor-repair.md`;
3. `docs/superpowers/plans/2026-08-23-e1-attempt3-finding-to-test-matrix.md`;
4. `docs/superpowers/plans/2026-08-23-e1-attempt3-review-contract.md`.

The four-document package must pass an independent review with zero unresolved
P0/P1/P2 before a separate request for implementation authorization. A green
documentation review does not authorize implementation, QA, Push, or PR.

## Why a successor design is required

At `ecec6e1`, the exact ten-module suite passed 1,508 tests and a fresh
`make validate` passed Ruff, Mypy, 1,883 Python tests, web checks, and 15
Playwright tests. The full Python test phase took 5,553.14 seconds. Four
independent whole-branch reviews nevertheless rejected that HEAD because its
current-verification and source-trust boundaries remained fail-open.

Therefore:

```text
AUTOMATED_GREEN != REVIEW_APPROVED
REVIEW_REJECTED_CHECKPOINT != QA_BASELINE
IMPLEMENTATION != APPROVAL
```

No validation or review approval from `ecec6e1` carries forward to a later
HEAD. Historical evidence remains auditable, but it cannot grant current
verification credit.

## Finding namespaces and counts

### Repository findings

Attempt 3 has one authoritative deduplicated repository ledger:

| ID | Severity | Domain | Finding |
| --- | --- | --- | --- |
| `A3-REPO-P1-01` | P1 | Artifact state | A nonempty early-invalid packet without a verified implementation-validation anchor receives complement-derived verification credit. |
| `A3-REPO-P1-02` | P1 | Artifact state | `finalize()` can return success when a report is present but corrupt. |
| `A3-REPO-P2-01` | P2 | Artifact state | Unauthorized Phase 2 returns before its optional invalid-terminal projection is verified. |
| `A3-REPO-P1-03` | P1 | Truth boundary | A value that may be `sys` is treated as exact `sys` during identity folding. |
| `A3-REPO-P1-04` | P1 | Truth boundary | Unreachable `If`/`IfExp` policy inspection leaks runtime values and writes into reachable state. |
| `A3-REPO-P1-05` | P1 | Truth boundary | Containers and unknown calls erase protected `EvaluationScope` and `plan_cases` provenance. |
| `A3-REPO-P1-06` | P1 | Truth boundary | Direct, reflected, bound-dunder, and import-from sensitive-member selection use inconsistent grammars. |
| `A3-REPO-P1-07` | P1 | Validation infrastructure | The sealed full-pytest deadline is 1,800 seconds although the validated selection required 5,553.14 seconds. |

Authoritative total: `P0=0 / P1=7 / P2=1`, eight repository findings.
The timeout is implemented as a separate validation-infrastructure task, but
it remains `A3-REPO-P1-07` and remains part of the total eight. It must not be
relabelled as an unscored operational note.

### Plan-review findings

GPT's review of the proposed successor plan is tracked separately as
`A3-PLAN-REVIEW-P1-01..05` and `A3-PLAN-REVIEW-P2-01..02`. Those seven review
items govern the accuracy and safety of this documentation package; they are
not additional repository defects and must never be added to the repository
total. Their closure is recorded in the finding-to-test matrix.

## Binding trust invariants

1. **Current anchor:** Current verification credit requires a current,
   parsed, schema-valid, and deeply verified implementation-validation anchor.
2. **No complement proof:** Presence is inventory, not verification.
   `NONEMPTY != VERIFIED`; a nonempty unanchored packet receives zero credit.
3. **Terminal integrity:** A terminal decision/report is creditable only when
   its exact bytes and bindings project the current inspected state. A present
   corrupt report is never overwritten or treated as success.
4. **Historical separation:** Historical records may remain byte-preserved for
   audit. Stale identity, stale timeout semantics, or stale upstream bindings
   cannot grant current credit.
5. **Exact versus may:** Approval may use only complete exact identity. A
   may/unknown protected provenance is sufficient to reject but never to
   authorize an exception.
6. **Reachability separation:** Unreachable syntax remains policy-inspected,
   while its runtime value, state, writes, exits, raises, and dependency edges
   never enter the reachable projection.
7. **Uniform selection grammar:** Direct attribute access, exact builtin
   `getattr`, bound literal `__getattribute__`, and import-from selection use
   one finite sensitive-member classifier.
8. **Finite validation:** Every sealed command retains a finite deadline and
   its existing process-group kill boundary. The deadline must nevertheless
   permit the validated command selection to complete in the observed
   environment.

These invariants are the architecture. A patch that makes a named test pass by
weakening one of them is invalid even if all automation is green.

## Selected repair architecture

### R1 — Unanchored nonempty packet credit

`VerifiedStudyState.verified_paths` remains complement-based because retained
raw inputs and `report.md` can legitimately receive credit after anchor and
deep validation. The repair belongs at `StudyRunner._public_state`, not in a
global redefinition of that property.

- An absent root remains pristine `PENDING`, `study_valid=True`, zero of zero,
  and creates nothing.
- A nonempty packet without a parsed validation anchor becomes fail-closed
  `STUDY_INVALID`; every present path is invalid and the verify rate is 0.0.
- The existing inventory or verification reason is retained.
- Every anchored packet, including an honestly invalid packet, continues into
  deep verification.

This closes `A3-REPO-P1-01` without removing credit from an honestly sealed and
deeply verified `STUDY_INVALID` terminal pair.

### R2 — Unauthorized Phase 2 terminal projection

The unauthorized-Phase-2 branch first creates the same invalid state it does
today, then routes that state through the existing
`_verify_invalid_terminal_projection` path.

- The Phase-2 artifacts remain invalid and are never interpreted as an
  authorized study result.
- A forged or state-mismatched decision/report receives no credit.
- An exact honestly sealed `STUDY_INVALID` pair may retain credit after full
  identity, upstream, payload, invalid-path, rate, and rendered-byte checks.

No new decision grammar or phase authorization is introduced.

### R3 — Corrupt present report finalization

After deep finalization evidence is required, `finalize()` must distinguish
three terminal report states:

| Report state | Required result |
| --- | --- |
| absent | deterministically publish the report for an already verified decision |
| present and exact | return idempotently |
| present and invalid | raise `StudyStateError`, preserve all bytes, publish nothing |

An existing decision cannot make a corrupt present report recoverable. The
repair neither overwrites historical bytes nor disables absent-report repair.

### S1 — Exact `sys` identity

Identity folding may prove a `sys` mismatch only when one operand has the
complete exact imported identity `("imported", "sys", "<module>")` and the
other is complete and definitely carries no `sys-module` capability.

- exact `sys is sys.stdout` remains false;
- exact mismatch under `is not` remains true;
- may-`sys`, incomplete identity, and identity-top remain unknown;
- no object-identity engine or new lattice dimension is added.

This prevents a may-set from pruning a reachable rebinding or sensitive sink.

### S2 — Policy-only unreachable projection

Dead `If` and `IfExp` arms are scanned once with a policy-only projection.
Only policy facts and deferred bodies that still require policy inspection may
escape the dead arm. Runtime value, state, writes, normal/abrupt exits,
exceptions, and raises cannot join a reachable branch.

Unknown conditions still join both reachable arms. Definitely live arms keep
their writes and raises. Existing dead-source bans such as `eval` remain
enforced.

### S3 — Protected provenance through finite carriers

Add exactly two finite may-capability bits:

- `evaluation-scope`;
- `plan-cases-callable`.

Exact protected identity may be lost through a container or unknown call, but
the corresponding may bit must survive. Unknown-call returns conservatively
inherit only these protected bits from arguments, remain incomplete, and do
not acquire exact identity.

- May `EvaluationScope` at a protected member is rejected.
- May `plan_cases` at a call is rejected.
- The two existing approved plan roles still require both completed exact
  identity and the exact approved call site.

The capability dimension changes mechanically from 15 to 17. The expected
canonical height bounds change only as follows: `69 -> 75`, `137 -> 149`, and
`807 -> 879`. No heap graph, arbitrary wrapper graph, interprocedural return
summary, or unbounded provenance store is permitted.

### S4 — Central sensitive-member grammar

One finite classifier is shared by these four selection forms:

1. direct `ast.Attribute`;
2. exact builtin `getattr`, including an alias, `builtins.getattr`, and its
   three-argument default form;
3. bound literal `receiver.__getattribute__("member")`;
4. `from module import member [as alias]`.

| Receiver or owner | Literal members | Capability/result |
| --- | --- | --- |
| `sys-module` | `modules`, `meta_path`, `path_hooks` | `import-registry` |
| `pkgutil-module` | `get_loader`, `resolve_name` | `dynamic-import` and `import-loader` |
| `zipimport-module` | `zipimporter` | `dynamic-import` and `import-loader` |
| `operator-module` | `attrgetter`, `methodcaller` | `namespace-reflection` |
| any receiver | `__globals__`, `__subclasses__`, `__bases__`, `__mro__`, `f_globals`, `f_locals`, `f_builtins`, `f_back`, `tb_frame`, `gi_frame`, `cr_frame`, `ag_frame` | `namespace-reflection` |
| may `EvaluationScope` | `SMOKE`, `CALIBRATION`, `RELEASE_TEST`, or a dynamic name | protected-scope fact |
| any receiver | `plan_cases` | plan-cases provenance; exact approval remains separate |

PEP 562, the CLI dataclass role, and the two approved plan-call roles remain
exact and are not broadened. `__dict__` is not added to the universal deny set
because its existing controlled builtins-mapping semantics must remain intact.
A nonliteral bound `__getattribute__` member fails closed. A harmless literal
retains existing generic behavior.

### I1 — Full-pytest validation deadline

The validation-infrastructure task changes exactly the fourth tuple value:

```text
(300, 300, 600, 1800, 600, 900)
->
(300, 300, 600, 7200, 600, 900)
```

Ordinal 3 is the sealed `uv run pytest -q` command. The observed exact-HEAD
runtime was 5,553.14 seconds; 7,200 seconds leaves 1,646.86 seconds, or 29.66
percent, of headroom while retaining a finite two-hour kill boundary.

Schema and semantic compatibility are deliberately separate:

```text
v1 structural compatibility: timeout enum permits 1800 and 7200
current semantic validity: ordinal 3 must be exactly 7200
```

The schema remains a closed enum `[300, 600, 900, 1800, 7200]`; it is not
replaced with a range and its version is not changed. A historical 1,800-second
record remains structurally readable but cannot receive current semantic
credit. The runner already forwards the retention tuple into the request and
kill deadline, so its production source is read-only for this task.

## Allowed future implementation surface

Implementation remains unauthorized. If later approved, each task is limited
to the following paths.

| Tasks | Production/schema | Tests |
| --- | --- | --- |
| R1-R3 | `src/manufacturing_vision_studio/e1/study_runner_v2.py` | `tests/test_e1_study_runner_v2.py` |
| S1-S4 | `src/manufacturing_vision_studio/e1/study_retention_v2.py` | `tests/test_e1_study_dependency_guard_v2.py` |
| I1 | `src/manufacturing_vision_studio/e1/study_retention_v2.py`; `schemas/e1-feasibility-study-artifact.v1.json` | `tests/test_e1_study_runner_v2.py`; `tests/test_e1_study_retention_v2.py`; `tests/test_e1_study_artifacts_v2.py` |

For I1, `study_runner_v2.py`, `Makefile`, and `study_cli_v2.py` are read-only
evidence. A task that needs a path outside its row stops before editing.

## Frozen identity and behavior

The following remain byte- or value-frozen throughout the future repair:

- Candidate Selection raw SHA-256:
  `32868450a349379e8e548854217c69035b7972ab75acc7f02295e5fae8a76242`;
- Candidate Selection record/projection:
  `7392d4d1d9078b44dac0c9dc777d7622f1f145c2e3b6bf9fffb9a58be407ae5a` /
  `7ccc656be191d0216480da4ad6536d4f50995a446a45f6810b1133a64583cbfa`;
- selection semantics: `HOLD / null / UNVERIFIED`;
- embedded Candidate A/B:
  `ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84` /
  `983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029`;
- historical raw/record/projection/snapshot:
  `18ca69bba321f24105c95cc3482b9658e7a2f03ef274ac75a5ed44f822782a9b` /
  `f2a257a731d991ceba74f791e24a15e983fd806734af2ea973fc5808daab7280` /
  `90c5c7a894b1289572718fce13f39177fafe278707fae697accb0cd9828de429` /
  `8d636717a1b04267933b214a3121acfb93182e46`;
- v0.1.0 bundle, E1-mini, E1-full, and HOLD Packet:
  `1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7`,
  `f026d1fccb34711b82bcda30eab399558c418f9e3ca33f1c754ed8117d624764`,
  `557ea17abe655f82e5974ab7121de4ed905755ee4f1ff02976a0ed62a01f964c`,
  `91d3c3dbb3241fd7c5b3d697f08ee9b239ff347e8cebb1e3aa6b6a842d4dc62d`;
- Candidate A/B outcomes, historical 120/108 counts, threshold, seed,
  protocol, acceptance gates, fixed E1 results, feasibility config, and study
  phase authorization;
- feasibility implementation-projection membership and order: exactly 47
  unique paths in protocol order.

The current feasibility projection hash
`b426178abe769390fde21689ca0df311b8ac28a291665cb4c74a9d828f61fe2f`
is a measured base fingerprint, not a frozen successor value. Authorized
source/schema edits will deterministically change member hashes and therefore
the aggregate hash. Membership and order must not change. Candidate Selection
has no overlap with these changed source/schema members and must not be rebound.

The following paths are prohibited from creation or modification:

- `data/e1-v2-development/candidate-a.json`;
- `data/e1-feasibility-study`;
- `docs/evaluation/results/e1-feasibility-study`.

No Candidate comparison, evaluation, search, inference, benchmark, or study
implementation-validation/oracle/finalization/phase command may run during
this documentation cycle. Read-only inspection and ordinary focused repository
tests are allowed. The future implementation cycle also may not execute study
phases; its ordinary unit/integration validation is allowed only after separate
approval.

## Worktree preservation

The successor worktree is the only writable repository checkout for this
cycle. These sibling states are protection evidence, not repair inputs:

| Worktree | Expected state |
| --- | --- |
| rejected checkpoint `/Users/jangtaeho/manufacturing-vision-studio-e1-review-blocker-repair` | `ecec6e1`, clean |
| original dirty `/Users/jangtaeho/manufacturing-vision-studio-e1-dataflow-redesign` | `3ced81c`; status hash `80ce51d494c8a145d99ec671b778af0248f4ea512f4761e853e76c6737c1182c`; diff hash `d1395bf9d4036547fd5a2ae26788a8fc27fa74eb81b4803868e457a7183d50c8` |
| current-identity `/Users/jangtaeho/manufacturing-vision-studio-e1-current-identity-repair` | `c689309`, clean |
| parked QA `/Users/jangtaeho/manufacturing-vision-studio-quality-evidence-change-review-v0.3.0` | `3ced81c`, clean |
| historical run `/Users/jangtaeho/manufacturing-vision-studio-e1-v2` | `9fd6d0c`, clean |
| feasibility sibling `/Users/jangtaeho/manufacturing-vision-studio-e1-feasibility-separability` | `0a3f9ad`, clean |

The dirty Candidate Selection file is never reset, stashed, checked out,
overwritten, staged, committed, or copied to another worktree.

## Task and review state machine

Every repository task is sequential and owns one commit boundary:

```text
OPEN -> RED_PROVEN -> INITIAL_GREEN -> TASK_REVIEW -> REVIEWED
```

The first RED must reproduce the named public failure at the task's pre-task
SHA and mandatory positive controls must remain valid. One initial focused
implementation is allowed. If task review finds a valid in-scope issue, the
same task may receive at most one review-driven focused repair and one fresh
review. The following conditions stop the cycle immediately:

- the same blocker survives that focused repair;
- the RED does not reproduce for the expected reason;
- a positive control fails before implementation;
- a required change falls outside the task allowlist or a frozen boundary;
- a new structural or out-of-scope P0/P1/P2 appears;
- correctness requires a general reflection engine, heap/object graph,
  interprocedural summary, protocol change, gate change, or study execution.

There is no automatic Attempt 4 or Attempt 5. On stop, ask the user to choose:

```text
A. redesign a smaller Trusted Core
B. freeze E1 as HOLD and stop QA
C. reevaluate whether further investment is justified
```

## Review ranges and completion gates

The documentation review uses exactly:

```text
ecec6e128ff560ab0e7b8ec403dca861ce0965ee..DOC_HEAD
```

`DOC_HEAD` is the commit containing exactly the four authorized documents. If
any document changes, pin the new `DOC_HEAD` and restart that review. The
future whole-branch review uses exactly:

```text
8e4b3ff52461c907c728fb2eae6660dafba7c53a..FINAL_HEAD
```

All four final reviewers receive one byte-identical diff package, package hash,
common contract, severity scale, frozen claims, and their domain appendix.
Approval requires four of four first-line `APPROVE` verdicts and zero unresolved
P0/P1/P2. Earlier validation, hashes, or reviews do not transfer across a HEAD
change.

## QA handoff

Even an approved `FINAL_HEAD` is only eligible for a new QA Stage 1 audit:

```text
FINAL_HEAD eligible
  -> create a fresh QA branch/worktree from FINAL_HEAD
  -> rerun read-only Stage 1
  -> classify BASELINE_ACCEPTED or BASELINE_HOLD from evidence
```

`BASELINE_ACCEPTED` is not predetermined. The parked QA worktree is not reused.
QA Core implementation still requires separate user authorization after an
accepted baseline. This successor design never authorizes QA implementation.
