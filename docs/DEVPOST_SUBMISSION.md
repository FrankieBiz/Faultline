# FaultLine submission draft

> **Owner TODO before submitting. Remove this block from the pasted copy.**
>
> - [ ] **Inspiration.** Write the firsthand account in the section below, or state plainly that there is none ([IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md)). Do not invent an incident.
> - [ ] **Video.** Record and link the demo following [the storyboard](VIDEO_STORYBOARD.md).
> - [ ] **User feedback.** Add only real conversations from [IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md). Otherwise keep the "not yet measured" sentence.
> - [ ] **Verification.** Run `make check`, `make browser`, and `make integration` on the submitted commit and record the commit hash.
> - [ ] **Published traces.** The Meta replay on GitHub Pages includes two Playwright trace archives that contain workstation file paths ([review](evidence/2026-10-28-meta-replay-review.md)). Decide whether they stay public.

Author: Francis Bisignano (`FrankieBiz`). Indie Developer Track.

**Links:** [Judge page](https://frankiebiz.github.io/Faultline/) · [Source](https://github.com/FrankieBiz/Faultline) · [Meta repair replay (static, read-only)](https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/index.html) · [Evaluation](https://github.com/FrankieBiz/Faultline/blob/main/docs/EVALUATION.md) · Video: *TODO (owner)*

## Elevator pitch

A browser reproduces a checkout crash. Meta's model proposes a source patch. Independent browser and business checks decide whether the candidate earns a green result.

## Evidence at a glance

| Claim | What is recorded |
| --- | --- |
| Meta's model repaired the seeded defect under the gates | One retained controller job on October 28, 2026 ([replay](https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/index.html), [provenance review](https://github.com/FrankieBiz/Faultline/blob/main/docs/evidence/2026-10-28-meta-replay-review.md)). `muse-spark-1.3` returned a one-line patch in 6.9 s using 1,569 prompt and 1,685 completion tokens. The baseline failed with the seeded `TypeError`. The candidate passed 44 of 44 assertions, and cleanup succeeded. The whole job took 13.0 s. |
| Verification catches what a symptom check misses | Six plausible but wrong repairs were authored for the seeded defect. A "does the request now return 201" check accepted five of them. FaultLine accepted none, and it accepted both correct repairs ([evaluation](https://github.com/FrankieBiz/Faultline/blob/main/docs/EVALUATION.md#what-verification-catches)). |
| The loop handles defects the model was not told about | Measured only with a labeled **non-Meta** model, DeepSeek `deepseek-v4-pro`. Over two trials, it verified 18 of 20 runs across the seeded defect and nine variants. The gates rejected its two wrong patches. Meta has not yet been run on this corpus. |
| Candidates run contained | Each candidate backend runs in Linux namespaces inside a cgroup v2 scope (512 MiB, no swap, 64 tasks, one CPU), and those limits are read back from the kernel. Both executions in the Meta job recorded verified limits, as did every backend session in both recorded evaluation runs (48 of 48 and 19 of 19). |

The two retained Meta jobs are single runs, not a reliability rate. The seeded defect is deliberately simple; the deterministic fallback's patch makes the same change. The contribution is the verification around the patch, not the difficulty of the fix.

## Inspiration

*TODO (owner): firsthand account, or a plain statement that there is none.*

## The problem

A valid coupon can hide a broken checkout path. Customers who leave the coupon field empty receive an HTTP 500. A quick patch can make the error disappear while breaking pricing, validation, or order storage. A suggested fix on its own does not show which of these happened.

FaultLine makes that repair claim inspectable. The checkout defect is deliberately seeded, and the scope is a controlled prototype. Customer impact and intended-user demand have not yet been measured.

## What it does

1. **Reproduce:** a real headless Chromium journey hits the seeded HTTP 500, correlated with the backend's own exception log.
2. **Propose:** the configured provider receives the source, the failure, and the checkout's business contract (never the defect or its fix) and returns a schema-bound single-file diff.
3. **Gate:** the patch policy enforces exact paths and source hashes, bounded size (16 KiB diff, 100 changed lines), valid syntax, approved imports only, no dynamic execution, and no catch-all exception handlers. Miscounted hunk headers are recounted without altering content.
4. **Verify:** the candidate runs in Linux namespaces inside a cgroup v2 scope whose limits are read back from the kernel. It must pass the same browser journey (16 checks), 27 independent HTTP business checks, and a combined confirmation check, for 44 assertions in total.
5. **Retry with findings:** if a gate rejects the first proposal, the model receives the failing checks with expected and observed values, or the exact policy error, for one more attempt.
6. **Record:** screenshots, traces, logs, reports, and a checksummed evidence bundle that `tools/verify_bundle.py` re-checks offline. The digest is a checksum, not a signature. A verified candidate is not a production deployment.

## How Meta's model is used

The adapter targets the Meta Model API (`muse-spark-1.3` by default). It records exact model identity, runs a startup availability probe, decodes proposals against a strict schema, and passes failure evidence to the model as bounded, untrusted input. Provider identity comes from the endpoint host. An attempt is attributed to a provider only when that provider returned a response.

In the retained job, the model explained its patch as: "Empty/null coupon produced None discount causing TypeError on subtotal-discount. Default missing coupon lookup to 0 so absent/empty/whitespace means zero discount, while valid coupons still use integer arithmetic and invalid coupons still 400 before pricing." The replay and its evidence bundle are controller records with matching checksums, not provider-signed attestations.

Without credentials, an explicitly labeled deterministic provider (`deterministic-checkout-v1`, no model call) exercises the workflow. Its runs are never counted as Meta results. Repeated Meta trials and a Meta run on the unfamiliar-defect corpus remain outstanding.

## How it was built

- FastAPI control plane with transactional SQLite idempotency, a singleton execution lease, and resumable SSE events.
- Content-addressed exports from detached Git worktrees pinned to a fixture revision.
- Restricted candidate execution with aggregate cgroup v2 limits, verified at every launch. Before readiness, an OOM and task-limit probe must pass. Trusted browser and HTTP verification run outside the candidate.
- A hash-pinned evaluation corpus and harness, a trial ledger, a static checksummed replay export, and an offline evidence-bundle checker.
- Next.js 16 / React 19 Inspector and storefront, and a Playwright runner that writes the report and evidence.

Built with: Python 3.13, FastAPI, Pydantic, SQLite, Next.js, React, TypeScript, Playwright, Chromium, Bubblewrap, systemd and cgroup v2, uv, and the Meta Model API.

## Challenges

- **"Fixed" is not the same as correct.** A wrong patch can make the 500 go away. A 201 check accepted five of six authored wrong repairs; the 27 business checks rejected all six.
- **Models miscount diff hunks.** In 6 of the 18 verified DeepSeek runs, the hunk headers declared wrong line counts. FaultLine recounts them, as `git apply --recount` does, and never changes content. The model's original diff is kept.
- **Tooling can reject a correct patch.** In a second retained Meta job ([`82ac2dcc`](https://frankiebiz.github.io/Faultline/replay/82ac2dcc-e7f9-4ea7-9187-a0c0d79d8ba3/index.html)), the model's first patch made the same change as its verified retry but used a zero-context hunk. It passed policy, but `git apply` refused it in the disposable snapshot. The retry received that error and verified. This was a FaultLine limitation, not a wrong patch. Snapshot application now passes `--unidiff-zero` (commit `a69d705`).
- **Per-process limits do not bound a candidate.** Aggregate memory, task, and CPU limits come from a systemd user scope. Readiness requires a probe to trigger that scope's own OOM kill and task limit.

## Limits

AST checks are policy, not a sandbox. Containment is Linux namespaces plus cgroup limits on a shared kernel. It is not a VM, and there is no seccomp filter or external security review yet. The live demo has one registered defect, and the evaluation corpus covers one checkout route. A green suite supports the tested behaviors. It does not prove general production safety or compliance.

## What's next

Repeated Meta trials and a Meta run on the unfamiliar-defect corpus, defects outside the checkout route, a seccomp filter and external sandbox review, and human-reviewed pull requests. Production rollout and monitoring integrations remain future work.

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
