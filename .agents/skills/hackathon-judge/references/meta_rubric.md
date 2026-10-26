# Meta Global AI Developer Hackathon — 100-Point Rubric (FaultLine)

Source: Official Webinar Judging Criteria (`docs/HACKATHON_BRIEF.md` / `meta-provided/webinar/2026-10-26-judging-rubric.png`).

---

## 1. Real-World Impact (30 Points)

Evaluates whether FaultLine solves a critical firsthand problem with measurable economic and developer utility.

| Band | Score | Criteria & Repo Evidence Anchor |
| :--- | :--- | :--- |
| **Pinnacle** | 27–30 | Solves silent high-cost production checkout defects. Provides quantified downtime prevention, conversion protection, and automated post-incident remediation. Grounded in e-commerce loss data and demonstrated across edge test cases. |
| **Strong** | 22–26 | Clear enterprise utility. Demonstrates full incident reproduction and verified patch deployment, but lacks multi-merchant loss telemetry. |
| **Moderate** | 15–21 | Functional defect repair, but feels like an internal developer utility rather than an end-to-end impact platform. |
| **Deficient** | 0–14 | Synthetic toy demo with no discernible production impact or business justification. |

---

## 2. Creative Use of Meta AI Tooling (25 Points)

Evaluates how deeply and effectively Meta AI models and tooling are utilized.

| Band | Score | Criteria & Repo Evidence Anchor |
| :--- | :--- | :--- |
| **Pinnacle** | 23–25 | Advanced integration of Meta inference (Muse Spark / Llama 3.3). Generates strict unified diffs conforming to AST constraints; utilizes prompt containment, structured output repair contracts, and validation against regressions. |
| **Strong** | 18–22 | Reliable source repair using Meta Model API, but relies on standard prompting without custom constrained decoding or validation feedback loops. |
| **Moderate** | 12–17 | Basic API calls to Meta endpoints with minimal task grounding or error recovery. |
| **Deficient** | 0–11 | Meta models bypassed, mocked, or superficially tacked onto an unrelated workflow. |

---

## 3. Technical Depth & Rigor (20 Points)

Evaluates architectural soundness, deterministic sandboxing, test coverage, and execution craft.

| Band | Score | Criteria & Repo Evidence Anchor |
| :--- | :--- | :--- |
| **Pinnacle** | 18–20 | Isolated execution sandbox; zero unchecked file modifications; deterministic Playwright browser assertions paired with backend unit tests; clean async architecture; 100% green verification (`make check`). |
| **Strong** | 14–17 | Solid container/subprocess containment, thorough automated tests, and clear separation between orchestrator and runner. |
| **Moderate** | 9–13 | Working script without robust failure isolation or with partial test coverage. |
| **Deficient** | 0–8 | Fragile code, flaky tests, unchecked arbitrary code execution risks. |

---

## 4. Demo & Presentation (25 Points)

Evaluates the running live demo, Inspector observability, and pitch execution within 180 seconds.

| Band | Score | Criteria & Repo Evidence Anchor |
| :--- | :--- | :--- |
| **Pinnacle** | 23–25 | Flawless 180s live demonstration: chaos trigger -> live browser capture -> Meta repair generation -> isolated candidate execution -> verified green status -> zero regressions. Live Inspector exposes complete state telemetry. |
| **Strong** | 18–22 | Complete demo flow succeeds live, but telemetry display or pitch narrative requires clarification. |
| **Moderate** | 12–17 | Demo succeeds partially or relies heavily on pre-recorded fallback assets. |
| **Deficient** | 0–11 | Broken live demo, timeout, or crashes during core checkout loop. |
