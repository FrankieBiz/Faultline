# Hackathon launch playbook: Meta AI Developer Hackathon

How to compete for the **$20,000 Most Viral Project** bonus (demo engagement on X) and the **$10,000 Community Vote** bonus (public gallery) with FaultLine, without spending the credibility that the main judging depends on.

> **Terms source:** `docs/HACKATHON_BRIEF.md` (webinar bonus-prize slide, 2026-10-26). Most Viral counts demo engagement on X **through Nov 8, 11:59 PM ET**. Community Vote is decided by the most votes in the public gallery, **one vote per verified account**, with the winner announced **Nov 16**. Main submissions are due **Nov 4, 9:00 PM ET**. Re-confirm all terms in Discord `#announcements` before acting.

---

## 1. Strategy in one screen

| Prize | What wins it | Our lever |
| --- | --- | --- |
| Most Viral on X | Engagement on the demo post(s) on X during the window | One killer native video, with the reply loop worked hard (75x weight), daily follow-ups that extend the original thread, and amplification from the builder community |
| Community Vote | Unique verified voters in the gallery | Converting attention from X, LinkedIn, and Discord into gallery visits, plus a gallery entry that converts in 5 seconds |
| Main judging (context) | Rubric in `.agents/skills/hackathon-judge/references/meta_rubric.md` | Every viral claim must survive a judge clicking through to evidence. Virality that judges can debunk costs the main prize. |

**Principle:** one hero asset, many entry points. The 30-60 s video is the root of everything. Every other post points back to the same pinned X thread (where the engagement must accumulate) and the gallery page (where the votes must land).

---

## 2. The 30-60 second dopamine loop

The video follows four beats: **Catastrophe → Interception → Reasoning and verification gate → Hot-patch and redemption.** Each beat uses real footage. `scripts/record-footage.sh` captures clips 01-05, and `scripts/assemble-footage.sh` builds a captioned rough cut (see `docs/VIDEO_STORYBOARD.md`).

| Beat | Time | Picture (real footage) | Burned-in caption | Sound (optional) |
| --- | --- | --- | --- | --- |
| **1. Catastrophe** | 0:00-0:08 | Clip 01: two Trail Mugs, empty coupon, **Place order**, then the red "Checkout failed" banner with the HTTP 500 `TypeError`. Frame 1 already shows the cart. | "Leave the coupon empty → checkout crashes." | Low thud on the 500 |
| **2. Interception** | 0:08-0:15 | Headless Chromium reproduces the failure in two fresh sessions, with the failing frame in the allowlisted file highlighted | "Reproduced twice in a real browser before any AI is called." | Geiger clicks per session |
| **3. Reasoning + gate** | 0:15-0:40 | Clip 02 (retained Meta replay at real 13.0 s timing): `muse-spark-1.3` returns a one-line diff, then the AST/policy gate passes, then the Bubblewrap sandbox, then assertion counters climb to **44/44** | "Meta's model writes a one-line patch. It's untrusted until it passes every gate." | Rising tone while assertions climb |
| **4. Redemption** | 0:40-0:55 | Inspector **Apply fix**: the demo store is hot-patched, the live re-check shows HTTP 201, then the evidence bundle and cleanup ✓ | "Verified. Patched. Every step has a receipt." | Two-tone chime on green |
| End card | 0:55-1:00 | Repo + judge page, "Recorded run: job 3573b32b" | "Try to break it → link below" | none |

**Mandatory labels.** Caption the replay as "recorded Meta run, Oct 28, real timing". "Hot-patching" here means the local demo store, not production. If you show the deterministic fallback, caption it as such and do not call it Meta.

**Cut rules.** No dead frames over 1.5 s. Every 2-3 s something new appears on screen. Any speed-up is disclosed in the caption ("2x") with the original duration kept. Zoom into the diff and the assertion counter, because UI-wide shots are unreadable on phones.

---

## 3. Why developers hate AI wrappers, and why FaultLine is different

### The wrapper fatigue

Developer timelines are saturated with demos where a model emits code, the UI turns green on a timer, and nothing proves the code is right. Senior engineers reply with "so it's a prompt", "what happens when it's wrong?", and "show me the tests". Those replies kill reach for wrappers.

### FaultLine's asymmetric advantage: the system says no

**The most shareable moment in FaultLine is a rejection.** Proof that the gate catches a bad patch before it reaches the code is what turns skeptics into amplifiers. Assets that show it, all evidence-backed:

| Asset | What it proves | Caption requirement |
| --- | --- | --- |
| "Return 201" vs FaultLine table (`docs/EVALUATION.md`) | 6 plausible but wrong repairs: the naive check accepted 5, FaultLine accepted 0, and both correct repairs passed | "Authored wrong patches" (they were written as tests, not by Meta) |
| Clip 03 gate explorer (`zero_all_discounts`, `null_coupon_only`, `early_return_unsaved`) | Specific wrong fixes that look right and the exact assertion that catches each | "Recorded evaluation results, deterministic and DeepSeek corpus runs, not Meta" |
| DeepSeek corpus run | 18 of 20 verified, and the gates rejected the wrong patches in the other 2 | Name DeepSeek `deepseek-v4-pro` |
| AST policy rejection (e.g. a patch adding `except Exception:` to swallow the error) | The gate refuses to "fix" a crash by hiding it | If authored, say so. Only call it model-generated if the attempt record shows that. |
| Replay `82ac2dcc` | First proposal refused, feedback sent to the model, verified retry | Honest framing: it was *our tooling* that refused a correct patch (zero-context hunk), and it is now fixed. This is a great post-mortem story, not a "caught a bad AI patch" story. |

**The narrative hook:** *"Anyone can get a model to write a patch. The hard part is knowing when the patch is wrong."* Lead with the 5-of-6 result, then show the gate. This is the post skeptics bookmark.

---

## 4. Tagging and cross-linking

### X handles *(verify each on the live profile the day you post)*

| Who | Handle to verify | Where to tag |
| --- | --- | --- |
| Meta AI | `@AIatMeta` | Root post or first reply, once |
| Meta corporate | `@Meta` | Optional, root post |
| Cerebral Valley (organizer) | `@cerebral_valley` | Root post |
| Event hashtag | Check `#announcements` for an official one | At most one, if the organizers use one |
| Teammates | Personal handles | Thread post 2+, or replies |

**Rules:** at most 3 tags in the root post. Never tag judges or individual Meta employees you haven't interacted with. Tags in replies or quote posts are cheaper and still surface to those accounts. Too many tags in the root post read as spam and draw mutes (-74 weight).

### Cross-linking map

```
             ┌──────────── Pinned X launch thread (engagement must accrue HERE) ────────────┐
             │  root: native video, no links → reply 1: repo + judge page + gallery        │
             └──────────────▲──────────────────────────────▲─────────────────────────────────┘
                            │ quote/link                    │ quote/link
   LinkedIn carousel ───────┤                               ├────── Daily X follow-ups (self-replies)
   (link in 1st comment)    │                               │
                            ▼                               ▼
                  Devpost / gallery page  ◄────────  Judge page (frankiebiz.github.io/Faultline)
                  (votes land HERE)                  (evidence, replays, "Break it yourself")
                            ▲
                            └──── GitHub README badge + link, Discord #showcase-style channels
```

- **Devpost / gallery entry:** embed the same hero video, and link the X thread and judge page.
- **GitHub README:** add a "Vote for FaultLine" link to the gallery during the vote window, and remove it afterwards.
- **Judge page:** link back to the X thread ("Discussion on X") so replies stay in one place.
- **LinkedIn:** link the X thread *and* the gallery in the first comment.

### Community Vote conversion

- One vote per verified account means **unique people** matter, not repeated actions. Every channel post ends with one clear ask and one link: the gallery.
- Gallery entry: the first sentence is the hook, the thumbnail is the red-to-green frame, and the video sits at the top.
- Ask your real networks directly and personally (classmates, coworkers, open-source contacts) with a one-line why. Personal asks convert far better than broadcasts.
- **Never** buy votes, use multiple accounts, or trade votes in bulk. It is disqualifying, and the community notices.

---

## 5. Timing

All times are Eastern. Confirm deadlines in Discord.

### Pre-launch (now to Nov 3)

- Record footage. Cut a 30-60 s hero, a 15 s teaser, a 2-3 min Devpost version, and a separate rejection clip.
- Build the 10-page LinkedIn carousel ([`templates-and-copy.md`](templates-and-copy.md#linkedin-2-architecture-carousel-copy-10-pages)).
- Update the X bio, header, and website field (see [`x-algorithm-mechanics.md`](x-algorithm-mechanics.md#7-profile-click-conversion-12)) and the LinkedIn headline.
- Line up 5-10 people who will ask real questions in the first 15 minutes.
- Owner reviews and approves all copy.

### Launch day (Tue-Thu after the Nov 4 submission; Nov 5 is ideal)

| Time (ET) | Action |
| --- | --- |
| 8:30 AM | X root post (native video, no links) |
| 8:31 AM | Reply 1: repo, judge page, Devpost/gallery. Then thread posts 2-6. Pin the thread. |
| 8:31-8:45 | Answer every reply, the first 20 within 15 minutes |
| 8:45-10:00 | Keep the reply loop going. Quote the thread in Discord. |
| 12:00 PM | LinkedIn carousel post. Links in the first comment. |
| 12:00-1:30 | LinkedIn golden window: answer every comment |
| Evening | Reply-to-self on the X thread with one new detail (a gate stat or a short clip) |

### Days 2-4 (Nov 6-8): keep the original thread alive

- **Nov 6:** rejection clip ("5 of 6 wrong patches passed the obvious test"). Post it as a reply to the pinned thread *and* as a standalone post that quotes the thread.
- **Nov 7:** architecture breakdown thread (template X-2). Quote the launch thread.
- **Nov 8:** playground challenge (template X-3). Last push before **11:59 PM ET**.
- Each day: 30 minutes of "reply-guy" work, giving genuine, useful replies to big AI and devtools accounts posting about AI code agents. These earn profile clicks (+12). Do not link-drop.

### Nov 9-16: Community Vote push

- Nov 9 (closing ceremony): "what we learned" post on X and the LinkedIn builder-journey post (template LI-3), both ending with the gallery link.
- Mid-week: a personal-ask round, plus a reminder in Discord and the README.
- Nov 15: one final "last day to vote" post, only if the gallery is still open. Check the rules.

---

## 6. Measurement

Track daily in a scratch note (never commit engagement numbers as product evidence):

- X: impressions, engagement rate, replies, author replies, bookmarks, profile clicks, video completion (Media Studio)
- LinkedIn: impressions, "see more" clicks (shown as dwell in analytics), saves, sends, comments, carousel completion
- Gallery: vote count, if visible, and referral sources

If a day-2 post beats the launch post on engagement rate, double down on that angle. Typically it will be the rejection or "wrong patch" angle.

---

## 7. Hard lines

- No bots, purchased engagement, sock-puppet accounts, or vote trading.
- No claims beyond the evidence in SKILL.md section 0. No production, uptime, or savings claims.
- Name the model and provider exactly as recorded. Never call a deterministic or DeepSeek result "Meta".
- The owner posts. This skill drafts.
