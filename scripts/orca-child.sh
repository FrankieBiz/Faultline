#!/usr/bin/env bash
set -euo pipefail

# FaultLine Orca Child Dispatch & Orchestration Helper
# Strictly dispatches real Orca child agents (Codex / Claude) in dedicated worktrees.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve orca CLI binary
resolve_orca() {
  if command -v orca >/dev/null 2>&1; then
    echo "orca"
  elif [[ -x "/home/frankbiz/.config/orca/linux-orca-cli-shim/orca" ]]; then
    echo "/home/frankbiz/.config/orca/linux-orca-cli-shim/orca"
  elif command -v orca-ide >/dev/null 2>&1; then
    echo "orca-ide"
  else
    echo "Error: Orca CLI not found in PATH or ~/.config/orca/linux-orca-cli-shim/orca" >&2
    exit 1
  fi
}

ORCA_BIN="$(resolve_orca)"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/orca-child.sh spawn <codex|claude> <worktree-name> <prompt>
  ./scripts/orca-child.sh list
  ./scripts/orca-child.sh status <worktree-name>
  ./scripts/orca-child.sh read <worktree-name> [limit]
  ./scripts/orca-child.sh merge <worktree-name>
  ./scripts/orca-child.sh clean <worktree-name>

Frontier Model Defaults:
  codex  -> gpt-6-astra (effort: high)
  claude -> claude-opus-5-5 (effort: high)
EOF
  exit 1
}

cmd_spawn() {
  local agent="${1:-}"
  local name="${2:-}"
  local prompt="${3:-}"

  if [[ -z "$agent" || -z "$name" || -z "$prompt" ]]; then
    echo "Error: spawn requires <agent> <worktree-name> <prompt>" >&2
    usage
  fi

  local model=""
  local effort="high"

  case "$agent" in
    codex)
      model="gpt-6-astra"
      effort="high"
      ;;
    claude)
      model="claude-opus-5-5"
      effort="high"
      ;;
    *)
      echo "Error: Unsupported agent '$agent'. Must be 'codex' or 'claude'." >&2
      exit 1
      ;;
  esac

  echo "==> Spawning real Orca child: ${agent} (${model}) in worktree '${name}'" >&2
  local output
  output="$("$ORCA_BIN" worktree create \
    --name "$name" \
    --agent "$agent" \
    --model "$model" \
    --effort "$effort" \
    --prompt "$prompt" \
    --activate \
    --json)"

  local ok
  ok="$(echo "$output" | jq -r '.ok // false')"
  if [[ "$ok" != "true" ]]; then
    echo "Error: Failed to create Orca child worktree:" >&2
    echo "$output" | jq . >&2
    exit 1
  fi

  local wt_path
  local branch
  wt_path="$(echo "$output" | jq -r '.result.worktree.path')"
  branch="$(echo "$output" | jq -r '.result.worktree.branch')"

  echo "==> Child worktree created at: ${wt_path}" >&2
  echo "==> Branch: ${branch}" >&2
  echo ""
  echo "### Active Orca Children Spun Up:"
  echo "- **${agent^}** (\`${model}\` via Orca worktree \`${name}\`): ${prompt:0:80}..."
  echo ""
  echo "{\"ok\": true, \"agent\": \"$agent\", \"model\": \"$model\", \"worktree\": \"$name\", \"path\": \"$wt_path\", \"branch\": \"$branch\"}"
}

cmd_list() {
  "$ORCA_BIN" worktree list --json | jq -r '
    .result.worktrees[]
    | select(.projectId == "github:frankiebiz/faultline")
    | "\(.displayName) | agent: \(.createdWithAgent // "none") | branch: \(.branch) | path: \(.path)"
  '
}

cmd_status() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    echo "Error: status requires <worktree-name>" >&2
    exit 1
  fi

  local wt_path="/home/frankbiz/orca/workspaces/Faultline/${name}"
  if [[ ! -d "$wt_path" ]]; then
    wt_path="$name"
  fi

  "$ORCA_BIN" terminal list --worktree "path:${wt_path}" --json | jq -r '
    .result.terminals[]
    | "Terminal: \(.handle) | Agent: \(.agentIdentity // "unknown") | Title: \(.title)\nPreview: \(.preview // "no preview")\n---"
  '
}

cmd_read() {
  local name="${1:-}"
  local limit="${2:-50}"
  if [[ -z "$name" ]]; then
    echo "Error: read requires <worktree-name>" >&2
    exit 1
  fi

  local wt_path="/home/frankbiz/orca/workspaces/Faultline/${name}"
  if [[ ! -d "$wt_path" ]]; then
    wt_path="$name"
  fi

  local term_handle
  term_handle="$("$ORCA_BIN" terminal list --worktree "path:${wt_path}" --json | jq -r '.result.terminals[0].handle // empty')"
  if [[ -z "$term_handle" ]]; then
    echo "Error: No active terminal handle found for worktree '${name}'" >&2
    exit 1
  fi

  "$ORCA_BIN" terminal read --terminal "$term_handle" --limit "$limit"
}

cmd_merge() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    echo "Error: merge requires <worktree-name>" >&2
    exit 1
  fi

  local wt_path="/home/frankbiz/orca/workspaces/Faultline/${name}"
  if [[ ! -d "$wt_path" ]]; then
    echo "Error: Worktree path ${wt_path} does not exist" >&2
    exit 1
  fi

  local branch
  branch="$(git -C "$wt_path" rev-parse --abbrev-ref HEAD)"
  echo "==> Fetching branch '${branch}' from child worktree '${wt_path}'"
  git fetch "$wt_path" "$branch"
  echo "==> Merging FETCH_HEAD..."
  git merge --no-edit FETCH_HEAD
  echo "==> Running verification gate: make check"
  make check
  echo "==> Child worktree '${name}' merged and verified successfully!"
}

cmd_clean() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    echo "Error: clean requires <worktree-name>" >&2
    exit 1
  fi

  echo "==> Removing child worktree: ${name}"
  "$ORCA_BIN" worktree rm --worktree "name:${name}" --force --json | jq .
}

case "${1:-}" in
  spawn)
    shift
    cmd_spawn "$@"
    ;;
  list)
    cmd_list
    ;;
  status)
    shift
    cmd_status "$@"
    ;;
  read)
    shift
    cmd_read "$@"
    ;;
  merge)
    shift
    cmd_merge "$@"
    ;;
  clean)
    shift
    cmd_clean "$@"
    ;;
  *)
    usage
    ;;
esac
