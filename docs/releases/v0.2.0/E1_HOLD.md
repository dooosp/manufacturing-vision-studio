# v0.2.0 E1 release-candidate packet — HOLD

This packet records the first formal E1 evaluation after code and protocol
freeze. It does not claim `DEMO_READY_E1`, `FIELD_READY`, production accuracy,
safety approval, shipment authority, or completed human UAT.

## Frozen identities

- Evaluation commit: `2f87b885b29c12468effea927279d27424eaa340`
- Protocol: `mvs-e1` `1.3.0`
- Protocol SHA-256:
  `140887fb9e9980c8f7854d2d9f8b0a927aee4994fb74ee2535aa109f19fa7d99`
- Generator: `mvs-e1-generator` `1.0.0`
- Generator configuration SHA-256:
  `7e05399f8f93769b83196b255724b6be6548c27ad54c2e242c9dc388c2415f09`
- Pipeline/model: `e1-normalized-local-difference` `1.1.0`
- Model artifact SHA-256:
  `15d557ed44541d4e3b7f382b9b6ff6a9e510a1924b7b9d86a07c7ba52bcbbc03`
- Evaluation configuration SHA-256:
  `70400090ee420f42470e1b8c539f1145e5a71620ceb57d32b7cf6823ffd8ade0`
- Threshold candidate: `0.0025`, selected from calibration only

## Formal decisions

| Profile | Cases | Calibration | Held-out test | Decision |
| --- | ---: | --- | --- | --- |
| E1-mini | 48 | 4/4 gates passed; lock persisted | 8/10 gates passed | HOLD |
| E1-full | 480 | 3/4 gates passed; lock withheld | Not executed | HOLD |

Mini test failures:

| Gate | Observed | Required |
| --- | ---: | ---: |
| Nuisance-only false-positive rate | 1/6 = 16.67% | ≤ 5% |
| Affected-feature mapping accuracy | 11/12 = 91.67% | ≥ 95% |

Full calibration failure:

| Gate | Observed | Required |
| --- | ---: | ---: |
| Nuisance-only false-positive rate | 3/30 = 10.00% | ≤ 5% |

The full runner correctly wrote `CALIBRATION_HOLD`, kept `metrics` null,
published no gallery, and executed zero full test cases. No threshold, model,
protocol, seed, metric, or acceptance threshold was changed after either result.

## Mini held-out metrics

| Metric | Result |
| --- | ---: |
| Confusion | TP 10, TN 9, FP 1, FN 2 |
| Precision / recall / specificity / F1 | 90.91% / 83.33% / 90.00% / 86.96% |
| Average precision / AUROC | 93.34% / 91.67% |
| Medium / high recall | 4/4 / 4/4 |
| LOW recall | 2/4 = 50.00% exploratory |
| Median Dice / median IoU | 1.000 / 1.000 |
| Mask precision / recall | 100.00% / 64.51% |
| Empty-mask accuracy | 8/10 = 80.00% |
| Feature / part / revision binding | 91.67% / 100% / 100% |
| Trust-boundary abstention | 4/4 |

Weakest mini slices were scale nuisance FPR `1/1`, front-view classification
`3/6`, LOW recall `2/4`, burr recall `1/2`, and stain recall `1/2`.

## Full calibration metrics

| Metric | Result |
| --- | ---: |
| Confusion | TP 56, TN 51, FP 3, FN 4 |
| Precision / recall / specificity / F1 | 94.92% / 93.33% / 94.44% / 94.12% |
| Average precision / AUROC | 96.82% / 97.04% |
| Medium / high recall | 20/20 / 20/20 |
| LOW recall | 16/20 = 80.00% exploratory |
| Median Dice / median IoU | 1.000 / 1.000 |
| Mask precision / recall | 100.00% / 53.90% |
| Empty-mask accuracy | 47/54 = 87.04% |
| Feature / part / revision binding | 100% / 100% / 100% |

The weakest full calibration slices were scale nuisance FPR `3/4`, burr
recall `6/10`, LOW recall `16/20`, and oblique-right classification `35/39`.

## Artifact bindings

| Binding | Mini | Full |
| --- | --- | --- |
| Dataset manifest SHA-256 | `00e6ac243217a90f04776855354c2d30de387245b9306c46c22ef992fa0159e3` | `1a8f6a32b7e98fe51c72f711f172effcbf04eeda00d0d4fdc8fe5f3ba36dbbc2` |
| Threshold-lock SHA-256 | `58b7449fb77fcd93bd4c38b0c120115f0fca31b00851da61b22adb3cc544d985` | `07cee282ce6fc3cc4b55924a8905cfa494deaf3f005581fad2796303ecf3bd06` |
| Result SHA-256 | `a66d791a5ba53bd53007ace5520ddb9b7e583ef910ff38f566538a1558a1d756` | `1207932bf2ad290f6951aaa157042d96adf64ad06d1f3611a93921f2d89a543b` |
| Deterministic projection SHA-256 | `815fa35af5330fa6feaf73a51ff17efb6a6743135dae319df46fe073c0460c06` | `54a50e6d62be01a277e00f8ff0015ec40e62b25e4e0300554ec55017ab7ca2cb` |

Both FULL repeatability manifests equal
`1a8f6a32b7e98fe51c72f711f172effcbf04eeda00d0d4fdc8fe5f3ba36dbbc2`.
The exact public summaries are linked below; volatile local runtime paths and
timestamps are intentionally excluded.

- [`e1-mini-v0.2.0-hold.json`](../../evaluation/results/e1-mini-v0.2.0-hold.json)
- [`e1-full-v0.2.0-hold.json`](../../evaluation/results/e1-full-v0.2.0-hold.json)

## Validation already completed before formal evaluation

- Ruff: PASS
- Mypy: PASS across 27 source files
- Pytest: 231 passed
- TypeScript and Vite production build: PASS
- Chromium: 8 passed
- Repository hygiene: PASS across 133 tracked or unignored files
- npm audit: zero vulnerabilities
- Independent correctness, security, and UI reviews: initial P2 findings were
  repaired before the evaluation commit.

## Post-evaluation packaging verification

The formal mini and full artifacts above remain unchanged. The packaging and
read-only evidence UI were verified after the formal decision without changing
the protocol, generator, pipeline, threshold, manifests, or result digests.

- `make verify-e1-results`: PASS for both frozen profiles and all bindings above
- `make validate`: Ruff PASS; Mypy PASS across 27 source files; Pytest 232
  passed; TypeScript and Vite production build PASS; Chromium 15 passed
- `mvs-e1 verify --profile mini --require-pass`: expected exit 1 for `HOLD`
- `mvs-e1 verify --profile full --require-pass`: expected exit 1 for `HOLD`
- Repository hygiene: PASS across 140 tracked or unignored files
- npm audit at `high`: zero vulnerabilities
- Independent result reconciliation: 316 expected fields checked, zero
  discrepancies between generated artifacts and public summaries
- Independent correctness, security, metric, and product-UI re-reviews: no
  unresolved P0-P2 product defects; the five-pane responsive gallery correction
  was re-tested at 1280 px and 800 px
- Final CI review classified the intentionally failing `--require-pass` step as
  a P1 landability blocker. It is retained and dispositioned as the formal HOLD
  signal: a failed preregistered release gate must keep this Draft PR unmerged.
- Actual mini API inspection: seven bounded gallery cases; exact E1 asset
  namespace; no local absolute paths in the public payload; unpublished trust
  assets remain null and read-only

Review screenshots are presentation evidence only; the JSON artifacts and
digests above remain authoritative.

| View | Screenshot SHA-256 |
| --- | --- |
| [Mini HOLD overview](../../screenshots/e1-mini-hold-overview.png) | `f42a3816d6d6c3c9ea0e6159d0c3f4cdb268a93eb89e7e57986e7ca648530608` |
| [Mini five-pane error explorer](../../screenshots/e1-mini-error-explorer.png) | `8a24a841cf55322a2d5fb3eb1fbc66b5bff39bb699e16d30fe2f7db66bbd10a0` |
| [Full calibration HOLD in Korean](../../screenshots/e1-full-calibration-hold-ko.png) | `99943dede339e85e3d44413902211ae715eb5e35b47ae3af260bdd2b55a32d7f` |

## Next protocol scope

Do not tune against these calibration or test results inside protocol `1.3.0`.
A future protocol version may use development-only work to improve scale
normalization residue rejection and affected-feature mapping, while retaining
this packet and both formal HOLD results unchanged. The v0.3.0 FreeCAD Vision
Evidence Contract remains deferred until E1 passes.

## Decision

`HOLD`
