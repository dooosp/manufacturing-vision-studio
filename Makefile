.PHONY: setup lint typecheck test web-check e2e validate demo format

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

format:
	uv run ruff format .
	uv run ruff check --fix .
