#!/usr/bin/env bash
# Verify recorded candidate evidence, without claiming a production deployment.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
usage() {
  cat <<'EOF'
Usage: scripts/rehearse-demo.sh [--dry-run] [--interactive]

  (no flags)     Run one repair job headlessly. Exit 0 only if it verifies and cleans up.
  --dry-run      Check tools and readiness and print the cue sheet. Creates no job.
  --interactive  Pause for Enter before each demo beat. Needs a terminal; without one
                 the rehearsal runs unattended. Combine with --dry-run to practice
                 narration against the cues without touching the controller.

Set FAULTLINE_INSPECTOR_URL to rehearse against a stack on another port.
EOF
}
dry_run=0
interactive=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) dry_run=1 ;;
    --interactive|-i) interactive=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done
if [ "$interactive" = 1 ] && ! [ -t 0 ]; then
  echo 'No terminal on stdin; continuing without pauses.'
  interactive=0
fi
INSPECTOR="${FAULTLINE_INSPECTOR_URL:-http://127.0.0.1:4000}"
API="$INSPECTOR/api/faultline"
programs=(curl jq)
[ "$dry_run" = 1 ] || programs+=(uv)
for program in "${programs[@]}"; do command -v "$program" >/dev/null || { echo "Missing $program" >&2; exit 1; }; done
request() { curl --fail-with-body --silent --show-error --max-time 10 "$@"; }
# beat TITLE CUE: name the next demo step (dry or interactive runs only) and, when interactive, wait.
beat() {
  [ "$dry_run" = 1 ] || [ "$interactive" = 1 ] || return 0
  printf '\n== %s ==\n   %s\n' "$1" "$2"
  if [ "$interactive" = 1 ]; then
    local reply
    read -r -p '   Enter to continue, q to stop: ' reply || reply=q
    case "$reply" in q|Q) echo 'Rehearsal stopped by presenter.'; exit 0 ;; esac
  fi
}
beat 'Readiness' "Checking the Inspector at $INSPECTOR."
if ! ready=$(request "$API/readiness" 2>&1); then
  echo "Readiness request to $INSPECTOR failed: $ready" >&2
  echo 'Start the stack with ./scripts/start-demo.sh, or set FAULTLINE_INSPECTOR_URL to the running Inspector.' >&2
  exit 1
fi
if ! jq -e '.runtime_ready and (.quarantined | not) and .model.available' >/dev/null <<<"$ready"; then
  echo 'Repair unavailable. Inspect runtime/model readiness before recording.' >&2
  jq '{status, reason, runtime_ready, model: {provider: .model.provider, available: .model.available, reason: .model.reason}}' <<<"$ready"
  exit 1
fi
provider=$(jq -r '.model.provider' <<<"$ready")
model=$(jq -r '.model.model' <<<"$ready")
echo "Rehearsing candidate verification with provider=$provider model=$model"
if [ "$provider" = deterministic ]; then echo 'Deterministic rehearsal: this is not a live Meta trial.'; fi
beat 'The problem' "Storefront: add two Trail Mugs, leave the coupon empty, Place order. Expect HTTP 500."
beat 'Repair in the sandbox' "Inspector: Run sandbox repair. The model gets the business contract and the failure, never the bug or the fix."
if [ "$dry_run" = 1 ]; then
  beat 'Verification' 'Expect 44 assertions: 16 checkout, 1 confirmation, 27 business checks run against the sandboxed build.'
  beat 'Wrong fixes rejected' 'Judge drawer (J): a symptom check accepts 5 of 6 wrong repairs; FaultLine rejects all 6.'
  echo
  next=./scripts/rehearse-demo.sh
  [ "$interactive" = 1 ] && next+=' --interactive'
  echo "Dry run passed: the stack is ready and no job was created. Run $next to rehearse a real job."
  exit 0
fi
key=$(uv run --project apps/buggyshop-backend --python 3.13 --locked python -c 'import uuid; print(uuid.uuid4())')
created=$(request -X POST "$API/jobs" -H 'Content-Type: application/json' -d "{\"scenario_id\":\"scripted_checkout_repair\",\"mode\":\"repair\",\"idempotency_key\":\"$key\"}")
job_id=$(jq -er '.job_id' <<<"$created")
started=$SECONDS
last=''
while (( SECONDS - started < 190 )); do
  detail=$(request "$API/jobs/$job_id")
  state=$(jq -r '.job.state' <<<"$detail")
  progress=$(jq -r '"\(.job.state) / \(.job.stage) / \(.job.outcome // "pending")"' <<<"$detail")
  if [ "$progress" != "$last" ]; then echo "$progress"; last=$progress; fi
  case "$state" in
    succeeded|failed|cancelled|interrupted)
      if ! jq -e '.job.state == "succeeded" and .job.outcome == "verified" and .job.cleanup_status == "succeeded" and (.baseline.report.verdict == "failed") and ([.executions[] | select(.phase == "verification") | .report | select(.verdict == "passed" and (.assertions | length > 0) and (.assertions | all(.passed)))] | length > 0)' >/dev/null <<<"$detail"; then
        echo "Rehearsal failed; inspect job $job_id in the Inspector." >&2
        exit 1
      fi
      jq '{job: .job.id, outcome: .job.outcome, cleanup: .job.cleanup_status, provider: .attempts[-1].validation_result.provider, model: .attempts[-1].validation_result.model, attempts: (.attempts | length), assertions: [.executions[] | select(.phase == "verification") | .report.assertions | length]}' <<<"$detail"
      # Compare this run with the figures the voiceover speaks.
      jq -r '
        ([.executions[] | select(.phase == "verification") | .report.assertions[]] | map((.name // .id // "unnamed") | split(".")[0]) | group_by(.) | map("\(.[0]) \(length)") | join(", ")) as $split
        | (.attempts[-1].validation_result.generation_ms) as $ms
        | "Assertions by group: \($split)",
          (if $ms == null then "Generation time: not recorded"
           elif $ms < 7000 then "Generation time: \($ms) ms (under seven seconds)"
           else "Generation time: \($ms) ms (the voiceover line \"under seven seconds\" describes recorded job 3573b32b, not this run)" end)' <<<"$detail"
      echo 'Verified candidate diff:'
      jq -r '.attempts[-1].parsed_diff' <<<"$detail"
      echo "Candidate verified in $((SECONDS - started))s. The production fixture remains seeded."
      beat 'Wrong fixes rejected' 'Judge drawer (J): a symptom check accepts 5 of 6 wrong repairs; FaultLine rejects all 6.'
      exit 0
      ;;
  esac
  sleep 1
done
echo "Job $job_id exceeded the rehearsal deadline; cancelling." >&2
request -X POST "$API/jobs/$job_id/cancel" >/dev/null || true
exit 1
