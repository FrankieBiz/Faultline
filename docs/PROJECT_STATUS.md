# FaultLine project status

Updated October 28, 2026 (America/New_York). See [QUALITY_REVIEW.md](QUALITY_REVIEW.md) for the evidence-based review.

## Product and scope

- Entry: Meta Global AI Developer Hackathon, Indie Developer Track.
- Builder: Francis Bisignano (`FrankieBiz`).
- Product: controlled browser QA and verified source repair.
- One registered seeded backend checkout defect in the live demo. An authored, hash-pinned evaluation corpus adds nine unfamiliar defects and eleven candidate patches for the same route. The Inspector's authored chaos previews were removed on October 30, 2026; it now live-checks HTTP invariants from `faultline.toml` and any URL, and repairs only failures the registered scenario covers.
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
- Inspector with measured results, terminal-state handling, reload recovery, truthful legacy-record labeling, binary artifact downloads, replay cursors, responsive layout, a scenario rail (sandbox repair, `faultline.toml` rules, and added probes), live two-session HTTP checks, and guarded live-store apply/revert.
- Safe setup/start/reconciliation/rehearsal scripts and GitHub verification workflow.

Last recorded verification (October 28, before the judge-walkthrough commits): `make check` passed with 239 backend/script tests, 320 orchestrator tests, and 32 runner unit tests, plus lint, strict typing, builds, and fixture and corpus provenance. Nine Inspector browser tests passed separately, as did 13 required isolated-runtime and real cgroup tests, which are included in the orchestrator count. Later commits added tests. At commit `a24e890`, the suites collect 239 backend/script, 321 orchestrator, and 48 runner unit tests, plus 14 Inspector and 1 storefront browser tests (`make browser`) and the same 13 isolation tests. The full suites have not been rerun at that commit for this document; rerun them before quoting pass counts.

Five deterministic controller jobs each reproduced the real failure, verified 44 candidate assertions in about five seconds, recorded kernel-verified limits, and confirmed cleanup ([ledger](evidence/2026-10-27-controller-ledger-deterministic.md)). This is workflow/runtime evidence, not a live Meta trial. Evaluation results are in [EVALUATION.md](EVALUATION.md).

## Access and remaining work

- Default target model: `muse-spark-1.3`; availability depends on the configured account and startup probe.
- The earlier runtime review used `provider=deterministic`, `model=deterministic-checkout-v1`. The October 28 [retained-replay review](evidence/2026-10-28-meta-replay-review.md) checked a controller-recorded `meta` / `muse-spark-1.3` repair: 44 assertions passed and cleanup succeeded. No fresh Meta call was made by that review; checksums establish consistency, not provider-signed authenticity. A non-Meta model (DeepSeek v4-pro, explicitly labeled) was used only to exercise the evaluation harness with real model output.
- Earlier account/model/rate-limit claims lacked retained verification evidence. Treat them as historical unverified notes until checked privately through the account/provider.
- Configure `META_API_KEY` privately in the server environment or ignored `.env` to run further live Meta trials. Never paste credentials into chat or commit them.
- Still needed for a strong entry, all owner-dependent: repeated live Meta trials and a Meta evaluation run (commands in the [score assessment](HACKATHON_SCORE_ASSESSMENT.md#remediation-since-this-assessment); the retained Meta jobs are single runs, not a series), a firsthand problem account and intended-user feedback ([IMPACT_EVIDENCE.md](IMPACT_EVIDENCE.md)), a recorded final video, and a decision on the published Meta replay's two trace archives, which contain workstation paths ([review](evidence/2026-10-28-meta-replay-review.md)).
- GitHub Pages serves `docs/` from `main` at <https://frankiebiz.github.io/Faultline/>, including the static replays (checked October 28, 2026). It hosts static files only; the control plane is not exposed. No social post, video publication, or hackathon submission is recorded in this repository.

The official event pages list November 4, 2026 at 9 PM ET as the submission deadline, subject to change ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon); retrieved October 27 and rechecked October 28, 2026).

`meta-provided/` remains immutable. All five preserved webinar hashes were verified.
