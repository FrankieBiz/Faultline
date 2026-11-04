# FaultLine judge video: final narration script

Prepared November 4, 2026. Target: 2:59. Your voice narrates the captioned master. This is our editorial target, not a verified organizer-imposed duration. The official [submission portal](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit) requires sign-in; confirm its video fields before upload.

Read naturally, without imitating a presenter. Aim for roughly 130 words per minute and use the remaining time in each cue as a quiet hold; the whole script is about 330 words. Start each new section at its printed time. In the Meta section, let the result land at about 0:52 before saying “Forty-four passed.” In the close, begin “FaultLine gives…” when the end card appears at 2:48. The screen recording carries captions, so do not rush to read identifiers or commands aloud. Source labels remain visible: today's local recording, the retained October 28 Meta job, and the authored evaluation corpus are different evidence.

## 0:00–0:15 — The failure

“Leave the coupon empty, and this checkout crashes. But making the error disappear is only half the problem. A patch can return a successful status while silently breaking discounts or never saving the order. FaultLine makes a repair prove itself.”

Picture: the real local storefront, empty coupon, checkout failure. Label: deliberately seeded demo defect; recorded November 4.

## 0:15–0:31 — Block the broken preview

“Before a coding agent ships, FaultLine explores its preview with a real browser. Here it reaches the checkout failure, blocks with exit one, and returns the steps and a fix prompt. This crawler uses deterministic heuristics; it is not the model.”

Picture: actual captured `faultline gate` output, HTTP 500, reproduction trail and exit 1. Do not use the historical simulated terminal-flex video.

## 0:31–1:02 — Meta writes the patch

“Meta's muse-spark-1.3 proposes the source patch from the business contract and failure evidence. This is our retained October twenty-eighth job, replayed at its recorded timing. Meta generated the patch; independently authored checks decided whether to accept it. Forty-four passed, and cleanup completed. The diff and original explanation are available beside the record.”

Picture: complete recorded Meta replay, then its one-line patch. Label: retained recording, job `3573b32b`, not a new live Meta trial. The full job lasted 13.039 seconds; do not call every future run a thirteen-second repair.

## 1:02–1:33 — Exercise the local pipeline

“Today's local run uses the clearly labeled deterministic fallback, with no model call. It still reproduces the failure, applies the patch policy, and verifies the candidate in an isolated runtime. Linux namespaces confine it, with memory, task, and CPU limits read back from the kernel. The checks judge correctness.”

Picture: actual Inspector run, provider label, verification result, runtime disclosure. Keep the run's actual execution unsped.

## 1:33–1:55 — A successful status can lie

“This authored wrong fix returns two-oh-one but never saves the order. A status-only check accepts it. FaultLine rejects it on six business checks. Across six authored wrong fixes for this checkout, the status check accepted five; FaultLine accepted none, while still accepting both correct fixes.”

Picture: `early_return_unsaved` in the recorded corpus explorer. Label: authored test cases, recorded evaluation; these are not Meta-generated patches.

## 1:55–2:34 — Apply, then check again

**1:55–2:07:**

“Apply writes only the verified diff to the bundled demo store. Checkout now returns two-oh-one.”

**2:07–2:25:**

“The new gate finishes exploring and exits zero. That is a clean smoke check of the flows it reached, not a proof of every business rule.”

**2:25–2:34:**

“A checksummed evidence bundle keeps the run inspectable, and Revert restores the seeded store.”

Picture: actual Apply, live HTTP 201 recheck, captured clean-gate output with `stop_reason: exhausted`, evidence and Revert. Caption any cuts between these steps; never substitute a historical clean result.

## 2:34–2:59 — Scope and close

“This is a controlled prototype: one checkout route, single-file repairs, and a shared-kernel sandbox. Meta evidence covers one scenario; general repair reliability remains unmeasured. FaultLine gives coding agents a gate they can obey, and developers a repair they can inspect. The source and interactive evidence are linked here.”

Picture: scope card, then judge-page and repository URLs.

## Recording and delivery

- Use the completed recording's edit list and caption timings as the final timing authority. This script is approximately 330 words; leave room for the actual Meta playback and visible results.
- Keep all source/provenance captions when adding narration. Do not describe local deterministic footage as Meta or a retained replay as a new live run.
- Export the master as H.264, 1920×1080, 30 fps, with fast-start metadata. Deliver English subtitles separately as well as on screen.
- Before upload, watch the whole exported file, inspect the first and last frames, verify text stays legible, and check that the final source links match the approved public release.
- Upload and final form submission require the owner's account and approval. A local MP4 path is not a public video URL.
