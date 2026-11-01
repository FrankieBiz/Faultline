# FaultLine 3-Minute Hackathon Demo: Voiceover Script

This script is timed byte-for-byte to the assembled video rough cut:
**`data/footage/20261101-193931/rough-cut.mp4`** (Total duration: **2:13.8** / 133.80 seconds).

All footage was recorded live on the demo stack and the static showcase. Lower-third captions state exact provenance throughout the video.

---

## Cue-by-Cue Timing Sheet

### Segment 1: The Problem (0:00 – 0:28 | 28 seconds)
- **On-Screen Picture:** BuggyShop storefront on `http://127.0.0.1:3000`. Adding two Trail Mugs to cart, leaving coupon input blank, clicking "Place order", triggering the unhandled HTTP 500 error banner.
- **Lower-Third Caption:** `Seeded demo store, recorded on this machine · A deliberately planted defect: an empty coupon makes checkout return HTTP 500`
- **Narration (speak from 0:01 to 0:24):**
  > "As autonomous coding agents increasingly build and deploy software, they often make quick patches that silence errors on the surface while silently breaking core business logic.
  >
  > Here on BuggyShop, leaving the coupon field empty crashes checkout with an unhandled HTTP 500 error. The homepage is fine, so monitoring stays green—but real customer transactions are dead."

---

### Segment 2: Meta Model Repair & Verification (0:28 – 1:02 | 34 seconds)
- **On-Screen Picture:** Public Judge Page playing back the retained `muse-spark-1.3` repair job (`3573b32b`) at recorded timing. Showing the baseline error, prompt containment, the one-line unified diff, and all 44 business assertions passing.
- **Lower-Third Caption:** `Recorded Meta muse-spark-1.3 repair, played back at real timing · Job 3573b32b from October 28, 2026, replayed on the judge page · not a live run`
- **Narration (speak from 0:29 to 0:59):**
  > "This is FaultLine: an autonomous immune system for web applications.
  >
  > Here, Meta's `muse-spark-1.3` model receives the checkout's business contract and the failure evidence—never the bug or the fix.
  >
  > In under seven seconds, Meta returns a schema-bound single-file diff. The candidate runs in a kernel-isolated sandbox against 44 independent checks, passing every assertion on the first attempt."

---

### Segment 3: Local Developer Studio & Kernel Sandboxing (1:02 – 1:44 | 42 seconds)
- **On-Screen Picture:** Local Inspector Studio on `http://127.0.0.1:4000`. Clicking "Run sandbox repair", watching live stages execute, verifying kernel-enforced aggregate cgroup limits, and inspecting the 44 passing assertions and proof bundle.
- **Lower-Third Caption:** `Local run with the deterministic fallback: not a Meta trial · Inspector on this machine, November 1, 2026 · preset patch, real gates, isolated runtime`
- **Narration (speak from 1:03 to 1:40):**
  > "In our local developer studio, the candidate executes inside Linux Bubblewrap namespaces under aggregate cgroup v2 limits—strictly enforcing 512 megabytes of RAM, 64 tasks, and one CPU quota, verified directly from the kernel with adversarial OOM-kill probes.
  >
  > The sandbox confines the candidate, but our independent business oracles decide if it's correct. 44 assertions verify the fix, and an offline checksummed evidence bundle is generated."

---

### Segment 4: Verification vs Symptom Checks (1:44 – 2:09 | 25 seconds)
- **On-Screen Picture:** Public Judge Page Patch Explorer. Comparing candidate patches (`early_return_unsaved`, `zero_all_discounts`, `null_coupon_only`). Showing how naive HTTP 201 checks accept 5 of 6 wrong patches, while FaultLine rejects all 6.
- **Lower-Third Caption:** `Recorded evaluation results · Corpus runs of October 28, 2026 with the deterministic fallback and DeepSeek, not Meta`
- **Narration (speak from 1:45 to 2:06):**
  > "Why independent verification matters: on this corpus, a naive status check accepts five of six plausible wrong repairs, including one that returns 201 but silently drops the customer order!
  >
  > FaultLine's independent assertions reject every single wrong patch. Our cross-platform Pre-Flight Gate blocks broken code before deployment on macOS, Linux, and Windows."

---

### Segment 5: End Card & Outro (2:09 – 2:14 | 5 seconds)
- **On-Screen Picture:** FaultLine end card displaying repository and live showcase links.
- **Narration (speak from 2:09 to 2:13):**
  > "FaultLine: repairs you can inspect, and a gate your agents can obey."

---

## Pacing & Audio Tips

1. **Tone:** Crisp, confident, technical, and objective. Speak like an infrastructure engineer demonstrating real tooling, not a sales pitch.
2. **Speed:** ~130–140 words per minute. There is ample padding (3–4 seconds of silence) at the end of each cut so you never need to rush.
3. **One-Liner Audio Mux:** Once you record your voiceover track (`voiceover.wav` or `voiceover.mp3`), mux it with the rough cut into the final deliverable with ffmpeg:
   ```bash
   ffmpeg -i data/footage/20261101-193931/rough-cut.mp4 -i voiceover.wav \
     -c:v copy -c:a aac -b:a 192k -shortest final-demo.mp4
   ```
4. **Playback Preview:** You can preview the assembled video immediately in any media player (VLC, mpv, browser):
   ```bash
   mpv data/footage/20261101-193931/rough-cut.mp4
   # or
   xdg-open data/footage/20261101-193931/rough-cut.mp4
   ```
