# FaultLine project status

Updated November 4, 2026 (America/New_York). See [QUALITY_REVIEW.md](QUALITY_REVIEW.md) and [EVALUATION_REPORT_MULTI_MODEL.md](audits/EVALUATION_REPORT_MULTI_MODEL.md) for evidence-based reviews.

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
- Shared judge-page and Inspector redesign with self-hosted, checksummed fonts, recorded event timing, responsive keyboard-accessible controls, reduced-motion handling and generated share images. The recorded HTTP 500 occurs at 2.103 s; diagnosis begins at 2.615 s.

Current recorded verification:
- November 4, 2026: `make check` passed with 340 backend/root tests, 2,291 orchestrator/CLI tests, and 144 runner unit tests (**2,775 automated tests passed**; 26 platform- or tool-gated tests skipped on Linux: 23 backend/root and 3 orchestrator/CLI), plus Ruff lint and format checks, strict mypy across 116 source files (0 errors), Next.js frontend builds, both Python distribution builds, and fixture and corpus provenance.
- November 4: `make browser` passed with 78 Inspector, 2 storefront, and 26 showcase browser tests (**106 browser tests total**).
- November 4: `make integration` passed all 77 required Linux isolation, cgroup, repro, and project tests under `FAULTLINE_REQUIRE_ISOLATED_TESTS=1`, with zero skips.
- Together: **2,958 passing test executions** (2,775 `make check` + 106 browser + 77 integration). The 26 skips are excluded: 21 PowerShell bootstrap tests without `pwsh`, 2 native Windows demo tests and 3 real Windows Job Object tests. Integration reruns its containment subset with skips disallowed.
- Backend Perfection Check findings: P01 (WebRTC fallback egress, 0 UDP bytes on both launch paths), P02, P03 (cleanup under persistence faults and cancellation), and P05 (catch-all AST policy) are fixed and confirmed by re-running the audit's executable probes ([record](evidence/2026-11-03-backend-security-hardening.json)). P04 (cgroup release after a stop timeout) and P07 (snapshot root allowlist), both fixed in `26b032e`, are confirmed by re-running the updated edge probe ([record](evidence/2026-11-03-backend-perfection-edges.json)). P08 (CI coverage of live containment) is fixed in configuration and verified by the same record and a local integration run, but hosted CI has not yet passed its required integration step. P06 is partly fixed: project-mode browser helpers are scoped and artifact output is bounded, but the fixture path's frontend and runner still run unscoped on the host ([debate record](audits/ADVERSARIAL_JUDGING_DEBATE.md#r22-backend-isolation-p01p08-answers-objection-33)).
- Cross-platform runtime unification (`1575461`): the control plane and the evaluation harness both get their isolation engine from `select_runtime()`, so evaluations on macOS or Windows no longer hard-code the Linux runtime. Project runs bind the candidate listener through the platform endpoint seam: an abstract Unix socket on Linux, a file socket on macOS, and loopback TCP on Windows. The CLI's run guard uses the same host detection. Covered by `test_crossplatform_unify.py` with mocked hosts.
- Isolation adapters: Linux Bubblewrap is the production engine. The macOS (`sandbox-exec`) and Windows (Job Object) adapters are wired into CLI capability dispatch and were hardened in `ef54542`: a valid macOS preflight, fork denial, and real rlimit probing; and a suspended-start, checked Windows job assignment with `QueryInformationJobObject` read-back. Neither has been run on its native host yet, and Windows Jobs bound resources but are not a filesystem or network sandbox ([adapter review](../services/repair-orchestrator/app/isolation/ADVERSARIAL_REVIEW.md)). Sandbox repair is Linux-only.

Recorded Meta Model API evidence:
- On October 31, 2026, **3 of 3 live `muse-spark-1.3` trials** verified on the first attempt at 44 of 44 assertions, median wall time 10.5 s (10.4 to 12.6 s), ~3,200 tokens per repair (prompt plus completion; the prompt is ~1,580), with confirmed cleanup ([ledger](evidence/2026-10-31-controller-ledger-meta.md)). The ledger script strictly validates provider identity against the Meta endpoint.
- October 28, 2026 [retained-replay review](evidence/2026-10-28-meta-replay-review.md) verified a step-by-step controller-recorded `muse-spark-1.3` repair (13.0 s end to end, 44/44 assertions passed).

Internal multi-model review (November 1, 2026):
- Multi-model evaluation conducted across DeepSeek-V4.1 (Judge & SRE personas), Llama 3.2 (Systems Auditor), Claude Opus 5.5 (UX & Product Judge), and Codex GPT-6.1 (Systems & Security Architect), documented in [EVALUATION_REPORT_MULTI_MODEL.md](audits/EVALUATION_REPORT_MULTI_MODEL.md). Its scores are self-assessments by models we prompted, not an external judging score, so none is quoted here.

## Access and remaining work

- Default target model: `muse-spark-1.3`; availability depends on the configured account and startup probe.
- Configure `META_API_KEY` privately in the server environment or ignored `.env` to run further live Meta trials. Never paste credentials into chat or commit them.
- Remaining owner work: review the final recording and narration, upload an accessible video and add its URL, confirm the published page and repository revision match the recording, then complete the Indie Developer submission in the [Cerebral Valley portal](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit), as directed by the [official rules](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/waiver). Authenticated form fields and video limits remain unverified. See the explicit placeholders in [DEVPOST_SUBMISSION.md](DEVPOST_SUBMISSION.md) (legacy filename) and [VIDEO_STORYBOARD.md](VIDEO_STORYBOARD.md). No completed upload or submission is claimed here.
- GitHub Pages serves `docs/` from `main` at <https://frankiebiz.github.io/Faultline/>, including the static replays and recorded gate replays. It hosts static files only; the control plane is not exposed.

The official event pages list **November 4, 2026 at 9 PM ET** (November 5 at 02:00 UTC) as the submission deadline, subject to change ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon); rechecked November 4, 2026).

`meta-provided/` remains immutable. All five preserved webinar hashes were verified.
