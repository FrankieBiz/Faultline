.PHONY: setup check test lint typecheck build provenance frontend runner inspector browser integration evaluate

BACKEND := apps/buggyshop-backend
UV := uv run --project $(BACKEND) --python 3.13 --locked
ORCHESTRATOR := services/repair-orchestrator
ORCHESTRATOR_UV := uv run --project $(ORCHESTRATOR) --python 3.13 --locked
FRONTEND := apps/buggyshop-frontend
RUNNER := tools/browser-runner
INSPECTOR := web/inspector-ui

check: lint typecheck test provenance frontend runner inspector build

setup:
	./scripts/setup.sh

integration: frontend runner
	FAULTLINE_REQUIRE_ISOLATED_TESTS=1 $(ORCHESTRATOR_UV) pytest $(ORCHESTRATOR)/tests/test_isolated_runtime.py $(ORCHESTRATOR)/tests/test_resource_limits_cgroup.py

browser:
	cd $(RUNNER) && npm run test:inspector

frontend:
	cd $(FRONTEND) && npm run check

runner:
	cd $(RUNNER) && npm run check

inspector:
	cd $(INSPECTOR) && npm run check

test:
	$(UV) pytest $(BACKEND)/tests tests
	$(ORCHESTRATOR_UV) pytest $(ORCHESTRATOR)/tests

lint:
	$(UV) ruff check --config $(BACKEND)/pyproject.toml $(BACKEND) shared fixtures tests
	$(UV) ruff format --check --config $(BACKEND)/pyproject.toml $(BACKEND) shared fixtures tests
	$(ORCHESTRATOR_UV) ruff check --config $(ORCHESTRATOR)/pyproject.toml $(ORCHESTRATOR)
	$(ORCHESTRATOR_UV) ruff format --check --config $(ORCHESTRATOR)/pyproject.toml $(ORCHESTRATOR)

typecheck:
	cd $(BACKEND) && uv run --python 3.13 --locked mypy
	cd $(ORCHESTRATOR) && uv run --python 3.13 --locked mypy

provenance:
	$(UV) python -m fixtures.provenance
	$(UV) python -m fixtures.evaluation.corpus

evaluate:
	./scripts/evaluate.sh

build:
	uv build --project $(BACKEND) --python 3.13 --no-sources
	uv build --project $(ORCHESTRATOR) --python 3.13 --no-sources
