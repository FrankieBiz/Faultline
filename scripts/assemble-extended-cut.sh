#!/usr/bin/env bash
# Assemble extended rough cut including the terminal pre-flight gate flex.
# Segment order:
#   1. 01-storefront-crash (28.03 s)
#   2. 05-terminal-gate-flex (25.20 s)
#   3. 02-recorded-meta-repair (34.02 s)
#   4. 04-inspector-run (42.53 s)
#   5. 03-gates (24.69 s)
#   6. End Card (5.00 s)
# Total duration: ~159.47 s (2:39.5)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DIR="$ROOT/data/footage/20261101-193931"
MANIFEST="$DIR/clips.json"

ENCODERS="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
if grep -qw libx264 <<<"$ENCODERS"; then
  VENC=(-c:v libx264 -preset slow -crf 18 -profile:v high)
elif grep -qw libopenh264 <<<"$ENCODERS"; then
  VENC=(-c:v libopenh264 -profile:v high -b:v 8M)
else
  echo "ffmpeg has neither libx264 nor libopenh264." >&2
  exit 1
fi
OUT_ARGS=("${VENC[@]}" -g 60 -r 30 -pix_fmt yuv420p -an -movflags +faststart)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

font_file() {
  local override=$1 pattern
  shift
  if [ -n "$override" ]; then echo "$override"; return; fi
  for pattern in "$@"; do
    local file
    file="$(fc-match -f '%{file}' "$pattern" 2>/dev/null || true)"
    case "$file" in *.ttf|*.otf|*.TTF|*.OTF) [ -f "$file" ] && { echo "$file"; return; } ;; esac
  done
  return 1
}
FONT="$(font_file "${FOOTAGE_FONT:-}" 'Inter:style=Medium' 'Inter' 'Liberation Sans' 'DejaVu Sans' 'sans-serif')" \
  || { echo "No TTF/OTF sans-serif font found (fc-match)." >&2; exit 1; }
FONT_BOLD="$(font_file "${FOOTAGE_FONT_BOLD:-}" 'Inter:style=SemiBold' 'Inter:style=Bold' 'Liberation Sans:style=Bold' 'DejaVu Sans:style=Bold' 'sans-serif:bold')" \
  || FONT_BOLD="$FONT"
ln -s "$FONT" "$WORK/regular.font"
ln -s "$FONT_BOLD" "$WORK/bold.font"

clip_field() { jq -r --arg name "$1" ".clips[] | select(.name == \$name and .status == \"ok\") | $2 // empty" "$MANIFEST" | head -n 1; }
pretty_date() { date -u -d "$1" '+%B %-d, %Y' 2>/dev/null || echo "$1"; }

caption_filter() {
  local id=$1 line1=$2 line2=$3
  printf '%s' "$line1" >"$WORK/$id-1.txt"
  printf '%s' "$line2" >"$WORK/$id-2.txt"
  local plate="box=1:boxcolor=0x1b1e24:expansion=none:y_align=font"
  printf "drawtext=fontfile=%s:textfile=%s:fontsize=34:fontcolor=white:x=70:y=h-158:%s:boxborderw=14|26|9|26" \
    "$WORK/bold.font" "$WORK/$id-1.txt" "$plate"
  printf ",drawtext=fontfile=%s:textfile=%s:fontsize=26:fontcolor=0xd4d7dc:x=70:y=h-99:%s:boxborderw=9|26|14|26" \
    "$WORK/regular.font" "$WORK/$id-2.txt" "$plate"
  printf ",drawbox=x=38:y=ih-172:w=6:h=118:color=0xf3c969:t=fill"
}

FADE=0.35
segment_filter() {
  local input=$1 duration=$2 captions=$3
  local fade_out
  fade_out="$(awk -v d="$duration" -v f="$FADE" 'BEGIN { printf "%.3f", d - f }')"
  printf "[%s:v]fps=30,scale=1920:1080:flags=lanczos,setsar=1,setpts=PTS-STARTPTS" "$input"
  [ -n "$captions" ] && printf ",%s" "$captions"
  printf ",fade=t=in:st=0:d=%s,fade=t=out:st=%s:d=%s,format=yuv420p" "$FADE" "$fade_out" "$FADE"
}

# Also encode uncaptioned clip 05 to clips/
ffmpeg -v error -y -i "$DIR/05-terminal-gate-flex.webm" \
  -filter_complex "[0:v]fps=30,scale=1920:1080:flags=lanczos,setsar=1,setpts=PTS-STARTPTS,format=yuv420p[v]" \
  -map "[v]" "${OUT_ARGS[@]}" "$DIR/clips/05-terminal-gate-flex.mp4"

inputs=()
filters=()
labels=""
index=0
total=0
edl="$DIR/rough-cut-extended.txt"
{
  echo "FaultLine extended rough cut (with Pre-Flight CLI Gate Flex) · assembled $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "Narration is recorded separately by the owner. No segment is sped up."
  echo
} >"$edl"

# Segments definition: [name, file, start, end, cap1, cap2]
add_segment() {
  local name=$1 file=$2 start=$3 end=$4 cap1=$5 cap2=$6
  local duration
  duration="$(awk -v s="$start" -v e="$end" 'BEGIN { printf "%.3f", e - s }')"

  inputs+=(-ss "$start" -to "$end" -i "$file")
  filters+=("$(segment_filter "$index" "$duration" "$(caption_filter "seg$index" "$cap1" "$cap2")")[v$index]")
  labels+="[v$index]"

  printf '%s  %6.2f s  %s  source %s %.2f-%.2f s\n    caption: %s\n             %s\n' \
    "$(awk -v t="$total" 'BEGIN { printf "%d:%05.2f", t / 60, t % 60 }')" "$duration" "$name" \
    "$(basename "$file")" "$start" "$end" "$cap1" "$cap2" >>"$edl"
  total="$(awk -v t="$total" -v d="$duration" 'BEGIN { printf "%.3f", t + d }')"
  index=$((index + 1))
}

# 1. 01-storefront-crash
add_segment "01-storefront-crash" "$DIR/$(clip_field 01-storefront-crash .file)" \
  "$(clip_field 01-storefront-crash .marks.start)" "$(clip_field 01-storefront-crash .marks.end)" \
  "Seeded demo store, recorded on this machine" \
  "A deliberately planted defect: an empty coupon makes checkout return HTTP 500"

# 2. 05-terminal-gate-flex
add_segment "05-terminal-gate-flex" "$DIR/05-terminal-gate-flex.webm" \
  "0.00" "25.20" \
  "Pre-Flight Agent Gate · CLI on this machine" \
  "Deterministic Playwright exploration exits 1 (DEPLOYMENT_BLOCKED) · generates exact fix prompt"

# 3. 02-recorded-meta-repair
add_segment "02-recorded-meta-repair" "$DIR/$(clip_field 02-recorded-meta-repair .file)" \
  "$(clip_field 02-recorded-meta-repair .marks.start)" "$(clip_field 02-recorded-meta-repair .marks.end)" \
  "Recorded Meta muse-spark-1.3 repair, played back at real timing" \
  "Job 3573b32b from October 28, 2026, replayed on the judge page · not a live run"

# 4. 04-inspector-run
add_segment "04-inspector-run" "$DIR/$(clip_field 04-inspector-run .file)" \
  "$(clip_field 04-inspector-run .marks.start)" "$(clip_field 04-inspector-run .marks.end)" \
  "Local run with the deterministic fallback: not a Meta trial" \
  "Inspector on this machine, November 1, 2026 · preset patch, real gates, isolated runtime"

# 5. 03-gates
add_segment "03-gates" "$DIR/$(clip_field 03-gates .file)" \
  "$(clip_field 03-gates .marks.start)" "$(clip_field 03-gates .marks.end)" \
  "Recorded evaluation results" \
  "Corpus runs of October 28, 2026 with the deterministic fallback and DeepSeek, not Meta"

# 6. End card
CARD=5
printf '%s' "FaultLine" >"$WORK/card-1.txt"
printf '%s' "Source  github.com/FrankieBiz/Faultline" >"$WORK/card-2.txt"
printf '%s' "Judge page  frankiebiz.github.io/Faultline" >"$WORK/card-3.txt"
card="drawtext=fontfile=$WORK/bold.font:textfile=$WORK/card-1.txt:expansion=none:fontsize=84:fontcolor=white:x=(w-text_w)/2:y=h/2-150"
card+=",drawtext=fontfile=$WORK/regular.font:textfile=$WORK/card-2.txt:expansion=none:fontsize=40:fontcolor=0xd4d7dc:x=(w-text_w)/2:y=h/2-10"
card+=",drawtext=fontfile=$WORK/regular.font:textfile=$WORK/card-3.txt:expansion=none:fontsize=40:fontcolor=0xd4d7dc:x=(w-text_w)/2:y=h/2+60"
inputs+=(-f lavfi -t "$CARD" -i "color=c=0x0b0c0e:s=1920x1080:r=30")
filters+=("$(segment_filter "$index" "$CARD" "$card")[v$index]")
labels+="[v$index]"
printf '%s  %6.2f s  end card: FaultLine · github.com/FrankieBiz/Faultline · frankiebiz.github.io/Faultline\n' \
  "$(awk -v t="$total" 'BEGIN { printf "%d:%05.2f", t / 60, t % 60 }')" "$CARD" >>"$edl"
index=$((index + 1))

graph="$(IFS=';'; echo "${filters[*]}");${labels}concat=n=$index:v=1:a=0[out]"
echo "Assembling rough-cut-extended.mp4..."
ffmpeg -v error -y "${inputs[@]}" -filter_complex "$graph" -map "[out]" "${OUT_ARGS[@]}" "$DIR/rough-cut-extended.mp4"

duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$DIR/rough-cut-extended.mp4")"
printf '\nTotal  %.2f s\n' "$duration" >>"$edl"
echo "Created: rough-cut-extended.mp4 ($(awk -v d="$duration" 'BEGIN { printf "%d:%04.1f", d / 60, d % 60 }'))"
echo "Edit list: $edl"
