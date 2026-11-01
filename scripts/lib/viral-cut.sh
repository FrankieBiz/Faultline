# Shared helpers for the short social cuts (assemble-viral-cut.sh, assemble-rejection-cut.sh).
# Source this file; it is not executable on its own.
#
# A cut is a list of segments taken from recorded clips. Each segment may be cropped (to fill a
# phone screen with the part of the page that matters) and sped up. Every speed-up is stated in the
# segment's own caption and in the edit list, alongside the original duration. Nothing is invented:
# captions describe the recording they sit on.

for program in ffmpeg ffprobe jq fc-match awk; do
  command -v "$program" >/dev/null || { echo "Required command missing: $program" >&2; exit 1; }
done

# Prefer x264; Fedora's ffmpeg-free ships OpenH264 instead.
VC_ENCODERS="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
if grep -qw libx264 <<<"$VC_ENCODERS"; then
  VC_VENC=(-c:v libx264 -preset slow -crf 18 -profile:v high)
elif grep -qw libopenh264 <<<"$VC_ENCODERS"; then
  VC_VENC=(-c:v libopenh264 -profile:v high -b:v 10M)
else
  echo "ffmpeg has neither libx264 nor libopenh264." >&2
  exit 1
fi
VC_OUT_ARGS=("${VC_VENC[@]}" -g 30 -r 30 -pix_fmt yuv420p -an -movflags +faststart)

VC_WORK="$(mktemp -d)"
trap 'rm -rf "$VC_WORK"' EXIT

vc_font() {
  local override=$1 pattern file
  shift
  if [ -n "$override" ]; then echo "$override"; return; fi
  for pattern in "$@"; do
    file="$(fc-match -f '%{file}' "$pattern" 2>/dev/null || true)"
    case "$file" in *.ttf|*.otf|*.TTF|*.OTF) [ -f "$file" ] && { echo "$file"; return; } ;; esac
  done
  return 1
}
VC_FONT="$(vc_font "${FOOTAGE_FONT:-}" 'Inter:style=Medium' 'Inter' 'Liberation Sans' 'DejaVu Sans' 'sans-serif')" \
  || { echo "No TTF/OTF sans-serif font found (fc-match)." >&2; exit 1; }
VC_FONT_BOLD="$(vc_font "${FOOTAGE_FONT_BOLD:-}" 'Inter:style=Bold' 'Inter:style=SemiBold' 'Liberation Sans:style=Bold' 'DejaVu Sans:style=Bold' 'sans-serif:bold')" \
  || VC_FONT_BOLD="$VC_FONT"
VC_FONT_MONO="$(vc_font "${FOOTAGE_FONT_MONO:-}" 'monospace:style=Bold')" \
  || VC_FONT_MONO="$VC_FONT_BOLD"
# Symlinks keep filter paths free of characters that need escaping.
ln -s "$VC_FONT" "$VC_WORK/regular.font"
ln -s "$VC_FONT_BOLD" "$VC_WORK/bold.font"
ln -s "$VC_FONT_MONO" "$VC_WORK/mono.font"

# Palette shared with the judge page and the Inspector.
VC_GOLD=0xf3c969
VC_ROSE=0xff4d6a
VC_AMBER=0xf59e0b
VC_CYAN=0x2dd4ff
VC_EMERALD=0x3dffa2
VC_INK=0x0b0c0e

vc_text() { # id text -> path of a text file (textfile + expansion=none never interprets % or :)
  printf '%s' "$2" >"$VC_WORK/$1.txt"
  printf '%s' "$VC_WORK/$1.txt"
}

# Lower third for muted mobile feeds: a mono kicker in the beat's color, a large bold headline,
# and a provenance line, on near-opaque plates beside a gold accent bar. The block ends at
# y=846, above the bottom 20% of the frame where feed players draw their controls.
vc_caption() { # id kicker kicker_color line1 line2
  local id=$1 kicker=$2 color=$3 line1=$4 line2=$5
  local plate="box=1:boxcolor=${VC_INK}@0.94:expansion=none:y_align=font"
  printf "drawtext=fontfile=%s:textfile=%s:fontsize=28:fontcolor=%s:x=86:y=630:%s:boxborderw=10|28|10|28" \
    "$VC_WORK/mono.font" "$(vc_text "$id-k" "$kicker")" "$color" "$plate"
  printf ",drawtext=fontfile=%s:textfile=%s:fontsize=52:fontcolor=white:x=86:y=696:%s:boxborderw=16|28|12|28" \
    "$VC_WORK/bold.font" "$(vc_text "$id-1" "$line1")" "$plate"
  printf ",drawtext=fontfile=%s:textfile=%s:fontsize=30:fontcolor=0xe4e6ea:x=86:y=784:%s:boxborderw=10|28|18|28" \
    "$VC_WORK/regular.font" "$(vc_text "$id-2" "$line2")" "$plate"
  printf ",drawbox=x=44:y=620:w=12:h=226:color=%s:t=fill" "$VC_GOLD"
}

# A short full-frame flash tied to a real on-screen event (for example the HTTP 500 appearing).
vc_flash() { # color start duration
  printf "drawbox=x=0:y=0:w=iw:h=ih:color=%s@0.30:t=fill:enable='between(t,%s,%s)'" \
    "$1" "$2" "$(awk -v s="$2" -v d="$3" 'BEGIN { printf "%.3f", s + d }')"
}

VC_INPUTS=()
VC_FILTERS=()
VC_LABELS=""
VC_INDEX=0
VC_TOTAL=0
VC_EDL=()

vc_clock() { awk -v t="$1" 'BEGIN { printf "%d:%05.2f", t / 60, t % 60 }'; }

# Add a recorded segment. crop is W:H:X:Y in source pixels (1920x1080 recordings), or "none".
vc_segment() { # file start end speed crop overlay_filters edl_note
  local file=$1 start=$2 end=$3 speed=$4 crop=$5 overlay=$6 note=$7
  local source duration
  [ -f "$file" ] || { echo "Missing clip: $file" >&2; exit 1; }
  source="$(awk -v s="$start" -v e="$end" 'BEGIN { printf "%.3f", e - s }')"
  duration="$(awk -v d="$source" -v x="$speed" 'BEGIN { printf "%.3f", d / x }')"
  local chain="[$VC_INDEX:v]setpts=(PTS-STARTPTS)/$speed,fps=30"
  [ "$crop" != none ] && chain+=",crop=$crop"
  chain+=",scale=1920:1080:flags=lanczos,setsar=1,trim=duration=$duration,setpts=PTS-STARTPTS"
  [ -n "$overlay" ] && chain+=",$overlay"
  chain+=",format=yuv420p[v$VC_INDEX]"
  VC_INPUTS+=(-ss "$start" -to "$end" -i "$file")
  VC_FILTERS+=("$chain")
  VC_LABELS+="[v$VC_INDEX]"
  local pace="real speed"
  [ "$speed" != 1 ] && pace="${speed}x speed-up of $source s"
  VC_EDL+=("$(printf '%s  %5.2f s  %s %.2f-%.2f s (%s)\n    %s' \
    "$(vc_clock "$VC_TOTAL")" "$duration" "$(basename "$file")" "$start" "$end" "$pace" "$note")")
  VC_TOTAL="$(awk -v t="$VC_TOTAL" -v d="$duration" 'BEGIN { printf "%.3f", t + d }')"
  VC_INDEX=$((VC_INDEX + 1))
}

# End card: brand, one line of positioning, and the two public links.
vc_card() { # duration tagline edl_note
  local duration=$1 tagline=$2 note=$3 fade_start
  fade_start="$(awk -v d="$duration" 'BEGIN { printf "%.3f", d - 0.3 }')"
  local c="drawbox=x=0:y=0:w=iw:h=ih:color=${VC_INK}:t=fill"
  c+=",drawbox=x=(iw-160)/2:y=300:w=160:h=10:color=${VC_GOLD}:t=fill"
  c+=",drawtext=fontfile=$VC_WORK/bold.font:textfile=$(vc_text card-brand FaultLine):expansion=none:fontsize=150:fontcolor=white:x=(w-text_w)/2:y=350"
  c+=",drawtext=fontfile=$VC_WORK/bold.font:textfile=$(vc_text card-tag "$tagline"):expansion=none:fontsize=58:fontcolor=${VC_GOLD}:x=(w-text_w)/2:y=560"
  c+=",drawtext=fontfile=$VC_WORK/mono.font:textfile=$(vc_text card-src 'github.com/FrankieBiz/Faultline'):expansion=none:fontsize=40:fontcolor=white:x=(w-text_w)/2:y=700"
  c+=",drawtext=fontfile=$VC_WORK/mono.font:textfile=$(vc_text card-judge 'frankiebiz.github.io/Faultline'):expansion=none:fontsize=40:fontcolor=0xb8bcc4:x=(w-text_w)/2:y=765"
  c+=",fade=t=out:st=$fade_start:d=0.3"
  VC_INPUTS+=(-f lavfi -t "$duration" -i "color=c=${VC_INK}:s=1920x1080:r=30")
  VC_FILTERS+=("[$VC_INDEX:v]$c,format=yuv420p[v$VC_INDEX]")
  VC_LABELS+="[v$VC_INDEX]"
  VC_EDL+=("$(printf '%s  %5.2f s  end card: %s\n    %s' "$(vc_clock "$VC_TOTAL")" "$duration" "$tagline" "$note")")
  VC_TOTAL="$(awk -v t="$VC_TOTAL" -v d="$duration" 'BEGIN { printf "%.3f", t + d }')"
  VC_INDEX=$((VC_INDEX + 1))
}

# Concatenate with hard cuts, draw a gold progress bar along the top edge, encode, and write the
# edit list next to the video.
vc_render() { # output title
  local output=$1 title=$2 graph duration
  graph="$(IFS=';'; echo "${VC_FILTERS[*]}")"
  graph+=";${VC_LABELS}concat=n=$VC_INDEX:v=1:a=0[cat]"
  graph+=";color=c=${VC_GOLD}:s=1920x8:r=30[bar];[cat][bar]overlay=x='-w+w*t/$VC_TOTAL':y=0:shortest=1[out]"
  ffmpeg -v error -y "${VC_INPUTS[@]}" -filter_complex "$graph" -map "[out]" "${VC_OUT_ARGS[@]}" "$output"
  duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$output")"
  {
    echo "$title · assembled $(date -u '+%Y-%m-%d %H:%M UTC')"
    echo "Silent cut for muted feeds; captions carry the story. Speed-ups are stated per segment."
    echo
    printf '%s\n' "${VC_EDL[@]}"
    printf '\nPlanned %.2f s · encoded %.2f s\n' "$VC_TOTAL" "$duration"
  } >"${output%.mp4}.txt"
  echo "  $(basename "$output") ($(printf '%.2f' "$duration") s, $(du -h "$output" | cut -f1))"
  echo "  Edit list: ${output%.mp4}.txt"
}
