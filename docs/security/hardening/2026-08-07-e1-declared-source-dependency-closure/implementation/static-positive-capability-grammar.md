# Implementation Plan: Static Positive Source-Capability Grammar

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Before
> editing production code, use `superpowers:using-git-worktrees`; the plan must
> pass review and the user must explicitly authorize one execution mode. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Replace E1's recurring import-spelling denylist with a fail-closed
declared-source capability grammar while directly repairing decision/report
verification, negative-snapshot identity, and invalid verify exit semantics.

**Architecture:** Preserve the existing bounded one-read projection so the
bytes hashed are the bytes parsed. Build literal project dependency edges and
lexical capability provenance from that AST, reject unknown
dependency-sensitive capabilities, and admit only finite ordinary-object forms
plus structurally exact PEP 562 exceptions in two package initializers. Keep the
claim bounded to declared source dependency closure; this is not a sandbox.

**Tech stack:** Python 3.11+, `ast`, frozen dataclasses, `pytest`, Ruff, Mypy,
the existing E1 artifact store and CLI, Make, and Git.

**Plan status:** The written specification is approved and the canonical plan
has passed independent documentation review. This handoff is bound to the
approved source and design identities below, but neither document itself
authorizes production edits, implementation validation, or a study phase; user
authorization of one execution mode remains pending.

The step-by-step TDD sequence, exact test selectors, and per-task commit/review
gates live in the
[canonical execution plan](../../../../superpowers/plans/2026-08-07-e1-declared-source-dependency-closure-hardening.md).
This security-portfolio handoff defines the same boundary at work-package
granularity; it is not a second execution sequence. If aggregation wording here
is less specific, the reviewed canonical plan controls after explicit user
execution authorization.

## Selected Design And Constraints

We are implementing Option 2 from the
[hardening proposal](../proposals/declarative-dependency-closure.md). The
selected design has these non-negotiable properties:

- Read each protocol-declared production path once with the existing bounds;
  hash and parse that same in-memory payload. No policy stage reopens a source
  path.
- Preserve literal dependency edges, relative-import resolution, projection
  completeness, direct-import allowlists, forbidden reachability, protected
  scopes, forbidden calls, and study-owned cycle rejection.
- Reject acquisition, storage, aliasing, passing, returning, or invocation of
  loader, executable-code, and dependency-sensitive reflection capabilities in
  runtime-reachable projected source.
- Preserve ordinary safe object operations through finite positive forms. Do
  not grant a broad reflection exemption to keep existing source green.
- Permit lazy loading only in `src/manufacturing_vision_studio/__init__.py` and
  `src/manufacturing_vision_studio/e1/__init__.py`, and only when each file
  satisfies the exact approved PEP 562 AST structure.
- Directly repair `report.md -> decision.json` invalidity propagation, exact
  negative-snapshot path identity, and `verify` exit status. These fixes are
  required independently of the AST redesign.
- Do not rename an artifact schema, record type, serialized closure field,
  configuration key, or protocol version. Do not modify frozen diagnostic
  inputs, thresholds, gates, seeds, splits, or study phase behavior.
- Use the phrase **declared source dependency closure** in reader-facing
  material. Do not claim a sandbox, complete runtime dependency proof, process
  isolation, runtime import hook, or coverage of test/subprocess source.
- Do not run `validate-implementation`, Phase 0, Phase 1, the feature oracle,
  Phase 2, finalization, or study verification as part of implementation.

No repository code, test, validation, implementation-validation, or study
command was run while drafting this handoff.

## Source Revision And Drift Check

| Identity | Value | Meaning |
| --- | --- | --- |
| Source revision | `8e4b3ff52461c907c728fb2eae6660dafba7c53a` | Exact tracked source and four-finding review target |
| Source tree | `1fa91aa8206122b5d75038276e2ec1926a6b72dc` | Git tree at the source revision |
| Evidence collection SHA-256 | `7394cd37a067a25a87dd5c41a64ee52bcfdd4ed210d3516fcd763d4854dc0619` | Integrity identity recorded by the hardening portfolio |
| Design commit | `aaf425bababa2d0034f4ebcb66aba321ca1901de` | Approved specification and hardening portfolio |
| Approved specification blob | `de7f65eb7e2d7e41896fa88014811da755eb592d` | Exact written specification after its approval/plan-status update |
| Plan-authoring state | Clean at the design commit | Observed with read-only Git inspection |

At plan authoring, the diff from the source revision to the design commit adds
only documentation. There is no change under `src/`, `tests/`, `configs/`,
`schemas/`, `Makefile`, or `pyproject.toml`; the implementation boundary is
therefore unchanged from the reviewed source.

Before the first production edit, run these read-only checks in the isolated
implementation worktree:

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git merge-base --is-ancestor aaf425bababa2d0034f4ebcb66aba321ca1901de HEAD
git hash-object docs/superpowers/specs/2026-08-07-e1-declared-source-dependency-closure-hardening-design.md
git diff --name-only 8e4b3ff52461c907c728fb2eae6660dafba7c53a..HEAD -- src tests configs schemas Makefile pyproject.toml
git status --short
```

Expected before implementation: repository identity is
`manufacturing-vision-studio`; the design commit is an ancestor; the
source/test/config/schema diff command prints nothing; the approved design is
the exact approved specification blob is
`de7f65eb7e2d7e41896fa88014811da755eb592d`; and the worktree is clean. If a
relevant source boundary has drifted,
stop and return to design review instead of adapting this plan silently.

After implementation begins, only changes named under **Affected Components**
are plan-scoped. Any new production module would alter the frozen 47-path
projection and is not authorized; keep the capability implementation inside
the existing retention module.

## Affected Components

| Path | Responsibility | Planned effect |
| --- | --- | --- |
| `src/manufacturing_vision_studio/e1/study_retention_v2.py` | Single-read projection, AST extraction, graph and dependency policy | Introduce lexical capability values/frames, positive policy, exact initializer validation, stable rejection categories; preserve byte snapshot and graph contracts |
| `src/manufacturing_vision_studio/e1/study_runner_v2.py` | Artifact-state truth and verification report | Centralize `report.md -> decision.json` invalidity propagation before every invalid-state return |
| `src/manufacturing_vision_studio/e1/study_protocol_v2.py` | Frozen protocol and snapshot validation | Compare the two complete ordered snapshot identity tuples before bounded byte reads |
| `src/manufacturing_vision_studio/e1/study_cli_v2.py` | Fixed command dispatch and process status | Keep JSON output; return `1` only when `verify` returns `study_valid=false` |
| `src/manufacturing_vision_studio/e1/metrics.py` | Finite metric field grouping | Replace two variable-name `getattr` calls with explicit literal field dispatch if the positive grammar cannot prove them safely |
| `docs/evaluation/e1-feasibility-study.md` | Operator-facing assurance and CLI contract | Define the bounded declared-source claim and invalid verify process status |
| `tests/test_e1_study_dependency_guard_v2.py` | Projection, graph and malicious-source fixtures | Add capability, lexical-scope, exact-byte, safe-form, and exact-initializer matrices |
| `tests/test_study_package_import_closure.py` | Public lazy export/import compatibility | Preserve identity, caching and import-order behavior for both exact initializers |
| `tests/test_e1_study_runner_v2.py` | Artifact state and terminal decision behavior | Regress malformed decision plus present report and valid sealed `STUDY_INVALID` |
| `tests/test_e1_feasibility_protocol_v2.py` | Frozen protocol mutations and byte bounds | Regress both exact snapshot paths and retain oversized-input reachability |
| `tests/test_e1_study_cli_v2.py` | CLI dispatch/output/status contract | Regress invalid verify `1`, valid `PENDING` zero, and unchanged other commands |
| `tests/test_e1_metrics.py` | Metric slice compatibility | Prove explicit field dispatch preserves slice results if that refactor is used |

The two initializer sources are compatibility anchors, not planned edits. The
implementation validates their current structure. Do not change
`configs/evaluation/e1-feasibility-study.v1.json`, a schema, `Makefile`,
`pyproject.toml`, a result artifact, a review ledger, or any file under
`docs/superpowers/`.

## Ordered Work Packages

### Work Package 1: Close Decision-To-Report Verification Dependencies

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_runner_v2.py:261-272,310-490,1115-1177,1248-1269`
- Test: `tests/test_e1_study_runner_v2.py`

**Interfaces:**

- Consumes: `VerifiedStudyState`, `_invalid_state(...)`, the existing ordered
  `present_paths`, and `invalid_paths`.
- Produces:
  `_closed_invalid_paths(present_paths: tuple[str, ...], invalid_paths: tuple[str, ...]) -> tuple[str, ...]`.
  `_invalid_state(...)` must call it exactly once before constructing
  `VerifiedStudyState`.

- [ ] **Step 1: Write the malformed-decision RED regression.** Add
  `test_malformed_decision_invalidates_present_report` using the existing
  semantic-packet fixture: publish a decision/report pair, replace only the
  decision bytes with malformed JSON, call `runner.verify()`, and assert
  `study_valid is False`, both paths are absent from `verified_paths`, and the
  rate excludes both.

```python
state = runner_module.inspect_state(runner.protocol, repo_root=tmp_path)
report = runner.verify()
assert report.status.study_valid is False
assert "decision.json" not in report.verified_paths
assert "report.md" not in report.verified_paths
assert report.verify_rate == len(report.verified_paths) / len(state.present_paths)
```

- [ ] **Step 2: Run the single regression and confirm RED.**

```bash
uv run pytest tests/test_e1_study_runner_v2.py::test_malformed_decision_invalidates_present_report -q
```

Expected: FAIL because `report.md` is still counted as verified.

- [ ] **Step 3: Implement centralized dependency closure.** Add this helper
  beside `_invalid_state` and apply it inside `_invalid_state`:

```python
def _closed_invalid_paths(
    present_paths: tuple[str, ...],
    invalid_paths: tuple[str, ...],
) -> tuple[str, ...]:
    present = set(present_paths)
    invalid = set(invalid_paths)
    if "report.md" in present and (
        "decision.json" not in present or "decision.json" in invalid
    ):
        invalid.add("report.md")
    return tuple(path for path in present_paths if path in invalid)
```

Keep `_verify_invalid_terminal_projection` responsible for proving a valid
sealed `STUDY_INVALID` decision/report pair; do not mark that pair invalid when
the decision itself is valid.

- [ ] **Step 4: Run focused state tests.**

```bash
uv run pytest tests/test_e1_study_runner_v2.py -q
```

Expected: PASS, including the existing test that keeps a sealed invalid-study
decision and matching report verifiable.

- [ ] **Step 5: Commit the independently reviewable fix.**

```bash
git add src/manufacturing_vision_studio/e1/study_runner_v2.py tests/test_e1_study_runner_v2.py
git commit -m "fix(e1): propagate decision invalidity to reports"
```

### Work Package 2: Bind Exact Negative-Snapshot Identity

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_protocol_v2.py:28-106,405-433`
- Test: `tests/test_e1_feasibility_protocol_v2.py:515-534`

**Interfaces:**

- Consumes: the canonical snapshot values already present in
  `configs/evaluation/e1-feasibility-study.v1.json`.
- Produces: `_EXPECTED_NEGATIVE_RESULT_SNAPSHOTS`, an ordered tuple of
  `(name, checked_in_path, original_sibling_path, raw_sha256)` values used by
  `_validate_snapshots` before file access.

- [ ] **Step 1: Write two path-only RED regressions.** Add
  `test_protocol_rejects_checked_in_snapshot_path_alias` and
  `test_protocol_rejects_original_snapshot_path_alias`. Preserve each entry's
  name and hash; change only one path; assert `StudyProtocolError` contains
  `snapshot identity`.

```python
snapshots = cast(list[dict[str, str]], document["negative_result_snapshots"])
canonical_path = STUDY_PROJECT_ROOT / snapshots[0]["checked_in_path"]
alias_path = fixture_dir / "task4-report-alias.raw.txt"
alias_path.write_bytes(canonical_path.read_bytes())
snapshots[0]["checked_in_path"] = alias_path.relative_to(
    STUDY_PROJECT_ROOT
).as_posix()
config_path.write_text(json.dumps(document))
with pytest.raises(StudyProtocolError, match="snapshot identity"):
    load_study_protocol_v2(config_path)
```

This alias has the canonical bytes and therefore the canonical hash, so the
current implementation accepts it. The original-path case changes only that
field to a different absolute string with the same currently accepted prefix;
it must still reject before opening the checked-in file.

- [ ] **Step 2: Run both regressions and confirm RED.**

```bash
uv run pytest tests/test_e1_feasibility_protocol_v2.py -k 'snapshot_path_alias' -q
```

Expected: both cases FAIL because current validation accepts path drift.

- [ ] **Step 3: Freeze and compare the complete tuples.** Define the two exact
  tuples beside the other `_EXPECTED_*` constants. In `_validate_snapshots`,
  build the ordered actual tuple from all four fields, compare it to the frozen
  tuple, then perform the existing bounded read and SHA-256 check. Retain the
  duplicate/name/coverage failures as stable fail-closed errors.

- [ ] **Step 4: Refactor the oversized snapshot test without weakening exact
  identity.** Keep the canonical checked-in path in the copied document and
  monkeypatch `_read_bounded_bytes` so that the canonical snapshot read raises
  the same size-bound `StudyProtocolError`. The test must reach the bounded-read
  branch only after exact tuple validation succeeds.

- [ ] **Step 5: Run the protocol module.**

```bash
uv run pytest tests/test_e1_feasibility_protocol_v2.py -q
```

Expected: PASS; no config, schema, hash, or evidence bytes change.

- [ ] **Step 6: Commit the independently reviewable fix.**

```bash
git add src/manufacturing_vision_studio/e1/study_protocol_v2.py tests/test_e1_feasibility_protocol_v2.py
git commit -m "fix(e1): bind exact negative snapshot paths"
```

### Work Package 3: Map Invalid Verification To Process Failure

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_cli_v2.py:29-67`
- Test: `tests/test_e1_study_cli_v2.py`

**Interfaces:**

- Consumes: `StudyVerificationReport.status.study_valid` returned by
  `StudyRunner.verify()`.
- Produces: JSON output followed by exit `1` for only the `verify` command when
  `study_valid` is false; valid `PENDING`, valid terminal reports, and all
  other successful commands remain zero.

- [ ] **Step 1: Write RED status tests.** Add
  `test_verify_returns_one_after_printing_invalid_report` and
  `test_verify_returns_zero_for_valid_pending_report`. Construct exact
  `StudyVerificationReport`/`StudyStatus` values rather than generic mappings,
  patch `StudyRunner.from_default`, and assert parsed stdout plus empty stderr.
  Update the existing parametrized dispatch fixture so its `verify` branch
  also returns a real `StudyVerificationReport`; retain all eight commands and
  its construction, call-count, JSON, and zero-status assertions.

```python
invalid = StudyVerificationReport(
    (),
    0.0,
    StudyStatus(False, False, False, False, False, "STUDY_INVALID", ("X",)),
)
assert main(["verify"]) == 1
assert json.loads(capsys.readouterr().out)["result"]["status"]["study_valid"] is False
```

- [ ] **Step 2: Run both tests and confirm the invalid case is RED.**

```bash
uv run pytest tests/test_e1_study_cli_v2.py -k 'verify_returns' -q
```

Expected: invalid report test FAILS with observed exit zero; pending test
passes.

- [ ] **Step 3: Add command-specific status mapping after JSON output.**

```python
print(json.dumps(output, ensure_ascii=False, indent=2))
if command == "verify":
    report = cast(study_runner_v2.StudyVerificationReport, result)
    if not report.status.study_valid:
        return _OPERATIONAL_ERROR
return 0
```

Do not raise for domain invalidity, suppress JSON, change exception handling,
or alter another command's success semantics.

- [ ] **Step 4: Run CLI tests.**

```bash
uv run pytest tests/test_e1_study_cli_v2.py -q
```

Expected: PASS, including override rejection, parse status `2`, operational
status `1`, and exact entry-point/Makefile contracts.

- [ ] **Step 5: Commit the independently reviewable fix.**

```bash
git add src/manufacturing_vision_studio/e1/study_cli_v2.py tests/test_e1_study_cli_v2.py
git commit -m "fix(e1): fail invalid study verification commands"
```

### Work Package 4: Introduce Lexical Capability Provenance

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:46-48,542-983,1623-1716`
- Test: `tests/test_e1_study_dependency_guard_v2.py:604-968`

**Interfaces:**

- Consumes: one `ast.Module` parsed from `projection_payloads[relative]`, the
  source module/path, and the existing known projected modules.
- Produces: capability-aware references and stable errors while retaining
  `DependencyScanReport` and serialized fields unchanged.

- [ ] **Step 1: Add the RED capability matrix.** Add one parametrized test per
  capability family with these exact rejected source forms:

| Family | Mandatory source forms |
| --- | --- |
| Builtin loader | `vars(builtins)["__import__"]`, `vars(__builtins__)["__import__"]`, `getattr(builtins, name)`, `object.__getattribute__(builtins, "__dict__")` |
| Loader modules | `importlib.import_module`, reflected/aliased loader, `runpy.run_module`, `pkgutil.resolve_name`, `zipimport.zipimporter` |
| Executable code | unshadowed `exec`, `eval`, and `compile` acquisition or call |
| Namespace access | `vars`, `globals`, `locals`, `__dict__`, `__globals__`, frame globals/builtins, `sys.modules`, `sys.meta_path`, `sys.path_hooks`, `sys.path_importer_cache` |
| Operator reflection | `operator.attrgetter("__import__")(builtins)` and `operator.methodcaller("__getattribute__", "__dict__")(builtins)` |

Each fixture must expect a stable category containing its module, line, and one
of `dynamic-import`, `executable-code`, `namespace-reflection`,
`import-registry`, or `package-object`—not a spelling-specific internal helper
name.

- [ ] **Step 2: Add lexical propagation RED cases.** Cover capability values in
  plain/annotated/destructuring/walrus assignment, function defaults and
  arguments, return and call arguments, closure capture, lambdas,
  comprehensions, loop/with/exception/match targets, `global`, `nonlocal`, and
  an uncertain branch. Add benign rebinding and exact unshadowed
  `typing.TYPE_CHECKING` positive controls; shadowed or branch-ambiguous guards
  must be treated as runtime.

- [ ] **Step 3: Run the new negative slice and confirm RED.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py -k 'capability or lexical_scope or vars_builtin' -q
```

Expected: the new forms expose missing or unstable capability handling.

- [ ] **Step 4: Define the abstract value and frame model inside the existing
  retention module.** Do not add a production file. Use these exact internal
  shapes:

```python
_Capability = Literal[
    "builtins-namespace",
    "dynamic-loader-module",
    "executable-code",
    "import-loader",
    "import-namespace",
    "import-registry",
    "namespace-mapping",
    "namespace-reflection",
    "package-object",
    "sys-module",
    "type-checking-sentinel",
    "typing-module",
]
_ScopeKind = Literal["module", "class", "function", "lambda", "comprehension"]

@dataclass(frozen=True, slots=True)
class _Binding:
    capabilities: frozenset[_Capability] = frozenset()
    package_target: str | None = None
    uncertain: bool = False

    def merged(self, other: _Binding) -> _Binding:
        package_target = (
            self.package_target
            if self.package_target == other.package_target
            else None
        )
        return _Binding(
            capabilities=self.capabilities | other.capabilities,
            package_target=package_target,
            uncertain=(
                self.uncertain
                or other.uncertain
                or self.package_target != other.package_target
            ),
        )

@dataclass(slots=True)
class _ScopeFrame:
    kind: _ScopeKind
    bindings: dict[str, _Binding]
    global_names: set[str]
    nonlocal_names: set[str]
```

Use one source-policy visitor as the control owner. RHS analysis happens before
target binding. A provably benign literal/value may clear a local capability;
an unknown value joins with prior provenance rather than silently clearing it.
Branch joins union possible provenance. Resolve `global` and `nonlocal` to the
correct frame.

- [ ] **Step 5: Cover every approved binding construct.** Implement explicit
  visitors for modules, classes, sync/async functions, lambdas,
  comprehensions, imports, arguments/defaults, `Assign`, `AnnAssign`,
  `AugAssign`, destructuring, named expressions, loops, `with`, exceptions,
  match patterns, `global`, and `nonlocal`. Continue collecting the current
  graph references, protected-scope references, and forbidden calls.

- [ ] **Step 6: Recognize capability acquisition semantically.** Resolve
  unshadowed builtin names, literal/attribute/call/subscript forms, and tracked
  aliases into `_Binding`. Map every rejection to a stable capability
  family. String constants, malicious fixture text, helper names inside the
  scanner, and `re.compile` remain data, not executable capability use.

- [ ] **Step 7: Keep tactical spelling recognizers until the new matrix is
  green.** Do not remove existing direct-import, `__import__`, package-object,
  runpy, `exec`/`eval`, or forbidden-call checks in this package. If both old
  and new paths reject, normalize to one stable error rather than weakening
  either path.

- [ ] **Step 8: Run the dependency module and static checks.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py
uv run mypy src
```

Expected: PASS with no change to `DependencyScanReport` fields or direct
allowlist results.

- [ ] **Step 9: Commit the provenance engine.**

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py
git commit -m "refactor(e1): model source capability provenance"
```

### Work Package 5: Enforce Exact Initializers And Finite Safe Reflection

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:1002-1200,1661-1739`
- Modify only if needed for explicit dispatch: `src/manufacturing_vision_studio/e1/metrics.py:452-489`
- Test: `tests/test_e1_study_dependency_guard_v2.py`
- Test: `tests/test_study_package_import_closure.py`
- Test only if metrics changes: `tests/test_e1_metrics.py`
- Inspect without editing: `src/manufacturing_vision_studio/__init__.py`, `src/manufacturing_vision_studio/e1/__init__.py`

**Interfaces:**

- Produces:
  `_InitializerPolicy(allowed_node_ids: frozenset[int], lazy_targets: tuple[tuple[str, str, str], ...])`
  for only two exact paths, and finite ordinary-object reflection decisions.
- Preserves: public lazy export identity/caching, current graph report shape,
  and explicit submodule imports for study-owned source.

- [ ] **Step 1: Add exact-initializer RED mutations.** For each initializer path,
  mutate exactly one property at a time: alias the import, add a second import,
  make `_LAZY_EXPORTS` nonliteral, point a target outside the projection, wrap
  or alias `import_module`, add a keyword/second call, capture or return the
  loader, add another `globals()`/namespace use, or move the same source to a
  third path. Every mutation must reject; the two unchanged real initializers
  must pass.

- [ ] **Step 2: Add ordinary safe-form positives.** Cover literal non-sensitive
  `getattr`/`hasattr` used for OS flags, Pillow `n_frames`, the mask method
  probe, fixed runner result fields, and the exact dataclass serialization form
  in `study_cli_v2._json_value`. The dependency-guard fixture must opt out of
  `SYNTHETIC_CLI` for this case so the unchanged real serializer is actually
  scanned, followed by a one-node computed-name mutation that must reject. A
  nonliteral attribute on a capability-bearing object remains rejected.

- [ ] **Step 3: Run the initializer/safe-form slice and confirm RED where the
  current exception is too broad.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py -k 'pep562 or initializer or safe_object' -q
```

- [ ] **Step 4: Pre-validate the two exact initializer ASTs.** Pass the
  repository-relative source path into the visitor. Before general traversal,
  validate exactly one unaliased module-level
  `from importlib import import_module`, a literal `_LAZY_EXPORTS` mapping with
  projected module targets, one direct loader call in module-level
  `__getattr__`, the exact cache write, and the exact `__dir__` globals use.
  Preserve the other imports already present in those initializers under the
  ordinary graph and `TYPE_CHECKING` rules. Return allowed node identities and
  latent targets. Visit children normally; exempt only the recorded node
  identities, never a whole subtree or function name.

- [ ] **Step 5: Implement finite safe ordinary-object forms.** Direct builtin
  `getattr`/`hasattr` requires a literal non-sensitive attribute unless it is
  the exact dataclass field-comprehension structure. Prove that structure from
  the `is_dataclass(value)` guard, `fields(value)` iterator, same `value`
  object, `field.name`, and private-field filter. Reject computed names on
  capability-bearing values.

- [ ] **Step 6: Replace metric variable reflection if positive proof would
  broaden the grammar.** Use explicit field dispatch, preserving the existing
  `Literal` parameter API:

```python
if attribute == "severity":
    key = item.severity
else:
    key = item.defect_type
```

Use the analogous `cad_revision`/`view_id` branch in `_accuracy_slices`. Add
metric tests proving the output dictionaries are unchanged. Do not add a
general annotation evaluator solely for these two call sites.

- [ ] **Step 7: Remove superseded spelling state only after equivalent coverage
  is green.** Delete alias sets/helpers whose only purpose is now owned by the
  capability values. Retain graph resolution, forbidden prefixes/calls,
  protected scopes, cycles, and direct allowlist equality.

- [ ] **Step 8: Run compatibility and closure tests.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py tests/test_study_package_import_closure.py tests/test_e1_metrics.py -q
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py src/manufacturing_vision_studio/e1/metrics.py tests/test_e1_study_dependency_guard_v2.py tests/test_study_package_import_closure.py tests/test_e1_metrics.py
uv run mypy src
```

Expected: the real 47-path checkout passes, both lazy APIs preserve identity
and caching, every prohibited family rejects, and metric slices remain equal.

- [ ] **Step 9: Preserve the two canonical review boundaries.** Execute the
  canonical plan's initializer task and positive-capability task separately,
  including each task's RED/GREEN, commit, and review gate. Do not collapse
  path/node initializer exceptions and the general grammar into one commit. If
  `metrics.py` and `test_e1_metrics.py` remain unchanged, omit them from the
  capability commit; do not create a no-op diff.

### Work Package 6: Align The Bounded Claim And Operator Contract

**Files:**

- Modify: `docs/evaluation/e1-feasibility-study.md`
- Verify: `docs/security/hardening/2026-08-07-e1-declared-source-dependency-closure/proposals/declarative-dependency-closure.md`

**Interfaces:**

- Produces: operator language consistent with the approved bounded assurance
  claim and CLI exit behavior; no schema or record rename.

- [ ] **Step 1: Update the dependency claim.** State that exact projected bytes
  are hashed and statically checked for declared source dependencies and
  prohibited capability syntax. Explicitly exclude complete runtime proof,
  descriptors, callbacks, extensions, environment effects, subprocess source,
  and sandboxing.

- [ ] **Step 2: Update verify semantics.** State that JSON is always printed for
  a returned report; `study_valid=false` yields status `1`; valid `PENDING` and
  valid terminal reports yield zero; operational exceptions keep the existing
  error path.

- [ ] **Step 3: Check claim vocabulary.**

```bash
rg -n "sandbox|runtime dependency proof|declared source dependency closure|study_valid" docs/evaluation/e1-feasibility-study.md docs/security/hardening/2026-08-07-e1-declared-source-dependency-closure
```

Expected: every sandbox reference is a non-claim; no text calls the result a
complete runtime dependency proof.

- [ ] **Step 4: Commit documentation.**

```bash
git add docs/evaluation/e1-feasibility-study.md
git commit -m "docs(e1): define declared source closure assurance"
```

### Work Package 7: Validate And Obtain Fresh Reviews

**Files:**

- No planned source edit; repair only within the file ownership above if a
  check finds a defect.
- Do not create or modify study-result artifacts.

**Interfaces:**

- Consumes: all prior work packages at one clean implementation commit.
- Produces: focused/full validation receipts, bounded-complexity review, and
  four fresh reviews. It does not produce
  `implementation-validation.json`.

- [ ] **Step 1: Run the focused five-boundary suite.**

```bash
uv run pytest tests/test_e1_study_dependency_guard_v2.py tests/test_study_package_import_closure.py tests/test_e1_study_runner_v2.py tests/test_e1_feasibility_protocol_v2.py tests/test_e1_study_cli_v2.py -q
```

Expected: PASS; no study result root is created.

- [ ] **Step 2: Run the plan-exact ten-module suite.**

```bash
uv run pytest tests/test_e1_feasibility_protocol_v2.py tests/test_e1_known_transform_v2.py tests/test_e1_study_inference_v2.py tests/test_e1_study_parity_v2.py tests/test_e1_study_truth_v2.py tests/test_e1_study_artifacts_v2.py tests/test_e1_study_retention_v2.py tests/test_e1_study_runner_v2.py tests/test_e1_study_cli_v2.py tests/test_e1_study_dependency_guard_v2.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full repository validation.**

```bash
make validate
git diff --check
```

Expected: Ruff, Mypy, Python tests, web checks, and Playwright all pass. Normal
validation must not execute Phase 0, Phase 1, the oracle, or Phase 2.

- [ ] **Step 4: Review the approved performance and resource boundary.** Confirm
  from the candidate diff that each captured module is parsed once, traversed
  once by the capability policy, and represented only by transient lexical
  frames and bounded branch joins. The focused suites and `make validate` must
  complete within their existing fixed timeouts with no resource failure. Do
  not run a standalone benchmark, invent a numeric latency or memory budget,
  or present validation completion as benchmark evidence.

- [ ] **Step 5: Obtain four independent final reviews over the whole range.**
  Request state, truth-boundary, evidence, and integration reviews from source
  revision `8e4b3ff…` through the candidate. Resolve every P0-P2 finding, rerun
  Steps 1-4 after an edit, and record each approval.

- [ ] **Step 6: Prove the pre-implementation-validation state.**

```bash
git status --short
git rev-parse HEAD
test ! -e docs/evaluation/results/e1-feasibility-study/implementation-validation.json
test ! -e docs/evaluation/results/e1-feasibility-study/phase-1-execution-claim.json
test ! -e docs/evaluation/results/e1-feasibility-study/phase-2-execution-claim.json
```

Expected: clean candidate commit, no implementation-validation artifact, and
no phase claim. Stop here. `make validate-e1-study-implementation` and every
study command remain later, separately authorized gates.

## Compatibility And Migration

The migration is source-only and pre-execution. Existing result schemas,
serialized dependency fields, protocol paths, direct allowlists, frozen
configuration, and lazy public exports remain compatible. We expect the
implementation projection hash to change because reviewed production source
changes; we do not change which 47 paths belong to the projection.

Compatibility is explicit at four seams:

- The root and E1 package initializers retain import identity, lazy loading,
  caching in `globals()`, `__all__`, and `__dir__` behavior.
- Literal OS/Pillow/application field access and the dataclass serialization
  form remain accepted. Variable metric field selection uses explicit dispatch
  instead of broad reflective authority if necessary.
- A correctly sealed `STUDY_INVALID` decision and matching report remain
  verifiable even though the CLI returns `1` for the invalid domain result.
- Valid `PENDING` verification remains a successful observational command; no
  final-only requirement is introduced.

No dual-read or dual-policy rollout is needed. We keep the current tactical
recognizers during development, switch control ownership only when the positive
matrix and real projection pass, and remove obsolete matcher state in the same
reviewed package. Any newly legitimate dynamic Python requires a new design
review, a narrow exact exception, or a non-reflective refactor—not silent
relaxation.

## Tactical Protections During Migration

- Preserve the current exact-byte read/hash/parse snapshot test throughout.
- Keep every existing negative loader/reflection fixture until the positive
  grammar covers its capability family; never replace a strong test with only
  a new diagnostic string.
- Keep direct import allowlists, forbidden runtime prefixes, protected scopes,
  forbidden calls, runtime-cycle rejection, and unprojected-edge rejection.
- Keep the exact `vars(builtins)["__import__"]` and
  `vars(__builtins__)["__import__"]` regressions permanently.
- Route all invalid-state construction through centralized report dependency
  propagation; do not repair malformed evidence or remove a present artifact.
- Compare exact snapshot tuples before any byte read; retain bounded reads and
  hashes after identity passes.
- Print the structured verify report before mapping its domain validity to
  process status; preserve parse and operational error codes.
- Do not modify or generate frozen config, schema, source evidence, result
  artifacts, review ledgers, or study execution claims.

## Tests And Security Validation

The security matrix is complete only when it contains both negative capability
families and positive compatibility cases. At minimum it must prove:

- static imports are projected and allowlisted; wildcard, package-object,
  unprojected, forbidden, and runtime cyclic edges reject;
- exact unshadowed `typing.TYPE_CHECKING` remains type-only while shadowed or
  ambiguous forms are runtime;
- importlib/builtin/runpy/pkgutil/zipimport loaders, executable-code builtins,
  namespace mappings, frames, import registries, operator reflection, and
  computed sensitive names reject across all approved lexical binding forms;
- two exact PEP 562 structures pass and every structural deviation rejects;
- safe literal object inspection, dataclass fields, OS flags, Pillow frame
  checks, and explicit metric field dispatch pass;
- projection hashing and AST parsing use the same captured bytes during a
  post-read path swap;
- malformed decision JSON invalidates a present report without breaking a
  valid sealed invalid-study pair;
- both snapshot paths and bytes are frozen;
- invalid verify returns `1` after JSON, valid `PENDING` returns zero, and other
  command statuses remain unchanged.

Run RED cases individually before implementation, the owning module after each
work package, the five-boundary suite after integration, the exact ten-module
suite, then `make validate`. A green test suite is necessary but does not
authorize implementation validation or a study phase.

## Performance And Resource Benchmarks

The expected mechanism is one richer AST traversal with transient lexical
frames and branch unions over the already bounded 47-path projection. There is
no new runtime process, service, network hop, persistent cache, queue, or
application hot-path work.

The approved design deliberately supplies no standalone latency or memory
benchmark. Its workload is the exact projected-source scanner exercised by the
focused dependency tests and the repository's normal `make validate` target;
its acceptance threshold is completion within those commands' existing fixed
timeouts without a resource failure. Diff review additionally proves one parse
and one policy traversal per captured module, bounded lexical frames and branch
joins, no path enumeration, and no persistent cache. These are validation and
complexity receipts, not benchmark data.

If focused or full validation breaches its existing timeout or fails for
resource use, inspect duplicate AST walks or unbounded frame retention and
optimize without reopening source files or adding a persistent cache. If the
cost cannot be made proportionate, stop and return to design review; do not
fall back silently to spelling patches or add a new numeric gate without
separate approval.

## Rollout And Rollback

Roll out as the seven small commits in the canonical execution plan: three
direct fixes, lexical bindings, exact initializer policy, positive capability
grammar, and bounded-claim documentation. This handoff aggregates the last two
scanner boundaries under Work Package 5, but implementation keeps them as
separate commits so reviewers can isolate path/node exceptions from the general
capability grammar. A clean validation/review candidate follows those commits.

Before implementation validation or any study artifact exists, rollback is a
normal revert of the affected commits, followed by the focused and full
validation suites. Do not selectively revert the known `vars(builtins)`
regression or the three direct truth/operability fixes.

After implementation validation or a study artifact exists, rollback cannot
preserve the old evidence binding. Treat generated validation and study
artifacts as invalid, restore an absent result root through the separately
approved evidence procedure, freeze a new projection at a reviewed clean
commit, and restart the later execution gate. This plan does not authorize that
cleanup or rerun.

## Acceptance Criteria

- Source revision `8e4b3ff…`, design commit `aaf425b…`, and evidence collection
  SHA-256 remain traceable in the implementation handoff; relevant pre-edit
  drift is absent or returned to design review.
- The known reflected-import bypass and the complete capability-family/lexical
  matrix fail closed with stable module, line, and family diagnostics.
- The two exact PEP 562 initializers and public package import-closure tests
  pass without broad loader or namespace exemptions.
- Each projected source path is read once; projection hashing and AST policy use
  the same payload.
- Declared project dependencies remain projected, allowlisted, cycle-free, and
  free of forbidden reachability; serialized fields are unchanged.
- Ordinary safe object operations and metric results remain compatible.
- Malformed decisions cannot confer verification credit on reports; a valid
  sealed `STUDY_INVALID` pair remains verifiable.
- Both negative-snapshot paths and bytes are exactly frozen without config,
  schema, or evidence-byte changes.
- Invalid verification prints JSON and returns `1`; valid `PENDING` and valid
  terminal reports return zero; exceptions preserve the operational path.
- Focused five-boundary tests, the exact ten-module suite, Ruff, Mypy, full
  Python tests, web checks, and Playwright pass.
- Focused and full validation complete within their existing fixed timeouts,
  and review confirms the bounded traversal/resource model without an
  unapproved benchmark claim.
- Four fresh state, truth-boundary, evidence, and integration reviews approve
  the entire source-to-candidate range with no P0-P2 finding open.
- Documentation makes only the bounded declared-source dependency closure claim
  and retains local-demo, synthetic-data, and no-real-manufacturing limits.
- The candidate is clean and no implementation-validation or phase artifact
  exists. Passing this plan does not authorize a study phase.

## Open Decisions

- Obtain explicit user authorization for one execution mode under the reviewed
  plan: subagent-driven execution is recommended; inline execution is the
  alternative.
- Keep any tighter numeric scan-time or peak-memory budget deferred. Adding one
  requires a separately reviewed design update; until then, use only the
  existing validation-runtime and bounded-complexity gate above.
- Keep runtime bootstrap deferred as a separate defense-in-depth design unless
  exercised import enforcement becomes a new requirement.
- If the finite safe grammar rejects a legitimate future dynamic behavior,
  return to design review for a narrow exception or refactor; do not expand the
  approved capability surface during implementation.
