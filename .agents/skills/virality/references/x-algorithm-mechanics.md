# X (Twitter) algorithm mechanics for developer launches

How the For You ranker decides whether a post travels, and how to engineer a launch around it.

> **Provenance.** The weights below come from X's March-April 2023 open-source release: `twitter/the-algorithm` and `twitter/the-algorithm-ml` (`projects/home/recap`). X has since said ranking has moved toward Grok-based models. Treat these numbers as **directional ratios** that still match what practitioners observe, not as live constants. Anything labeled *heuristic* is practitioner consensus, not published by X.

---

## 1. Pipeline in one paragraph

Candidate sourcing pulls roughly 1,500 posts per user from in-network accounts (people you follow, via RealGraph) and out-of-network sources (SimClusters communities, the follow graph, embeddings). A light ranker prunes them. The **Heavy Ranker**, a neural network, predicts the probability of each engagement type for that user and post. Each probability is multiplied by its weight and summed into one score. Heuristics and filters then apply: author diversity, a feedback-fatigue penalty, an out-of-network discount, and visibility filters for safety and spam. Your job is to raise the high-weight probabilities and keep the negative ones near zero.

---

## 2. Heavy Ranker engagement weights (2023 release)

| Signal (config name) | Weight | Ratio to a like | What it means for you |
| --- | ---: | ---: | --- |
| `reply_engaged_by_author`: someone replies **and you reply back** | **+75.0** | **150x** | The single most valuable event. Run a reply loop (section 5). |
| `reply`: user replies | **+13.5** | 27x | Ask for a specific technical opinion, not "thoughts?" |
| `good_profile_click`: profile click followed by engagement or dwell | **+12.0** | 24x | Your bio and pinned post must convert the click (section 7). |
| `good_click`: opens the conversation and replies or likes inside it | +11.0 | 22x | Threads with substance below the fold earn this. |
| `good_click_v2`: opens the conversation and stays at least 2 minutes | **+10.0** | 20x | Deep threads, code screenshots, long-form replies. |
| `retweet` | **+1.0** | 2x | Nice, but a minor ranking signal. Its value is distribution to new graphs. |
| `fav` (like) | **+0.5** | 1x | The baseline unit. |
| `video_playback50`: watches 50% of a video | +0.005 | ~0 | The *ranking* weight is tiny. Video wins through dwell and the replies it provokes (section 4). |
| `negative_feedback_v2`: "show less", mute, block | **-74.0** | -148x | One annoyed viewer cancels about 150 likes. Do not spam tags. |
| `report` | **-369.0** | -738x | Never engagement-bait, mass-tag, or reply-spam. |

**On bookmarks.** The +10 weight is often misreported as "bookmark". In the published config it is `good_click_v2`, a 2-minute conversation dwell. Bookmarks became a visible public metric after 2023, and practitioners treat them as a strong save-for-later signal, but no weight was published. Optimize for them anyway: a post worth bookmarking (an architecture diagram, a checklist, a reproducible command) is also a post people dwell on.

**Practical reading of the table:**

1. 30 genuine replies you answered are worth more than 4,000 likes.
2. A post that makes engineers *argue about a technical choice* outranks one they merely admire.
3. Anything that causes "show less" is catastrophic. Mass-tagging strangers is the usual cause.

---

## 3. The 30-minute velocity window *(heuristic)*

Early engagement *rate*, not total engagement, decides whether a post leaves your follower graph and enters out-of-network For You candidate pools.

- **Minutes 0-30.** The ranker tests the post on a slice of your followers. Replies and author replies in this window compound, because every reply re-surfaces the conversation to the replier's followers.
- **Minutes 30-120.** If velocity holds, out-of-network distribution through SimClusters starts. A second wave comes from quote posts.
- **After about 6 hours.** Ranking decays sharply. Revive with a reply-to-self containing new evidence (a new clip or result), not with a repost.

**Pre-launch setup for the window:**

- Post when your followers are awake: Tuesday-Thursday, 8:00-10:30 AM ET, which also catches EU afternoon. Check your own analytics, which beat any general rule.
- Line up 5-10 people (teammates, friends from the hackathon Discord) who will **reply with real technical questions** in the first 15 minutes. Do not ask for likes or retweets. Coordinated identical engagement is detectable and worthless.
- Clear your calendar for 60 minutes. You are the reply loop.
- Do not post anything else from the account for 3-4 hours. Author diversity heuristics make your own posts compete with each other.

---

## 4. Video mechanics

Video is the format that stops the scroll for a developer tool. The demo *is* the argument.

| Rule | Why | How |
| --- | --- | --- |
| **3-second hook** | Autoplay is muted, and the scroll decision happens in about 1-3 s | Frame 1 shows the failure: the red checkout banner, HTTP 500. No logo, no title card, no face. |
| **10-second threshold** *(heuristic)* | Watches past ~10 s are treated as qualified views and drive dwell. Under 10 s reads as a skip. | Something new on screen every 2-3 s: failure, then reproduction, then diff. |
| **Native upload** | Embedded YouTube or Loom players get a fraction of the reach and break autoplay | Upload the MP4 directly. H.264, 1920x1080 (16:9) for UI demos, or 1080x1350 (4:5) crops for phone dominance. |
| **Dynamic burnt-in captions** | Most viewers watch muted, and X's auto-captions are unreliable on code terms | Word-by-word or phrase captions burned into the pixels, high contrast, kept out of the bottom ~15% where the player UI sits |
| **30-60 s for the root post** | Completion rate falls off a cliff past ~60 s for a cold audience | 30-60 s hero cut in the root post. The 2-3 min version goes in the thread or on YouTube for the Devpost. |
| **Loop-friendly ending** | Autoplay loops count as more watch time | End on the green verified state, which cuts cleanly back to the red failure |
| **No external link in the root post** *(observed)* | Posts with outbound links get visibly suppressed, because X keeps users on-platform | Put the repo, Devpost, and judge page in the **first reply-to-self**, and say "links below" in the root. |
| **Readable at phone size** | UI text at 1080p shrinks to about 6 px on a phone | Record with CSS zoom of 1.2 or more (`record-footage.sh` defaults to 1.2), and crop or zoom on the diff and the gate result |

**Thumbnail.** X uses the first frame by default. Make frame 1 the red failure with a clear caption ("Empty coupon field → HTTP 500").

---

## 5. Reply-loop mechanics: answer the first 20 within 15 minutes

Because `reply_engaged_by_author` is 150x a like, the launch-hour job is conversation, not broadcasting.

**Protocol:**

1. **Minutes 0-15.** Reply to *every* reply, up to the first 20, inside 15 minutes. Speed matters, because each author reply re-surfaces the thread to the replier's network while velocity is being measured.
2. **Each reply adds something new:** a number with its source, a screenshot, a one-line command, or a counter-question. "Thanks!" is wasted. "Good catch. That's why `except Exception` is banned by the AST gate. Here's the rejection: [screenshot]" earns another reply.
3. **End roughly half your replies with a question** so the loop continues (reply, author reply, reply, author reply). Each round is another weighted event.
4. **Answer skeptics first and best.** The "this is just a wrapper" reply is a gift. Answer with the 5-of-6 wrong-fix result and the rejection replay. Hostile-to-convinced threads are what people screenshot.
5. **Quote posts.** Reply inside the quote post's thread too, which earns distribution in the quoter's graph.
6. **Minutes 15-120.** Keep answering, and batch every 10-15 minutes.
7. **Never** reply with the same copy-paste text, link-dump in replies, or argue past two exchanges. A mute from a heated exchange costs -74.

---

## 6. Thread retention mechanics

Threads exist to earn `good_click` and `good_click_v2` (conversation dwell) and to hold the links the root post must not carry.

- **The root post stands alone.** Video, a 2-4 line hook, and "🧵" or "How it works ↓". Most viewers never open the thread, so the root has to deliver the whole payoff.
- **Post 2 is the strongest technical claim plus proof.** It answers "why should I believe this?" before they leave.
- **One idea per post, one visual per post.** Diff screenshot, gate table, architecture diagram, evidence bundle.
- **5-7 posts maximum** for a launch. Long threads lose readers fast after post 3 or 4.
- **The last post is the call to action:** links, Devpost or gallery vote, "try to break it". Pin the thread to your profile for the whole campaign.
- **Self-replies extend the life.** On day 2 or 3, reply to your own thread with a new clip (rejection replay, new trial result) instead of re-posting. The original's engagement history carries over.

---

## 7. Profile-click conversion (+12)

Every viral post sends traffic to your profile. Make the click pay off:

- **Bio.** What it does plus the proof hook, for example: "Building FaultLine: browser-reproduced bugs → Meta-model patches → verified in a sandbox. Meta AI Dev Hackathon."
- **Pinned post.** The launch thread with video.
- **Header image.** The red-to-green before/after, or the gate pipeline diagram.
- **Website field.** The judge page, or the Devpost/gallery during the vote window.

---

## 8. Things that quietly kill reach

| Action | Effect |
| --- | --- |
| Tagging 10+ accounts in the root post | Looks like spam, invites mutes (-74), and is the usual way tags backfire |
| Hashtag stacks (more than 2) | Treated as low quality. One event hashtag, if the organizers use one, is fine. |
| Editing the post in the first hour | Can reset or confuse distribution *(observed)*. Fix typos in a reply instead. |
| Deleting and reposting | Loses the velocity history and looks like manipulation |
| Engagement pods or "like for like" | Wrong audience, so negative signals rise and out-of-network tests fail |
| External link in the root post | Suppressed reach *(observed)* |
| Posting the same video on several accounts in the same hour | Duplicate-content filtering |
