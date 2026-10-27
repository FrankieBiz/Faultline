#!/usr/bin/env bash
# Verify recorded candidate evidence, without claiming a production deployment.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
API="${FAULTLINE_INSPECTOR_URL:-http://127.0.0.1:4000}/api/faultline"
for program in curl jq uv; do command -v "$program" >/dev/null || { echo "Missing $program" >&2; exit 1; }; done
request() { curl --fail-with-body --silent --show-error --max-time 10 "$@"; }
ready=$(request "$API/readiness")
if ! jq -e '.runtime_ready and (.quarantined | not) and .model.available' >/dev/null <<<"$ready"; then
  echo 'Repair unavailable. Inspect runtime/model readiness before recording.' >&2
  jq '{status, reason, runtime_ready, model: {provider: .model.provider, available: .model.available, reason: .model.reason}}' <<<"$ready"
  exit 1
fi
provider=$(jq -r '.model.provider' <<<"$ready")
model=$(jq -r '.model.model' <<<"$ready")
echo "Rehearsing candidate verification with provider=$provider model=$model"
if [ "$provider" = deterministic ]; then echo 'Deterministic rehearsal: this is not a live Meta trial.'; fi
key=$(uv run --project apps/buggyshop-backend --python 3.13 --locked python -c 'import uuid; print(uuid.uuid4())')
created=$(request -X POST "$API/jobs" -H 'Content-Type: application/json' -d "{\"scenario_id\":\"scripted_checkout_repair\",\"mode\":\"repair\",\"idempotency_key\":\"$key\"}")
job_id=$(jq -er '.job_id' <<<"$created")
started=$SECONDS
while (( SECONDS - started < 190 )); do
  detail=$(request "$API/jobs/$job_id")
  state=$(jq -r '.job.state' <<<"$detail")
  jq -r '"\(.job.state) / \(.job.stage) / \(.job.outcome // "pending")"' <<<"$detail"
  case "$state" in
    succeeded|failed|cancelled|interrupted)
      if ! jq -e '.job.state == "succeeded" and .job.outcome == "verified" and .job.cleanup_status == "succeeded" and (.baseline.report.verdict == "failed") and ([.executions[] | select(.phase == "verification") | .report | select(.verdict == "passed" and (.assertions | length > 0) and (.assertions | all(.passed)))] | length > 0)' >/dev/null <<<"$detail"; then
        echo "Rehearsal failed; inspect job $job_id in the Inspector." >&2
        exit 1
      fi
      jq '{job: .job.id, outcome: .job.outcome, cleanup: .job.cleanup_status, provider: .attempts[-1].validation_result.provider, model: .attempts[-1].validation_result.model, diff: .attempts[-1].parsed_diff, assertions: [.executions[] | select(.phase == "verification") | .report.assertions | length]}' <<<"$detail"
      echo "Candidate verified in $((SECONDS - started))s. The production fixture remains seeded."
      exit 0
      ;;
  esac
  sleep 1
done
echo "Job $job_id exceeded the rehearsal deadline; cancelling." >&2
request -X POST "$API/jobs/$job_id/cancel" >/dev/null || true
exit 1
