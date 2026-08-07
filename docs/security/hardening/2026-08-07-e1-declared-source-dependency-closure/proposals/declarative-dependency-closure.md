# Security Hardening Proposal: Declarative Dependency Closure

## Decision

We need to choose how the E1 pre-execution verifier establishes a bounded
declared-source dependency claim after repeated loader-spelling bypasses. All
three options also carry the same direct repairs for malformed decision/report
propagation, exact negative-snapshot paths, and invalid verify exit status.
Those repairs are mandatory and are not substitutes for the dependency design.

## Executive Recommendation

The complete option set is:

- **Option 1: Continue incremental spelling patches.** Reject the known
  `vars(builtins)["__import__"]` form and nearby examples in the current visitor.
- **Option 2: Adopt a static positive source-capability grammar.** Keep the
  single-read snapshot and declared graph, but reject unknown
  dependency-sensitive capabilities by default. This is the selected option.
- **Option 3: Enforce imports through a runtime bootstrap.** Install an import
  guard before loading the runner and treat its observations as exercised
  runtime evidence.

I recommend Option 2 under the current constraints. It preserves pre-execution
attestation without introducing another process or runtime hook, and its claim
can remain precise: for the exact projected bytes, accepted declared source
dependencies are projected and allowed, and prohibited source capabilities do
not appear outside two exact initializer exceptions. We must not expand that
claim into sandboxing or complete semantic reachability.

## Evidence

I inspected the exact target revision and the supplied findings; I did not run
their probes or any repository command that executes code. The current source
mechanisms make the structural inference reviewable:

| Evidence | Finding or document | What it establishes |
| --- | --- | --- |
| `E1-F01` | Recurrent reflected-import spelling bypass | The supplied review identifies `vars(builtins)["__import__"]`; `_ImportVisitor` in `src/manufacturing_vision_studio/e1/study_retention_v2.py` recognizes selected aliases, calls, attributes and `__dict__` forms but not that call-wrapped namespace access. |
| `E1-F02` | Malformed decision leaves report verified | `VerifiedStudyState.verified_paths` is present minus invalid, while the invalid-JSON fast return in `src/manufacturing_vision_studio/e1/study_runner_v2.py` marks the malformed JSON but does not propagate invalidity to a present report. |
| `E1-F03` | Negative snapshots are not exact-path-bound | `_validate_snapshots` in `src/manufacturing_vision_studio/e1/study_protocol_v2.py` binds names and bytes but accepts a broad original-path prefix and any project-local byte-identical checked-in path. |
| `E1-F04` | Invalid verify result exits zero | `main()` in `src/manufacturing_vision_studio/e1/study_cli_v2.py` prints any non-exception result and unconditionally returns zero. |

Observed at the target revision, `_snapshot_study_implementation_projection`
reads each declared path once, hashes the payload, and retains it for
`ast.parse`. Observed also, the only intended dynamic package loaders are the
literal PEP 562 export structures in
`src/manufacturing_vision_studio/__init__.py` and
`src/manufacturing_vision_studio/e1/__init__.py`. From the repeated matcher
growth and the still-open call-wrapped form, we infer that spelling denial is
the unstable ownership boundary; a finite capability grammar is the proposed
replacement.

## Current Design And Failure Mode

The protocol declares a sorted implementation projection. The retention code
checks containment and tracked status, performs a bounded read, binds SHA-256
to the captured bytes, parses those bytes, then follows repository imports from
study-owned roots. It rejects unexpected direct edges, forbidden runtime
prefixes, protected scopes and selected dynamic-loading syntax. That exact-byte
chain is a valuable existing control and should remain.

The failure sits inside policy extraction. The visitor carries sets for
`importlib`, builtin, runpy, package-object and type-checking aliases; separate
handlers recognize particular assignment, attribute, `getattr`, subscript and
call shapes. Each recognized spelling can be covered well, but Python offers
other paths to the same loader capability. `vars(builtins)` demonstrates the
difference between denying known syntax and owning the capability invariant.

The adjacent findings expose a similar truth-propagation lesson, but at other
boundaries: report credit must depend positively on a verified decision,
snapshot identity must equal a complete frozen tuple, and process success must
depend on the domain result. We should fix those locally under every option and
avoid pretending the dependency architecture absorbs them.

## Desired Invariants

- Each declared source path is read once within its bounds; the hashed payload
  is the parsed payload.
- Every accepted project dependency is declared, projected and allowed before
  Phase 0.
- Unknown loader, executable-code, or dependency-sensitive reflection
  capability syntax in runtime-reachable projected source fails closed.
- Only the two exact package initializer paths may use the structurally exact
  PEP 562 loader form.
- Direct literal `getattr`/`hasattr` on non-sensitive fields and other finite
  safe object operations remain accepted; broad reflection does not.
- A present report is verified only through a verified decision; snapshot
  identity binds both paths and bytes; `verify` is nonzero for
  `study_valid=false` after printing its JSON.
- Documentation says **declared source dependency closure**, never sandbox or
  complete runtime dependency proof.

## Constraints And Non-Goals

We are preserving a local deterministic demo, the existing frozen study inputs,
and all later one-time execution gates. No runtime service, network boundary,
container, new candidate, or study phase belongs in this decision. Tests and
validation subprocess source are outside the production AST claim. Performance
and memory effects are unmeasured. The approved written design uses focused and
full validation within existing fixed timeouts plus bounded-complexity review;
it does not add a standalone benchmark or numeric budget.

## Before Architecture

The [before diagram](../diagrams/declarative-dependency-closure-before.mmd)
shows the sound byte snapshot feeding a spelling-specific visitor. The dashed
path is the security-relevant gap: an unrecognized reflection form can obtain
loader authority without becoming a declared graph edge.

## Options

### Option 1: Continue Incremental Spelling Patches

The strongest case for Option 1 is delivery simplicity. We would add a
`vars(builtins)` predicate, mandatory regressions for the reviewed form and its
closest variants, then directly repair findings `E1-F02` through `E1-F04`. The
existing scanner, records, entry points and initializer exceptions stay
familiar. Its [after diagram](../diagrams/declarative-dependency-closure-incremental-spelling-patches-after.mmd)
makes that small delta explicit.

Security improves for the four known cases, and scan time and transient memory
should remain effectively within the current mechanism because no extra pass,
process, or persistent state appears. Reliability and operability improve from
truth propagation and nonzero invalid verification. What gives me pause is the
unchanged invariant: a future spelling is accepted until someone identifies
and encodes it. Developer ergonomics also continue to pay review and fixture
cost per bypass.

Rollout is a focused change with a normal pre-study revert. After generated
validation or study evidence exists, rollback must invalidate that evidence and
restart the freeze gate rather than preserve a stale projection claim.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Loader recognition | Known names, aliases, attributes and dictionary forms | Adds `vars(builtins)` and adjacent cases | Closes the known bypass only | Small diff; recurrence remains |
| Truth/CLI fixes | Three open direct defects | Explicit dependency/path/exit repairs | Closes known false-credit and automation paths | Focused compatibility changes |

### Option 2: Static Positive Source-Capability Grammar

Option 2 keeps the exact-byte reader and declared graph, then replaces the
open-ended bad-spelling vocabulary with positive accepted source forms. Literal
imports produce declared edges. Lexical frames track capability provenance
across functions, classes, lambdas, comprehensions, assignments and branch
joins. Unknown binding does not erase provenance. Loader/spec APIs,
`__import__`, executable-code builtins, import registries and
dependency-sensitive namespace reflection reject unless a node is part of one
of two exact initializer structures.

The [selected after diagram](../diagrams/declarative-dependency-closure-static-positive-capability-grammar-after.mmd)
also shows an important compatibility path. We retain ordinary safe object
operations through finite positive forms, including literal non-sensitive
attribute access and the constrained dataclass serialization already used by
the CLI. The two PEP 562 exceptions are keyed by exact source path, literal
export map, AST ancestry and node identity—not merely a function or variable
name. This keeps the public lazy API without granting broad loader authority.

The security gain is recurrence resistance inside the bounded source claim:
unknown dependency-sensitive capabilities fail closed. Residual risk remains
substantial enough to name plainly. AST analysis does not prove descriptors,
callbacks, extension modules, environment behavior, subprocess code or every
Python semantic. A bug in the grammar can still misclassify provenance. This
design is not a sandbox.

The richer lexical analysis adds transient maps and branch unions while ASTs
are live, so scan CPU and peak memory can regress even though application
runtime gains no hop. No result has been measured. Acceptance therefore uses
the exact projected-source focused suites and `make validate` within their
existing timeouts, plus review that confirms one parse, one policy traversal,
bounded branch joins, and no persistent cache. A standalone benchmark or
numeric threshold requires a separate approved design update. Conservative
rejection can also block future legitimate dynamic Python; that is intentional,
but it moves developer workflow toward reviewed narrow exceptions or non-
reflective refactors.

The written specification is approved, and the
[implementation plan](../implementation/static-positive-capability-grammar.md)
has passed independent review. Migration should start only after the user
explicitly authorizes one execution mode, with the present tactical guards
retained until the capability matrix is complete.
A pre-study rollback is a commit revert. Once artifacts bind the new
projection, rollback invalidates them and restarts the gate.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Policy model | Deny recognized spellings | Accept finite safe capabilities; unknown sensitive capability rejects | Narrows recurrence within declared source | Richer lexical analysis and false-positive review |
| PEP 562 | Name/ancestry-oriented exception | Exactly two path- and node-identity structures | Limits trusted loader syntax | Tight initializer compatibility contract |
| Safe object access | Mixed with broad reflection matching | Finite positive ordinary-object forms | Avoids a blanket exemption | Some sites may need small refactors |
| Claim | Dependency scan phrasing can be overread | Declared source dependency closure; no sandbox claim | Makes assurance boundary auditable | Documentation and diagnostic migration |

### Option 3: Runtime Bootstrap

Option 3 moves authority enforcement closer to actual imports. A fixed entry
point would install an import guard before it loads the study runner; allowed
and denied imports after installation would be observable runtime facts. That
is attractive if exercised import behavior becomes the dominant requirement,
and it can remain defense in depth alongside the static inventory.

Its [after diagram](../diagrams/declarative-dependency-closure-runtime-bootstrap-after.mmd)
shows why it does not replace the selected claim cleanly. Already loaded
modules, pre-bootstrap code, unexercised branches, subprocesses and native
loading lie outside the evidence. The current top-level runner import must move
behind the hook, and direct or alternate entry points can become behaviorally
different. It is still not a sandbox.

Startup gains hook decisions and live allowlist state; peak memory and import
latency may regress, though neither is measured. Reliability and operations
also gain hook-order, caching and bootstrap-failure modes plus new diagnostics.
We would need entry-point, repeated-import, partial-failure and subprocess
coverage. Rollback restores the prior entry point before any study execution;
later evidence again must be invalidated.

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Enforcement time | Static pre-execution scan | Import guard before runner load | Observes exercised post-bootstrap imports | Misses preloaded and unexercised behavior |
| Entry point | Runner imported by current CLI path | Bootstrap must precede runner import | Establishes hook ordering | Compatibility and failure-mode expansion |
| Operations | Static report | Static report plus runtime denial telemetry | Better exercised-path visibility | More diagnostics and incident complexity |

## Comparison

No composite score is appropriate; the mechanisms and assurance claims differ.

| Dimension | Option 1: Spelling patches | Option 2: Positive grammar | Option 3: Runtime bootstrap |
| --- | --- | --- | --- |
| Security | Improves known cases; high confidence; recurrence remains | Improves declared-source boundary; high source-derived confidence; semantic residuals remain | Improves exercised imports; medium analogous confidence; bootstrap gaps remain |
| Performance | Neutral; high source-derived confidence | Likely regression in scan CPU; low hypothetical confidence | Startup/import regression; medium analogous confidence |
| Memory | Neutral; high source-derived confidence | Transient lexical-state regression; low hypothetical confidence | Live guard-state regression; low hypothetical confidence |
| Reliability | Improves direct failure signaling; denylist omissions remain | Improves deterministic categories; false positives can block | Regresses through hook ordering and entry-point dependence |
| Operability | Improves CLI automation; no new component | Improves diagnostics; adds policy-review ownership | Regresses through runtime telemetry and bootstrap incidents |
| Migration | Small and reversible, but future churn | Moderate refactor; exact compatibility gates | Largest entry-point and import-order migration |
| Developer drift | Highest long-term patch drift | Lower policy drift; reviewed exceptions required | Hook-aware debugging and alternate-entry drift |

Option 1 wins only for a deliberately short emergency horizon. Option 3 wins if
runtime observations become more important than pre-execution coverage. Under
today's constraints, Option 2 offers the best match between the evidence and
the assurance claim.

## Recommendation

I recommend Option 2 with the three independent direct fixes included in the
same pre-execution implementation change. I would change that recommendation
if the source projection grows enough that the existing validation-runtime gate
cannot complete proportionately, if legitimate dynamic behavior cannot be expressed through
narrow safe forms, or if runtime exercised-import evidence becomes mandatory.
In the first two cases, Option 1 is a temporary fallback; in the third, Option 3
deserves a separate defense-in-depth design review.

## Evidence Coverage And Residual Risk

| Evidence | Option 1 | Option 2 | Option 3 | Tactical protection |
| --- | --- | --- | --- | --- |
| `E1-F01` — Recurrent reflected-import bypass | **Addresses** known form; recurrence remains | **Addresses** through fail-closed capability grammar | **Mitigates** post-bootstrap exercised imports | Keep exact known bypass regression during migration |
| `E1-F02` — Malformed decision leaves report verified | **Addresses** directly | **Addresses** directly | **Addresses** directly | Central decision-to-report invalidity propagation is always required |
| `E1-F03` — Snapshots not exact-path-bound | **Addresses** directly | **Addresses** directly | **Addresses** directly | Compare both frozen paths before bounded byte/hash validation |
| `E1-F04` — Invalid verify exits zero | **Addresses** directly | **Addresses** directly | **Addresses** directly | Print JSON, then return nonzero for `study_valid=false` |

Even after Option 2, we retain risks from AST implementation error and Python
behavior outside the declared source language. Original reproductions and all
direct fixes therefore remain part of final validation; the proposal itself
does not close any finding.

## Migration And Rollout

The written specification gate has passed. The selected option now has a
[file-level implementation plan](../implementation/static-positive-capability-grammar.md)
bound to source revision `8e4b3ff52461c907c728fb2eae6660dafba7c53a`
and design commit `aaf425bababa2d0034f4ebcb66aba321ca1901de`.
The implementation plan has passed independent review. After the user
explicitly authorizes one execution mode, we can add focused failing
regressions, introduce the capability grammar while retaining present guards,
apply the three direct fixes, and then run targeted and broad validation. No
study phase is authorized by passing those checks. Rollback is safe only before
evidence is generated; later rollback invalidates validation/study artifacts
and restarts from an absent result root and newly frozen projection.

## Validation Plan

- Reproduce all four supplied findings against the recorded base, then show
  fail-closed candidate behavior.
- Cover direct, aliased, destructured, annotated, closure, comprehension,
  computed-name and uncertain-branch capability forms.
- Positively cover both exact PEP 562 initializers and current ordinary safe
  object operations.
- Prove projection hash and AST consume one captured payload under a swap
  attempt.
- Require the focused scanner suites and `make validate` to complete within
  their existing fixed timeouts, and review the bounded traversal/resource
  model. Do not add standalone benchmark evidence without a design update.
- Assert malformed decisions cannot credit reports, both snapshot paths are
  exact, and invalid verify output remains JSON while process status is nonzero.
- Run the repository's targeted suites and full validation only after the user
  explicitly authorizes one execution mode under the reviewed plan.

No item in this plan was run during proposal drafting.

## Implementation Work Packages

The [implementation handoff](../implementation/static-positive-capability-grammar.md)
separates capability grammar, exact initializer/safe-form compatibility,
decision/report propagation, snapshot tuple binding, CLI status mapping, and
performance-bound/claim documentation into reviewable packages. Production
code, implementation validation, and every study phase remain outside this
planning change.

## Open Questions

- Should a future, separately reviewed design add numeric scan-time or
  peak-memory budgets after this existing-validation-runtime gate?
- Which ordinary reflection sites require positive grammar forms versus small
  explicit-field refactors?
- Should runtime bootstrap remain deferred or be designed later as defense in
  depth?
- When will the user explicitly authorize one execution mode under the reviewed
  plan?
