# Frozen Coolgear integration evaluation v1

The machine-readable source is
[configs/integration/coolgear-r1-v1.json](../../configs/integration/coolgear-r1-v1.json).
It is frozen before this evaluation run. The existing model configuration and
whole-image threshold 0.0025 are unchanged. No E1 configuration, candidate
selection or historical result is modified.

Five smoke cases and ten evaluation cases use disjoint feature-local or nuisance
family groups. The previously observed H1 occlusion is retained only in smoke.
The same design and related transformations make these correlated synthetic
cases; the evaluation is descriptive and is not an independent population study.
Neither duplicated normal samples nor slight variants are presented as
independent evidence. Every reported denominator includes its case/group counts.
There is no fitting or threshold selection from these outputs.

The generator makes the image and truth mask independently of the detector.
Only the reference image, blind-named inspection image and preselected CAD ROIs
reach `inspect`. Expected feature IDs, defect parameters, seed and truth mask stay
in the evaluator. Expected revision remains R1 for nonconforming R1 samples.
Generation is a raster mutation; no imaginary defect CAD file/hash is invented.

Report classification TP/TN/FP/FN separately from feature mapping, unmapped pixels,
execution failures and human-review state. Exterior changes are outside the eight
hole ROIs. Registration translates inspection pixels into reference coordinates;
global translation and a local H4 shift are separate counterexamples. Out-of-frame
coverage is recorded rather than interpreted as inspected geometry.

R2 is a separate change-control demonstration: actual H4 X changes from 113 to
113.5 mm. Comparison with the unchanged R1 requirement (0.10 mm software comparison
tolerance) must fail. A normal image under the R2 reference does not approve that
design. Wrong-revision/part and byte-tamper refusal probes are integrity checks,
never added to visual detection accuracy. All scripted dispositions are identified
as automated, with no human approval or manufacturing release.

## Reproduction

From the MVS worktree, after preserving the selected producer files and the
separately reviewed R2 selection:

```sh
uv run python scripts/run_coolgear_integration.py \
  --protocol configs/integration/coolgear-r1-v1.json \
  --reference-export ../freecad-automation/output/mvs-reference/coolgear-r1 \
  --r2-export ../freecad-automation/output/mvs-reference/coolgear-r2-demo \
  --r2-selection ../freecad-automation/tmp/codex/freecad-mvs-baseline/r2-selected-source.json \
  --out-dir output/coolgear-integration/run-001
```

An existing output folder is refused. The output contains blind-named inputs,
separate truth masks, predicted masks/registered images, the exact protocol and
`results.json`. The R2 case and its verified bundle are separate from the detection
confusion matrix. A missing R2 selection cannot be filled by trusting the ZIP's
own hash declarations. Recreating the producer run can change its manifest bytes;
review a new selection/protocol version instead of rewriting the frozen v1 values.
