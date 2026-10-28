# Agent handoff state

Updated October 28, 2026. Branch: `FrankieBiz/fix-hackathon-assessment-issues` (worktree `brittlestar`), merged to `main`.

## Objective and completed changes

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

- `make check` passed: 220 backend/script tests, 301 orchestrator tests, and 32 runner unit tests, plus lint, strict types, builds, and fixture/corpus provenance.
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
