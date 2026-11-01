# FaultLine: Executive Overview from the Frontend Architect and Meta Hackathon Judge

**Date:** November 1, 2026 (submissions close November 4, 9 PM ET)
**Commit reviewed:** `d8b84b3` on `FrankieBiz/judge-claude-eval`
**Inputs:** the three cheap-model panel reports in `.agents/judging/eval-panel/`, the source of `web/inspector-ui/src/`, `docs/index.html`, `README.md`, `docs/DEVPOST_SUBMISSION.md`, and `docs/evidence/`.

**What I actually ran.** I used headless Chromium at 1440 px and 390 px on two surfaces. The first was the judge page, loaded from `file://`. The second was this branch's Inspector, served by `next dev` on a spare port without a control token, so the engine-unreachable path was exercised. I also rendered the recorded Meta replay and the blocked-gate replay on the judge page. I did not run a live repair job, because the shared engine on :9000 belongs to another worktree and its token stays in that process.

---

## 0. The verdict in one paragraph

FaultLine is a real, defensible submission whose engineering is ahead of its pitch. Technical depth and honesty are the strongest of any indie entry I would expect to see. The judge page is a well-made, evidence-first artifact. The weaknesses are a toy demo defect, no user validation, unfamiliar-defect evidence that comes from a non-Meta model, and an Inspector that most judges will never run. My score is **71/100**, and I think **76 to 79** is reachable before November 4 without writing new product code. The single most damaging problem is self-inflicted and takes ten minutes to fix: **the judge page and the Devpost text tell judges that "repeated Meta trials" have not been run, but `docs/evidence/2026-10-31-controller-ledger-meta.md` records 3 of 3 live `muse-spark-1.3` trials verified at 44/44, and the README already says so.**

---

## 1. How much to trust the panel reports

Read the three panel reports with care. **None of the models saw the repository.** `run_evaluators.py` gave each model a hand-written `SYSTEM_CONTEXT` paragraph, so the panel scored a *summary* of FaultLine. That makes the reports useful in one specific way: they show what a tired judge concludes after reading only the Devpost text. They are unreliable as a description of what exists.

| Panel claim | Status in the repo | Evidence |
|---|---|---|
| "Judge orientation is weak; leads with architecture" (DeepSeek judge, −3) | **Already fixed.** The hero is followed by a timed 3-minute tour: Meta repair, then agent gate, then "Try to fool the gates". | `docs/index.html` `nav.tour`; screenshot at 1440 |
| "No adversarial sandbox test cited" (DeepSeek judge, −2) | **Exists.** A memory hog is OOM-killed and a task hog is bounded by the production scope. The readiness payload reports `oom_kill_events`, `pids_max_events`, and `hog_exit_code: -9`. | `services/repair-orchestrator/tests/test_resource_limits_cgroup.py:197,222` |
| "Demo doesn't show a rejection followed by a retry" (DeepSeek judge, −4) | **Partly addressed.** "Try to fool the gates" shows six wrong patches rejected. The recorded Meta retry (`82ac2dcc`) was rejected by `git apply` (a zero-context hunk), *not* by the verifier for wrong behavior. | judge page `#gates`; `DEVPOST_SUBMISSION.md:71` |
| "Headline evidence is DeepSeek, not Meta" (DeepSeek judge, −5) | **Half true.** The page's headline is the Meta repair (44/44, 6.9 s, 3,254 tokens). The *unfamiliar-defect corpus* (18/20) is still DeepSeek-only. | judge page `#repair`, `#criteria` |
| "Model choice hedging, muse-spark or Llama" (−2) | **Resolved.** muse-spark-1.3 is the default and on record. Llama is listed as "Supported; no recorded run yet." | `aside#core` |
| "No cost/ROI model" (−2) | **Partly.** Tokens are recorded per attempt (about 3.1k to 3.4k per verified repair, median wall time 10.5 s). No dollar figure is stated. | Meta ledger 2026-10-31 |
| "Does `gate` fail closed? Machine-readable output?" (SRE persona) | **Yes on both.** Exit codes are 0, 1, and 2, and an inconclusive run fails closed. Output modes are `--json`, `--markdown`, and `--format ci`. The Inspector's gate payload is a TypeScript port that tests check byte for byte against the Python output. | `docs/PREFLIGHT_GATE.md`; `lib/agent-gate.ts` |
| "Crawler shouldn't require the kernel sandbox" (SRE persona) | **Architecturally true already.** `faultline gate` only crawls and touches no Bubblewrap code, but no doc says so and nobody has tested it on macOS. | `app/cli_crawl.py` (no bwrap path in gate) |
| Llama 3.2 "systems audit" (7/10, tmpfs concerns, "lack of documentation") | **Low signal; give it near-zero weight.** It is a 3B local model and its points are generic. The repo is heavily documented. | `report_llama_systems.md` |

**Takeaway.** The DeepSeek judge scored the *summary* at 67. Most of its deductions are already answered in the repo, which means the problem is that **the Devpost text does not answer them**. Rewrite the Devpost text so a summary-only reader reaches the same conclusions a repo reader does (§4.3).

---

## 2. UI/UX: the Inspector and the judge demo

### 2.1 Judge page (`docs/index.html`): A−

This is the surface most judges will actually see, and it is good.

- **Hierarchy.** The h1 hook ("The autonomous immune system / for AI coding agents and web applications") is followed by a green Repair core chip citing `muse-spark-1.3 · 44/44`, then three CTAs, then the 3-minute tour. A judge has their bearings within one screen. Numbered mono kickers (01 to 08) make the 10,472 px page easy to navigate.
- **Evidence-first design.** Color is used only for evidence: rose for detect, amber for repair, green for verify, cyan for in-flight work. The recorded player shows before and after screenshots, the real diff, the model's explanation verbatim, tokens, cgroup limits, and SHA256SUMS. **Very few hackathon entries can show a judge the actual bytes.** The blocked-gate replay (AuraScale, HTTP 500, a five-step reproduction trail, and a copyable agent remediation prompt) is the most persuasive single visual in the submission.
- **Honesty.** Section 08, "What this does not claim", and the "Not yet shown" row in each criterion are unusually candid. Experienced judges reward this. Keep it, but make sure it is *accurate* (see the undersell in §4.1).
- **Craft.** I saw no console errors and no horizontal overflow at either width. At 390 px the criteria table stacks and the nav scrolls. The seismograph reuses the trace math from `CrawlerHud.tsx`, so the two surfaces read as one product.
- **Weaknesses.**
  - **The page is long.** It is 16,652 px tall at 390 px, and "Break it yourself" is dead on the hosted page because the `faultline-live-api` meta tag is empty, so it falls back to the recording. That fallback is honest, but the only *interactive* thing a remote judge can do is replay recordings.
  - **The demo defect is one line.** The diff is `discounts.get(coupon_code)` → `discounts.get(coupon_code, 0)`. When judges see this they think "null guard". The page says the difficulty is in the verification, not the fix. That is correct, but the pitch has to say it before the judge thinks "toy" (§4.2).
  - **The AuraScale target is not in the repo.** Its error body (`NVMeLeaseAllocationException … isolated cgroup enclave #109`) reads as staged. A judge who looks for `:5050` cannot reproduce it.

### 2.2 Inspector (`web/inspector-ui`): B

- **Visual system.** It shares the judge page's tokens (`--bg #07080a`, `--well`, `--raised`), so the two surfaces feel like one product. The hero arena (prompt-style URL field, presets, "Enter to unleash") is a good interaction pattern. The CrawlerHud (seismograph, mission clock, journey ribbon, click-to-focus ticker) is genuinely distinctive work, with motion that uses only composite properties and is gated on `prefers-reduced-motion`.
- **State honesty is excellent.** I ran it with the engine unreachable. The header turned red ("Engine Status: Needs attention"), the hero chip said "Engine unreachable", and the rail named the exact fix ("Set FAULTLINE_CONTROL_TOKEN on the Inspector server. Check again"). The repair label changes to "Repair with Meta" only when readiness reports `provider: meta` and the provider is available. Otherwise it reads "Auto-repair (deterministic-checkout-v1)". This is the right discipline.
- **Information architecture is the main UX debt.** The page stacks **five start affordances** for overlapping jobs:
  1. Hero "Unleash Autonomous Agent"
  2. Hero "Quick HTTP Ping"
  3. Gate "Run Pre-Flight Gate" (the same crawl as #1, routed elsewhere)
  4. Guided Flow steps 1→2→3
  5. Rail scenario "Run sandbox repair" and "Custom URL check"

  A first-time user has to work out how they relate. #1 and #3 are the same Playwright crawl with different presentation (`crawlOrigin`). That is clever internally, but outside it looks like two features.
- **Two identities.** The h1 says "FaultLine Autonomous Bug Hunter" (pinned by tests) while the kicker and judge page say "immune system". Emoji CTAs (🚀 "Unleash", 🛡️) and "Unleash Autonomous Agent" lean hype, while everything else is sober and evidence-led. Pick one voice.
- **Reachability.** The Inspector needs Linux, unprivileged user namespaces, Bubblewrap, cgroup v2 under a systemd user session, uv, Node 24, and a control token. **Assume zero judges run it.** Its value to the score comes entirely through the video and screenshots.
- **One overclaim to remove.** `README.md:14` says the Inspector "One-click applies verified code diffs to your actual repository." The Inspector itself says "Project repairs stay in the sandbox; FaultLine never writes your working source" (`Inspector.tsx:722`). Apply works only for the bundled demo store. A judge who notices this contradiction will discount the honesty everywhere else.
- **Environment note, not a product bug.** The Inspector on :4000 (from the `barnacle` worktree) is a stale `next start` build whose CSS chunk 404s, so it renders unstyled. Anyone recording the video must rebuild first. Separately, `next dev` blocks HMR and hydration when opened as `127.0.0.1` instead of `localhost`, so record from `localhost`.

---

## 3. Ease of use and onboarding friction

| Persona | Path | Time to first value | Friction |
|---|---|---|---|
| Remote judge | Judge page, then tour step 1 (Play) | **About 15 s** | None. This is the strongest path in the submission. |
| Judge who wants to touch something live | "Break it yourself" | Blocked unless the live service is on | High. The service is off by default. |
| Engineer adopting the gate | `faultline gate URL --json` in an agent rule or GitHub Action | **About 10 to 20 min** on Linux | Medium. Snippets are copy-paste ready (Cursor and Claude Code rule, Actions YAML, Agent Skill), but the gate's actual requirements aren't stated. |
| Engineer running the full loop | `make setup && ./scripts/start-demo.sh`, then the Inspector | **30 to 90 min**, Linux only | High. It needs kernel features, a systemd user session (not bare SSH), a token, and four ports. |

**Friction worth fixing before submission:**

1. **Say what `faultline gate` needs.** Gating is crawl-only and does not use the sandbox. If it really runs with Python, Node, and Playwright alone (verify on one non-Linux machine or in a plain container), say so in `PREFLIGHT_GATE.md` and in the judge page's "Run it yourself". That turns the SRE persona's biggest objection ("a wall for MacBook engineers") into a selling point: *the gate runs anywhere, and only the repair sandbox needs Linux.*
2. **Turn the live service on for the judging window**, or remove "Break it yourself" from the tour footer so judges don't hit a dead end.
3. **Vendor AuraScale into the repo** (for example under `apps/aurascale-fixture/`) with a one-line launcher, so the blocked-gate verdict can be reproduced. If the error string is invented for the demo, make it plainer.

The things that already reduce friction: the launcher reports occupied ports instead of killing their owners, the port overrides are documented, `rehearse-demo.sh` exits non-zero unless the run verified and cleaned up, the `?` CLI sheet works, and "Setup and recovery" is tucked away until needed.

---

## 4. Real problem solved vs. hackathon theater

### 4.1 What is real (anti-theater evidence)

- **The problem.** AI agents and humans ship patches that make the error go away without making the behavior correct. The "Try to fool the gates" result states this in one line: *a naive "did it return 201?" check accepts 5 of 6 authored wrong patches, including one that silently drops orders, and FaultLine's 27 business checks plus a browser journey reject all six.* That is the real thesis, and it is measured.
- **The gate.** `faultline gate` follows a real contract: exit codes, fail-closed on inconclusive runs, JSON, Markdown, and CI annotations, a pre-push hook, and a workflow that self-tests a healthy store and a broken one. It is tested with real Chromium (29 tests). It works as a component on its own, not as staging for the demo.
- **The sandbox.** Bubblewrap user, network, and PID namespaces plus cgroup v2 (512 MiB, 64 tasks, 1 CPU, no swap), with **kernel-read-back verification and OOM and task-hog probes**. That is real systems work, and the limits section honestly says "not a VM, no seccomp".
- **Meta evidence is stronger than the submission claims.** The record holds three live muse-spark-1.3 trials, all verified on the first attempt at 44/44, with a median of 10.5 s and about 1.6k prompt and 1.3k to 1.9k completion tokens each, recorded by a ledger script that **refuses to count anything except a Meta provider response**. It also holds one retained two-attempt Meta job. This was tooling built to prevent self-deception.

### 4.2 Where it drifts toward theater

- **One route, one fixture store, one-line fix.** Every repair result, including the 10-defect corpus, is on `POST /api/checkout` of BuggyShop. The corpus tests generalization *across defect types on one route*, not across apps.
- **The external "broken site" is a scratch app outside the repo**, with a dramatized error message.
- **The Meta retry was a tooling rejection.** In the retained two-attempt Meta job, `git apply` refused a zero-context hunk; the verifier never rejected wrong behavior. The verifier-feedback loop (the most interesting Meta-tooling idea) has been shown working on behavior only with DeepSeek.
- **Copy inflation in the Inspector.** "Unleash Autonomous Agent", "Chaos Crawler", "Live Agent Mission", and the 🚀 emoji oversell what is a well-engineered deterministic crawler.

**Net judgment: about 75% real and 25% theater-adjacent.** The theater-adjacent part is *presentation*. The engineering is not fake, and all of it can be fixed with copy and evidence before the deadline.

---

## 5. Meta rubric scoring

My scores are against the published weights, scoring what a judge can verify from the judge page, the README, and the repo.

| Criterion | Weight | Claude | DeepSeek panel | Rationale |
|---|---:|---:|---:|---|
| Impact | 30 | **18** | 19 | A timely problem (gating AI-written changes) and a sharp measured stat ("5 of 6 wrong patches"). Held down by no user interviews or production use, one route, and one store. |
| Use of Meta AI tooling | 25 | **16** | 15 | muse-spark is the real default repair core, with a strict schema, bounded untrusted evidence, a gate-findings retry, honest provider attribution, and 3/3 live trials with tokens. Held down by unfamiliar-defect evidence that is DeepSeek-only, no behavioral rejection-then-retry shown for Meta, no Llama run, and **the submission underselling its own 3/3 ledger**. |
| Technical depth | 20 | **18** | 17 | Namespaces, verified cgroup limits with hog probes, AST and import policy, independent HTTP and browser oracles, checksummed bundles, hunk recount, a gate contract ported to TS and checked byte for byte, and about 1,211 tests. Held down by no seccomp and single-file scope. |
| Demo and polish | 25 | **19** | 16 | The judge page is excellent: a recorded run at real timing, real verdict JSON, and a 3-minute tour. Held down by the live path being off, a one-line demo bug, an Inspector that is unreachable for judges, and AuraScale being non-reproducible. |
| **Total** | **100** | **71** | **67** | |

**Score after the fixes in §6:** Meta tooling rises to 19 to 21 (if a Meta corpus run lands) and Demo to 21, giving **76 to 79**. Impact cannot move much without real users, and in four days only two pieces of evidence could move it: one external team's quote or one real open-source app gated.

---

## 6. Pitch recommendations, in priority order

### P0: before anything else (hours)

1. **Stop underselling the Meta evidence.** Update `docs/index.html:835` ("Not yet shown: repeated Meta trials…"), `docs/index.html:901` ("One retained Meta repair and one Meta retry… repeated Meta trials… still outstanding"), and `DEVPOST_SUBMISSION.md:28,55,80` to cite **3 of 3 live muse-spark-1.3 trials, all verified on the first attempt, 44/44, median 10.5 s** with a link to the 10-31 ledger. Keep the scope caveat (one scenario). This is the highest return per minute in this report.
2. **Run Meta on the unfamiliar-defect corpus** (`checkout-eval-v1`, ten defects) and publish the result *whatever it is*. This is the only change that answers the strongest hostile question ("why is your generalization evidence from DeepSeek?"). If muse-spark scores below DeepSeek's 18/20, publish that too and frame it as "the gates caught every wrong Meta patch". That is the product working.
3. **Delete the README overclaim** at `README.md:14` ("One-click applies verified code diffs to your actual repository").

### P1: the narrative (copy only)

4. **Lead with the gate and the 5-of-6 stat, not the coupon bug.** Suggested 20-second opening: *"AI agents ship fixes that make the error disappear. On our corpus a status-code check would have shipped five of six wrong patches, one of which silently drops orders. FaultLine is the gate that stops them: it crawls the preview, blocks the deploy, hands the agent the exact reproduction, and only counts a Meta-written fix after 44 independent checks pass in a kernel-limited sandbox."* Then introduce the coupon bug as *"deliberately simple, so you can watch the verification, which is the hard part."*
5. **Make the Devpost text pre-empt the panel's objections.** The DeepSeek judge read a summary and deducted for things that exist. Add one line each for: the hog-probe tests (sandbox red-team), the gate's exit codes and fail-closed behavior, the token cost per repair, and the 3-minute tour link.
6. **Pick one name.** "Immune system" is the hook. Retire "Autonomous Bug Hunter", "Unleash", and "Chaos Crawler" from anything a judge sees, including the video. The Inspector h1 is pinned by tests, so update the tests too.

### P2: the demo

7. **Video storyboard (under 3 minutes), matching the tour:**
   - 0:00 to 0:20: the hook and the 5-of-6 stat.
   - 0:20 to 1:05: the Inspector Guided Flow only (Break it, Repair with Meta, Apply fix) with the seismograph rupture and then resonance. Hide the rail and the hero ping.
   - 1:05 to 1:50: `faultline gate` in a terminal against a broken preview: exit 1, paste the remediation prompt into Claude Code or Cursor, the agent fixes it, re-gate, exit 0. This **closes the agent loop on camera**, which is the immune-system claim made literal.
   - 1:50 to 2:30: "Try to fool the gates", picking the order-dropping patch and showing the rejection.
   - 2:30 to 3:00: limits, honestly stated, and the repo.
8. **Show a behavioral rejection with Meta.** If the corpus run produces a Meta attempt 1 that the verifier rejects and attempt 2 passes, make that the replay linked from the "Meta tooling" criterion row.
9. **Live service.** Turn it on for the judging window with rate limits, or remove "Break it yourself" from the tour.
10. **Vendor AuraScale** into the repo so the blocked verdict can be reproduced.

### P3: Inspector UX (only if time remains after P0 to P2)

11. **Merge "Unleash" and "Run Pre-Flight Gate" into one action.** Use a single URL field whose result renders as a gate verdict with a "Repair" follow-up. Demote "Quick HTTP Ping" and "Custom URL check" into the `?` sheet.
12. **Collapse the dashboard (rail, history, setup) behind a "Developer workspace" disclosure** so the default page is hero, verdict, and guided flow.

---

## 7. Hostile Q&A: grounded answers

**"Your generalization numbers are DeepSeek. Is Meta a checkbox?"**
> "Meta is the default repair core and the only provider on the recorded demo. We ran three live muse-spark trials on the seeded defect, and all three verified first try at 44/44. Our ledger script refuses to count any non-Meta response as a Meta trial. The ten-defect corpus was first measured with DeepSeek, labeled as non-Meta everywhere. [If P0-2 lands: here is the Meta corpus run.] The gates don't care which model wrote the patch, and that's the point."

**"You fixed a null guard."**
> "Yes, on purpose. The fix is trivial; knowing it's *correct* isn't. A status-code check would have accepted five of six wrong patches for this same route, including one that silently drops orders. FaultLine rejected all six."

**"Show me the sandbox holding."**
> "`test_memory_hog_is_killed_by_the_production_scope` and `test_task_hog_is_bounded_by_the_production_scope` run against the real cgroup v2 scope, and readiness reports the OOM-kill and pids-max events live. We also say plainly what it isn't: a shared kernel, not a VM, and no seccomp."

**"Can I use the gate on my Mac?"**
> Answer only after verifying P1-1. If it holds: "The gate is a crawl, so it needs Python and Playwright. Only the repair sandbox needs Linux."

---

## 8. Bottom line

FaultLine's engineering and honesty would hold up in front of an expert panel. Its score is held back by **evidence it already has but does not cite**, a **demo bug that invites the "toy" reflex**, and an **Inspector judges won't run**. Fix the Meta undersell today, attempt the Meta corpus run, lead with the gate and the 5-of-6 stat, and record the agent-loop video. That moves the submission from "strong contender" to "plausible winner" in the Indie track without new product code.
