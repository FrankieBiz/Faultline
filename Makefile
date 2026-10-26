.PHONY: check test lint typecheck build provenance frontend runner

BACKEND := apps/buggyshop-backend
UV := uv run --project $(BACKEND) --python 3.13 --locked
ORCHESTRATOR := services/repair-orchestrator
ORCHESTRATOR_UV := uv run --project $(ORCHESTRATOR) --python 3.13 --locked
FRONTEND := apps/buggyshop-frontend
RUNNER := tools/browser-runner

check: lint typecheck test provenance frontend runner build

frontend:
	cd $(FRONTEND) && npm run check

runner:
	cd $(RUNNER) && npm run check

test:
	$(UV) pytest $(BACKEND)/tests
	$(ORCHESTRATOR_UV) pytest $(ORCHESTRATOR)/tests

lint:
	$(UV) ruff check --config $(BACKEND)/pyproject.toml $(BACKEND) shared fixtures
	$(UV) ruff format --check --config $(BACKEND)/pyproject.toml $(BACKEND) shared fixtures
	$(ORCHESTRATOR_UV) ruff check --config $(ORCHESTRATOR)/pyproject.toml $(ORCHESTRATOR)
	$(ORCHESTRATOR_UV) ruff format --check --config $(ORCHESTRATOR)/pyproject.toml $(ORCHESTRATOR)

typecheck:
	cd $(BACKEND) && uv run --python 3.13 --locked mypy
	cd $(ORCHESTRATOR) && uv run --python 3.13 --locked mypy

provenance:
	$(UV) python -m fixtures.provenance

build:
	uv build --project $(BACKEND) --python 3.13 --no-sources
	uv build --project $(ORCHESTRATOR) --python 3.13 --no-sources
