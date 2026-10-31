# FaultLine: Autonomous SRE & Sandbox-Verified Repair Platform for Web Applications

**A real browser finds the failure. A Meta model proposes a patch. Independent, kernel-contained checks decide whether it works.**

**Judges: start at the [FaultLine judge page](https://frankiebiz.github.io/Faultline/).** It needs no install: play the recorded Meta repair, plant a bug yourself, and try to fool the gates.

---

## The 2 AM checkout failure

It's 2 AM. A shopper fills a cart, skips the coupon field, and clicks **Place order**. The API answers with **HTTP 500**. Nobody is paged, because the homepage is up and the error rate barely moves. Every customer who checks out without a coupon gets the same crash until someone notices in the morning, and each one is a lost order.

FaultLine is built for that kind of bug: a reproducible business failure in code you own. It:

1. reproduces the failure in a real Chromium session,
2. asks Meta's `muse-spark-1.3` for a single-file unified diff,
3. rejects unsafe or out-of-scope patches before they run,
4. executes the candidate inside a Bubblewrap sandbox under kernel-enforced cgroup v2 limits,
5. replays the same browser journey plus independent business assertions, and
6. emits a checksummed evidence bundle.

The output is a **verified candidate with proof**, never a silent production change. FaultLine does not deploy, route live traffic, or claim compliance certification. The developer reviews and applies the fix.

### Why a local developer tool, not a cloud SaaS wrapper

| Concern | Remote SaaS repair bot | FaultLine (local CLI + Inspector) |
| --- | --- | --- |
| Source custody | The whole repository is uploaded to a vendor | The repository stays on your machine. The only outbound data is the bounded model request: one target file plus failing-check evidence, marked as untrusted. The deterministic demo fallback sends nothing. |
| Reaching your app | Needs tunnels or a deployed preview | Talks directly to `localhost` dev servers (Next.js, Vite, Express, FastAPI) |
| Running untrusted patches | Opaque vendor container | Bubblewrap user, PID, IPC, network, UTS, and mount namespaces; read-only code mounts; a cgroup v2 scope whose limits are read back from `/sys/fs/cgroup` before anything runs |
| Proof | A chat message saying "fixed" | Screenshots, Playwright traces, request logs, assertion reports, and a checksummed bundle you can re-verify offline |

---

## What judges can do on the hosted page

The [judge page](https://frankiebiz.github.io/Faultline/) is static and works without cloning anything:

- **Play the recorded Meta repair.** A retained `muse-spark-1.3` controller job replays at its real 13-second timing, from the crashing checkout to 44 of 44 passing checks.
- **Break it yourself.** Plant one of ten corpus bugs and watch the model repair it live in the isolated runtime, under the same gates. The model is never told which bug you picked. When the live service is offline, the page says so and offers the recording instead.
- **Try to fool the gates.** Compare eleven recorded candidate patches under a naive "did it return 201?" check and under FaultLine.
- **Read the raw record.** The [replays](https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/) are static, script-free, and checksummed.

![Inspector after a local run: the failed baseline, the five recorded steps, and 44 of 44 candidate checks passing, with the patch source labeled as the deterministic fallback and not a Meta trial](docs/assets/inspector.png)

*Recorded local workflow evidence. This screenshot shows the deterministic fallback, not a live Meta trial.*

---

## Installation and quickstart

### Prerequisites

| Requirement | Notes |
| --- | --- |
| Linux | Developed and verified on Fedora. **WSL2 is untested.** It would need systemd enabled (`systemd=true` in `/etc/wsl.conf`) and cgroup v2. |
| Bubblewrap (`bwrap`) | Unprivileged user namespaces must work. Fedora: `sudo dnf install bubblewrap`. Debian/Ubuntu: `sudo apt install bubblewrap`. |
| cgroup v2 + systemd user session | Run from a desktop terminal or a user service, not a bare SSH login, so `systemd-run --user` can create a delegated scope. |
| [`uv`](https://docs.astral.sh/uv/) | Provides Python 3.13 and the locked environments. |
| Node.js 24+ and npm | Used by the storefront, the Inspector, and the Playwright runner. |
| Git, curl, `setsid` | Use a **full clone**, not `--depth 1` or a ZIP. The seeded fixture is pinned to a commit in this repository's history. |

FaultLine **fails closed**. If namespaces or enforced aggregate resource limits are unavailable, it refuses to run candidates instead of running them unconfined.

### 1. Clone and set up

```bash
git clone https://github.com/FrankieBiz/Faultline.git
cd Faultline
make setup
```

`make setup` syncs both locked Python environments, runs `npm ci` for the storefront, runner, and Inspector, and installs Playwright Chromium. On Fedora, Playwright prints an "OS is not officially supported" warning and downloads its Ubuntu fallback Chromium. The warning is harmless.

### 2. Check system health

```bash
./faultline doctor
```

`doctor` reports Bubblewrap, cgroup v2, uv, Node.js, `META_API_KEY`, and whether the controller and storefront API are reachable. Finding the tools only means the prerequisites exist. The isolation guarantee comes from the runner's own enforcement preflight, which runs before every candidate launch.

### 3. Launch the demo stack

```bash
./scripts/start-demo.sh
```

Then open the **Inspector at <http://127.0.0.1:4000>**.

| Service | URL |
| --- | --- |
| Inspector (web studio) | http://127.0.0.1:4000 |
| Seeded storefront | http://127.0.0.1:3000 |
| Seeded checkout API | http://127.0.0.1:8000 |
| Repair controller | http://127.0.0.1:9000 |

The launcher binds every service to loopback, generates a session control credential if needed, and keeps job history. If a port is taken, it reports the owner instead of killing it. Ctrl+C stops only the processes it started. To use other ports:

```bash
BUGGYSHOP_API_PORT=8400 FAULTLINE_PORT=9400 BUGGYSHOP_PORT=3400 INSPECTOR_PORT=4400 ./scripts/start-demo.sh
FAULTLINE_INSPECTOR_URL=http://127.0.0.1:4400 ./scripts/rehearse-demo.sh
```

`./scripts/rehearse-demo.sh` drives a full run headlessly. It exits non-zero for failed, cancelled, interrupted, timed-out, or unverified jobs.

### 4. Install the CLI globally

The root `faultline` launcher resolves its own installation through symlinks and keeps your working directory, so one checkout can serve every project:

```bash
mkdir -p ~/.local/bin
ln -sf "$(pwd)/faultline" ~/.local/bin/faultline
```

Then, inside any Next.js, Vite, Express, or FastAPI repository:

```bash
cd ~/code/my-app
faultline init                                             # detect the stack, write a reviewable faultline.toml
# start your dev server, then gate it on its declared HTTP invariants:
faultline check --config faultline.toml --port 3000
faultline check --config faultline.toml --port 3000 --json  # one JSON object on stdout, for CI
```

`init` detects Next.js App/Pages routers, Vite (React/Vue/Svelte), Express and generic Node entrypoints, FastAPI/Starlette, Flask, and Django. It writes a starting invariant for you to review; it doesn't guess a repair target. The sandbox currently mounts Node/npm and uv only, so adapt pnpm, Yarn, or Bun commands to installed Node entrypoints before requesting repair. See [CLI checks, initialization, and CI](docs/CLI_CHECK.md) and [the project runner](docs/PROJECT_RUNNER.md).

### 5. Connect Meta (optional)

```bash
export META_API_KEY=...        # or put it in an ignored .env at the repo root
./scripts/start-demo.sh
```

Optional settings are `META_BASE_URL`, `META_MODEL_NAME` (default `muse-spark-1.3`), `META_REASONING_EFFORT`, `META_RESPONSE_FORMAT`, and `META_TIMEOUT_SECONDS`. See the [orchestrator README](services/repair-orchestrator/README.md#configuration). Credentials stay server-side and never reach browser code or the candidate sandbox.

- **Without a key**, the checkout demo uses a clearly labeled **deterministic fallback**, `deterministic-checkout-v1`. It exercises the full pipeline locally, but **it is not a Meta model trial**, and every record says so.
- **A configured provider that fails** never silently falls back to the deterministic adapter.
- **Project repairs** (`faultline run`, `faultline check --repair`) require a Meta provider and have no fallback.
- **Provider identity comes from the endpoint host**, not from variable names. Only Meta-operated hosts are labeled `meta`, loopback endpoints are `local`, and anything else is `openai-compatible`.

---

## How it works: the 6-step verification engine

**1. Headless browser reproduction.** A fresh, real Chromium session drives the storefront journey through Playwright. The engine intercepts the failing HTTP response and correlates it with observed server failure evidence (for the demo, the 500 and the backend `TypeError` traceback from the allowlisted file). Project scenarios must fail identically in **two** fresh sessions before any model is called, so flaky failures never trigger a repair.

**2. Prompt containment and Meta model repair.** The adapter separates trusted scope from bounded, JSON-encoded **untrusted evidence** (source, logs, findings), and tells the model that instructions inside that evidence are data. The prompt states the checkout's *business contract*, not the defect or its fix. `muse-spark-1.3` returns a schema-bound, single-file unified diff.

**3. AST safety and patch policy.** Before anything runs, the candidate must pass a strict gate:

- Stale source hashes, wrong or extra paths, malformed hunks, and NUL bytes are rejected.
- Size limits: 16 KiB diff, 32 KiB source, 100 changed lines.
- The patched file is parsed (never executed) and rejected for invalid syntax, any bare `import`, `from` imports outside the approved symbol allowlist, dynamic execution or OS capabilities, dunder access, and **catch-all exception handlers** (`except:`, `except Exception`) that would hide the failure instead of fixing it.
- Hunk headers with miscounted line totals are recounted from the hunk body, as `git apply --recount` does. Content is never altered.

**4. Hermetic Bubblewrap sandboxing.** The candidate is applied to a fresh detached worktree from the pinned fixture commit, with application files exported separately from tests and reference solutions. It then runs under `bwrap --unshare-all --unshare-user --die-with-parent --new-session --clearenv --cap-drop ALL`, which gives it private user, PID, IPC, network, UTS, and mount namespaces. The source snapshot, interpreter, and dependencies are mounted read-only, `/tmp` and `/run` are small tmpfs mounts, and the environment is emptied.

**5. Kernel-enforced cgroup v2 limits.** Every candidate launch runs in a `systemd-run` scope with **512 MiB memory, no swap, 64 tasks, and one CPU**. Before execution, the runtime reads `memory.max`, `memory.swap.max`, `pids.max`, and `cpu.max` back from `/sys/fs/cgroup` and refuses to proceed if they don't match. Then the browser journey and **27 independent HTTP business assertions** run against the candidate, keeping real screenshots, Playwright traces, request logs, and reports.

**6. Verifier-guided feedback loop and checksummed proof.** If any gate rejects attempt 1, its structured findings (failing check IDs with expected and observed values, or the exact policy error) go back to the model as untrusted evidence for **a second round**. A job is `verified` only after the controller has confirmed execution identity, artifact hashes, and resource cleanup. If cleanup fails, new jobs are refused until it is resolved. Each verified job stores a checksummed evidence bundle that `tools/verify_bundle.py` re-checks offline. The digest is a checksum, not a signature.

Static AST inspection and Git worktrees are policy and source-management tools; process isolation comes from the runtime. Passing this bounded suite is evidence for the tested behavior, not proof that arbitrary code is safe.

---

## Three ways to use FaultLine

### Terminal power users

| Command | What it does |
| --- | --- |
| `faultline init` | Detects the stack and writes a reviewable `faultline.toml` |
| `faultline check` | Gates a running service on declared HTTP invariants, each measured in two fresh sessions; `--repair` asks for a sandbox-verified candidate without touching source |
| `faultline doctor` | Checks sandbox prerequisites, the Meta key, and service health |
| `faultline run [scenario]` | Freezes tracked source, needs two matching isolated failures, requests a Meta patch, verifies it, and writes a checksummed proof to `.faultline/runs`; `--detect` stops before the model call |
| `faultline listen [job]` | Streams a job's stages as a live HUD with a cyan spinner and progress bar for in-flight work; `--plain` gives one line per stage for CI logs |
| `faultline dashboard` | Opens the Inspector, starting the built app if nothing is serving it |

`status`, `jobs`, `diff`, `apply`, `revert`, `verify`, and `version` round out the CLI. Every command honors `NO_COLOR`, `--no-color`, `--plain`, and non-TTY output, and `--port` / `--api-port` follow `FAULTLINE_PORT` / `BUGGYSHOP_API_PORT`.

### Web Inspector studio (`localhost:4000`)

- **Scenario rail.** Sandbox repair scenarios and live HTTP checks, each with a status line: cyan while work is in flight, emerald only for evidence-verified repairs, red for failures.
- **Live invariant tester.** Runs `[[invariants.rule]]` and `[scenarios.*]` from `faultline.toml` against the running store, in two sessions each.
- **Ad-hoc URL probe dialog.** **New invariant** registers a check against any URL and validates JSON input in place.
- **Procedural Web Audio cues.** Synthesized from oscillators, off by default: an alarm for a failing check and a resolution chord for a verified repair.
- **One-click apply / revert.** **Apply fix** writes a verified, cleanly cleaned-up candidate to the running store's source. **Revert store** restores the seeded defect.
- A built-in CLI guide (press `?`) pairs each dashboard control with its terminal command.

### CI/CD pull request gate

[`.github/workflows/faultline-ci.yml`](.github/workflows/faultline-ci.yml) starts a local service on a GitHub runner and runs `faultline check` against it. A passing invariant must exit 0, and a deliberately false one must exit 1. Copy the pattern into your own repository to block pull requests that break declared HTTP contracts. The hosted runner installs the sandbox prerequisites but makes no sandbox-execution claim and does not request repair.

---

## Evidence and evaluation

### Live Meta trial series: 3 of 3 verified

[`docs/evidence/2026-10-31-controller-ledger-meta.md`](docs/evidence/2026-10-31-controller-ledger-meta.md) was recorded by `scripts/trial_ledger.py --require-provider meta`, which refuses to record anything except a Meta provider response as a Meta trial.

| Trial | Outcome | Attempts | Wall time | Assertions | Cleanup |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | verified | 1 | 10.5 s | 44/44 | succeeded |
| 2 | verified | 1 | 12.6 s | 44/44 | succeeded |
| 3 | verified | 1 | 10.4 s | 44/44 | succeeded |

That is **3 of 3 verified on the first attempt**, with a median wall time of **10.5 s**, no policy rejections, and cleanup confirmed every time. The provider is `meta` and the model is `muse-spark-1.3`. Scope: one registered scenario (`scripted_checkout_repair`).

The retained [Meta repair replay](https://frankiebiz.github.io/Faultline/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/) ([files](docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118), [provenance review](docs/evidence/2026-10-28-meta-replay-review.md)) shows the failed baseline, 44 passing assertions, and cleanup. A [second Meta replay](https://frankiebiz.github.io/Faultline/replay/82ac2dcc-e7f9-4ea7-9187-a0c0d79d8ba3/) records a rejected first proposal and a verified second-round retry.

### 10-defect evaluation corpus

`./scripts/evaluate.sh` runs the same adapter, policy, feedback loop, and oracle over a hash-pinned corpus in [`fixtures/evaluation/`](fixtures/evaluation). Every variant and candidate runs in the isolated runtime. See the [full method and results](docs/EVALUATION.md).

- **What verification catches.** Of six plausible but wrong repairs, a naive "returns HTTP 201" check accepted five. FaultLine accepted **none**, accepted both correct repairs, and rejected all three out-of-policy patches before execution.
- **Unfamiliar defects.** The registered defect plus nine holdout variants cover rounding, normalization, pricing, validation, and persistence, and the model is never told which defect is present. The deterministic fallback repairs only the registered defect (1 of 10), as designed. A non-Meta model (DeepSeek `deepseek-v4-pro`, labeled as such in every record) verified 18 of 20 runs, and the gates rejected its wrong patches in the other two. **A Meta run over the full corpus has not been recorded yet.**

These results describe an authored corpus for one checkout route, not arbitrary applications.

### Test scorecard

| Suite | Tests |
| --- | ---: |
| Backend, scripts, and fixtures (pytest) | 286 |
| Repair orchestrator and CLI (pytest) | 665 |
| Browser runner unit tests | 96 |
| **Unit and integration total** (`make check`) | **1,047** |
| Inspector browser tests (Playwright) | 32 |
| Storefront browser test (Playwright) | 1 |
| **Browser total** (`make browser`) | **33** |
| **All automated tests** | **1,080** |

`make check` also runs Ruff lint and format checks, strict mypy, fixture and corpus provenance, the storefront, runner, and Inspector builds, and both Python distribution builds. `make integration` exercises real isolated Chromium and cgroup enforcement, and `make evaluate` runs the corpus.

---

## Live repair service

`scripts/start-live-demo.sh` powers the judge page's **Break it yourself** panel. A visitor can only choose one of the ten corpus defects; no code or text is accepted. Each run gets a fresh isolated backend, the 27 business checks, a model proposal under the patch policy, re-measurement, and one feedback retry. The service runs one job at a time, enforces per-visitor and daily limits, and requires a Meta provider in production (`LIVE_DEMO_REQUIRE_PROVIDER=meta`). Every finished run is appended to a public ledger, labeled by the provider that answered. [`deploy/README.md`](deploy/README.md) covers hosting it on a small Linux VM.

## Evidence tools

- `scripts/trial_ledger.py` records provider, outcomes, attempts, tokens, latency, assertions, and cleanup for repeated controller jobs.
- `scripts/export_replay.py` exports a finished job as a static, read-only, checksummed replay with no scripts or external requests.
- `tools/verify_bundle.py` re-checks an evidence bundle and its exported artifacts offline.
- `scripts/demo-chaos.sh` is a terminal walkthrough that prints only what it measures in that run.
- Recorded evidence lives in [`docs/evidence/`](docs/evidence/).

## Scope and limits

- Sandbox repair binds only to registered scenarios and configured project scenarios. Live checks work against any URL, but a failure outside a repairable scenario is reported as detection only.
- The authored corpus covers ten defects and eleven candidate patches for one checkout route. Pricing uses integer cents; coupons are `TENOFF` and `FIFTEEN`.
- There is no continuous production monitoring, Sentry or GitHub issue integration, rollout, or automatic production deployment.
- There are no measured customer adoption figures, revenue recovered, recovery SLA, or external judging score.
- Isolation is namespaces plus cgroup limits on a shared kernel, not a VM, and there is no seccomp filter. An internal adversarial review is recorded; an external review is still outstanding.
- Local checks, contained browser execution, and live Meta inference are separate verification claims. See the [quality review](docs/QUALITY_REVIEW.md) for current evidence and remaining work.

## Repository map

| Path | Responsibility |
| --- | --- |
| [apps/buggyshop-backend](apps/buggyshop-backend) | Seeded FastAPI fixture and protected business inputs |
| [apps/buggyshop-frontend](apps/buggyshop-frontend) | Accessible storefront and runtime backend proxy |
| [services/repair-orchestrator](services/repair-orchestrator) | CLI, durable admission, model adapter, patch policy, runtime, cleanup |
| [tools/browser-runner](tools/browser-runner) | Trusted Playwright journey, assertions, and evidence |
| [web/inspector-ui](web/inspector-ui) | Inspector studio: scenarios, live checks, job results, diffs, evidence |
| [shared](shared) / [fixtures](fixtures) | Canonical contracts, scenarios, pinned source provenance, evaluation corpus |
| [scripts](scripts) | Setup, supervised startup, rehearsal, evaluation, trial ledger, replay export, live repair service |
| [deploy](deploy) | Runbook and service files for the live repair service |

## Hackathon materials

[Event brief](docs/HACKATHON_BRIEF.md), [project status](docs/PROJECT_STATUS.md), [score assessment](docs/HACKATHON_SCORE_ASSESSMENT.md), [evaluation](docs/EVALUATION.md), [impact evidence](docs/IMPACT_EVIDENCE.md), [submission draft](docs/DEVPOST_SUBMISSION.md), [video storyboard](docs/VIDEO_STORYBOARD.md), [technical dossier](docs/SUBMISSION.md).

The official event pages list submission on November 4, 2026 at 9 PM ET, subject to organizer changes ([Meta](https://dev.meta.ai/events/global-hackathon), [Cerebral Valley](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon); retrieved October 27, 2026). Preserved webinar materials in `meta-provided/` are immutable.

Built by Francis Bisignano (`FrankieBiz`) for the Meta Global AI Developer Hackathon.
