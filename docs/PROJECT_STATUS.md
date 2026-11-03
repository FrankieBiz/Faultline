# FaultLine project status

Updated November 1, 2026 (America/New_York). See [QUALITY_REVIEW.md](QUALITY_REVIEW.md) and [EVALUATION_REPORT_MULTI_MODEL.md](audits/EVALUATION_REPORT_MULTI_MODEL.md) for evidence-based reviews.

## Product and scope

- Entry: Meta Global AI Developer Hackathon, Indie Developer Track.
- Builder: Francis Bisignano (`FrankieBiz`).
- Product: controlled browser QA, cross-platform pre-flight deployment gating, and verified source repair.
- One registered seeded backend checkout defect in the live demo. An authored, hash-pinned evaluation corpus adds nine unfamiliar defects and eleven candidate patches for the same route.
- A successful repair job produces a verified isolated candidate and downloadable evidence. It does not auto-deploy to production. The Pre-Flight Agent Gate (`faultline gate`) provides an immediate, cross-platform (macOS/Linux/Windows) pre-merge or pre-deployment check for coding agents and CI.

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
- Pre-Flight Agent Gate CLI (`faultline gate`) with deterministic Playwright exploration, fail-closed exit codes (0 = safe, 1 = blocked/inconclusive, 2 = usage error), machine-readable output (`--json`, `--markdown`, `--format ci`), and native cross-platform support across macOS, Linux, and Windows.
- Safe setup/start/reconciliation/rehearsal scripts and GitHub verification workflow.

Current recorded verification (November 3, 2026):
- On `f143778`, `make check` passed with 328 backend/root tests, 1,453 orchestrator/CLI tests, and 134 runner unit tests (**1,915 automated tests total**; 26 Windows- or PowerShell-only tests skipped on Linux), plus Ruff lint and format checks, strict mypy across 104 source files (0 errors), Next.js frontend builds, and fixture and corpus provenance. The hosted Verify workflow has failed since `7ec953f` on one test, `test_browser_scope_and_kernel_artifact_production_limits`, which times out on GitHub's Ubuntu runner ([debate record](audits/ADVERSARIAL_JUDGING_DEBATE.md#r26-new-objection-your-ci-is-red-sre-contrarian)).
- `make browser` passed with 52 Inspector and 2 storefront browser tests (**54 browser tests total**).
- `make integration` passed all 77 required Linux isolation, cgroup, repro, and project tests under `FAULTLINE_REQUIRE_ISOLATED_TESTS=1`, with no skips.
- Backend Perfection Check findings: P01 (WebRTC fallback egress, 0 UDP bytes on both launch paths), P02, P03 (cleanup under persistence faults and cancellation), and P05 (catch-all AST policy) are fixed and confirmed by re-running the audit's executable probes ([record](evidence/2026-11-03-backend-security-hardening.json)). P04 (cgroup release after a stop timeout) and P07 (snapshot root allowlist), both fixed in `26b032e`, are confirmed by re-running the updated edge probe ([record](evidence/2026-11-03-backend-perfection-edges.json)). P08 (CI coverage of live containment) is fixed in configuration and verified by the same record and a local integration run, but hosted CI has not yet passed its required integration step. P06 is partly fixed: project-mode browser helpers are scoped and artifact output is bounded, but the fixture path's frontend and runner still run unscoped on the host ([debate record](audits/ADVERSARIAL_JUDGING_DEBATE.md#r22-backend-isolation-p01p08-answers-objection-33)).
- Isolation adapters: Linux Bubblewrap is the production engine. The macOS (`sandbox-exec`) and Windows (Job Object) adapters are wired into CLI capability dispatch and were hardened in `ef54542`: a valid macOS preflight, fork denial, and real rlimit probing; and a suspended-start, checked Windows job assignment with `QueryInformationJobObject` read-back. Neither has been run on its native host yet, and Windows Jobs bound resources but are not a filesystem or network sandbox ([adapter review](../services/repair-orchestrator/app/isolation/ADVERSARIAL_REVIEW.md)). Sandbox repair is Linux-only.

Recorded Meta Model API evidence:
- On October 31, 2026, **3 of 3 live `muse-spark-1.3` trials** verified on the first attempt at 44 of 44 assertions, median wall time 10.5 s (10.4 to 12.6 s), ~3,200 tokens per repair (prompt plus completion; the prompt is ~1,580), with confirmed cleanup ([ledger](evidence/2026-10-31-controller-ledger-meta.md)). The ledger script strictly validates provider identity against the Meta endpoint.
- October 28, 2026 [retained-replay review](evidence/2026-10-28-meta-replay-review.md) verified a step-by-step controller-recorded `muse-spark-1.3` repair (13.0 s end to end, 44/44 assertions passed).

Independent Multi-Model Evaluation Panel (November 1, 2026):
- Multi-model evaluation conducted across DeepSeek-V4.1 (Judge & SRE personas), Llama 3.2 (Systems Auditor), Claude Opus 5.5 (UX & Product Judge), and Codex GPT-6.1 (Systems & Security Architect), documented in [EVALUATION_REPORT_MULTI_MODEL.md](audits/EVALUATION_REPORT_MULTI_MODEL.md). Its scores are self-assessments by models we prompted, not an external judging score, so none is quoted here.

## Access and remaining work

- Default target model: `muse-spark-1.3`; availability depends on the configured account and startup probe.
- Configure `META_API_KEY` privately in the server environment or ignored `.env` to run further live Meta trials. Never paste credentials into chat or commit them.
- Remaining owner work: Recording the 3-minute video voiceover per [VIDEO_STORYBOARD.md](VIDEO_STORYBOARD.md).
- GitHub Pages serves `docs/` from `main` at <https://frankiebiz.github.io/Faultline/>, including the static replays and recorded gate replays. It hosts static files only; the control plane is not exposed.

The official event pages list November 4, 2026 at 9 PM ET as the submission deadline, subject to change ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon); retrieved October 27 and rechecked October 28, 2026).

`meta-provided/` remains immutable. All five preserved webinar hashes were verified.
