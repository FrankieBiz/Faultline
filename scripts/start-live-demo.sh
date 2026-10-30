#!/usr/bin/env bash
# Run only the backend live repair service, with no browser or frontend builds.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
command -v uv >/dev/null || { echo "Required command missing: uv" >&2; exit 1; }
uv sync --project services/repair-orchestrator --python 3.13 --locked
export PYTHONPATH="$ROOT"
export FAULTLINE_RUNTIME=isolated
# Resolve relative storage paths from the repository, not uvicorn's service cwd.
export LIVE_DEMO_DATA_DIR="${LIVE_DEMO_DATA_DIR:-$ROOT/data/live-demo}"
if [[ "$LIVE_DEMO_DATA_DIR" != /* ]]; then
  export LIVE_DEMO_DATA_DIR="$ROOT/$LIVE_DEMO_DATA_DIR"
fi
cd "$ROOT/services/repair-orchestrator"
exec uv run --python 3.13 --locked uvicorn app.live_demo:create_app --factory \
  --host 127.0.0.1 --port "${LIVE_DEMO_PORT:-9600}" --workers 1 \
  --no-proxy-headers --no-access-log
