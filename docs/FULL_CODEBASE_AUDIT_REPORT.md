# Full codebase audit report

> **Provenance.** Claude's static, read-only repository review, produced on November 1, 2026 in the `koi` worktree (branch `FrankieBiz/codebase-product-audit`, commit `53aaa1f`) by eight parallel area audits. The report below is reproduced verbatim except for its closing conversational line. Line references come from the auditors and were not individually re-checked. It is a snapshot: later commits may already address some findings (see "Status since the audit" at the end).

---

## Scope and how this was done

- **Read-only, static review.** I ran no tests, builds, or sandbox paths. Findings come from reading code, configs, docs, and artifacts. The line references are the auditors' and I didn't re-check each one, so verify the high-impact items before acting on them.
- **Eight parallel audits**, one per area: repair orchestrator app, orchestrator and top-level tests, CLI and browser-runner, both frontends and the judge page, backend and fixtures and deploy, build/CI/scripts, docs and agent tooling, and the evidence layer.
- **Repo state:** the worktree is clean, nothing was committed or pushed, and no files were changed. The branch is `FrankieBiz/codebase-product-audit`, not `koi` as the session snapshot said.
- **One housekeeping incident:** an audit wrote a scratch file to `/tmp/_x` despite its read-only instructions. I checked it (a filename listing), confirmed the repo was untouched, and deleted it.

## What Faultline is

It's a local developer tool that proves a web bug is real and checks a proposed fix:

1. A real Chromium session reproduces a failure twice before any model is called.
2. Meta's `muse-spark-1.3` proposes a single-file unified diff.
3. A policy gate rejects unsafe or out-of-scope patches (AST rules, size caps, import allowlist).
4. The candidate runs in a Bubblewrap sandbox with cgroup v2 limits (Linux only).
5. A browser journey and 27 HTTP business checks verify it.
6. A checksummed evidence bundle is written.

It never deploys or changes production code on its own. The developer applies the fix.

The product has several surfaces:

| Surface | What it is | Where |
|---|---|---|
| CLI `faultline` | bash, PowerShell, and cmd launchers for the same commands | repo root |
| Inspector | Next.js studio for demo, repair, and checks | `web/inspector-ui`, port 4000 |
| Pre-Flight Gate | `faultline gate`, a deploy gate for agents and CI with exit codes 0, 1, and 2 | CLI, plus workflows |
| Judge page | static recorded demo on GitHub Pages | `docs/index.html` |
| Live demo API | public rate-limited repair service behind Caddy | `live_demo.py`, port 9600 |

Supported platforms: the gate runs on macOS, Linux, and Windows. Sandboxed repair is Linux-only. `demo` is refused on Windows, and macOS gets explore-only.

## How the repository is organized

| Directory | Tracked files | Contents |
|---|---|---|
| `docs/` | 85 | Status, evaluation, submission drafts, evidence, replays, judge page |
| `services/` | 60 | `repair-orchestrator`: the FastAPI controller, worker, sandbox, CLI, and tests |
| `apps/` | 50 | `buggyshop-backend` (the seeded checkout API) and `buggyshop-frontend` (the storefront) |
| `.agents/` | 42 | Skills, rules, handoff notes, and judging reports for AI agents |
| `fixtures/` | 32 | Healthy and seeded snapshots, manifest, 10-case evaluation corpus |
| `tools/` | 30 | `browser-runner` (TypeScript Playwright CLI), `verify_bundle.py`, social tools |
| `web/` | 26 | `inspector-ui` |
| `scripts/` | 18 | Setup, demo, footage, trial ledger, Orca child helpers |
| `tests/` | 7 | Cross-cutting tests: platform smoke, rehearsal, ledger, replay export |
| `meta-provided/` | 7 | Immutable Meta/Cerebral Valley source material (must not be edited) |
| `shared/` | 6 | Pydantic contracts and scenario registry |
| `.github/` | 4 | Four workflows: Verify, PR gate, pre-flight gate, platform smoke |
| `deploy/` | 4 | Caddy config and systemd unit for the live service |

Root files include `faultline` (plus `.ps1` and `.cmd`), `setup.ps1` and `setup.bat`, `faultline.toml`, a `Makefile` with 14 targets, and `AGENTS.md`, where `GEMINI.md` is a symlink to it.

## Component by component

### 1. Repair orchestrator (`services/repair-orchestrator/app`, about 40 modules)

- **Core flow:** `database.create_job` commits the job, lease, and first event in one transaction. `Worker` then runs a serial 7-stage state machine: baseline (must fail with the checkout fingerprint), up to two patch attempts, policy, snapshot, sandbox activation, verification, and publish. Publishing is atomic, and a job is marked verified only after cleanup is confirmed.
- **Providers:** Meta Chat Completions at `api.meta.ai`, default model `muse-spark-1.3`. Other hosts are labeled `openai-compatible`, and loopback hosts `local`. The audit found no DeepSeek-specific code, even though the evaluation docs cite DeepSeek results. With no API key, a deterministic fallback returns the seeded fix.
- **Isolation:** Bubblewrap with unshared namespaces, dropped capabilities, cleared env, and read-only binds. A systemd scope enforces 512 MiB memory, zero swap, 64 tasks, and one CPU. Readiness depends on a live probe that reads the limits back from `/sys/fs/cgroup`. There is no seccomp filter, which the README acknowledges.
- **Strengths:** idempotent admission, content-addressed evidence with redaction, fail-closed unavailable runtime, and a strict diff parser that recounts hunks.

Findings:

- **High:** project mode allows bare `except` and `except Exception`. The ban applies only to the checkout AST gate, but the README describes it more generally.
- **High:** `ProjectRuntime.execute` ignores `timeout_ms`, and the worker caps runtime timeouts at 20 s, so project budgets like `baseline = 40` never reach the runtime.
- **High:** `POST /api/crawl` is unprefixed, which contradicts the README's claim that all controller routes start with `/api/faultline`.
- **Medium:** trusted frontend startup failures are reported as candidate rejections and consume a model attempt.
- **Medium:** backend logs can reach 256 KiB, but the artifact cap is 64 KiB, so a chatty candidate produces an artifact error instead of a verdict.
- **Medium:** the delivery path in `cli.py` and `live_store.py` doesn't re-run the AST policy. A fallback path can apply unvalidated model output.
- **Medium:** a single HTTP 400, 404, or 422 can permanently disable repair until restart.
- **Medium:** the public live demo reports itself as available unless `LIVE_DEMO_REQUIRE_PROVIDER` is set, and it serves the canned fix in that case.
- **Low:** the CLI falls back to the constant token `dev-insecure-token`, and it passes the full `os.environ` to the Inspector process.
- **Low:** live probes accept any http(s) host, including link-local and metadata addresses.
- **Low:** dead code includes `validate_patch`, `repro.repair`, `HEALTHY_FILE`, and `isLoopbackOrPrivateHost` in the Inspector proxy.

### 2. Orchestrator and top-level tests

- **Coverage:** about 29 test files map closely to the app modules. Strong behavioral tests cover the database, policy, evidence, worker lifecycle with real SQLite and git, and export and ledger scripts.
- **Mock-heavy areas:** `test_cli.py` has about 160 `patch` calls, and `test_repro.py` asserts only call arguments against a mock page.
- **No live network or model calls** in any test. No test is xfail, and no test lacks assertions outright.
- **Biggest gap:** the sandbox containment tests skip unless `FAULTLINE_REQUIRE_ISOLATED_TESTS=1` is set, and no CI workflow sets it. The README and DevPost draft present `make integration` as part of verification, but CI never runs it. The sandbox has therefore never been exercised in automation.
- **Other gaps:** evaluation runs on the host, not isolated. The process supervisor and the relay have no default-run tests. Most shell scripts are untested.
- **Config:** the top-level tests have no pytest config of their own, so the backend's strict settings may not apply to them.

### 3. CLI, browser-runner, and shared

- **Entrypoints** all forward to `cli.py`. The three launchers expose identical subcommands, but platform behavior differs.
- **Browser-runner** is a TypeScript Playwright CLI with two jobs: a checkout oracle and an autonomous crawler. The crawler is the notable one. It scores buttons like "pay", "place order", "send", and "register" highest, and it submits forms with synthetic data. There is no origin allowlist, so pointing `gate`, `scan`, or `crawl` at a live site with real accounts or orders could create real transactions.
- **`shared/`** holds Pydantic contracts consumed by the Python side through an editable install. The TypeScript side hand-copies the contracts, and they have already drifted: TypeScript lacks the `timed_out` verdict that Python defines.
- **`faultline.toml`:** several keys are parsed but never used (`setup_command`, `test_command`, `lockfiles`, `repair.context`). The schema directive on line 1 points to a file that doesn't exist.
- **Install scripts:** `setup.ps1` pipes a remote installer into `Invoke-Expression` and fetches the latest uv release with no checksum. `scripts/setup.sh` pipes `curl` into `sh`. `deploy/bootstrap.sh` pins uv, but `setup.sh` doesn't.
- **Footage:** `record-terminal-flex.mjs` builds a video from a hardcoded transcript, including invented output lines, and writes to a hardcoded path that includes a username.

### 4. Frontends and judge page

- **Inspector** (Next.js 16, React 19, port 4000): one route with a proxy that allowlists about 20 orchestrator endpoints. I confirmed every called route exists and the response shapes match. The user journeys are real: demo, sandbox repair, live checks, apply and revert, and a gate panel.
- **Storefront** (port 3000): deliberately has no bugs of its own. Its README says the frontend stays fixed during repair. The seeded defect is on the backend, at `checkout.py:43`, and the frontend contract matches the backend.
- **Judge page:** static, inline JS, no external resources. Live-API meta tag is empty, so only recorded replays play. It builds its DOM with text nodes, and I found no `dangerouslySetInnerHTML` anywhere. Its CSP allows `unsafe-inline`.
- **Overclaims in copy:**
  - The hero says the agent "clicks every button, fills every form," but the crawl caps at 25 actions.
  - The probe dialog says no credentials or custom headers are sent, but headers are sent.
  - The storefront advertises free shipping and no tax, which the backend doesn't implement.
  - The gate header lists Codex and Devin integrations that don't exist.
- **Gate verdict is recomputed in the browser.** The Pre-Flight panel rebuilds `SAFE_TO_DEPLOY` in TypeScript instead of reading it from the controller, and no test ensures the two agree.
- **Accessibility:** a duplicate `id="gate"`, multiple `h1`s per screen, `role="alert"` on every notice including success, and a job poll that retries forever at 1.5 s even on a permanent 404.

### 5. Backend, fixtures, deploy

- **Backend:** six endpoints. The defect is `discounts.get(coupon_code)` with no default at `checkout.py:43`. A missing, null, empty, or whitespace coupon produces an HTTP 500 with a TypeError. The live route is byte-identical to the seeded variant, and the healthy variant differs by one line.
- **Fixtures:** the holdout has 9 variants plus the registered seed. The adversarial set has 11 patches: 2 correct, 6 wrong, and 3 out-of-policy. Hashes match the manifest, and the pinned commit is an ancestor of HEAD.
- **Holdout integrity problems:**
  - The repair system prompt states every rule the holdout breaks, including trimming, case-folding, zero-default coupons, floor rounding, and unknown-coupon handling. The holdout is kept out of the code path but not out of the prompt. It therefore tests whether the model follows a spec it was given, not whether it generalizes.
  - `cases.json` is committed, and the live status endpoint serves the holdout titles and expected failures.
  - The holdout summary counts the seed as one of its 10 runs, and the deterministic fallback hard-codes the seed's fix. The deterministic result is a rehearsal, not an independent measure.
  - The holdout and the prompt contract were both added in the same commit on the same day, so there is no ordering evidence.
- **Deploy:** Caddy proxies only `/api/live/*` to a loopback service. The budget constants match the README. The worst-case token figure in the deploy docs may be low, since one run can make two model calls.

### 6. Build, CI, scripts, hooks

- **`make check`** runs, in order: lint, typecheck, provenance, frontend, runner, inspector, tests, and build. `make integration` and `make evaluate` are not in any CI workflow.
- **Workflows:** all actions are pinned to commit SHAs, with no `pull_request_target` and no printed secrets. The gate self-test condition in `faultline-gate.yml:99` may always be skipped, which needs a real run to confirm.
- **Git hook:** `.githooks/pre-push` is executable but not active. It takes `git config core.hooksPath .githooks`, which the docs mention but the README doesn't.
- **Scripts:** `.env` is loaded through `eval` in `evaluate.sh` and through `source` in two demo scripts, so anything in `.env` runs as shell.
- **Orca child helper:** `merge` commits the child branch even if the post-merge `make check` fails. `worktree rm --force` can discard uncommitted child work.
- **Finish tool:** `~/.local/bin/agent-finish`, which AGENTS.md mandates, runs `git add -A`, commits, and pushes `HEAD:main` to every remote. It doesn't run `make check` first, and it prints "pushed" even when both pushes fail. Note that it lives outside the repo.

### 7. Docs and agent tooling

- **About 35 docs.** `PROJECT_STATUS.md` is the primary status document. Several are stale: `QUALITY_REVIEW.md`, `HACKATHON_SCORE_ASSESSMENT.md`, and `PLATFORM_DX_SPEC.md`, which describes scripts that don't exist. `SpecV1` is superseded and has no inbound links.
- **Scores conflict:** `HACKATHON_SCORE_ASSESSMENT.md` and the handoff say 55/100 is "the only score," while `PROJECT_STATUS.md` publishes a 77.6 panel consensus.
- **Agent rules conflict:**
  - Codex model: `AGENTS.md` says `gpt-6-astra`, but `orca-child.sh` uses `gpt-6.1-sol`.
  - DeepSeek: `AGENTS.md` recommends `deepseek-v4.1-flash`, but the handoff says flash breaks the JSON contract.
  - Llama: the docs name two different versions.
  - `AGENTS.md` forbids `Co-Authored-By` lines, which conflicts with the attribution rule given for this session. No recent commit has a trailer.
  - `AGENTS.md` says loop mode pushes to main without confirmation.
  - The Orca skill forbids bare `orca` on Linux outside Orca terminals, but `orca-child.sh` tries bare `orca` first.
- **Dangling references:** the voiceover script links to a different worktree's files. Two skill docs cite missing scripts. The gate workflow starts fixtures on port 5050, which is also the AuraScale preset port.

### 8. Evidence and replay

- **Supported:** 44/44 checks in 13.0 s, the 3-of-3 live trials with their wall times, the corpus definition, the 1-of-10 deterministic result, the 18-of-20 DeepSeek result, and the 5-of-6 naive-check comparison.
- **Contradicted:** the README's test totals (1,372 in `make check`, 335 backend, 914 orchestrator, 1,417 overall) don't match the latest committed verification artifact, which shows 1,290, 290, 877, and 123, and 1,335 overall. No committed artifact supports the README's figures.
- **Overstated:** the README says the ledger "refuses to record anything except a Meta provider response." The script checks readiness only before trials, and a mixed series is labeled rather than rejected.
- **Replay provenance:** all three replay jobs are controller-written records with matching internal hashes. None is provider-signed. Job `83d1c403` is a deterministic rehearsal labeled as such.
- **Concerning hash match:** the ledger's diff hash for live Meta trials 1 and 3 equals the diff hash of the deterministic job. Trial 2 and the Meta replay have different diffs. Either the Meta patches coincide with the deterministic fix, or the ledger hashes are computed differently. The job records for those trials aren't committed, so this can't be settled from the repo.
- **Secrets:** none found in the evidence text. Two trace archives may contain workstation paths, which the auditor didn't open.
- **Stale docs:** `EVALUATION_REPORT_MULTI_MODEL.md` names a different repository, says 5 of 6 wrong patches were rejected when FaultLine rejects all six, and cites a README line that doesn't exist. `QUALITY_REVIEW.md` cites a job ID that isn't in the repo.

## Claims versus evidence

| Claim | Verdict | Why |
|---|---|---|
| 44/44 checks in 13.0 s | Supported | Replay job record |
| 3 of 3 live Meta trials verified | Supported, with a caveat | Ledger summary; trial job records not committed; diff-hash match above |
| 10-defect corpus, 5-of-6 naive-check result | Supported | Evaluation JSON |
| Holdout is held out | Partly | Not from the prompt, and public |
| Test counts (1,372 / 1,417) | Contradicted | Latest artifact: 1,290 / 1,335 |
| Ledger refuses non-Meta responses | Overstated | Readiness check only |
| Sandbox is kernel-isolated | Overstated | No seccomp; "not a VM" in README; never tested in CI |
| Live repair is available | Unclear | Judge page says it may be off; empty meta tag |
| Replays omit traces | False | Two trace archives are published |
| "Wrong AI patches" | Misleading | Corpus patches are authored, as the docs say |

## Priorities

1. **Crawler and real sites.** Decide whether the crawler may submit commit-style actions on non-disposable URLs. Add an origin allowlist or an opt-in before anyone runs `gate` against production.
2. **Auto-publishing tools.** `agent-finish` pushes to main without `make check` and reports false success. `orca-child.sh merge` commits even when checks fail. Fix or retire these before they run unattended.
3. **Sandbox evidence.** Run `make integration` in CI on a runner that has bwrap and cgroup delegation, or remove the claim from the docs.
4. **Evaluation integrity.** Decide whether the holdout is meant to be secret. If it is, remove the seed from it and take the rules out of the prompt, then re-run. Confirm the Meta trial patches independently of the deterministic result.
5. **Public claims.** Correct the test counts, the score, the trace statement, the live-service status, and "wrong AI patches." Each contradicts a committed artifact or a document.
6. **Security hygiene.** Remove the constant fallback token and the full-environment pass-through to the Inspector. Pin or checksum the Windows installer. Stop executing `.env` as shell.
7. **Repair-path gaps.** Enforce the AST policy in the delivery path, make project mode apply the same catch-all ban, honor project timeouts, and stop a single 4xx from disabling repair permanently.

## Open questions for you

- Is the live repair service deployed and enabled right now?
- Is the holdout meant to be secret? If so, the seed and the prompt rules need to change.
- Should the crawler be allowed to submit commit actions on any URL?
- Which Codex and DeepSeek model IDs are canonical?
- Which score is current: 55/100 or 77.6?
- Which commit identity applies, and is `Co-Authored-By` allowed?
- Are the two published trace archives meant to stay public?
- Does the locked virtualenv shadow the candidate `app` package?

---

## Status since the audit

- **Priority 1, crawler and real sites: addressed.** `tools/browser-runner/src/crawler.ts` no longer clicks commit-style controls (Place order, Pay, Purchase, Submit, Send, and so on) unless the target origin is disposable: `localhost`, loopback, `0.0.0.0/8`, RFC 1918 private IPv4, or IPv6 loopback/unique-local. External origins require the explicit `allowCommitActions` option (`--allow-commit-actions` on the runner CLI). Hostnames are not resolved, so a public name that points at a private address is still treated as external. Unlabeled submit buttons and checkout steps such as "Continue" are still clicked, and the opt-in is not yet exposed through `faultline gate`, `scan`, or `crawl`.
- **Priority 2, `orca-child.sh merge`: addressed.** The helper refuses to merge into a tree with uncommitted tracked changes, and when `make check` fails after merging `FETCH_HEAD` it runs `git reset --hard` to the pre-merge HEAD and exits 1, so a failing merge is not kept. `agent-finish` lives outside this repository and is unchanged.
