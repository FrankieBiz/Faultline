---
name: virality
description: "Operational playbook for engineering developer virality on X (Twitter) and LinkedIn, plus Hacker News, demo videos, and hackathon bonus prizes (Most Viral Project on X, Community Vote). Covers ranking-algorithm mechanics, the 30-60 second demo loop, launch timing, reply loops, carousels, and copy-paste post templates. Trigger when the user mentions 'viral', 'virality', 'go viral', 'launch video', 'demo video script', 'make it louder', 'social launch', 'Twitter thread', 'X post', 'LinkedIn post', 'carousel', 'Hacker News launch', 'Show HN', 'community vote', 'visual dopamine', or 'judge impact'."
---

# DevTool & AI Agent Virality Playbook

An operating manual for turning a technical developer tool into something engineers stop scrolling for, share, and vote on. It covers X, LinkedIn, Hacker News, demo video, and hackathon bonus prizes.

The playbook is compact on purpose. The depth lives in four references. Load the one that matches the task:

| Task | Load |
| --- | --- |
| Why a post does or does not travel on X; video, threads, reply loops | [`references/x-algorithm-mechanics.md`](references/x-algorithm-mechanics.md) |
| LinkedIn ranking, dwell, saves/sends, carousels, link handling, tone rules | [`references/linkedin-algorithm-mechanics.md`](references/linkedin-algorithm-mechanics.md) |
| Hackathon launch: Most Viral on X, Community Vote, demo loop, tagging, Devpost | [`references/hackathon-launch-playbook.md`](references/hackathon-launch-playbook.md) |
| Writing the actual posts | [`references/templates-and-copy.md`](references/templates-and-copy.md) |

---

## 0. Evidence rules (read first, never skip)

Credibility is the whole growth engine for a developer audience. One debunked number in the replies erases a week of reach.

### FaultLine evidence requirements

Read `docs/QUALITY_REVIEW.md`, `docs/PROJECT_STATUS.md`, `docs/LAUNCH.md`, and `docs/VIDEO_STORYBOARD.md` before applying this playbook. Templates in the references are narrative scaffolds, not verified FaultLine capabilities or measurements. Do not reuse latency, savings, rejection-rate, production hot-patching, integration, or uptime claims without matching evidence. Green UI and exported reports must depend on actual job results and cleanup. Authored previews must remain labeled. Missing-key deterministic runs are not Meta trials. Do not invent sensory telemetry, receipt IDs, or progress timers to make a demonstration look faster. No social publishing is authorized merely by using this skill: every post, DM, tag, and submission is drafted for the owner, who sends it.

### Rules for any project

1. **Every number links to a record.** If you cannot point to the file, run, or commit, cut the number.
2. **Name the model that produced the result.** Only say "Meta", "Muse Spark", or "Llama" when the run record names that provider and model.
3. **Label recordings as recordings.** "Retained replay of a real run" beats "live" when it is not live.
4. **State scope in the same breath as the win.** "One seeded checkout defect" makes the claim survive a hostile quote-post.
5. **Disclose edits.** Cuts and speed-ups are fine if the caption says so and the original duration is kept.

### Verified FaultLine facts safe to quote (re-check before each use)

Source: `README.md` and `docs/DEVPOST_SUBMISSION.md` as of 2026-10-31.

- A retained `muse-spark-1.3` job repaired the seeded checkout `TypeError`. The model returned a one-line patch in 6.9 s. The candidate passed 44 of 44 assertions, cleanup succeeded, and the whole job took 13.0 s. A public replay is linked from the judge page.
- Controller ledger: 3 of 3 Meta trials verified on the first attempt, median wall time 10.5 s, one registered scenario.
- Six plausible but wrong repairs were tested. A "returns HTTP 201" check accepted five. FaultLine accepted none, and it accepted both correct repairs.
- A second retained Meta job shows a rejected first proposal and a verified second-round retry.
- Gates: two identical browser reproductions, AST and patch policy (no catch-all `except`, import allowlist, size limits), a Bubblewrap sandbox with cgroup v2 limits read back before execution, 27 independent HTTP business assertions, and a checksummed evidence bundle.
- **Not yet true, do not imply it:** a Meta run over the 10-defect corpus, production deployment, arbitrary-application repair, or certified security.

---

## 1. The psychology of developer virality

Developers are the most skeptical feed on the internet. They have seen hundreds of scripted AI wrappers. Feature tours, slides, and pitch-speak get near-zero organic reach.

**What actually earns shares, bookmarks, and votes:**

1. **Visceral pain, then catharsis.** Open on a universal nightmare: a 500 at checkout, a 2 AM page, a broken deploy. Resolve it on screen.
2. **Velocity you can see.** Catastrophe to verified fix in one continuous take, with a real clock.
3. **Anti-vaporware proof.** People share when the system *refuses* something. Showing a gate rejecting a bad patch is what separates an engine from a wrapper. This is FaultLine's sharpest asset (see the hackathon playbook, section 3).
4. **Inspectability.** "Here is the diff, the trace, and the checksum. Check it yourself" invites the expert reply that the algorithm rewards most.
5. **Sensory contrast.** Red failure, amber reasoning, green verified. These must be readable on a muted phone screen at 1x speed.

---

## 2. The 30-60 second dopamine loop (summary)

Four beats. Full shot list, captions, and timing are in [`references/hackathon-launch-playbook.md`](references/hackathon-launch-playbook.md#2-the-30-60-second-dopamine-loop).

| Beat | Window | What the viewer must see |
| --- | --- | --- |
| 1. Catastrophe | 0-3 s hook, to ~8 s | The checkout fails with a real HTTP 500. No title card. |
| 2. Interception | ~8-15 s | Failure reproduced twice in fresh browser sessions, with the stack frame named |
| 3. Reasoning + gates | ~15-40 s | Model diff appears, then AST/policy gate, sandbox, 27 assertions turning green (or a visible rejection) |
| 4. Redemption | ~40-60 s | Store re-checked live and passing, evidence bundle, source link card |

---

## 3. Sensory and "loud" UI engineering

A silent, flat UI does not hold attention on mobile feeds. Apply these only to real state transitions. Never use them to fake progress.

### A. Tactile Web Audio synthesis

Synthesize with `AudioContext` rather than shipping `.mp3` files. Create the context only after a user gesture, and drop cues that cannot play on time (FaultLine's Inspector already does this).

- **Disaster thud.** Sine wave from 140 Hz down to 40 Hz with exponential decay.
- **Keystroke / Geiger click.** 5 ms noise burst, bandpass around 2,400 Hz.
- **Verification harmonic.** E6 (1318 Hz) and G#6 (1661 Hz) together, fast exponential fade.

Most feed viewers watch muted, so audio is a bonus layer. Captions carry the story.

### B. Screen shake and seismic tension

- A 300 ms shake (`transform: translate3d(-3px, 2px, 0)`), composite-only, disabled under `prefers-reduced-motion`.
- A radial red pulse (`rgba(255, 77, 106, 0.15)`) on the failing container.

### C. Seismograph HUD palette

- Background `#0A0B0D`. Error: Electric Rose `#FF4D6A`. In progress: Cyber Cyan `#2DD4FF` or Amber `#F59E0B`. Verified: Emerald `#3DFFA2`.
- Faint scanlines. Pulsing dashed SVG strokes (`stroke-dasharray: 4 8`).

---

## 4. Channel strategy at a glance

| | X | LinkedIn | Hacker News |
| --- | --- | --- | --- |
| Audience | Builders, AI researchers, Meta/organizer accounts | Engineering managers, recruiters, founders, judges' networks | Skeptical senior engineers |
| Winning format | Native video root post + thread | PDF carousel or post-mortem text, native video second | Plain "Show HN" + honest author comment |
| Top signal | Replies the author answers (2023 open-source weight 75) | Saves, DM sends, and long comments; dwell after "see more" | Substantive comments, upvote velocity |
| Golden window | First ~30 min | First ~60-90 min | First ~60 min on /newest |
| Links | Never in the root post; put them in a reply | First comment, or make the post consumable without one | The link is the post |
| Tone | Sharp, specific, a little combative | Builder-to-builder, lessons, no PR voice | Dry, technical, show the limits |

Mechanics: [`x-algorithm-mechanics.md`](references/x-algorithm-mechanics.md), [`linkedin-algorithm-mechanics.md`](references/linkedin-algorithm-mechanics.md).

---

## 5. Hacker News ("Show HN") playbook

HN rewards technical honesty and punishes marketing.

- **Title.** `Show HN: FaultLine – browser-reproduced bugs, model patches, verified in a Bubblewrap sandbox`. No superlatives, and nothing that implies deployment.
- **Post a first comment immediately**, as the author:
  - Why you built it: a firsthand problem the owner has confirmed. Never use a borrowed industry statistic.
  - Scope: one seeded checkout defect, a 10-defect authored corpus, and what is still unmeasured (Meta on the full corpus).
  - Threat model: model output is untrusted. Cover the AST policy, the sandbox, cgroup limits read back from `/sys/fs/cgroup`, and why "returns 201" is a bad oracle (the 5-of-6 result).
  - How to run it: `make setup`, `./faultline doctor`, `./scripts/start-demo.sh`.
  - Invite attack: "Tell us which assertion is too weak."
- **Timing.** Weekday, around 8-10 AM US Eastern. Stay in the thread for the first two hours. Never ask for upvotes; HN penalizes voting rings.

---

## 6. Launch calendar (FaultLine, Meta AI Developer Hackathon)

Deadlines come from `docs/HACKATHON_BRIEF.md`. Confirm them on official channels before acting.

| When | Action |
| --- | --- |
| Now to Nov 3 | Record the hero video (storyboard + `scripts/record-footage.sh`), cut 30-60 s and 2-3 min versions, design the carousel |
| Nov 4, before 9:00 PM ET | Devpost submission due. Link the video, judge page, and repo. |
| Nov 4-5 | X launch thread (Tue-Thu morning ET), LinkedIn carousel the same day, 3-4 hours later |
| Nov 5-8 | Daily follow-ups on X: rejection clip, architecture breakdown, playground challenge, reply-guy sessions |
| **Nov 8, 11:59 PM ET** | **Most Viral Project on X engagement window closes** |
| Until Nov 16 | Community Vote push: gallery link in profile, Discord, LinkedIn follow-up, builder-journey post |

Full schedule with hour-by-hour launch-day timing: [`hackathon-launch-playbook.md`](references/hackathon-launch-playbook.md#5-timing).

---

## 7. Pre-flight checklist (before any post goes out)

**Evidence**
- [ ] Every number traces to a file or run record linked in the repo.
- [ ] The model and provider are named exactly as the run record names them. A deterministic fallback is labeled as such.
- [ ] Replays are captioned "recorded", and cuts or speed-ups are disclosed.

**Video**
- [ ] Visible failure in the first 3 seconds. No logo or title slide.
- [ ] Burned-in captions, readable on a phone, with the key text above the bottom 20% of the frame.
- [ ] The gate (pass *or* rejection) is on screen long enough to read.
- [ ] Native upload, 1080p+, 30-60 s for the root post.

**Post**
- [ ] No external link in the X root post or LinkedIn body (put links in a reply or first comment).
- [ ] The hook works with zero context and lands before LinkedIn's "see more" cut.
- [ ] Passes the anti-slop rules in the LinkedIn reference: no "Agree?", no "game-changer", no emoji bullet walls.
- [ ] Handles and tags verified on the live platform the same day.

**Operations**
- [ ] The author is free to reply for the first 30 min (X) or 90 min (LinkedIn) after posting.
- [ ] The Devpost, gallery, judge page, and repo links all resolve in an incognito window.
- [ ] The owner has approved the final copy. This skill never posts.
