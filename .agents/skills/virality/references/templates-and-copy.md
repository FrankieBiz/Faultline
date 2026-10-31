# Templates and copy

Copy-paste-ready drafts for X and LinkedIn. Every factual line traces to `README.md`, `docs/EVALUATION.md`, or `docs/DEVPOST_SUBMISSION.md` as of 2026-10-31. **Re-verify each number and link before posting**, and replace every `[BRACKETED]` placeholder. The owner reviews and sends. Nothing here is auto-published.

Placeholders:

- `[VIDEO]`: native upload of the 30-60 s hero cut
- `[REPO]`: https://github.com/FrankieBiz/Faultline
- `[JUDGE]`: https://frankiebiz.github.io/Faultline/
- `[REPLAY]`: https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/
- `[GALLERY]`: Devpost / gallery entry URL (owner fills in)
- `[THREAD]`: URL of the pinned X launch thread

Character budgets: X posts are 280 characters unless the account has a Premium long-post allowance. Keep root posts under 280 anyway, because short roots outperform. The LinkedIn fold is about 210 characters.

---

## X-1: Launch thread

**Root post** (attach `[VIDEO]`, no links):

```text
Leave the coupon field empty and this checkout crashes.

Meta's model wrote the fix in 6.9s.

But that's not the interesting part. The interesting part is everything that had to pass before we believed it. 🧵
```

**Reply 1 (links, posted immediately):**

```text
Links so you can check everything yourself:

Code: [REPO]
Recorded Meta run (real timing): [REPLAY]
Judge page + evidence: [JUDGE]

Built for the Meta AI Developer Hackathon with @AIatMeta and @cerebral_valley
```

**Post 2: the claim and proof** (attach the gate table image):

```text
We wrote 6 plausible-but-wrong fixes for this bug.

A "did checkout return 201?" test accepted 5 of them.

FaultLine accepted 0, and still accepted both correct fixes.

A green status code isn't verification.
```

**Post 3: the pipeline** (attach the pipeline diagram):

```text
What a patch goes through before it counts:

1. Bug reproduced twice in fresh browsers
2. Model returns a diff, treated as untrusted
3. AST policy: no catch-all except, import allowlist
4. Bubblewrap sandbox + cgroup v2 limits, read back
5. 27 independent business assertions
```

**Post 4: the sandbox** (attach the `bwrap` command / cgroup readback screenshot):

```text
The candidate runs under:

bwrap --unshare-all --cap-drop ALL --clearenv

512 MiB, no swap, 64 tasks, 1 CPU, enforced by cgroup v2.

We read the limits back from /sys/fs/cgroup and refuse to run if they don't match. Trust, then verify the kernel too.
```

**Post 5: honest scope:**

```text
What's real today:
- 3/3 Meta trials verified first try, median 10.5s
- Every verified job ships a checksummed evidence bundle

What isn't yet:
- A Meta run over our 10-defect corpus. That's next.

One seeded checkout bug. We'd rather say that than oversell.
```

**Post 6: CTA:**

```text
If you build AI code tools: what's the assertion you'd add that we're missing?

Best answer gets turned into a gate.

Vote for FaultLine in the gallery: [GALLERY]
```

---

## X-2: Technical architecture breakdown (day 2-3, quote the launch thread)

**Root** (attach the architecture diagram):

```text
How we let an AI model patch code without trusting it.

6 gates. Any one can reject. Here's each one and the failure it exists to catch ↓
```

**Thread:**

```text
1/ Reproduction gate
The failure must happen identically in TWO fresh browser sessions before the model is ever called.

Flaky bugs never trigger a repair. That alone kills a class of hallucinated "fixes".
```

```text
2/ Prompt containment
Source, logs, and findings go to the model as JSON-encoded *untrusted evidence*.

The prompt states the checkout's business contract, not the bug and not the fix.
```

```text
3/ AST + patch policy (parse, never execute)
Rejected before anything runs:
- stale source hashes, extra paths, malformed hunks
- bare imports, dynamic exec, dunder access
- except: / except Exception
  (you don't fix a crash by hiding it)
```

```text
4/ Hermetic sandbox
Fresh detached git worktree from a pinned commit. Tests exported separately from app code.

Bubblewrap: private user/PID/IPC/net/UTS/mount namespaces, read-only mounts, empty env.
```

```text
5/ Kernel limits + business assertions
cgroup v2: 512 MiB, 64 tasks, 1 CPU, verified by readback.

Then the browser journey plus 27 HTTP assertions on coupons, quantities, totals, and stored orders.
```

```text
6/ Feedback + proof
Rejected? The exact findings go back to the model for one retry.

Verified only after identity, artifact hashes, AND cleanup are confirmed. Every job gets a checksummed bundle you can re-check offline.
```

```text
Source + every gate in code: [REPO]

Which gate would you remove first, and what would break?
```

---

## X-3: Interactive playground challenge (final day of the X window)

> Use the "Break it yourself" wording only if the public live service is deployed and requires a Meta provider. Otherwise use the local variant below.

**Root** (attach a 15-20 s clip of choosing a defect and the verdict):

```text
Challenge: pick a bug. Our gates decide if Meta's fix is real.

10 planted checkout defects: rounding, pricing, validation, persistence. The model is never told which one you picked.

Can you find one it gets wrong, or one our gates let through? ↓
```

**Reply 1 (live service variant):**

```text
Try it: [JUDGE] → "Break it yourself"

Every run lands in a public ledger, labeled by the provider that answered. Post your result here: screenshot + defect name.
```

**Reply 1 (local variant):**

```text
Run it locally (Linux, ~5 min):

git clone [REPO]
make setup && ./faultline doctor
./scripts/start-demo.sh

Then hit "Break it" in the Inspector. Post what you find.
```

**Follow-up reply (at the end of the day, with real results only):**

```text
Results so far from your runs: [N verified / N rejected, linked to the ledger]

Thanks to everyone who tried to break it. [GALLERY] if you want to vote.
```

---

## LinkedIn-1: Engineering post-mortem

```text
Our verification pipeline rejected a correct AI patch. That was our bug, not the model's.

Here's what happened, and why it made the system better.

We're building FaultLine for the Meta AI Developer Hackathon. It reproduces a failing checkout in a real browser, asks Meta's muse-spark-1.3 for a single-file patch, and only accepts it after independent checks pass in a sandbox.

In one recorded run, the model's first patch was right. Same change as the one that later verified.

But it used a zero-context diff hunk. It passed our AST policy, then `git apply` refused it inside the disposable snapshot. The job marked attempt 1 as failed.

Our feedback loop sent that exact error back to the model as untrusted evidence. The retry verified. And we fixed the tooling: snapshot application now accepts zero-context hunks.

Three lessons for anyone putting AI in a code path:

1. Your verifier has bugs too. Log rejections with enough detail to tell "wrong patch" from "wrong tooling."
2. Feedback beats retries. Sending the specific failure back worked; blindly regenerating wouldn't tell you anything.
3. Publish the failures. The replay of this run is public next to the successes.

What's the strangest false rejection your CI has ever produced?

Links to the replay and code are in the first comment.
```

**First comment:**

```text
Recorded run (rejected → verified retry): https://frankiebiz.github.io/Faultline/replay/82ac2dcc-e7f9-4ea7-9187-a0c0d79d8ba3/
Code: [REPO]
Hackathon gallery: [GALLERY]
```

---

## LinkedIn-2: Architecture carousel copy (10 pages)

**Post text (above the PDF):**

```text
5 of 6 wrong AI patches passed the obvious test.

We tested it: six plausible-but-wrong fixes for one checkout bug. A "does it return HTTP 201?" check accepted five. Our pipeline accepted none, and still accepted both correct fixes.

The carousel walks through the 6 gates that made the difference, with the real artifacts.

If your team is evaluating AI code agents, slide 9 is the checklist to bring to that meeting.

Built for the Meta AI Developer Hackathon with Meta and Cerebral Valley. Code and recorded runs are in the first comment.
```

**Document title:** `How to verify an AI-written patch: 6 gates (FaultLine teardown)`

**Pages (1080x1350, at most 30 words each, real screenshots):**

| # | Headline | Body | Visual |
| --- | --- | --- | --- |
| 1 | 5 of 6 wrong AI patches passed the obvious test. | How we built the test that caught all six. Swipe → | Red/green split: "201 OK ✓" vs "Rejected ✗" |
| 2 | The bug | Empty coupon field → HTTP 500 `TypeError` at checkout. Seeded on purpose, so we know the truth. | Storefront "Checkout failed" banner |
| 3 | Gate 1: Reproduce it twice | Two fresh headless browsers must fail identically. Flaky? No model call. | Two session panels, same failure |
| 4 | Gate 2: Treat the model as untrusted | Evidence goes in as JSON-encoded data. The prompt gives the business contract, never the fix. | Prompt structure diagram |
| 5 | Gate 3: Parse, never execute | AST policy blocks catch-all `except`, unapproved imports, dynamic exec, oversized diffs. | Rejected-diff snippet with the policy error |
| 6 | Gate 4: Contain it | Bubblewrap namespaces. Read-only mounts. Empty environment. Fresh git worktree per attempt. | `bwrap` command line |
| 7 | Gate 5: Verify the kernel too | cgroup v2: 512 MiB, 64 tasks, 1 CPU, read back before running. Then 27 business assertions. | cgroup readback + assertion list |
| 8 | Gate 6: Feedback + proof | Rejections go back to the model once. Verified only after cleanup. Checksummed evidence bundle. | Evidence bundle excerpt |
| 9 | Checklist: before you trust an AI patch | ☐ Reproduced twice ☐ Untrusted input ☐ Static policy ☐ Sandbox ☐ Business assertions, not status codes ☐ Cleanup proven | Clean checklist, save-worthy |
| 10 | Scope, honestly | 3/3 Meta trials verified, median 10.5 s. One seeded scenario. Full Meta corpus run: next. github.com/FrankieBiz/Faultline | Repo URL as text, FaultLine mark |

**First comment:**

```text
Code: [REPO]
Judge page with recorded runs: [JUDGE]
Evaluation method + the 6 wrong fixes: [REPO]/blob/main/docs/EVALUATION.md
Vote in the hackathon gallery: [GALLERY]
```

---

## LinkedIn-3: Builder journey (vote window, Nov 9-16)

```text
Two weeks ago I asked a simple question: can an AI model fix a production bug without anyone having to trust it?

The answer we shipped for the Meta AI Developer Hackathon is "yes, if you check everything except the model."

What I'd do the same:
→ Start with the failure, not the AI. A real browser has to reproduce the bug twice before any model is called.
→ Write wrong answers on purpose. Six plausible-but-wrong patches showed us that "returns 201" is a broken oracle.
→ Record everything. Every verified job has a checksummed evidence bundle, and we published the runs that failed.

What I'd do differently:
→ Run the model across our full defect corpus earlier. That Meta run is still next on the list, and I'd rather say so than imply it.
→ Test our own tooling as hard as the patches. Our verifier once rejected a correct fix.

The numbers I'm proudest of aren't the fast ones. They're the zeros: 0 of 6 wrong patches accepted, and 0 cleanup failures across 3 Meta trials.

Thank you to Meta and Cerebral Valley for running this, and to [NAMES + one line each on what they helped with].

If this approach is useful to you, the community vote is open until [DATE]. The link is in the first comment.
```

**First comment:**

```text
Vote: [GALLERY]
Code: [REPO]
Recorded Meta repair: [REPLAY]
```

---

## Reply snippets (for reply loops)

Use them as starting points, never verbatim twice.

| Incoming | Reply draft |
| --- | --- |
| "It's just a GPT wrapper" | "Fair test. The model is the part we trust least. 6 wrong patches: a 201 check accepted 5, our gates accepted 0. Table: [REPO]/blob/main/docs/EVALUATION.md. Which gate would you attack?" |
| "Would you run this in prod?" | "Not today, and we say that in the README. It verifies a candidate in a sandbox. It doesn't deploy. Production rollout needs more than one seeded scenario." |
| "How is the sandbox enforced?" | "Bubblewrap with all namespaces unshared, caps dropped, env cleared, plus a systemd-run cgroup scope whose limits we read back from /sys/fs/cgroup before launch. Mismatch = refuse." |
| "What if the model games the tests?" | "App files are exported separately from tests and reference solutions, and the prompt gives the business contract, not the assertions. Good question for a red-team run. Want to try?" |
| "Which model?" | "muse-spark-1.3 via Meta's API for the recorded runs. The provider label comes from the endpoint host, and non-Meta runs (e.g. DeepSeek) are labeled as such in every record." |
| "Cool!" | "Thanks! Which part would you want to see next: the rejection replays or the sandbox internals?" |
