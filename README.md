# FaultLine: Autonomous Browser QA & Verified Source Repair

[![Tests](https://img.shields.io/badge/tests-351%20passed%20%7C%20100%25%20green-3DFFA2?style=flat-square)](https://github.com/FrankieBiz/Faultline)
[![Meta Model API](https://img.shields.io/badge/meta--ai-muse--spark--1.3%20%7C%20llama--3.3--70b-2DD4FF?style=flat-square)](https://api.meta.ai)
[![Python](https://img.shields.io/badge/python-3.13-blue?style=flat-square)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/next.js-16%20Turbopack-black?style=flat-square)](https://nextjs.org/)
[![Playwright](https://img.shields.io/badge/playwright-e2e%20verified-green?style=flat-square)](https://playwright.dev/)
[![Track](https://img.shields.io/badge/hackathon-Meta%20Global%20AI%20Developer%20(Indie)-orange?style=flat-square)](https://github.com/FrankieBiz/Faultline)

> **Autonomous e-commerce QA and verified source repair.**  
> FaultLine captures unhandled production checkout crashes with genuine headless Playwright browsers, synthesizes bounded source patches using Meta AI reasoning models (`muse-spark-1.3` / `Llama-3.3-70B-Instruct`), verifies candidate repairs against a 36-test business invariant suite in disposable detached Git worktrees, and deploys atomic hot-patches with zero human intervention.

---

## The Firsthand Problem: Silent E-Commerce Checkout Outages

Unit tests pass in CI because their mock fixtures are out-of-date, but real customers experience silent checkout crashes in production.

For mid-market and enterprise e-commerce platforms, checkout downtime costs between **$5,600 and $45,000 per minute** ($336,000 to $2.7 million per hour). When an engineer refactors coupon handling, unit tests pass because mocked test data always provides valid coupon strings. In production, when a customer checks out without a coupon, `discounts.get(coupon_code)` returns `None` instead of `0`. The expression `total = subtotal - discount` throws an unhandled:
```text
TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'
```
Conversion drops to zero, and the incident isn't noticed until hours later when on-call is paged.

FaultLine moves generative AI from passive conversational suggestions into a **deterministic, closed-loop browser QA and source repair engine** that detects, diagnoses, patches, and verifies code in under **12 seconds**.

---

## Meta Hackathon Rubric Alignment

| Rubric Pillar | Weight | FaultLine Implementation & Evidence |
| :--- | :--- | :--- |
| **Real-World Impact** | **30%** | Solves $5.6k–$45k/min checkout downtime. Embedded [ROI Calculator](web/inspector-ui/src/components/RoiCalculator.tsx) computes annual revenue saved ($360k+) and engineering hours reclaimed. |
| **Meta AI Tooling** | **25%** | Direct authenticated integration with Meta's `muse-spark-1.3` reasoning model (4,000,000 TPM limit) via `https://api.meta.ai/v1`, enforcing strict JSON Schema output constraints and prompt containment markers. |
| **Technical Depth** | **20%** | Disposable detached Git worktrees (`git worktree add --detach`), compiler-level Python AST syntax and import guardrails, Playwright browser test harness, and 100% green verification across **351 automated tests**. |
| **Demo & Presentation** | **25%** | Baseten/Twelve Labs-inspired Mission Control UI (`web/inspector-ui`) with interactive split-screen Chaos Studio, procedural Web Audio synthesizer, physical seismic tremor animations, and a reproducible 180s pitch rehearsal script. |

---

## Closed-Loop Self-Healing Architecture

FaultLine cleanly separates stochastic model synthesis from deterministic execution gates:

1. **Autonomous Incident Reproduction ([tools/browser-runner](tools/browser-runner))**:
   - Headless Chromium Playwright automation navigates genuine storefront DOM journeys.
   - Intercepts checkout exceptions and bundles a forensically sealed failure packet containing DOM snapshots, network HAR traces, console logs, and Python server tracebacks.
2. **Meta Model Synthesis ([services/repair-orchestrator](services/repair-orchestrator))**:
   - Telemetry evidence is tagged with untrusted boundary markers (`"type": "UNTRUSTED_EVIDENCE"`).
   - Dispatched to Meta's `muse-spark-1.3` reasoning model with strict JSON schema constraints requiring a five-field `PatchProposal` object.
3. **Compiler-Level AST Guardrails ([app/policy.py](services/repair-orchestrator/app/policy.py))**:
   - The unified diff is parsed statically using Python's `ast` module before execution.
   - Rejects unauthorized imports, private/dunder attribute traversal (`__subclasses__`, `__globals__`), and dynamic execution functions (`eval`, `exec`, `open`, `subprocess`).
   - Enforces a bounded blast radius: single target file (`checkout.py`), max 100 changed lines, max 4KB diff.
4. **Sandboxed Worktree Execution ([app/snapshots.py](services/repair-orchestrator/app/snapshots.py))**:
   - Candidate patches are tested in a disposable, content-addressed detached Git worktree.
   - The test suite is mounted read-only—the model cannot game or delete tests.
5. **Deterministic Verification Gate**:
   - Playwright re-executes the authentic customer checkout flow to verify an HTTP 201 Created and order UUID.
   - Runs a 36-test business invariant suite validating tax arithmetic, discount boundaries, and catalog integrity.
6. **Atomic Deployment & Audit Trail ([web/inspector-ui](web/inspector-ui))**:
   - Verified patch is staged with complete cryptographic SHA-256 provenance.
   - Real-time SSE telemetry streams updates to the Mission Control dashboard.

---

## Repository Directory Map

Each component is isolated in a modular package with its own dedicated documentation:

| Directory | Role | Stack | Subpackage Guide |
| :--- | :--- | :--- | :--- |
| **[`apps/buggyshop-backend`](apps/buggyshop-backend)** | Storefront API with seeded coupon checkout defect | Python 3.13, FastAPI, SQLite | [apps/buggyshop-backend/README.md](apps/buggyshop-backend/README.md) |
| **[`apps/buggyshop-frontend`](apps/buggyshop-frontend)** | Authentic Next.js consumer e-commerce storefront | Next.js 16 (Turbopack), React 19, Tailwind | [apps/buggyshop-frontend/README.md](apps/buggyshop-frontend/README.md) |
| **[`services/repair-orchestrator`](services/repair-orchestrator)** | Meta Model API bridge, AST gate & sandbox runner | Python 3.13, FastAPI, Git Worktrees | [services/repair-orchestrator/README.md](services/repair-orchestrator/README.md) |
| **[`tools/browser-runner`](tools/browser-runner)** | Headless browser QA & failure evidence harvester | TypeScript, Playwright | [tools/browser-runner/README.md](tools/browser-runner/README.md) |
| **[`web/inspector-ui`](web/inspector-ui)** | Mission Control dashboard, Chaos Studio & Audio | Next.js 16, React 19, Web Audio API | [web/inspector-ui/README.md](web/inspector-ui/README.md) |
| **[`shared`](shared)** | Strict Pydantic v2 data models & scenario configs | Pydantic v2 (`extra="forbid"`) | [shared/README.md](shared/README.md) |
| **[`fixtures`](fixtures)** | Cryptographic SHA-256 fixture provenance & test seeds | Python 3.13, JSON | [fixtures/README.md](fixtures/README.md) |
| **[`scripts`](scripts)** | Multi-service launcher, pitch rehearsal & reset | Bash, POSIX signals | [scripts/README.md](scripts/README.md) |
| **[`docs`](docs)** | Devpost submission packet, video storyboard & specs | Markdown Documentation | [docs/DEVPOST_SUBMISSION.md](docs/DEVPOST_SUBMISSION.md) |
| **[`.agents`](.agents)** | Hackathon judging tools & virality launch playbook | Curated Agent Skills | [.agents/skills/virality/SKILL.md](.agents/skills/virality/SKILL.md) |
| **[`meta-provided`](meta-provided)** | Immutable Meta webinar artifacts & SHA-256 sums | Reference Materials | [meta-provided/README.md](meta-provided/README.md) |

---

## Quickstart in 60 Seconds

### Prerequisites
* Python 3.13+ (managed via [`uv`](https://docs.astral.sh/uv/))
* Node.js 20+ and npm
* Git

### Step 1: Run Full Verification Suite
Execute all unit, contract, integration, linting, and typechecking checks:
```bash
make check
```
*(Confirms all **351 tests** pass with zero warnings in ~7 seconds).*

### Step 2: Launch the Integrated Platform
Start all 4 services concurrently with unified logs and clean signal handling:
```bash
./scripts/start-demo.sh
```

| Service | Port | Description |
| :--- | :--- | :--- |
| **FaultLine Mission Control** | `http://localhost:4000` | Real-time Inspector UI, Chaos Studio & Audio |
| **BuggyShop Storefront** | `http://localhost:3000` | Next.js E-commerce checkout frontend |
| **BuggyShop API Backend** | `http://localhost:8000` | FastAPI catalog, pricing, and checkout routes |
| **Repair Orchestrator** | `http://localhost:9000` | Meta Model API bridge and sandboxed runner |

### Step 3: Trigger Live Autonomous Self-Healing
1. Open `http://localhost:4000` in your browser.
2. In the **Interactive Chaos Studio**, select *NoneType Subtraction (Seeded 500)*.
3. Click **Run Autonomous Self-Healing Repair**.
4. Observe the real-time telemetry stream: Sentry incident reproduction -> Meta `muse-spark-1.3` reasoning synthesis -> AST guardrail validation -> sandboxed candidate execution -> 36/36 green regression check -> hot-reload deployment.

### Step 4: Rehearse the Pitch Walkthrough
Run the automated end-to-end command-line rehearsal harness:
```bash
./scripts/rehearse-demo.sh
```

---

## Mission Control UI Features

The FaultLine Mission Control dashboard ([web/inspector-ui](web/inspector-ui)) delivers high-sensory developer ergonomics:
* **Interactive Chaos Studio**: Lets developers and judges inject 3 real failure scenarios (`NoneType Crash`, `Unknown Coupon Discount`, `Float Precision Drift`) and witness live client-side and backend recovery.
* **Seismic Tremor Feedback**: High-tension physical CSS screen shake (`animate-seismic-shake`) triggered whenever an exception strikes.
* **Procedural Web Audio API Synthesizer**: 80Hz seismic rumble on crash, cybernetic terminal keystroke chatter, and harmonic two-tone chord resolution upon verified repair (toggle with key `M`).
* **Agent Swarm Cinema**: Step-by-step visual HUD tracking Sentinel Interception -> Meta Reasoning -> AST Gate -> Hot Deployer.
* **Enterprise ROI Calculator**: Configurable downtime leakage model calculating annualized revenue saved and engineering triage hours reclaimed.
* **Competitive Comparison Matrix**: Feature-by-feature architectural breakdown against Datadog, Sentry, and passive AI copilots.
* **Command Palette (`Cmd + K`)**: Power-user keyboard launcher for instant navigation.

---

## Anti-Vaporware Guarantees

1. **Sandboxed Detached Worktrees**: No candidate code ever mutates the working tree or production branch until it has passed all regression gates.
2. **Immutable Test Suite**: The test directory is mounted read-only in the snapshot; models cannot bypass gates by deleting assertions.
3. **Compiler-Level AST Inspection**: Patches are rejected at the syntax tree level if they attempt dynamic execution (`eval`, `exec`, `open`, `subprocess`) or attribute traversal (`__subclasses__`).
4. **Transparent Provenance**: If uncredentialed, the system runs an explicitly labeled `deterministic-checkout-v1` mode that never silently impersonates the Meta Model API.

---

## Documentation & Evaluation Materials

* **[Devpost Submission Packet](docs/DEVPOST_SUBMISSION.md)** — Copy-paste ready submission text for the Meta Devpost hackathon portal.
* **[180-Second Video Storyboard & Script](docs/VIDEO_STORYBOARD.md)** — Second-by-second demo video recording guide with cue-by-cue narration.
* **[Comprehensive Hackathon Dossier](docs/SUBMISSION.md)** — Full technical dossier, economic downtime loss analysis, and quantitative validation.
* **[Automated Rehearsal Script](scripts/rehearse-demo.sh)** — Command-line pitch rehearsal harness.
* **[Implementation Specification](docs/SpecV1.md)** — Detailed technical specification for controlled source repair.
* **[Architectural Research Notes](docs/SpecV1-research-notes.md)** — Primary research notes and trade-off analyses.
* **[Official Hackathon Brief](docs/HACKATHON_BRIEF.md)** — Meta Hackathon requirements, deadlines, and scoring criteria.
* **[Live Project Status](docs/PROJECT_STATUS.md)** — Project status, verified Meta models, and environment settings.
* **[Hackathon Judge Skill](.agents/skills/hackathon-judge/)** — Judging scorecard, automated verification CLI, and hostile Q&A guide.
* **[Virality Playbook Skill](.agents/skills/virality/)** — 30-second dopamine loop, social launch thread architecture, and sensory UI playbook.

---

## Source Integrity & License

Protected Meta-provided webinar assets are preserved byte-for-byte in `meta-provided/` and verified against `meta-provided/SHA256SUMS`.

Authored by **Francis Bisignano (`FrankieBiz`)** for Meta's Global AI Developer Hackathon.
