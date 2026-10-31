# LinkedIn algorithm mechanics for engineering posts

How LinkedIn's feed decides who sees a post, and how to write engineering content that earns saves, sends, and deep comments without sounding like a press release.

> **Provenance.** "360Brew" comes from LinkedIn's published research ("360Brew: A Decoder-only Foundation Model for Personalized Ranking and Recommendation", 2025). LinkedIn engineering posts and product leads have confirmed the broad direction: dwell, meaningful comments, and saves and sends matter more than reactions. Exact weights are **not public**. Items marked *heuristic* are practitioner consensus from creator analytics.

---

## 1. 360Brew: what changed and why it matters

LinkedIn has been consolidating many task-specific, ID-feature ranking models into one large decoder-only foundation model (the research paper describes about 150B parameters). It ranks by reading **text**: the post's text, the viewer's profile and history, and the author's profile, all expressed in natural language.

Implications:

1. **Topical authority is read, not inferred from hashtags.** The model compares what the post is about with what the author's profile says they do. An engineer posting about sandboxing and verification gets distributed to people interested in those topics. A sudden pivot into motivational content does not. **Make the author's headline and About section say what the post is about** ("Building FaultLine: verified AI code repair · Linux sandboxing · Meta AI Dev Hackathon").
2. **Hashtags are nearly irrelevant.** Use 0-3, only where they are genuinely descriptive. The text itself is the topic signal.
3. **Specific beats generic.** Precise technical nouns (Bubblewrap, cgroup v2, AST policy, unified diff, Playwright) match the right interest clusters. Vague nouns ("AI", "innovation") match everyone and therefore no one.
4. **Engagement bait is detectable in text.** A model that reads language can recognize "Agree?", "Comment YES", and pod-style comments. Treat them as negative.

---

## 2. Distribution stages and the 60-90 minute golden window *(heuristic)*

1. **Classification (seconds).** Spam and low-quality filters, plus a topic read.
2. **Test audience (first ~60-90 minutes).** Shown to a slice of first-degree connections and followers. Dwell, comments, saves, and sends from this slice decide expansion.
3. **Expansion (hours 2-24).** Second- and third-degree reach through people who engaged, plus interest-based distribution to non-connections.
4. **Long tail (days 2-7).** LinkedIn keeps distributing strong posts for days, much longer than X. Comments on day 3 can still revive a post.

**Golden window playbook:**

- Post Tuesday-Thursday, 7:30-9:30 AM in the audience's time zone (US Eastern for this hackathon), when engineering managers and recruiters scroll.
- Stay available for 90 minutes. Reply to every comment with a substantive answer, ideally ending in a question. Comment threads (comment, author reply, more replies) are a strong signal.
- Line up a few teammates or mentors to leave **real, specific comments** (two or more sentences, a technical question or experience) in the first hour. One-word comments ("Great work!") barely count and may read as pod behavior.
- Do not edit the post in the first hour *(observed)*. Do not post anything else for 18-24 hours, because LinkedIn throttles multiple same-day posts from one author.

---

## 3. Dwell time and "see more"

LinkedIn measures time spent on the post. A click on "...see more" is an explicit high-intent signal, and the time spent reading after it is dwell.

**Engineer the fold:**

- About **210 characters** (roughly 2-3 short lines) show before "see more" on desktop, and fewer on mobile. The hook must fit there and create an open loop.
- Line 1 is a concrete, surprising fact or tension: *"A test that checks 'did checkout return 201?' accepted 5 of 6 wrong AI patches."* Line 2 adds stakes or a twist: *"Ours accepted zero. Here's what it checks instead."*
- After the fold, use short paragraphs (1-3 lines), white space, and a numbered structure. Mobile readers bail on walls of text.
- Total length of 1,200-2,000 characters suits post-mortems and lessons. Do not pad. Dwell from padding is offset by early exits.

**Dwell multipliers:** a document carousel (people swipe through 8-12 pages), an image with dense but legible technical detail (an architecture diagram), and native video with captions.

---

## 4. The high-value signals: Saves and Sends

On LinkedIn, **saves** ("save for later") and **sends** (sharing privately by DM) are the viral multipliers *(heuristic, consistent with LinkedIn's public statements that it values content people find worth keeping and sharing)*.

- A **save** says "this has lasting value." Reference material earns saves: checklists, architecture teardowns, threat-model tables, "7 gates every AI code tool needs."
- A **send** says "a specific person I know must see this." It is a person-to-person endorsement. Engineering managers send posts to their team leads, and engineers send them to their CTO.

**How to earn them without asking cringingly:**

- Make the post a reusable artifact. A carousel slide titled "The verification checklist" is a save magnet.
- Name the person it is for: *"If your team is piloting AI code review, the slide on wrong-but-passing patches is the one to show them."* This prompts a send without saying "share this."
- Reposts with no commentary are a weak signal. Do not chase them.

---

## 5. Format selection

| Format | Strengths | Weaknesses | Use for FaultLine |
| --- | --- | --- | --- |
| **PDF document carousel** | Highest dwell, swipe interactions, very high save rate, works muted | Takes design time | **Primary launch asset:** architecture teardown of the 6 gates |
| **Native video** (vertical 9:16 or square 1:1 / 4:5) | Autoplay in feed, shows real proof | Lower completion than X, sound off | Day-2 post: 30-60 s demo loop, captions burned in |
| **Text only** (with optional single image) | Fast, conversational, strong comment threads | Lower dwell ceiling | Engineering post-mortem, builder journey |
| **Link post** | Clean preview | Reach visibly reduced *(observed)* | Avoid. Use the link handling below. |

### PDF carousel spec (architectural teardown)

- **Size: 1080x1350 px (4:5 portrait).** It fills the most vertical feed space on mobile. Export as PDF and upload as a *document*.
- **8-12 pages.** Fewer feels thin, and more loses swipe-through.
- **Page 1 = hook only.** Huge type, one claim, one visual: *"5 of 6 wrong AI patches passed the obvious test."* Put a subtle "swipe →" cue.
- **One idea per page**, 30 words or fewer per page, minimum 28-32 pt body text, high contrast, consistent with the FaultLine HUD palette (`#0A0B0D` background, rose/cyan/emerald accents).
- **Real artifacts, not stock art.** Diff screenshots, the gate table, the cgroup readback, an evidence-bundle excerpt.
- **Second-to-last page = the "save this" checklist.** **Last page = CTA**: repo, judge page, Devpost or gallery vote (as plain text, not live links).
- Give the document a descriptive title. It appears in the feed as the carousel's header.

Copy for a ready-made 10-page carousel is in [`templates-and-copy.md`](templates-and-copy.md#linkedin-2-architecture-carousel-copy-10-pages).

### Native video spec

- 1080x1350 (4:5) or 1080x1080 (1:1). 1080x1920 (9:16) also works on mobile but crops on desktop.
- Burned-in captions plus an uploaded SRT for accessibility.
- First frame is the failure, same as on X. 30-90 s.

---

## 6. External link handling

LinkedIn wants people to stay in the feed. Posts with outbound links in the body tend to get less distribution *(observed by creators; LinkedIn has denied a blanket penalty, but the effect is consistent in analytics)*.

Options, best first:

1. **Native consumption.** Make the post fully valuable with no click: carousel, video, or complete text. The link becomes optional, so put it in the first comment.
2. **Link in the first comment.** Post, then immediately add the first comment with the repo, judge page, and Devpost or gallery links. Say "Links in the first comment" in the post. *(Observed: this is weaker than it used to be, but still better than links in the body.)*
3. **Edit the link in after the golden window** (after 90-120 minutes), if you must have it in the body.
4. Never use link shorteners. They look spammy and hide the destination from a skeptical audience.

---

## 7. Anti-cringe and anti-slop rules

Engineers and engineering managers mute PR voice instantly. 360Brew reads text, so slop also reads as low quality to the ranker.

### Banned outright

| Banned | Why | Write instead |
| --- | --- | --- |
| "Agree?", "Thoughts?", "Comment YES if…", "Drop a 🔥" | Engagement bait, detectable, cringe | Ask a real, answerable question: "Where would you put the gate: before or after the sandbox run?" |
| "I'm thrilled / humbled / excited to announce" | Fake enthusiasm, a corporate opener | Start with the fact: "We built a test that rejects wrong AI patches." |
| "Game-changer", "revolutionary", "disrupting", "next-gen", "unlock", "leverage", "synergy", "seamless" | PR-speak, zero information | The specific mechanism: "cgroup limits read back from `/sys/fs/cgroup` before anything runs" |
| "In today's fast-paced world…", "Let that sink in.", "Here's the thing:" | AI-slop filler | Delete the sentence |
| Emoji bullet walls (🚀✅💡🔥 on every line) | Signals low effort or generated text | Plain numbers or dashes. One emoji in the whole post at most. |
| Broetry (one-word lines for drama) | Read as manipulative | Normal short paragraphs |
| Tagging 15 people "for visibility" | Spam. Tagged people who don't engage hurt reach *(heuristic)* | Tag only people or companies actually involved (section 8) |
| Unverified numbers ("saves $120k/hr", "99.9% uptime") | One skeptical comment destroys the post | Only numbers with a record (SKILL.md section 0) |
| "AI-powered" as the headline | Everyone is. It means nothing. | Say what the model does and what checks it |

### Tone rules

- **Builder to builder.** Write as the engineer who built it, in the first person, with specifics and admitted limits.
- **Show the failure honestly.** "Our tooling rejected a *correct* patch once. Here's why, and the fix" earns more trust than any win.
- **Limit the claims in the post itself.** "One seeded defect. A Meta run on the full corpus is next." This disarms critics before they comment.
- **Read it aloud.** If it sounds like a press release or a LinkedIn parody account, rewrite it.

---

## 8. Tagging on LinkedIn

- Tag company pages that were genuinely involved: **Meta** and **Cerebral Valley** as hackathon hosts, and teammates.
- Tag 1-3 people who would genuinely want to know: mentors from office hours or people you credit. Each one should get a sentence explaining why.
- Tags go in the body near the end, not the hook.
- Never tag individual Meta employees you haven't interacted with.
