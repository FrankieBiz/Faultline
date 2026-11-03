#!/usr/bin/env bash
# Run both suites deterministically by default; --suite selects the configured provider.
# Candidate code runs only in the isolated runtime; results are retained under data/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
explicit_suite=false
for argument in "$@"; do
  case "$argument" in
    --suite|--suite=*) explicit_suite=true ;;
  esac
done
if "$explicit_suite" && [ -f "$ROOT/.env" ]; then
  # Read .env defaults without clobbering existing environment overrides
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    varname="${line%%=*}"
    varname="$(echo "$varname" | tr -d '[:space:]')"
    if [ -n "$varname" ] && [ -z "${!varname+x}" ]; then
      eval "export $line"
    fi
  done < "$ROOT/.env"
fi
cd "$ROOT/services/repair-orchestrator"
exec env PYTHONPATH="$ROOT" uv run --python 3.13 --locked python -m app.evaluation "$@"
