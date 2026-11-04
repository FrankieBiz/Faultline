# FaultLine: final judge recording

Prepared November 4, 2026. The current captioned master targets **2:59**, below our chosen three-minute target. The public official rules do not specify a video length; verify the signed-in [Cerebral Valley submission form](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit) before upload.

The spoken copy is in [JUDGE_VIDEO_SCRIPT.md](JUDGE_VIDEO_SCRIPT.md). The finished edit plan, source ranges, hashes and subtitle timings are delivered beside the local MP4. Those generated media files live under ignored `data/`, so committing this document does not upload the video.

## Final edit

| Time | Picture | Evidence label |
| --- | --- | --- |
| 0:00–0:15 | Empty coupon, Place order, real checkout HTTP 500 | Recorded Nov 4; deliberately seeded local demo defect |
| 0:15–0:31 | Actual captured `faultline gate` verdict, reproduction and remediation | Actual CLI exit 1; selected fields from saved stdout |
| 0:31–1:02 | The complete retained Meta repair at recorded timing, then its diff | Meta `muse-spark-1.3`, job `3573b32b`, Oct 28; not a new live trial |
| 1:02–1:33 | Local Inspector repair, verdict, patch and evidence | Recorded Nov 4; deterministic fallback, no model call; execution unsped |
| 1:33–1:55 | `early_return_unsaved`: status-only Accepted, FaultLine Rejected | Authored corpus patch; recorded evaluation, not Meta output; still held for reading |
| 1:55–2:07 | Apply the verified demo fix; both fresh sessions return HTTP 201 | Real local Apply and recheck |
| 2:07–2:25 | Actual clean-gate stdout, exit 0 and `stop_reason: exhausted` | Real CLI result; waiting between views cut |
| 2:25–2:34 | Revert; fresh checks return HTTP 500 again | Real local Revert; seeded source restored |
| 2:34–2:48 | Current limitations | One checkout route; single-file repair; shared kernel; Meta on one scenario |
| 2:48–2:59 | Source and interactive judge-page URLs | Closing card |

No source event playback is sped up. Cuts remove navigation or waiting between evidence views. Still-frame holds allow the viewer to read results; each hold is recorded in `edit-list.json`. The full 13.06-second playback of the retained Meta job is included. The original job completed at 13.039 seconds; tiny video sampling differences are not new execution measurements.

## Fresh recording sources

- `data/footage/20261104-judge/`: successful clips 01, 02, 03, 04, 07 and 08. The first clip 06 failed because a completed job is not automatically reopened after page reload; exclude it.
- `data/footage/20261104-judge-06-final/`: the successful final Apply/re-gate/Revert clip for exact verified local job `14e0a75f-1732-4224-a403-22afe8979d8a`.
- Local job JSON records a failed 18-check baseline, a passing 44-check candidate and successful cleanup. It is labeled `deterministic-checkout-v1`, with no model call.
- CLI sidecars preserve complete stdout, stderr, command, timestamps and actual exit status. The clean gate explored 45 elements across four screens with 12 actions and finished `exhausted`.
- Live-check sidecars record `[201, 201]` after Apply and `[500, 500]` after Revert. Store states are seeded → patched → seeded.
- The historical `record-terminal-flex.mjs` is a scripted visual transcript. It is not used in this judge video and must not be described as an actual CLI capture.

## Reproduce

First run `make check`, `make integration`, and `make browser`. Do not rebuild `.next` while a recording stack is using it. Use an isolated checkout and disposable demo data; recording Apply changes only that checkout's bundled demo source, and the recorder restores it.

Start the demo stack on free ports (the recorder itself does not start it):

```bash
BUGGYSHOP_API_PORT=8760 FAULTLINE_PORT=9760 BUGGYSHOP_PORT=3760 INSPECTOR_PORT=4760 ./scripts/start-demo.sh
```

Without model credentials, readiness must name the deterministic fallback. The recording command refuses a different provider before submitting its repair:

```bash
./scripts/record-footage.sh --stack-ports 3760,4760,8760,9760 --serve-docs 8770 \
  --only 01,02,03,07,04,06,08 --require-deterministic --judge-cut \
  --out data/footage/NEW-JUDGE-TAKE
```

The recorder saves exact submitted job identity. To record clip 06 separately, use `--only 06 --repair-job-id JOB_UUID` and a new output directory. Never overwrite previous raw takes.

Use the delivered edit-plan format with the assembler. Plan source paths are relative to the plan file. Confirm raw video bounds with `ffprobe`: browser wall-clock marks can differ slightly from encoded first/last frames, and a CLI capture can complete before its first painted video frame.

```bash
uv run --no-project python scripts/assemble-judge-video.py \
  data/submission/2026-11-04/edit-plan.json --out data/submission/2026-11-04
```

Outputs: `faultline-judge-captioned.mp4`, English `faultline-judge.srt`, and `edit-list.json` with media metadata and SHA-256 hashes. The master has burned-in explanatory captions and evidence labels, with no audio narration. For an owner-recorded voice track already timed to the master, add `--narration-audio /path/to/narration.wav`; the assembler preserves the video speed, normalizes audio and emits a separate narrated MP4. A voice track longer than the master is refused.

## Review and upload

Inspect the exported file, rather than trusting a successful render. Check every scene's picture against its caption, especially the clean-gate still before navigation and the fresh failing check after Revert. Decode the whole file, verify 1920×1080 H.264 at 30 fps, inspect first/last frames, check the subtitle end time and confirm no keys or private account material appear.

The current package is local until approved and uploaded. The owner's remaining steps are to approve the recording/narration, authorize the public release, upload a video accessible to judges and paste its URL, confirm the Indie Developer track and authenticated form requirements, then submit before the official deadline. Do not substitute a local file path for a public video URL.
