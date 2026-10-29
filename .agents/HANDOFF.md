# Agent handoff state

Updated October 28, 2026 (late evening). Latest: branch `FrankieBiz/judge-review-demo-polish` (worktree `jaeger`), pushed to `main`. The sections after this one describe the earlier `brittlestar` session and still hold.

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
