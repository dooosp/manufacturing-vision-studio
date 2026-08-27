# E1 Declared Source Dependency Closure Hardening Design

**Date:** 2026-08-07

**Status:** Approved written specification

**Target revision:** `8e4b3ff52461c907c728fb2eae6660dafba7c53a`

**Branch:** `codex/e1-feasibility-separability-study`

**Workspace:**
`/Users/jangtaeho/manufacturing-vision-studio-e1-feasibility-separability`

## 1. Decision and purpose

The E1 feasibility study remains blocked before implementation validation and
before every one-time study phase. Four whole-branch review findings at the
target revision are confirmed:

1. the dependency scanner accepts another reflected import spelling,
   `vars(builtins)["__import__"]`;
2. a malformed `decision.json` can leave its dependent `report.md` counted as
   verified;
3. negative-result snapshots bind their bytes but not their two exact frozen
   paths; and
4. the `verify` CLI command returns exit status zero when the report says
   `study_valid=false`.

This design replaces the recurring import-spelling patch cycle with a
conservative source-capability policy and closes the three independent truth
and operability defects in the same pre-execution implementation projection.
The result must fail closed before Phase 0 rather than attempt to repair or
reinterpret study evidence after an experiment has run.

This document amends Sections 3, 5, 6.3, and 7 of
`docs/superpowers/specs/2026-08-01-e1-feasibility-separability-study-design.md`
only where they describe dependency-closure assurance and its pre-execution
gate. Every other approved study purpose, phase boundary, metric, and non-goal
remains in force.

## 2. Evidence and structural diagnosis

The implementation projection contains 47 protocol-declared paths. The current
retention verifier reads each bounded production source once, hashes those
bytes, parses those same bytes, and constructs an abstract dependency graph.
That byte-to-AST binding is retained.

The repeated failure is in the graph extractor's claim and policy. The current
`_ImportVisitor` in
`src/manufacturing_vision_studio/e1/study_retention_v2.py` recognizes selected
ways to acquire a loader. Review rounds have successively found importlib
reflection, alias laundering, annotated and destructuring assignments,
aliased builtin dictionaries, and now `vars(builtins)`. Python's reflective
surface is open-ended, so adding the latest spelling cannot establish a closed
invariant.

Source inspection also shows that the study performance surface does not need
general dynamic import or namespace reflection. The only intended dynamic
import behavior is the established PEP 562 public API loader in:

- `src/manufacturing_vision_studio/__init__.py`; and
- `src/manufacturing_vision_studio/e1/__init__.py`.

Other production `getattr` calls serve ordinary typed field access, optional OS
flags, Pillow frame checks, or dataclass serialization. They do not need access
to loader, module-dictionary, frame-global, or executable-code capabilities.

The other three findings are local but must be fixed before the implementation
projection is frozen:

- `VerifiedStudyState.verified_paths` is the complement of `invalid_paths`, so
  missing dependency propagation overstates verification;
- snapshot validation currently accepts any matching project-local copy and
  any original path under `/Users/jangtaeho/`; and
- `study_cli_v2.main()` prints every successful API return and then
  unconditionally returns zero.

No study command, broad validation command, Phase 0, implementation validation,
or experiment phase was run to derive this design. The basis is exact-revision
source, configuration, tests, and review-ledger inspection.

The integrity-bound evidence inventory, option tradeoffs, and residual risks
are recorded in the
[security hardening portfolio](../../security/hardening/2026-08-07-e1-declared-source-dependency-closure/hardening.md)
and its
[detailed proposal](../../security/hardening/2026-08-07-e1-declared-source-dependency-closure/proposals/declarative-dependency-closure.md).

## 3. Options considered

### 3.1 Continue spelling-specific patches

This option would add `vars(builtins)` and adjacent fixtures to the existing
visitor. It has the smallest immediate diff, but its invariant remains "the
spellings currently known to reviewers are rejected." The accumulated bypass
history demonstrates that this is not an adequate final gate.

### 3.2 Static positive source-capability grammar — selected

This option keeps exact-byte parsing and the declared dependency graph, but
changes the scanner from open-ended bad-spelling recognition to a deliberately
narrow source language. Static imports are visible graph edges. Dynamic loader,
executable-code, and dependency-sensitive reflection capabilities are rejected
unless a node belongs to one of two exact package-initializer structures.

This option matches the actual local-demo objective, adds no process or service,
and preserves pre-execution attestation. It is the selected design.

### 3.3 Runtime import bootstrap

A bootstrap process could install an import guard before loading the study
runner. It would add defense in depth for exercised imports, but it would require
moving the current top-level runner import behind a new entry point. Already
loaded modules, pre-bootstrap behavior, subprocesses, and unexercised paths
would remain outside its proof. It is deferred and is not part of the current
attestation claim.

## 4. Truthful claim and non-goals

The retained verifier will make this bounded claim:

> For the exact bounded bytes of the protocol-declared production projection,
> every accepted declared source dependency is projected and allowed, and the
> runtime-reachable study source contains none of the prohibited
> dynamic-import, executable-code, or dependency-sensitive reflection syntax
> outside the two exact initializer exceptions.

The result and documentation will call this the **declared source dependency
closure**. They must not call it a complete runtime dependency proof.

This design does not:

- turn Python into a sandbox or prove semantic reachability for every possible
  input, callback, extension module, descriptor, or environment;
- add a runtime import hook, container, process boundary, or remote service;
- recursively impose the production AST policy on pytest or validation
  subprocess code;
- change the frozen diagnostic matrix, threshold, gates, seeds, split, or study
  phase behavior;
- change the canonical study configuration or schema version merely to repair
  validation;
- run implementation validation or any one-time study phase;
- reopen Candidate A/B selection, create Candidate C, connect to FreeCAD, push,
  open a PR, tag, or release.

## 5. Trust boundaries

### 5.1 Projected production source

The policy applies to the exact Python production files in the protocol's
implementation projection. Runtime reachability begins from the study-owned
roots and uses declared source edges. Project imports must resolve to the
projection and satisfy the existing direct-import allowlists and forbidden
reachability rules.

### 5.2 Latent public package exports

The two package initializers expose lazy public API exports. Their literal
`_LAZY_EXPORTS` targets are validated as projected latent edges. A latent target
is not automatically a performance-command edge merely because it appears in
the public export table; it becomes reachable only when accepted source
performs the corresponding package-object attribute access. Study-owned source
continues to reject package-object loading in place of explicit submodule
imports.

### 5.3 Tests and validation subprocesses

Tests contain malicious source strings and some tests intentionally use
`__import__`, `vars`, `sys.modules`, or importlib. Validation also invokes fixed
local commands in a sealed environment. These are audited command/evidence
boundaries, not production dependency edges. The production scanner parses
malicious fixture strings but never executes them.

## 6. Selected architecture

### 6.1 Single-read projection snapshot

The verifier retains the existing bounded-read invariant:

1. resolve and validate each declared tracked path;
2. read each production file once with the existing size and file-safety
   limits;
3. calculate the projection hash from those bytes;
4. pass those exact in-memory bytes to `ast.parse`; and
5. build every source-policy result from that parsed snapshot.

No policy stage may reopen a source path. A read/parse mismatch, unknown path,
unsafe file kind, or syntax error remains a deterministic validation failure.

### 6.2 Declared dependency graph

Literal `import` and `from ... import ...` statements create graph edges.
Relative imports are resolved against the source module. Project targets must
be known projected modules; unresolved project symbols, wildcard imports,
runtime package-object imports, forbidden prefixes, unexpected direct edges,
and study-owned cycles remain rejected.

The graph result will be described as a declared source dependency closure. No
artifact schema, record type, or existing serialized field is renamed by this
hardening. Reader-facing documentation and diagnostics define those existing
closure fields precisely and must not describe them as proof of all possible
Python execution.

### 6.3 Source-capability policy

For runtime-reachable projected source, the scanner rejects acquisition, first-
class storage, aliasing, passing, returning, or invocation of these capability
families:

- `importlib` and loader/spec APIs;
- `builtins`, `__builtins__`, and `__import__`;
- `runpy`, `pkgutil`, and `zipimport` loading APIs;
- builtin `exec`, `eval`, and `compile`;
- dependency-sensitive namespace access through `vars`, `globals`, `locals`,
  `__dict__`, `__globals__`, frame globals/builtins, and import-related
  `sys` registries;
- `object.__getattribute__`, `type.__getattribute__`, or operator reflection
  used to acquire the same capabilities; and
- computed or nonliteral names on a capability-bearing object.

String constants, test fixture text, helper names inside the scanner, and
`re.compile` are not capability use. Attribute and call matching is semantic
AST matching rather than token matching.

Ordinary object inspection is accepted only through finite safe forms:

- direct `getattr` or `hasattr` with a literal non-sensitive attribute;
- the existing dataclass serialization form, where `is_dataclass(value)` and
  `fields(value)` constrain field acquisition;
- a locally provable finite set of benign application fields; or
- an explicit field-dispatch refactor when the scanner cannot prove the prior
  case.

New first-class or unconstrained reflection fails closed. Existing production
behavior must not receive a broad reflection exemption simply to keep a test
green.

### 6.4 Lexical scope model

Capability state is tracked with real lexical frames for modules, classes,
functions, async functions, lambdas, and comprehensions. Binding analysis
includes:

- arguments, defaults, imports, class and function definitions;
- `Assign`, `AnnAssign`, `AugAssign`, destructuring, and named expressions;
- loop, `with`, exception, and match-pattern targets; and
- `global` and `nonlocal` declarations.

Branch joins union possible capability provenance. If one path can bind a
prohibited capability, later use is rejected. Unknown binding behavior does not
silently clear provenance.

`TYPE_CHECKING` is type-only only when it resolves to an unshadowed exact
`typing.TYPE_CHECKING` import. Rebinding, ambiguous aliases, or branch-dependent
shadowing makes the guarded body runtime for policy purposes.

### 6.5 Exact PEP 562 initializer exception

Only the two exact package initializer paths may use the lazy-loader exception.
Each accepted initializer must structurally satisfy all of these rules:

- one module-level, unaliased
  `from importlib import import_module` declaration;
- a literal, validated `_LAZY_EXPORTS` mapping whose module targets resolve to
  projected paths;
- one direct `import_module(module_name)` call inside its module-level
  `__getattr__`, with one positional argument and no keywords;
- no assignment, return, argument passing, wrapper, closure capture, alias, or
  second use of `import_module`;
- only the exact `globals()[name] = value` cache write and `globals()` use in
  the module-level `__dir__`; and
- no extra loader or namespace capability node.

Exception membership is determined by exact source path and AST ancestry/node
identity, not by a matching function name alone. Existing subprocess tests
continue to prove public API identity, lazy loading, and caching behavior.

## 7. Artifact verification dependency closure

`decision.json` and `report.md` form a verification dependency:

```text
report.md -> decision.json
```

Invalidity propagation is centralized and applied before every invalid-state
return, including malformed JSON, relationship errors, semantic terminal
decision failure, or report byte mismatch. A present report cannot enter
`verified_paths` unless its decision is present, parsed, identity-bound,
semantically valid for the current state, and its rendered bytes match.

A correctly sealed terminal `STUDY_INVALID` decision and its matching report
remain verifiable. The fix changes only false verification credit; it does not
convert an invalid study into an exception or a valid study.

## 8. Exact negative-result snapshot identity

Protocol validation uses an ordered frozen tuple for each snapshot:

```text
(name, checked_in_path, original_sibling_path, raw_sha256)
```

The canonical values remain those already checked into
`configs/evaluation/e1-feasibility-study.v1.json`. Validation compares the
complete identity tuple before opening the checked-in path, then performs the
existing bounded byte read and SHA-256 verification.

A byte-identical alias path and a different `/Users/jangtaeho/...` sibling path
are invalid. No configuration, schema, source hash, or evidence byte is changed
by this repair.

## 9. CLI verification semantics

The `StudyRunner.verify()` API remains observational and returns a structured
report. The CLI continues to print that report as JSON.

After printing:

- `verify` returns exit status `1` when `report.status.study_valid is False`;
- `verify` returns zero for a valid `PENDING` or valid terminal report;
- exceptions and operational failures continue to use the existing operational
  error path; and
- other commands preserve their current success semantics.

This allows `make verify-e1-study` and other shell automation to fail when the
domain result is invalid without discarding the machine-readable report.

## 10. Failure behavior and diagnostics

Every new rejection is deterministic and fail closed. Source-policy errors
identify the projected module, source line, and rejected capability family.
They do not expose source contents or attempt recovery. Stable categories are
preferred over spelling-specific messages so fixtures can assert the invariant
rather than internal visitor mechanics.

No failed verification writes or repairs experiment artifacts. No source-policy
failure creates the study result root. CLI invalidity is represented both in
the JSON domain result and the nonzero process status.

## 11. Test design

Implementation follows RED-GREEN-refactor. The first failing tests cover the
reviewed defects before production changes.

### 11.1 Source capability matrix

The dependency-guard suite covers these families, including direct, aliased,
annotated, destructured, walrus, closure, comprehension, argument/default,
computed-name, and uncertain-branch forms where applicable:

| Family | Accepted | Rejected |
| --- | --- | --- |
| Static imports | projected and allowlisted literal imports | unprojected, forbidden, wildcard, or package-object loading |
| Type-only imports | exact unshadowed `typing.TYPE_CHECKING` | shadowed or ambiguous guards |
| PEP 562 | two exact initializer structures | aliases, wrappers, extra calls, nonliteral targets |
| Import capability | no general runtime use | importlib, builtins, `__import__`, runpy, pkgutil, zipimport |
| Executable code | none | builtin exec, eval, compile and loader execution APIs |
| Namespace reflection | finite safe ordinary-object forms | vars/globals/locals, module dictionaries, frame globals, import registries |
| Projection snapshot | identical bytes are hashed and parsed | reread/swap, unsafe path, unprojected target |

The known `vars(builtins)["__import__"]` case and the corresponding
`vars(__builtins__)` form are mandatory regressions. Current legitimate package
imports and ordinary safe attribute uses are positive fixtures.

### 11.2 Artifact-state tests

Tests create a packet containing malformed `decision.json` and a present
`report.md`, then assert that both are excluded from `verified_paths` and the
verify rate is not overstated. Existing valid sealed `STUDY_INVALID`
decision/report coverage remains green.

### 11.3 Snapshot tests

Separate tests mutate only the original sibling path and only the checked-in
path while preserving names and bytes. Both must fail. The oversized-file test
is refactored so it still reaches the bounded-read condition without first
violating exact identity.

### 11.4 CLI tests

Tests assert JSON output plus exit status `1` for an invalid verification report
and zero for a valid intermediate `PENDING` report. Makefile propagation remains
covered by the CLI contract; no final-only requirement is added to `verify`.

## 12. Validation and review gates

The implementation sequence after written-specification review is:

1. write and approve a file-level implementation plan;
2. add focused failing tests for the four findings and policy matrix;
3. implement the selected architecture in small reviewed changes;
4. run the targeted dependency, package-closure, runner, protocol, and CLI
   suites;
5. run the plan-exact ten-module validation set;
6. run `make validate`;
7. obtain fresh state, truth-boundary, evidence, and integration reviews over
   the whole branch range; and
8. proceed to implementation validation only if all four reviews approve and
   the worktree, projection, and result root satisfy the frozen preconditions.

Implementation validation, Phase 0, Phase 1, the feature oracle, Phase 2,
finalization, candidate comparison, Candidate C, FreeCAD, remote publication,
PR, tag, and release remain prohibited until their existing later gates are
separately satisfied.

## 13. Acceptance criteria

The hardening is acceptable only when all of the following are supported by
fresh evidence:

- the known reflected-import bypass and every capability-family regression
  fail closed;
- the two exact PEP 562 initializers and current public API closure tests pass;
- projection bytes used for hashing are the bytes used for parsing;
- declared project dependencies remain projected, allowlisted, and free of
  forbidden reachability;
- malformed decisions cannot confer verification credit on reports;
- both snapshot paths and bytes are exactly frozen;
- an invalid verification report makes the CLI and Make target nonzero while
  preserving JSON output;
- the plan-exact ten-module suite and `make validate` pass;
- four independent final reviews approve the complete branch range; and
- documentation uses the bounded declared-source claim and retains the
  local-demo, synthetic-data, and no-real-manufacturing limitations.

Passing tests alone do not authorize a study phase. The result root must still
be absent and the implementation projection must be frozen before the one-time
execution sequence begins.

## 14. Risks, migration, and rollback

The selected grammar may reject a future legitimate use of dynamic Python. That
is intentional: the default response is an explicit design review and a narrow
audited exception or a non-reflective refactor. It must not be silently relaxed.

Static scanning adds no runtime process, network hop, persistent cache, or
meaningful new memory lifetime. No performance measurement has been made; the
expected cost is a bounded additional AST walk over the already bounded
projection and will be checked by the existing validation runtime rather than
presented as benchmark evidence.

Rollback before any study execution is a normal commit revert. After
implementation validation or a study artifact exists, rollback cannot preserve
the old evidence binding: generated validation and study artifacts must be
treated as invalid and the execution gate must be restarted from an absent
result root and a newly frozen projection.

## 15. Written-review decision

The user approved the architectural direction, detailed conversational design,
and this written specification on 2026-08-07. The file-level implementation
plan now exists and has passed independent documentation review. Production
edits begin only after the user explicitly authorizes one execution mode, then
continue through that plan's TDD, per-task review, validation, and final-review
gates. Neither this specification nor the plan alone authorizes a study command.
