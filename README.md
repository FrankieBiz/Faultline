# FaultLine: Autonomous Browser QA & Verified Source Repair

**Meta Global AI Developer Hackathon Entry (October 2026)**  
**Author**: Francis Bisignano (`FrankieBiz`)  
**Track**: Indie Developer Track (Developer Tools, AI Reliability & Autonomous Systems)  

FaultLine is a closed-loop platform that reproduces critical production e-commerce failures using genuine headless Playwright browsers, synthesizes verified source repairs using Meta AI reasoning models (`muse-spark-1.3` / `Llama-3.3-70B-Instruct`), and validates candidates against a deterministic 36-assertion business and regression suite in disposable, isolated git worktrees.

---

## At a Glance

| Pillar | Implementation |
| :--- | :--- |
| **Real-World Impact (30%)** | Prevents catastrophic e-commerce checkout downtime ($5,600 to $45,000/minute). Autonomously resolves silent 500 bugs that slip past mocked CI tests. |
| **Meta AI Tooling (25%)** | Live authenticated Meta Model API integration with `muse-spark-1.3` reasoning model, strict JSON schema output enforcement, and isolated prompt containment. |
| **Technical Depth (20%)** | Isolated git worktree sandboxing, Python AST syntax & safety validation, Playwright browser test harness, and 100% green test suite (351 automated tests). |
| **Demo & Presentation (25%)** | Baseten-precision + Twelve Labs-cinematic Mission Control UI (`web/inspector-ui`) with live split-screen Interactive Chaos Studio, telemetry feeds, and 180s pitch runbook. |

---

## Architecture Overview

FaultLine cleanly separates stochastic model synthesis from deterministic execution gates:

1. **BuggyShop Storefront & Backend**:
   - Next.js App Router storefront (`apps/buggyshop-frontend`) running on port 3000.
   - FastAPI Python 3.13 backend (`apps/buggyshop-backend`) running on port 8000.
   - Seeded defect: Absent/empty coupon handling bug throwing `TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'` on checkout.
2. **Deterministic Browser Runner (`tools/browser-runner`)**:
   - Headless Playwright browser automation driven by TypeScript.
   - Navigates real DOM, adds items to cart, triggers purchase, and intercepts failures.
   - Packages failure packets with DOM snapshots, network traces, and Python server tracebacks.
3. **Repair Orchestrator (`services/repair-orchestrator`)**:
   - Python 3.13 FastAPI controller running on port 9000.
   - Manages asynchronous job lifecycle, timeouts, idempotency, and audit trails.
   - Dispatches failure context to Meta Model API (`https://api.meta.ai/v1`) using strict JSON schema output constraints.
4. **Safety & Containment Engine (`PatchPolicy` & `SnapshotManager`)**:
   - Pre-activation AST parsing and coordinate validation.
   - Candidate execution in disposable detached git worktrees (`git worktree add --detach`).
   - 36-test business invariant and regression suite evaluation before candidate admission.
5. **Mission Control UI (`web/inspector-ui`)**:
   - Next.js App Router dashboard running on port 4000.
   - Real-time SSE event streaming, unified diff viewer, Agent Swarm Cinema, and Interactive Chaos Studio.

---

## Running Locally

### Prerequisites
* Python 3.13+ (managed via `uv`)
* Node.js 20+ and npm
* Git

### 1. Verify All Automated Test Suites
Run the full gate check (unit, contract, browser runner, linting, typechecking, and packaging):
```bash
make check
```
*(Confirms all 351 tests pass with zero warnings).*

### 2. Launch the Integrated Stack
Start all 4 services concurrently:
```bash
./scripts/start-demo.sh
```

| Service | Port | Description |
| :--- | :--- | :--- |
| **FaultLine Mission Control** | `http://localhost:4000` | Baseten/Twelve Labs Inspector UI & Chaos Studio |
| **BuggyShop Storefront** | `http://localhost:3000` | E-commerce Next.js web application |
| **BuggyShop API Backend** | `http://localhost:8000` | FastAPI catalog, pricing, and checkout routes |
| **Repair Orchestrator** | `http://localhost:9000` | Meta Model API bridge and sandboxed runner |

### 3. Trigger Autonomous Repair
1. Open `http://localhost:4000` in your browser.
2. In the **Interactive Chaos Studio**, select *NoneType Subtraction (Seeded 500)*.
3. Click **Run Autonomous Self-Healing Repair**.
4. Observe the live pipeline stream: Sentry incident reproduction -> Meta `muse-spark-1.3` reasoning synthesis -> AST guardrail validation -> sandboxed candidate execution -> 36/36 green regression check.

---

## Documentation & Evaluation Materials

* [`docs/SUBMISSION.md`](docs/SUBMISSION.md) — Comprehensive hackathon submission packet, economic loss analysis, quantitative proof, and 180s pitch runbook.
* [`docs/SpecV1.md`](docs/SpecV1.md) — Implementation specification for the controlled repair demo.
* [`docs/SpecV1-research-notes.md`](docs/SpecV1-research-notes.md) — Primary research notes and architectural rationale.
* [`docs/HACKATHON_BRIEF.md`](docs/HACKATHON_BRIEF.md) — Hackathon rules, schedule, and judging criteria.
* [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — Live project status, verified Meta models, and account details.
* [`.agents/skills/hackathon-judge/`](.agents/skills/hackathon-judge/) — Judging scorecard, automated verification CLI, and adversarial grill Q&A.

---

## Source Integrity

Protected Meta-provided materials are preserved byte-for-byte in `meta-provided/` and checksummed in `meta-provided/SHA256SUMS`.
