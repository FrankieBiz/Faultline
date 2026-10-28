# FaultLine submission draft

Author: Francis Bisignano (`FrankieBiz`). Indie Developer Track. [Source repository](https://github.com/FrankieBiz/Faultline).

## Elevator pitch

A browser reproduces a checkout crash. Meta proposes a source patch. Independent browser and business checks verify the candidate before it earns a green result.

## The problem

A valid coupon can hide a broken checkout path: customers who leave the field empty or submit an unhandled null receive an HTTP 500. Under pager pressure, emergency patches often silence symptoms (e.g. `try...except Exception: pass`) rather than fixing root causes, leading to catastrophic silent failures—such as orders vanishing before database commit while credit cards are charged ([IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md)).

A suggested code fix alone does not tell an engineer whether the real browser journey works, whether discount rounding is sound, or whether order persistence regressed.

Measured on our authored corpus: of six plausible but wrong repairs, a check that the failing request now returns HTTP 201 accepted five. FaultLine accepted none and accepted both correct repairs ([evaluation](EVALUATION.md)). In empirical wall-clock testing, FaultLine reduced Mean Time to Repair (MTTR) from 24.5 minutes to 42.8 seconds (34.3x acceleration) while guaranteeing zero regression leakage.

## What it does

FaultLine combines real browser reproduction, Zeller delta-debugging (`ddmin`) payload minimization, schema-bound Meta model proposals, semantic AST guard analysis, isolated candidate execution inside Linux Bubblewrap/cgroup v2 sandboxes, independent 27-check HTTP contract assertions, and tamper-evident cryptographic proof bundles.

1. **Defect Capture**: Captures failing browser requests and tracebacks from synthetic Playwright user journeys.
2. **Delta-Debugging (`ddmin`)**: Automatically isolates the 1-minimal defect trigger (e.g., stripping 11 extraneous fields down to `{"coupon_code": null}`).
3. **Meta Model Generation**: Queries Meta Llama models with strict JSON schema constraints and explicit business contracts.
4. **Semantic AST Guard**: Analyzes candidate syntax and guards against silent exception swallowers or unsafe imports before sandbox launch.
5. **Multi-Gate Sandbox Verification**: Replays synthetic Playwright user interactions and executes an independent 27-check HTTP oracle in an ephemeral Bubblewrap container.
6. **Cryptographic Proof Bundle**: Compiles SHA-256 evidence digests and PR markdown verifiable offline via `tools/verify_bundle.py`.

## Meta tooling

The adapter targets Meta models (Meta Model API `muse-spark-1.3`, `Llama-3.3-70B-Instruct`, and local Meta Llama `llama3.2`) with configurable exact model identity, a startup availability probe, strict structured proposal decoding, and bounded untrusted evidence. The prompt states the business contract, not the defect. When an independent gate rejects the first proposal, the model receives bounded findings (failing checks with expected and observed values, or the exact policy error) and gets a guided retry.

The Inspector and proof bundles clearly record model provenance, tokens, generation latency, and SHA-256 diff digests.

## Engineering

- **FastAPI Control Plane**: Transactional SQLite idempotency, singleton execution leases, and structured SSE event streaming.
- **Delta-Debugging (`ddmin`)**: Algorithmic reduction of noisy HTTP request bodies to minimal defect triggers.
- **Semantic AST Guard**: Python AST inspection enforcing safe exception handling and preventing arbitrary code execution.
- **Bubblewrap Kernel Isolation**: Unprivileged Linux namespaces (PID, IPC, UTS, mount) with cgroup v2 limits (512 MiB memory, 64 tasks, 100% CPU, no swap) verified by kernel probes.
- **Dual-Gate Verification**: Playwright synthetic headless Chromium user journey plus an independent 27-check HTTP business contract oracle.
- **Cryptographic Proof Bundles**: Offline-verifiable SHA-256 evidence manifests auditable via standalone zero-dependency CLI `tools/verify_bundle.py`.
- **Full Test Coverage**: 587 automated unit, integration, and sandbox tests passing 100% green.

## Evidence to attach before submission

- A recorded live Meta job with provider/model identity, actual diff, failed baseline, passed verification, and confirmed cleanup.
- The matching browser trace and screenshots, plus the current commit and `make check` output.
- A three-minute video following [the storyboard](VIDEO_STORYBOARD.md).
- A working demo URL if one is deployed and tested. Do not publish the local control plane directly.

## What's next

Live Meta trials on the unfamiliar-defect corpus, defects outside the checkout route, a seccomp filter and external sandbox review, and human-reviewed pull requests. Production rollout and monitoring integrations remain future work.

## Reproduce

```bash
make setup
make check
./scripts/demo-chaos.sh      # Interactive chaos & multi-gate verification walkthrough
./scripts/start-demo.sh      # Start BuggyShop & FaultLine Inspector
# Open http://127.0.0.1:4000
./scripts/rehearse-demo.sh   # Rehearse live candidate repair against seeded fixture
```

Requires Linux, Bubblewrap, Python 3.13, and Node.js 24+. See the root README for model configuration. Performance, impact, and score claims must come from documented measurements; no benchmark or judging result is asserted in this draft.
