#!/usr/bin/env python3
"""Assemble captured judge footage with captions, provenance and an auditable edit list."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def probe(path: Path) -> dict:
    return json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
    )


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "plan", type=Path, help="JSON edit plan; source paths are relative to this file"
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--narration-audio",
        type=Path,
        help="Optional owner-recorded narration, already timed to the master",
    )
    args = parser.parse_args()
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            parser.error(f"Missing {command}")

    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text())
    scenes = plan["scenes"]
    if not scenes:
        parser.error("The plan has no scenes")
    total = sum(float(scene["duration"]) for scene in scenes)
    if not 0 < total <= 179:
        parser.error(f"The chosen judge-video target is under three minutes; plan is {total:.2f}s")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    encoder_list = subprocess.check_output(
        ["ffmpeg", "-hide_banner", "-encoders"], stderr=subprocess.DEVNULL
    ).decode()
    if "libx264" in encoder_list:
        codec = ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    elif "libopenh264" in encoder_list:
        codec = ["-c:v", "libopenh264", "-b:v", "8M", "-profile:v", "high"]
    else:
        parser.error("ffmpeg needs libx264 or libopenh264")

    subtitles = []
    edit_list = []
    clock = 0.0
    with tempfile.TemporaryDirectory(prefix="faultline-judge-edit-") as scratch:
        work = Path(scratch)
        font = work / "sans.woff2"
        mono = work / "mono.woff2"
        shutil.copyfile(ROOT / "docs/assets/fonts/zalando-sans-latin-wdth-wght.woff2", font)
        shutil.copyfile(ROOT / "docs/assets/fonts/martian-mono-latin-wdth-wght.woff2", mono)
        encoded = []
        for index, scene in enumerate(scenes):
            duration = float(scene["duration"])
            if duration <= 0:
                parser.error("Scene durations must be positive")
            title = work / f"title-{index}.txt"
            provenance = work / f"source-{index}.txt"
            title.write_text(scene["title"])
            provenance.write_text(scene["provenance"])
            subtitles_for_scene = []
            words = scene["narration"].split()
            chunks = textwrap.wrap(
                " ".join(words), width=138, break_long_words=False, break_on_hyphens=False
            )
            word_total = max(len(words), 1)
            cue_clock = 0.0
            for cue_index, chunk in enumerate(chunks):
                cue_duration = duration * len(chunk.split()) / word_total
                cue_end = duration if cue_index == len(chunks) - 1 else cue_clock + cue_duration
                text = textwrap.fill(
                    chunk, width=80, break_long_words=False, break_on_hyphens=False
                )
                cue = work / f"cue-{index}-{cue_index}.txt"
                cue.write_text(text)
                subtitles.append((clock + cue_clock, clock + cue_end, text))
                subtitles_for_scene.append(
                    f"drawtext=fontfile={font}:textfile={cue}:fontsize=34:fontcolor=0xeceef1:"
                    f"x=80:y=956:line_spacing=8:enable='gte(t,{cue_clock:.6f})*lt(t,{cue_end:.6f})'"
                )
                cue_clock = cue_end

            source = None
            source_range = None
            if scene.get("mode") == "card":
                body = work / f"card-{index}.txt"
                body.write_text(scene["body"])
                inputs = ["-f", "lavfi", "-i", f"color=c=0x0b0b0a:s=1920x1080:r=30:d={duration}"]
                filters = [
                    f"drawtext=fontfile={font}:textfile={body}:fontsize=58:fontcolor=0xeceef1:x=120:y=240:line_spacing=24",
                ]
            else:
                source = (plan_path.parent / scene["file"]).resolve()
                if not source.is_file():
                    parser.error(f"Missing footage: {source}")
                start = float(scene["start"])
                end = float(scene["end"])
                source_duration = float(probe(source)["format"]["duration"])
                if (
                    start < 0
                    or end <= start
                    or end > source_duration + 0.1
                    or end - start > duration + 0.05
                ):
                    parser.error(
                        f"Invalid source range for {source.name}: {start}..{end}, scene {duration}s"
                    )
                source_range = [start, end]
                inputs = ["-ss", str(start), "-t", str(end - start), "-i", str(source)]
                # Preserve the app's aspect ratio, with a dedicated caption strip below it.
                filters = [
                    "fps=30",
                    "scale=1600:900:flags=lanczos:force_original_aspect_ratio=decrease",
                    "pad=1600:900:(ow-iw)/2:(oh-ih)/2:color=0x0b0b0a",
                    "setsar=1",
                    "setpts=PTS-STARTPTS",
                    "tpad=stop_mode=clone:"
                    f"stop_duration={max(0, duration - (end - start)) + 0.1:.4f}",
                    "pad=1920:1080:160:0:color=0x0b0b0a",
                ]
            filters += [
                "drawbox=x=0:y=900:w=1920:h=180:color=0x0b0b0a:t=fill",
                "drawbox=x=80:y=900:w=1760:h=1:color=0x565758:t=fill",
                f"drawtext=fontfile={font}:textfile={title}:fontsize=25:fontcolor=0xa9abaf:x=80:y=917",
                f"drawtext=fontfile={mono}:textfile={provenance}:fontsize=19:fontcolor=0xa9abaf:x=80:y=1045",
                *subtitles_for_scene,
            ]
            segment = work / f"segment-{index:02}.mp4"
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    *inputs,
                    "-vf",
                    ",".join(filters),
                    "-t",
                    str(duration),
                    *codec,
                    "-r",
                    "30",
                    "-g",
                    "60",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    "-movflags",
                    "+faststart",
                    str(segment),
                ]
            )
            encoded.append(segment)
            edit_list.append(
                {
                    "scene": index + 1,
                    "title": scene["title"],
                    "from_seconds": clock,
                    "to_seconds": clock + duration,
                    "provenance": scene["provenance"],
                    "source_file": str(source) if source else None,
                    "source_range": source_range,
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()
                    if source
                    else None,
                    "playback_speed": 1,
                    "tail_hold_seconds": max(0, duration - (source_range[1] - source_range[0]))
                    if source_range
                    else 0,
                }
            )
            clock += duration
            print(
                f"Rendered scene {index + 1}/{len(scenes)}: {scene['title']} ({duration:.2f}s)",
                flush=True,
            )

        concat = work / "concat.txt"
        concat.write_text("".join(f"file '{segment}'\n" for segment in encoded))
        master = out / "faultline-judge-captioned.mp4"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(master),
            ]
        )
        if args.narration_audio:
            audio = args.narration_audio.resolve()
            if float(probe(audio)["format"]["duration"]) > total:
                parser.error(
                    "Narration is longer than the master; revise its timing "
                    "rather than speeding it up"
                )
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(master),
                    "-i",
                    str(audio),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11,apad",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-t",
                    str(total),
                    "-movflags",
                    "+faststart",
                    str(out / "faultline-judge-narrated.mp4"),
                ]
            )

    (out / "faultline-judge.srt").write_text(
        "\n\n".join(
            f"{index}\n{timestamp(start)} --> {timestamp(end)}\n{text}"
            for index, (start, end, text) in enumerate(subtitles, 1)
        )
        + "\n"
    )
    metadata = probe(master)
    outputs = {
        master.name: {
            "media": metadata,
            "sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        }
    }
    if args.narration_audio:
        narrated = out / "faultline-judge-narrated.mp4"
        outputs[narrated.name] = {
            "media": probe(narrated),
            "sha256": hashlib.sha256(narrated.read_bytes()).hexdigest(),
        }
    (out / "edit-list.json").write_text(
        json.dumps(
            {
                "duration_seconds": total,
                "editorial_note": (
                    "Cuts remove navigation or waiting between evidence views. "
                    "No source event playback is sped up. Still holds are listed per scene."
                ),
                "narration": "Owner audio supplied"
                if args.narration_audio
                else "Captioned master; no audio narration",
                "scenes": edit_list,
                "outputs": outputs,
            },
            indent=2,
        )
        + "\n"
    )
    print(master)


if __name__ == "__main__":
    main()
