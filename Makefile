.PHONY: check test lint typecheck build provenance

BACKEND := apps/buggyshop-backend
UV := uv run --project $(BACKEND) --python 3.13 --locked

check: lint typecheck test provenance build

test:
	$(UV) pytest $(BACKEND)/tests

lint:
	$(UV) ruff check --config $(BACKEND)/pyproject.toml $(BACKEND) shared fixtures
	$(UV) ruff format --check --config $(BACKEND)/pyproject.toml $(BACKEND) shared fixtures

typecheck:
	cd $(BACKEND) && uv run --python 3.13 --locked mypy

provenance:
	$(UV) python -m fixtures.provenance

build:
	uv build --project $(BACKEND) --python 3.13 --no-sources
