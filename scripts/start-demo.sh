#!/usr/bin/env bash
# Start only owned demo processes; retain job history and the seeded source.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
BACKEND_PORT="${BUGGYSHOP_API_PORT:-8000}"
CONTROL_PORT="${FAULTLINE_PORT:-9000}"
STORE_PORT="${BUGGYSHOP_PORT:-3000}"
UI_PORT="${INSPECTOR_PORT:-4000}"
for program in uv node npm curl setsid; do
  command -v "$program" >/dev/null || { echo "Required command missing: $program" >&2; exit 1; }
done
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) process.exit(1)' || {
  echo "Node.js 24 or newer is required." >&2; exit 1;
}
# Detect collisions without killing unrelated services or resetting data.
uv run --project apps/buggyshop-backend --python 3.13 --locked python - "$BACKEND_PORT" "$CONTROL_PORT" "$STORE_PORT" "$UI_PORT" <<'PY'
import socket
import sys
ports = [int(value) for value in sys.argv[1:]]
if len(set(ports)) != 4 or any(not 1 <= port <= 65535 for port in ports):
    raise SystemExit('Demo ports must be distinct integers between 1 and 65535.')
names = ['BUGGYSHOP_API_PORT', 'FAULTLINE_PORT', 'BUGGYSHOP_PORT', 'INSPECTOR_PORT']
occupied = []
for name, port in zip(names, ports):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            occupied.append(f'{port} ({name})')
if occupied:
    raise SystemExit(
        'Occupied: ' + ', '.join(occupied) + '. Stop their owners, or choose free ports, for example:\n'
        '  BUGGYSHOP_API_PORT=8400 FAULTLINE_PORT=9400 BUGGYSHOP_PORT=3400 INSPECTOR_PORT=4400 ./scripts/start-demo.sh'
    )
PY
for project in apps/buggyshop-frontend tools/browser-runner web/inspector-ui; do
  if [ ! -d "$project/node_modules" ]; then
    echo "Missing dependencies in $project. Run make setup first." >&2
    exit 1
  fi
done
uv sync --project services/repair-orchestrator --python 3.13 --locked
npm --prefix tools/browser-runner run build
npm --prefix apps/buggyshop-frontend run build
npm --prefix web/inspector-ui run build
# Generate one session credential if the owner did not supply one. Never print it.
FAULTLINE_CONTROL_TOKEN="${FAULTLINE_CONTROL_TOKEN:-$(uv run --project apps/buggyshop-backend --python 3.13 --locked python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export FAULTLINE_CONTROL_TOKEN
children=()
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  for pid in "${children[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  for attempt in {1..30}; do
    local alive=0
    for pid in "${children[@]}"; do kill -0 -- "-$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.1
  done
  for pid in "${children[@]}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
  for pid in "${children[@]}"; do wait "$pid" 2>/dev/null || true; done
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
start() {
  local directory=$1
  shift
  (cd "$ROOT/$directory"; exec setsid "$@") &
  children+=("$!")
}
start apps/buggyshop-backend env PYTHONPATH="$ROOT" uv run --python 3.13 --locked uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload --reload-dir "$ROOT/apps/buggyshop-backend" --log-level warning
start services/repair-orchestrator env PYTHONPATH="$ROOT" FAULTLINE_RUNTIME=isolated uv run --python 3.13 --locked uvicorn app.main:app --host 127.0.0.1 --port "$CONTROL_PORT" --log-level warning
start apps/buggyshop-frontend env BUGGYSHOP_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT" node node_modules/next/dist/bin/next start -p "$STORE_PORT" -H 127.0.0.1
start web/inspector-ui env BUGGYSHOP_PORT="$STORE_PORT" FAULTLINE_ORCHESTRATOR_URL="http://127.0.0.1:$CONTROL_PORT" node node_modules/next/dist/bin/next start -p "$UI_PORT" -H 127.0.0.1
for url in "http://127.0.0.1:$BACKEND_PORT/healthz" "http://127.0.0.1:$CONTROL_PORT/healthz" "http://127.0.0.1:$STORE_PORT" "http://127.0.0.1:$UI_PORT"; do
  ready=0
  for attempt in {1..120}; do
    for pid in "${children[@]}"; do
      kill -0 "$pid" 2>/dev/null || { echo "A demo service exited during startup." >&2; exit 1; }
    done
    if curl --fail --silent --max-time 1 "$url" >/dev/null; then ready=1; break; fi
    sleep 0.25
  done
  [ "$ready" = 1 ] || { echo "Service did not become healthy: $url" >&2; exit 1; }
done
printf '\nFaultLine is running at http://127.0.0.1:%s\nStorefront: http://127.0.0.1:%s\n' "$UI_PORT" "$STORE_PORT"
echo 'Readiness is shown in the Inspector. Ctrl+C stops this session; evidence is retained.'
if [ "$UI_PORT" != 4000 ]; then
  printf 'Rehearse against this stack with: FAULTLINE_INSPECTOR_URL=http://127.0.0.1:%s ./scripts/rehearse-demo.sh\n' "$UI_PORT"
fi
wait -n "${children[@]}"
