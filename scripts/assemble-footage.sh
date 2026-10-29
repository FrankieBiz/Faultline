#!/usr/bin/env bash
# Turn recorded footage (scripts/record-footage.sh) into H.264 clips and a silent rough cut.
# Every rough-cut segment carries a lower-third caption stating where its footage came from.
# Nothing is sped up; segments are trimmed to the recorder's start and end marks only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/assemble-footage.sh [FOOTAGE_DIR]

FOOTAGE_DIR holds clips.json and the recorded WebM clips (default: the newest
data/footage/*/ with a clips.json). Writes, inside FOOTAGE_DIR:

  clips/<name>.mp4   each clip trimmed to its marks, H.264 1080p30, uncaptioned
                     (a non-Meta clip 05 is never written uncaptioned)
  rough-cut.mp4      clips 01, 02, [05 if Meta], 04, 03 and an end card, captioned
  rough-cut.txt      edit list: source ranges, durations, and captions
  05-live-break-it-validation.mp4
                     only when clip 05 is not a Meta run: captioned as pipeline
                     validation and excluded from the rough cut

Environment: FOOTAGE_FONT and FOOTAGE_FONT_BOLD override the caption fonts.
EOF
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
for program in ffmpeg ffprobe jq fc-match; do
  command -v "$program" >/dev/null || { echo "Required command missing: $program" >&2; exit 1; }
done

DIR="${1:-}"
if [ -z "$DIR" ]; then
  DIR="$(ls -1dt "$ROOT"/data/footage/*/ 2>/dev/null | while read -r d; do [ -f "$d/clips.json" ] && echo "$d"; done | head -n 1)"
  [ -n "$DIR" ] || { echo "No footage found under data/footage/. Record some with scripts/record-footage.sh." >&2; exit 1; }
fi
DIR="$(cd "$DIR" && pwd)"
MANIFEST="$DIR/clips.json"
[ -f "$MANIFEST" ] || { echo "Missing $MANIFEST" >&2; exit 1; }

# Prefer x264; Fedora's ffmpeg-free ships OpenH264 instead.
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

# Caption fonts come from the installed system; symlinks keep filter paths free of special characters.
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
clip_ok() { [ -n "$(clip_field "$1" .file)" ] && [ -f "$DIR/$(clip_field "$1" .file)" ]; }
pretty_date() { date -u -d "$1" '+%B %-d, %Y' 2>/dev/null || echo "$1"; }

# Lower third: a bold provenance line over a smaller detail line on opaque plates that touch,
# with an accent bar, so captions never blend into the page behind them.
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

# Captions per clip. Provider claims for 04 and 05 come from what the recorder read on screen
# and from the live service's run record, never from the clip name.
captions_for() {
  local name=$1 date
  date="$(pretty_date "$(clip_field "$name" .recorded_at)")"
  case "$name" in
    01-storefront-crash)
      CAP1="Seeded demo store, recorded on this machine"
      CAP2="A deliberately planted defect: an empty coupon makes checkout return HTTP 500" ;;
    02-recorded-meta-repair)
      CAP1="Recorded Meta muse-spark-1.3 repair, played back at real timing"
      CAP2="Job 3573b32b from October 28, 2026, replayed on the judge page · not a live run" ;;
    03-gates)
      CAP1="Recorded evaluation results"
      CAP2="Corpus runs of October 28, 2026 with the deterministic fallback and DeepSeek, not Meta" ;;
    04-inspector-run)
      local source provenance model
      source="$(clip_field "$name" .job_source)"
      provenance="$(clip_field "$name" .provenance)"
      if [ "$provenance" = local-deterministic ]; then
        CAP1="Local run with the deterministic fallback: not a Meta trial"
        CAP2="Inspector on this machine, $date · preset patch, real gates, isolated runtime"
      elif [ "$provenance" = local-meta ]; then
        model="$(sed -E 's/^Meta Model API · ([^ ]+).*/\1/' <<<"$source")"
        CAP1="Local run with Meta $model via the Meta Model API"
        CAP2="Inspector on this machine, $date · real speed"
      else
        CAP1="Local run with ${source%% · *}: not a Meta trial"
        CAP2="Inspector on this machine, $date"
      fi ;;
    05-live-break-it)
      local model provider run
      model="$(clip_field "$name" .run.model)"
      provider="$(clip_field "$name" .run.provider)"
      run="$(clip_field "$name" .run.id)"
      if [ "$(clip_field "$name" .provenance)" = live-meta ]; then
        CAP1="Live Meta $model run on the FaultLine live service, recorded $date"
        CAP2="Real speed, nothing cut · run ${run:0:8} · bug: $(clip_field "$name" .run.defect_id)"
      else
        CAP1="Pipeline validation only: ${model:-unknown model} (${provider:-unknown provider}), NOT a Meta run"
        CAP2="Local live service, $date · not part of the submission video"
      fi ;;
  esac
}

segment_range() {
  local name=$1
  SEG_START="$(clip_field "$name" .marks.start)"
  SEG_END="$(clip_field "$name" .marks.end)"
  [ -n "$SEG_START" ] && [ -n "$SEG_END" ] || { echo "$name has no start/end marks." >&2; return 1; }
  SEG_DURATION="$(awk -v s="$SEG_START" -v e="$SEG_END" 'BEGIN { printf "%.3f", e - s }')"
}

encode_one() { # name output [captioned]
  local name=$1 output=$2 captioned=${3:-}
  segment_range "$name"
  local captions=""
  if [ -n "$captioned" ]; then
    captions_for "$name"
    captions="$(caption_filter "$name" "$CAP1" "$CAP2")"
  fi
  ffmpeg -v error -y -ss "$SEG_START" -to "$SEG_END" -i "$DIR/$(clip_field "$name" .file)" \
    -filter_complex "$(segment_filter 0 "$SEG_DURATION" "$captions")[v]" -map "[v]" "${OUT_ARGS[@]}" "$output"
}

mkdir -p "$DIR/clips"
live_meta=0
if clip_ok 05-live-break-it && [ "$(clip_field 05-live-break-it .provenance)" = live-meta ]; then live_meta=1; fi

echo "Encoder: ${VENC[1]} · caption fonts: $(basename "$FONT_BOLD"), $(basename "$FONT")"
for name in 01-storefront-crash 02-recorded-meta-repair 03-gates 04-inspector-run 05-live-break-it; do
  clip_ok "$name" || continue
  if [ "$name" = 05-live-break-it ] && [ "$live_meta" = 0 ]; then
    rm -f "$DIR/clips/$name.mp4"
    encode_one "$name" "$DIR/05-live-break-it-validation.mp4" captioned
    echo "  05-live-break-it-validation.mp4 (not Meta; captioned, kept out of the rough cut)"
    continue
  fi
  encode_one "$name" "$DIR/clips/$name.mp4"
  echo "  clips/$name.mp4"
done

# Storyboard order: the failure, the recorded Meta repair (and a live Meta run when one exists),
# the Inspector's own evidence, the wrong-patch results, then the source links.
ORDER=(01-storefront-crash 02-recorded-meta-repair)
[ "$live_meta" = 1 ] && ORDER+=(05-live-break-it)
ORDER+=(04-inspector-run 03-gates)

inputs=()
filters=()
labels=""
index=0
total=0
edl="$DIR/rough-cut.txt"
{
  echo "FaultLine silent rough cut · assembled $(date -u '+%Y-%m-%d %H:%M UTC') from $(basename "$DIR")"
  echo "Narration is recorded separately by the owner. No segment is sped up."
  echo
} >"$edl"
for name in "${ORDER[@]}"; do
  if ! clip_ok "$name"; then
    echo "  skipping $name (not recorded or failed)" >&2
    continue
  fi
  segment_range "$name"
  captions_for "$name"
  inputs+=(-ss "$SEG_START" -to "$SEG_END" -i "$DIR/$(clip_field "$name" .file)")
  filters+=("$(segment_filter "$index" "$SEG_DURATION" "$(caption_filter "seg$index" "$CAP1" "$CAP2")")[v$index]")
  labels+="[v$index]"
  printf '%s  %6.2f s  %s  source %s %.2f-%.2f s\n    caption: %s\n             %s\n' \
    "$(awk -v t="$total" 'BEGIN { printf "%d:%05.2f", t / 60, t % 60 }')" "$SEG_DURATION" "$name" \
    "$(clip_field "$name" .file)" "$SEG_START" "$SEG_END" "$CAP1" "$CAP2" >>"$edl"
  total="$(awk -v t="$total" -v d="$SEG_DURATION" 'BEGIN { printf "%.3f", t + d }')"
  index=$((index + 1))
done
[ "$index" -gt 0 ] || { echo "No usable clips in $MANIFEST." >&2; exit 1; }

# End card with the public links.
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
ffmpeg -v error -y "${inputs[@]}" -filter_complex "$graph" -map "[out]" "${OUT_ARGS[@]}" "$DIR/rough-cut.mp4"

duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$DIR/rough-cut.mp4")"
printf '\nTotal  %.2f s\n' "$duration" >>"$edl"
echo "  rough-cut.mp4 ($(awk -v d="$duration" 'BEGIN { printf "%d:%04.1f", d / 60, d % 60 }'))"
echo "Edit list: $edl"
