# Agent handoff state

## October 31: terminal color and port polish (claude-terminal-polish)

- **Color policy.** Every command now goes through `_color_enabled(args)` in `cli.py`. ANSI is off when `NO_COLOR` is non-empty (per no-color.org, an empty value does not count), when stdout is not a TTY, or when `--plain` or `--no-color` is passed. Every subcommand accepts both flags. Legacy commands take a `Palette` (`c = _palette(args)`, all fields empty when color is off) instead of interpolating the module constants. The HUD renderers still take an explicit `color` flag. `listen --no-color` keeps the live redraw (cursor escapes) and drops only color. `listen --plain` now also drops color.
- **Ports.** `--port` resolves to `FAULTLINE_PORT` and then 9000. `--api-port` resolves to `BUGGYSHOP_API_PORT` and then 8000. Commands with `--port`: doctor, status, jobs, diff, apply, and listen (whose default was a hard-coded 9000). Commands with `--api-port`: doctor, apply, and verify. Storefront URLs in apply/verify/revert messages use `BUGGYSHOP_PORT`. `dashboard --port` is still the Inspector port. The Inspector it launches now points at `FAULTLINE_PORT`. Invalid env ports exit with a named error; invalid flags are argparse usage errors (exit 2). `check --port` keeps its own meaning (the live service port substituted for `{port}`).
- **Token discovery.** When several demo stacks run side by side, `_get_control_token(port)` prefers the uvicorn process whose cmdline has `--port <port>`. Without a match it falls back to the old first-found behavior.
- **Tests.** 37 new tests in `test_cli.py` (164 total). Pytest swaps `sys.stdout` after fixture setup, so the fake TTY is patched inside the test body. Positive controls prove the commands do color on a TTY. Before reading `/proc/PID/cmdline`, wait for the child to exec, or it still shows the parent's argv.
- **Verified.** `make check` exit 0: 286 backend/script, 665 orchestrator, and 96 runner unit tests. `make browser` exit 0: 32 Inspector and 1 storefront. Under a real pty, `faultline version` emits `\x1b[1m`, and `NO_COLOR=1`, `--no-color`, `--plain`, and a pipe emit none.

## October 31, 09:50 EDT: usability QA pass (claude-usability-qa)

- **Audit.** Walked the CLI (`version`, `doctor`, `init`, `check`, `dashboard`) and a real isolated stack (ports 8572/9572/3572/4572, data in `/tmp/fl-qa-data`, now stopped; another worktree owned 3000/4000/8000/9000 and was left alone). The Inspector showed no console errors and no horizontal scroll at 1440 or 390 px, and all 15 tab stops have the 2 px focus ring. The palette tokens are consistent; the only literals are the diff tints and the primary-button hover.
- **CLI guide.** New step "Gate live invariants" (`faultline check --port 8000`, `--json`) after doctor. "Probe live" became "Probe the demo store" (`verify` ↔ Check checkout live). The stale "faultline.toml rules have no CLI equivalent" line is gone. The clone note now points at the root `./faultline` launcher instead of the `uv run` prefix. Flags in prose are nowrap `code.flag`.
- **Inspector fixes.** (1) When session 1 gets no response, the engine never sends session 2 (`repro.py` `reproduce`). The result now shows a "Session 2 · Not sent" cell instead of an empty half-panel. (2) The probe dialog marks the rejected field `aria-invalid`, describes it with the error, and focuses it. The JSON error includes the parser's position. Reopening clears the last error but keeps the draft. (3) The store bar no longer references `#store-hint` when no hint renders.
- **Audio.** Cues never play late. No context is created before user activation, and a context that does not resume within 500 ms drops the cue (previously a suspended context queued it until the next click). Contexts use `latencyHint: "interactive"`. Playwright's evaluations count as gestures and its Chromium autoplays, so the test stubs `navigator.userActivation` from real pointer/key events and holds the context suspended through a switch. It failed on the old code and passes now.
- **`faultline check` plain output.** Lines read `PASS id: every assertion passed in both sessions` or `FAIL id: failed the same way in both sessions: <assertion ids>`, plus flaky, fingerprint-mismatch, and no-response forms. `port_required` gets a `--port N` hint. A missing config or bad TOML names the file. JSON reason codes are unchanged.
- **Known, not changed (fixed later by claude-terminal-polish).** `doctor`, `verify`, `apply`, and `status` assumed ports 8000/9000, and legacy commands printed ANSI when piped or with `NO_COLOR`.
- **Verified.** `make check` exit 0: 286 backend/script, 628 orchestrator, 96 runner unit tests, plus lint, mypy, provenance, and builds. `make browser` exit 0: 32 Inspector (31 existing, several extended, plus 1 new audio test) and 1 storefront.

## October 31, 09:18 EDT: visual studio polish (claude-visual-studio child)

- **Palette.** `globals.css` keeps the rule that color is evidence only, with new values: bg `#0A0B0D`, red `#FF4D6A` (failure), emerald `#3DFFA2` (verified), amber `#F59E0B` (degraded or inconclusive), and a new cyan `#2DD4FF` used only for work in flight (current pipeline stage, live check running, readiness being checked). Amber was not reused for "active", so it still means degraded. The faint dot grid is a fixed `body::before` with a fade mask, so scrolling never repaints it. The ineffective Tailwind body classes in `layout.tsx` were removed.
- **CLI guide.** `CliGuide.tsx` is a native `<dialog>` opened from the header or with `?` (ignored in fields and open dialogs). It pairs each terminal step with its dashboard control and has copy buttons. It lists only commands in `build_parser()`. `faultline run` writes to `.faultline/runs` and does not go through the orchestrator, so its runs never appear in the dashboard history; `listen`, `diff`, and `apply` read orchestrator jobs.
- **Rail status.** Each rail item shows a visible status line. Live checks show "checking live…" (cyan) and then the verdict. A repair scenario reflects only the run on screen: in progress (cyan), "verified repair" only when `summarizeJob` verifies the evidence, and otherwise the outcome title (legacy records read "unverified result"). Group headings show the kind and count (`sandbox · 1`, `http · 3`).
- **Sound cues.** `lib/audio-cues.ts` synthesizes them with Web Audio oscillators, with no files and no dependencies. They are off by default; the header toggle (`aria-pressed`, persisted in `localStorage` as `faultline.sound`) enables them, and that click unlocks audio. An alarm (detuned saw falling a tritone) plays for a failing live check or a bad job outcome. A resolution (major-triad arpeggio) plays for a passing check or a verified job. Job cues fire only for a run seen in flight during the session, never when opening a past run.
- **Terminal.** In the `listen` HUD, the running glyph, spinner, and progress bar are cyan, the wordmark is bold, and `doctor` ends with a thin dim rule. `faultline diff` used to print "Verified Candidate Diff" for any job; it now prints the job's recorded outcome (the test was updated to match).
- **Verified.** `make check` exit 0 (286 backend, 533 orchestrator, 96 runner unit). `make browser`: 31 Inspector (27 existing + 4 new: guide, sound, rail live/sandbox status) and 1 storefront passed. Screenshots were checked at 1440 px and 390 px. The worktree needed `npm ci` in `web/inspector-ui`, `tools/browser-runner`, and `apps/buggyshop-frontend`.

## October 31, 09:13 EDT: CLI check platform (codex-cli-platform child)

- **Branch / handoff:** `FrankieBiz/codex-cli-platform`. Implementation child completed local work; coordinator owns review, integration, final verification, and production push.
- **Check contract:** `faultline check --config PATH [--port N] [--repair] [--json] [--plain]` validates schema and every declaration before HTTP requests. It reuses `load_project_config`, `run_check`, and the two-session ReproSpec engine. Every assertion must pass twice; flaky `no_failure`, unreachable targets, malformed/empty configs, unsupported fields/profiles, and missing sandbox prerequisites exit **1**. All checks and prerequisites passing exits **0**. Placeholder URLs require `--port`.
- **Readiness:** `doctor` and `check` share the local prerequisite diagnostic. Tool/cgroup presence is explicitly `unverified`, with `runtime_ready: null`, never a claim of enforced isolation. Missing prerequisites fail the overall check even if HTTP assertions pass. Repair still requires the actual project runner's namespace/cgroup preflight.
- **Repair:** only identical repeated failures escalate. A failed scenario selects its own target; an ordinary rule requires explicit `repair.target_file`. The existing `load_project` / `run_project` pipeline repeats reproduction, policy, verification, and cleanup. No apply call exists in this path. `verified_candidate` requires verified outcome, successful cleanup, and proof bundle; the original live gate remains exit **1**. Transport/flaky failures never invoke repair. Target-form rules now retain JSON bodies in the sandbox oracle too.
- **Output:** `--json` prints one JSON object on stdout; runner chatter is redirected to stderr. Plain check output has no ANSI styling. CLI response excerpts/fingerprints/assertion values are omitted. Parse/validation failures are structured; argparse usage errors retain exit 2.
- **Initialization:** helper module detects Next App/Pages under root/src, package manager/locks (including Yarn classic versus Berry), Vite React/Vue/Svelte and TS/JS, Express/generic scripts or main, Python dependency-declared frameworks and ordinary app assignments, Django, and Flask. Commands use real scripts/modules where found, shell-free `env PORT={port}` for Node, `.venv/bin/python` for requirements-only projects, and TOML-safe quoting. Generated templates validate against settings and live-check schemas; configured Next templates also load through `load_project`. Unknown services fail without creating a fake static-file service. Malformed manifests/syntax errors are graceful.
- **Honest template limits:** `/` is a reviewable starting invariant, not an invented health endpoint. Dependency-only ASGI/Flask fallback entrypoints explicitly require customization. pnpm/Yarn/Bun are supported for local setup/detection, but their binaries are not currently mounted by the sandbox; adapt to installed Node entrypoints before repair. No automatic target guess, dependency install, or missing schema-file reference.
- **Launcher / CI / docs:** root launcher resolves its installation through symlinks, preserves external cwd, forwards all arguments, uses `uv --locked --no-env-file`. New `faultline-ci.yml` uses pinned existing workflow actions, a healthy deterministic local Node service, and real positive/negative HTTP gates. Hosted Linux prerequisite installation is separate from enforcement claims. `docs/CLI_CHECK.md` documents the contract and is linked from README.
- **Verification:** exact requested `uv run --project services/repair-orchestrator --python 3.13 --locked pytest services/repair-orchestrator/tests/test_cli.py`: **125 passed in 9.50s**. `make check`: exit **0**, **286 backend/script**, **626 orchestrator**, **96 runner** tests; lint, strict typing, provenance, frontend/Inspector/runner builds, and both Python distribution builds passed. Locked JS dependencies installed with `npm ci`; no lockfile changes. Local extraction/execution of the CI service/check shell exited **0**, with healthy check exit **0** and false invariant exit **1**; no Ubuntu install command run on Fedora. Real launcher tested from an external temporary project: init exit **0**, missing-config JSON check exit **1**. No fresh model inference requested.
- **Resolved failures / do not repeat:** serializing generated ReproSpec with `exclude_unset=True` omits default `action` discriminator fields and prevents runner admission; retain those fields. Two old initializer tests assumed an invented pytest command and fake empty-directory service; tests now cover conservative behavior. Ruff does not wrap long string literals; those require explicit wrapping. Mypy requires explicit CLI helper re-exports and variable-width tuple annotations.
## October 30: multi-scenario developer dashboard (claude-universal-inspector)

- **Removed toy material.** `AuthoredPreview.tsx` and `lib/chaos-scenarios.ts` (scripted scenarios that never executed) are deleted. Docs that called them "authored previews" now describe live checks.
- **Live invariants.** `app/probes.py` wires the existing `ReproEngine` to real HTTP sessions. Each check sends the request from two fresh `httpx` clients, each with its own `X-Faultline-Case-Id`. It follows no redirects, reads at most 64 KiB, and redacts excerpts. A failure counts only when both sessions fail identically. Sources are `[[invariants.rule]]` in `faultline.toml`, in both the `faultline init` form and the §4.3 `request`/`assert` form (re-read on every request, with per-rule errors), and up to 50 probes registered from the dashboard (new `probes` and `invariant_checks` tables, additive at `user_version` 1).
- **Repair binding is narrow on purpose.** A live failure offers sandbox repair only when the route equals a `REGISTRY` scenario's route, the 5xx error text contains its fingerprint in both sessions, and the origin is `FAULTLINE_LIVE_STORE_URL`. Anything else is labeled detection only. The sandbox job still re-reproduces in isolation before any model call (F1). Do not loosen this into "repair any URL": the engine can rebuild and verify only the pinned fixture.
- **Delivery.** `app/live_store.py` reports `seeded`, `patched` (with a `live-store.json` marker naming the job), or `modified` from file hashes. Apply requires `verified` with cleanup `succeeded` and a seeded store (409 `store_not_seeded` otherwise). Revert restores the seed and clears the marker. Tests monkeypatch `cli.TARGET_FILE`/`REPOSITORY_ROOT`, so they never touch the worktree's real `checkout.py`.
- **Merged with `3c91997` (project runner, pushed mid-session by another session).** The root `faultline.toml` is theirs, unchanged: rules there are appended to the project run's oracle, so do not add dashboard-only rules to it. The dashboard lists `[scenarios.*]` ReproSpecs (request steps) as live checks; `scenario.checkout_api` is the store's live checkout check. Listing and binding use `worker.scenarios`. In project mode (`FAULTLINE_CONFIG` set), a live failure of `scenario.NAME` binds to the runner's own `NAME`, route binding never applies (project scenarios have `route=""`), and the store bar is hidden. `live_store.apply` refuses any job whose scenario is not the checkout executor (`delivery_unsupported`). `start-demo.sh` passes `FAULTLINE_PROJECT_PORT` and `FAULTLINE_LIVE_STORE_URL`, never `FAULTLINE_CONFIG`.
- **Inspector.** Components: scenario rail, `PackPanel`, `InvariantPanel`, `ProbeDialog` (native `<dialog>`; it needs `margin: auto` because Tailwind preflight zeroes it), `StoreBar`, and `JobResult` (extracted unchanged). The proxy allowlists the new routes, and invariant IDs must start alphanumeric so `.`/`..` segments cannot reach other routes. `footage/record.mjs` now clicks "Run sandbox repair".
- **Verified on real stacks** (ports 8471/9471/3471/4471, data in `/tmp`, both stopped, store left seeded).
  - Checkout mode: `scenario.checkout_api` returned 500/201/201/400 live in both sessions and bound to `scripted_checkout_repair`. The deterministic sandbox repair verified 44/44, apply patched the store, the live re-check passed, and revert restored the seed. An uncovered 404 probe read as detection only.
  - Project mode (`FAULTLINE_CONFIG=faultline.toml`): the rail showed the runner's `checkout_api` (14 assertions), and the store bar was hidden. The live failure bound to `checkout_api`. Repair was gated on `meta_credentials_required`. A dashboard detection run through `ProjectRuntime` returned `detected` with cleanup confirmed.
  - Final tree: `make check` exit 0 (286 backend/script, 533 orchestrator, 96 runner unit tests). `npm --prefix web/inspector-ui run check` exit 0. `make browser` passed 27 Inspector and 1 storefront tests.

## October 30: terminal HUD and dashboard commands (claude-terminal-hud)

- `faultline listen [JOB] [--port 9000] [--plain] [--ascii]` streams `/api/faultline/jobs/{id}/events` and redraws the PLATFORM_DX_SPEC §6.3 screen in place. Stage labels match the Inspector's `STAGE_LABEL`. Without a TTY, with `--plain`, or with `CI=true`, it prints the §6.9 one-line-per-stage form. It honors `NO_COLOR` and exits with the §5.2 code for the outcome.
- The SSE events carry no assertion data, so pass/fail marks come from `GET /jobs/{id}` executions. Verification reports are matched to attempts by `attempt_id`. The baseline stops early, so the summary counts assertions passing "in both" separately from those that ran on only one side.
- The progress bar counts settled stages out of 7. It is not a time estimate, because §6.2 forbids percentage bars for work of unknown length.
- A stage that ends into cleanup shows "verdict pending" until the outcome event arrives. A second attempt marks where the first was rejected.
- Dropped streams (including `IncompleteRead`) resume after the last sequence, up to 5 reconnects. SIGTERM and Ctrl+C restore the cursor; the run continues in the engine.
- `faultline dashboard [--port 4000] [--no-open]` opens the Inspector. If nothing serves the port, it starts the built Inspector detached, as `start-demo.sh` does, logs to `$FAULTLINE_DATA_DIR/inspector.log`, and prints the PID. It refuses a port that is serving something else, and it never builds `.next`. `--run` from the spec is omitted because the Inspector has no run deep link yet.
- Verified with a read-only replay of a real `sander` job and a live deterministic run on a temporary isolated controller (port 9471, now stopped), both rendered on a pseudo-terminal. `make check` exit 0 on the pre-merge tree; it was re-run on the merged tree before pushing.
- The pre-existing `test_apply_and_revert_helpers` calls the real `revert_to_seeded()`. It rewrites the worktree's `checkout.py`, which today is a no-op because the file is already seeded.

## October 30: ReproSpec engine (codex-universal-repro)

- Added `services/repair-orchestrator/app/repro.py`: strict versioned ReproSpec,
  eight step primitives, the platform spec's status/JSON assertion matchers,
  and a Playwright adapter for a runtime-provided page.
- `ReproEngine.reproduce` requires identical failed assertions and correlated
  fingerprints across two fresh sessions. `repair` invokes its proposal callback
  only after this gate and both cleanups succeed. Passing/flaky/mismatched runs
  return `no_failure`; execution and cleanup errors block admission.
- The current platform spec's sections 3–5 do not define a ReproSpec wire format;
  this additive module supplies one. JSON examples and all primitive behaviors
  are exercised in `tests/test_repro.py`. The existing worker, CLI, and TypeScript
  oracle remain unchanged. Wiring a sandbox session factory into those paths is
  separate integration work: it must reset application state and browser context,
  enforce network isolation, and confirm cleanup. The adapter does not launch apps.
- Verification: requested pytest command **88 passed**; `make check` exit 0:
  **286 backend/script, 450 orchestrator, 81 runner tests**, lint, strict typing,
  provenance, frontend/Inspector/runner builds, and Python distribution builds.
  Initial `make check` lacked frontend dependencies; locked `npm ci` installs
  resolved that environment issue. No dependency or lockfile changes.

Updated October 29, 2026. Latest: branch `FrankieBiz/judge-review-demo-polish` (worktree `jaeger`), pushed to `main`. The sections after this one describe the earlier `brittlestar` session and still hold.

## October 29: interactive judge experience (jaeger)

Plan and API contract: `.agents/PLAN-live-demo.md`. Backend written by Codex `gpt-6.1-sol`, reviewed and extended by the coordinator.

- **Judge page.** "Play the recorded Meta repair" animates job `3573b32b` at its recorded timing, with a five-step timeline and before/after reveals. "Break it yourself" (`#live`) plants one of the ten corpus defects through the live service and streams events, the diff, the verdict, and a public tally. Deep links use `#run=<id>`. The service URL comes only from `<meta name="faultline-live-api">`, which is empty, so the panel is off and offers the recording. `?live=` accepts loopback URLs only, so nobody can link the official page to another server.
- **Live service.** `services/repair-orchestrator/app/live_demo.py` and `scripts/start-live-demo.sh` wrap `evaluate_holdout` (new optional `on_event` hook). One FIFO worker; per-visitor hourly, queue, and daily limits; salted in-memory client hashes; persisted `runs/*.json` and `ledger.jsonl`; output allowlisted and redacted. Production settings: `LIVE_DEMO_REQUIRE_PROVIDER=meta` (refuses any other provider), `LIVE_DEMO_EXIT_ON_FAILURE=1` (self-restart after an infrastructure failure, and every 5 minutes while starting unavailable), `LIVE_DEMO_TRUST_PROXY=1` behind Caddy.
- **Deploy kit.** `deploy/README.md` (Fedora 44 VM runbook, verified locally with the real unit, Caddy, and restarts, not yet on a cloud VM), `deploy/faultline-live.service`, `deploy/Caddyfile`, `deploy/bootstrap.sh`, `scripts/configure-live-demo.py` (+ `tests/test_configure_live_demo.py`).
- **Verified locally.** A real DeepSeek-backed live run from the judge page planted `coupon_case_sensitive`, and the patch passed the gates and 27/27 checks in 42 s, labeled "not Meta". Mocked UI states: offline, unavailable, rate-limited, queue, retry, and deep link.
- **Owner steps to go live:** create the VM, run `deploy/README.md`, put `META_API_KEY` in `~/.config/faultline/live.env`, run `scripts/configure-live-demo.py https://<host>`, and push. Keep it up through judging (Nov 4–8). Before deleting the VM, run `--clear` and push.

## October 28 judge review (jaeger)

A judge-perspective review of every public surface, then fixes.

- **Public judge page rebuilt.** `docs/index.html` is live at https://frankiebiz.github.io/Faultline/ (Pages builds from `main:/docs`, so pushing to `main` publishes it). The previous version had self-assigned "Pinnacle" rubric scores, a "$4.8M" loss figure, wrong token and latency numbers, invented assertion IDs and order ID, invented corpus diffs, and "cryptographic" wording. The new page uses only recorded data: the Meta replay `3573b32b` (1,569 + 1,685 tokens, 6,863 ms, 44/44, 13.0 s), real corpus diffs and results from `fixtures/evaluation/` and `docs/evidence/2026-10-28-evaluation-deterministic.json`, a per-criterion evidence map with no scores, and an honest limits section. Its patch explorer is plain inline JS (CSP allows inline only). If corpus or replay data changes, update the `PATCHES` array and the facts block by hand.
- **Inspector.** The result now shows a five-step recorded pipeline, a "Patch source" line (deterministic is labeled "not a Meta model trial"), and the diff open by default. Disclosure chevrons, live stage sync, past-run focus, and a "Check again" recovery were added. The proxy now rejects any Host other than 127.0.0.1, localhost, or `*.orca.localhost` (DNS rebinding). The idempotency-key fallback is now a real UUID v4.
- **Controller robustness.** Trusted failures are logged, and `error_details.reason` carries the fixed reason code. Chromium and profile preflight timeouts withhold readiness instead of crashing startup. Reconcile and reset use a 45 s `preflight` budget. Oversized hunk numbers are policy rejections, not `ValueError`. An absolute `PLAYWRIGHT_BROWSERS_PATH` is honored.
- **Judge friction.** `start-demo.sh` lists every occupied port with a working alternate-port example and prints the matching `FAULTLINE_INSPECTOR_URL` rehearsal command. `rehearse-demo.sh` prints only state changes and the raw diff. `make check` builds before testing, so isolated-runtime tests run instead of skipping. The README links the judge page and rendered replays, requires a full clone (the fixture is pinned in history), and notes that the Fedora Playwright warning is harmless. Root `a.md` moved to `docs/evidence/2026-10-28-judge-walkthrough-audit.md`.
- **Docs.** All claims were audited against evidence; 116 links resolve. The Devpost draft was rewritten with owner TODOs. The brief now lists Fireworks at $100 (official page rechecked October 28). `docs/assets/inspector.png` was re-captured from the new UI with a real deterministic run.
- **Not done.** `.env.example` could not be created because a permission rule denies `.env*` writes; the variables are documented in `services/repair-orchestrator/README.md`.

Verification on the final tree: `make check` exit 0 (239 backend, 323 orchestrator with 0 skipped, 81 runner unit, lint, strict types, builds, provenance). `make browser`: 18 Inspector and 1 storefront passed. `make integration`: 13 passed. A live deterministic run through the Inspector UI and `rehearse-demo.sh` both verified 44/44 with cleanup.

Owner-only items remain: video, firsthand account, user conversations, repeated Meta trials and a Meta corpus run (`META_API_KEY`), and whether the replay's published trace archives (workstation paths) stay public. The `petrel` and `sander` worktree databases hold unretained Meta jobs. Those after the isolated-runtime commit could be exported and reviewed as a real trial series; none is cited yet.

## Objective and completed changes (brittlestar)

Acted on every engineering gap in `docs/HACKATHON_SCORE_ASSESSMENT.md`. The 55/100 record is unchanged; its new "Remediation since this assessment" section maps each withheld reason to the action and evidence. No new score was self-assigned.

- **Verifier-guided repair.** The prompt states the checkout contract, not the defect. Rejected attempts send bounded gate findings (failing checks, policy error, rejected diff) to attempt 2. Hunk headers are recounted like `git apply --recount`, and the model's original output is retained. Proposal-contract errors have specific codes. Provider identity comes from the endpoint host. `provider`/`model` are recorded only from responses; the dispatched endpoint is stored separately.
- **Oracle robustness.** Candidate crashes, hangs, and oversized bodies are failed checks, not infrastructure errors.
- **Aggregate limits.** A systemd user scope with cgroup v2 limits (512 MiB, no swap, 64 tasks, one CPU, OOM group kill). Limits are verified from kernel files per launch, an enforcement probe must pass before readiness, and limits are recorded on `ExecutionRecord.resource_limits`. Also: explicit `--unshare-user`, `env -i` (closing a `/proc/1/environ` leak), JSON-only backend logs, and full-length scope prefixes.
- **Evaluation.** A hash-pinned corpus (`fixtures/evaluation/`), harness (`app/evaluation.py`, `scripts/evaluate.sh`), trial ledger (`scripts/trial_ledger.py`), and static replay export (`scripts/export_replay.py`).
- **Documentation.** `docs/EVALUATION.md` and `docs/IMPACT_EVIDENCE.md` are new. README, status, quality review, submission, storyboard, and launch docs are updated. Evidence is in `docs/evidence/`, and a reviewed deterministic replay is in `docs/replay/`.

## Settled decisions

- Earlier decisions still stand: `scripted_checkout_repair`, integer cents, TENOFF/FIFTEEN, a deterministic fallback that is explicitly labeled, no host execution, and no fabricated evidence.
- Only Meta-operated hosts (`meta.ai`, `meta.com`, `llama.com`) may be labeled `meta`. DeepSeek results are harness validation only; never present them as Meta results.
- Aggregate limits are `required` by default. `disabled` must be explicit, and the evaluation also requires `--allow-disabled-limits`.
- Evaluation sessions use the `faultline-evaluation-` scope prefix. Only controller reconciliation releases leftovers, and it is scoped to its own installation.
- Replays committed to the repo omit Playwright traces, because the traces contain local file paths.

## Verification

- `make check` passed: 239 backend/script tests, 320 orchestrator tests, and 32 runner unit tests, plus lint, strict types, builds, and fixture/corpus provenance.
- `make browser`: 9 passed. `make integration`: 13 passed (real Bubblewrap, Chromium, and cgroup tests, including memory and task hogs and log forgery).
- Five deterministic controller jobs verified 44 assertions each.
- Evaluation results are in `docs/EVALUATION.md`.

## Avoid repeated dead ends

- Several worktrees (petrel, gulper, brittlestar) run demo stacks at once. Never `pgrep`/`kill` by script name; verify `/proc/<pid>/environ` ports and cwd. This review accidentally stopped petrel's storefront/API on ports 3000/8000; petrel's Inspector (4000) and controller (9000) kept running.
- Background Python output redirected to a file is block-buffered. An empty log does not mean the process died.
- `deepseek-flash` sometimes adds a stray `"type"` key in `json_object` mode, which the strict contract correctly rejects. Use `deepseek-v4-pro`. Local Ollama on this CPU-only host takes over 80 seconds per proposal.
- Do not rebuild `.next` while a demo stack or isolated run is using it.

## Next evidence needed (owner)

Configure `META_API_KEY`, then run `scripts/trial_ledger.py --trials 5 --require-provider meta` against the running demo and `./scripts/evaluate.sh --suite holdout --repeat 2`. Also needed: the firsthand account and 3–5 user conversations in `docs/IMPACT_EVIDENCE.md`, the final video, and a decision on publishing `docs/replay/` (e.g. GitHub Pages). No deployment, social post, video, or hackathon submission has been made.

## Parallel work preserved from main

Another session added `docs/LONG_TERM_RESEARCH_AND_IDEAS.md` (repository-grounded strategy, 120 catalog ideas, 12 proposed but unexecuted experiments, dated sources). It notes that the official Cerebral Valley page lists a $100 Fireworks offer while `docs/HACKATHON_BRIEF.md` says $25. That session also made backend stderr unbuffered and added a 50 ms drain before baseline log correlation; both are carried forward in the new runtime launch path.

## October 28 audit of the parallel session's additions

The petrel session's commits `f4655ac`–`a168307` were audited and corrected. Details are in `docs/CHRONOLOGICAL_ADJUSTMENTS.md`.

- **Removed:** fake ddmin in repair jobs (hardcoded oracle and payload); the fix-specific AST "defect guard"; impact content with impossible dates (interviews and time trial); and the self-assigned 70 and 93 scores.
- **Fixed:** the evidence bundle (it was never saved; the digest covered only the artifact count; it claimed cryptographic authenticity) and `scripts/demo-chaos.sh` (unconditional fake passes).
- **Added:** an enforced catch-all-exception rule in the patch policy.
- **Settled:** never restore fabricated impact material. Restore only owner-confirmed material with real dates. The ddmin library stays unwired until a real replay oracle exists.
