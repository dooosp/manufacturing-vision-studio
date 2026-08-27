# E1 Declared Source Dataflow Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rejected Task 6 source-flow implementation with one
immutable, reachability-aware transfer engine that preserves Python eager and
deferred timing, propagates capability provenance through bindings, validates
exact exceptions by resolved callable identity, and remains bounded by
`O(N * H)` transfer work.

**Architecture:** Keep the existing single bounded read, projection graph, and
public `scan_study_dependencies()` result. Inside
`study_retention_v2.py`, replace the mutable `_Binding` / `_LexicalBindings`
plus repeated `ast.NodeVisitor` queries with one structured module analyzer.
Every expression returns its abstract value, reachable post-state, truth
partition, and deferred effects in one pass; statements compose those results
through immutable lexical frames and finite fixed points. Exact PEP 562 and CLI
dataclass exceptions require both an exact structural role and an unambiguous
resolved identity at the completed module state.

**Tech Stack:** Python 3.12.13 through `uv`, `ast`, frozen dataclasses, enums,
immutable tuples/frozensets, pytest 8+, Ruff, Mypy, Git, and the existing E1
projection and subprocess compatibility tests.

**Plan status:** DRAFT FOR USER APPROVAL. This document is the single
architecture/implementation-plan artifact required by the `REDESIGN_REQUIRED`
review. It does not authorize production or test edits. After this document is
reviewed and approved, the first implementation commit must contain only the
counterexample tests from Task 1.

## Global Constraints

- Repository: `/Users/jangtaeho/manufacturing-vision-studio-e1-dataflow-redesign`.
- Branch: `codex/e1-declared-source-dataflow-redesign`.
- Clean redesign baseline: Task 5
  `cc7d32397e68bef0a18acbfa0d096eae9558d9c0`.
- Rejected forensic checkpoint:
  `0a3f9ad5dcf3f22c48c2da7744f53f2ef6ed95b7`, whose parent is exactly the
  redesign baseline.
- The current directory is already a linked worktree at the clean baseline.
  Do not create another worktree and do not modify the rejected checkpoint's
  worktree.
- Never cherry-pick, merge, or mechanically copy the rejected analyzer or its
  analyzer tests. Recreate required behavior from the review counterexamples.
- The finite metrics dispatch is the only independently reusable behavior from
  `0a3f9ad`; reimplement it only after the parity gate in Task 2.
- Preserve the 47-path implementation projection, bounded single-read
  hash/parse identity, dependency graph result, direct-import allowlists,
  forbidden reachability, protected scopes, package exports, schemas, config,
  artifact record fields, study thresholds, gates, seeds, and phase behavior.
- Create no new production module, dependency, schema, config field, service,
  process boundary, runtime import hook, or result artifact.
- The claim remains **declared source dependency closure**. Never claim a
  Python sandbox, complete semantic reachability, shop-floor validation, or
  manufacturing safety validation.
- `docs/evaluation/results/e1-feasibility-study` must remain absent.
- Do not run Task 7, `make validate`, implementation validation, any study
  phase, feature oracle, finalization, study verification, Candidate C,
  FreeCAD, remote push, PR, tag, or release under this plan.
- Keep sibling worktrees and repositories read-only, including
  `/Users/jangtaeho/manufacturing-vision-studio-e1-v2` at
  `9fd6d0c600206083fde4fafc874e0226b5df60b3`.
- Every production change must be driven by a test that was observed failing
  for the intended reason, followed by a focused GREEN run, scoped Ruff, and
  `uv run mypy src` before its review gate.
- A green implementation pass is not approval. Task 6 remains blocked until a
  fresh skeptical review approves the complete redesign range.

## Baseline Evidence

The planning worktree was verified before this document was written:

| Evidence | Observed value |
| --- | --- |
| Repository root | `/Users/jangtaeho/manufacturing-vision-studio-e1-dataflow-redesign` |
| Branch | `codex/e1-declared-source-dataflow-redesign` |
| HEAD | `cc7d32397e68bef0a18acbfa0d096eae9558d9c0` |
| Worktree | clean linked worktree; not a submodule |
| Remote default | `main` pinned by `git ls-remote` to `9a1280b553673a08262295ab5e3480c4080c59ce` |
| Python | `3.12.13` |
| Existing focused baseline | exit `0` for dependency guard, package import closure, metrics, and study CLI tests |
| Result root | absent |

The baseline is a checkpoint, not a sound analyzer. F2, F3, and F7 already
exist at `cc7d323`; F1, F4-F6, and F8 expose the rejected Task 6 design or its
attempted repairs.

## File Structure

No production file is added.

- `src/manufacturing_vision_studio/e1/study_retention_v2.py`
  - retains exact-byte projection capture, graph construction, and public
    report types;
  - owns the new immutable abstract domain, structured expression/statement
    transfer, fixed-point joins, capability policy, and exact exception
    validation;
  - removes `_Binding`, mutable `_ScopeFrame`, `_LexicalBindings`, and every
    lexical-state-dependent node cache or node-ID-only authorization.
- `src/manufacturing_vision_studio/e1/metrics.py`
  - replaces the two finite reflective slice lookups with explicit typed
    dispatch after exact parity is characterized.
- `tests/test_e1_study_dependency_guard_v2.py`
  - owns the F1-F8 RED/characterization matrix, execution-timing cases,
    capability and identity mutations, complexity families, real 47-path
    projection, and exact initializer/CLI controls.
- `tests/test_e1_metrics.py`
  - owns complete dictionary parity for the four supported slice fields,
    unknown/empty values, empty observations, denominators, and confidence
    intervals.
- `tests/test_study_package_import_closure.py`
  - remains an unchanged subprocess compatibility gate for lazy identity,
    caching, unknown attributes, and import order.
- `src/manufacturing_vision_studio/__init__.py`,
  `src/manufacturing_vision_studio/e1/__init__.py`, and
  `src/manufacturing_vision_studio/e1/study_cli_v2.py`
  - are compatibility anchors, not planned edits.

## Abstract Domain

### Truth and reachability

Use an enum, not `bool | None`, so unreachable exits cannot be confused with
unknown truth:

```python
class _Truth(Enum):
    BOTTOM = "bottom"
    FALSE = "false"
    TRUE = "true"
    UNKNOWN = "unknown"
```

The join is exact:

```text
BOTTOM  ⊔ x       = x
TRUE    ⊔ TRUE    = TRUE
FALSE   ⊔ FALSE   = FALSE
TRUE    ⊔ FALSE   = UNKNOWN
UNKNOWN ⊔ x       = UNKNOWN
```

An unreachable state is represented by `None` on a result channel. A reachable
state never uses `_Truth.BOTTOM`; the bottom truth is reserved for an
expression with no normal completion.

### Resolved identities

Node identity is not semantic identity. Define source-stable identities:

```python
_IdentityKind = Literal["builtin", "imported", "function", "class"]


@dataclass(frozen=True, slots=True, order=True)
class _SourceLocation:
    module: str
    node_kind: str
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int


@dataclass(frozen=True, slots=True, order=True)
class _ResolvedIdentity:
    kind: _IdentityKind
    owner: str
    name: str
    definition: _SourceLocation | None = None
```

Examples:

```text
_ResolvedIdentity("builtin", "builtins", "getattr")
_ResolvedIdentity("imported", "importlib", "import_module")
_ResolvedIdentity("function", source_module, "_json_value", definition_location)
```

An exact identity check succeeds only when `complete is True` and the direct
identity fact is `exact(required_identity)`. Assignment, annotated assignment,
augmented assignment, deletion, import aliasing, star import, conditional
one-arm rebinding, or module-level later rebinding widens the fact to `top` and
makes that check fail.

### Values

Keep direct facts separate from an iterable's flattened element facts so loop
targets never discard provenance and the lattice does not recurse without a
bound:

```python
_ExactState = Literal["none", "exact", "top"]
_IterationOutcome = Literal["zero", "one", "many"]


@dataclass(frozen=True, slots=True)
class _PackageFact:
    state: _ExactState = "none"
    target: str | None = None


@dataclass(frozen=True, slots=True)
class _IdentityFact:
    state: _ExactState = "none"
    identity: _ResolvedIdentity | None = None


@dataclass(frozen=True, slots=True)
class _ValueFacts:
    may_capabilities: frozenset[_Capability] = frozenset()
    package: _PackageFact = _PackageFact()
    identity: _IdentityFact = _IdentityFact()
    complete: bool = True


@dataclass(frozen=True, slots=True)
class _AbsValue:
    facts: _ValueFacts = _ValueFacts()
    iterable_element: _ValueFacts = _ValueFacts(complete=False)
    contained: _ValueFacts = _ValueFacts()
    iteration_outcomes: frozenset[_IterationOutcome] = frozenset(
        {"zero", "one", "many"}
    )
```

Constructors enforce canonical forms: `none` and `top` require a `None`
payload, while `exact` requires exactly one non-`None` target/identity. A
synthetic module scope uses the stable `Module` span `(0, 0, 0, 0)`; every AST
location includes node kind plus start/end span so distinct semantic roles do
not collide on an object ID or a shared starting coordinate.

Container values retain the union of every contained value's direct, element,
and contained facts in `contained`, because a capability hidden in a tuple,
list, set, dict, lambda result, or call argument must not cross an unknown
boundary. `iterable_element` is the transitively flattened union of possible
yielded elements. A sink checks direct plus contained facts. Nested container
elements are deliberately flattened; this may conservatively reject code but
cannot erase a capability or invent an exact safe identity. Flattening into
`contained` or through another wrapper widens package and callable identity to
`top`; only direct facts may satisfy an exact-identity exception.

The exact-or-top joins are not ordinary set unions:

```text
none  ⊔ none         = none
exact(x) ⊔ exact(x)  = exact(x)
anything else        = top
complete             = left.complete AND right.complete
capabilities         = set union
iteration outcomes   = set union
```

Thus `none ⊔ exact(x)` cannot accidentally become exact. Strong assignment on
one sequential path replaces a binding; control-flow and fixed-point joins are
monotone. Literal empty iterables have only `zero`, known singleton iterables
have only `one`, known longer literals have only `many`, and an unproved
iterable has all three outcomes. A value with `complete is False` is never
capability-free at a sensitive sink: nonliteral reflection, sensitive
attribute acquisition, dynamic loading, and exact-exception admission fail
closed. Exact exception admission additionally requires direct `exact(x)`
facts, never `contained` facts.

### Immutable lexical state

```python
_ScopeKind = Literal["module", "class", "function", "lambda", "comprehension"]


@dataclass(frozen=True, slots=True)
class _BindingSlot:
    value: _AbsValue
    may_be_bound: bool = True
    may_be_unbound: bool = False


@dataclass(frozen=True, slots=True)
class _Frame:
    scope_id: _SourceLocation
    kind: _ScopeKind
    bindings: tuple[tuple[str, _BindingSlot], ...]
    global_names: frozenset[str] = frozenset()
    nonlocal_names: frozenset[str] = frozenset()
    wildcard_shadowed: bool = False


@dataclass(frozen=True, slots=True)
class _State:
    frames: tuple[_Frame, ...]
```

All `_State` operations return new values:

```python
def resolve(self, name: str) -> _BindingSlot: ...
def bind(self, name: str, value: _AbsValue) -> _State: ...
def bind_target(self, target: ast.expr, value: _AbsValue) -> _State: ...
def bind_pattern(self, pattern: ast.pattern, value: _AbsValue) -> _State: ...
def declare_global(self, names: Sequence[str]) -> _State: ...
def declare_nonlocal(self, names: Sequence[str]) -> _State: ...
def push(self, frame: _Frame) -> _State: ...
def pop(self) -> _State: ...
def join(self, other: _State) -> _State: ...
```

State join requires identical scope IDs, kinds, and declaration sets. It joins
binding presence and values pointwise and ORs `wildcard_shadowed`. A possibly
unbound load has both its normal bound exit and a `NameError` raise exit; it is
never silently treated as a known-empty value.

Function-local collection remains lexical, but declarations and local names
are collected before the deferred body is transferred. A comprehension target
binds in the comprehension frame. A comprehension `NamedExpr` binds in the
nearest enclosing non-comprehension frame, subject to normal global/nonlocal
resolution; it must never rebind an iteration variable.

### Expression, deferred effects, and statement exits

```python
_DeferredKind = Literal["function", "async-function", "lambda", "generator"]
_ExitKind = Literal["normal", "break", "continue", "return", "raise"]
_WriteKind = Literal["assign", "augment", "delete", "import", "star-import"]
_DeferredTiming = Literal["on-call", "on-await", "on-iteration"]
_Multiplicity = Literal["zero-or-one", "exactly-one", "zero-or-many"]
_TransferMode = Literal[
    "eager",
    "deferred",
    "type-only",
    "unreachable",
    "postponed-annotation",
    "lazy-annotation",
]


@dataclass(frozen=True, slots=True)
class _DeferredWrite:
    kind: _DeferredKind
    name: str
    location: _SourceLocation
    target_scope: _SourceLocation | None
    operation: _WriteKind
    value: _AbsValue
    timing: _DeferredTiming
    multiplicity: _Multiplicity


@dataclass(frozen=True, slots=True)
class _DeferredBody:
    kind: _DeferredKind
    location: _SourceLocation
    enclosing_scope: _SourceLocation
    definition_state: _State
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.GeneratorExp


@dataclass(frozen=True, slots=True)
class _DeferredEffects:
    writes: tuple[_DeferredWrite, ...] = ()
    bodies: tuple[_DeferredBody, ...] = ()
    unknown_outer_write: bool = False


@dataclass(frozen=True, slots=True)
class _TransferContext:
    mode: _TransferMode
    commit_state: bool
    emit_runtime_references: bool
    emit_type_only_references: bool


@dataclass(frozen=True, slots=True)
class _NormalExit:
    value: _AbsValue
    state: _State


@dataclass(frozen=True, slots=True)
class _PolicyFacts:
    references: frozenset[_ImportReference] = frozenset()
    protected: frozenset[str] = frozenset()
    forbidden_calls: frozenset[str] = frozenset()
    study_forbidden_calls: frozenset[str] = frozenset()
    closure_errors: frozenset[str] = frozenset()
    pending_exact_uses: tuple[_ExactCallSite, ...] = ()


@dataclass(frozen=True, slots=True)
class _ExprResult:
    truthy: _NormalExit | None
    falsy: _NormalExit | None
    raises: _State | None
    deferred: _DeferredEffects = _DeferredEffects()
    facts: _PolicyFacts = _PolicyFacts()


@dataclass(frozen=True, slots=True)
class _FlowResult:
    normal: _State | None
    breaks: _State | None = None
    continues: _State | None = None
    returns: _State | None = None
    raises: _State | None = None
    deferred: _DeferredEffects = _DeferredEffects()
    facts: _PolicyFacts = _PolicyFacts()
```

`_DeferredEffects` is a canonical sorted tuple, not an append-only event log.
Writes join by `(kind, location, target_scope, name, operation)` and union the
value/multiplicity facts; bodies deduplicate by `(kind, location)` and join
their definition states rather than keeping the first visit. Pending
exact uses likewise deduplicate by `(role, location)`. These collections can
therefore grow only over source locations already present in the AST and
cannot make a loop fixed point diverge through duplicate records.
Multiplicity join keeps identical values, maps `exactly-one ⊔ zero-or-one` to
`zero-or-one`, and maps every join involving `zero-or-many` (or incompatible
remaining values) to `zero-or-many`; `unknown_outer_write` joins with Boolean
OR.

The context modes have one fixed meaning. `eager` commits state and emits
runtime references. `deferred` commits only the isolated local state and emits
runtime references because the body may later run. `type-only` emits tagged
type-checking references but discards state. `unreachable`, `postponed-
annotation`, and `lazy-annotation` emit source-policy findings only: they do not
commit state or add dependency-graph references. This distinction prevents a
policy-only safety inspection from inventing runtime reachability.

`value`, `post_state`, and `truth` are derived properties of the two normal
exits. An unknown truth has both exits, which may carry different values and
states. `BoolOp`, `IfExp`, and filters consume `truthy` / `falsy` directly;
they never reconstruct control flow from syntax after evaluation. Statement
sequences feed only the normal channel to the next statement and retain the
other exit channels by kind. Joins combine channels, deferred effects, and
policy facts component-wise without path enumeration. This keeps policy
findings separate from eager runtime state while still inspecting deferred
bodies exactly once. A definition transfer registers `_DeferredBody`; after
the containing scope's control-flow graph is complete, the analyzer transfers
that body against the join of states reachable at and after the definition.
This call-time suffix envelope prevents a global/free read from being frozen to
a stale definition-time alias. The body still receives a fresh local frame,
and no body state replaces eager definition state. Nested deferred bodies use
the same rule recursively. Exact PEP 562/CLI roles use the stricter completed-
module invariant described below.

Compute suffix envelopes without rescanning syntax: retain the converged output
state at each containing-scope CFG point, then run one reverse monotone join
worklist over those states. A definition receives the envelope at its normal
successor, including loop backedges and normal scope exits. Reverse-envelope
join sites are phase-tagged program points in `_AnalysisStats`; they contribute
worklist pops/strict updates but never expression/statement transfer calls.
This keeps all deferred bodies and all envelope summaries within the same
`O(N * H)` accounting instead of running one suffix scan per definition.

## Execution-Timing Table

| Construct | Eager state effect | Deferred or branch effect | Required transfer rule |
| --- | --- | --- | --- |
| Module statement | Evaluate in source order and commit reachable normal state | none | One module state; no re-query visitor |
| `FunctionDef` / `AsyncFunctionDef` | Evaluate decorator expressions top-down, defaults, keyword defaults, and non-postponed annotations; create Python 3.12 type parameters without eagerly evaluating their lazy bounds; apply decorators bottom-up; bind the function result | Register the body, then inspect it once in an isolated function frame using the containing scope's call-time suffix envelope; never commit it at definition time | Reject every global/nonlocal body write as a deferred violation; inspect lazy type-parameter bounds policy-only; do not summarize arbitrary calls |
| `lambda` | Evaluate defaults before creating the lambda value | Register the body after defaults and inspect it once against the call-time suffix envelope in an isolated lambda frame | Fixes `lambda _=(eval := 0): eval`; no lexical-state cache |
| `ClassDef` | Evaluate decorators, create the type-parameter scope, evaluate bases/keywords, execute the class body eagerly, create/apply decorators, then bind the class result; Python 3.12 type-parameter bounds remain lazy | Decorator replacement makes identity incomplete unless exact | Class-frame local writes stay local; explicit `global` writes update the enclosing module state; inspect lazy bounds policy-only |
| List/set/dict comprehension | Entire comprehension is eager; include zero, one, and fixed-point many exits only when declared by `iteration_outcomes` | Filters and later generators run only on their reachable continuation | Use per-generator loop headers and a finite fixed point; walrus targets nearest non-comprehension frame |
| Generator expression | Evaluate only the outermost iterable expression at creation | Target binding, filters, later iterables, element, and walrus effects are deferred | Inspect deferred body for policy, return element summary, do not commit it; reject every enclosing write from a generator body in this first design |
| `for` / `async for` | Evaluate iterable once | Body executes zero or more times; `else` executes only on normal exhaustion | Bind target from `iterable_element`; fixed point joins zero, next-iteration, break, and normal-exhaustion exits |
| `match` | Evaluate subject once | Cases are possible first-match branches; guards partition each branch | Simple capture receives subject facts; decomposition captures receive a conservative subject-derived value, never empty unknown |
| `with` / `async with` | Evaluate context expressions left to right | Body follows optional target binding; hidden `__exit__` effects are outside the source grammar | Bind `as` target to context-derived unknown facts so known capability provenance is retained |
| `try` / `try*` | Transfer body in order | Each handler starts from the join of entry and every reachable body prefix; `else` uses only normal body exit; `finally` applies to every exit channel | Preserve exception target binding during handler, then delete it on handler exit |
| `if` / `IfExp` | Evaluate condition once | Transfer runtime-reachable truth partitions; inspect a statically unreachable arm once in `unreachable` mode | Join only reachable runtime exits; policy-only state is discarded; nested truth is returned to the parent |
| `BoolOp` | Evaluate operands left to right | `and` continues on true; `or` continues on false | Short-circuit with result truth/state, not `ast.Constant` inspection |
| `while` | Evaluate condition at each loop header | Zero iterations, body backedge, break, and `else` are separate channels | Finite fixed point; no unbounded path enumeration |
| `NamedExpr` | Evaluate value, then bind on the reached path | In deferred context the write remains deferred | Binding occurs only in the result's reachable post-state |
| Assignment / import / delete | Execute in source order on the current state | none | Destructuring uses element facts; deletion binds unknown and invalidates identity |

## Comprehension and Loop Equations

Use these names in code and tests:

```text
E[e](S)             expression transfer
Bind(t, v, S)       target transfer
Join(S1, S2, ...)   reachability-aware state join; ignores None
Element(v)          v.iterable_element as an AbsValue-compatible target value
N(r)                join of r.truthy.state and r.falsy.state
V(r)                join of values on r.truthy and r.falsy exits
ProjectOuter(S)     pop only the comprehension frame, preserving changed outer frames
```

For an eager comprehension with generators `g0 ... gm`:

```text
outer       = E[g0.iter](S0)                         # exactly once
base_0      = push_comprehension(N(outer))
zero_exit   = ProjectOuter(base_0) iff "zero" is possible
```

At generator `i`, use the precomputed `V(outer)` for `i == 0`; otherwise
evaluate `gi.iter` only on the reachable prefix state. Bind `gi.target` from
the iterable's element summary, then evaluate filters left to right:

```text
filter_0.truthy.state = target_state
filter_j              = E[gi.ifs[j]](filter_(j-1).truthy.state)
iteration_done_i      includes every reachable filter_j.falsy.state
pass_i                = final_filter.truthy.state, or target_state when no filters
```

`pass_i` enters generator `i + 1`; for the final generator it evaluates the
element/key/value and joins its normal state into `iteration_done_i`. A false
filter never enters a later generator or result expression. For each clause,
define `Step_i(header)` as target bind, ordered filters, the reachable nested
clause/result transfer, and the join of its normal iteration-completion states.
The outcome equations are:

```text
one_exit_i     = Step_i(base_i)                         iff "one" is possible
header_i^0     = base_i
header_i^(k+1) = Join(base_i, Step_i(header_i^k))       for "many"
many_exit_i    = Step_i(lfp(header_i))                  iff "many" is possible

Post = Join(
    zero_exit,
    ProjectOuter(one_exit_0),
    ProjectOuter(many_exit_0),
)
```

Do not add `base_i` to the final exit unless `"zero"` is an allowed outcome.
The `base_i` term inside the many-iteration header is only the fixed-point seed;
`Step_i(lfp(...))` proves at least one iteration before the many exit. Multiple
iterations are represented by that monotone header fixed point, not a single
synthetic iteration and not path enumeration. Nested generators receive their
own outcome-gated headers, so a later iterable is evaluated only from an outer
filter-pass state. Break/continue are not legal inside a comprehension body and
need no comprehension channel.

For a generator expression, compute only `outer = E[g0.iter](S0)` eagerly.
Build the same generator/filter graph in an isolated deferred comprehension
state for policy and element-summary analysis, but return `N(outer)` as
the creation state. Any `NamedExpr` whose target resolves outside the generator
comprehension is a stable `deferred-effect` rejection in this redesign; no
consumption summary is committed to the creator.

Ordinary `for`, `async for`, and `while` use the same outcome-gated loop-header
operator. They include the entry state in normal exhaustion only when zero
iterations are possible, join each reachable continue/body-normal backedge,
and stop at equality. `else` consumes normal exhaustion only. A break bypasses
`else` and joins the statement's normal output afterward.

## Deferred-Body Policy

- Function, async-function, and lambda bodies are always inspected for imports,
  capabilities, protected scopes, forbidden calls, and exact-exception use.
- Their body state never changes the state in which the definition executes.
- A free/global read in a deferred body resolves against the conservative join
  of containing-scope states reachable at or after that definition, not only
  the definition snapshot. Disagreement becomes `top`/incomplete and fails
  closed at a sensitive sink. Add a regression where a safe global alias is
  rebound to `sys` after `def` and the body later reads `.modules`.
- Function-local and lambda-local writes remain allowed in the isolated state.
- Every `global` or `nonlocal` body write is rejected as `deferred-effect`.
  Assignment, augmented assignment, deletion, import alias binding, and a
  nested comprehension/genexpr walrus all count as writes. Module-scope star
  import remains a separate wildcard/identity invalidator; compile-invalid
  function-scope star-import fixtures are never used. Reads through a correctly
  resolved declaration remain analyzable.
- Because the first redesign has no interprocedural call-effect summaries,
  every outer write is security-sensitive: even an ordinary boolean write can
  change whether later capability acquisition executes. The analyzer must not
  guess whether a function is called.
- Every generator-expression write to a binding outside its comprehension
  frame is rejected. The current 47-path projection has no required generator
  outer-write exception.
- A future direct-call summary is out of scope and requires a separate design.

## Exact-Exception Identity Invariants

Structural matching produces `_ExactCallSite` records keyed by source location
and role, never a frozenset of allowed node IDs:

```python
_ExactRole = Literal[
    "pep562-import-module",
    "pep562-getattr",
    "pep562-cache-globals",
    "pep562-dir-globals",
    "cli-dataclass-getattr",
]


@dataclass(frozen=True, slots=True)
class _ExactCallSite:
    role: _ExactRole
    location: _SourceLocation
    required_bindings: tuple[tuple[str, _ResolvedIdentity], ...]
```

The source location identifies the structurally reviewed role only. Admission
requires all `required_bindings` to resolve exactly in the completed module
state. The analyzer records pending exact uses while inspecting deferred
function bodies and validates them after the full module body has been
transferred, which catches later module-level rebindings.

PEP 562 protects these call-time identities:

```text
import_module -> ImportedIdentity("importlib", "import_module")
getattr       -> BuiltinIdentity("getattr")
globals       -> BuiltinIdentity("globals")
KeyError      -> BuiltinIdentity("KeyError")
AttributeError-> BuiltinIdentity("AttributeError")
sorted        -> BuiltinIdentity("sorted")
set           -> BuiltinIdentity("set")
```

The initializer validator still requires the exact literal `_LAZY_EXPORTS`,
the exact `__getattr__` lookup/cache/return sequence, the exact `__dir__`, one
unaliased `from importlib import import_module`, projected targets, and no
additional capability use. Any write that resolves to a protected module
binding, any mutation of `_LAZY_EXPORTS`/`__all__`, or a module-scope star
import invalidates the exception. An unrelated nested local with the same
spelling does not; a shadow inside the exact function does because that call no
longer resolves to the required module/builtin identity.

The CLI dataclass exception protects:

```text
fields        -> ImportedIdentity("dataclasses", "fields")
is_dataclass  -> ImportedIdentity("dataclasses", "is_dataclass")
getattr       -> BuiltinIdentity("getattr")
isinstance    -> BuiltinIdentity("isinstance")
type          -> BuiltinIdentity("type")
_json_value   -> FunctionIdentity(current module, exact definition)
```

It additionally requires the sole top-level synchronous `_json_value`
function, exact `value: object` parameter, exact dataclass guard, exact
`fields(value)` comprehension, private-field filter, and recursive call.
Assignment, deletion, import alias, star import, conditional rebinding, a
second definition, a decorator, or a later module-level rebind of any required
call-time binding rejects the exception. The same scope-resolution rule applies:
only a write that can change the exact function's lookup matters, while a
shadow in an unrelated local scope does not grant or revoke authorization.

## Complexity Bound

The rejected evaluator was quadratic because the normal visitor repeatedly
asked a second evaluator to recompute receiver prefixes. The redesign has one
transfer owner:

1. A parent calls `E[child](state)` once for each reachable structured edge.
2. `E[child]` returns value, states, truth, and deferred facts together.
3. Capability policy consumes that result immediately; it never calls back into
   an expression-binding query for the same child.
4. There is no lexical-state-dependent cache and no `id(node)` memo.
5. Context-free helpers may cache only literal extraction, source locations,
   and exact syntax facts.
6. Acyclic expression families therefore take `O(N)` transfers.
7. A loop/control-flow program point is scheduled initially and then only when
   its immutable input state strictly grows. With the conservative strict-
   height bound `H` below,
   each point transfers at most `H + 1` times, giving `O(N * H)` work and
   `O(N + state)` memory.

The module-local universe is finite: capability bits are fixed; package targets
come from `known_modules`; resolved identities come from builtins, imports, and
definition locations in the parsed module; binding names come from that same
AST; truth and unknown have fixed height. Header joins are monotone. If a
header exceeds the exact height guard without equality, fail closed with
`source dataflow did not converge` rather than widening to a capability-free
value.

Define the one authoritative counter record returned by the private analyzer
hook; the public `scan_study_dependencies()` result remains unchanged:

```python
@dataclass(frozen=True, slots=True)
class _AnalysisStats:
    program_points: int
    cfg_edges: int
    expression_transfers: int
    statement_transfers: int
    pattern_transfers: int
    state_join_attempts: int
    strict_state_updates: int
    worklist_pops: int
    max_updates_per_program_point: int
    computed_height_bound: int

    @property
    def transfer_steps(self) -> int:
        return (
            self.expression_transfers
            + self.statement_transfers
            + self.pattern_transfers
        )
```

A program point is one phase-tagged expression, statement, or pattern
transfer-dispatch site across the module plus every deferred body, or one
reverse suffix-envelope join site. The reverse site has no transfer dispatch;
including it in `program_points` makes its worklist growth explicit.
Context-free structural matching is not a transfer. Let:

```text
C = number of bits in the fixed capability universe
V = 3 * (C + 2 package + 2 identity + 1 completeness) + 3 iteration outcomes
B(p) = total preallocated binding slots across every frame at point p
F(p) = number of frames at point p
H(p) = 1 point-reachability + B(p) * (V + 2 binding presence) + F(p) wildcard bits
H = max(1, max_p H(p))
```

This intentionally over-approximates the minimal product-lattice height.
Package and identity each receive two units: one for arrival from the
program-point bottom into `none` or one `exact`, and one for the only later
widening to `top`. Binding presence similarly receives one unit for initial
`BOUND`/`UNBOUND` arrival and one for widening to both. The leading point-
reachability unit makes the bound safe even though those per-component arrival
charges are conservative duplicates; `H` may be loose but cannot undercount a
strict input update. All names
bound by assignments, imports, definitions, patterns, exception/with/loop
targets, and comprehensions are preallocated in the frame skeleton. Therefore
no join can add a new slot, and `H` is computed before the worklist runs.
Sequential strong assignment need not be monotone; only a program point's
joined input is compared for a strict update.

The canonical gates, used everywhere after `_AnalysisStats` exists, are:

```text
stats.computed_height_bound == the conservative H formula above
stats.max_updates_per_program_point <= H
stats.worklist_pops <= stats.program_points * (H + 1)
stats.transfer_steps <= stats.program_points * (H + 1)
straight-line stats.transfer_steps <= 2 * len(tuple(ast.walk(tree)))
```

The last factor `2` permits one runtime transfer and one policy-only transfer
for a syntactically unreachable node; there is no `4N` fallback. Tests use
depths `1, 2, 4, 8, 16, 32, 64` for nested
`.__getattribute__("x")`/call chains, alternating `BoolOp`, `IfExp`, lambda
defaults/body, generator expressions, eager comprehensions, wrapper
containers, match/try diamonds, and ordinary/async loops. They count these
structural counters, never wall-clock time or RSS.

## Counterexample and Positive-Control Matrix

Every source fixture is first passed to `compile(source, "<fixture>", "exec")`
so the analyzer is not tested with syntax that `ast.parse()` accepts but Python
cannot compile.

| ID | Fixture and observable contract | Baseline at `cc7d323` | Final requirement |
| --- | --- | --- | --- |
| F1-A | False comprehension filter skips result walrus; later `carrier.modules` remains a registry access | incorrectly accepted | reject `source capability rejected: import-registry` |
| F1-B | False first filter prevents later generator/filter walrus | incorrectly accepted | reject `import-registry` |
| F1-C | Generator expression body walrus is deferred at creation | incorrectly accepted | reject exact `source capability rejected: deferred-effect`; creator state is unchanged |
| F1-D | Empty eager iterable preserves zero-iteration state | incorrectly accepted | reject later `carrier.modules` |
| F2 | Uncalled function contains `global carrier; carrier = carrier.stdout` | incorrectly accepted | reject exact `source capability rejected: deferred-effect`; definition state is unchanged |
| F3-A | `for carrier in (sys,)` then `carrier.modules` | incorrectly accepted | reject `import-registry` |
| F3-B | `match sys: case carrier:` then `carrier.modules` | incorrectly accepted | reject `import-registry` |
| F3-C | `async for` target is unknown and then reads the sensitive `modules` surface | untested | fail closed at the sensitive sink |
| F4 | `SAFE = lambda _=(eval := 0): eval` | accepted positive characterization | remain accepted; defaults precede body analysis |
| F5 | `((False and object()) or (carrier := carrier.stdout))` followed by literal `getattr(carrier, "write")` | accepted positive characterization | remain accepted; nested false reaches outer `or` |
| F6 | Depth 1/2/4/8/16/32/64 dunder, BoolOp, IfExp, lambda, genexpr, and comprehension families | current simple visitor has stable bounded behavior | final `_AnalysisStats` satisfies the single canonical `O(N * H)` inequalities |
| F7 | Exact PEP 562 initializer plus early or late `import_module` rebind | incorrectly accepted | reject `initializer capability structure` |
| F8-A | Real CLI plus late module `getattr` rebind | current scanner has no safe exception and accepts the projection | reject `namespace-reflection` after the exact exception exists |
| F8-B | Real CLI plus late `_json_value` rebind | current scanner has no safe exception and accepts the projection | reject `namespace-reflection` |

Mandatory positives at the final gate:

- direct `sys.stdout` and `from sys import stdout` remain ordinary values;
- `sys.stdout` remains ordinary through lambda/list/set/dict/generator wrappers
  and comprehension targets;
- definitely executed walrus rebinding from `sys` to `sys.stdout` remains safe;
- direct literal `getattr`/`hasattr` on nonsensitive attributes remains safe;
- `re.compile` and sensitive words used only as strings remain safe;
- the real CLI serializes a real `StudyVerificationReport` with exact JSON;
- both real PEP 562 initializers retain lazy identity, caching, `__all__`,
  unknown-attribute behavior, and normal from-list imports;
- the real projection remains exactly 47 paths with the same membership/order,
  direct allowlists, graph relationships, and absent forbidden/protected
  results; and
- metrics preserve complete result dictionaries for severity, defect type,
  CAD revision, and view ID, including missing/empty values and empty inputs.

## Additional Baseline Soundness Obligations

The current-checkpoint inspection found related gaps that the clean transfer
must close instead of carrying forward:

- `global` and `nonlocal` declarations apply to their complete code block, not
  only statements visited after the declaration. Collect them before any body
  transfer, including declarations nested under a branch.
- Assignment target subexpressions execute after the RHS. Transfer the receiver
  and index of attribute/subscript targets so
  `sink[__import__("project.module")] = value` cannot bypass policy.
- A failed `match` guard can mutate state before matching proceeds to a later
  case. Cases are ordered; do not restart every case from the pristine
  baseline.
- Ordinary `except` handlers are exclusive alternatives, while multiple
  `except*` handlers may execute for disjoint subgroups. Model `except*`
  conservatively as ordered may-execute handlers, joining skipped and executed
  state into the next handler.
- Delete an exception target at handler exit as Python does.
- `from module import *` invalidates exact identities and introduces unknown
  bindings; it may not preserve a protected exact exception.
- In Python 3.12, decorator expressions precede defaults, which precede
  eagerly evaluated annotations. When the module has
  `from __future__ import annotations`, annotation expressions are inspected
  as non-runtime source but do not mutate runtime state.
- `_InitializerPolicy.lazy_targets` may not be dead data. Validate every
  literal target against the projected module set, not merely every repository
  module, while retaining latent rather than automatically runtime-reachable
  semantics.
- Exhaustive branch joins must not automatically include the pre-branch state;
  include only reachable exits.
- A runtime-reachable expression, statement, or pattern without an explicit
  ordered transfer rule fails closed with `unsupported source-flow syntax`.
  Its children are still inspected once policy-only for diagnostics. A generic
  `ast.iter_child_nodes()` fallback may not silently fabricate an empty value.

## Implementation Tasks

### Task 0: Approval and execution preflight

**Files:** No edits.

**Interfaces:** Confirms this approved plan, the isolated worktree, Task 5
ancestry, and the absence of result artifacts before test or production work.

- [ ] **Step 1: Obtain explicit user approval of this document and execution mode**

Stop until the user approves this exact plan and chooses subagent-driven or
inline execution. The request to draft/continue the redesign is not the plan
approval gate.

- [ ] **Step 2: Re-prove the isolated baseline after approval**

Run:

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git merge-base --is-ancestor cc7d32397e68bef0a18acbfa0d096eae9558d9c0 HEAD
git log -1 --format=%H -- docs/superpowers/plans/2026-08-08-e1-declared-source-dataflow-redesign.md
git status --short
git diff --check
git rev-parse --show-superproject-working-tree
test ! -e docs/evaluation/results/e1-feasibility-study
test ! -e result
```

Expected: correct root and branch; Task 5 is an ancestor; the latest plan
commit is on the branch; clean worktree; empty superproject output; both result
roots absent.

- [ ] **Step 3: Re-run the pre-red focused baseline**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_dependency_guard_v2.py \
  tests/test_study_package_import_closure.py \
  tests/test_e1_metrics.py \
  tests/test_e1_study_cli_v2.py
```

Expected: exit `0`. If the unchanged baseline fails, stop and diagnose that
failure before adding redesign tests.

### Task 1: Commit the valid F1-F8 counterexample matrix with no production change

**Files:**

- Modify: `tests/test_e1_study_dependency_guard_v2.py`
- Do not modify any file under `src/`.

**Interfaces:**

- Consumes: `_complete_repo`, `_append`, real root/E1 initializer bytes, and
  public `scan_study_dependencies()`.
- Produces: compile-valid F1-F8 security REDs plus positive characterization
  controls for F4-F6.

- [ ] **Step 1: Add a real-CLI fixture seam without changing production**

Change the test helper signature and only its CLI branch:

```python
def _complete_repo(
    tmp_path: Path,
    protocol: StudyProtocolV2,
    *,
    preserve_real_cli: bool = False,
) -> Path:
    # Existing copy logic remains.
    if Path(relative) == RUNNER_PATH:
        destination.write_bytes(SYNTHETIC_RUNNER)
    elif Path(relative) == CLI_PATH and not preserve_real_cli:
        destination.write_bytes(SYNTHETIC_CLI)
    else:
        destination.write_bytes((PROJECT_ROOT / relative).read_bytes())
```

Add a fixture helper that proves syntax before appending:

```python
def _compiled_source(source: str) -> str:
    compile(source, "<dependency-guard-fixture>", "exec")
    return source
```

- [ ] **Step 2: Add F1-F3 negative REDs**

Use this parameterized F1 shape and append each source to `RUNNER_PATH`:

```python
@pytest.mark.parametrize(
    ("source", "expected_category"),
    (
        (
            "import sys as carrier\n"
            "EMPTY = [(carrier := carrier.stdout) for _ in (0,) if False]\n"
            "REGISTRY = carrier.modules\n",
            "import-registry",
        ),
        (
            "import sys as carrier\n"
            "HEAP = [item for _ in (0,) if False "
            "for item in (0,) if (carrier := carrier.stdout)]\n"
            "REGISTRY = carrier.modules\n",
            "import-registry",
        ),
        (
            "import sys as carrier\n"
            "DEFERRED = ((carrier := carrier.stdout) for _ in (0,))\n"
            "REGISTRY = carrier.modules\n",
            "deferred-effect",
        ),
        (
            "import sys as carrier\n"
            "EMPTY = [(carrier := carrier.stdout) for _ in ()]\n"
            "REGISTRY = carrier.modules\n",
            "import-registry",
        ),
    ),
)
def test_nonexecuted_comprehension_paths_preserve_sys_authority(
    tmp_path: Path,
    source: str,
    expected_category: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))
    with pytest.raises(
        StudyRetentionError,
        match=rf"source capability rejected: {expected_category}",
    ):
        scan_study_dependencies(protocol, repo_root=repo_root)
```

Add a separate dormant-global test that requires exact `deferred-effect` and
also executes the source without calling the function to prove `carrier` is
still `sys`. Add named tests for ordinary `for`, unknown `async for` sensitive
access, and simple `match` capture. The normal loop/match core is:

```python
"import sys\nfor carrier in (sys,):\n    REGISTRY = carrier.modules\n"
"import sys\nmatch sys:\n    case carrier:\n        REGISTRY = carrier.modules\n"
```

- [ ] **Step 3: Add F4-F5 positive characterizations**

```python
@pytest.mark.parametrize(
    "source",
    (
        "SAFE = lambda _=(eval := 0): eval\n",
        "import sys as carrier\n"
        "SAFE = ((False and object()) or (carrier := carrier.stdout))\n"
        "WRITE = getattr(carrier, 'write')\n",
    ),
)
def test_ordered_expression_effects_keep_safe_sources_allowed(
    tmp_path: Path,
    source: str,
) -> None:
    protocol = load_study_protocol_v2()
    repo_root = _complete_repo(tmp_path, protocol)
    _append(repo_root, RUNNER_PATH, "\n" + _compiled_source(source))
    scan_study_dependencies(protocol, repo_root=repo_root)
```

Execute each snippet separately with `exec` in a fresh dictionary and assert
`SAFE() == 0` for the lambda and a callable `WRITE` on `sys.stdout` for the
nested truth case. Runtime expectations are derived independently of scanner
internals.

- [ ] **Step 4: Add F6 structural complexity characterization**

Generate compile-valid depths `1, 2, 4, 8, 16, 32, 64` for the reviewed dunder
chain and the six additional AST families. At the Task 5 baseline, characterize
only stable scanner behavior and rejection category; do not couple the first
test-only commit to a rejected/private evaluator or invent a second call-count
definition. After `_AnalysisStats` exists, replace this behavioral-only F6
checkpoint with the canonical counters and inequalities in the Complexity
Bound section. Never assert elapsed time, RSS, or a fallback multiplier.

- [ ] **Step 5: Add F7-F8 exact identity REDs**

For F7, copy each real initializer and insert both an early and a late form of:

```python
class Fake:
    Thing = 7


import_module = lambda module_name: Fake
```

Keep its literal target known/projected. Expect `initializer capability
structure`.

For F8, use `_complete_repo(..., preserve_real_cli=True)` and separately append:

```python
getattr = lambda value, name: "spoofed"
```

and:

```python
_json_value = lambda value: "spoofed"
```

Expect `source capability rejected: namespace-reflection` after the exception
is implemented.

- [ ] **Step 6: Prove the intended RED/characterization split**

Run the F1-F3/F7/F8 selectors. Expected: FAIL because the current scanner
accepts each unsafe source. Run F4-F6 separately. Expected: PASS at the Task 5
checkpoint. A syntax error is not an acceptable RED.

- [ ] **Step 7: Commit tests only**

Run:

```bash
git diff --name-only
git diff --check
git add tests/test_e1_study_dependency_guard_v2.py
git commit -m "test(e1): capture source flow redesign blockers"
```

Expected staged/committed path: only
`tests/test_e1_study_dependency_guard_v2.py`. The security selectors remain
intentionally RED until their implementation task.

### Task 2: Reapply finite metrics dispatch behind complete parity

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/metrics.py:452-509`
- Modify: `tests/test_e1_metrics.py:1-330`

**Interfaces:**

- Consumes: `EvaluationObservation` and the existing `_proportion_metric`
  result contract.
- Produces:
  `_recall_slice_value(item, Literal["severity", "defect_type"])` and
  `_accuracy_slice_value(item, Literal["cad_revision", "view_id"])`.

- [ ] **Step 1: Characterize complete pre-refactor parity**

Extend the existing `observation()` helper with literal `cad_revision` and
`view_id` parameters. Add
`test_recall_slice_dispatch_preserves_complete_metric_parity` and
`test_accuracy_slice_dispatch_preserves_complete_metric_parity`. Assert the
complete dictionaries returned for both supported fields, ordinary values,
missing/empty values mapped to `unknown`, empty observations, sample counts,
proportions, denominators, and confidence intervals. Do not calculate expected
values with the production helper under test.

Run:

```bash
uv run pytest -q tests/test_e1_metrics.py
```

Expected before the refactor: PASS; these are preservation characterizations.

- [ ] **Step 2: Replace only the two reflective field reads**

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

Use the helpers at the two existing grouping sites. Do not change sort order,
fallback keys, metric computation, or public output.

- [ ] **Step 3: Prove GREEN and commit independently**

Run:

```bash
uv run pytest -q tests/test_e1_metrics.py
uv run ruff check src/manufacturing_vision_studio/e1/metrics.py tests/test_e1_metrics.py
uv run mypy src
git diff --check
git add src/manufacturing_vision_studio/e1/metrics.py tests/test_e1_metrics.py
git commit -m "refactor(e1): use finite metric slice dispatch"
```

Expected: all PASS; only the two metric paths are committed.

### Task 3: Add adjacent timing REDs, then build the immutable transfer core

**Files:**

- Modify: `tests/test_e1_study_dependency_guard_v2.py`
- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:543-1600`

**Interfaces:**

- Produces `_SourceFlowAnalyzer.analyze(tree: ast.Module) -> _ModuleFlowResult`.
- Produces the abstract-domain types and immutable operations specified above.
- Produces one `_transfer_expression(node, state, context) -> _ExprResult` and
  one `_transfer_statement(node, state, context) -> _FlowResult` owner.
- Keeps `scan_study_dependencies()` and `DependencyScanReport` public behavior
  unchanged.

- [ ] **Step 1: Add the adjacent structured-flow RED matrix before production edits**

Add focused tests with these exact contracts:

```python
def test_assignment_target_expressions_are_transferred(tmp_path: Path) -> None:
    source = (
        "sink = {}\n"
        "sink[__import__('manufacturing_vision_studio.e1.policy_v2')] = 1\n"
    )
    # compile-valid; expect dynamic-import rejection


def test_scope_declarations_apply_to_the_complete_function_body(
    tmp_path: Path,
) -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "def deferred(flag: bool) -> None:\n"
        "    if flag:\n"
        "        global TYPE_CHECKING\n"
        "    TYPE_CHECKING = False\n"
        "    if TYPE_CHECKING:\n"
        "        from manufacturing_vision_studio.e1.policy_v2 import E1V2Policy\n"
    )
    # the global declaration is scope-wide; the outer write rejects deferred-effect
```

Also add:

- `test_loop_else_receives_normal_exhaustion_state`;
- `test_failed_match_guard_effect_reaches_later_cases`;
- `test_except_star_handlers_preserve_prior_handler_effects`;
- `test_exception_target_is_unbound_after_handler`;
- `test_with_target_preserves_context_capability_provenance`;
- `test_future_annotations_do_not_commit_runtime_named_expression_effects`;
- `test_nonfuture_annotations_follow_python_312_definition_order`; and
- `test_python312_type_parameter_bounds_are_lazy_but_policy_inspected`, with a
  safe trace proving no bound call at definition plus a separate dynamic-import
  bound that is rejected by the policy-only inspection;
- `test_class_body_global_write_is_eager` and
  `test_class_local_write_does_not_escape`;
- `test_abrupt_exit_channels_do_not_feed_following_statements`, covering
  `break`, `continue`, `return`, and `raise`;
- `test_finally_completion_replaces_each_incoming_exit`;
- `test_deferred_free_reads_use_the_call_time_suffix_envelope`, where a safe
  global alias is rebound to `sys` after `def` and the dormant body reads
  `.modules`; and
- `test_deferred_outer_writes_fail_closed` parameterized over function,
  async-function, global/nonlocal assignment, delete, augmented assignment,
  import alias binding, and a generator-expression walrus targeting its
  enclosing function/lambda frame.

Each fixture must compile under Python 3.12. Derive the expected runtime order
with a separate trace-list execution where the case is safe to execute.

- [ ] **Step 2: Run and commit the adjacent tests as RED evidence**

Run the new selectors. Expected: assignment-target, declaration timing,
loop-else, match-guard, `except*`, handler cleanup, and deferred-effect cases
FAIL for their stated behavioral reason. Commit only the test file:

```bash
git add tests/test_e1_study_dependency_guard_v2.py
git commit -m "test(e1): capture structured source flow timing"
```

- [ ] **Step 3: Replace mutable bindings with the exact frozen domain**

Implement `_SourceLocation`, `_ResolvedIdentity`, `_PackageFact`,
`_IdentityFact`, `_ValueFacts`, `_AbsValue`, `_BindingSlot`, `_Frame`, `_State`,
`_DeferredWrite`, `_DeferredBody`, `_DeferredEffects`, `_TransferContext`, `_NormalExit`,
`_PolicyFacts`, `_ExprResult`, `_FlowResult`, and `_AnalysisStats` exactly as
specified in the Abstract Domain and Complexity Bound sections.

Implement state operations with these rules:

- bindings are sorted tuples and are converted to a temporary dict only inside
  a constructor helper;
- `resolve` skips enclosing class frames for function/lambda lookup, honors
  scope-wide global/nonlocal declarations, and returns a possibly-unbound slot
  instead of an empty value;
- strong bind replaces one path's slot;
- destructuring promotes flattened element facts and preserves contained
  capabilities;
- branch join includes only supplied reachable states and requires identical
  frame skeletons;
- star import sets `wildcard_shadowed=True`, makes unresolved loads incomplete,
  and invalidates exact identity checks; and
- no state method mutates an existing frame or state.

Delete `_Binding`, mutable `_ScopeFrame`, and `_LexicalBindings` once their
callers are replaced. Do not add a compatibility cache.

- [ ] **Step 4: Precompute complete lexical declarations**

Replace `_FunctionLocalCollector` with a scope-declaration prepass that returns
all local bindings, `global_names`, and `nonlocal_names` for the module and each
function, lambda, class, or comprehension scope while skipping nested bodies.
The binding universe includes assignments, imports, definitions, patterns,
exception/with/loop targets, and comprehension targets, so fixed-point joins
never grow a frame skeleton. Apply the sets when the frame is created, before
transferring any branch. Treat a declaration conflict or unresolved nonlocal as
a stable closure error.

- [ ] **Step 5: Implement one ordered expression transfer**

`_transfer_expression` must cover these nodes without a second visitor query:

- constants and literal containers, including exact truth and flattened
  contained/element facts;
- names with builtin/import/function/class identities and maybe-unbound raise
  exits;
- attributes and subscripts, including package targets, sensitive attributes,
  `sys` registries, ordinary `sys.stdout`, and target receiver/index effects;
- calls, arguments, keywords, wrappers, return facts, capability crossing, and
  stable policy categories;
- `NamedExpr`, `BoolOp`, `IfExp`, unary `not`, comparisons needed by exact
  guards, and nested truth partitions;
- lambda defaults before isolated body inspection; and
- yield/yield-from facts in deferred bodies.

The stable source-capability families remain:

```text
dynamic-import
executable-code
namespace-reflection
import-registry
package-object
deferred-effect
```

Add/recreate the original capability matrix before implementing its GREEN:
`vars(builtins)["__import__"]`, `vars(__builtins__)`, `sys.modules`,
`__globals__`, `pkgutil.get_loader`, `zipimport.zipimporter`,
`operator.attrgetter`, builtin `compile`/`eval`/`exec`, broad/nonliteral
`getattr`, first-class `getattr`, sensitive dunder calls, and capability values
inside call arguments and wrappers. Unknown/incomplete receivers fail closed
only at a sensitive sink; ordinary typed operations remain analyzable.

- [ ] **Step 6: Implement straight-line statements and import facts**

Implement `Expr`, `Assign`, `AnnAssign`, `AugAssign`, `NamedExpr` through its
expression transfer, `Delete`, `Import`, `ImportFrom`, `Return`, `Raise`,
`Break`, `Continue`, `Pass`, and definition expression order. Transfer an
assignment RHS first, then each target left-to-right; for attribute/subscript
stores transfer the receiver and index expressions before binding/recording
the store.

The module context detects `from __future__ import annotations`. Without it,
function definition order is decorator expressions top-down, positional
defaults, keyword-only defaults, parameter/return annotations, function
creation, decorator application bottom-up, then name binding. With postponed
annotations, inspect annotation syntax for policy facts but do not commit its
state or runtime references. In Python 3.12, type-parameter bound and constraint
expressions are lazy even without the future import: inspect them once for
source policy, do not commit their expression state at function/class
definition, and prove that order with the locked-runtime trace test.

- [ ] **Step 7: Create one module analyzer result without global diagnostic lists**

```python
@dataclass(frozen=True, slots=True)
class _ModuleFlowResult:
    final_states: tuple[_State, ...]
    facts: _PolicyFacts
    stats: _AnalysisStats
```

`_SourceFlowAnalyzer` owns immutable context (source module, known/projected
modules, initializer/CLI structural policy, future-annotation mode). It returns
facts from transfers; it does not append to mutable visitor lists. Convert the
final facts into the existing `_ImportReference` and diagnostic collections at
the `scan_study_dependencies()` boundary.

- [ ] **Step 8: Verify the straight-line checkpoint without committing it**

Run F4, F5, the capability-family matrix, assignment-target evaluation,
existing import/package tests, Ruff on the two edited paths, and Mypy. F1-F3
and the structured loop/try selectors may remain RED until Task 4. Do not
commit the production rewrite until Task 4 completes every required structured
transfer and the analyzer has one active policy path.

### Task 4: Complete eager/deferred structured flow and activate one analyzer

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:898-1800`
- Modify only for already-written assertions: `tests/test_e1_study_dependency_guard_v2.py`

**Interfaces:**

- Consumes: the Task 3 abstract domain and transfer owners.
- Produces: reachability-aware `if`, function/lambda/class, comprehension,
  genexpr, loop, match, with, try/try-star, and statement-sequence transfers.
- Produces a single active `_SourceFlowAnalyzer`; the old `_ImportVisitor` no
  longer exists.

- [ ] **Step 1: Implement branch and short-circuit composition**

Compose `if`, `IfExp`, and `BoolOp` from `_ExprResult.truthy` and `.falsy`.
Transfer runtime effects only on reachable branches. Transfer every statically
unreachable, type-only, postponed-annotation, deferred, and type-parameter
bound/constraint syntax region once with the matching explicit
`_TransferContext` mode (`lazy-annotation` for the type-parameter case): collect source
capabilities and only the references allowed by `_TransferContext` (`type-only`
references stay tagged; unreachable/postponed/lazy annotation references are
not graph edges), discard its state, and do not add a runtime CFG exit. Use the
same transfer dispatcher, not a second visitor. Never merge the pre-branch
state unless it is a real reachable exit.

- [ ] **Step 2: Separate definition-time and deferred-body state**

Implement the timing table for function, async-function, lambda, and class.
Function/lambda bodies start from an isolated frame over read-only outer
frames whose free/global values come from the containing scope's call-time
suffix envelope; their final state never replaces the definition state. Reject
every write resolved outside that deferred frame as `deferred-effect`. Class
bodies execute eagerly, explicit class-body global writes update the outer
state, and ordinary class locals remain isolated. Keep the class, type-
parameter, and late global-alias regressions GREEN.

Update existing tests that previously expected an ordinary deferred nonlocal
write to pass. The stronger expectation is a `deferred-effect` rejection; do
not remove their lexical-resolution assertions.

- [ ] **Step 3: Implement eager comprehensions with per-generator fixed points**

Use the equations in this plan. Preserve zero iteration; use literal
empty/nonempty iteration outcomes where known; partition every filter; enter a
later generator only from the prior filter's truthy exit; bind target element
facts; and project only the popped comprehension frame at exit. A walrus binds
the nearest non-comprehension frame and rejects an illegal iteration-variable
rebind.

- [ ] **Step 4: Implement generator creation versus consumption**

Evaluate only the outermost iterable in the creator state. Analyze the
remaining graph in a deferred comprehension state to produce element and
policy facts. Do not commit deferred state. Reject every write that resolves
outside the generator frame as `deferred-effect`.

- [ ] **Step 5: Implement regular loops and their exit channels**

Use a monotone header fixed point for `for`, `async for`, and `while`. Promote
iterable elements into the target and honor the exact zero/one/many outcomes.
Join normal-body and continue exits into the backedge, route break around
`else`, route only normal exhaustion through `else`, and carry raise/return
outward. A statement after an unconditional abrupt exit is transferred only
policy-only. Unknown async iteration adds incomplete target facts and a
possible raise; it never becomes capability-free.

- [ ] **Step 6: Implement ordered match transfer**

Evaluate the subject once. For each case, join the prior no-match state with
the false-guard state from the preceding case. A simple capture receives the
subject value; sequence/mapping/class/or-pattern captures receive conservative
subject-derived direct/contained facts. A possibly partial failed-pattern
binding is marked maybe-bound/unknown. Only a truthy guard enters the body.

- [ ] **Step 7: Implement with and exception flow**

For `with`/`async with`, evaluate items left-to-right and bind each optional
target to an incomplete context-derived value that retains known capability
facts. Model body exits; treat hidden exit suppression conservatively by
joining the possible raised and normal channels without clearing facts.

For `try`/`try*`, collect the entry and each may-raise prefix state. Ordinary
handlers are exclusive; `except*` handlers are ordered may-run handlers, so
each next handler receives the join of skipped and executed prior state. Run
`else` only from normal try completion. Remove handler target bindings on exit.
Apply `finally` to normal, break, continue, return, and raise channels and honor
a finalbody exit that replaces the incoming completion. The abrupt-exit and
finalbody-replacement regressions are mandatory GREENs, not checklist-only
claims.

- [ ] **Step 8: Make F1-F6 and adjacent timing selectors GREEN**

Run:

```bash
uv run pytest -q tests/test_e1_study_dependency_guard_v2.py -k \
  'nonexecuted_comprehension or dormant_function or loop_and_match or async_for or ordered_expression or transfer_is_single_pass or assignment_target or scope_declarations or loop_else or match_guard or except_star or exception_target or with_target or annotations or type_parameter or class_body or abrupt_exit or finally_completion or call_time_suffix or deferred_outer'
```

Expected: PASS. Then run all dependency-guard tests except the still-RED F7/F8
identity selectors. Fix only verified source-flow defects; do not weaken a
counterexample or broaden an exception.

- [ ] **Step 9: Commit the coherent analyzer core**

Run scoped Ruff, `uv run mypy src`, and `git diff --check`. Confirm the diff
contains no copied `_evaluate_expression` or node-ID memo from `0a3f9ad`.
Commit:

```bash
git add src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py
git commit -m "refactor(e1): add immutable source flow analysis"
```

### Task 5: Bind exact exceptions to completed-module identities

**Files:**

- Modify: `src/manufacturing_vision_studio/e1/study_retention_v2.py:543-590,2322-2695`
- Modify: `tests/test_e1_study_dependency_guard_v2.py`
- Keep byte-identical: both package initializers and `study_cli_v2.py`.

**Interfaces:**

- Replaces `_InitializerPolicy.allowed_node_ids` with structural
  `_ExactCallSite` roles and projected latent targets.
- Produces exact completed-module identity checks for PEP 562 and CLI
  `_json_value`.

- [ ] **Step 1: Extend the identity mutation RED matrix**

In addition to F7/F8, cover assignment, annotated/augmented assignment,
deletion, import alias, star import, one-arm conditional rebind, loop/match/
with/exception target rebind, function/class redefinition, decorator, second
function definition, and deferred outer write for each protected identity.
Keep existing exact-shape mutation tests.

- [ ] **Step 2: Replace node-ID authorization with structural roles**

Make `_validate_initializer_policy` return exact call sites and literal lazy
targets. Source location identifies a reviewed structural role but never grants
permission. Pass the projected module set into validation and reject a literal
lazy target that is merely repository-known but not projected. Retain lazy
targets as latent validation facts; do not enqueue every public export as a
runtime dependency.

- [ ] **Step 3: Validate PEP 562 identity at every normal module exit**

Require the exact `import_module`, `getattr`, `globals`, `KeyError`,
`AttributeError`, `sorted`, and `set` identities listed above. Require the
literal maps and exact two function definitions to remain unshadowed. A
protected binding must be exactly bound and complete on every normal module
exit; disagreement or a wildcard makes the exception fail.

- [ ] **Step 4: Validate the CLI dataclass exception**

Recognize only the exact top-level synchronous `_json_value` in the real CLI.
Require final exact identities for `fields`, `is_dataclass`, `getattr`,
`isinstance`, `type`, and recursive `_json_value`, plus the exact guard,
comprehension, field-name read, private filter, and recursive call. Record the
nonliteral `getattr` as a pending exact use while the deferred body is
inspected; resolve it only after completed module-state validation.

- [ ] **Step 5: Remove every source-flow node-ID allowance**

Delete `allowed_node_ids` and all checks that authorize a call/name because
`id(node)` belongs to a set. Context-free source locations and structural
matchers may remain. There must be no lexical-state memo keyed by node ID.

- [ ] **Step 6: Prove identity GREEN and real compatibility**

Run:

```bash
uv run pytest -q \
  tests/test_e1_study_dependency_guard_v2.py \
  tests/test_study_package_import_closure.py \
  tests/test_e1_study_cli_v2.py
```

Expected: F7/F8 and all mutation cases reject; the real CLI, both real
initializers, all six subprocess package tests, both import orders, and the
real 47-path projection pass.

- [ ] **Step 7: Prove compatibility-anchor bytes and commit**

Run:

```bash
git diff --exit-code cc7d32397e68bef0a18acbfa0d096eae9558d9c0 -- \
  src/manufacturing_vision_studio/__init__.py \
  src/manufacturing_vision_studio/e1/__init__.py \
  src/manufacturing_vision_studio/e1/study_cli_v2.py \
  configs/evaluation/e1-feasibility-study.v1.json
uv run ruff check \
  src/manufacturing_vision_studio/e1/study_retention_v2.py \
  tests/test_e1_study_dependency_guard_v2.py \
  tests/test_study_package_import_closure.py \
  tests/test_e1_study_cli_v2.py
uv run mypy src
git diff --check
git add src/manufacturing_vision_studio/e1/study_retention_v2.py tests/test_e1_study_dependency_guard_v2.py
git commit -m "fix(e1): bind source exceptions to callable identity"
```

### Task 6: Prove the bound, run the complete Task 6 gate, and reopen review

**Files:**

- Modify only if a verified defect remains:
  `src/manufacturing_vision_studio/e1/study_retention_v2.py`
- Modify only if a missing behavioral assertion remains:
  `tests/test_e1_study_dependency_guard_v2.py`
- No Task 7 documentation or result artifact.

**Interfaces:**

- Consumes: all Task 1-5 commits.
- Produces: fresh structural complexity evidence, complete focused validation,
  and independent Task 6 review decisions. It does not authorize Task 7.

- [ ] **Step 1: Complete adversarial complexity families**

Use depths `1, 2, 4, 8, 16, 32, 64` for dunder/call chains, alternating
BoolOps, nested IfExp, lambda defaults/body, list/set/dict comprehensions,
false filters, later/nested generators, genexprs, wrapper containers,
match guards, try/except/finally/except-star, for/async-for, and diamond joins.
Assert:

```text
computed H equals the plan formula
max updates at one program point <= computed H
worklist pops <= program points * (H + 1)
all expression + statement + pattern transfer steps <= program points * (H + 1)
straight-line expression transfers <= 2 * ast.walk node count
```

Use only `_AnalysisStats` and the definitions in the Complexity Bound section.
There is no alternate profiler, elapsed-time budget, or `4N` fallback. Do not
raise `H`, change what counts as a program point, or exclude a transfer family
to fit observed behavior; a counter mismatch is an implementation defect.

- [ ] **Step 2: Run the complete focused Task 6 GREEN set**

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
git diff --check
test ! -e docs/evaluation/results/e1-feasibility-study
test ! -e result
```

Expected: all commands exit `0`; both result roots remain absent. Do not run
the ten-module Task 7 suite or `make validate` in this plan.

- [ ] **Step 3: Re-check exact requirements and diff**

Verify every F1-F8 row and mandatory positive control against fresh output.
Inspect the complete range from the plan commit through HEAD. Confirm:

- no second stateful visitor/evaluator path;
- no state-dependent node cache;
- no node-ID-only authorization;
- no capability-free unknown at a sensitive sink;
- no deferred body effect committed at definition/creation time;
- no result artifact, config/schema/projection membership change, or claim
  expansion; and
- the rejected commit remains only a forensic reference.

- [ ] **Step 4: Dispatch four independent read-only Task 6 reviews**

Review the complete redesign range in parallel:

1. Python execution order, truth partitions, fixed points, exits, and deferred
   effects;
2. capability acquisition/escape, unknown handling, package graph, PEP 562,
   and CLI exact identities;
3. traversal accounting, convergence proof, adversarial families, and absence
   of repeated subtree evaluation; and
4. real 47-path/public import behavior, metrics parity, test honesty, bounded
   claims, and prohibited artifact/remote work.

Every P0-P2 finding blocks Task 6. Repair only a verified issue with a fresh
RED, rerun the affected focused gate, then rerun all four reviews.

- [ ] **Step 5: Stop at the Task 6 approval boundary**

Report exact HEAD, commit list, test counts, Ruff/Mypy/diff results, complexity
bounds, compatibility anchors, result-root absence, and four review decisions.
Do not start Task 7 until the user/controller explicitly approves Task 6.

## Post-Task-6 Approval Handoff (Not Authorized by This Plan)

This document intentionally ends at the blocked review boundary; it does not
erase the approved specification's landing gates. Only after an explicit Task 6
approval, create/approve a short execution addendum that resumes the canonical
plan in this order:

1. run the plan-exact ten-module Task 7 validation set;
2. run `make validate`;
3. re-prove the exact projection/worktree/result-root preconditions and retain
   the bounded declared-source/local-demo claims;
4. obtain four independent whole-branch state, truth-boundary, evidence, and
   integration approvals; and
5. stop before implementation validation, every study phase, Candidate C,
   FreeCAD, and remote/GitHub work unless their separate later gates are
   explicitly approved.

None of those commands or reviews is part of the current execution scope. This
handoff exists only so Task 6 approval has an unambiguous next gate instead of
silently treating the focused redesign suite as final acceptance.

## Self-Review Checklist

- [ ] All eight review findings map to a named compile-valid test and a transfer
  or identity rule.
- [ ] Execution timing covers function defaults/body, lambda, class, eager
  comprehension, generator expression, for/async-for, match, with/async-with,
  try/except/except-star/finally, annotations, lazy type-parameter bounds, and
  abrupt exits, with named compile-valid tests for each state-changing family.
- [ ] Truth/state correlation is retained through separate truthy/falsy normal
  exits; unreachable paths are not joined.
- [ ] Values retain direct, contained, and iterable-element capability facts;
  unknown/incomplete facts fail closed at sensitive sinks.
- [ ] Function/lambda/genexpr outer writes are rejected until a separately
  designed call/consumption summary exists.
- [ ] Comprehensions preserve zero iteration, false-filter cutoff, later
  generator reachability, multiple iterations, and nested generator state.
- [ ] Every exact exception requires structure plus completed-module resolved
  identities; node/source location alone never grants permission.
- [ ] Complexity evidence uses only `_AnalysisStats`, the one formula for `H`,
  and the canonical transfer/worklist inequalities; it never substitutes
  elapsed time, RSS, a private-profiler count, or a larger fallback multiplier.
- [ ] Metrics are an independent parity-preserving commit.
- [ ] No new production file, dependency, schema, config field, projection
  member, artifact field, runtime hook, service, or process boundary is added.
- [ ] The plan stops before Task 7, `make validate`, every study command,
  FreeCAD, and all remote/GitHub work.
- [ ] The non-authorizing post-Task-6 handoff preserves the ten-module,
  `make validate`, whole-branch-review, and implementation-validation gates.
- [ ] The document contains no unresolved placeholder or instruction to weaken
  tests or trust boundaries.

## Execution Handoff

After this document is committed and explicitly approved, choose one:

1. **Subagent-Driven (recommended):** dispatch a fresh implementer for each
   task and run specification plus code-quality review between tasks.
2. **Inline Execution:** execute this plan in the current linked worktree with
   checkpoints after each task.

No implementation path begins before that choice and approval.
