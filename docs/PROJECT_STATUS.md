# FaultLine project status

Updated October 28, 2026 (America/New_York). See [QUALITY_REVIEW.md](QUALITY_REVIEW.md) for the evidence-based review.

## Product and scope

- Entry: Meta Global AI Developer Hackathon, Indie Developer Track.
- Builder: Francis Bisignano (`FrankieBiz`).
- Product: controlled browser QA and verified source repair.
- One registered seeded backend checkout defect in the live demo. An authored, hash-pinned evaluation corpus adds nine unfamiliar defects and eleven candidate patches for the same route. Chaos scenarios in the Inspector remain authored previews.
- A successful job produces a verified isolated candidate and downloadable evidence. It does not deploy to production.

## Implemented and exercised

- Strict backend contracts, integer-cent pricing expectations, namespace-scoped orders, and pinned fixture provenance.
- Transactional admission/idempotency, singleton lease, cancellation, deadlines, reset recovery, and cleanup quarantine.
- Meta adapter with structured proposals, bounded untrusted evidence, provider probe, and explicitly identified deterministic fallback.
- Exact single-file Git patch application, restricted import/AST policy, and content-addressed application exports.
- Linux Bubblewrap runtime: private user/network/PID namespaces, readonly application/interpreter mounts, bounded private tmpfs, no inherited model/control credentials, inherited backend listener, external trusted HTTP/browser verification, and owned-process supervision.
- Aggregate cgroup v2 limits for every candidate backend (512 MiB, no swap, 64 tasks, one CPU, whole-scope OOM kill) in a systemd user scope, read back from kernel files per launch and proven by an OOM/task-limit probe before readiness. Recorded on every execution record.
- Verifier-guided repair: the prompt states the checkout contract rather than the defect; a rejected first attempt sends bounded gate findings to the second; miscounted hunk headers are recounted without altering content; provider identity is derived from the endpoint host and recorded only from actual responses.
- Evaluation harness, trial ledger, and static checksummed replay export.
- Actual Chromium baseline/candidate evidence, correlated server failures, artifact checksums, and cleanup.
- Inspector with measured results, terminal-state handling, reload recovery, truthful legacy-record labeling, binary artifact downloads, replay cursors, responsive layout, and authored preview separation.
- Safe setup/start/reconciliation/rehearsal scripts and GitHub verification workflow.

Verification in this workspace: `make check` passed with 220 backend/script tests, 301 orchestrator tests, and 32 runner unit tests, plus lint, strict typing, builds, fixture and corpus provenance. Nine Inspector browser tests and 13 required isolated-runtime and real cgroup tests passed separately; the latter are included in the orchestrator count.

Five deterministic controller jobs each reproduced the real failure, verified 44 candidate assertions in about five seconds, recorded kernel-verified limits, and confirmed cleanup ([ledger](evidence/2026-10-27-controller-ledger-deterministic.md)). This is workflow/runtime evidence, not a live Meta trial. Evaluation results are in [EVALUATION.md](EVALUATION.md).

## Access and remaining work

- Default target model: `muse-spark-1.3`; availability depends on the configured account and startup probe.
- This review's running stack reports `provider=deterministic`, `model=deterministic-checkout-v1`; no live Meta inference is certified by this review. A non-Meta model (DeepSeek v4-pro, explicitly labeled) was used only to exercise the evaluation harness with real model output.
- Earlier account/model/rate-limit claims lacked retained verification evidence. Treat them as historical unverified notes until checked privately through the account/provider.
- Configure `META_API_KEY` privately in the server environment or ignored `.env` to run a live Meta trial. Never paste credentials into chat or commit them.
- Still needed for a strong entry, all owner-dependent: repeated live Meta trials and a Meta evaluation run (commands in the [score assessment](HACKATHON_SCORE_ASSESSMENT.md#remediation-since-this-assessment)), a firsthand problem account and intended-user feedback ([IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md)), a recorded final video, and review/publication of the read-only replay.
- No public deployment, social post, video publication, or hackathon submission has been performed by this review.

The official event pages list November 4, 2026 at 9 PM ET as the submission deadline, subject to change ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon); retrieved October 27, 2026).

`meta-provided/` remains immutable. All five preserved webinar hashes were verified.
