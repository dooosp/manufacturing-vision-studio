# Local Context: E1 Declared Source Dependency Closure

## Source identity

- Source root: `/Users/jangtaeho/manufacturing-vision-studio-e1-feasibility-separability`
- Repository: `manufacturing-vision-studio`
- Branch: `codex/e1-feasibility-separability-study`
- Target revision: `8e4b3ff52461c907c728fb2eae6660dafba7c53a`
- Target tree: `1fa91aa8206122b5d75038276e2ec1926a6b72dc`
- Default branch evidence: local `main` and `origin/main` refs are present; no
  `origin/HEAD` symbolic ref was available.
- Source drift: `none` for tracked evidence. Source was inspected at the target
  revision. The concurrent untracked draft specification and this derived
  hardening directory are excluded from the source-evidence identity.

The target revision contains 202 tracked artifacts. A deterministic
`git archive --format=tar HEAD` of that revision has SHA-256
`f30970efc36f5fc9a8c175cf3415ce5f4925afe4116e81e2ba3fbcd5341ae6e2`.

## Supplied finding registry

The four review findings were supplied for this hardening analysis. The
following canonical, LF-terminated lines have SHA-256
`29a8cb27eb3abc556ddc9ae4b54b9cbad39690eb8ab36f787aaea754f8aada28`:

```text
F01|Repeated AST alias/reflection misses culminate in accepted vars(builtins)["__import__"].
F02|Malformed decision JSON leaves its dependent report counted as verified.
F03|Negative-result snapshots bind bytes but not both exact frozen paths.
F04|The verify CLI exits zero when study_valid is false.
```

| Evidence | Reader-facing title | Classification | Exact-revision support |
| --- | --- | --- | --- |
| `E1-F01` | Recurrent reflected-import spelling bypass | Observed supplied finding; source mechanism inspected | `_ImportVisitor` and `_is_builtin_import_dict_access` in `src/manufacturing_vision_studio/e1/study_retention_v2.py`; dependency-guard fixtures in `tests/test_e1_study_dependency_guard_v2.py`; relevant history includes `b9bfe34`, `2039795`, `4c75190`, `dd23e6d`, and `8e4b3ff` |
| `E1-F02` | Malformed decision leaves report verified | Observed supplied finding; source mechanism inspected | Early invalid-JSON return and complement-derived `verified_paths` in `src/manufacturing_vision_studio/e1/study_runner_v2.py` |
| `E1-F03` | Negative snapshots are not exact-path-bound | Observed supplied finding; source mechanism inspected | `_validate_snapshots` in `src/manufacturing_vision_studio/e1/study_protocol_v2.py` and canonical tuples in `configs/evaluation/e1-feasibility-study.v1.json` |
| `E1-F04` | Invalid verify result exits zero | Observed supplied finding; source mechanism inspected | `main()` in `src/manufacturing_vision_studio/e1/study_cli_v2.py` returns zero after every non-exception result |

## Collection identity

The evidence collection combines the exact 202-file tracked archive with the
four canonical supplied findings, for an artifact count of 206. The collection
SHA-256 is `7394cd37a067a25a87dd5c41a64ee52bcfdd4ed210d3516fcd763d4854dc0619`,
computed over these LF-terminated manifest lines:

```text
targetRevision=8e4b3ff52461c907c728fb2eae6660dafba7c53a
treeSha1=1fa91aa8206122b5d75038276e2ec1926a6b72dc
trackedArtifactCount=202
trackedArchiveSha256=f30970efc36f5fc9a8c175cf3415ce5f4925afe4116e81e2ba3fbcd5341ae6e2
findingSetSha256=29a8cb27eb3abc556ddc9ae4b54b9cbad39690eb8ab36f787aaea754f8aada28
```

## Focused source inventory

| Path | SHA-256 | Purpose |
| --- | --- | --- |
| `src/manufacturing_vision_studio/e1/study_retention_v2.py` | `f77362ce5144b5820baac38db3b059980fc6df0eda40b5d052cedd1c95fc12ec` | Single-read projection, AST visitor, graph and policy |
| `tests/test_e1_study_dependency_guard_v2.py` | `742dffa89d016619dd527443a3f01ad668fb4eea24fb3798978f845822a5201d` | Current spelling-specific and closure fixtures |
| `src/manufacturing_vision_studio/e1/study_runner_v2.py` | `43914fd54936d118ed9baef849dc5800a32a0df0a20cb5e04349fb719bf2fa42` | Decision/report verification dependency |
| `tests/test_e1_study_runner_v2.py` | `49fc1e72fb3ce9ce93e87fec55d126e42e7bcff9267fd77141572fb3b984c546` | Artifact-state expectations |
| `src/manufacturing_vision_studio/e1/study_protocol_v2.py` | `e416e0425efe6043cfe7bbfc26763e31495880dbd29e7bd082415a9864984e87` | Negative snapshot validation |
| `tests/test_e1_feasibility_protocol_v2.py` | `5c4c1e9bcb2d77281b4a02ce404d03d3fc2909f2e242050cef4b784157e51c4c` | Protocol mutation coverage |
| `src/manufacturing_vision_studio/e1/study_cli_v2.py` | `2c6c4756ba6f2cb2cf0e1b82347081d31a09d539ef26ba98d14b615571948847` | CLI process-status mapping |
| `tests/test_e1_study_cli_v2.py` | `6e308073f0680c56cb1c2b58bbc78669a3cf15c7230755b41adb5ce8ad5c35db` | CLI contract fixtures |
| `src/manufacturing_vision_studio/__init__.py` | `4928e38cee2ffbdfa910099e34f251e5049ef74cdbe542e9f984e68b449c510c` | First PEP 562 lazy initializer |
| `src/manufacturing_vision_studio/e1/__init__.py` | `df6a2451cf64e05395961d97f5de523a549ca5109ce3838f034fbec791a0bdba` | Second PEP 562 lazy initializer |
| `configs/evaluation/e1-feasibility-study.v1.json` | `2342f51b1d52cf523bf9f1e0d0b1bd67d3b0245b9505a8842129185f046ce8be` | Frozen snapshot names, paths and hashes |

## Evidence limits and commands

This is an ordinary mixed source-and-finding collection, not a sealed Codex
Security scan. No PoC was executed and no behavior was dynamically reproduced.
No repository code, test, validation, study, implementation-validation, or
experiment-phase command was run. The analysis used read-only Git and file
inspection plus hashing; later checks only validate the derived JSON, links,
and owned paths.
