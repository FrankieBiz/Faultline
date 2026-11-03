#!/usr/bin/env bash
# Run only the backend live repair service, with no browser or frontend builds.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
check=0
case "${1:-}" in
  '') ;;
  --check|--dry-run) check=1 ;;
  --help|-h)
    cat <<'EOF'
Usage: scripts/start-live-demo.sh [--check]

  (no flags)  Start the live repair service on 127.0.0.1:${LIVE_DEMO_PORT:-9600}.
  --check     Report prerequisites, provider settings, and the port, then exit
              without syncing dependencies or starting anything. Never prints secrets.
EOF
    exit 0 ;;
  *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
esac
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
if [ "$check" = 1 ]; then
  failures=0
  report() { # report ok|warn|fail MESSAGE
    printf '  %-4s %s\n' "$1" "$2"
    if [ "$1" = fail ]; then failures=$((failures + 1)); fi
  }
  port="${LIVE_DEMO_PORT:-9600}"
  echo "Live repair service preflight (nothing will be started):"
  if command -v uv >/dev/null; then report ok 'uv found'; else report fail 'uv missing'; fi
  if command -v bwrap >/dev/null; then report ok 'Bubblewrap found'; else report fail 'Bubblewrap (bwrap) missing; candidates cannot run isolated'; fi
  if [ -f /sys/fs/cgroup/cgroup.controllers ]; then report ok 'cgroup v2 mounted'; else report fail 'cgroup v2 not mounted at /sys/fs/cgroup'; fi
  if systemctl --user show-environment >/dev/null 2>&1; then report ok 'systemd user session reachable'; else report fail 'no systemd user session; aggregate limits need one'; fi
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then report fail "127.0.0.1:$port is already in use (set LIVE_DEMO_PORT)"; else report ok "127.0.0.1:$port is free"; fi
  if [ -n "${META_API_KEY:-}${MODEL_API_KEY:-}" ]; then report ok 'model credential set'; else report warn 'no META_API_KEY or MODEL_API_KEY; runs use the labeled deterministic provider'; fi
  required="${LIVE_DEMO_REQUIRE_PROVIDER:-}"
  if [ -z "$required" ]; then
    report warn 'LIVE_DEMO_REQUIRE_PROVIDER unset; production pins it to meta'
  elif [ "$required" = meta ] && [ -z "${META_API_KEY:-}" ]; then
    report fail 'LIVE_DEMO_REQUIRE_PROVIDER=meta but META_API_KEY is unset'
  else
    report ok "LIVE_DEMO_REQUIRE_PROVIDER=$required"
  fi
  data="${LIVE_DEMO_DATA_DIR:-$ROOT/data/live-demo}"
  [[ "$data" == /* ]] || data="$ROOT/$data"
  report ok "ledger and runs kept in $data"
  if [ "$failures" -gt 0 ]; then echo "$failures check(s) failed." >&2; exit 1; fi
  echo "Ready. Start the service with ./scripts/start-live-demo.sh"
  exit 0
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
