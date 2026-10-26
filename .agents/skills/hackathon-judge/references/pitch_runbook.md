# Pitch Runbook: 180-Second Live Judging Script

Master presentation cues, timing, and fallback protocols for FaultLine at Meta's Global AI Developer Hackathon.

---

## Pre-Flight Checklist (T-Minus 5 Minutes)

1. Run `make check` to verify 100% test pass.
2. Start the local server stack: Next.js frontend, FastAPI backend, BuggyShop instance.
3. Open Inspector tab at `http://localhost:3000` (or configured port) at 100% browser zoom.
4. Ensure clean terminal view ready for live log inspection.
5. Confirm offline fallback toggle is accessible if network drops.

---

## 180-Second Cue-by-Cue Script

### Beat 1: The Inciting Problem (00:00 – 00:30)
- **Visual**: BuggyShop storefront displaying Trail Mug and Field Notebook.
- **Narrative**:
  > "Every e-commerce company loses thousands of dollars when subtle backend bugs slip past CI and silently break checkout. An engineer pushes a coupon handling refactor, unit tests pass because mocks were outdated, but real customers hitting the checkout button get a silent HTTP 500. By the time on-call wakes up, hundreds of carts are abandoned. This is FaultLine: autonomous browser reproduction, Meta-powered source repair, and deterministic sandboxed verification."

### Beat 2: The Chaos Trigger & Browser Reproduction (00:30 – 01:15)
- **Visual**: FaultLine Inspector interface; cursor hovering over `[Run Chaos]`.
- **Action**: Click `[Run Chaos]`.
- **Visual**: Inspector updates in real-time. Headless Playwright browser navigates BuggyShop, adds Trail Mug to cart, inputs coupon code, and clicks 'Place Order'. Checkout crashes.
- **Narrative**:
  > "Watch live as FaultLine reproduces the issue. We trigger our checkout chaos scenario. Playwright executes a real browser session—locating accessible DOM elements, placing items in the cart, and attempting purchase. The checkout fails. Immediately, FaultLine captures the DOM snapshot, network trace, and Python traceback. The incident is verified, isolated, and packaged into a structured repair contract."

### Beat 3: Meta AI Model Synthesis & AST Validation (01:15 – 02:00)
- **Visual**: Inspector diff pane updates; unified diff streams in.
- **Narrative**:
  > "FaultLine dispatches the failure trace directly to Meta's instruction model. Instead of blind natural language advice, Meta generates a strict, bounded unified diff targeting the single culprit route file. Before that code can run anywhere near production, FaultLine's AST guard parses the patch, validates syntax, and verifies that no unauthorized files are touched."

### Beat 4: Isolated Execution & Full Regression Proof (02:00 – 02:40)
- **Visual**: Sandbox test runner fires; progress bars turn green.
- **Narrative**:
  > "Now the critical moment: isolated verification. FaultLine applies the candidate patch into a sterile execution sandbox. It immediately re-runs the browser checkout scenario—which now completes with a valid order confirmation—and re-runs the full API regression test suite. Every single business assertion passes: order ID generated, subtotal verified, zero regressions."

### Beat 5: Impact & The Future of Source Repair (02:40 – 03:00)
- **Visual**: Status banner flips to `VERIFIED GREEN`; summary scorecard displayed.
- **Narrative**:
  > "In under 30 seconds, an incident that would have cost thousands in lost GMV and hours of on-call debugging was reproduced, repaired via Meta AI, mathematically validated, and verified green in a real browser. That is FaultLine: moving AI from suggestion to verified source repair. Thank you, and we're ready for your questions."

---

## Contingency & Fallback Plans

- **Meta API Network Flake**: Switch to local offline fallback fixture via UI toggle. Announce: "Switching to our local deterministic model fixture to preserve live verification flow."
- **Browser Port Conflict**: Run `./start.sh --clean` or specify custom ports `API_PORT=8012 WEB_PORT=3012`.
- **Subprocess Freeze**: Kill lingering Chrome processes with `pkill -f playwright`.
