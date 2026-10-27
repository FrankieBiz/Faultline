#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
uv sync --project apps/buggyshop-backend --python 3.13 --locked
uv sync --project services/repair-orchestrator --python 3.13 --locked
for project in apps/buggyshop-frontend tools/browser-runner web/inspector-ui; do
  npm --prefix "$project" ci
done
(cd tools/browser-runner && npx playwright install chromium)
