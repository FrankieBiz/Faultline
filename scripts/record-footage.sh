#!/usr/bin/env bash
# Record FaultLine demo footage clips into data/footage/<timestamp>/ (see docs/VIDEO_STORYBOARD.md).
# The demo stack and any live service must already be running; this script never starts or stops them.
# --serve-docs PORT is the one exception: it serves docs/ on 127.0.0.1:PORT for the duration of the
# recording and stops that server afterwards.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = -h ] || [ "${1:-}" = --help ]; then
  cat <<'EOF'
Usage: scripts/record-footage.sh [--serve-docs PORT] [recorder options]

  --serve-docs PORT   Serve docs/ on http://127.0.0.1:PORT/ while recording (and pass it
                      as --docs-url). Without it, pass --docs-url for a server you run.

Recorder options (tools/browser-runner/footage/record.mjs):
EOF
  exec node tools/browser-runner/footage/record.mjs --help
fi

[ -d tools/browser-runner/node_modules/@playwright/test ] || {
  echo "Missing tools/browser-runner dependencies. Run make setup first." >&2; exit 1;
}
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) process.exit(1)' || {
  echo "Node.js 24 or newer is required." >&2; exit 1;
}

args=()
docs_port=""
while [ $# -gt 0 ]; do
  case "$1" in
    --serve-docs) docs_port="${2:-}"; shift 2 || { echo "--serve-docs needs a port." >&2; exit 1; } ;;
    --serve-docs=*) docs_port="${1#*=}"; shift ;;
    *) args+=("$1"); shift ;;
  esac
done

server=""
cleanup() {
  if [ -n "$server" ]; then
    kill -TERM -- "-$server" 2>/dev/null || true
    wait "$server" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -n "$docs_port" ]; then
  [[ "$docs_port" =~ ^[0-9]+$ ]] && [ "$docs_port" -ge 1 ] && [ "$docs_port" -le 65535 ] || {
    echo "--serve-docs needs a port number." >&2; exit 1;
  }
  if curl --silent --max-time 1 "http://127.0.0.1:$docs_port/" >/dev/null 2>&1; then
    echo "Port $docs_port is already serving something; use --docs-url http://127.0.0.1:$docs_port/ instead." >&2
    exit 1
  fi
  setsid uv run --no-project python -m http.server "$docs_port" --bind 127.0.0.1 --directory docs \
    >/dev/null 2>&1 </dev/null &
  server=$!
  for attempt in {1..40}; do
    curl --fail --silent --max-time 1 "http://127.0.0.1:$docs_port/index.html" >/dev/null 2>&1 && break
    kill -0 "$server" 2>/dev/null || { echo "The docs server exited; is port $docs_port free?" >&2; server=""; exit 1; }
    sleep 0.25
  done
  args=(--docs-url "http://127.0.0.1:$docs_port/" "${args[@]}")
fi

node tools/browser-runner/footage/record.mjs "${args[@]}"
