#!/usr/bin/env bash
# Assemble the 45-second viral hero cut for X and LinkedIn from recorded footage.
#
#   0:00-0:06  storefront: empty coupon, Place order, HTTP 500 (real speed; the 500 lands at 0:02.5)
#   0:06-0:16  faultline gate: 30 elements explored, HTTP 500 caught, exit 1 DEPLOYMENT_BLOCKED
#   0:16-0:30  recorded Meta muse-spark-1.3 job: model wait (2x), the diff, sandbox, 44/44 green
#   0:30-0:41  wrong-patch explorer: naive 201 check accepts 5 of 6, FaultLine rejects all six
#   0:41-0:45  end card
#
# Every number on screen traces to a record: the storefront and terminal clips to the Nov 1
# pre-filming verification (docs/evidence/2026-11-01-prefilm-verification.json), the repair to job
# 3573b32b (docs/evidence/2026-10-28-meta-replay-review.md), and the patch results to
# docs/evidence/2026-10-28-evaluation-deterministic.md.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-}" in -h|--help)
  echo "Usage: scripts/assemble-viral-cut.sh [FOOTAGE_DIR]   (default: data/footage/20261101-193931)"
  echo "Writes FOOTAGE_DIR/viral-hero-cut.mp4 and viral-hero-cut.txt (edit list)."
  exit 0 ;;
esac

DIR="$(cd "${1:-$ROOT/data/footage/20261101-193931}" && pwd)"
# shellcheck source=lib/viral-cut.sh
source "$ROOT/scripts/lib/viral-cut.sh"

STORE="$DIR/01-storefront-crash.webm"
REPAIR="$DIR/02-recorded-meta-repair.webm"
GATES="$DIR/03-gates.webm"
TERMINAL="$DIR/05-terminal-gate-flex.webm"

# Crops (W:H:X:Y) keep the working area of each 1920x1080 page and drop the empty margins.
PAGE=1440:810:240:40
echo "Encoder: ${VC_VENC[1]}"

# 1. Hook. The 500 banner appears at source 24.46 s, 2.46 s into this segment.
vc_segment "$STORE" 22.00 28.00 1 1440:810:240:80 \
  "$(vc_flash "$VC_ROSE" 2.46 0.30),$(vc_caption s1 'LIVE CHECKOUT · HTTP 500' "$VC_ROSE" \
    'Empty coupon. Place order. HTTP 500.' \
    'Seeded demo store, recorded on this machine at real speed · a deliberately planted defect')" \
  "Seeded storefront; crash banner at 2.46 s; flash marks the real banner appearing"

# 2. Pre-flight gate.
vc_segment "$TERMINAL" 1.20 11.20 1 1280:720:110:120 \
  "$(vc_caption s2 'faultline gate · EXIT 1' "$VC_ROSE" \
    'Pre-flight gate: 30 elements, 500 caught' \
    'DEPLOYMENT_BLOCKED before git push · terminal replay of the recorded Nov 1 gate verdict')" \
  "Terminal re-creation of the storefront_seeded_gate verdict in 2026-11-01-prefilm-verification.json (30 elements, 7 actions, 3 screens, exit 1)"

# 3. Recorded Meta repair: the model wait, the patch, the sandboxed verification, the result.
vc_segment "$REPAIR" 10.20 17.80 2 "$PAGE" \
  "$(vc_caption s3 'META · muse-spark-1.3' "$VC_AMBER" \
    'Meta muse-spark-1.3 writes the patch: 6.9 s' \
    'Recorded job 3573b32b, Oct 28, 2026 · this wait is shown at 2x · whole job 13.0 s')" \
  "Judge-page replay of job 3573b32b during the model request"
vc_segment "$REPAIR" 25.10 29.30 1 "$PAGE" \
  "$(vc_caption s4 'THE DIFF · ONE LINE' "$VC_AMBER" \
    'One line: a missing coupon now means 0' \
    "The model's patch to checkout.py, verbatim from the recorded job")" \
  "Patch panel of the same recorded job"
vc_segment "$REPAIR" 17.60 22.00 1 "$PAGE" \
  "$(vc_caption s5 'BUBBLEWRAP SANDBOX · CGROUP V2' "$VC_CYAN" \
    'Untrusted patch, locked-down sandbox' \
    'Namespaces + 512 MiB / 64 tasks / 1 CPU, limits read back from /sys/fs/cgroup')" \
  "Replay timeline: patch policy, isolated verification, 44/44 verified"
vc_segment "$REPAIR" 30.00 31.60 1 "$PAGE" \
  "$(vc_caption s6 '44 / 44 VERIFIED' "$VC_EMERALD" \
    '44 of 44 checks pass. Cleanup confirmed.' \
    'Browser journey + 27 independent HTTP business assertions')" \
  "Recorded job facts: 44/44 candidate checks, 13.0 s, cleanup succeeded"

# 4. The wrong-patch explorer.
vc_segment "$GATES" 0.90 4.40 1 1440:810:240:150 \
  "$(vc_caption s7 'ADVERSARIAL PATCHES' "$VC_ROSE" \
    'A 201 check accepted 5 of 6 wrong patches' \
    'FaultLine accepted 0 of 6 · authored corpus, recorded Oct 28, 2026')" \
  "Patch explorer summary from the Oct 28 evaluation"
vc_segment "$GATES" 9.00 12.50 1 1440:810:240:70 \
  "$(vc_caption s8 'zero_all_discounts' "$VC_ROSE" \
    'Returns 201. Overcharges coupons. Rejected.' \
    'Naive check: accepted · FaultLine: 4 of 27 business checks failed')" \
  "zero_all_discounts detail"
vc_segment "$GATES" 20.60 24.60 1 1440:810:240:70 \
  "$(vc_caption s9 'early_return_unsaved' "$VC_ROSE" \
    'Returns 201. Never saves the order. Rejected.' \
    'Naive check: accepted · FaultLine: 6 of 27 business checks failed')" \
  "early_return_unsaved detail"

# 5. End card.
vc_card 4 "Don't trust the 201. Verify the patch." "Public links: source and judge page"

vc_render "$DIR/viral-hero-cut.mp4" "FaultLine viral hero cut (45 s)"
