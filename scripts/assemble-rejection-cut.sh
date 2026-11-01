#!/usr/bin/env bash
# Assemble the 25-second "Anti-Vaporware Rejection Flex" cut from the recorded patch explorer.
#
#   0:00-0:05  hook over the explorer summary
#   0:05-0:10  early_return_unsaved   naive 201 check accepted · FaultLine rejected, 6 of 27 failed
#   0:10-0:15  zero_all_discounts     naive 201 check accepted · FaultLine rejected, 4 of 27 failed
#   0:15-0:20  null_coupon_only       naive 201 check accepted · FaultLine rejected, 2 of 27 failed
#   0:20-0:22.5 the 5 of 6 / 0 of 6 summary
#   0:22.5-0:25 end card
#
# All footage is real speed. The patches are the authored adversarial corpus, not model output;
# results are docs/evidence/2026-10-28-evaluation-deterministic.md (the DeepSeek run agrees).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-}" in -h|--help)
  echo "Usage: scripts/assemble-rejection-cut.sh [FOOTAGE_DIR]   (default: data/footage/20261101-193931)"
  echo "Writes FOOTAGE_DIR/rejection-flex-cut.mp4 and rejection-flex-cut.txt (edit list)."
  exit 0 ;;
esac

DIR="$(cd "${1:-$ROOT/data/footage/20261101-193931}" && pwd)"
# shellcheck source=lib/viral-cut.sh
source "$ROOT/scripts/lib/viral-cut.sh"

GATES="$DIR/03-gates.webm"
DETAIL=1440:810:240:70
echo "Encoder: ${VC_VENC[1]}"

# 1. Hook: the claim in two lines over a darkened explorer, readable without sound.
hook="drawbox=x=0:y=0:w=iw:h=ih:color=${VC_INK}@0.86:t=fill"
hook+=",drawbox=x=(iw-160)/2:y=330:w=160:h=10:color=${VC_GOLD}:t=fill"
hook+=",drawtext=fontfile=$VC_WORK/bold.font:textfile=$(vc_text hook-1 'Anyone can get an AI model to write a patch.'):expansion=none:fontsize=62:fontcolor=white:x=(w-text_w)/2:y=400"
hook+=",drawtext=fontfile=$VC_WORK/bold.font:textfile=$(vc_text hook-2 'The hard part is knowing when the patch is wrong.'):expansion=none:fontsize=62:fontcolor=${VC_GOLD}:x=(w-text_w)/2:y=500"
hook+=",drawtext=fontfile=$VC_WORK/regular.font:textfile=$(vc_text hook-3 'Three wrong patches. Watch which check catches them.'):expansion=none:fontsize=34:fontcolor=0xb8bcc4:x=(w-text_w)/2:y=640"
vc_segment "$GATES" 0.90 5.90 1 1440:810:240:150 "$hook" "Hook text over the patch explorer summary"

# 2-4. Three wrong patches, each accepted by "did it return 201?" and rejected by FaultLine.
vc_segment "$GATES" 20.60 25.60 1 "$DETAIL" \
  "$(vc_caption r1 'WRONG PATCH 1 · early_return_unsaved' "$VC_ROSE" \
    'Returns 201. Never saves the order.' \
    'Naive 201 check: ACCEPTED · FaultLine: REJECTED, 6 of 27 business checks failed')" \
  "early_return_unsaved detail"
vc_segment "$GATES" 9.00 14.00 1 "$DETAIL" \
  "$(vc_caption r2 'WRONG PATCH 2 · zero_all_discounts' "$VC_ROSE" \
    'No crash, because no discount ever applies.' \
    'Naive 201 check: ACCEPTED · FaultLine: REJECTED, 4 of 27 business checks failed')" \
  "zero_all_discounts detail"
vc_segment "$GATES" 14.80 19.80 1 "$DETAIL" \
  "$(vc_caption r3 'WRONG PATCH 3 · null_coupon_only' "$VC_ROSE" \
    'Fixes null. An empty coupon still crashes.' \
    'Naive 201 check: ACCEPTED · FaultLine: REJECTED, 2 of 27 business checks failed')" \
  "null_coupon_only detail"

# 5. The scoreboard.
vc_segment "$GATES" 0.90 3.40 1 1360:765:280:200 \
  "$(vc_caption r4 'STATUS CODES ARE NOT ORACLES' "$VC_EMERALD" \
    'Naive check: 5 of 6 through. FaultLine: 0.' \
    'Authored corpus of 6 wrong + 2 correct patches · recorded Oct 28, 2026')" \
  "Patch explorer summary: 5 of 6, 0 of 6, 2 of 2, 3 of 3"

# 6. End card.
vc_card 2.5 "Don't trust the 201. Verify the patch." "Public links: source and judge page"

vc_render "$DIR/rejection-flex-cut.mp4" "FaultLine rejection flex cut (25 s)"
