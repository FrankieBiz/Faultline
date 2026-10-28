#!/usr/bin/env bash
# Terminal walkthrough built only from measurements taken during this run:
# the isolated runtime's enforcement probe, the registered defect reproduced and
# repaired under the gates, and plausible wrong repairs rejected. Every line of
# output is read from the probe result or the evaluation's results.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for program in uv jq; do
  command -v "$program" >/dev/null || { echo "Required command missing: $program" >&2; exit 1; }
done
if [ -t 1 ]; then
  BOLD=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GREEN=$'\e[32m' AMBER=$'\e[33m' RESET=$'\e[0m'
else
  BOLD='' DIM='' RED='' GREEN='' AMBER='' RESET=''
fi
step() { printf '\n%s%s%s\n' "$BOLD" "$1" "$RESET"; }
OUT="$(mktemp -d /tmp/faultline-walkthrough-XXXXXX)"

step "1. Isolated runtime preflight"
(cd "$ROOT/services/repair-orchestrator" && env PYTHONPATH="$ROOT" \
  uv run --python 3.13 --locked python - > "$OUT/preflight.json") <<'PY'
import asyncio, json
from app.isolated_runtime import IsolatedRuntime
from app.runtime import RuntimeUnavailable

runtime = IsolatedRuntime()
try:
    asyncio.run(runtime.backend_preflight())
except RuntimeUnavailable as exc:
    print(json.dumps({"ready": False, "reason": str(exc), **runtime.resource_limits_status}))
else:
    print(json.dumps({"ready": True, **runtime.resource_limits_status}))
PY
if ! jq -e '.ready' "$OUT/preflight.json" >/dev/null; then
  printf '%sRuntime not ready: %s%s\n' "$RED" "$(jq -r '.reason' "$OUT/preflight.json")" "$RESET"
  exit 1
fi
jq -r --arg ok "$GREEN" --arg dim "$DIM" --arg r "$RESET" '
  if .requested == "disabled" then "  \($ok)Sandbox ready\($r); aggregate limits disabled by the operator"
  else
    "  \($ok)Sandbox and aggregate limits enforced\($r) (\(.configured.memory_max_bytes / 1048576) MiB, \(.configured.tasks_max) tasks, \(.configured.cpu_quota_percent)% CPU, no swap)",
    "  \($dim)Probe: memory hog exit \(.probe.hog_exit_code), oom_kill events \(.probe.oom_kill_events), threads started \(.probe.threads_started) of 64 attempted\($r)"
  end' "$OUT/preflight.json"

step "2. Reproduce the registered defect, then repair it under the gates"
CASES="seeded_missing_coupon,reference_default_zero,null_coupon_only,zero_all_discounts,early_return_unsaved,debug_logging_import"
"$ROOT/scripts/evaluate.sh" --suite all --cases "$CASES" --out "$OUT/evaluation" > "$OUT/evaluation.log"
RESULTS="$OUT/evaluation/results.json"
jq -r --arg bad "$RED" --arg ok "$GREEN" --arg warn "$AMBER" --arg dim "$DIM" --arg r "$RESET" '
  .holdout.cases[0] as $case
  | "  Provider: \(.provider.provider) · \(.provider.model) (\(.classification))",
    "  \($bad)Baseline failed \($case.baseline_failures | length) of 27 business checks\($r): \($case.baseline_failures | join(", "))",
    ($case.attempts[] |
      "  Attempt \(.attempt_number): \(.outcome)"
      + (if .policy then " · policy \(if .policy.is_valid then "pass" else "reject" end)" else "" end)
      + (if .failing_after then " · \(27 - (.failing_after | length)) of 27 checks passed" else "" end)),
    (if $case.outcome == "verified" then "  \($ok)Candidate verified in a fresh isolated backend\($r)"
     else "  \($warn)Not verified: \($case.outcome)\($r)" end),
    "  \($dim)Diff:\($r)",
    ($case.attempts[-1].diff // "" | split("\n")[] | select(length > 0) | "    \(.)")' "$RESULTS"

step "3. Plausible repairs: a symptom check versus FaultLine"
jq -r --arg bad "$RED" --arg ok "$GREEN" --arg r "$RESET" '
  .patches.cases[] |
  "  \(.id) (\(.kind | gsub("_"; " "))): symptom check "
  + (if .symptom_check_accepts == null then "not run" elif .symptom_check_accepts then "accepts" else "rejects" end)
  + ", FaultLine " + (if .faultline_accepts then "\($ok)accepts\($r)" else "\($bad)rejects\($r)" end)
  + (if (.failing | length) > 0 then " · \(.failing | length) failing checks"
     elif .policy.is_valid | not then " · policy: \(.policy.error)" else "" end)' "$RESULTS"

step "4. Containment record"
jq -r '"  \(.runtime_limits.verified_sessions) of \(.runtime_limits.sessions) backend sessions ran under kernel-verified limits"' "$RESULTS"
printf '\nMeasured results: %s\nSummary: %s\n' "$RESULTS" "$OUT/evaluation/summary.md"
