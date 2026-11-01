#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

find_uv() {
  command -v uv >/dev/null 2>&1 && return 0
  local directory
  for directory in "$HOME/.local/bin" "$HOME/.cargo/bin" /opt/homebrew/bin /usr/local/bin; do
    if [ -x "$directory/uv" ]; then
      export PATH="$directory:$PATH"
      return 0
    fi
  done
  return 1
}
if ! find_uv; then
  command -v curl >/dev/null 2>&1 || {
    echo "curl is required to install uv. Install curl, then run make setup again." >&2
    exit 1
  }
  echo "Installing uv from https://astral.sh/uv/install.sh ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  find_uv || { echo "uv installation did not provide uv. Add it to PATH and run make setup again." >&2; exit 1; }
fi
for program in node npm npx; do
  command -v "$program" >/dev/null 2>&1 || {
    echo "Missing $program. Install Node.js 24+ (including npm), then run make setup again." >&2
    exit 1
  }
done
# Next needs 20.9; the locked ESLint toolchain needs 20.19 / 22.13.
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 13) || major >= 24)) process.exit(1)' || {
  echo "Node.js 20.19+, 22.13+, or 24+ is required by the locked dependencies; Node.js 24+ is recommended." >&2
  exit 1
}
uv python install 3.13
uv sync --project apps/buggyshop-backend --python 3.13 --locked
uv sync --project services/repair-orchestrator --python 3.13 --locked
for project in apps/buggyshop-frontend tools/browser-runner web/inspector-ui; do
  npm --prefix "$project" ci
done
npm --prefix tools/browser-runner run build
(cd tools/browser-runner && npx playwright install chromium)
