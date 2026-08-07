# Security Hardening Review: E1 Declared Source Dependency Closure

## Evidence Basis

This portfolio is bound to tracked revision
`8e4b3ff52461c907c728fb2eae6660dafba7c53a` and four supplied review findings.
The exact source archive and canonical finding set are integrity-recorded in
`context.md`; this is an ordinary evidence collection, not a sealed security
scan. Source inspection confirmed the control-flow mechanisms behind each
finding, but no PoC, repository code, test, validation, or study command was
run.

The structural signal is concentrated in the dependency guard. Several review
rounds extended an AST visitor for new loader aliases and reflection forms, yet
`vars(builtins)["__import__"]` remains outside its recognized spellings. The
other findings—decision/report verification credit, exact negative-snapshot
paths, and invalid verify exit status—are independent direct defects. We must
repair those under every option; they are not evidence that an AST redesign
alone fixes artifact truth or CLI semantics.

## Constraints

- Keep the bounded single-read invariant: hash and parse the exact same bytes.
- Fail closed before Phase 0 and preserve the declared projected dependency
  graph, direct allowlists, and forbidden reachability rules.
- Preserve ordinary safe object operations and only the two exact PEP 562 lazy
  initializers in `src/manufacturing_vision_studio/__init__.py` and
  `src/manufacturing_vision_studio/e1/__init__.py`.
- Make only a declared source dependency closure claim. This is not a sandbox
  or a complete proof of Python runtime behavior.
- Use a balanced profile because no measured latency or memory budget was
  supplied. Implementation remains blocked at the written-spec review gate.

## Opportunity Portfolio

| Opportunity | Evidence | Options | Recommendation | Proposal |
| --- | --- | --- | --- | --- |
| Positive declared-source capability boundary | Recurrent reflected-import bypass; malformed decision/report propagation; non-exact snapshot paths; invalid verify exits zero (`E1-F01`–`E1-F04`) | 1. Incremental spelling patches; 2. Static positive capability grammar; 3. Runtime bootstrap | Select Option 2 under the current pre-execution, local-demo, no-new-service constraints; retain direct fixes for findings 2–4 | [Make declared source dependencies a positive capability boundary](proposals/declarative-dependency-closure.md) |

## Recommendation Summary

I recommend Option 2, the static positive source-capability grammar. It keeps
the strongest existing property—the one captured payload is both hashed and
parsed—while changing the policy owner from a growing vocabulary of bad
spellings to finite accepted capabilities. Unknown dependency-sensitive
reflection would reject by default, with narrow structural exceptions only for
the two current package initializers. Ordinary safe field and attribute access
would remain available through finite positive forms.

Option 1 is proportionate only when the immediate delivery horizon dominates
recurrence risk. Option 3 becomes preferable if the project later needs
evidence about imports actually exercised at runtime and accepts bootstrap
ordering, startup, memory, and operational costs. It still would not be a
sandbox and would not attest unexercised or pre-bootstrap behavior.

## Next Decisions

- Approve or revise the written specification before creating
  `implementation/` or modifying production code.
- Set explicit dependency-scan time and peak-memory budgets.
- Confirm the finite safe ordinary-object forms and exact initializer grammar.
- Decide whether runtime bootstrap should remain deferred defense in depth.

No implementation plan is present in this portfolio because the written-spec
review gate remains pending.
