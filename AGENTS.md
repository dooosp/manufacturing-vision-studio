# AGENTS.md

## Repository identity

This repository is `manufacturing-vision-studio`, a standalone local-first
industrial visual-inspection demo. The sibling `freecad-automation` and
`b2b-lead-agent` repositories are read-only references and must never be
modified from this project.

## Product boundary

- Build for portfolio-grade `DEMO_READY`, not production inspection.
- Use deterministic synthetic data as the checked-in demo.
- Keep every automated result tied to part ID, CAD revision, pipeline version,
  configuration hash, source-image hashes, and explicit human disposition.
- Fail closed on identity mismatches, malformed or unsafe input, incomplete
  evidence, and verification failures.
- Never claim shop-floor, safety, or real manufacturing validation.

## Commands

- Python setup: `uv sync --all-groups`
- Python lint: `uv run ruff check .`
- Python typecheck: `uv run mypy src`
- Python tests: `uv run pytest`
- Web setup: `npm --prefix web install`
- Web checks: `npm --prefix web run check`
- Browser E2E: `npm --prefix web run test:e2e`
- Full validation: `make validate`

## Collaboration

- Preserve edits made by other agents and the user.
- Respect assigned file ownership; coordinate before editing another stream's
  files.
- Do not weaken tests or trust boundaries to make validation pass.
- Record known limitations honestly and keep the demo entirely local.

