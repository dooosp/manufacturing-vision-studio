# E1 Task 7 Current-Identity Repair Design

## Status and authority

This design was approved by the user on 2026-08-17 as a separate repair cycle
for the two defects exposed by Task 7 `make validate`.

- Repository: `/Users/jangtaeho/manufacturing-vision-studio-e1-dataflow-redesign`
- Branch: `codex/e1-declared-source-dataflow-redesign`
- Clean design start: `334322780c47a3c6a41ea67669d9077c4a82de5a`
- Existing linked worktree: reuse it; do not create another worktree.
- Task 7 remains stopped before implementation validation and every study phase.

The implementation plan will pin the exact clean HEAD after the design and
plan documentation commits. That plan-pinned HEAD, rather than the earlier
design-start SHA, is the required implementation preflight identity.

The repair is complete only after its focused reviews pass and Task 7 Steps
5–8 are rerun from the beginning. Green tests alone are not approval.

## Problem statement

Task 7's exact ten-module study suite passed 1,464/1,464, but full repository
pytest failed 19 tests. Four independent read-only investigations split those
failures into two deterministic defects already present at the authorized Task
7 start commit:

1. Seventeen diagnostics and policy tests fail closed because Task 2 commit
   `ceb67cbaf2a8684f147cd9afef0e87c582b04758` changed the bytes of projected
   `src/manufacturing_vision_studio/e1/metrics.py` without rebinding the checked
   candidate selection's current implementation projection.
2. Two replay-verification cases read the ignored local file
   `data/e1-v2-development/candidate-a.json`. That file is absent from a clean
   checkout even though byte-identical, hash-bound Candidate A evidence is
   already embedded in the checked selection.

Neither defect may be hidden by weakening a loader, removing a projection
member, copying ignored data, or rerunning Candidate A/B comparison.

## Design decision

Use a controlled current-identity migration for the checked selection, then
make the replay test consume the checked embedded Candidate A evidence.

This reuses the repository's existing separation between:

- immutable original execution evidence;
- the current audited implementation wrapper; and
- downstream feasibility-study source bindings.

The design deliberately does not change candidate ranking, candidate metrics,
runtime policy, scanner policy, schemas, path membership, thresholds, gates,
or study behavior.

### Rejected alternatives

#### Restore the old `metrics.py` bytes

Restoring the old SHA requires restoring the reflective
`getattr(item, attribute)` implementation. Any different finite dispatcher has
different bytes. Restoring reflection would undo the approved Task 2 behavior
and reintroduce a prohibited source capability. A metrics-specific scanner
exception or removal from the projection would weaken the fail-closed boundary.

#### Allow stale or versioned projections in the loader

Converting the exact current-projection comparison into a warning, exception,
or dual-version path would let runtime consumers load a selection that is not
bound to current implementation bytes. The existing record already separates
original execution identity from current audit identity, so a schema version,
new loader mode, or production API is unnecessary.

#### Copy, generate, or track Candidate A data

Copying an ignored sibling file would keep the test checkout-dependent.
Generating it would reopen candidate comparison or inference. Tracking another
587 KB copy would duplicate evidence already present in the checked selection.

## Identity model

### Historical evidence that must remain unchanged

The following values describe the original one-run comparison and are never
migrated:

| Evidence | Required identity |
| --- | --- |
| Original snapshot | `8d636717a1b04267933b214a3121acfb93182e46` |
| Original selection raw SHA-256 | `18ca69bba321f24105c95cc3482b9658e7a2f03ef274ac75a5ed44f822782a9b` |
| Original selection record SHA-256 | `f2a257a731d991ceba74f791e24a15e983fd806734af2ea973fc5808daab7280` |
| Original execution projection | `90c5c7a894b1289572718fce13f39177fafe278707fae697accb0cd9828de429` |
| Candidate A raw SHA-256 | `ed8c0331759500d78cb69805af8678b4214398120b8ec5ad7389e2360f344c84` |
| Candidate B raw SHA-256 | `983c8e6dc47e62f78b3c55e701a091c96d603a9ea7334e6e7098392ff97ae029` |

The complete original projection, embedded Candidate A/B envelopes, candidate
records, comparison inputs, candidate evidence, and recorded transforms remain
unchanged. The selection remains `HOLD`, `selected_candidate_id: null`, and
`audit_evidence_status: UNVERIFIED`. The original execution dependency guard
remains the truthful `INCOMPLETE_DEPENDENCY_CLOSURE` result.

Historical plans, the Task 4 negative-result report, the Task 4 ledger, and
security context retain their old wrapper hashes because they describe their
specific reviewed revisions.

### Current identities that migrate

The current 47-path projection has the same sorted membership as the checked
record. Its only mismatched entry is:

| Path | Stored SHA-256 | Current SHA-256 |
| --- | --- | --- |
| `src/manufacturing_vision_studio/e1/metrics.py` | `b9e9627dd1bb8e3f688e11e602542fd47f3a9c3b9f57860ed29c899c3c5354cc` | `3c200c1f0101a4d93c584e825dbed9e630e09ff1d5feaff7aa349eb4da42899f` |

The generated selection must have these exact new identities:

| Current identity | Required value |
| --- | --- |
| Implementation projection | `7ccc656be191d0216480da4ad6536d4f50995a446a45f6810b1133a64583cbfa` |
| Selection record SHA-256 | `7392d4d1d9078b44dac0c9dc777d7622f1f145c2e3b6bf9fffb9a58be407ae5a` |
| Selection raw SHA-256 | `32868450a349379e8e548854217c69035b7972ab75acc7f02295e5fae8a76242` |

Relative to the checked selection at `3343227`, exactly four semantic leaves
may change:

1. `implementation_projection[32].sha256` for `metrics.py`;
2. `implementation_projection_sha256`;
3. `audit_evidence.provenance.current_audit_projection_sha256`; and
4. `record_sha256`.

Any fifth semantic difference is a stop condition.

## Components and ownership

### Repair 1: current selection and downstream source identities

Owned tracked paths:

- `configs/evaluation/e1-v2-candidate-selection.json`
- `configs/evaluation/e1-feasibility-study.v1.json`
- `src/manufacturing_vision_studio/e1/study_protocol_v2.py`
- `tests/test_e1_feasibility_protocol_v2.py`
- `tests/test_e1_study_retention_v2.py`

The checked selection is generated in a temporary directory with the existing
`repair_candidate_selection_from_preserved_run()` and
`write_candidate_selection()` functions. The preserved input root is fixed to:

`/Users/jangtaeho/manufacturing-vision-studio-e1-v2/data/e1-v2-development`

That root and its containing sibling are read-only inputs. Before generation,
the sibling must be clean at
`9fd6d0c600206083fde4fafc874e0226b5df60b3`, and the preserved selection and
Candidate A/B raw hashes must match the historical identities above.

The repair function is permitted because it verifies the original repository
snapshot and stored transforms while explicitly avoiding candidate comparison,
search, policy inference, and benchmark reruns. It may render deterministic
inputs and run the existing current trust, baseline, history, dependency, and
recorded-transform audits. It must write only its temporary output.

The temporary selection is accepted only after:

- its semantic diff is exactly the four-leaf allowlist;
- its raw, record, and projection hashes equal the required new values;
- `load_candidate_selection()` returns `HOLD`/`None`/`UNVERIFIED`; and
- `verify_candidate_selection_audit()` returns `None` without changing bytes.

Only then may the canonical temporary bytes replace the checked selection.

The feasibility protocol then migrates exactly two source-hash scalars:

- `source_hashes.selection_raw_sha256`; and
- `source_hashes.selection_record_sha256`.

The same two values are mirrored in `study_protocol_v2.py` and its literal
protocol/retention tests. Every other feasibility-config field remains exactly
equal to `cc7d32397e68bef0a18acbfa0d096eae9558d9c0`.

### Repair 2: checkout-independent replay test evidence

Owned tracked path:

- `tests/test_e1_v2_diagnostics.py`

The existing replay-verification test first loads the checked selection through
`load_candidate_selection(...).as_record()`. From that validated export it
selects the Candidate A envelope and the corresponding pinned candidate hash,
then calls the existing private test-facing decoder:

```python
provenance = evidence["provenance"]
artifact = diagnostics._decode_embedded_candidate_artifact(
    provenance["embedded_candidate_artifacts"]["A"],
    expected_sha256=provenance["candidate_artifact_sha256"]["A"],
)
```

The decoder retains encoded/raw length caps, canonical Base64, compressed and
raw SHA checks, bounded decompression, and canonical JSON parsing. The test uses
the decoded first diagnostic trace and the candidate evidence from the same
validated selection. No production helper, shared fixture, tracked candidate
copy, or public API is added.

## Data flow

```text
read-only preserved sibling bytes + exact git snapshot
    -> existing preserved-run repair audit
    -> temporary canonical selection
    -> four-leaf semantic-diff and identity gate
    -> pure loader + explicit procedural verifier
    -> checked current selection
    -> two feasibility source-hash scalars
    -> mirrored protocol constants and tests

checked current selection
    -> pure validated export
    -> bounded embedded Candidate A decoder
    -> replay-verification test input
```

No data flows from test output back into production records. No result or raw
data root is created in the active worktree.

## Failure handling and stop conditions

Stop without replacing tracked bytes or committing when any of the following
is true:

1. Active branch, plan-pinned implementation HEAD, or worktree cleanliness
   differs from the implementation plan's preflight contract.
2. The preserved sibling HEAD, status, or any preserved raw hash differs.
3. The live/stored selection projection mismatch is not exactly `metrics.py`.
4. Projection membership/order is not the same 47 paths.
5. Repair execution reaches candidate comparison, search, policy inference, or
   benchmark code.
6. Temporary output changes anything outside the four-leaf allowlist.
7. Any original provenance, candidate envelope, candidate metric, comparison
   input, recorded transform, or current audit payload changes.
8. The result is not `HOLD`/`null`/`UNVERIFIED`.
9. The pure loader or explicit audit verifier fails.
10. The feasibility config changes outside the two source-hash scalars.
11. Any other protected anchor differs from the redesign baseline.
12. Either active result root appears, the sibling becomes dirty, or a
    prohibited command runs.
13. A focused test, static gate, scoped review, restarted Task 7 validation, or
    whole-branch review fails.

Temporary files are disposable diagnostics, not study evidence. A failed
attempt leaves the checked worktree at its pre-repair state and records the
exact failure in the ignored SDD report.

## Test and review strategy

### Existing RED evidence

- Selection load/policy: 17 tests fail at the exact current-projection guard.
- Replay fixture: two parameter cases fail with `FileNotFoundError` while
  `data/e1-v2-development/candidate-a.json` is absent.

These existing failures are the required behavioral REDs; no weaker substitute
test is introduced.

### Repair 1 GREEN evidence

- Recompute all 47 current projection entries and prove one pre-repair mismatch.
- Prove exactly four allowed semantic selection changes.
- Run the affected 17 diagnostics/policy cases.
- Run pure load and full explicit audit verification.
- Run feasibility protocol and retention identity selectors.
- Run Ruff on changed Python/tests, Mypy on `src`, and `git diff --check`.
- Obtain an independent scoped identity/evidence review before committing.

### Repair 2 GREEN evidence

- Prove the ignored Candidate A path remains absent.
- Run the replay-verification selector and require `2 passed`.
- Run the complete diagnostics module and policy default-selection selector.
- Run Ruff on the changed test and `git diff --check`.
- Obtain an independent scoped portability/trust review before committing.

### Integrated restart

After both repair commits and their reviews approve:

1. rerun the exact Task 7 ten-module suite from the beginning;
2. rerun `make validate` from the beginning;
3. prove the active worktree clean and both result roots absent;
4. prove the other three protected anchors unchanged;
5. structurally prove the feasibility config differs from the baseline only in
   the two authorized selection hashes;
6. prove the preserved sibling remains clean at
   `9fd6d0c600206083fde4fafc874e0226b5df60b3`;
7. obtain four fresh whole-branch reviews from the exact redesign branch base
   `8e4b3ff52461c907c728fb2eae6660dafba7c53a` through the repair `HEAD`; this
   deliberately broader review range is independent of the implementation
   plan's narrower preflight identity; and
8. stop before implementation validation and every study phase.

If integrated validation or a review finds another issue, return to a separate
focused RED/GREEN repair and restart all integrated Task 7 gates.

## Commit boundaries

The implementation plan will preserve two independently reviewable repair
commits:

1. `fix(e1): rebind current candidate selection identity` for Repair 1's five
   tracked paths.
2. `test(e1): use embedded candidate replay evidence` for Repair 2's one test
   path.

The design and implementation-plan documents are separate documentation-only
commits. No implementation commit includes unrelated cleanup.

## Non-goals

- Candidate A/B comparison, search, ranking, policy inference, or benchmark
  reruns
- Candidate C or any new candidate
- implementation validation or an E1 study phase
- feature-oracle, finalization, or study verification commands
- changes to `metrics.py`, scanner policy, loader semantics, schemas, projection
  membership/order, gates, thresholds, seeds, phase behavior, or public APIs
- edits to historical plans, negative-result evidence, or original provenance
- ignored candidate generation/copying/tracking
- result creation, FreeCAD, sibling modification, or remote/GitHub work
- shop-floor, safety, production-inspection, or real-manufacturing claims
