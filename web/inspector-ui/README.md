# FaultLine Inspector & Mission Control UI

**Package**: `faultline-inspector-ui`  
**Framework**: Next.js 16 (Turbopack) & React 19  
**Styling**: Tailwind CSS v4, Lucide React, Custom Dark Mode HUD  
**Port**: `http://localhost:4000`  

FaultLine Inspector is the developer mission control dashboard for autonomous browser QA and verified source repair. It provides real-time SSE telemetry feeds, visual diff inspection, an interactive chaos studio, an enterprise downtime ROI calculator, and procedural in-browser Web Audio feedback.

---

## Architecture & Components

* **`src/app/page.tsx`**: Core Mission Control dashboard handling Server-Sent Events (SSE) from the Repair Orchestrator (`http://localhost:9000`), real-time job state transitions, terminal log outputs, and browser-synthesized tactile audio.
* **`src/components/InteractiveChaosStudio.tsx`**: Interactive testing panel allowing developers and judges to simulate and inject 3 distinct failure scenarios (`NoneType Crash`, `Unknown Coupon Discount`, and `Float Precision Drift`) with physical seismic screen-shake feedback.
* **`src/components/AgentCinema.tsx`**: Multi-agent execution timeline visualizing the four autonomous phases:
  1. `01 // SENTRY SENTINEL` (Exception telemetry interception)
  2. `02 // META REASONING ENGINE` (Streaming token generation from `muse-spark-1.3`)
  3. `03 // AST VERIFIER & GATEKEEPER` (Sandboxed git worktree syntax gate)
  4. `04 // HOT-RELOAD DEPLOYER` (Zero-downtime patch deployment)
* **`src/components/RoiCalculator.tsx`**: Real-time economic downtime calculator computing annual revenue leakage prevented and engineering triage hours reclaimed.
* **`src/components/CompetitiveMatrix.tsx`**: Architectural comparison matrix contrasting FaultLine with traditional APM (Datadog/New Relic), error monitoring (Sentry), and passive code copilots.
* **`src/components/CommandPalette.tsx`**: Quick-action keyboard launcher activated via `Cmd+K` or `Ctrl+K`.
* **`src/components/IntegrationDroplet.tsx`**: One-liner embed and CLI installation snippet generator.

---

## Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **`Cmd + K` / `Ctrl + K`** | Open Command Palette HUD |
| **`M`** | Toggle Procedural Web Audio Sound Effects |
| **`Esc`** | Dismiss Modals & Palette |

---

## Local Development

```bash
# Install dependencies
npm install

# Start development server on port 4000
npm run dev

# Run TypeScript check and production build
npm run check
```
