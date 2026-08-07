# E1 Declared Source Dependency Closure Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the recurring dynamic-import spelling patches with a fail-closed declared-source capability grammar and close the three remaining artifact-truth and CLI verification defects before any one-time E1 study command runs.

**Architecture:** Preserve the existing single bounded read whose bytes are both hashed and parsed, then make dependency-sensitive capabilities explicit through lexical bindings, exact PEP 562 initializer policies, and a finite source grammar in `study_retention_v2.py`. Independently centralize `report.md -> decision.json` invalidity propagation, freeze the complete negative-snapshot identity tuples, and map an invalid verification report to CLI exit status `1` after JSON output.

**Tech Stack:** Python 3.11+, `ast`, immutable dataclasses and mappings, pytest 8+, Ruff, Mypy, JSON Schema, Git, Make, npm/web validation, Playwright.

## Global Constraints

- Source behavior baseline: `8e4b3ff52461c907c728fb2eae6660dafba7c53a`.
- Approved written-design commit: `aaf425bababa2d0034f4ebcb66aba321ca1901de`.
- Approved written-specification blob (including current approval/plan status): `de7f65eb7e2d7e41896fa88014811da755eb592d`.
- Independent documentation review: PASS; no implementation task was executed during review.
- Execute only in `/Users/jangtaeho/manufacturing-vision-studio-e1-feasibility-separability` on branch `codex/e1-feasibility-separability-study`.
- Preserve `/Users/jangtaeho/manufacturing-vision-studio-e1-v2` unchanged and clean at `9fd6d0c600206083fde4fafc874e0226b5df60b3`.
- Do not create a new production module, dependency, schema version, config field, artifact record field, service, process boundary, or runtime import hook.
- This reviewed plan records executable steps but does not itself authorize production edits. Do not start Task 1 until this planning-doc commit exists and the user explicitly authorizes one execution mode.
- Keep all frozen gates, thresholds, seeds, matrix rows, paths, hashes, direct-import allowlists, artifact schemas, and public package behavior unchanged.
- The only claim is **declared source dependency closure** for the exact projected production bytes; never claim a Python sandbox or complete semantic runtime reachability.
- Tests and fixed validation subprocesses remain a separate audited trust domain and are not recursively subject to the production AST grammar.
- Every production change begins with a focused failing regression, reaches GREEN, passes scoped Ruff and `uv run mypy src`, and receives a fresh task review before the next task.
- The study result root `docs/evaluation/results/e1-feasibility-study` must remain absent throughout Tasks 1–7.
- Do not run `mvs-e1-study validate-implementation`, Phase 0, Phase 1, the feature oracle, Phase 2, `finalize`, Candidate A/B comparison, Candidate C, FreeCAD, remote push, PR, tag, or release.
- Scanner complexity is bounded to one parse and one policy traversal per captured module, one binding map per active lexical scope, and at most the pre-branch plus branch-result maps at a control-flow join; no path enumeration or persistent cache.
- Performance acceptance is the approved existing validation runtime: focused suites and `make validate` must complete within their existing fixed timeouts. Do not add a standalone benchmark, invent a numeric latency or memory budget, or present an unapproved measurement as benchmark evidence.

---

## File Structure

No new production file is created because an added module would alter the
frozen implementation projection. Responsibilities remain:

- `src/manufacturing_vision_studio/e1/study_runner_v2.py`: artifact-state dependency closure and verification credit.
- `src/manufacturing_vision_studio/e1/study_protocol_v2.py`: exact frozen protocol identities and bounded input validation.
- `src/manufacturing_vision_studio/e1/study_cli_v2.py`: command dispatch, JSON serialization, and process status.
- `src/manufacturing_vision_studio/e1/study_retention_v2.py`: exact-byte projection, lexical source policy, declared dependency graph, and PEP 562 exception validation.
- `src/manufacturing_vision_studio/e1/metrics.py`: explicit finite field dispatch replacing runtime nonliteral reflection in the reachable metric layer.
- `src/manufacturing_vision_studio/__init__.py` and `src/manufacturing_vision_studio/e1/__init__.py`: unchanged lazy public API structures validated by the scanner.
- `tests/test_e1_study_runner_v2.py`: artifact dependency and terminal invalid-report regressions.
- `tests/test_e1_feasibility_protocol_v2.py`: exact snapshot tuple and bounded-read regressions.
- `tests/test_e1_study_cli_v2.py`: JSON plus process-exit contract.
- `tests/test_e1_study_dependency_guard_v2.py`: adversarial source grammar, lexical binding, projection, and exact initializer contracts.
- `tests/test_study_package_import_closure.py`: unchanged subprocess proof for public lazy import identity and caching.
- `tests/test_e1_metrics.py`: explicit metric slice field-dispatch parity.
- `docs/evaluation/e1-feasibility-study.md`: operator-facing declared-source and verify-exit semantics.

## Execution Preflight

Run these read-only commands immediately before Task 1:

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git merge-base --is-ancestor aaf425bababa2d0034f4ebcb66aba321ca1901de HEAD
git hash-object docs/superpowers/specs/2026-08-07-e1-declared-source-dependency-closure-hardening-design.md
git status --short
git diff --check
test ! -e docs/evaluation/results/e1-feasibility-study
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 rev-parse HEAD
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 status --short
```

Expected: correct root and branch, the approved design is an ancestor, the
specification blob is exactly `de7f65eb7e2d7e41896fa88014811da755eb592d`,
the active tree is clean after this planning-doc commit, the result root is
absent, and the preserved worktree is clean at exact
`9fd6d0c600206083fde4fafc874e0226b5df60b3`.

Blocking authorization gate: even when every preflight check passes, stop
unless the user has explicitly selected subagent-driven or inline execution
for this reviewed plan. Approval of the written specification alone is not
production-edit authorization.

### Task 1: Propagate artifact verification dependencies

**Files:**
- Modify: `src/manufacturing_vision_studio/e1/study_runner_v2.py:140-280,310-480,1115-1177,1248-1270`
- Test: `tests/test_e1_study_runner_v2.py:2115-2380,2680-2790`

**Interfaces:**
- Consumes: `VerifiedStudyState.present_paths`, `VerifiedStudyState.invalid_paths`, and the existing `_invalid_state(...)` construction path.
- Produces: `_closed_invalid_paths(present_paths: tuple[str, ...], invalid_paths: tuple[str, ...]) -> tuple[str, ...]`; every invalid state applies the fixed dependency `report.md -> decision.json` before `verified_paths` is derived.

- [ ] **Step 1: Add the malformed-decision RED regression**

Add this focused contract using the existing `_publish_semantic_packet` helper:

```python
def test_verify_does_not_credit_report_when_decision_json_is_malformed(
    tmp_path: Path,
) -> None:
    runner = _publish_semantic_packet(tmp_path)
    decision_path = runner.protocol.artifact_root / "decision.json"
    decision_path.write_bytes(b"{")

    state = runner_module.inspect_state(runner.protocol, repo_root=tmp_path)
    report = runner.verify()

    assert state.status.study_valid is False
    assert state.status.terminal_decision == "STUDY_INVALID"
    assert "decision.json" in state.invalid_paths
    assert "report.md" in state.invalid_paths
    assert "decision.json" not in state.verified_paths
    assert "report.md" not in state.verified_paths
    assert report.verified_paths == state.verified_paths
    assert report.verify_rate == len(state.verified_paths) / len(state.present_paths)
```

- [ ] **Step 2: Run the RED selector**

Run:

```bash
uv run pytest -q tests/test_e1_study_runner_v2.py::test_verify_does_not_credit_report_when_decision_json_is_malformed
```

Expected: FAIL because `report.md` is present but absent from `invalid_paths`,
so it receives false verification credit.

- [ ] **Step 3: Centralize invalid dependency closure**

Add the fixed relationship beside the artifact path constants and implement the
closure without special-casing only the JSON fast path:

```python
_ARTIFACT_VERIFICATION_DEPENDENCIES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"report.md": ("decision.json",)}
)


def _closed_invalid_paths(
    present_paths: tuple[str, ...],
    invalid_paths: tuple[str, ...],
) -> tuple[str, ...]:
    present = set(present_paths)
    invalid = set(invalid_paths)
    changed = True
    while changed:
        changed = False
        for dependent, requirements in _ARTIFACT_VERIFICATION_DEPENDENCIES.items():
            if dependent not in present or dependent in invalid:
                continue
            if any(requirement not in present or requirement in invalid for requirement in requirements):
                invalid.add(dependent)
                changed = True
    return tuple(path for path in present_paths if path in invalid)
```

Call `_closed_invalid_paths(...)` inside `_invalid_state(...)` immediately
before constructing `VerifiedStudyState`. Do not mark `decision.json` invalid
merely because an upstream study artifact is invalid: a correctly sealed
`STUDY_INVALID` decision and its deterministic report must remain verifiable
through `_verify_invalid_terminal_projection(...)`.

- [ ] **Step 4: Run GREEN and compatibility selectors**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_runner_v2.py::test_verify_does_not_credit_report_when_decision_json_is_malformed \
  tests/test_e1_study_runner_v2.py::test_finalize_seals_semantically_invalid_packet_with_honest_report
uv run pytest -q tests/test_e1_study_runner_v2.py
uv run ruff check src/manufacturing_vision_studio/e1/study_runner_v2.py tests/test_e1_study_runner_v2.py
uv run mypy src
```

Expected: all PASS; malformed decisions invalidate reports, while a valid
sealed `STUDY_INVALID` decision/report pair remains in `verified_paths`.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/manufacturing_vision_studio/e1/study_runner_v2.py tests/test_e1_study_runner_v2.py
git commit -m "fix(e1): propagate artifact verification dependencies"
```

- [ ] **Step 6: Obtain the Task 1 review gate**

Review exact `HEAD^..HEAD` for verification-credit truth, valid-invalid terminal
compatibility, ordering, and missing dependencies. Resolve every finding and
rerun Step 4 before Task 2.

### Task 2: Freeze complete negative-result snapshot identities

**Files:**
- Modify: `src/manufacturing_vision_studio/e1/study_protocol_v2.py:20-75,405-433`
- Test: `tests/test_e1_feasibility_protocol_v2.py:1-25,450-555`

**Interfaces:**
- Consumes: the already frozen `_EXPECTED_SOURCE_HASHES` and canonical entries in `configs/evaluation/e1-feasibility-study.v1.json`.
- Produces: `_EXPECTED_NEGATIVE_RESULT_SNAPSHOTS`, an ordered exact `(name, checked_in_path, original_sibling_path, raw_sha256)` identity; `_validate_snapshots(...)` compares all four fields before reading bytes.

- [ ] **Step 1: Add two exact-identity RED regressions**

Import the module as `protocol_module` for a later bounded-reader seam, then add:

```python
def test_protocol_rejects_negative_snapshot_original_path_drift(tmp_path: Path) -> None:
    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        snapshots = document["negative_result_snapshots"]
        assert isinstance(snapshots, list)
        snapshots[0]["original_sibling_path"] = (
            "/Users/jangtaeho/manufacturing-vision-studio-e1-v2/forged-report.md"
        )
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError, match="snapshot identity changed"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)


def test_protocol_rejects_negative_snapshot_checked_in_path_alias(tmp_path: Path) -> None:
    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    try:
        snapshots = document["negative_result_snapshots"]
        assert isinstance(snapshots, list)
        canonical = STUDY_PROJECT_ROOT / snapshots[0]["checked_in_path"]
        alias = fixture_dir / "byte-identical-report.raw.txt"
        alias.write_bytes(canonical.read_bytes())
        snapshots[0]["checked_in_path"] = alias.relative_to(STUDY_PROJECT_ROOT).as_posix()
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError, match="snapshot identity changed"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)
```

- [ ] **Step 2: Run both RED selectors**

Run:

```bash
uv run pytest -q \
  tests/test_e1_feasibility_protocol_v2.py::test_protocol_rejects_negative_snapshot_original_path_drift \
  tests/test_e1_feasibility_protocol_v2.py::test_protocol_rejects_negative_snapshot_checked_in_path_alias
```

Expected: both FAIL because the current validator accepts the broad sibling
prefix and a project-local byte-identical alias.

- [ ] **Step 3: Add the exact ordered identity constant**

Add this constant after `_EXPECTED_SOURCE_HASHES`:

```python
_EXPECTED_NEGATIVE_RESULT_SNAPSHOTS = (
    (
        "task4_report",
        "docs/evaluation/negative-results/e1-v2-task4-report.raw.txt",
        (
            "/Users/jangtaeho/manufacturing-vision-studio-e1-v2/"
            ".superpowers/sdd/2026-08-01-e1-v2-scale-feature-remediation/"
            "task-4-report.md"
        ),
        "b6a2093082aa63631adb233c282466539720281ab96b53bc3928cf292efc8835",
    ),
    (
        "task4_progress_ledger",
        "docs/evaluation/negative-results/e1-v2-task4-progress-ledger.raw.txt",
        (
            "/Users/jangtaeho/manufacturing-vision-studio-e1-v2/"
            ".superpowers/sdd/2026-08-01-e1-v2-scale-feature-remediation/progress.md"
        ),
        "fcef0c3b22b962f185911cc74bdad45f1bd2860c42ae8e59bac76d6741c13ea7",
    ),
)
```

In `_validate_snapshots(...)`, construct the actual ordered four-field tuples
from the two records and require exact equality with the constant before any
`_project_path(...)` or `_read_bounded_bytes(...)` call. Then retain the
existing `_EXPECTED_SOURCE_HASHES` equality, bounded read, and byte-hash
comparison so both identity registries stay mutually bound.

- [ ] **Step 4: Refactor the oversized snapshot test without identity drift**

Do not mutate `checked_in_path`. Redirect only the canonical snapshot read to a
temporary oversized file while retaining the real bounded reader:

```python
def test_protocol_loader_rejects_oversized_retained_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_dir, config_path, document = _project_local_protocol_copy(tmp_path)
    oversized = tmp_path / "oversized.raw.txt"
    oversized.write_bytes(b"x" * (MAX_STUDY_INPUT_BYTES + 1))
    snapshots = document["negative_result_snapshots"]
    assert isinstance(snapshots, list)
    canonical = STUDY_PROJECT_ROOT / snapshots[0]["checked_in_path"]
    original_reader = protocol_module._read_bounded_bytes

    def redirect(path: Path) -> bytes:
        return original_reader(oversized if path == canonical else path)

    monkeypatch.setattr(protocol_module, "_read_bounded_bytes", redirect)
    try:
        config_path.write_text(json.dumps(document))
        with pytest.raises(StudyProtocolError, match="exceeds"):
            load_study_protocol_v2(config_path)
    finally:
        shutil.rmtree(fixture_dir)
```

- [ ] **Step 5: Run GREEN, protocol coverage, and static checks**

Run:

```bash
uv run pytest -q \
  tests/test_e1_feasibility_protocol_v2.py::test_protocol_rejects_negative_snapshot_original_path_drift \
  tests/test_e1_feasibility_protocol_v2.py::test_protocol_rejects_negative_snapshot_checked_in_path_alias \
  tests/test_e1_feasibility_protocol_v2.py::test_protocol_loader_rejects_oversized_retained_snapshot
uv run pytest -q tests/test_e1_feasibility_protocol_v2.py
uv run ruff check src/manufacturing_vision_studio/e1/study_protocol_v2.py tests/test_e1_feasibility_protocol_v2.py
uv run mypy src
```

Expected: all PASS; the checked config bytes and schema version remain
unchanged.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/manufacturing_vision_studio/e1/study_protocol_v2.py tests/test_e1_feasibility_protocol_v2.py
git commit -m "fix(e1): freeze negative snapshot identities"
```

- [ ] **Step 7: Obtain the Task 2 review gate**

Review exact `HEAD^..HEAD` for identity-before-I/O ordering, byte-bound
preservation, canonical config compatibility, and tests that genuinely reach
each failure mode. Resolve every finding and rerun Step 5 before Task 3.

### Task 3: Make invalid CLI verification fail automation

**Files:**
- Modify: `src/manufacturing_vision_studio/e1/study_cli_v2.py:20-90`
- Test: `tests/test_e1_study_cli_v2.py:1-115`
- Modify: `docs/evaluation/e1-feasibility-study.md:28-42`

**Interfaces:**
- Consumes: `StudyRunner.verify() -> StudyVerificationReport` and `StudyVerificationReport.status.study_valid`.
- Produces: `_command_exit_code(command: str, result: object) -> int`; invalid verification prints normal JSON and returns `_OPERATIONAL_ERROR` (`1`), while valid `PENDING` and valid terminal reports return `0`.

- [ ] **Step 1: Add invalid and valid-PENDING CLI RED tests**

Import `StudyStatus` and `StudyVerificationReport`, add a small builder, and
assert both JSON and exit status:

```python
def _verification_report(*, study_valid: bool) -> StudyVerificationReport:
    decision = "PENDING" if study_valid else "STUDY_INVALID"
    reasons = () if study_valid else ("ARTIFACT_VERIFICATION_FAILED",)
    return StudyVerificationReport(
        verified_paths=(),
        verify_rate=0.0,
        status=StudyStatus(
            study_valid=study_valid,
            phase1_complete=False,
            feature_oracle_complete=False,
            phase2_authorized=False,
            phase2_complete=False,
            terminal_decision=decision,
            reasons=reasons,
        ),
    )


@pytest.mark.parametrize(("study_valid", "expected_exit"), ((False, 1), (True, 0)))
def test_cli_verify_exit_matches_domain_validity(
    study_valid: bool,
    expected_exit: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _verification_report(study_valid=study_valid)
    runner = SimpleNamespace(verify=lambda: report)
    monkeypatch.setattr(
        cli_module.study_runner_v2.StudyRunner,
        "from_default",
        lambda: runner,
    )

    assert main(["verify"]) == expected_exit
    output = json.loads(capsys.readouterr().out)
    assert output["result"]["status"]["study_valid"] is study_valid
```

Update `test_cli_dispatches_each_fixed_command_once` so its `verify` case
returns `_verification_report(study_valid=True)` and asserts the serialized
report rather than a generic mapping. Every other command keeps the current
generic mapping fixture.

- [ ] **Step 2: Run the RED test**

Run:

```bash
uv run pytest -q tests/test_e1_study_cli_v2.py::test_cli_verify_exit_matches_domain_validity
```

Expected: the invalid case FAILS with actual exit `0`; the valid `PENDING` case
passes.

- [ ] **Step 3: Map the verified domain result to process status**

Return the status after printing JSON:

```python
def _command_exit_code(command: str, result: object) -> int:
    if command != "verify":
        return 0
    report = cast(study_runner_v2.StudyVerificationReport, result)
    return 0 if report.status.study_valid else _OPERATIONAL_ERROR
```

Inside `main(...)`, replace the unconditional final `return 0` with
`return _command_exit_code(command, result)`. Keep parse exit `2` and exception
exit `1` unchanged. Do not raise for a domain-invalid report and do not move its
JSON to stderr.

Document that `make verify-e1-study` exits nonzero for
`study_valid=false`, while a valid read-only `PENDING` packet exits zero.

- [ ] **Step 4: Run GREEN and CLI compatibility coverage**

Run:

```bash
uv run pytest -q tests/test_e1_study_cli_v2.py
uv run ruff check src/manufacturing_vision_studio/e1/study_cli_v2.py tests/test_e1_study_cli_v2.py
uv run mypy src
```

Expected: all PASS; JSON output is retained for both validity values, generic
commands remain zero, parse errors remain `2`, and operational exceptions
remain `1`.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/manufacturing_vision_studio/e1/study_cli_v2.py tests/test_e1_study_cli_v2.py docs/evaluation/e1-feasibility-study.md
git commit -m "fix(e1): fail invalid study verification in cli"
```

- [ ] **Step 6: Obtain the Task 3 review gate**

Review exact `HEAD^..HEAD` for process/domain separation, output ordering,
valid intermediate compatibility, and Make propagation. Resolve every finding
and rerun Step 4 before Task 4.

### Task 4: Replace module-global alias sets with lexical bindings

**Files:**
- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:560-990,1615-1740`
- Test: `tests/test_e1_study_dependency_guard_v2.py:600-845`

**Interfaces:**
- Consumes: `_ImportVisitor`'s existing `references`, `protected`, `forbidden_calls`, `study_forbidden_calls`, and `closure_errors` output lists.
- Produces: `_Binding`, `_ScopeFrame`, and `_LexicalBindings`; `_ImportVisitor` resolves package objects, exact type-checking sentinels, and the initializer loader through the current lexical scope rather than shared mutable name sets.

- [ ] **Step 1: Add lexical-shadowing RED cases**

Add a parameterized runtime classification contract:

```python
@pytest.mark.parametrize(
    "source",
    (
        "from typing import TYPE_CHECKING\n"
        "def guarded(TYPE_CHECKING: bool) -> None:\n"
        "    if TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "import typing as typing_alias\n"
        "typing_alias = object()\n"
        "if typing_alias.TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "from typing import TYPE_CHECKING\n"
        "flag = object()\n"
        "if flag:\n"
        "    TYPE_CHECKING = True\n"
        "if TYPE_CHECKING:\n"
        "    from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
        "from typing import TYPE_CHECKING\n"
        "def outer() -> None:\n"
        "    runtime_guard = TYPE_CHECKING\n"
        "    def inner() -> None:\n"
        "        nonlocal runtime_guard\n"
        "        runtime_guard = True\n"
        "        if runtime_guard:\n"
        "            from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n",
    ),
)
def test_ambiguous_type_checking_bindings_are_runtime_code(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(StudyRetentionError, match=r"forbidden direct import.*policy_v2"):
        scan_study_dependencies(protocol, repo_root=repo_root)
```

- [ ] **Step 2: Run RED plus the existing exact type-only positive test**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_dependency_guard_v2.py::test_ambiguous_type_checking_bindings_are_runtime_code \
  tests/test_e1_study_dependency_guard_v2.py::test_type_only_package_and_importlib_imports_remain_type_only
```

Expected: at least the function-argument shadowing case FAILS because the
current visitor stores bindings in module-global sets; all cases become
permanent regressions for the lexical implementation.

- [ ] **Step 3: Implement the lexical binding data model**

Add these internal types in `study_retention_v2.py`; do not serialize them or
add a production module:

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
        package_target = self.package_target if self.package_target == other.package_target else None
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

`_LexicalBindings` must expose these exact operations:

| Signature | Required result |
| --- | --- |
| `clone() -> _LexicalBindings` | independent copies of every frame container with shared immutable `_Binding` values |
| `push(kind: _ScopeKind) -> None` | append an empty lexical frame of the requested kind |
| `pop() -> None` | remove exactly the current non-module frame; reject popping the module frame |
| `bind(name: str, value: _Binding) -> None` | write to the frame selected by current `global`/`nonlocal` declarations |
| `bind_target(target: ast.expr, value: _Binding) -> None` | bind a name or recursively bind every tuple/list target element |
| `bind_pattern(pattern: ast.pattern, value: _Binding) -> None` | recursively bind `MatchAs`, `MatchStar`, mapping-rest, sequence, class, and OR-pattern names |
| `resolve(name: str) -> _Binding` | search the lexical chain while honoring declarations; return an uncertain empty binding when unresolved |
| `declare_global(names: Sequence[str]) -> None` | record all names as module-frame assignments for the current scope |
| `declare_nonlocal(names: Sequence[str]) -> None` | resolve all names to the nearest enclosing non-module frame and fail closed if none exists |
| `merge_branches(branches: Sequence[_LexicalBindings]) -> None` | merge corresponding current-scope bindings with `_Binding.merged(...)`, including the unchanged pre-branch state |

Implement every method rather than leaving stub bodies. `clone()` copies frame
containers; immutable `_Binding` values are shared. `bind()` honors current
`global`/`nonlocal` declarations. `bind_target()` recursively covers tuple/list
destructuring. `merge_branches()` unions possible values for each binding and
marks differing package targets or missing branch assignments uncertain.

- [ ] **Step 4: Integrate scopes and every binding construct**

Replace the visitor's module-global alias sets with `_LexicalBindings`.
Implement explicit visitor handling for:

| AST construct | Required binding behavior |
| --- | --- |
| function/async function | visit decorators/defaults in the outer frame; bind the function name outside; push a function frame; bind every argument uncertain; visit body; pop |
| class | visit decorators/bases in the outer frame; bind class name; push class frame; visit body; pop |
| lambda/comprehension | push the matching frame and bind parameters/targets uncertain |
| `Assign`/`AnnAssign`/`NamedExpr` | derive the RHS `_Binding` first, then bind every target |
| `AugAssign` | merge the prior target value with an uncertain value |
| `For`/`AsyncFor`, `With`/`AsyncWith`, exception handler, match pattern | bind every introduced name uncertain |
| `If`, `Try`, `Match`, loop body/else | clone the pre-state, visit each branch once, then merge; never enumerate path combinations |
| `Global`/`Nonlocal` | register declarations before later assignment resolution |

An exact unshadowed `typing.TYPE_CHECKING` import binds
`"type-checking-sentinel"`; `import typing as alias` binds
`"typing-module"`. `_is_type_checking_test(...)` consults the lexical binding
and returns true only for an unambiguous exact sentinel. Type-only bodies still
produce `type_checking` edges but skip runtime capability rejection.

- [ ] **Step 5: Run GREEN and the whole dependency guard**

Run:

```bash
uv run pytest -q tests/test_e1_study_dependency_guard_v2.py
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py
uv run mypy src
```

Expected: all PASS; the real projection and exact type-only imports remain
accepted, and ambiguous/shadowed guards are runtime.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py
git commit -m "refactor(e1): add lexical source capability tracking"
```

- [ ] **Step 7: Obtain the Task 4 review gate**

Review exact `HEAD^..HEAD` for lexical-frame correctness, branch union,
comprehension isolation, `global`/`nonlocal`, exact type-only classification,
and non-exponential traversal. Resolve every finding and rerun Step 5 before
Task 5.

### Task 5: Seal the two PEP 562 initializer exceptions

**Files:**
- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:1000-1205,1635-1800`
- Test: `tests/test_e1_study_dependency_guard_v2.py:800-900`
- Test: `tests/test_study_package_import_closure.py:60-250`

**Interfaces:**
- Consumes: the parsed `ast.Module`, exact source module, and projected `known_modules` inside `scan_study_dependencies(...)`.
- Produces: `_InitializerPolicy` and `_validate_initializer_policy(source_module: str, tree: ast.Module, known_modules: frozenset[str]) -> _InitializerPolicy`; only exact allowed AST node identities bypass the general capability grammar.

- [ ] **Step 1: Add structural initializer RED mutations**

Parameterize mutations of each copied real initializer:

```python
@pytest.mark.parametrize(
    ("relative", "old", "new"),
    (
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            "from importlib import import_module",
            "from importlib import import_module as load_module",
        ),
        (
            Path("src/manufacturing_vision_studio/e1/__init__.py"),
            "value = getattr(import_module(module_name), attribute_name)",
            "value = getattr(import_module(module_name), attribute_name)\n    import_module(module_name)",
        ),
        (
            Path("src/manufacturing_vision_studio/__init__.py"),
            '"manufacturing_vision_studio.registry", "CaseRegistry"',
            '"manufacturing_vision_studio.not_projected", "CaseRegistry"',
        ),
        (
            Path("src/manufacturing_vision_studio/e1/__init__.py"),
            "return sorted(set(globals()) | set(__all__))",
            "globals()\n    return sorted(set(globals()) | set(__all__))",
        ),
    ),
)
def test_pep562_initializer_requires_exact_capability_structure(
    tmp_path: Path,
    relative: Path,
    old: str,
    new: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    path = repo_root / relative
    source = path.read_text()
    changed = source.replace(old, new, 1)
    assert changed != source
    path.write_text(changed)

    with pytest.raises(StudyRetentionError, match="initializer capability structure"):
        scan_study_dependencies(protocol, repo_root=repo_root)
```

Retain the existing laundering tests and add a wrapper/return fixture if no
case covers storing or returning `import_module`.

- [ ] **Step 2: Run RED plus real initializer positives**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_dependency_guard_v2.py::test_pep562_initializer_requires_exact_capability_structure \
  tests/test_e1_study_dependency_guard_v2.py::test_real_pep562_initializers_preserve_complete_dependency_closure
```

Expected: mutated alias/extra-use/map/globals cases are not all rejected by one
stable structural category; the real initializers pass.

- [ ] **Step 3: Build an exact initializer policy from the parsed tree**

Add an immutable internal policy:

```python
@dataclass(frozen=True, slots=True)
class _InitializerPolicy:
    allowed_node_ids: frozenset[int]
    lazy_targets: tuple[tuple[str, str, str], ...]


_EMPTY_INITIALIZER_POLICY = _InitializerPolicy(frozenset(), ())
```

`_validate_initializer_policy(...)` returns the empty policy for every module
except exact `manufacturing_vision_studio` and
`manufacturing_vision_studio.e1`. For those two modules, require:

1. one module-level unaliased `from importlib import import_module`;
2. one literal `_LAZY_EXPORTS` dictionary with unique string keys and exact
   two-string tuple values;
3. every module target resolves through `known_modules`;
4. one module-level `__getattr__(name: str)` containing exactly one direct
   `import_module(module_name)` nested in the existing direct `getattr` call;
5. the existing direct `globals()[name] = value` cache and one return of value;
6. one module-level `__dir__()` with exactly the current
   `sorted(set(globals()) | set(__all__))` return;
7. no other `import_module`, loader, nonliteral module reflection, or
   `globals()` node.

Collect only the node identities belonging to those validated forms in
`allowed_node_ids`. Collect `(export_name, module_name, attribute_name)` in
sorted order as `lazy_targets`; validate them but do not append unconditional
performance graph edges.

Parse once in `visitor_for(...)`, derive the initializer policy from that same
tree, and pass it to `_ImportVisitor`. Do not reread either initializer.

- [ ] **Step 4: Run exact initializer and public API closure coverage**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_dependency_guard_v2.py \
  tests/test_study_package_import_closure.py
uv run ruff check \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py \
  tests/test_study_package_import_closure.py
uv run mypy src
```

Expected: all PASS; real public exports stay lazy, identity-preserving, and
cached, while every structural mutation fails before graph acceptance.

- [ ] **Step 5: Commit Task 5**

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py tests/test_study_package_import_closure.py
git commit -m "fix(e1): seal package lazy import exceptions"
```

- [ ] **Step 6: Obtain the Task 5 review gate**

Review exact `HEAD^..HEAD` for path/node identity, literal map validation,
latent-versus-runtime edge semantics, same-byte parsing, and unchanged public
API behavior. Resolve every finding and rerun Step 4 before Task 6.

### Task 6: Enforce the positive source-capability grammar

**Files:**
- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:200-260,560-990,1615-1745`
- Modify: `src/manufacturing_vision_studio/e1/metrics.py:445-500`
- Test: `tests/test_e1_study_dependency_guard_v2.py:600-1015`
- Test: `tests/test_e1_metrics.py:1-260`

**Interfaces:**
- Consumes: `_LexicalBindings`, `_InitializerPolicy.allowed_node_ids`, and existing project dependency graph rules.
- Produces: stable source-policy categories for `dynamic-import`, `executable-code`, `namespace-reflection`, `import-registry`, and `package-object`; `_safe_reflection_call(...)` accepts only finite ordinary-object forms.

- [ ] **Step 1: Add the capability-family RED matrix**

Add the reviewed bypass and adjacent capability families:

```python
@pytest.mark.parametrize(
    ("family", "source"),
    (
        (
            "namespace-reflection",
            "import builtins\nREFLECTED = vars(builtins)['__import__']\n",
        ),
        (
            "namespace-reflection",
            "REFLECTED = vars(__builtins__)['__import__']\n",
        ),
        (
            "import-registry",
            "import sys\nREFLECTED = sys.modules['builtins']\n",
        ),
        (
            "namespace-reflection",
            "def reflected(value: object) -> object:\n"
            "    return value.__globals__['__builtins__']\n",
        ),
        (
            "dynamic-import",
            "import pkgutil\nLOADER = pkgutil.get_loader('manufacturing_vision_studio.adapters')\n",
        ),
        (
            "dynamic-import",
            "import zipimport\nLOADER = zipimport.zipimporter('/tmp/archive.zip')\n",
        ),
        (
            "namespace-reflection",
            "import operator\nLOOKUP = operator.attrgetter('__globals__')\n",
        ),
        (
            "executable-code",
            "CODE = compile('x = 1', '<study>', 'exec')\n",
        ),
        (
            "namespace-reflection",
            "def reflected(value: object, name: str) -> object:\n"
            "    return getattr(value, name)\n",
        ),
        (
            "namespace-reflection",
            "REFLECT = getattr\n",
        ),
    ),
)
def test_runtime_capability_families_fail_closed(
    tmp_path: Path,
    family: str,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + source)

    with pytest.raises(
        StudyRetentionError,
        match=rf"source capability rejected: {family}",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)
```

Add positive fixtures for direct literal safe attribute reads, `re.compile`,
the real CLI dataclass serialization form, and the unchanged real projection.
The current `_complete_repo(...)` helper replaces `study_cli_v2.py` with
`SYNTHETIC_CLI`, so first add an explicit opt-out:

```python
def _complete_repo(
    tmp_path: Path,
    protocol: StudyProtocolV2,
    *,
    preserve_real_cli: bool = False,
) -> Path:
    # Existing copy loop remains unchanged except for this branch.
    if Path(relative) == RUNNER_PATH:
        destination.write_bytes(SYNTHETIC_RUNNER)
    elif Path(relative) == CLI_PATH and not preserve_real_cli:
        destination.write_bytes(SYNTHETIC_CLI)
    else:
        destination.write_bytes((PROJECT_ROOT / relative).read_bytes())
```

Use that seam to prove both the exact positive and a one-node mutation:

```python
def test_real_cli_dataclass_getattr_is_an_exact_safe_form(tmp_path: Path) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol, preserve_real_cli=True)

    scan_study_dependencies(protocol, repo_root=repo_root)

    cli_path = repo_root / CLI_PATH
    source = cli_path.read_text()
    changed = source.replace(
        "getattr(value, field.name)",
        "getattr(value, field.name.upper())",
        1,
    )
    assert changed != source
    cli_path.write_text(changed)
    with pytest.raises(
        StudyRetentionError,
        match="source capability rejected: namespace-reflection",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)
```

- [ ] **Step 2: Run RED and real-projection positive coverage**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_dependency_guard_v2.py::test_runtime_capability_families_fail_closed \
  tests/test_e1_study_dependency_guard_v2.py::test_real_cli_dataclass_getattr_is_an_exact_safe_form \
  tests/test_e1_study_dependency_guard_v2.py::test_real_task_7_checkout_has_the_exact_reviewed_dependency_closure
```

Expected: `vars(builtins)`, import registries, builtin `compile`, broad
reflection, and first-class `getattr` include failures or unstable old
spelling-specific messages; the real projection passes.

- [ ] **Step 3: Define stable capability categories and sensitive surfaces**

Add immutable constants with these exact memberships:

```python
_DYNAMIC_LOADER_MODULE_ROOTS = frozenset(
    {"importlib", "pkgutil", "runpy", "zipimport"}
)
_NAMESPACE_REFLECTION_MODULE_ROOTS = frozenset(
    {"builtins", "inspect", "operator"}
)
_EXECUTABLE_CODE_NAMES = frozenset({"compile", "eval", "exec"})
_NAMESPACE_REFLECTION_NAMES = frozenset({"globals", "locals", "vars"})
_SENSITIVE_ATTRIBUTES = frozenset(
    {
        "__builtins__",
        "__dict__",
        "__globals__",
        "__import__",
        "__loader__",
        "__spec__",
        "exec_module",
        "f_builtins",
        "f_globals",
        "find_spec",
        "load_module",
        "module_from_spec",
        "spec_from_file_location",
    }
)
_SYS_IMPORT_REGISTRIES = frozenset(
    {"meta_path", "modules", "path_hooks", "path_importer_cache"}
)
```

In runtime-reachable projected source, importing a dynamic-loader module root
is rejected as `dynamic-import` except the exact initializer import node.
Importing a namespace-reflection module root is rejected as
`namespace-reflection`. Acquisition of `__import__`, executable names,
namespace-reflection names, sensitive attributes, and tracked `sys` import
registries produces the corresponding lexical capability before it is
rejected; assignment, argument, return, subscript, attribute, and call analysis
therefore cannot launder it. Subscript and computed spellings on a capability
binding reject even when the key is nonliteral.

Do not reject strings containing these words, `re.compile`, test fixture text,
or the scanner's comparisons against sensitive string constants.

- [ ] **Step 4: Implement finite safe ordinary-object reflection**

`getattr` and `hasattr` are valid only as immediate calls. Record the direct
function `Name` node as allowed while visiting that call, then reject any other
first-class load. `_safe_reflection_call(...)` returns true only when:

1. the call has two or three positional arguments and no keywords;
2. the receiver does not resolve to a capability or package object;
3. the attribute is a literal non-sensitive string; or
4. the node is the exact `study_cli_v2._json_value` dataclass-fields
   comprehension form already validated by path, function ancestry, receiver
   `value`, and `field.name` derived from `fields(value)`.

The exact PEP 562 `getattr(import_module(module_name), attribute_name)` is
accepted only through `_InitializerPolicy.allowed_node_ids`.

Replace the two reachable nonliteral metric reflection sites with explicit
finite dispatch:

```python
def _recall_slice_value(
    item: EvaluationObservation,
    attribute: Literal["severity", "defect_type"],
) -> str | None:
    return item.severity if attribute == "severity" else item.defect_type


def _accuracy_slice_value(
    item: EvaluationObservation,
    attribute: Literal["cad_revision", "view_id"],
) -> str:
    return item.cad_revision if attribute == "cad_revision" else item.view_id
```

Use these helpers in `_recall_slices(...)` and `_accuracy_slices(...)`. Add
tests proving both branches produce the same existing slice keys and metrics.

- [ ] **Step 5: Remove superseded spelling recognizers**

After the capability-family tests are GREEN, remove any remaining
spelling-specific compatibility fields and helpers whose only purpose was
enumeration, including `_is_builtin_import_dict_access(...)` and
`_dynamic_import_loader_kind(...)`. The module-global alias sets were already
replaced in Task 4. Keep project-edge classification, forbidden call names,
protected-scope rules, and exact development-provider rules unchanged. Do not
leave both policies active as competing sources of truth.

- [ ] **Step 6: Run the complete focused GREEN set**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_dependency_guard_v2.py \
  tests/test_study_package_import_closure.py \
  tests/test_e1_metrics.py \
  tests/test_e1_study_cli_v2.py
uv run ruff check \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  src/manufacturing_vision_studio/e1/metrics.py \
  tests/test_e1_study_dependency_guard_v2.py \
  tests/test_study_package_import_closure.py \
  tests/test_e1_metrics.py \
  tests/test_e1_study_cli_v2.py
uv run mypy src
```

Expected: all PASS with stable category diagnostics, real projection accepted,
and public lazy imports unchanged.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py src/manufacturing_vision_studio/e1/metrics.py tests/test_e1_study_dependency_guard_v2.py tests/test_e1_metrics.py
git commit -m "fix(e1): enforce declared source capabilities"
```

- [ ] **Step 8: Obtain the Task 6 review gate**

Review exact `HEAD^..HEAD` for capability-family completeness, false-positive
escapes, direct-call identity, dataclass exception narrowness, removal of the
old spelling policy, bounded traversal, and truthful non-sandbox claims.
Resolve every finding and rerun Step 6 before Task 7.

### Task 7: Align claims, run integrated validation, and reopen final review

**Files:**
- Modify: `docs/evaluation/e1-feasibility-study.md:1-65`
- Modify only if wording remains stale: `src/manufacturing_vision_studio/e1/study_retention_v2.py:1-10`
- Test: the plan-exact ten study modules listed below

**Interfaces:**
- Consumes: approved Task 1–6 commits and all existing study tests.
- Produces: operator documentation that defines declared source dependency closure, plus fresh validation and four independent whole-branch review decisions. It does not produce implementation-validation or study artifacts.

- [ ] **Step 1: Update the operator-facing bounded claim**

Add a short section stating:

```markdown
## Declared source dependency closure

The pre-execution dependency check hashes and parses the same bounded bytes and
verifies declared production-source edges plus prohibited source capabilities.
It is not a Python sandbox or proof of every possible runtime behavior. Tests
and fixed validation subprocesses are a separate audited boundary.

`verify` always prints its JSON report. Its process status is nonzero when the
report says `study_valid: false`; a valid read-only `PENDING` report exits zero.
```

Do not change the command order, phase authorization, one-run rules, or
filesystem-only limitation.

- [ ] **Step 2: Run documentation and focused static checks**

Run:

```bash
uv run ruff check src/manufacturing_vision_studio/e1/study_retention_v2.py
uv run mypy src
git diff --check
```

Expected: PASS.

- [ ] **Step 3: Commit the claim alignment**

```bash
git add docs/evaluation/e1-feasibility-study.md src/manufacturing_vision_studio/e1/study_retention_v2.py
git commit -m "docs(e1): define declared source closure verification"
```

If the retention module wording already exactly matches the approved claim,
stage only the operator guide.

- [ ] **Step 4: Obtain the Task 7 documentation review**

Review exact `HEAD^..HEAD` for claim strength, CLI semantics, unchanged phase
instructions, and absence of production or shop-floor claims. Resolve every
finding before integrated validation.

- [ ] **Step 5: Run the plan-exact ten-module study suite**

Run exactly:

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
  tests/test_e1_study_dependency_guard_v2.py \
  -q
```

Expected: 100% PASS, no execution claim, no result root, and no study command.

- [ ] **Step 6: Run full repository validation**

Run:

```bash
make validate
```

Expected: Ruff PASS, Mypy PASS, all Python tests PASS, web typecheck/build PASS,
and Playwright PASS. This target must not invoke any E1 study phase.

- [ ] **Step 7: Prove the post-validation safety state**

Run:

```bash
git status --short
git diff --check
test ! -e docs/evaluation/results/e1-feasibility-study
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 rev-parse HEAD
git -C /Users/jangtaeho/manufacturing-vision-studio-e1-v2 status --short
```

Expected: active tree clean, result root absent, and preserved HOLD worktree
clean at exact `9fd6d0c600206083fde4fafc874e0226b5df60b3`.

- [ ] **Step 8: Run four fresh whole-branch final reviews**

Dispatch independent read-only reviews over the behavior-change range
`8e4b3ff52461c907c728fb2eae6660dafba7c53a..HEAD`:

1. artifact state, one-run behavior, invalidity propagation, and recovery;
2. truth boundary, protected reachability, declared-source capabilities, and
   PEP 562 exceptions;
3. evidence identity, paths, hashes, schemas, gates, and denominators; and
4. CLI, Make, tests, config integration, operator semantics, and regressions.

Every P0–P2 finding blocks completion. Repair through a focused RED/GREEN task,
rerun the relevant task review, then rerun Steps 5–8. Do not treat green tests
as approval.

- [ ] **Step 9: Stop at the implementation-validation gate**

When and only when all four reviews approve, report the exact clean HEAD,
validation counts, existing validation-runtime result, absent result root, and
preserved HOLD state. Do not run `validate-implementation` or any study phase
in this plan. Those commands remain the separately authorized next stage of
the original E1 feasibility-study plan.

## Self-Review Checklist

- [ ] Every requirement in the approved design has a task: artifact dependency
  propagation (Task 1), exact paths/bytes (Task 2), CLI status (Task 3), lexical
  scopes (Task 4), exact initializers (Task 5), positive capabilities and safe
  forms (Task 6), bounded claims and complete validation (Task 7).
- [ ] No task changes frozen study inputs, schemas, direct-import allowlists,
  package exports, command order, or one-time phase behavior.
- [ ] No new production file or dependency is introduced.
- [ ] All named interfaces and diagnostic categories are consistent across
  tasks.
- [ ] Every production task contains an honest RED selector, a GREEN command,
  scoped static checks, a focused commit, and a fresh review gate.
- [ ] The final task stops before implementation validation and all study
  phases.
- [ ] The plan contains no `TBD`, `TODO`, deferred implementation body, or
  instruction to weaken tests or trust boundaries.
