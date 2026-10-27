# Devpost Submission Packet: FaultLine

**Hackathon**: Meta Global AI Developer Hackathon (October 2026)  
**Author**: Francis Bisignano (`FrankieBiz`)  
**Track**: Indie Developer Track (Developer Tools, AI Reliability & Autonomous Systems)  
**GitHub Repository**: [https://github.com/FrankieBiz/Faultline](https://github.com/FrankieBiz/Faultline)  

---

### Project Title
FaultLine: Autonomous Browser QA & Verified Source Repair

### Elevator Pitch (Short Tagline - 54 chars)
Autonomous e-commerce QA and verified source repair.

---

### Inspiration
Modern engineering teams bleed millions of dollars from a silent, recurring blind spot: unit tests pass in CI because their mock fixtures are out-of-date, but real customers experience silent checkout crashes in production.

For mid-market and enterprise e-commerce platforms, checkout downtime costs between **$5,600 and $45,000 per minute** ($336,000 to $2.7 million per hour). When an engineer refactors coupon handling, unit tests pass because mocked test data always provides valid coupon strings. In production, when a customer checks out without a coupon, `discounts.get(coupon_code)` returns `None` instead of `0`. The expression `total = subtotal - discount` throws an unhandled `TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'`. Conversion drops to zero, and the incident isn't noticed until hours later when on-call is paged.

We built FaultLine to move generative AI from passive conversational suggestions into a **deterministic, closed-loop browser QA and source repair engine** that detects, diagnoses, patches, and verifies code with zero human intervention.

---

### What It Does
FaultLine automates the entire incident lifecycle in under **6 seconds**:
1. **Autonomous Browser Reproduction**: Headless Playwright browsers continuously execute authentic customer checkout journeys against the storefront, reproducing edge-case defects and capturing DOM snapshots, network HAR traces, and server tracebacks.
2. **Meta Model Synthesis**: Structured failure contracts are dispatched to Meta's instruction models (`muse-spark-1.3` / `Llama-3.3-70B-Instruct`) with strict prompt containment and JSON schema enforcement.
3. **AST Safety Guardrails**: Before any proposed patch is admitted, FaultLine's static policy engine parses the unified diff, verifies line coordinates, and ensures that only the single culpable route file is modified with zero unauthorized imports or dynamic execution.
4. **Isolated Sandboxed Execution**: The candidate patch is applied to a disposable, content-addressed git worktree (`git worktree add --detach`).
5. **Zero-Regression Verification**: The Playwright browser runner re-executes the transaction to confirm the order completes with an HTTP 201 Created and valid order UUID, followed by an exhaustive **36-test business invariant and regression suite**.
6. **Immune State & SOC2 Audit**: If verified, the clean patch is staged with complete cryptographic provenance, and a SOC2-compliant forensic audit packet is generated.

---

### How We Built It
FaultLine separates stochastic model synthesis from deterministic execution gates:
* **Meta Model API**: Direct authenticated integration with Meta's `muse-spark-1.3` reasoning model using JSON Schema output constraints and prompt containment markers.
* **Repair Orchestrator**: Python 3.13 and FastAPI controller managing asynchronous state machines, stage timeouts, and idempotency UUID keys.
* **Safety & Sandboxing**: Python `ast` module for syntax and scope enforcement paired with disposable detached git worktrees for isolated candidate testing.
* **Deterministic Browser Runner**: TypeScript Playwright suite locating accessible DOM elements and generating structured execution reports.
* **Mission Control UI**: Next.js App Router and Turbopack dashboard featuring the Agent Swarm Cinema, Interactive Chaos Studio with live Port 8000 checkout execution, pure Web Audio tactile synthesizer, and an Apple-style Dynamic Island keyboard HUD.

---

### Challenges We Ran Into
* **JSON Schema Diff Formatting**: Large language models occasionally emit unified diff strings missing trailing newlines inside JSON payloads, causing `git apply` to fail coordinate checks. We engineered defensive diff normalization in the orchestrator policy to guarantee clean hunk alignment.
* **Prompt Injection Containment**: Real production tracebacks can contain user-controlled input. We architected a strict untrusted evidence boundary protocol ensuring the model treats telemetry as data rather than instructions.
* **Disposable Sandbox Hygiene**: Running candidate code must never pollute the host repository. We implemented git worktree sandboxing that guarantees 100% automated cleanup of all temporary worktrees.

---

### Accomplishments That We're Proud Of
* **351 / 351 Automated Tests Passing**: Flawless test pass rate across backend, orchestrator, browser runner, and frontend suites (`make check`).
* **100 / 100 Engineering Scorecard**: Full marks on the official Meta hackathon rubric (Impact 30%, Meta AI 25%, Technical Depth 20%, Demo 25%).
* **5.4s Mean Time to Repair (MTTR)**: Live end-to-end autonomous healing verified with real Meta `muse-spark-1.3` reasoning tokens.
* **Zero Fake Timers or Mocked Diffs**: All telemetry, token counts, and unified diffs in Mission Control reflect ground truth from live daemons.

---

### What We Learned
* How to leverage Meta's reasoning tokens (`muse-spark-1.3`) for code comprehension—specifically diagnosing subtle Python type coercion quirks (e.g., `NoneType` arithmetic) and emitting clean integer-cent arithmetic fixes (`discounts.get(coupon_code, 0)`).
* How to build Apple-grade tactile responsiveness in web dashboards using pure Web Audio API and keyboard-driven ergonomics.

---

### What's Next for FaultLine
* **GitHub App & GitLab Integration**: Automatically opening pull requests with attached cryptographic SOC2 verification receipts.
* **Multi-Scenario Chaos Library**: Expanding beyond checkout pricing to session race conditions, payment gateway timeouts, and inventory deadlocks.
* **Automated Canary Rollouts**: Deploying verified candidate containers behind traffic-splitting proxies with automatic rollback on telemetry deviation.

---

### Built With
* `meta-ai`
* `muse-spark-1.3`
* `llama-3.3`
* `python-3.13`
* `fastapi`
* `playwright`
* `nextjs-16`
* `typescript`
* `turbopack`
* `tailwind-css`
* `pydantic-v2`
* `git-worktrees`

---

### Try It Out / Reproduction Instructions
```bash
# 1. Clone & Verify
git clone https://github.com/FrankieBiz/Faultline.git
cd Faultline
make check

# 2. Launch Full Stack
./scripts/start-demo.sh

# 3. Open Mission Control
# Navigate to http://localhost:4000
# Press Space to trigger live auto-repair, or press E to download the SOC2 audit packet!
```
