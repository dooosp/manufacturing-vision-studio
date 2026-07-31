.PHONY: setup lint typecheck test web-check e2e validate demo format \
	evaluate-e1-mini evaluate-e1-full verify-e1-mini verify-e1-full verify-e1-results

E1_OUTPUT_ROOT ?= data/e1-evaluation

setup:
	uv sync --all-groups
	npm --prefix web ci
	npm --prefix web exec playwright -- install --with-deps chromium

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest

web-check:
	npm --prefix web run check

e2e:
	npm --prefix web run test:e2e

validate:
	uv run ruff check .
	uv run mypy src
	uv run pytest
	npm --prefix web run check
	npm --prefix web run test:e2e

demo:
	uv run python scripts/run_local.py

evaluate-e1-mini:
	uv run mvs-e1 --output-root $(E1_OUTPUT_ROOT) evaluate --profile mini

evaluate-e1-full:
	uv run mvs-e1 --output-root $(E1_OUTPUT_ROOT) evaluate --profile full

verify-e1-mini:
	uv run mvs-e1 --output-root $(E1_OUTPUT_ROOT) verify --profile mini

verify-e1-full:
	uv run mvs-e1 --output-root $(E1_OUTPUT_ROOT) verify --profile full

verify-e1-results: verify-e1-mini verify-e1-full

format:
	uv run ruff format .
	uv run ruff check --fix .
