#!/usr/bin/env bash
# Reconcile owned runtime resources. Preserve source and durable evidence.
set -euo pipefail
API="${FAULTLINE_INSPECTOR_URL:-http://127.0.0.1:4000}/api/faultline"
curl --fail-with-body --silent --show-error --max-time 20 -X POST "$API/reset"
printf '\nRuntime reconciliation requested; job history is retained.\n'
