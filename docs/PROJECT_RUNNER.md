# Run a repository repair

`faultline run [scenario_name]` runs a configured development service, reproduces an assertion failure in two fresh isolated sessions, requests a Meta repair, and checks the candidate against the same immutable reproduction. It retains the reports, actual browser evidence, provider output, diff, and checksummed proof. It leaves your working source unchanged.

This is a configurable runner for a local repository. It does not claim that every application will run without configuration, or that passing your reproduction proves every behavior correct. The existing Inspector demo remains available with its dedicated checkout regression suite.

## From this checkout

Run `make setup` first. Linux Bubblewrap, a working systemd user session with cgroup v2, Node, and Playwright Chromium are required. Candidate launches always require verified limits: 512 MiB memory, no swap, 64 tasks, and one CPU. The browser uses Chromium's sandbox and permits requests only to the run's loopback bridge. WebSockets and service workers are blocked.

```bash
uv run --project services/repair-orchestrator --python 3.13 --locked faultline run checkout_api --detect
uv run --project services/repair-orchestrator --python 3.13 --locked faultline run checkout_api
```

The repository's `faultline.toml` points to the checkout API as an ordinary project. Detection needs no model credentials and exits **10** when the failure repeats. Repair requires `META_API_KEY` in the controller environment and a Meta-operated `META_BASE_URL` (the default is Meta). It never substitutes the checkout fallback for a project repair. Neither credentials nor the controller environment reach the candidate service. No environment file is loaded.

Use an absolute `--project` path when invoking the source installation from another repository:

```bash
uv run --project /path/to/Faultline/services/repair-orchestrator --python 3.13 --locked faultline run addition
```

The source installation includes the shared contracts in its import path. Shared contracts and the trusted Node/Playwright installation still come from the FaultLine checkout; the wheel is not yet a standalone published distribution.

## Configure a project

Paths in `project.root` resolve relative to the TOML file. Repair targets and editable globs resolve relative to that project root. ReproSpec file paths resolve relative to the TOML file. A single scenario can be selected implicitly; multiple scenarios require a name.

```toml
schema = 1

[project]
name = "calculator"
root = "."
dev_command = ["node", "server.js", "{port}"]
url = "http://127.0.0.1:{port}"
health = "/health"

[repair]
editable = ["src/**/*.js", "server.js"]
max_files = 1

[model]
provider = "meta"
model = "muse-spark-1.3"
max_attempts = 2

[budgets]
baseline = 40

[scenarios.addition]
target_file = "server.js"
repro = "repros/addition.json"
```

`dev_command` accepts an argument array or a shell-style quoted string, split into arguments without a shell. `{port}` is substituted with the private service port. Start one foreground service on `127.0.0.1`; the controller exposes a separate ephemeral loopback bridge to its browser. `/health` must return HTTP 200 before the reproduction starts.

Install dependencies before running. Existing `node_modules` and `.venv` directories are mounted read-only; the configured dev command executes only inside the namespace. The Node and Python toolchains and `uv` are available there. `uv` runs offline without syncing. The service receives a fresh writable copy of the frozen source on a 256 MiB tmpfs, so data and build caches reset between measurements. Environment files, hidden source paths, private-key files, symlinks, and `meta-provided/` are excluded or rejected. Git must already have a commit. Tracked local edits are included and hashed; untracked source is not included. Source export is capped at 64 MiB total and 8 MiB per file.

The runner supports one existing repair target per scenario, up to 32 KiB source, 16 KiB diff, and 100 changed lines. Lower limits can be configured. Exact base hashes, paths and hunks are checked for every language; Python targets also receive syntax checks and configured import allow/deny checks. This general policy does not claim arbitrary application code is AST-safe. Candidate execution is contained by the runtime.

## Write a ReproSpec

`repros/addition.json`:

```json
{
  "version": 1,
  "id": "addition",
  "steps": [
    {"id": "response", "action": "request", "method": "GET", "path": "/sum?a=1&b=2"},
    {"id": "sum.correct", "action": "assert", "source": "response", "check": {"path": "$.sum", "equals": 3}}
  ]
}
```

The eight primitives are `navigate`, `fill`, `click`, `select`, `wait_for`, `request`, `capture`, and `assert`. Assertions use status, equality, another JSON path, regex, type, or existence. Capture supports text, input value, visibility, URL, and screenshots. Assertions refer to earlier request/capture IDs. The controller evaluates assertions outside the candidate namespace. Browser and application state are recreated for each baseline and candidate.

An optional `fingerprint` requires the same literal marker in that session's bounded service logs. Logs are untrusted evidence, not instructions. Admission always requires the same failed assertion IDs, expected values, and observed values twice. Passing baselines, changed failures, execution errors, missing evidence, and failed cleanup prevent a repair claim.

Inline TOML is also supported using `[scenarios.NAME.repro]` and `[[scenarios.NAME.repro.steps]]`, or a single top-level `[repro]` with `repair.target_file`. `[[scenarios]]` entries can use an `id` instead of table names.

A CLI-supplied spec overrides scenario lookup:

```bash
faultline run --config faultline.toml --repro repros/addition.json --target server.js
```

`[[invariants.rule]]` checks are appended to the immutable reproduction and run on every baseline and candidate. Both the initializer's `target`/`expected_status` form and the platform spec's `request`/`assert` form are supported. `invariants.test` is rejected explicitly. `project.setup_command`, `project.test_command`, and `repair.context` are reserved metadata in this runner; setup/test commands are not executed and extra context is not sent to the model. Put required behavioral checks in the ReproSpec or invariant rules.

## Results and proof

Each command prints JSON with its job ID, outcome, cleanup status, evidence directory, and (only after verified cleanup) proof-bundle path. Defaults go under `<project.root>/.faultline/runs/`; use `--data-dir` to override. An installation lock prevents simultaneous CLI processes from reconciling each other's resources. Keep the run directory out of Git.

Useful exit codes: **0** verified, **10** detected, **11** no deterministic failure, **20** unresolved/rejected repair, **21** model error, **30** infrastructure/evidence error, **31** cleanup failure, **130** interrupted.

The bundle's artifact manifest includes both baseline reports, candidate report, the selected reproduction/configuration, provider output, diff, screenshots, traces, request records, and logs. Verify it offline:

```bash
python tools/verify_bundle.py /path/to/proof-bundle --artifacts-dir /path/to/job/artifacts
```

The SHA-256 digest detects inconsistency; it is not a signature. Source hashes identify the measured snapshot. Dependency directories are installed inputs, not content-addressed exports, so freeze those dependencies while running. Review evidence before sharing it; traces and response bodies can contain application data.

## Use the HTTP controller

Set `FAULTLINE_CONFIG=/absolute/path/to/faultline.toml` and optionally `FAULTLINE_SCENARIO=addition` before starting the authenticated controller. Its scenario listing and admission use the selected project configuration, with the same worker and runtime as the CLI. A controller serves one selected project/scenario per installation. Omit these variables to retain the existing Inspector checkout demo.

The Inspector lists the selected scenario under **Sandbox repair**. Set `FAULTLINE_PROJECT_PORT` to the port of a dev server you already run, and the dashboard can also check the scenario's request steps and `[[invariants.rule]]` rules against that server live. The request runs from two fresh HTTP sessions, and a failure counts only when both fail the same way. A live failure of a scenario offers that scenario's sandbox run, which reproduces it again from tracked source before any model call. The dashboard never applies a project diff.

Remote website mutation, external-service egress, multi-service orchestration, WebSocket journeys, automatic dependency installation, arbitrary test-command ingestion, and automatic patch application/deployment are not part of this command.
