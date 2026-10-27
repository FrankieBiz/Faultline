#!/usr/bin/env bash
# Supervised FaultLine Demo Startup Script
# Boots the BuggyShop backend (8000), BuggyShop storefront (3000),
# Repair Orchestrator (9000), and Inspector UI (4000).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

echo "=== Pre-flight: Running workspace reset ==="
"$ROOT/scripts/reset.sh"

echo "=== Starting BuggyShop Backend on 127.0.0.1:8000 ==="
(cd "$ROOT/apps/buggyshop-backend" && \
  PYTHONPATH="$ROOT" uv run --project . --python 3.13 --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning) &
PID_BACKEND=$!

echo "=== Starting Repair Orchestrator on 127.0.0.1:9000 ==="
(cd "$ROOT/services/repair-orchestrator" && \
  PYTHONPATH="$ROOT" FAULTLINE_DEMO_RUNTIME="1" FAULTLINE_CONTROL_TOKEN="${FAULTLINE_CONTROL_TOKEN:-dev-control-token}" \
  uv run --project . --python 3.13 --locked uvicorn app.main:app --host 127.0.0.1 --port 9000 --log-level warning) &
PID_ORCHESTRATOR=$!

echo "=== Starting BuggyShop Frontend on 127.0.0.1:3000 ==="
(cd "$ROOT/apps/buggyshop-frontend" && \
  PORT=3000 BUGGYSHOP_BACKEND_URL="http://127.0.0.1:8000" npx next start -p 3000 -H 127.0.0.1) &
PID_FRONTEND=$!

PID_INSPECTOR=""
if [ ! -d "$ROOT/web/inspector-ui/.next" ]; then
  echo "=== Building Inspector UI ==="
  (cd "$ROOT/web/inspector-ui" && npm run build)
fi
echo "=== Starting Inspector UI on 127.0.0.1:4000 ==="
(cd "$ROOT/web/inspector-ui" && \
  PORT=4000 FAULTLINE_CONTROL_TOKEN="${FAULTLINE_CONTROL_TOKEN:-dev-control-token}" npx next start -p 4000 -H 127.0.0.1) &
PID_INSPECTOR=$!

cleanup() {
  echo ""
  echo "=== Shutting down FaultLine demo processes ==="
  kill -9 "$PID_BACKEND" "$PID_ORCHESTRATOR" "$PID_FRONTEND" ${PID_INSPECTOR:+"$PID_INSPECTOR"} 2>/dev/null || true
  exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "=== Waiting for service health checks ==="
until curl -s http://127.0.0.1:8000/healthz | grep -q "ok"; do sleep 0.5; done
echo "✓ BuggyShop Backend ready at http://127.0.0.1:8000"

until curl -s http://127.0.0.1:9000/healthz | grep -q "ok"; do sleep 0.5; done
echo "✓ Repair Orchestrator ready at http://127.0.0.1:9000"

until curl -s http://127.0.0.1:3000 >/dev/null; do sleep 0.5; done
echo "✓ BuggyShop Frontend ready at http://127.0.0.1:3000"

if [ -n "$PID_INSPECTOR" ]; then
  until curl -s http://127.0.0.1:4000 >/dev/null; do sleep 0.5; done
  echo "✓ Inspector UI ready at http://127.0.0.1:4000"
fi

echo ""
echo "=========================================================="
echo "  FAULTLINE DEMO STACK IS RUNNING"
echo "  Inspector:         http://127.0.0.1:4000"
echo "  BuggyShop Store:   http://127.0.0.1:3000"
echo "  Orchestrator API:  http://127.0.0.1:9000"
echo "  BuggyShop API:     http://127.0.0.1:8000"
echo "=========================================================="
echo "Press Ctrl+C to stop all services."

wait
