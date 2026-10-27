---
name: virality
description: "Tactical playbook for engineering developer virality, high-sensory UI impact, cinematic demo loops, and multi-channel launch distribution for AI systems and devtools. Trigger when the user mentions 'viral', 'virality', 'go viral', 'launch video', 'demo video script', 'make it louder', 'social launch', 'Twitter thread', 'Hacker News launch', 'visual dopamine', or 'judge impact'."
---

# DevTool & AI Agent Virality Playbook

This skill provides an end-to-end operational framework for transforming technical developer tools and autonomous AI systems into viral sensations across X/Twitter, LinkedIn, Hacker News, YouTube, and hackathon judging panels.

---

## FaultLine evidence requirements

Read `docs/QUALITY_REVIEW.md`, `docs/PROJECT_STATUS.md`, and `docs/LAUNCH.md` before applying this playbook. The examples below are narrative templates, not verified FaultLine capabilities or measurements. Do not reuse their latency, savings, rejection-rate, production hot-patching, integration, or uptime claims without matching evidence. Green UI and exported reports must depend on actual job results and cleanup. Authored previews must remain labeled. Missing-key deterministic runs are not Meta trials. Do not invent sensory telemetry, receipt IDs, or progress timers to make a demonstration look faster. No social publishing is authorized merely by using this skill.

## 1. The Core Psychology of Developer Virality

Developers and tech investors are the most skeptical audience on the internet. They have seen hundreds of scripted, fake, or fragile AI wrappers. Generic feature tours, slides, and theoretical pitches achieve near-zero organic reach.

### What Actually Triggers Shares and Retweets:
1. **Visceral Pain + Instant Catharsis**: The demo must tap into a universal, acute nightmare (e.g., 2 AM production crash, broken checkout, PagerDuty alert, memory leak, infinite loop) and solve it before their eyes.
2. **"Holy Shit" Velocity**: The transition from catastrophe to autonomous resolution must take seconds, not minutes.
3. **The Anti-Vaporware Proof**: Skeptics share when they see the system handle failure gracefully—specifically when the verification gate *catches a bad patch or rejects an invalid syntax proposal* before committing. This separates toys from production engines.
4. **Sensory Contrast (Loud UI)**: High contrast transitions from deep warning reds to cybernetic telemetry amber to vibrant emerald success.

---

## 2. The 30-Second Dopamine Loop

Every viral video or interactive demo must follow this four-beat cadence:

### Beat 1: The Catastrophe (0:00 - 0:05)
- **Visual**: A real storefront or web app violently breaks. A red `500 Internal Server Error` banners across the screen, the cart fails, or console errors explode.
- **Audio**: Low-frequency bass thud or alarm ping.
- **Hook Text**: *"What happens when your checkout explodes at 2 AM on Black Friday with zero engineers awake?"*

### Beat 2: Autonomous Telemetry & Sentry Interception (0:05 - 0:12)
- **Visual**: Hands off keyboard. The mission control / seismograph HUD lights up. The exception is intercepted in under 20ms, displaying the exact failing stacktrace frame.
- **Telemetry**: Live counter spinning, memory footprint, trace ID.
- **Sound**: High-speed cybernetic data stream or mechanical keystroke chatter.

### Beat 3: The Frontier Model & Verification Gate (0:12 - 0:22)
- **Visual**: The AI reasoning model synthesizes a candidate patch in an isolated git worktree snapshot. The AST parser analyzes syntax. The automated test suite executes in the background.
- **Proof Moment**: Show the verification test passing (e.g., `351 tests passed in 5.5s`).
- **Sound**: Rising synthesizer tone or sonar sweep.

### Beat 4: Hot-Patching & Instant Redemption (0:22 - 0:30)
- **Visual**: The patch applies atomically. The storefront instantly re-renders or completes the checkout with a green checkmark and receipt.
- **Resolution**: *"From 500 error to production fix in 12.4 seconds. Zero human intervention."*
- **Sound**: Crisp, high-frequency harmonic resolution chime.

---

## 3. Sensory & "Loud" UI Engineering

A silent, flat UI does not hold attention on mobile feeds. Incorporate these tactical sensory layers:

### A. Tactile Web Audio Synthesis
Never rely on external `.mp3` files that fail to load or get blocked by CORS. Use the native browser `AudioContext` to synthesize tactile audio procedurally:
- **Disaster Thud**: Sine wave descending from 140Hz to 40Hz with an exponential decay envelope.
- **Terminal Keystroke / Geiger Click**: Short 5ms noise burst with a bandpass filter around 2,400Hz.
- **Verification Harmonic**: Two-tone chord (E6 1318Hz + G#6 1661Hz) with a fast exponential fade.

### B. Screen Shake & Seismic Tension
When chaos is triggered or an error strikes:
- Add a 300ms CSS shake animation (`transform: translate3d(-3px, 2px, 0)`).
- Pulse the container with a radial red gradient (`rgba(255, 77, 106, 0.15)`).

### C. Live Seismograph HUD Aesthetics
- Use high-contrast dark mode background (`#0A0B0D`).
- Neon telemetry accents:
  - Error: Electric Rose (`#FF4D6A`)
  - Reasoning / In-Progress: Cyber Cyan (`#2DD4FF`) or Amber Gold (`#F59E0B`)
  - Verified / Safe: Emerald Green (`#3DFFA2`)
- Faint SVG scanlines and pulsating SVG lines (`stroke-dasharray: 4 8; animation: linePulse 2s linear infinite`).

---

## 4. Viral Social Launch Blueprint (X / Twitter)

Structure the launch as a high-density, multi-layer thread.

### Post 1: The Visual Hook + Video (Zero Fluff)
- **Asset**: 45–60 second screen recording at 1080p, 60fps, with crisp font rendering and burned-in dynamic captions.
- **Copy**:
  ```text
  We gave Meta's reasoning model the keys to self-heal crashed production code.

  Watch what happens when an ecommerce checkout throws an unhandled exception at checkout.

  1. Exception intercepted in 18ms
  2. Isolated git worktree branched
  3. Meta Muse/Llama generates bounded patch
  4. AST & Playwright test gates verify fix
  5. Hot-reloaded in 12s. Zero downtime.

  Here is how FaultLine works (and why we reject 90% of AI patches): 🧵👇
  ```

### Post 2: The Technical Architecture & Proof
- Focus on why this is **not** a toy wrapper:
  ```text
  Most "self-healing" AI demos hallucinate or break production worse.

  FaultLine enforces 3 unbreakable safety invariants:
  - Sandboxed Git Worktrees: Zero live filesystem mutations until verified.
  - Strict AST Parsing: Patches exceeding 4KB diffs or touching unauthorized files are immediately killed.
  - Automated Regression Harness: Playwright + pytest must run 100% green before atomic commit.
  ```

### Post 3: The Live Interactive Playground
- Share a direct, zero-auth link to the web inspector with a pre-configured chaos scenario:
  ```text
  Don't take our word for it. Try breaking it yourself:

  👉 [faultline.dev/playground]

  Click "Inject Chaos", pick a crash scenario, and watch the multi-agent telemetry stream live.
  ```

### Post 4: Open Source Repository & Devpost Submission
- Link to GitHub repo with documentation, `make check` instructions, and hackathon submission badge.

---

## 5. Hacker News ("Show HN") Playbook

Hacker News values technical honesty, architecture breakdowns, and direct discussion of trade-offs:
- **Title Format**: `Show HN: FaultLine – Autonomous self-healing code using Meta reasoning models and sandboxed git worktrees`
- **First Comment**:
  - State clearly that you are the author.
  - Detail why you built it (the firsthand problem: checkout crashes cost e-commerce businesses $120k/hr).
  - Explain the threat model (unbounded LLM code generation is dangerous; how sandboxed AST verification prevents hallucination).
  - Open-source instructions to run locally (`make check`, `scripts/start-demo.sh`).

---

## 6. Pre-Flight Virality Checklist

Before hitting record or publishing a demo video:

- [ ] **First 3 Seconds**: Is there visible action or catastrophe in the first 3 seconds? (No title slides, no talking heads).
- [ ] **Contrast**: Is the transition from broken (red) to fixed (green) dramatic and unmistakable?
- [ ] **Pacing**: Is all dead air cut? (Speed up API wait times or terminal output by 1.5x–2x if longer than 3 seconds).
- [ ] **Sensory Feedback**: Are audio clicks, chimes, and seismograph telemetry audible and tactile?
- [ ] **Proof of Work**: Is the test verification gate visible on screen?
- [ ] **Call to Action**: Is there a clear, frictionless link for the viewer to test the app or read the source?
