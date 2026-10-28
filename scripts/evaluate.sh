#!/usr/bin/env bash
# Evaluate the configured provider and the gates on the authored corpus.
# Candidate code runs only in the isolated runtime; results are retained under data/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then
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
arguments=("$@")
case " ${arguments[*]-} " in
  *" --out "*|*" --out="*) ;;
  *) arguments+=(--out "$ROOT/data/evaluations/$(date -u +%Y%m%dT%H%M%SZ)") ;;
esac
cd "$ROOT/services/repair-orchestrator"
exec env PYTHONPATH="$ROOT" uv run --python 3.13 --locked python -m app.evaluation "${arguments[@]}"
