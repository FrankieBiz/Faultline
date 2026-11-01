# Independent Evaluation: End-User & Developer Experience
**Model**: DeepSeek-V4.1 (Chat)
**Elapsed Time**: 20.6s

# FaultLine: Independent Review from the SRE / Engineering Lead Chair

**Reviewer stance:** I run platform/SRE for a mid-size e-commerce org. I've been burned by "AI fixes your bugs" pitches before. I care about: does it catch real regressions, does it lie to me, and does it fit into a PR pipeline without becoming a flaky tax on my team. I'm going to be blunt.

---

## 1. Ease of Use & Onboarding

### The CLI surface is the right shape, but the story is incomplete

`faultline init` / `faultline run` / `faultline gate` is a clean, conventional triad. That's good — it maps to the mental model every engineer already has (scaffold → execute → enforce). Naming is honest: `gate` implies a pass/fail barrier, not a magic fixer. I appreciate that.

**But the docs I'd need to trust this are the ones I can't see in the summary.** Specifically:

- What does `faultline init` actually write? A config file? A Playwright project? A contract spec? If it's a YAML contract, I need to know the schema and whether it's versioned. If it's "point at a URL and go," I need to know what it *assumes* about my app (auth? seeded data? a running dev server?).
- `faultline run` against *what*? A localhost URL? A preview deploy? A staging environment? The crawler needs a target and a definition of "checkout flow." If I have to hand-author the click-trail contract, that's a real onboarding cost — and it's the exact thing that makes QA tools die in a backlog.
- `faultline gate` — what's the exit code contract? Does it fail closed on infrastructure errors (bubblewrap unavailable, cgroup missing)? That's the single most important question for CI adoption and it's not answered here.

### Setup friction is the biggest red flag for the average frontend engineer

This is where I get genuinely concerned. The dependency stack is:

- **Linux kernel features**: Bubblewrap namespaces, cgroup v2, systemd user scopes.
- **Python via `uv`**.
- **Node.js** (for the Next.js inspector and Playwright).

For a *Staff SRE* on a Linux CI runner, this is fine. For the **average frontend engineer on a MacBook**, this is a wall. Bubblewrap is Linux-only. cgroup v2 + systemd user scopes are Linux-only. So the "run it locally before you push" story is effectively **"run it in a container or don't run it at all."** That's a significant UX cliff, and it needs to be *stated loudly* rather than discovered when `faultline run` explodes on macOS.

**My recommendation to the team:** ship a first-class `docker run` / devcontainer path and make it the *documented default*. The sandboxed repair orchestrator is a server-side concern; the *crawler* and *gate* should be runnable anywhere. If the crawler requires the full bubblewrap stack, that's a coupling problem — the crawler doesn't need kernel isolation to click through a staging URL.

### Time-to-value: probably 30–90 minutes, gated on the contract

Realistic estimate for a motivated engineer with a Linux box or container:

- `init` + config: 10–20 min (assuming the contract schema is sane).
- First crawl against a known-broken checkout: 10 min.
- Understanding the output bundle: 15–30 min.
- Getting a *useful* signal (not just "it ran"): the rest.

That's acceptable for a hackathon-grade tool. It is **not** acceptable if the contract authoring is manual and brittle. The single biggest time-to-value lever is: **can FaultLine infer the checkout flow from a URL + a couple of hints, or does it need a hand-written spec?** The summary says "registered e-commerce checkout failure" — registered implies a contract. I want to know how much of that contract is auto-derived.

---

## 2. UI/UX of the Inspector

### The Inspector is well-scoped for its job — and that job is *not* CI

The feature list — live job status, Playwright trace preview, replay cursor, cgroup kernel telemetry, pre-flight gate — reads like a **debugging console**, not a dashboard. That's the correct instinct. When a gate fails, I don't want a pretty chart; I want to *see the click that broke* and *see the diff that's supposed to fix it*.

**What's likely good:**
- **Playwright trace preview + replay cursor** is the killer feature. Playwright traces are already the gold standard for browser debugging; surfacing them inline with a scrubber is genuinely useful and hard to fake. This is the thing that earns trust.
- **Pre-flight gate** as a distinct visual state is smart — it tells me "we checked whether this run is even valid before showing you results," which is exactly the honesty I want from a tool that claims to verify fixes.
- **cgroup telemetry** is *interesting* but I'm skeptical it's *actionable* for a frontend engineer. 512 MiB / 64 tasks / 1 CPU is a sandbox constraint, not a product metric. Showing it builds credibility with *me* (the SRE) but risks being **noise** for the developer who just wants to know "did my patch pass?"

**What's likely noisy / risky:**
- **Visual hierarchy risk**: trace preview + replay cursor + cgroup graphs + job status + gate state + patch diff is a *lot* of panes. If the primary question — "**is this patch safe to merge?**" — isn't the loudest thing on screen, the UI has failed. The gate verdict and the *one* failing assertion should dominate; everything else should be collapsible.
- **Real-time feedback** is a trap if it means "spinner that updates every 200ms." For a repair loop that runs multiple attempts, what I want is a **clear attempt timeline** (attempt 1 → rejected, findings → attempt 2 → verified) with the *bounded gate findings* visible per attempt. That's the actual story of the tool. If the UI shows a live log instead, it's worse than the CLI.

### CLI vs. UI: the CLI wins for CI, the UI wins for *triage*

This isn't close:

- **CI/CD**: CLI, always. `faultline gate` must emit a machine-readable result (JUnit XML? SARIF? a JSON bundle?) and a non-zero exit on failure. The Inspector is irrelevant in a headless runner. If the gate's only rich output is the web UI, that's a design failure — CI can't consume a Next.js app.
- **Triage / PR review**: the Inspector. When a gate fails on a PR, I want a link to the trace, the replay, and the candidate diff. That's the Inspector's job, and it's a good one.

**The honest critique:** the Inspector is a *demo asset* first and a *product* second. That's fine for a hackathon. For adoption, the CLI output must be the source of truth, and the Inspector must be a *rendering* of that same bundle — not a separate code path. If they diverge, engineers will stop trusting both.

---

## 3. Functional Utility & Real-World Adoption

### Does it work in a real team's workflow? Partially — and the gaps are the usual ones

**The good:**
- The **verifier-guided repair loop** with *independent external HTTP and browser regression suites* is the right architecture. The critical property is that the candidate patch is validated by a *different* mechanism than the one that generated it. That's the difference between "AI wrote a patch" and "AI wrote a patch that a second system proved doesn't regress." This is the single most credible thing in the whole project.
- **Bounded gate findings fed into attempt 2** is exactly how you avoid the "AI flails forever" failure mode. Bounded retries + structured feedback = debuggable.
- **AST validation + restricted imports + single-file modification** is a real safety property. I'd want to see the allowlist, but the *intent* is correct.

**The gaps that will bite in a real org:**
- **Scope is narrow.** "Silent checkout regressions" is a great beachhead, but my team's silent failures are: auth token expiry, race conditions in cart state, third-party payment SDK timeouts, feature-flag misconfigs. A tool that only catches `None` subtraction on empty coupons is a *demo*, not a *platform*. The 10-defect holdout corpus is a start; I need to know its *diversity*, not its size.
- **The 18/20 DeepSeek verification number is doing a lot of work.** 90% on a 10-defect corpus is a *small sample*. The earlier 55/100 internal review's concern — "need for live Meta trial repetition" — is the right concern. I'd want to see: per-defect pass rates, false-positive rate (patches that "pass" but are wrong), and behavior on *unseen* defect classes. A 90% headline on a curated corpus is not the same as 90% in my repo.
- **No mention of how the contract stays in sync with the app.** Checkout flows change. If the contract rots, the gate becomes a flaky test that everyone mutes. This is the #1 killer of QA tooling and it's not addressed.

### The safety boundary is correct — and it's a feature, not a bug

**FaultLine does not auto-deploy.** It produces a verified candidate patch + evidence bundle. **This is exactly right.** I would not adopt a tool that auto-merges AI-generated patches to checkout code, full stop. The boundary is:

1. Detect failure (crawler).
2. Propose patch (LLM).
3. Verify patch in isolation (sandbox + external suites).
4. **Hand a human a diff + evidence.**

Step 4 is where trust is built. "Magic" that skips step 4 is a liability. The summary frames the boundary defensively ("does it reduce the magic?") — I'd reframe it: **the boundary is the product.** A tool that respects the human merge decision is one I can put in front of a skeptical team.

### Would I put `faultline gate` in GitHub Actions? Conditionally.

**Yes, if:**
- It fails **closed** on infrastructure errors (missing bubblewrap/cgroup → fail the job, don't silently pass).
- It emits a **machine-readable artifact** (JSON/SARIF) plus a PR comment with a link to the Inspector trace.
- It runs against a **preview deploy**, not localhost, so it tests what will actually ship.
- It has a **time budget** (e.g., 10 min) and a **quarantine path** for known-flaky contracts.
- The contract is **versioned in the repo** and reviewed like code.

**No, if:**
- The only way to see *why* it failed is the web UI.
- It requires a bespoke Linux runner image that my platform team has to maintain.
- The contract is hand-maintained and drifts.
- The 90% verification rate turns out to be 90% on *curated* defects and much lower on my real ones.

The honest answer: **I'd pilot it on a non-critical flow first** (e.g., a marketing-site form, not checkout), measure false-positive rate for a month, and only then consider gating checkout PRs. That's not a knock on FaultLine — it's how any new gate earns its place.

---

## 4. Top 3 UX / Product Recommendations

### 1. Make the CLI the source of truth and the Inspector a renderer of the same bundle

Right now the Inspector risks being a parallel implementation. **Fix:** define a single **evidence bundle schema** (JSON) that `faultline run`/`gate` emit, and have the Inspector render *only* that bundle. Benefits:
- CI gets a first-class artifact (SARIF/JUnit/JSON) with no web dependency.
- The Inspector can't drift from reality.
- PR comments can link to a *static* rendered bundle even without a running server.
- Debugging "why did the gate fail" becomes `cat bundle.json | jq`, which every SRE trusts more than a dashboard.

This is the highest-leverage change and it's mostly plumbing.

### 2. Kill the setup cliff: decouple the crawler from the sandbox, ship a container-first path

The bubblewrap/cgroup/systemd stack is correct for the **repair orchestrator** (untrusted code execution) but wrong as a prerequisite for **crawling and gating**. **Fix:**
- `faultline run` (crawl + gate) should work with just Node + Playwright, anywhere, including macOS.
- `faultline repair` (sandboxed candidate execution) requires the Linux stack, and should be documented as "runs in CI or a container."
- Ship a `docker run` one-liner and a devcontainer as the *default* onboarding path.
- Detect missing kernel features at `init` time with a clear, actionable error — not a stack trace at `run` time.

This alone probably cuts time-to-first-bug from "an afternoon" to "20 minutes."

### 3. Make the gate verdict the loudest thing in the UI, and show the *attempt timeline*

The Inspector's job is to answer one question: **"Is this patch safe to merge, and if not, why?"** **Fix:**
- Top of screen: a single **verdict banner** (VERIFIED / REJECTED / INCONCLUSIVE) with the *one*
