# FaultLine Multi-Model Master Evaluation Report
## Independent Cross-Model Assessment: UI/UX, Code Architecture, Functional Correctness, Ease of Use & Problem Viability

**Evaluation Date:** November 1, 2026 (Submissions close November 4, 2026 at 9:00 PM ET)  
**Evaluated Revision:** Commit `d8b84b3` (`FrankieBiz/hackathon-winning-usable-product`)  
**Repository:** [FaultLine](https://github.com/FrankieBiz/Faultline) (Francis Bisignano / FrankieBiz)  
**Track:** Meta Global AI Developer Hackathon — Indie Developer Track  
**Evaluator Panel Architecture:**
1. **Tier 1 (Cheap / Unbiased Independent Panel):**
   - **DeepSeek-V4.1 (Chat)**: Skeptical Meta Hackathon Judge (`.agents/judging/eval-panel/report_deepseek_judge.md`)
   - **DeepSeek-V4.1 (Chat)**: Pragmatic SRE & DevOps Engineer (`.agents/judging/eval-panel/report_deepseek_user.md`)
   - **Llama 3.2:latest (Local Ollama 3.2B CPU)**: Systems & Security Auditor (`.agents/judging/eval-panel/report_llama_systems.md`)
2. **Tier 2 (Frontier Overviewers via Real Orca Children):**
   - **Claude Opus 5.5 (High Reasoning)**: Lead Frontend Architect & Executive Judge Overview (`.agents/judging/report_claude_overview.md` via Orca worktree `judge-claude-eval`)
   - **Codex GPT-6.1-Sol (High Effort)**: Principal Systems & Security Engineer Overview (`.agents/judging/report_codex_overview.md` via Orca worktree `systems-codex-eval`)
3. **Tier 3 (Synthesis & Orchestration):**
   - **Antigravity (Gemini 3.8 Flash Coordinator)**: Verification gatekeeper, empirical consolidator, and master report compiler.

---

## 1. Executive Summary & Meta Rubric Scorecard

FaultLine is a verified source repair and browser QA platform designed to catch and fix silent regressions (specifically e-commerce checkout failures) before they reach production.

Across all five independent evaluators, the consensus is unambiguous: **FaultLine's systems engineering and empirical rigor are dramatically ahead of typical hackathon submissions.** It features genuine Linux Bubblewrap namespace containment, verified cgroup v2 aggregate limits (512 MiB RAM, 64 tasks, 1 CPU) proven by kernel readbacks and live OOM/task-hog probes, 1,211 automated repository tests, 42 browser tests, and an independent verification gate that rejects 100% of wrong candidate patches.

However, the panel also identified clear vulnerabilities: the demo defect (`discounts.get(coupon_code)`) is a simple null guard, firsthand user interviews are missing, and the project has critically **undersold its own Meta evidence** by leaving recent live Meta trials out of the headline pitch.

### Meta Hackathon 100-Point Scoring Breakdown

| Category | Weight | Claude Opus 5.5 | DeepSeek Judge | October 27 Baseline | Projected Score Post-Fixes | Main Reason & Evidence |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Impact** | 30 | **18 / 30** | **19 / 30** | 14 / 30 | **20 / 30** | Timely problem (gating AI-generated code); measured business metric ("5 of 6 wrong patches rejected by business oracle"); held back by lack of external customer interviews and single-route demo scope. |
| **Meta AI Tooling** | 25 | **16 / 25** | **15 / 25** | 8 / 25 | **20 / 25** | Structured `muse-spark-1.3` repair core with bounded gate findings fed into attempt 2; 3/3 live trials verified at 44/44 assertions. Held down because the 10-defect holdout corpus was measured with DeepSeek, and index.html still calls Meta trials "outstanding". |
| **Technical Depth** | 20 | **18 / 20** | **17 / 20** | 16 / 20 | **18 / 20** | Linux user/net/PID namespaces, real cgroup v2 memory/pids quotas with OOM-kill probes, AST allowlist, single-file diff recount, byte-for-byte TypeScript/Python gate parity, 1,211 automated tests. |
| **Demo & Polish** | 25 | **19 / 25** | **16 / 25** | 17 / 25 | **21 / 25** | Outstanding evidence-first judge page with recorded Meta and blocked-gate replays, timed 3-minute tour, and seismograph HUD. Held down by inactive hosted live service, unreachable local Inspector for remote judges, and one-line demo bug. |
| **Total Score** | **100** | **71 / 100** | **67 / 100** | **55 / 100** | **79 / 100** | **Strong Contender with Clear Path to Plausible Winner.** |

---

## 2. Multi-Model Consensus & Convergence Matrix

| Dimension | Cheap Panel (DeepSeek & Llama) | Frontier Overviewers (Claude & Codex) | Ground Truth Reality in Repository |
| :--- | :--- | :--- | :--- |
| **1. UI/UX Quality** | SRE persona warned of noisy telemetry and visual crowding; praised Playwright trace preview. | Claude took live Chromium screenshots at 1440px and 390px; verified judge page is A−; identified that Inspector stacks five overlapping start affordances. | Judge page is clean and evidence-first; Inspector has excellent telemetry but needs start buttons consolidated. |
| **2. Code & Architecture** | Llama rated 7/10 with generic tmpfs concerns; DeepSeek praised the verifier feedback loop. | Codex ran all 1,211 tests + 42 browser tests + 14 isolation tests; confirmed real cgroups, strict AST parser, and SQLite WAL transactions. | 1,211 passing tests across three suites; strict mypy typing with 0 errors across 93 files; ruff clean across 106 files. |
| **3. Functional Execution** | Questioned whether repair loop actually works or is a canned animation on one defect. | Codex proved repair works on both BuggyShop fixture and generic Node.js service; Claude confirmed 44/44 live assertions. | Verified end-to-end; deterministic fallback repairs 1/10 defects; DeepSeek verified 18/20 holdouts; Meta verified 3/3 live trials. |
| **4. Ease of Use** | SRE persona called Linux kernel requirements a "wall for MacBook developers"; wanted Docker path. | Claude and Codex proved the SRE was mistaken: `faultline gate` is pure crawl-only (Node/Playwright) and runs anywhere; only backend repair needs Linux. | Gating runs on macOS/Windows/Linux; repair sandbox requires Linux. This distinction must be prominently documented. |
| **5. Problem Solved** | Validated checkout regression as real; warned that empty-coupon bug looks like a toy "null guard". | Claude proved the real thesis is the gate: naive checks accept 5 of 6 wrong patches; FaultLine catches all 6. | The gate and verifier oracle are the real IP; the LLM is the proposal generator. Leading with the gate neutralizes the "toy" objection. |

---

## 3. Dimension-by-Dimension Deep Dive

### Dimension 1: UI/UX & Visual Experience

#### Evaluator Findings
- **Claude Opus 5.5 (Lead Frontend Architect):**
  - **Judge Page (`docs/index.html` - Grade: A−):** The evidence-first design is stellar. Color is used strictly for evidence (rose for detect, amber for repair, green for verify, cyan for in-flight). The seismograph reuses trace telemetry from `CrawlerHud.tsx`. The 3-minute timed tour (`nav.tour`) provides immediate orientation. At 390px mobile viewport, the criteria table stacks cleanly and navigation scrolls without overflow.
  - **Inspector (`web/inspector-ui` - Grade: B):** Strong dark mode aesthetic matching the judge page (`--bg: #07080a`). The CrawlerHud mission clock, journey ribbon, and click-to-focus ticker are distinctive and respect `prefers-reduced-motion`. However, information architecture has debt: it stacks five overlapping start affordances (Hero "Unleash", Quick HTTP Ping, Pre-Flight Gate, Guided Flow 1-2-3, Rail scenarios).
  - **State Handling:** Excellent error recovery. When the backend engine is down, the header turns red ("Engine Status: Needs attention"), the hero chip displays "Engine unreachable", and the rail names the exact missing environment variable.
- **DeepSeek (SRE Persona):**
  - The Playwright trace preview with a scrubbable replay cursor is the killer feature for engineering teams.
  - Cgroup telemetry (512 MiB, 64 tasks) is great for systems engineers, but risks being noise for frontend developers who just want to know "did the patch pass?"

---

### Dimension 2: Code Quality, Architecture & Security Rigor

#### Evaluator Findings
- **Codex GPT-6.1-Sol (Principal Systems & Security Engineer):**
  - **Control Plane & Concurrency:** FastAPI with Bearer authentication and SQLite WAL mode using `BEGIN IMMEDIATE` for cross-connection admission. Job creation, lease reservation, and the first event commit atomically. Transactions never span asynchronous awaits or external side effects.
  - **Sandbox Isolation:** Linux Bubblewrap container isolation provides private user, network, and PID namespaces, readonly application mounts, and bounded private tmpfs. Aggregate systemd cgroup v2 limits (512 MiB memory, no swap, 64 tasks, 1 CPU) are verified directly from `/sys/fs/cgroup` files per launch.
  - **Hog Probes:** Automated tests (`test_resource_limits_cgroup.py`) prove that memory hogs are killed by kernel OOM (-9) and task hogs cannot exceed 64 PIDs.
  - **AST Policy:** The fixture policy enforces strict AST checks on `checkout.py` (max 16 KiB diff, max 100 changed lines, no dunder access, no unauthorized imports, no catch-all `except Exception:` blocks).
  - **Generic Projects vs Fixture:** Codex noted that while BuggyShop has a strict Python AST allowlist, generic projects use `ProjectPatchPolicy` (syntax validation + import delta checks), relying more directly on the Bubblewrap sandbox.

---

### Dimension 3: Functional Correctness — "Does it Actually Work?"

#### Evaluator Findings
- **Codex GPT-6.1-Sol:**
  - **Verified Repair Execution:** The repair loop was verified with fresh test executions. On the BuggyShop fixture, candidate patches pass all 44 independent assertions (integer-cent pricing, coupon normalization, order isolation). On a generic Node.js repository, baseline repair and proof generation passed cleanly in 20.2 seconds under `FAULTLINE_REQUIRE_ISOLATED_TESTS=1`.
  - **Hunk Recounting:** When LLMs generate diffs with miscounted line headers, FaultLine recounts them without altering patch content, mirroring `git apply --recount`.
- **Two Critical Empirical Limitations Discovered by Codex:**
  1. **Bounded Exploration as False Approval:** In `tools/browser-runner/src/crawler.ts:1025`, when the crawler hits `max_actions` or timeout without encountering a defect, it returns `{ status: "clean", stop_reason: "max_actions" }`. The CLI `gate` maps `status: clean` to `SAFE_TO_DEPLOY`. Codex proved via probe that a 1-action budget against a broken store emits `SAFE_TO_DEPLOY` because it never reached checkout! Bounded exploration proves absence of discovered errors, not proof of complete flow coverage.
  2. **Cleanup Failure vs Portable Proof:** When a job experiences a container cleanup failure, the controller correctly sets job outcome to `cleanup_failed` and blocks new runs. However, the portable proof bundle generated prior to cleanup still says `verified` and passes offline consistency checks.

---

### Dimension 4: Ease of Use & Developer Experience

#### Evaluator Findings
- **DeepSeek (SRE Persona):**
  - The CLI triad (`faultline init`, `faultline run`, `faultline gate`) maps perfectly to developer mental models (scaffold → execute → enforce).
  - The safety boundary is exactly right: **FaultLine does NOT auto-deploy to production**. It hands developers a verified unified diff, reproduction trace, and evidence bundle. SREs will not adopt an agent that pushes unreviewed code to prod; the human merge boundary builds trust.
- **Debunking the "macOS Wall" Myth:**
  - DeepSeek initially complained that Bubblewrap and cgroups make FaultLine impossible to run on macOS.
  - **Claude and Codex proved this claim false:** `faultline gate` is pure TypeScript/Playwright. It crawls web applications and checks HTTP invariants without touching Bubblewrap. Only backend repair synthesis requires Linux. Documenting this makes `faultline gate` instantly adoptable across macOS, Windows, and Linux CI runners.

---

### Dimension 5: Real Problem Solved vs Hackathon Theater

#### Evaluator Findings
- **Claude Opus 5.5 & DeepSeek Judge:**
  - **The Problem:** Silent e-commerce checkout regressions are real and expensive. Static linters and type checkers do not catch `None` subtraction on empty strings; unit tests with mock data pass; only real browser interactions trigger the failure.
  - **The "Toy" Defense:** The empty-coupon bug is deliberately simple so judges can observe the verification mechanics. The true intellectual property is not generating the one-line fix—it is **the independent verifier oracle**.
  - **The 5-of-6 Killer Statistic:** Naive CI/CD checks (e.g., "did checkout return 201?") accept 5 of 6 plausible AI-generated patches, including one that silently drops customer orders. FaultLine's 27 business rules and Playwright assertions reject all six. This single statistic reframes FaultLine from a "bug-fixing demo" to an **indispensable pre-deployment immune system**.

---

## 4. The Meta Evidence Undersell (Crucial Finding)

Both Claude and DeepSeek observed that the project's documentation currently **undercells its own Meta AI Tooling achievements**:
1. **The Outdated Claim:** `docs/index.html` (lines 835, 901) and `docs/DEVPOST_SUBMISSION.md` state that "repeated Meta trials are still outstanding" and highlight DeepSeek's 18/20 corpus results.
2. **The Ground Truth Reality:** On October 31, 2026, the project recorded `docs/evidence/2026-10-31-controller-ledger-meta.md` and `.json`. This ledger proves **3 of 3 live `muse-spark-1.3` trials verified on the first attempt at 44/44 assertions**, with median latency of 10.5 seconds and ~3,200 tokens per run, verified by a strict controller that refuses to record non-Meta responses.
3. **Immediate Impact:** Updating `docs/index.html` and Devpost to prominently feature the 3/3 live Meta trials immediately lifts the **Meta AI Tooling score from 16 to 20+**, moving the overall project score to **76–79/100**.

---

## 5. Hostile Judge Q&A Defense Script

### Q1: "Your generalization numbers are from DeepSeek. Is Meta just a checkbox?"
> **Defense:** "Meta (`muse-spark-1.3`) is our default repair core and the primary provider on record. We ran three live `muse-spark-1.3` trials on the checkout route, and all three verified on the first attempt with 44/44 assertions in 10.5 seconds. Our trial ledger strictly rejects non-Meta endpoints. The holdout corpus was run across DeepSeek to prove harness neutrality—the gates reject bad patches regardless of which model generated them."

### Q2: "You fixed an empty coupon bug. That's a trivial one-line null guard."
> **Defense:** "The fix is simple; proving it doesn't break commerce is hard. A status-code check would have accepted 5 of 6 candidate patches for this route, including one that silently discards orders. FaultLine rejected all six. The value is the verification boundary, not the diff size."

### Q3: "Does your sandbox actually contain malicious code?"
> **Defense:** "Yes. We enforce aggregate cgroup v2 limits (512 MiB memory, 64 tasks, 1 CPU) and Bubblewrap namespaces. In `test_resource_limits_cgroup.py`, memory hogs are terminated by kernel OOM (-9) and task hogs are blocked by `pids.max`. We report real kernel telemetry per run, while transparently stating our boundaries: shared Linux kernel, not a hypervisor VM."

### Q4: "Can developers use this on macOS without Linux kernel features?"
> **Defense:** "Yes. `faultline gate` is crawl-only and runs on macOS, Windows, and Linux with Node.js and Playwright. It blocks deployments on broken flows and emits copy-paste agent remediation prompts. Only the sandboxed backend repair runtime requires Linux."

---

## 6. Prioritized Action Plan before Hackathon Deadline

### P0: Immediate Pitch & Evidence Fixes (Est: 1–2 hours)
1. **Update `docs/index.html` and Devpost:** Replace the outdated "repeated Meta trials outstanding" disclaimer with the verified **3 of 3 live `muse-spark-1.3` trials (44/44 passing assertions, 10.5s median wall time)** citing `docs/evidence/2026-10-31-controller-ledger-meta.md`.
2. **Remove README Overclaim:** Delete the statement at `README.md:14` claiming "one-click applies verified diffs to your actual repository." Clarify that project repairs remain safely in the sandbox, with guarded apply available for the demo store.
3. **Document macOS Support for Gate:** Update `docs/PREFLIGHT_GATE.md` to state clearly that `faultline gate` runs natively on macOS, Linux, and Windows.

### P1: Narrative & Pitch Alignment (Est: 2 hours)
4. **Lead with the Immune System Hook:** Open the video and Devpost pitch with the 5-of-6 wrong patch statistic:
   *"Coding agents ship fixes that eliminate HTTP errors without making behavior correct. On our corpus, status-code checks accept 5 of 6 wrong patches—one of which silently drops orders. FaultLine is the pre-flight gate that crawls previews, blocks deployment, and validates Meta-generated repairs in a kernel-contained sandbox."*
5. **Harmonize Naming:** Retire "Autonomous Bug Hunter" and "Chaos Crawler" in favor of **FaultLine: Pre-Flight Gate & Verified Repair**.

### P2: Video Demonstration (Under 180 Seconds)
6. **Follow Claude's Recommended Video Storyboard:**
   - **0:00–0:25:** The Problem — Silent checkout failure & the 5-of-6 wrong patch statistic.
   - **0:25–1:15:** The Pre-Flight Gate — `faultline gate` intercepts HTTP 500, emits structured reproduction trail.
   - **1:15–2:15:** Verifier-Guided Meta Repair — `muse-spark-1.3` proposes unified diff in Bubblewrap cgroup sandbox; passes 44 assertions.
   - **2:15–3:00:** The Agent Loop — Agent fixes code, re-gate emits exit 0 (`SAFE_TO_DEPLOY`), production protected.

### P3: Engineering Polish (Post-Submission Backlog)
7. **Fix Bounded Crawl Gate Ambiguity:** When the crawler stops at `max_actions` without error, return `INCONCLUSIVE_COVERAGE` rather than `SAFE_TO_DEPLOY` unless a required scenario route was executed.
8. **Reconcile Cleanup State in Proof Bundle:** Include container cleanup status in `proof_bundle.json` so offline consistency checkers flag `cleanup_failed` jobs.
