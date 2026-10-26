#!/usr/bin/env bash
# Reset FaultLine workspace to a clean, known-healthy baseline.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Resetting FaultLine Workspace ==="

# 1. Kill any existing processes listening on demo ports
for port in 4000 9000 8000 3000; do
  pid=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "Terminating process on port $port (PID: $pid)..."
    kill -9 $pid 2>/dev/null || true
  fi
done

# 2. Reset database and ephemeral data
rm -rf "$ROOT/data/faultline.db" "$ROOT/data/faultline.db-shm" "$ROOT/data/faultline.db-wal" "$ROOT/data/jobs"
mkdir -p "$ROOT/data/jobs"

# 3. Ensure seeded checkout route is in place
cp "$ROOT/fixtures/seeds/checkout_seeded.py" "$ROOT/apps/buggyshop-backend/app/routes/checkout.py"

# 4. Verify provenance
uv run --project "$ROOT/apps/buggyshop-backend" --python 3.13 --locked python -m fixtures.provenance

echo "=== Reset Complete. Workspace is pristine and ready for demo. ==="
