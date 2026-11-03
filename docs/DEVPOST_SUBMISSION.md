# FaultLine submission draft

> **Owner TODO before submitting. Remove this block from the pasted copy.**
>
> - [x] **Inspiration.** The section below now paraphrases the firsthand account recorded in [IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md#firsthand-relevance). Keep the two in step; do not add details the account does not contain.
> - [ ] **Video.** Record and link the demo following [the storyboard](VIDEO_STORYBOARD.md).
> - [ ] **User feedback.** Add only real conversations from [IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md). Otherwise keep the "not yet measured" sentence.
> - [ ] **Verification.** Run `make check`, `make browser`, and `make integration` on the submitted commit and record the commit hash.
> - [ ] **Published traces.** The Meta replay on GitHub Pages includes two Playwright trace archives that contain workstation file paths ([review](evidence/2026-10-28-meta-replay-review.md)). Decide whether they stay public.

Author: Francis Bisignano (`FrankieBiz`). Indie Developer Track.

**Links:** [Judge page](https://frankiebiz.github.io/Faultline/) · [Source](https://github.com/FrankieBiz/Faultline) · [Meta repair replay (static, read-only)](https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/index.html) · [Evaluation](https://github.com/FrankieBiz/Faultline/blob/main/docs/EVALUATION.md) · Video: *TODO (owner)*

## Elevator pitch

A browser reproduces a checkout crash. Meta's model proposes a source patch. Independently authored browser and business checks decide whether the candidate earns a green result, while a kernel-limited sandbox confines it. A pre-flight gate gives coding agents and CI the same crawl as an exit code.

## Evidence at a glance

| Claim | What is recorded |
| --- | --- |
| Meta's model repairs the seeded defect repeatedly | Three live `muse-spark-1.3` trials on October 31, 2026, all verified on the first attempt at 44 of 44 assertions, median wall time 10.5 s (10.4 to 12.6 s), cleanup confirmed each time ([ledger](https://github.com/FrankieBiz/Faultline/blob/main/docs/evidence/2026-10-31-controller-ledger-meta.md)). `scripts/trial_ledger.py --require-provider meta` refuses to record any other provider's response as a Meta trial. Scope: one registered scenario. |
| One Meta repair is replayable step by step | One retained controller job on October 28, 2026 ([replay](https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/index.html), [provenance review](https://github.com/FrankieBiz/Faultline/blob/main/docs/evidence/2026-10-28-meta-replay-review.md)). `muse-spark-1.3` returned a one-line patch in 6.9 s (6,863 ms recorded generation time) using 1,569 prompt and 1,685 completion tokens. The baseline failed with the seeded `TypeError`. The candidate passed 44 of 44 assertions, and cleanup succeeded. The whole job took 13.0 s. |
| Verification catches what a symptom check misses | Six plausible but wrong repairs were authored for the seeded defect. A "does the request now return 201" check accepted five of them. FaultLine accepted none, and it accepted both correct repairs ([evaluation](https://github.com/FrankieBiz/Faultline/blob/main/docs/EVALUATION.md#what-verification-catches)). |
| The loop handles defects the model was not told about | Measured only with a labeled **non-Meta** model, DeepSeek `deepseek-v4-pro`. Over two trials, it verified 18 of 20 runs across the seeded defect and nine variants. The gates rejected its two wrong patches. Meta has not yet been run on this corpus. |
| Candidates run contained | Each candidate backend runs in Linux namespaces inside a cgroup v2 scope (512 MiB, no swap, 64 tasks, one CPU), and those limits are read back from the kernel. Readiness enforces adversarial memory-hog (OOM killed, exit -9) and task-hog probes. Both executions in the Meta job recorded verified limits, as did every backend session in both recorded evaluation runs (48 of 48 and 19 of 19). |
| Each platform has a native isolation engine | One interface selects the engine for the host. The control plane and the evaluation harness both get their engine from `select_runtime()`; evaluations no longer hard-code the Linux runtime. Project runs bind the candidate's listener through the same platform seam: an abstract Unix socket on Linux, a file socket on macOS, and loopback TCP on Windows. The CLI's run guard uses the same host detection to report one consistent capability envelope. **Linux:** Bubblewrap namespaces in a cgroup v2 scope, limits read back from the kernel (the engine behind every result on this page). **macOS:** a deny-by-default `sandbox-exec` profile (read-only host paths, loopback-only network) plus per-process POSIX `setrlimit` bounds, reported as unverified because macOS cannot read them back, with a Docker/Podman fallback whose cgroup limits are read back. **Windows:** a Job Object (memory, active-process, and CPU-rate limits, kill-on-close, read back from the job handle) created by a PowerShell wrapper, with `taskkill /T` tree cleanup. The macOS and Windows engines are covered by adapter tests with mocked platform APIs and real POSIX process trees; they have not yet been run natively. |
| Pre-flight gate fails closed cross-platform | `faultline gate` runs natively on macOS, Linux, and Windows (Playwright + Python/TS). It exits 0 only when exploration cleanly completes with zero defects; any discovered defect, timeout, or budget-exhausted exploration exits 1 (`DEPLOYMENT_BLOCKED`), outputting machine-readable JSON, Markdown, or CI annotations with deterministic reproduction trails. |
| The build is verified end to end | `make check` passed 2,735 automated tests (2,255 orchestrator/CLI, 340 backend/root, 140 runner unit; 3 Windows- or PowerShell-only tests skipped on Linux). The browser suites passed 91 (72 Inspector, 2 storefront, 17 showcase), and `make integration` passed 77 isolated tests with skips disallowed: **2,903 tests passing** locally. Lint, strict mypy (zero errors across 115 source files), provenance, and all builds also passed. Hosted Verify runs with unconfined runner user namespaces and Playwright dependencies. |
| Backend isolation findings are tracked openly | An adversarial audit found eight issues (P01–P08). Seven are fixed. Six are confirmed by re-running the audit's executable probes: P01 (WebRTC fallback egress), P02, P03 (cleanup under persistence faults and cancellation), and P05 (catch-all policy) ([record](https://github.com/FrankieBiz/Faultline/blob/main/docs/evidence/2026-11-03-backend-security-hardening.json)), then P04 (cgroup release after a stop timeout) and P07 (snapshot allowlist rejects an unhashed file) ([machine-readable record](https://github.com/FrankieBiz/Faultline/blob/main/docs/evidence/2026-11-03-backend-perfection-edges.json)). P08 (CI coverage of live containment) is fixed in configuration and verified by the same record and a local 77-test integration run; hosted CI has not yet passed it. P06 (host browser quotas) is partly fixed ([audit](https://github.com/FrankieBiz/Faultline/blob/main/docs/audits/BACKEND_PERFECTION_CHECK.md)). |

Three live trials on one scenario are a small sample, not a reliability rate, and a Meta run over the full unfamiliar-defect corpus is still unmeasured. The seeded defect is deliberately simple; the deterministic fallback's patch makes the same change. The contribution is the verification around the patch, not the difficulty of the fix. The authored business checks are what catch a wrong patch; the sandbox confines execution and does not judge correctness.

## Inspiration

A symptom check is not a repair check. In an e-commerce checkout deployment, checkout threw intermittent runtime exceptions whenever a cart omitted a coupon. A rapid hotfix made the endpoint return 200 OK by skipping coupon processing when no coupon was sent. Monitoring dashboards showed zero 500 errors and the incident was declared resolved, but the patch also short-circuited percentage coupon normalization and tax calculation. The margin loss went undetected for nearly five hours, until financial reconciliation flagged the captured totals ([account](https://github.com/FrankieBiz/Faultline/blob/main/docs/IMPACT_EVIDENCE.md#firsthand-relevance)). A 200 OK response is not proof of a correct fix.

We also authored six plausible but wrong repairs for one seeded checkout defect: a naive "does the request now return 201" check accepted five of the six. FaultLine's business oracles rejected all six and accepted both correct repairs ([evaluation](https://github.com/FrankieBiz/Faultline/blob/main/docs/EVALUATION.md#what-verification-catches)). That is a measured property of an authored corpus, and it is why FaultLine pairs sandboxed execution with independent invariant checks: the sandbox contains the candidate, and the checks judge it.

Coding agents (Claude Code, Cursor, Codex) now write and ship fixes, and the same gap applies to them: a patch can make the 500 vanish while it breaks pricing, validation, or order storage, and the tests still pass. We built FaultLine around that gap. A headless browser crawls a running preview and stops at the first unhandled failure with a reproduction trail. Meta's `muse-spark-1.3` proposes a schema-bound source patch. Independently authored browser and business checks then decide whether the candidate is correct, while a kernel-limited sandbox confines it.

## The problem

A valid coupon can hide a broken checkout path. Customers who leave the coupon field empty receive an HTTP 500. A quick patch can make the error disappear while breaking pricing, validation, or order storage. A suggested fix on its own does not show which of these happened.

FaultLine makes that repair claim inspectable. The checkout defect is deliberately seeded, and the scope is a controlled prototype. Customer impact and intended-user demand have not yet been measured.

## What it does

1. **Reproduce:** a real headless Chromium journey hits the seeded HTTP 500, correlated with the backend's own exception log.
2. **Propose:** the configured provider receives the source, the failure, and the checkout's business contract (never the defect or its fix) and returns a schema-bound single-file diff.
3. **Gate:** the patch policy enforces exact paths and source hashes, bounded size (16 KiB diff, 100 changed lines), valid syntax, approved imports only, no dynamic execution, and no catch-all exception handlers. Miscounted hunk headers are recounted without altering content.
4. **Verify:** the candidate runs in Linux namespaces inside a cgroup v2 scope whose limits are read back from the kernel. It must pass the same browser journey (16 checks), 27 independent HTTP business checks, and a combined confirmation check, for 44 assertions in total.
5. **Retry with findings:** if a gate rejects the first proposal, the model receives the failing checks with expected and observed values, or the exact policy error, for one more attempt.
6. **Record:** screenshots, traces, logs, reports, and a checksummed evidence bundle that `tools/verify_bundle.py` re-checks offline. The digest is a checksum, not a signature. A verified candidate is not a production deployment. In the local Inspector, "Apply" writes a verified fix only to the bundled demo store; project repairs stay in the sandbox.

Separately, `faultline gate URL --json` runs the deterministic Playwright crawler (heuristics, not a model) against a running preview and returns one verdict for coding agents and CI. Exit 1 blocks a defect, with a reproduction trail and a fix prompt, and also blocks a crawl that ran out of actions, time, or screens before it finished, or that skipped commit controls it may not click on a hosted preview. Exit 0 means exploration finished with no defect in the flows the crawler reached. It is a bounded smoke signal, not proof of business correctness or complete coverage.

## How Meta's model is used

The adapter targets the Meta Model API (`muse-spark-1.3` by default). It records exact model identity, runs a startup availability probe, decodes proposals against a strict schema, and passes failure evidence to the model as bounded, untrusted input. Provider identity comes from the endpoint host. An attempt is attributed to a provider only when that provider returned a response.

In the retained job, the model explained its patch as: "Empty/null coupon produced None discount causing TypeError on subtotal-discount. Default missing coupon lookup to 0 so absent/empty/whitespace means zero discount, while valid coupons still use integer arithmetic and invalid coupons still 400 before pricing." The replay and its evidence bundle are controller records with matching checksums, not provider-signed attestations.

Without credentials, an explicitly labeled deterministic provider (`deterministic-checkout-v1`, no model call) exercises the workflow. Its runs are never counted as Meta results. Beyond the retained replay, a [trial ledger](https://github.com/FrankieBiz/Faultline/blob/main/docs/evidence/2026-10-31-controller-ledger-meta.md) records 3 of 3 live Meta trials verified on the first attempt (44/44, median 10.5 s) on the same scenario. A Meta run on the unfamiliar-defect corpus remains outstanding.

## How it was built

- FastAPI control plane with transactional SQLite idempotency, a singleton execution lease, and resumable SSE events.
- Content-addressed exports from detached Git worktrees pinned to a fixture revision.
- Restricted candidate execution with aggregate cgroup v2 limits, verified at every launch. Before readiness, an OOM and task-limit probe must pass. The trusted checks (16 browser, 27 HTTP business, 1 confirmation) run outside the candidate, against the sandboxed build.
- A hash-pinned evaluation corpus and harness, a trial ledger, a static checksummed replay export, and an offline evidence-bundle checker.
- A platform isolation interface that picks the engine for the host: Linux Bubblewrap with cgroup v2 (in production use), macOS `sandbox-exec` with POSIX `setrlimit` bounds and a Docker/Podman fallback, and Windows Job Objects set up by a PowerShell wrapper. A single `select_runtime()` drives engine choice for the control plane and the evaluation harness, project runs use the matching platform listener seam, and the CLI shares the same host detection (commit `1575461`). The macOS and Windows engines fail closed and are not yet validated on native hosts.
- 2,240 passing tests: 2,104 from `make check`, 59 browser tests from `make browser`, and 77 from `make integration`, with zero strict-mypy errors across 107 source files.
- Next.js 16 / React 19 Inspector and storefront, and a Playwright runner that writes the report and evidence.

Built with: Python 3.13, FastAPI, Pydantic, SQLite, Next.js, React, TypeScript, Playwright, Chromium, Bubblewrap, systemd and cgroup v2, uv, and the Meta Model API.

## Challenges

- **"Fixed" is not the same as correct.** A wrong patch can make the 500 go away. A 201 check accepted five of six authored wrong repairs; the 27 business checks rejected all six.
- **Models miscount diff hunks.** In 6 of the 18 verified DeepSeek runs, the hunk headers declared wrong line counts. FaultLine recounts them, as `git apply --recount` does, and never changes content. The model's original diff is kept.
- **Tooling can reject a correct patch.** In a second retained Meta job ([`82ac2dcc`](https://frankiebiz.github.io/Faultline/replay/82ac2dcc-e7f9-4ea7-9187-a0c0d79d8ba3/index.html)), the model's first patch made the same change as its verified retry but used a zero-context hunk. It passed policy, but `git apply` refused it in the disposable snapshot. The retry received that error and verified. This was a FaultLine limitation, not a wrong patch. Snapshot application now passes `--unidiff-zero` (commit `a69d705`).
- **Per-process limits do not bound a candidate.** Aggregate memory, task, and CPU limits come from a systemd user scope. Readiness requires a probe to trigger that scope's own OOM kill and task limit.

## Limits

AST checks are policy, not a sandbox. Containment is Linux namespaces plus cgroup limits on a shared kernel. It is not a VM, and there is no seccomp filter or external security review yet. Sandbox repair runs on Linux only; the macOS and Windows isolation adapters have not been exercised natively, and only the pre-flight gate is CI-tested on those systems. Backend audit finding P06 (host browser quotas) is only partly fixed, and P08's required CI integration step has not yet passed on a hosted runner. The Windows engine bounds resources but does not confine the file system or network. The live demo has one registered defect, and the evaluation corpus covers one checkout route. Repairs are single-file diffs, and nothing is deployed automatically. A clean gate covers only the flows the crawler explored. A green suite supports the tested behaviors. It does not prove general production safety or compliance.

## What's next

A Meta run on the unfamiliar-defect corpus, more Meta trials beyond one scenario, defects outside the checkout route, multi-file repairs, a seccomp filter and external sandbox review, and human-reviewed pull requests. Production rollout and monitoring integrations remain future work.

## Reproduce

```bash
make setup
make check
./scripts/demo-chaos.sh      # Measured walkthrough: preflight, repair under the gates, wrong fixes rejected
./scripts/start-demo.sh      # Start BuggyShop and the FaultLine Inspector
# Open http://127.0.0.1:4000
./scripts/rehearse-demo.sh   # Rehearse a repair job against the seeded fixture
```

This requires Linux, Bubblewrap, cgroup v2 with a systemd user session, Python 3.13 via `uv`, and Node.js 24+. See the root README for model configuration. Without `META_API_KEY`, jobs use the labeled deterministic provider. Every result above comes from a committed record. No benchmark result or judging score is claimed.
