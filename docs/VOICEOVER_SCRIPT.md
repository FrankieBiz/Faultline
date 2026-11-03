# FaultLine Hackathon Demo: Master Voiceover Scripts

This document provides complete, cue-by-cue, word-for-word voiceover scripts for **both assembled video cuts** of FaultLine. All footage was recorded on the demo stack and the static showcase, with lower-third provenance captions. The Meta segment plays back a retained job at its recorded timing; it is not a live run.

Choose the version that fits your presentation format:
- **Track A (Standard Cut · 2:28.8):** Fast-paced, concise walkthrough covering the storefront defect, Meta Model API repair, the Inspector's live candidate pulse and auto-scrolling event log, Linux kernel sandboxing, applying the verified fix to the demo store and reverting it, the 5-of-6 wrong patch oracle proof, the holdout results, and the cross-platform Pre-Flight Gate.
- **Track B (Extended Master Cut with CLI Flex · 2:54.5):** Includes the extra high-flex terminal clip showing `./faultline gate http://127.0.0.1:3000` discovering UI elements, catching the HTTP 500 error, exiting 1 (`DEPLOYMENT_BLOCKED`), and emitting an exact agent remediation prompt before demonstrating Meta's repair.

Both cuts are strictly under the Hackathon's 3-minute (180-second) ceiling. Each one narrates the full repair lifecycle: the sandbox repair is verified, the verified fix is applied to the demo store, and the store is reverted to the seeded defect.

**Timing note.** The assembled rough cuts in [Footage files](#3-footage-files) run 2:13.8 (Track A) and 2:39.5 (Track B). They do not contain the 15-second Apply and Revert segment, which the scripted clips predate ([storyboard](VIDEO_STORYBOARD.md)). Record that segment live in the Inspector and splice it in directly after the Inspector segment. The timestamps below assume it is in place. Until it is, every cue after the Inspector segment runs 15 seconds early against the old cut.

## Claim sources

Every figure spoken below comes from a committed record. Re-check this table before re-recording if any record changes.

| Spoken claim | Record |
| --- | --- |
| "In under seven seconds, Meta returns a … diff" | Retained job `3573b32b`: `generation_ms` 6,863 ([replay review](evidence/2026-10-28-meta-replay-review.md), [job record](replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/job.json)) |
| "44 independent checks, 27 of them business rules, on the first attempt" | Same job: one attempt; verification report = 16 checkout + 1 confirmation + 27 regression assertions, all passed. The checks run outside the sandbox, against the sandboxed build. |
| "512 megabytes of RAM, 64 tasks, and one CPU" | cgroup v2 limits read back from the kernel ([submission](DEVPOST_SUBMISSION.md), [Inspector audit](audits/INSPECTOR_PERFECTION_AUDIT.md#confirmed-correct-no-change)) |
| "accepts five of six plausible wrong repairs … reject all six" | Authored gauntlet ([evaluation](EVALUATION.md#what-verification-catches)); deterministic fallback and DeepSeek runs, not Meta |
| "All 2,793 project tests pass" | `make check` 2,631 (2,157 orchestrator/CLI, 340 backend/root, 134 runner unit), `make browser` 85 (69 Inspector, 2 storefront, 14 showcase), and `make integration` 77 isolated tests with skips disallowed. Strict mypy reports zero errors across 115 source files ([submission](DEVPOST_SUBMISSION.md#evidence-at-a-glance)). |
| "Apply Verified Fix writes it to the demo store only; live checkout now returns HTTP 201" | Pre-film verification record of November 1, 2026: apply left the store `patched` and the live checkout returned 201; revert returned the store to `seeded` ([record](evidence/2026-11-01-prefilm-verification.json)). Apply delivers only the bundled demo store's fix. Project runs never change the user's source. |
| "On ten unfamiliar holdout defects … eighteen of twenty runs … rejected both wrong patches" | Holdout suite, two trials with DeepSeek `deepseek-v4-pro`, **not Meta** ([evaluation](EVALUATION.md#unfamiliar-defects), [record](evidence/2026-10-28-evaluation-deepseek-v4-pro.json)). Always say "non-Meta model"; Meta has not been run on the holdout. |
| "a live pulse marks the candidate being verified … the event log auto-scrolls" | Inspector badge "Sandbox verification in progress · Candidate N of up to M" and the event log's "Following live output" lock, added in `1f27e8c` (November 3, 2026). **The November 1 footage predates them:** re-record the Inspector segment on `1f27e8c` or later and update its caption date before using this line. |
| "Pre-Flight Gate … on macOS, Linux, and Windows" | The gate CLI is CI-tested on all three (`platform-smoke.yml`). The macOS (`sandbox-exec` + `setrlimit`) and Windows (Job Object) isolation engines exist but have not run natively, so sandbox *repair* and its kernel limits are narrated as Linux only; do not narrate native macOS or Windows isolation. |
| "thirty interactive elements across three screens" (Track B) | Seeded-storefront gate in the pre-film verification record of November 1, 2026: `elements_explored` 30, which counts distinct links, product cards, buttons, and form fields discovered on the home, product, and checkout screens. The crash came after 7 actions ([record](evidence/2026-11-01-prefilm-verification.json)). "Thirty" counts elements the crawler discovered, not elements it clicked. It clicks in shopping-funnel order and halts at the first failure. If a re-recorded take prints a different `elements_explored`, speak that number. |

The Inspector segment is a local deterministic-fallback run, not a Meta trial, and its caption says so.

---

# Track B: Extended Master Cut with Pre-Flight CLI Gate Flex (2:54.5)
**Video File:** [`data/footage/20261101-193931/rough-cut-extended.mp4`](../data/footage/20261101-193931/rough-cut-extended.mp4) (local, see [Footage files](#3-footage-files)). It runs 2:39.5 until the Apply and Revert segment is spliced in.  
**Total Duration:** 2 minutes, 54.5 seconds (174.5 s)

### Segment 1: The Problem (0:00 – 0:28 | 28 seconds)
- **On-Screen Picture:** BuggyShop storefront on `http://127.0.0.1:3000`. Adding two Trail Mugs to cart, leaving coupon input blank, clicking "Place order", triggering the unhandled HTTP 500 error banner.
- **Lower-Third Caption:** `Seeded demo store, recorded on this machine · A deliberately planted defect: an empty coupon makes checkout return HTTP 500`
- **Voiceover Narration (speak from 0:01 to 0:24):**
  > "As autonomous coding agents increasingly build and deploy software, they often make quick patches that silence errors on the surface while silently breaking core business logic.
  >
  > Here on BuggyShop, leaving the coupon field empty crashes checkout with an unhandled HTTP 500 error. The homepage is fine, so monitoring stays green—but every checkout without a coupon fails."

---

### Segment 2: The Pre-Flight Agent Gate CLI Flex (0:28 – 0:53 | 25 seconds)
- **On-Screen Picture:** Clean dark terminal window executing `./faultline gate http://127.0.0.1:3000`. Headless Chromium scans each screen it reaches for interactive elements: links, product cards, buttons, and form fields. It discovers 30 of them across 3 screens (home, product, checkout) and works through them in shopping-funnel order in seven actions (the Trail Mug product card, Add to cart, Go to checkout, the required form fields, Place order). It intercepts the unhandled HTTP 500 on `POST /api/checkout`, prints a red `🛑 FAILED · DEPLOYMENT_BLOCKED (exit 1)` banner, displays the reproduction journey, and formats an exact agent remediation prompt.
- **Lower-Third Caption:** `Pre-Flight Agent Gate · CLI on this machine · Deterministic Playwright exploration (heuristics, no model) exits 1 (DEPLOYMENT_BLOCKED) · generates exact fix prompt`
- **Voiceover Narration (speak from 0:29 to 0:51):**
  > "Before an agent ships, the Pre-Flight Gate runs.
  >
  > `./faultline gate` drives headless Chromium. It scans every link, product card, button, and form field it reaches, thirty interactive elements across three screens. It works the shopping funnel, catches the checkout crash, exits 1 to block the deployment, and hands the agent an exact reproduction and fix prompt."

---

### Segment 3: Meta Model Repair & Verification (0:53 – 1:27 | 34 seconds)
- **On-Screen Picture:** Public Judge Page playing back the retained `muse-spark-1.3` repair job (`3573b32b`) at recorded timing. Showing the baseline error, prompt containment, the one-line unified diff, and all 44 business assertions passing.
- **Lower-Third Caption:** `Recorded Meta muse-spark-1.3 repair, played back at real timing · Job 3573b32b from October 28, 2026, replayed on the judge page · not a live run`
- **Voiceover Narration (speak from 0:54 to 1:24):**
  > "This is FaultLine: a verification layer for AI-written repairs.
  >
  > Here, Meta's `muse-spark-1.3` model receives the checkout's business contract and the failure evidence—never the bug or the fix.
  >
  > In under seven seconds, Meta returns a schema-bound single-file diff. The candidate runs in a kernel-isolated sandbox and passes all 44 independent checks, 27 of them business rules, on the first attempt."

---

### Segment 4: Local Developer Studio & Kernel Sandboxing (1:27 – 2:09 | 42 seconds)
- **On-Screen Picture:** Local Inspector Studio on `http://127.0.0.1:4000`. Clicking "Run sandbox repair", watching live stages execute with the pulsing "Candidate 1 of up to N" badge and the event log following live output, verifying kernel-enforced aggregate cgroup limits, and inspecting the 44 passing assertions and proof bundle.
- **Lower-Third Caption:** `Local run with the deterministic fallback: not a Meta trial · Inspector on this machine, November 1, 2026 · preset patch, real gates, isolated runtime`
- **Voiceover Narration (speak from 1:28 to 2:05):**
  > "In our local developer studio, a live pulse marks the candidate being verified, and the event log auto-scrolls to follow every stage. The candidate executes inside Linux Bubblewrap namespaces under aggregate cgroup v2 limits—512 megabytes of RAM, 64 tasks, and one CPU, verified from the kernel with adversarial OOM-kill probes.
  >
  > The sandbox confines the candidate; independent business oracles decide if it's correct. 44 assertions verify the fix, an offline checksummed evidence bundle is generated, and all 2,793 project tests pass."

---

### Segment 5: Apply & Revert, Closing the Loop (2:09 – 2:24 | 15 seconds)
- **Lower-Third Caption:** `Live local run · Apply writes the verified fix to the bundled demo store only · nothing is deployed or merged`

**Cue 5a · Apply (2:09 – 2:17)**
- **On-Screen Picture:** The Live Agent Mission HUD reads "Fix verified: 44/44 assertions passed". Click **Apply Verified Fix to Demo Store**. Hold on "Applying the verified fix…", then on "Applied to `apps/buggyshop-backend/app/routes/checkout.py`. Live checkout re-checked: HTTP 201 · defect gone." The HUD status changes to "Fix applied". In the Demo Playground, Step 3 "Apply fix" shows ✓ and `HTTP 201 · checkout works`.
- **Voiceover Narration (speak from 2:10 to 2:17):**
  > "Apply Verified Fix writes it to the demo store only; live checkout now returns HTTP 201."

**Cue 5b · Revert (2:17 – 2:24)**
- **On-Screen Picture:** In the Demo Playground bar, click **Revert store**, then **Confirm revert?**. Hold on the notice "Reverted `apps/buggyshop-backend/app/routes/checkout.py` to the seeded defect. Checkout without a coupon fails again." The headline returns to the seeded state.
- **Voiceover Narration (speak from 2:18 to 2:22):**
  > "Revert store restores the seeded bug. Nothing is deployed."

---

### Segment 6: Verification vs Symptom Checks (2:24 – 2:49 | 25 seconds)
- **On-Screen Picture:** Public Judge Page Patch Explorer. Comparing candidate patches (`early_return_unsaved`, `zero_all_discounts`, `null_coupon_only`). Showing how naive HTTP 201 checks accept 5 of 6 wrong patches, while FaultLine rejects all 6. For the holdout line, cut away to (or overlay) the unfamiliar-defects table from `docs/EVALUATION.md`; the judge page does not show it.
- **Lower-Third Caption:** `Recorded evaluation results · Corpus runs of October 28, 2026 with the deterministic fallback and DeepSeek, not Meta`
- **Voiceover Narration (speak from 2:25 to 2:46):**
  > "A naive status check accepts five of six plausible wrong repairs; FaultLine rejects all six. On ten unfamiliar holdout defects, a labeled non-Meta model verified eighteen of twenty runs, and the gates rejected both wrong patches.
  >
  > The Pre-Flight Gate runs on macOS, Linux, and Windows."

---

### Segment 7: End Card & Outro (2:49 – 2:54.5 | 5.5 seconds)
- **On-Screen Picture:** FaultLine end card displaying repository and live showcase links.
- **Voiceover Narration (speak from 2:49 to 2:53):**
  > "FaultLine: repairs you can inspect, and a gate your agents can obey."

---
---

# Track A: Standard Cut (2:28.8)
**Video File:** [`data/footage/20261101-193931/rough-cut.mp4`](../data/footage/20261101-193931/rough-cut.mp4) (local, see [Footage files](#3-footage-files)). It runs 2:13.8 until the Apply and Revert segment is spliced in.  
**Total Duration:** 2 minutes, 28.8 seconds (148.8 s)

### Segment 1: The Problem (0:00 – 0:28 | 28 seconds)
- **On-Screen Picture:** BuggyShop storefront on `http://127.0.0.1:3000`. Adding two Trail Mugs to cart, leaving coupon blank, clicking "Place order", triggering unhandled HTTP 500 error banner.
- **Lower-Third Caption:** `Seeded demo store, recorded on this machine · A deliberately planted defect: an empty coupon makes checkout return HTTP 500`
- **Voiceover Narration (speak from 0:01 to 0:24):**
  > "As autonomous coding agents increasingly build and deploy software, they often make quick patches that silence errors on the surface while silently breaking core business logic.
  >
  > Here on BuggyShop, leaving the coupon field empty crashes checkout with an unhandled HTTP 500 error. The homepage is fine, so monitoring stays green—but every checkout without a coupon fails."

---

### Segment 2: Meta Model Repair & Verification (0:28 – 1:02 | 34 seconds)
- **On-Screen Picture:** Public Judge Page playing back the retained `muse-spark-1.3` repair job (`3573b32b`) at recorded timing. Showing the baseline error, prompt containment, the one-line unified diff, and all 44 business assertions passing.
- **Lower-Third Caption:** `Recorded Meta muse-spark-1.3 repair, played back at real timing · Job 3573b32b from October 28, 2026, replayed on the judge page · not a live run`
- **Voiceover Narration (speak from 0:29 to 0:59):**
  > "This is FaultLine: a verification layer for AI-written repairs.
  >
  > Here, Meta's `muse-spark-1.3` model receives the checkout's business contract and the failure evidence—never the bug or the fix.
  >
  > In under seven seconds, Meta returns a schema-bound single-file diff. The candidate runs in a kernel-isolated sandbox and passes all 44 independent checks, 27 of them business rules, on the first attempt."

---

### Segment 3: Local Developer Studio & Kernel Sandboxing (1:02 – 1:44 | 42 seconds)
- **On-Screen Picture:** Local Inspector Studio on `http://127.0.0.1:4000`. Clicking "Run sandbox repair", watching live stages execute with the pulsing "Candidate 1 of up to N" badge and the event log following live output, verifying kernel-enforced aggregate cgroup limits, and inspecting the 44 passing assertions and proof bundle.
- **Lower-Third Caption:** `Local run with the deterministic fallback: not a Meta trial · Inspector on this machine, November 1, 2026 · preset patch, real gates, isolated runtime`
- **Voiceover Narration (speak from 1:03 to 1:40):**
  > "In our local developer studio, a live pulse marks the candidate being verified, and the event log auto-scrolls to follow every stage. The candidate executes inside Linux Bubblewrap namespaces under aggregate cgroup v2 limits—512 megabytes of RAM, 64 tasks, and one CPU, verified from the kernel with adversarial OOM-kill probes.
  >
  > The sandbox confines the candidate; independent business oracles decide if it's correct. 44 assertions verify the fix, an offline checksummed evidence bundle is generated, and all 2,793 project tests pass."

---

### Segment 4: Apply & Revert, Closing the Loop (1:44 – 1:59 | 15 seconds)
- **Lower-Third Caption:** `Live local run · Apply writes the verified fix to the bundled demo store only · nothing is deployed or merged`

**Cue 4a · Apply (1:44 – 1:52)**
- **On-Screen Picture:** The Live Agent Mission HUD reads "Fix verified: 44/44 assertions passed". Click **Apply Verified Fix to Demo Store**. Hold on "Applying the verified fix…", then on "Applied to `apps/buggyshop-backend/app/routes/checkout.py`. Live checkout re-checked: HTTP 201 · defect gone." The HUD status changes to "Fix applied". In the Demo Playground, Step 3 "Apply fix" shows ✓ and `HTTP 201 · checkout works`.
- **Voiceover Narration (speak from 1:45 to 1:52):**
  > "Apply Verified Fix writes it to the demo store only; live checkout now returns HTTP 201."

**Cue 4b · Revert (1:52 – 1:59)**
- **On-Screen Picture:** In the Demo Playground bar, click **Revert store**, then **Confirm revert?**. Hold on the notice "Reverted `apps/buggyshop-backend/app/routes/checkout.py` to the seeded defect. Checkout without a coupon fails again." The headline returns to the seeded state.
- **Voiceover Narration (speak from 1:53 to 1:57):**
  > "Revert store restores the seeded bug. Nothing is deployed."

---

### Segment 5: Verification vs Symptom Checks (1:59 – 2:24 | 25 seconds)
- **On-Screen Picture:** Public Judge Page Patch Explorer. Comparing candidate patches (`early_return_unsaved`, `zero_all_discounts`, `null_coupon_only`). Showing how naive HTTP 201 checks accept 5 of 6 wrong patches, while FaultLine rejects all 6. For the holdout line, cut away to (or overlay) the unfamiliar-defects table from `docs/EVALUATION.md`; the judge page does not show it.
- **Lower-Third Caption:** `Recorded evaluation results · Corpus runs of October 28, 2026 with the deterministic fallback and DeepSeek, not Meta`
- **Voiceover Narration (speak from 2:00 to 2:21):**
  > "A naive status check accepts five of six plausible wrong repairs; FaultLine rejects all six. On ten unfamiliar holdout defects, a labeled non-Meta model verified eighteen of twenty runs, and the gates rejected both wrong patches.
  >
  > The Pre-Flight Gate runs on macOS, Linux, and Windows."

---

### Segment 6: End Card & Outro (2:24 – 2:28.8 | 4.8 seconds)
- **On-Screen Picture:** FaultLine end card displaying repository and live showcase links.
- **Voiceover Narration (speak from 2:24 to 2:28):**
  > "FaultLine: repairs you can inspect, and a gate your agents can obey."

---

## Recording Instructions & Audio Mux Workflow

### 1. Delivery & Pacing
- **Tone:** Crisp, confident, technical, and objective. Deliver like a principal systems engineer walking through production infrastructure.
- **Pacing:** Standard cadence (~135 words per minute). Each segment includes 3 to 4 seconds of buffer at the transition point so you never have to rush.
- **Microphone:** Use a clear mic, record in a quiet room, and keep input levels around -12 dB to avoid clipping.

### 2. Audio-to-Video Muxing Command
Once you record your voiceover track as `voiceover.wav` or `voiceover.mp3`, merge it directly with either video cut in one command. Splice in the Apply and Revert segment first. `-shortest` cuts the output to the shorter input, so muxing the full narration onto a cut that lacks the segment drops the last 15 seconds of narration.

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
