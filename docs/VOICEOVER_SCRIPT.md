# FaultLine Hackathon Demo: Master Voiceover Scripts

This document provides complete, cue-by-cue, word-for-word voiceover scripts for **both assembled video cuts** of FaultLine. All footage was recorded live on the demo stack and static showcase with lower-third provenance captions.

Choose the version that fits your presentation format:
- **Track A (Standard Cut · 2:13.8):** Fast-paced, concise walkthrough covering the storefront defect, Meta Model API repair, Linux kernel sandboxing, and the 5-of-6 wrong patch oracle proof.
- **Track B (Extended Master Cut with CLI Flex · 2:39.5):** Includes the extra high-flex terminal clip showing `./faultline gate http://127.0.0.1:3000` discovering UI elements, catching the HTTP 500 error, exiting 1 (`DEPLOYMENT_BLOCKED`), and emitting an exact agent remediation prompt before demonstrating Meta's repair.

Both cuts are strictly under the Hackathon's 3-minute (180-second) ceiling.

## Claim sources

Every figure spoken below comes from a committed record. Re-check this table before re-recording if any record changes.

| Spoken claim | Record |
| --- | --- |
| "In under seven seconds, Meta returns a … diff" | Retained job `3573b32b`: `generation_ms` 6,863 ([replay review](evidence/2026-10-28-meta-replay-review.md), [job record](replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/job.json)) |
| "44 independent checks, 27 of them business rules, on the first attempt" | Same job: one attempt; verification report = 16 checkout + 1 confirmation + 27 regression assertions, all passed. The checks run outside the sandbox, against the sandboxed build. |
| "512 megabytes of RAM, 64 tasks, and one CPU" | cgroup v2 limits read back from the kernel ([submission](DEVPOST_SUBMISSION.md), [Inspector audit](audits/INSPECTOR_PERFECTION_AUDIT.md#confirmed-correct-no-change)) |
| "accepts five of six plausible wrong repairs … reject all six" | Authored gauntlet ([evaluation](EVALUATION.md#what-verification-catches)); deterministic fallback and DeepSeek runs, not Meta |

The Inspector segment is a local deterministic-fallback run, not a Meta trial, and its caption says so.

---

# Track B: Extended Master Cut with Pre-Flight CLI Gate Flex (2:39.5)
**Video File:** [`data/footage/20261101-193931/rough-cut-extended.mp4`](../data/footage/20261101-193931/rough-cut-extended.mp4) (local, see [Footage files](#3-footage-files))  
**Total Duration:** 2 minutes, 39.5 seconds (159.5 s)

### Segment 1: The Problem (0:00 – 0:28 | 28 seconds)
- **On-Screen Picture:** BuggyShop storefront on `http://127.0.0.1:3000`. Adding two Trail Mugs to cart, leaving coupon input blank, clicking "Place order", triggering the unhandled HTTP 500 error banner.
- **Lower-Third Caption:** `Seeded demo store, recorded on this machine · A deliberately planted defect: an empty coupon makes checkout return HTTP 500`
- **Voiceover Narration (speak from 0:01 to 0:24):**
  > "As autonomous coding agents increasingly build and deploy software, they often make quick patches that silence errors on the surface while silently breaking core business logic.
  >
  > Here on BuggyShop, leaving the coupon field empty crashes checkout with an unhandled HTTP 500 error. The homepage is fine, so monitoring stays green—but real customer transactions are dead."

---

### Segment 2: The Pre-Flight Agent Gate CLI Flex (0:28 – 0:53 | 25 seconds)
- **On-Screen Picture:** Clean dark terminal window executing `./faultline gate http://127.0.0.1:3000`. Headless Chromium explores 30 interactive elements across 3 screens, executes the checkout sequence, intercepts the unhandled HTTP 500 on `POST /api/checkout`, prints a red `🛑 FAILED · DEPLOYMENT_BLOCKED (exit 1)` banner, displays the reproduction journey, and formats an exact agent remediation prompt.
- **Lower-Third Caption:** `Pre-Flight Agent Gate · CLI on this machine · Deterministic Playwright exploration exits 1 (DEPLOYMENT_BLOCKED) · generates exact fix prompt`
- **Voiceover Narration (speak from 0:29 to 0:49):**
  > "Before an agent or CI/CD pipeline pushes broken code to production, our Pre-Flight Gate intercepts it.
  >
  > Running `./faultline gate` launches headless Chromium, autonomously explores user journeys across thirty interactive elements, catches the checkout crash, exits 1 with a blocked deployment verdict, and emits an exact reproduction trace and remediation prompt for the coding agent."

---

### Segment 3: Meta Model Repair & Verification (0:53 – 1:27 | 34 seconds)
- **On-Screen Picture:** Public Judge Page playing back the retained `muse-spark-1.3` repair job (`3573b32b`) at recorded timing. Showing the baseline error, prompt containment, the one-line unified diff, and all 44 business assertions passing.
- **Lower-Third Caption:** `Recorded Meta muse-spark-1.3 repair, played back at real timing · Job 3573b32b from October 28, 2026, replayed on the judge page · not a live run`
- **Voiceover Narration (speak from 0:54 to 1:24):**
  > "This is FaultLine: an autonomous immune system for web applications.
  >
  > Here, Meta's `muse-spark-1.3` model receives the checkout's business contract and the failure evidence—never the bug or the fix.
  >
  > In under seven seconds, Meta returns a schema-bound single-file diff. The candidate runs in a kernel-isolated sandbox and passes all 44 independent checks, 27 of them business rules, on the first attempt."

---

### Segment 4: Local Developer Studio & Kernel Sandboxing (1:27 – 2:09 | 42 seconds)
- **On-Screen Picture:** Local Inspector Studio on `http://127.0.0.1:4000`. Clicking "Run sandbox repair", watching live stages execute, verifying kernel-enforced aggregate cgroup limits, and inspecting the 44 passing assertions and proof bundle.
- **Lower-Third Caption:** `Local run with the deterministic fallback: not a Meta trial · Inspector on this machine, November 1, 2026 · preset patch, real gates, isolated runtime`
- **Voiceover Narration (speak from 1:28 to 2:05):**
  > "In our local developer studio, the candidate executes inside Linux Bubblewrap namespaces under aggregate cgroup v2 limits—strictly enforcing 512 megabytes of RAM, 64 tasks, and one CPU quota, verified directly from the kernel with adversarial OOM-kill probes.
  >
  > The sandbox confines the candidate, but our independent business oracles decide if it's correct. 44 assertions verify the fix, and an offline checksummed evidence bundle is generated."

---

### Segment 5: Verification vs Symptom Checks (2:09 – 2:34 | 25 seconds)
- **On-Screen Picture:** Public Judge Page Patch Explorer. Comparing candidate patches (`early_return_unsaved`, `zero_all_discounts`, `null_coupon_only`). Showing how naive HTTP 201 checks accept 5 of 6 wrong patches, while FaultLine rejects all 6.
- **Lower-Third Caption:** `Recorded evaluation results · Corpus runs of October 28, 2026 with the deterministic fallback and DeepSeek, not Meta`
- **Voiceover Narration (speak from 2:10 to 2:31):**
  > "Why independent verification matters: on this corpus, a naive status check accepts five of six plausible wrong repairs, including one that returns 201 but silently drops the customer order!
  >
  > FaultLine's independent assertions reject all six. Our cross-platform Pre-Flight Gate blocks broken code before deployment on macOS, Linux, and Windows."

---

### Segment 6: End Card & Outro (2:34 – 2:39 | 5 seconds)
- **On-Screen Picture:** FaultLine end card displaying repository and live showcase links.
- **Voiceover Narration (speak from 2:34 to 2:38):**
  > "FaultLine: repairs you can inspect, and a gate your agents can obey."

---
---

# Track A: Standard Cut (2:13.8)
**Video File:** [`data/footage/20261101-193931/rough-cut.mp4`](../data/footage/20261101-193931/rough-cut.mp4) (local, see [Footage files](#3-footage-files))  
**Total Duration:** 2 minutes, 13.8 seconds (133.8 s)

### Segment 1: The Problem (0:00 – 0:28 | 28 seconds)
- **On-Screen Picture:** BuggyShop storefront on `http://127.0.0.1:3000`. Adding two Trail Mugs to cart, leaving coupon blank, clicking "Place order", triggering unhandled HTTP 500 error banner.
- **Lower-Third Caption:** `Seeded demo store, recorded on this machine · A deliberately planted defect: an empty coupon makes checkout return HTTP 500`
- **Voiceover Narration (speak from 0:01 to 0:24):**
  > "As autonomous coding agents increasingly build and deploy software, they often make quick patches that silence errors on the surface while silently breaking core business logic.
  >
  > Here on BuggyShop, leaving the coupon field empty crashes checkout with an unhandled HTTP 500 error. The homepage is fine, so monitoring stays green—but real customer transactions are dead."

---

### Segment 2: Meta Model Repair & Verification (0:28 – 1:02 | 34 seconds)
- **On-Screen Picture:** Public Judge Page playing back the retained `muse-spark-1.3` repair job (`3573b32b`) at recorded timing. Showing the baseline error, prompt containment, the one-line unified diff, and all 44 business assertions passing.
- **Lower-Third Caption:** `Recorded Meta muse-spark-1.3 repair, played back at real timing · Job 3573b32b from October 28, 2026, replayed on the judge page · not a live run`
- **Voiceover Narration (speak from 0:29 to 0:59):**
  > "This is FaultLine: an autonomous immune system for web applications.
  >
  > Here, Meta's `muse-spark-1.3` model receives the checkout's business contract and the failure evidence—never the bug or the fix.
  >
  > In under seven seconds, Meta returns a schema-bound single-file diff. The candidate runs in a kernel-isolated sandbox and passes all 44 independent checks, 27 of them business rules, on the first attempt."

---

### Segment 3: Local Developer Studio & Kernel Sandboxing (1:02 – 1:44 | 42 seconds)
- **On-Screen Picture:** Local Inspector Studio on `http://127.0.0.1:4000`. Clicking "Run sandbox repair", watching live stages execute, verifying kernel-enforced aggregate cgroup limits, and inspecting the 44 passing assertions and proof bundle.
- **Lower-Third Caption:** `Local run with the deterministic fallback: not a Meta trial · Inspector on this machine, November 1, 2026 · preset patch, real gates, isolated runtime`
- **Voiceover Narration (speak from 1:03 to 1:40):**
  > "In our local developer studio, the candidate executes inside Linux Bubblewrap namespaces under aggregate cgroup v2 limits—strictly enforcing 512 megabytes of RAM, 64 tasks, and one CPU quota, verified directly from the kernel with adversarial OOM-kill probes.
  >
  > The sandbox confines the candidate, but our independent business oracles decide if it's correct. 44 assertions verify the fix, and an offline checksummed evidence bundle is generated."

---

### Segment 4: Verification vs Symptom Checks (1:44 – 2:09 | 25 seconds)
- **On-Screen Picture:** Public Judge Page Patch Explorer. Comparing candidate patches (`early_return_unsaved`, `zero_all_discounts`, `null_coupon_only`). Showing how naive HTTP 201 checks accept 5 of 6 wrong patches, while FaultLine rejects all 6.
- **Lower-Third Caption:** `Recorded evaluation results · Corpus runs of October 28, 2026 with the deterministic fallback and DeepSeek, not Meta`
- **Voiceover Narration (speak from 1:45 to 2:06):**
  > "Why independent verification matters: on this corpus, a naive status check accepts five of six plausible wrong repairs, including one that returns 201 but silently drops the customer order!
  >
  > FaultLine's independent assertions reject all six. Our cross-platform Pre-Flight Gate blocks broken code before deployment on macOS, Linux, and Windows."

---

### Segment 5: End Card & Outro (2:09 – 2:14 | 5 seconds)
- **On-Screen Picture:** FaultLine end card displaying repository and live showcase links.
- **Voiceover Narration (speak from 2:09 to 2:13):**
  > "FaultLine: repairs you can inspect, and a gate your agents can obey."

---

## Recording Instructions & Audio Mux Workflow

### 1. Delivery & Pacing
- **Tone:** Crisp, confident, technical, and objective. Deliver like a principal systems engineer walking through production infrastructure.
- **Pacing:** Standard cadence (~135 words per minute). Each segment includes 3 to 4 seconds of buffer at the transition point so you never have to rush.
- **Microphone:** Use a clear mic, record in a quiet room, and keep input levels around -12 dB to avoid clipping.

### 2. Audio-to-Video Muxing Command
Once you record your voiceover track as `voiceover.wav` or `voiceover.mp3`, merge it directly with either video cut in one command:

**For Track B (Extended Cut):**
```bash
ffmpeg -i data/footage/20261101-193931/rough-cut-extended.mp4 -i voiceover.wav \
  -c:v copy -c:a aac -b:a 192k -shortest final-demo-extended.mp4
```

**For Track A (Standard Cut):**
```bash
ffmpeg -i data/footage/20261101-193931/rough-cut.mp4 -i voiceover.wav \
  -c:v copy -c:a aac -b:a 192k -shortest final-demo-standard.mp4
```

### 3. Footage files

The rough cuts are local build outputs, not committed files. `data/` is gitignored, so the links above resolve only in a checkout where the footage has been recorded (`scripts/record-footage.sh`) and assembled (`scripts/assemble-footage.sh` for Track A, `scripts/assemble-extended-cut.sh` for Track B). Paths are relative to the repository root.

### 4. Immediate Playback Preview
You can preview either video file locally before recording:
```bash
# Preview Track B (Extended Cut)
mpv data/footage/20261101-193931/rough-cut-extended.mp4

# Preview Track A (Standard Cut)
mpv data/footage/20261101-193931/rough-cut.mp4
```
