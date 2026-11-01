# FaultLine: Viral Launch Kit & Distribution Playbook
**Targeting Meta Hackathon Bonuses: $20,000 Most Viral Project on X & $10,000 Community Vote**

This operational playbook provides ready-to-publish assets, timing sheets, and algorithm-engineered strategies for **X (Twitter)**, **LinkedIn**, and **Hacker News**.

> [!IMPORTANT]
> **Key Hackathon Deadlines (US Eastern Time):**
> - **Main Devpost Submission:** Wednesday, November 4, 2026 @ 9:00 PM ET
> - **Most Viral Project on X Engagement Window Closes:** Sunday, November 8, 2026 @ 11:59 PM ET
> - **Community Vote Gallery Voting Closes:** Monday, November 16, 2026

---

## 1. Algorithm Mechanics & Strategy

### A. The X (Twitter) Algorithm Blueprint
Based on the open-source X algorithm ranking weights (`twitter/the-algorithm`):

| Signal | Relative Weight | What It Means for Launch Day |
| :--- | :---: | :--- |
| **`reply_engaged_by_author`** | **+75.0 (150x a like)** | **The Golden Rule:** When someone replies, reply back immediately. The author reply re-surfaces the post to the replier's network. |
| **`reply`** | **+13.5 (27x a like)** | Prompt technical debate ("What assertion would you add?"), not generic "Thoughts?". |
| **`good_profile_click`** | **+12.0 (24x a like)** | Pinned thread and profile bio must convert viewers to GitHub and Devpost. |
| **`good_click_v2` (dwell >2 min)** | **+10.0 (20x a like)** | A substantial thread with code diffs, logs, and architecture keeps users dwelling. |
| **`negative_feedback_v2`** | **-74.0 (-148x a like)** | Never tag strangers or spam hashtags. One "Show less" cancels ~150 likes. |

#### Core Rules for X:
1. **Never Put External Links in the Root Post:** X sharply discounts posts containing external URLs. Put the video and hook in the root post; post the GitHub repo, judge page, and Devpost link in **Reply 1** within 30 seconds.
2. **The 3-Second Hook:** Frame 1 opens with the red HTTP 500 error banner. Zero intros, zero logos, zero talking heads.
3. **Burned-In Captions:** 85% of feed views are muted. All videos carry burned-in high-contrast captions with gold accent bars.
4. **The 15-Minute Author Sprint:** Clear your calendar for the first 30 minutes after posting. Reply to every comment within 15 minutes to trigger the `+75` algorithmic compounding.

---

### B. The LinkedIn Algorithm Blueprint
On LinkedIn, **PDF Document Carousels** dramatically outperform video and single images in dwell time, saves, and DM shares:
- Carousels get swipe interactions that continuously send positive dwell telemetry to LinkedIn's feed ranker.
- Post tone must be **"builder-to-builder post-mortem"**—sharing real engineering decisions, kernel sandbox configurations, and failure modes rather than promotional hype.
- Link goes in the **First Comment** or at the end of the post after the "see more" fold.

---

## 2. Ready-to-Publish Copy & Asset Matrix

### Asset 1: The 45-Second Viral Hero Video (X Root Launch)
- **Video File:** `data/footage/20261101-193931/viral-hero-cut.mp4` *(45 seconds, 1080p, burned-in captions)*
- **Beat Timing:**
  - `0:00–0:06`: BuggyShop checkout HTTP 500 error on empty coupon.
  - `0:06–0:16`: Pre-Flight CLI Gate catches defect, exits 1 (`DEPLOYMENT_BLOCKED`), generates fix prompt.
  - `0:16–0:30`: Meta `muse-spark-1.3` single-line repair diff + Bubblewrap sandbox 44/44 assertions turning emerald green.
  - `0:30–0:41`: Gate Explorer showing 5 of 6 wrong patches rejected by FaultLine while passing naive 201 check.
  - `0:41–0:45`: Fast call to action end card.

#### Root Post Copy (attach `viral-hero-cut.mp4`):
```text
Leave the coupon field empty and this checkout crashes with an HTTP 500.

Meta's muse-spark model synthesized the fix in 6.9s.

But that's not the interesting part.

The interesting part is the 44 independent verification gates it had to pass before we trusted it. 🧵
```

#### Reply 1 (post immediately at minute 0:01 with links):
```text
Try the interactive replays and inspect the evidence yourself:

💻 Code: https://github.com/FrankieBiz/Faultline
🔍 Interactive Judge Page: https://frankiebiz.github.io/Faultline/
⚡ Retained Meta Run (real timing): https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/

Built for the Meta Global AI Developer Hackathon with @AIatMeta and @cerebral_valley
```

#### Post 2: The 5-of-6 Rejection Trap (attach gate comparison screenshot):
```text
Why we don't trust "HTTP 201 Created":

We authored 6 plausible-but-wrong patches for this bug. One returned 201 but silently dropped the order.

A naive status-code test accepted 5 of the 6 wrong patches.

FaultLine's independent oracles rejected all 6, and verified the real fix.

A green status code is not an oracle.
```

#### Post 3: The Pre-Flight Gate CLI:
```text
Before any model touches code, our cross-platform Pre-Flight Gate intercepts broken deploys:

Run: ./faultline gate http://127.0.0.1:3000

Playwright autonomously explores 30 interactive elements, catches the checkout failure, exits 1 (DEPLOYMENT_BLOCKED), and outputs the exact remediation prompt for coding agents.
```

#### Post 4: The Linux Kernel Sandbox:
```text
Candidate code is untrusted. It executes inside Linux Bubblewrap namespaces:

bwrap --unshare-all --cap-drop ALL --clearenv

Strict aggregate cgroup v2 limits: 512 MiB RAM, 0 swap, 64 tasks, 1 CPU quota.

We read the limits directly from /sys/fs/cgroup and verify them with adversarial OOM-kill probes before execution.
```

#### Post 5: Honest Scope & Verified Numbers:
```text
What's verified today:
• 3/3 Meta trials verified on attempt 1 (10.5s median wall time)
• 44/44 independent business assertions passing
• 1,290 automated tests passing locally (`make check`)
• SHA-256 checksummed offline evidence bundle

One seeded checkout defect. Real infrastructure, zero simulated receipts.
```

#### Post 6: The Technical Question (Algorithmic Driver):
```text
If you build autonomous AI coding agents: what's the hardest verification check you've had to enforce?

Drop your toughest edge case below—we're turning the best replies into new test fixtures.

Vote for FaultLine in the community gallery: [DEVPOST_LINK]
```

---

### Asset 2: The 25-Second "Anti-Vaporware Rejection Flex" (X Follow-Up / Day 2)
- **Video File:** `data/footage/20261101-193931/rejection-flex-cut.mp4` *(25 seconds, fast cuts, high contrast)*
- **Core Message:** "Anyone can get an AI model to write a patch. The hard part is knowing when the patch is wrong."
- **Visuals:** Shows the 3 classic developer traps (`early_return_unsaved`, `zero_all_discounts`, `null_coupon_only`) getting accepted by standard tests and immediately blocked by FaultLine.

#### Post Copy (Quote-post your original launch thread):
```text
Anyone can get an LLM to generate a code patch.

The hard part is knowing when the model is lying to you.

Watch 3 "plausible" patches that pass standard test suites get caught red-handed by independent business oracles:
```

---

### Asset 3: The 10-Slide LinkedIn Developer Carousel (PDF)
- **File:** `data/social/linkedin-carousel/FaultLine-Architecture-Carousel.pdf`
- **Format:** 1080x1350 (4:5 vertical document, swipeable on mobile)

#### Slide Outline:
- **Slide 1 (Hook):** "We let an AI model patch our code. But only after passing 44 independent gates."
- **Slide 2 (The Trap):** "Why AI coding agents break apps in production: surface green, hollow core."
- **Slide 3 (The 5-of-6 Table):** "The Experiment: 6 plausible wrong repairs. Naive tests accepted 5. FaultLine rejected all 6."
- **Slide 4 (Pre-Flight CLI):** "`faultline gate`: Autonomous browser exploration before git push."
- **Slide 5 (Prompt Containment):** "Evidence-only prompt boundary: the model sees the contract, never the fix."
- **Slide 6 (Kernel Sandbox):** "Linux Bubblewrap + cgroup v2: 512 MB, 64 PIDs, verified via `/sys/fs/cgroup`."
- **Slide 7 (Business Oracles):** "44 assertions verifying exact transaction, discount, and inventory state."
- **Slide 8 (Evidence Receipts):** "SHA-256 signed evidence bundle for auditability."
- **Slide 9 (The Ledger):** "Verified results: 3/3 Meta trials, 10.5s median, 1,290 tests passing."
- **Slide 10 (Try It):** "Inspect the code, replays, and documentation: github.com/FrankieBiz/Faultline"

#### LinkedIn Post Copy (attach PDF document):
```text
Most AI coding demos show a model writing code, a UI turning green on a timer, and everyone clapping.

Then you look at the code:
• It caught `except Exception:` and swallowed the crash.
• Or it returned HTTP 201 Created but forgot to save the order to the database.

For our entry in Meta's Global AI Developer Hackathon, we built FaultLine: an autonomous immune system for web applications.

Here is the architecture we built to let Meta's models patch code without trusting them:

1. Pre-Flight CLI Gate: Headless Playwright explores 30 interactive elements across user journeys. If an endpoint throws 500, it exits 1 (DEPLOYMENT_BLOCKED).
2. Prompt Containment: The model receives the business contract and the failure trace—never the bug or the fix.
3. Linux Kernel Sandboxing: Candidates run inside Bubblewrap namespaces under aggregate cgroup v2 limits (512 MiB RAM, 1 CPU quota, 0 swap), verified directly with kernel OOM-kill probes.
4. Independent Oracles: 44 assertions verify the real business contract. In our benchmarks, a naive status check accepted 5 of 6 wrong patches. FaultLine rejected all 6.
5. Offline Proof Bundle: Every verified fix generates a SHA-256 checksummed evidence receipt.

Swipe through the carousel below for the complete architecture and verification data.

All code and live interactive replays are open source:
Links in the first comment below! 👇
```

#### LinkedIn First Comment (post immediately):
```text
Explore the project:
• Source code on GitHub: https://github.com/FrankieBiz/Faultline
• Live Interactive Judge Page: https://frankiebiz.github.io/Faultline/
• Verified Meta Replay: https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/
• Devpost Submission: [DEVPOST_LINK]

Built with Meta Model API (muse-spark-1.3). Huge thanks to @AI at Meta and @Cerebral Valley for hosting!
```

---

### Asset 4: Hacker News ("Show HN")
Hacker News requires technical humility, exact facts, and zero marketing language.

#### Title:
`Show HN: FaultLine – browser-reproduced bugs, model patches, verified in a Linux sandbox`

#### Author First Comment:
```text
Hey HN,

I built FaultLine for Meta's Global AI Developer Hackathon.

As autonomous coding agents increasingly build software, they often make quick patches that silence errors on the surface while silently breaking core business logic.

We tested this directly: we authored 6 plausible-but-wrong repairs for a checkout defect. A standard test checking for "HTTP 201 Created" accepted 5 of the 6 wrong repairs (including one that returned 201 but dropped the order without saving it to disk).

FaultLine approaches autonomous repair as an adversarial verification problem:
1. Browser reproduction: Headless Chromium must reproduce the unhandled exception across two fresh sessions before any model is invoked.
2. Prompt containment: The model receives the JSON-encoded business contract and reproduction trace—it never sees the bug or the fix.
3. AST & policy validation: Static analysis rejects catch-all `except Exception:`, dynamic `exec`, bare imports, and malformed hunks before execution.
4. Kernel sandbox: Candidate patches execute inside Linux Bubblewrap namespaces under aggregate cgroup v2 limits (512 MB memory, 0 swap, 64 PIDs, 1 CPU quota). We read the limits directly from /sys/fs/cgroup and verify them with adversarial probes.
5. Independent business oracles: 44 assertions verify database state, pricing math, coupon rules, and inventory integrity. It rejected all 6 wrong patches and verified the true fix.

Repository: https://github.com/FrankieBiz/Faultline
Interactive judge page & replays: https://frankiebiz.github.io/Faultline/

Everything is reproducible locally with `make setup` and `make check` (1,290 passing tests). Would appreciate feedback on which business assertions or kernel limits you'd harden.
```

---

## 3. Hour-by-Hour Launch Execution Timeline

| Day & Time (ET) | Platform | Action | Success Metrics |
| :--- | :--- | :--- | :--- |
| **Wed, Nov 4 · 9:00 PM** | **Devpost** | **Submit FaultLine.** Embed hero video, link GitHub repo and Judge Page. | Submission confirmed. |
| **Thu, Nov 5 · 8:30 AM** | **X (Twitter)** | **Publish X-1 Launch Thread with 45s Hero Video.** No links in root post. | Launch window begins. |
| **Thu, Nov 5 · 8:31 AM** | **X (Twitter)** | **Post Reply 1 with links.** Tag `@AIatMeta` and `@cerebral_valley`. Pin thread. | Thread pinned. |
| **Thu, Nov 5 · 8:31–9:00 AM** | **X (Twitter)** | **The 15-Minute Reply Loop:** Answer every reply inside 15 minutes to trigger the +75x ranking multiplier. | 20+ author replies logged. |
| **Thu, Nov 5 · 12:00 PM** | **LinkedIn** | **Publish 10-Slide PDF Carousel.** Post link in comment #1. | Dwell time & saves spike. |
| **Thu, Nov 5 · 2:00 PM** | **Hacker News** | **Submit "Show HN"** with the author first comment. | Front page of /newest. |
| **Fri, Nov 6 · 10:00 AM** | **X (Twitter)** | **Post 25s "Rejection Flex" Video.** Quote the pinned launch thread. | Revives thread velocity. |
| **Sat, Nov 7 · 11:00 AM** | **X (Twitter)** | **Deep Architecture Breakdown Thread.** Highlight Bubblewrap & cgroup v2. | Technical bookmarks. |
| **Sun, Nov 8 · 6:00 PM** | **X (Twitter)** | **Final Viral Push before 11:59 PM ET deadline.** | Maximum demo engagement. |
| **Nov 9–16** | **All Channels** | **Community Vote Campaign:** Drive unique verified accounts to public gallery. | Maximize gallery votes. |
