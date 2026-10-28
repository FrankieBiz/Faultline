# FaultLine submission draft

Author: Francis Bisignano (`FrankieBiz`). Indie Developer Track. [Source repository](https://github.com/FrankieBiz/Faultline).

## Elevator pitch

A browser reproduces a checkout crash. Meta proposes a source patch. Independent browser and business checks verify the candidate before it earns a green result.

## The problem

A valid coupon can hide a broken checkout path: customers who leave the field empty receive an HTTP 500. A quick patch can make the error disappear while breaking pricing, validation, or order persistence, and a suggested fix alone does not show which happened.

This project makes that repair claim inspectable. The checkout defect is deliberately seeded, and the scope is a controlled prototype. Add the builder's confirmed firsthand experience here before submitting ([IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md)); do not invent a personal incident, interviews, or customer impact.

Measured on an authored corpus: of six plausible but wrong repairs, a check that the failing request now returns HTTP 201 accepted five. FaultLine accepted none and accepted both correct repairs ([evaluation](EVALUATION.md)).

## What it does

1. **Reproduce:** a real headless Chromium journey hits the seeded HTTP 500, correlated with the backend's own exception log.
2. **Propose:** the configured provider receives the source, the failure, and the checkout's business contract (never the defect or its fix) and returns a schema-bound single-file diff.
3. **Gate:** the patch policy enforces exact paths and source hashes, bounded size, valid syntax, approved imports only, no dynamic execution, and no catch-all exception handlers. Miscounted hunk headers are recounted without altering content.
4. **Verify:** the candidate runs in Linux namespaces inside a cgroup v2 scope whose limits are read back from the kernel. The same browser journey and 27 independent HTTP business checks must pass.
5. **Retry with findings:** if a gate rejects the first proposal, the model receives the failing checks with expected and observed values, or the exact policy error, for one more attempt.
6. **Record:** screenshots, traces, logs, reports, and a checksummed evidence bundle that `tools/verify_bundle.py` re-checks offline. A verified candidate is not a production deployment.

## Meta tooling

The adapter targets the Meta Model API (`muse-spark-1.3` by default) with exact model identity, a startup availability probe, strict structured proposal decoding, and bounded untrusted evidence. Provider identity is derived from the endpoint host, and an attempt is attributed to a provider only when that provider returned a response. Report the provider/model/tokens from a recorded live job when demonstrating Meta use; `scripts/trial_ledger.py --require-provider meta` records that series.

The absent-key deterministic provider is explicitly identified. It exercises the workflow but does not demonstrate Meta generation. Do not describe it as a live Meta run.

## Engineering

- FastAPI control plane with transactional SQLite idempotency, a singleton execution lease, and resumable SSE events.
- Content-addressed exports from detached Git worktrees pinned to a fixture revision.
- Restricted candidate execution with aggregate cgroup v2 limits (512 MiB, no swap, 64 tasks, one CPU), verified per launch and proven by an OOM/task-limit probe before readiness. Trusted browser and HTTP verification run outside the candidate.
- A hash-pinned evaluation corpus and harness, a trial ledger, a static checksummed replay export, and an evidence bundle with an offline consistency checker.

AST checks are policy, not a sandbox. The evidence bundle's digest is a checksum, not a signature. A green suite supports the tested behaviors; it does not prove general production safety or compliance.

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
./scripts/demo-chaos.sh      # Measured walkthrough: preflight, repair under the gates, wrong fixes rejected
./scripts/start-demo.sh      # Start BuggyShop and the FaultLine Inspector
# Open http://127.0.0.1:4000
./scripts/rehearse-demo.sh   # Rehearse a repair job against the seeded fixture
```

Requires Linux, Bubblewrap, cgroup v2 with a systemd user session, Python 3.13, and Node.js 24+. See the root README for model configuration. Performance, impact, and score claims must come from documented measurements; no benchmark or judging result is asserted in this draft.
