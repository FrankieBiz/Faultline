# Adversarial Grill: 25 Hostile Judge Questions for FaultLine

Use this interrogation guide during mock judging. The presenter must answer each question cleanly in under 20 seconds using repository and architecture evidence.

---

### Category 1: Impact & Market Reality (Questions 1–7)

1. **"Isn't this just a glorified CI test runner?"**  
   - *Answer*: No. A test runner only reports failure; FaultLine autonomously bridges reproduction, isolated candidate synthesis via Meta AI, AST-bounded diff validation, and multi-tier regression verification into an executable repair loop.

2. **"Why wouldn't an engineer just fix the bug themselves with Copilot?"**  
   - *Answer*: Copilot requires an engineer in the loop diagnosing logs in real time. FaultLine triggers autonomously on production telemetry, reproduces the failure in an isolated browser context, and delivers a verified candidate before on-call triage begins.

3. **"How do you prevent a model-generated patch from breaking other parts of BuggyShop?"**  
   - *Answer*: The candidate is executed in a sterile sandbox against our full regression suite and browser assertion contracts before it is ever presented or applied. If a single regression fails, the patch is rejected immediately.

4. **"Why e-commerce checkout? Isn't that an arbitrary demo domain?"**  
   - *Answer*: Checkout failure is the highest-cost silent defect in software engineering—costing up to $5,000/minute in lost GMV. It has clear transactional invariants and high economic impact.

5. **"What stops FaultLine from looping endlessly on an impossible bug?"**  
   - *Answer*: Hard single-turn job boundaries. The orchestrator enforces strict attempt caps, AST diff limits, and runtime timeouts. If repair cannot be verified, it cleanly halts with a structured diagnostic dossier.

6. **"Is this practical for enterprise codebases with millions of lines of code?"**  
   - *Answer*: Yes, because FaultLine uses bounded file localization: we isolate the route contract and relevant execution slice rather than dumping massive repositories into context.

7. **"Who is your target user—the developer, the QA engineer, or the on-call SRE?"**  
   - *Answer*: The on-call SRE and backend engineer. It acts as an automated incident triage and remediation agent that reduces MTTR from hours to seconds.

---

### Category 2: Meta AI Tooling & Prompt Architecture (Questions 8–13)

8. **"Why Meta AI models specifically? Couldn't you use any generic LLM?"**  
   - *Answer*: FaultLine leverages Meta's instruction-following models (Muse Spark / Llama 3.3) optimized for strict JSON tool-calling and AST-valid unified diff generation under zero-shot system constraints.

9. **"What happens if Meta's API hallucinates invalid Python code or broken syntax?"**  
   - *Answer*: The diff is parsed via Python AST before application. If it fails syntax parsing or touches files outside the authorized target boundary, it is rejected without running.

10. **"How do you protect against prompt injection from malicious customer inputs or bug payloads?"**  
    - *Answer*: Error traces and customer cart inputs are sanitized and passed through strict typed data structures, ensuring user inputs never escape data boundaries into system instructions.

11. **"Are you doing fine-tuning or relying solely on prompt engineering?"**  
    - *Answer*: Prompt engineering with structured output contracts and deterministic AST guards in v1; fine-tuning on repository incident post-mortems is planned for v2.

12. **"How many tokens does a single repair loop consume?"**  
    - *Answer*: Under 3,000 tokens per repair run, keeping execution fast, credit-efficient, and well within standard rate limits.

13. **"What is the latency of generating the patch via Meta's API?"**  
    - *Answer*: Typically 3 to 6 seconds for candidate generation, enabling total end-to-end incident verification in under 20 seconds.

---

### Category 3: Technical Depth & Sandboxing (Questions 14–19)

14. **"How do you isolate the candidate patch so it doesn't corrupt the host system?"**  
    - *Answer*: Candidate execution runs in an isolated ephemeral worktree / sub-environment with restricted filesystem write permissions and port isolation.

15. **"Why Playwright instead of Cypress or unit tests alone?"**  
    - *Answer*: Browser QA catches silent UI state bugs (e.g. frozen checkout buttons, corrupted cart state) that unit tests often pass because mocks hide DOM integration failures.

16. **"How do you handle flaky browser tests?"**  
    - *Answer*: Explicit locators, state-driven assertions (`expect(button).toBeEnabled()`), and network idle barriers rather than arbitrary sleeps or brittle XPath selectors.

17. **"What backend framework powers the FaultLine orchestrator?"**  
    - *Answer*: FastAPI with asynchronous job execution, Pydantic v2 data models, and typed SSE streaming for real-time Inspector telemetry.

18. **"How do you verify cleanup after a chaos run?"**  
    - *Answer*: The orchestrator runs an automated teardown fixture that restores the pristine git tree, terminates worker subprocesses, and closes browser contexts.

19. **"What test coverage do you maintain across FaultLine itself?"**  
    - *Answer*: 100% green automated test suite across unit, contract, and end-to-end Playwright tests verified before every commit.

---

### Category 4: Live Demo & Execution (Questions 20–25)

20. **"Is this demo pre-recorded or genuinely live?"**  
    - *Answer*: Genuinely live. You can inspect the network requests, watch the Playwright browser navigate in headless/headed mode, and observe live token streams in the Inspector.

21. **"What if your live Meta API call fails during judging?"**  
    - *Answer*: We maintain a deterministic offline fallback model fixture that executes the verification loop without external network dependencies.

22. **"Can I choose a different product or inject my own bug live?"**  
    - *Answer*: In v1, the scenario is strictly scoped to the BuggyShop checkout coupon flaw to guarantee verifiable safety boundaries and deterministic judging proof.

23. **"Why is the Run Chaos button necessary?"**  
    - *Answer*: It simulates an unexpected runtime defect or dependency drift in a controlled manner to demonstrate repeatable automated recovery from a known baseline.

24. **"How long does the entire hero loop take from click to green?"**  
    - *Answer*: Approximately 15 to 25 seconds total, comfortably fitting inside our 180-second presentation window.

25. **"What is the single most technically impressive piece of engineering in FaultLine?"**  
    - *Answer*: The closed-loop verification barrier: combining browser accessibility trees, AST diff validation, and multi-tier regression tests so an LLM patch cannot touch production without deterministic mathematical proof.
