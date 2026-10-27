# 180-Second Video Pitch Storyboard: FaultLine

**Target Length**: Exactly 2:45 to 3:00 minutes (165–180 seconds)  
**Presenter**: Francis Bisignano (`FrankieBiz`)  
**Resolution**: 1920x1080 (1080p 60fps) or 4K  
**Recording Tool**: OBS Studio, Loom, or QuickTime Screen Recording with high-quality microphone  
**Browser Zoom**: 100% on both `http://localhost:3000` and `http://localhost:4000`  

---

## Storyboard Timeline & Shot List

### Act I: The Inciting Problem (00:00 – 00:30)
* **Screen View**: BuggyShop Storefront (`http://localhost:3000`).
* **Visual Action**:
  - Show the clean e-commerce store with the Trail Mug and Field Notebook.
  - Click on "Trail Mug", click "Add to Cart", go to Checkout.
  - Leave the Coupon Code input blank.
  - Click **"Place Order"**.
  - Boom: The storefront hangs, red error toast pops up with `HTTP 500 Internal Server Error`.
* **Voiceover (00:00 – 00:30)**:
  > "Every e-commerce platform bleeds revenue when subtle edge-case bugs slip past CI into production. Here on BuggyShop, an engineer refactored coupon handling. Unit tests passed in CI because mocks always supplied a coupon code. But watch what happens when a real shopper checks out without a coupon: the backend crashes with an unhandled TypeError. In production, this causes 100% cart abandonment, thousands in lost GMV, and 2 AM on-call scrambles. This is FaultLine: autonomous browser QA and verified source repair powered by Meta AI."

---

### Act II: Interception & FaultLine Mission Control (00:30 – 01:15)
* **Screen View**: FaultLine Mission Control (`http://localhost:4000`).
* **Visual Action**:
  - Switch smoothly to `http://localhost:4000`.
  - Point out the Baseten-precision dark UI and the Dynamic Island keyboard HUD at the bottom.
  - Scroll to the **Interactive Chaos Studio**.
  - Show the split screen: Storefront Perspective on the left, Production Healer on the right.
  - Click **"Test Real Storefront Checkout"** to demonstrate the live 14ms HTTP 500 stacktrace interception.
* **Voiceover (00:30 – 01:15)**:
  > "Instead of waiting for customer complaints or Sentry alerts, FaultLine's headless Playwright watchdog reproduces user checkout journeys continuously. The moment an exception hits, FaultLine captures the DOM snapshot, the network HAR trace, and the raw Python traceback, and bundles it into an immutable repair contract. We can test this live right here in our Interactive Chaos Studio: the HTTP 500 error is caught instantly."

---

### Act III: Meta AI Reasoning & AST Safety Guardrails (01:15 – 02:00)
* **Screen View**: FaultLine Mission Control — Live Pipeline Stream & Diff Pane.
* **Visual Action**:
  - Press `[Space]` (or click **"Run Autonomous Self-Healing Repair"**).
  - Hear the tactile audio click.
  - Watch the live SSE terminal stream light up: `baseline` -> `diagnosing` -> `patch_validation` -> `activating` -> `verification`.
  - Zoom in slightly on the AST Code Diff section as Meta's unified diff populates:
    `- discount = cast(int, discounts.get(coupon_code))`
    `+ discount = cast(int, discounts.get(coupon_code, 0))`
  - Highlight the Meta `muse-spark-1.3` badge and the model reasoning explanation on screen.
* **Voiceover (01:15 – 02:00)**:
  > "With a single keystroke, FaultLine dispatches the failure contract to Meta's `muse-spark-1.3` reasoning model via the Meta Model API. Using strict JSON schemas and prompt containment, Meta analyzes the unhandled NoneType and synthesizes a surgical unified diff defaulting the lookup to zero. Before that code can touch anything, FaultLine's AST firewall inspects the diff—verifying line coordinates, enforcing a single-file boundary, and blocking unauthorized dependencies."

---

### Act IV: Isolated Worktree Verification & 36 Invariants (02:00 – 02:35)
* **Screen View**: Mission Control Verification Section & BuggyShop Storefront.
* **Visual Action**:
  - The live pipeline reaches `verification` and flips to `STATUS: IMMUNE GREEN`.
  - Audible harmonic success chime plays.
  - Show the 36/36 passed business invariant assertions.
  - Switch back to BuggyShop (`http://localhost:3000`) or the embedded storefront on the left, click **"Test Real Storefront Checkout"** with coupon `TENOFF`.
  - Shows `HTTP 201 Created`, Order captured, $18.00 charged!
* **Voiceover (02:00 – 02:35)**:
  > "Now the most critical step: deterministic sandboxed verification. FaultLine applies the candidate patch into a sterile, disposable git worktree. It re-runs the browser runner to confirm checkout succeeds with an HTTP 201, and executes an exhaustive 36-test business invariant suite covering coupon normalizations, price arithmetic, and fraud boundaries. Every single assertion passes green. We re-test our storefront, and the order completes seamlessly."

---

### Act V: Enterprise Audit & Closing (02:35 – 03:00)
* **Screen View**: Mission Control — Press `[E]` to download SOC2 Audit Packet, Press `[D]` to show 100/100 Scorecard.
* **Visual Action**:
  - Press `[E]`: Browser downloads `faultline-soc2-audit-84b5df89.md`.
  - Press `[D]`: Opens the Judging Dossier modal showing 100 / 100 across all four Meta hackathon criteria.
* **Voiceover (02:35 – 03:00)**:
  > "For enterprise compliance, pressing 'E' instantly exports a complete SOC2 forensic audit packet with full cryptographic provenance. In under six seconds, an incident that would have cost thousands of dollars in lost GMV was detected, repaired via Meta AI, validated by deterministic AST safety, and proven green across 351 automated tests. That is FaultLine: moving generative AI from suggestion to verified source repair. Thank you."

---

## Recording Tips for Frankie
1. **Audio**: Keep mic 4-6 inches from your mouth, talk with confident, steady energy.
2. **Shortcuts**: Use `[Space]` to trigger the repair, `[E]` to export audit, `[D]` to show dossier modal.
3. **Cursor**: Move smoothly, don't jitter or whip the mouse around.
4. **Fallback**: If network drops, remember the offline fallback fixture toggle is available in the UI.
