# FaultLine scripts

- `setup.sh` installs locked Python/Node dependencies and Chromium; also available as `make setup`.
- `start-demo.sh` builds the web applications and trusted runner, then supervises the four loopback services. It refuses occupied ports and retains history. Ctrl+C terminates only this session's process groups.
- `rehearse-demo.sh` submits through the Inspector's server-side proxy and checks actual baseline, candidate, and cleanup results. It identifies deterministic mode explicitly, fails on unsuccessful terminal outcomes, and cancels if its overall deadline expires.
- `reset.sh` asks the running controller to reconcile its owned resources. Active jobs return an error. It preserves durable reports and never overwrites source or kills unrelated processes.
- `evaluate.sh` runs `app.evaluation` over the hash-pinned corpus in `fixtures/evaluation/` with the configured provider (loading `.env` like the launcher), executing every variant and candidate in the isolated runtime with enforced aggregate limits. Arguments pass through, for example `--suite holdout --repeat 2`; results default to `data/evaluations/<UTC time>/`. Also available as `make evaluate`. See `docs/EVALUATION.md`.
- `start-live-demo.sh` runs the public live repair service behind the judge page's "Break it yourself" panel, on `127.0.0.1:${LIVE_DEMO_PORT:-9600}`. It needs only the Python environment and the isolated backend runtime, not Node or browsers. Visitors choose one of the ten corpus defects; each run goes through the evaluation loop in a fresh isolated backend, one job at a time, with per-visitor and daily limits. Finished runs are kept under `data/live-demo/` with a public ledger. Settings are `LIVE_DEMO_*` plus the usual `META_*` provider variables; production pins `LIVE_DEMO_REQUIRE_PROVIDER=meta`. See `deploy/README.md`.
- `configure-live-demo.py` points the judge page at a deployed live service: `uv run --no-project python scripts/configure-live-demo.py https://<host>` checks `/api/live/status` and sets `<meta name="faultline-live-api">` in `docs/index.html`; `--clear` switches the panel off and `--dry-run` shows the change.
- `record-footage.sh` records 1080p demo clips with Playwright: the storefront crash, the judge page's recorded Meta playback, the patch explorer, an Inspector run, and, with `--live <url>`, a live repair. It needs a running stack and never starts or stops services. `assemble-footage.sh` turns the clips into MP4s and a silent rough cut with provenance captions. Output goes to `data/footage/`. See the Footage section of `docs/VIDEO_STORYBOARD.md`.
- `trial_ledger.py` and `export_replay.py` are described below.

Requires `uv`, Node.js 24+, npm, curl, and Linux `setsid`; the rehearsal also uses `jq`. For contained candidate execution, install Bubblewrap and allow unprivileged user namespaces. See the root README.

## Trial ledger

`trial_ledger.py` runs repeated repair jobs through the Inspector's server-side proxy, like the rehearsal, and records what the controller measured for each one. It uses only the Python standard library and never handles the controller credential.

```bash
uv run --project apps/buggyshop-backend --python 3.13 --locked \
  python scripts/trial_ledger.py --trials 5 --require-provider meta --out data/trials/meta.json
```

- `--trials N` (1-50, default 5) runs jobs sequentially. `--deadline SECONDS` (default 190) cancels a job that has not finished, then waits briefly for its terminal record. `--api` overrides `${FAULTLINE_INSPECTOR_URL:-http://127.0.0.1:4000}/api/faultline`.
- Readiness is checked first and before each later trial. The tool refuses to start, or stops, when the runtime is not ready, quarantined, or the model is unavailable. It never calls reset. `--require-provider` refuses a controller reporting another provider, so deterministic runs cannot be recorded as Meta trials.
- Output: the JSON ledger at `--out` and a sibling `.md` summary. It records the readiness snapshot, each trial's job ID, timestamps, state, outcome, cleanup, error code, baseline verdict, attempts (provider, model, tokens, policy result, diff SHA-256 and changed-line count, prior feedback), verification executions, artifact hashes, and a summary. Values the controller did not record are null. The ledger is rewritten after every trial.
- `classification` comes from the provider that actually answered each attempt. The controller records `provider`/`model` only from a returned response and keeps the endpoint it dispatched to as `dispatched_provider`/`dispatched_model`, so a provider error never counts as model output. `meta_model_trials` requires every response to come from `meta`; attempts with no response are reported separately. Deterministic runs are `deterministic_workflow_rehearsals`; responses from several providers are `mixed`; a series with no responses is `no_model_response`.
- Exit status is 0 when every requested trial reached a recorded result, including failures. It is 1 when readiness refused the run or a transport/protocol error stopped it; the partial ledger is still written with `"complete": false`.

What the ledger proves: for the trials it lists, which provider/model each attempt reported, how often the controller verified a repair, which proposals policy rejected, which candidates failed verification, and the recorded latency, token usage, and cleanup. What it does not prove: performance on any defect other than `scripted_checkout_repair`, the quality of a patch beyond its recorded assertions, or reliability beyond the trials run. A handful of trials is a small sample. `data/` is ignored by Git, so copy a reviewed ledger elsewhere if it should be published.

## Static replay export

`export_replay.py` turns one finished job into a self-contained, read-only replay that can be reviewed offline and later hosted as static files (for example, GitHub Pages). It reads the controller through the Inspector's server-side proxy, like the rehearsal, uses only the Python standard library, and never handles the controller credential. It publishes nothing.

```bash
uv run --project apps/buggyshop-backend --python 3.13 --locked \
  python scripts/export_replay.py --latest
```

- `--job JOB_ID` or `--latest` selects the job. Only terminal jobs (succeeded, failed, cancelled, interrupted) export; failed and unresolved jobs are allowed and the page states the recorded outcome plainly.
- `--out DIR` defaults to `replays/<job-id>` (ignored by Git). A nonempty directory is refused unless `--force`, and `--force` only replaces a directory that already holds a replay (`job.json` and `SHA256SUMS`).
- `--omit-traces` leaves Playwright trace archives out; their registered sizes and SHA-256 values stay listed on the page and in `job.json`. `--api` overrides `${FAULTLINE_INSPECTOR_URL:-http://127.0.0.1:4000}/api/faultline`.
- Every artifact must match the size and SHA-256 the controller registered, or the export aborts before writing anything. The replay is written to a staging directory and moved into place only when complete.
- Output: `index.html` (one static page with no scripts, no external requests, a strict CSP, and every recorded value HTML-escaped), `job.json` (the controller's job record, unedited), `artifacts/<artifact-id>.<png|zip|json|log|diff|txt>`, and `SHA256SUMS`, which covers every written file. Check it with `cd replays/<job-id> && sha256sum -c SHA256SUMS`.

What the replay proves: the controller recorded this job's baseline, patch attempts, assertions, events, runtime kind, resource limits, cleanup, and evidence files, and those files are byte-identical to what it registered at capture time. What it does not prove: anything the controller did not record, that a candidate was deployed (a verified candidate is not a production deployment), or that a Meta model was called. The provider banner repeats the identity the attempt recorded, and deterministic runs are labeled as not a Meta model trial.

Review before publishing or committing a replay:

1. Open every screenshot, and the trace archives (`npx playwright show-trace <file>.zip`), and confirm they contain no private data: tokens, cookies, local usernames or paths, or anything outside the seeded storefront. Use `--omit-traces` if traces cannot be reviewed.
2. Read the request logs, backend logs, reports, and proposals for credentials or personal details. The controller redacts configured secrets and authorization or cookie headers, but review anyway.
3. Confirm the provider banner matches the run you intend to present. Do not describe a deterministic, local, or OpenAI-compatible run as Meta inference.
4. Run `sha256sum -c SHA256SUMS` in the replay directory and confirm every line is `OK`.
5. Load `index.html` from the directory and confirm it renders without network access.
