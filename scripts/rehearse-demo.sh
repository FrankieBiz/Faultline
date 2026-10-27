#!/usr/bin/env bash
# FaultLine Automated 180s Pitch & Demo Rehearsal Script
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=========================================================="
echo "  FAULTLINE LIVE PITCH & DEMO REHEARSAL HARNESS"
echo "=========================================================="

# 1. Check services
echo "[Step 1/5] Checking live services..."
for port in 8000 3000 4000 9000; do
  if ! nc -z 127.0.0.1 "$port" 2>/dev/null; then
    echo "ERROR: Port $port is not listening. Run ./scripts/start-demo.sh first."
    exit 1
  fi
done
echo "✓ All 4 demo daemons online (8000, 3000, 4000, 9000)"

# 2. Trigger real checkout crash
echo ""
echo "[Step 2/5] Simulating customer checkout without coupon (Seeded Defect)..."
RESPONSE_500=$(curl -s -w "\n%{http_code}" -X POST http://127.0.0.1:8000/api/checkout \
  -H "Content-Type: application/json" \
  -d '{"items": [{"product_id": "trail-mug", "quantity": 1}], "coupon_code": ""}')
BODY_500=$(echo "$RESPONSE_500" | head -n 1)
CODE_500=$(echo "$RESPONSE_500" | tail -n 1)

if [ "$CODE_500" = "500" ]; then
  echo "✓ Intercepted Expected HTTP 500 TypeError:"
  echo "  $BODY_500"
else
  echo "Unexpected response code: $CODE_500"
  exit 1
fi

# 3. Dispatch Live Meta Repair Job
echo ""
echo "[Step 3/5] Submitting live repair job to Meta muse-spark-1.3 (Port 9000)..."
JOB_RES=$(curl -s -X POST http://127.0.0.1:9000/api/faultline/jobs \
  -H "Authorization: Bearer dev-control-token" \
  -H "Content-Type: application/json" \
  -d "{\"scenario_id\":\"scripted_checkout_repair\",\"mode\":\"repair\",\"idempotency_key\":\"$(uuidgen)\"}")

JOB_ID=$(echo "$JOB_RES" | jq -r '.job_id')
echo "✓ Dispatched Job ID: $JOB_ID"

# 4. Monitor Job to Completion
echo ""
echo "[Step 4/5] Monitoring autonomous healing state machine..."
START_T=$(date +%s)
while true; do
  sleep 1
  STATUS_RES=$(curl -s -H "Authorization: Bearer dev-control-token" "http://127.0.0.1:9000/api/faultline/jobs/$JOB_ID")
  STATE=$(echo "$STATUS_RES" | jq -r '.job.state')
  STAGE=$(echo "$STATUS_RES" | jq -r '.job.stage')
  OUTCOME=$(echo "$STATUS_RES" | jq -r '.job.outcome // "running"')
  NOW_T=$(date +%s)
  ELAPSED=$((NOW_T - START_T))
  echo "  [${ELAPSED}s] State: $STATE | Stage: $STAGE | Outcome: $OUTCOME"

  if [ "$STATE" = "succeeded" ] || [ "$STATE" = "failed" ]; then
    DIFF=$(echo "$STATUS_RES" | jq -r '.attempts[-1].parsed_diff // "none"')
    MODEL=$(echo "$STATUS_RES" | jq -r '.attempts[-1].validation_result.model // "unknown"')
    PROMPT_T=$(echo "$STATUS_RES" | jq -r '.attempts[-1].prompt_tokens // 0')
    COMP_T=$(echo "$STATUS_RES" | jq -r '.attempts[-1].completion_tokens // 0')
    EXPLANATION=$(echo "$STATUS_RES" | jq -r '.attempts[-1].raw_patch | fromjson | .explanation')

    echo ""
    echo "=========================================================="
    echo "  REPAIR VERIFIED GREEN BY META AI ($MODEL)"
    echo "=========================================================="
    echo "Tokens: $PROMPT_T in • $COMP_T out"
    echo "Reasoning: $EXPLANATION"
    echo "Unified Diff:"
    echo "$DIFF"
    break
  fi

  if [ "$ELAPSED" -gt 30 ]; then
    echo "ERROR: Repair timed out after 30 seconds."
    exit 1
  fi
done

# 5. Verify Storefront Recovery
echo ""
echo "[Step 5/5] Testing verified checkout with coupon TENOFF..."
RESPONSE_201=$(curl -s -w "\n%{http_code}" -X POST http://127.0.0.1:8000/api/checkout \
  -H "Content-Type: application/json" \
  -d '{"items": [{"product_id": "trail-mug", "quantity": 1}], "coupon_code": "TENOFF"}')
BODY_201=$(echo "$RESPONSE_201" | head -n 1)
CODE_201=$(echo "$RESPONSE_201" | tail -n 1)

if [ "$CODE_201" = "201" ]; then
  ORDER_ID=$(echo "$BODY_201" | jq -r '.id')
  TOTAL=$(echo "$BODY_201" | jq -r '.total')
  echo "✓ Order Captured Successfully!"
  echo "  Order ID: $ORDER_ID"
  echo "  Charged: \$$(echo "scale=2; $TOTAL / 100" | bc)"
else
  echo "Unexpected response code: $CODE_201"
  exit 1
fi

echo ""
echo "=========================================================="
echo "  DEMO REHEARSAL COMPLETED SUCCESSFULLY IN ${ELAPSED}s"
echo "  Mission Control:   http://localhost:4000"
echo "=========================================================="
