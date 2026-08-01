# E1 v2 Remediation Preflight

**Recorded:** 2026-08-01 (Asia/Seoul)  
**Repository:** `dooosp/manufacturing-vision-studio`  
**Remote:** `https://github.com/dooosp/manufacturing-vision-studio.git`

## Repository identity and branch boundary

| Check | Evidence |
|---|---|
| Isolated worktree | `/Users/jangtaeho/manufacturing-vision-studio-e1-v2` |
| Remediation branch | `codex/e1-v2-scale-feature-remediation` |
| Starting HEAD | `d7254cf8e09561a085def5cb9c914c31d79b9725` |
| Parent branch | `codex/e1-authoritative-mask-nuisance-evaluation-v0.2.0` |
| Parent local/origin HEAD | `d7254cf8e09561a085def5cb9c914c31d79b9725` |
| Default branch | GitHub `main` |
| `origin/main` | `9a1280b553673a08262295ab5e3480c4080c59ce` |
| Initial worktree state | Clean before the design/plan files were created |

## GitHub state

`gh pr view 12 --json number,title,state,isDraft,headRefName,headRefOid,baseRefName,mergeable,url,reviews`
returned:

```json
{
  "baseRefName": "main",
  "headRefName": "codex/e1-authoritative-mask-nuisance-evaluation-v0.2.0",
  "headRefOid": "d7254cf8e09561a085def5cb9c914c31d79b9725",
  "isDraft": true,
  "mergeable": "MERGEABLE",
  "number": 12,
  "reviews": [],
  "state": "OPEN",
  "title": "feat: add E1 authoritative-mask and nuisance robustness evaluation",
  "url": "https://github.com/dooosp/manufacturing-vision-studio/pull/12"
}
```

No submitted human GitHub review existed at preflight time.

## Release baseline preservation

| Check | Evidence |
|---|---|
| `v0.1.0` annotated tag object | `67bd8af8d6bfdbcb5ff2654fd37b797dc7c75f3d` |
| `v0.1.0` peeled commit | `cf7b9ac37d0533f656068199d3275410cf8cc2f8` |
| v0.1 evidence bundle SHA-256 | `1d492d942aa061e16399f715255760b0a37a8b91eba85cb7b729626ff9e435e7` |
| `v0.2.0` tag | Absent |

## Historical E1 HOLD reproduction

The preserved, ignored evaluation artifact directories live in the parent E1
worktree. Running `make verify-e1-results` there completed with exit code 0.
The verified records reported:

| Profile | Binding | Verified outcome |
|---|---|---|
| mini | code `2f87b885b29c12468effea927279d27424eaa340`; config `70400090ee420f42470e1b8c539f1145e5a71620ceb57d32b7cf6823ffd8ade0`; manifest `00e6ac243217a90f04776855354c2d30de387245b9306c46c22ef992fa0159e3` | `HOLD`, 8/10 gates, nuisance FPR 1/6, feature mapping 11/12 |
| full | code `2f87b885b29c12468effea927279d27424eaa340`; config `70400090ee420f42470e1b8c539f1145e5a71620ceb57d32b7cf6823ffd8ade0`; manifest `1a8f6a32b7e98fe51c72f711f172effcbf04eeda00d0d4fdc8fe5f3ba36dbbc2` | `CALIBRATION_HOLD`; threshold lock `07cee282ce6fc3cc4b55924a8905cfa494deaf3f005581fad2796303ecf3bd06`; release test not executed |

Attempting the same command in the fresh remediation worktree correctly found
no ignored `data/e1-evaluation` directory. That is an artifact-location issue,
not a verification or code failure; the parent artifact verification above is
the preserved source of truth.

## Available validation commands

The checked-in entry points are:

```text
make setup
make lint
make typecheck
make test
make web-check
make e2e
make validate
make verify-e1-results
```

After `make setup`, baseline `make validate` in the new worktree completed with
exit code 0: Ruff PASS, Mypy PASS for 27 source files, pytest 232 PASS, Vite and
TypeScript PASS, and Playwright Chromium 15 PASS. Pytest emitted the existing
Starlette multipart deprecation warning; no new warning was introduced.
