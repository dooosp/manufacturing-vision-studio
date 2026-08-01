# E1 v2 evaluation protocol

E1 v2 is an additive, deterministic synthetic-evaluation contract. It preserves
the E1 v1.3 HOLD artifacts as immutable history and uses four separately seeded
scopes: 120 development cases, 48 smoke cases, 120 calibration cases, and 240
release-test cases. Smoke is not a release subset and is never a release claim.

E1 v1.3 calibration and mini test results were observed. Their calibration/test
cases are retired from future release-gate use. They may be reused only as
development diagnostics.

The locked image threshold remains `0.0025`. The release gates remain medium/high
defect recall at least `0.90`, nuisance-only false-positive rate at most `0.05`,
positive-case median Dice at least `0.70`, and affected-feature mapping accuracy
at least `0.95`, with the existing integrity gates unchanged.

Each v2 plan has a scope-specific case ID, recipe ID, seed family, and contiguous
seed. Rendered records bind both source-image hashes, the authoritative-mask hash,
expected outcome, defect ID, and the v2 case-binding hash. The overlap proof is
recomputed from its declared membership and allows repeated raw empty masks only
for declared clean or nuisance negatives; non-empty mask hashes are leak keys.

The checked-in retired-v1 membership is self-hashed and binds the v1.3 canonical
config and historical mini/full manifests. `python scripts/verify_e1_v1_history.py`
verifies the public v1 config, schemas, result summaries, HOLD packet, v0.1
bundle, and recorded commit/tag identities without depending on ignored runtime
artifacts.
