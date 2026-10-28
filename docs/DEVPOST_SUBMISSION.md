# FaultLine submission draft

Author: Francis Bisignano (`FrankieBiz`). Indie Developer Track. [Source repository](https://github.com/FrankieBiz/Faultline).

## Elevator pitch

A browser reproduces a checkout crash. Meta proposes a source patch. Independent browser and business checks verify the candidate before it earns a green result.

## The problem

A valid coupon can hide a broken checkout path: customers who leave the field empty receive an HTTP 500. A suggested code fix alone does not tell an engineer whether the original journey works or whether pricing and order persistence regressed.

This project makes that repair claim inspectable. The checkout defect is deliberately seeded, and the scope is a controlled prototype. Add the builder's confirmed firsthand experience here before submitting ([IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md)); do not invent a personal incident or customer impact.

Measured on an authored corpus: of six plausible but wrong repairs, a check that the failing request now returns HTTP 201 accepted five. FaultLine accepted none and accepted both correct repairs ([evaluation](EVALUATION.md)).

## What it does

FaultLine combines real browser reproduction, schema-bound model proposals, exact single-file diff validation, isolated candidate execution, independent regression assertions, and durable evidence. The Inspector shows readiness, actual provider identity, attempts, diffs, execution results, artifacts, and cleanup.

A successful job yields a verified candidate. It does not deploy a production fix. Additional scenarios are labeled previews until real backend fixtures and independent assertions exist.

## Meta tooling

The adapter targets Meta Model API with configurable exact model identity, a startup availability probe, strict structured proposal decoding, and bounded untrusted evidence. The prompt states the business contract, not the defect. When an independent gate rejects the first proposal, the model receives the failing checks with expected and observed values, or the exact policy error, and gets one more attempt. Report the provider/model/tokens from a recorded live job when demonstrating Meta use; `scripts/trial_ledger.py --require-provider meta` records that series.

The absent-key deterministic provider is explicitly identified. It exercises the workflow but does not demonstrate Meta generation. Do not describe it as a live Meta run.

## Engineering

- FastAPI control plane with transactional SQLite idempotency and a singleton execution lease.
- Content-addressed exports from detached Git worktrees pinned to a fixture revision.
- Exact-hunk validation, source hashes, strict paths, syntax checks, and bounded imports.
- Restricted Linux candidate execution in private namespaces and an aggregate cgroup v2 scope whose limits are read back from the kernel and proven by an OOM/task-limit probe, with trusted browser and HTTP verification outside the candidate.
- A hash-pinned evaluation corpus and harness, a trial ledger, and a static checksummed replay export.
- Real Playwright evidence, inert artifact downloads, ordered events, cancellation, deadlines, and cleanup quarantine.

AST checks are policy, not a sandbox. A green suite supports the tested behaviors; it does not prove general production safety or compliance.

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
./scripts/start-demo.sh
# Open http://127.0.0.1:4000
./scripts/rehearse-demo.sh
```

Requires Linux, Bubblewrap, Python 3.13, and Node.js 24+. See the root README for model configuration. Performance, impact, and score claims must come from documented measurements; no benchmark or judging result is asserted in this draft.
