# Check a running service

From an external project, invoke the checkout's launcher by absolute path or a symlink on `PATH`. It resolves its own installation, uses locked Python dependencies, forwards arguments unchanged, and preserves your working directory. It does not load environment files.

```bash
/path/to/Faultline/faultline init
# Review the generated commands and route; install dependencies and start your service.
/path/to/Faultline/faultline check --config faultline.toml --port 3000 --plain
/path/to/Faultline/faultline check --config faultline.toml --port 3000 --repair --json
```

`check` validates the entire TOML document before sending requests. Schema version 1, a project with a nonempty `dev_command`, and at least one HTTP invariant or HTTP-only scenario are required. Unknown fields, invalid types, malformed rules, duplicate IDs, empty documents, missing files, unsupported sandbox profiles, and invalid budgets fail closed. Relative file references resolve from the config's directory; `project.root` resolves from that directory. Browser scenarios must use `faultline run`.

The target must already be running. `check` does not execute setup or development commands. `{port}` in URLs requires `--port`; literal HTTP(S) URLs need no port flag. Requests do not follow redirects. Each invariant is measured through the existing reproduction engine in two fresh HTTP sessions. Every declared assertion must pass in both sessions. A flaky result, unreachable service, HTTP mismatch, JSON mismatch, timeout, or incomplete execution fails the gate. Requests may include mutations explicitly declared in the config; live target state is not reset between sessions.

Example using status and JSON assertions:

```toml
schema = 1
[project]
name = "calculator"
dev_command = ["env", "PORT={port}", "node", "server.js"]
url = "http://127.0.0.1:{port}"
health = "/health"

[[invariants.rule]]
id = "addition"
request = {method = "GET", path = "/sum?a=2&b=3"}
assert = [{status = 200}, {path = "$.sum", equals = 5}]
```

The initializer's `target`, `method`, `expected_status`, and optional `json` form is also supported. Do not mix it with `request`/`assert` in one rule.

## Exit and output contract

- **0**: every assertion in every check passed twice, configuration is valid, and all local sandbox prerequisites are available.
- **1**: a failed invariant, invalid config, transport/execution error, or missing sandbox prerequisite. A verified repair candidate does **not** change a failing live check's exit code.
- `--json` emits exactly one JSON object on stdout, including errors. `schema`, `passed`, `exit_code`, `checks`, `errors`, `sandbox`, `repair_requested`, and `source_applied` describe the result. Runner diagnostics go to stderr. Response excerpts, fingerprints, and assertion values are omitted from CLI output to avoid accidentally printing application secrets.
- `--plain` contains no ANSI escapes; `check` currently uses plain output by default too. JSON takes precedence when both flags are supplied. Invalid command-line syntax retains argparse's conventional exit 2 and stderr usage message.

Sandbox diagnostics check Bubblewrap, cgroup v2, systemd-run, Node, and uv. Missing prerequisites fail the overall gate even if HTTP assertions pass. Presence only means `status: unverified` and `runtime_ready: null`: it does not prove usable user namespaces, delegated cgroups, or enforcement. Only the repair runner's actual preflight can establish those properties. The PR workflow installs prerequisites on Ubuntu and exercises real passing/failing HTTP invariants; it makes no sandbox execution claim and does not request repair.

## Optional repair

Only identical repeated live invariant failures can escalate. Transport errors, flaky failures, and passing invariants never invoke the runner. Scenarios select their own `target_file`; ordinary rules need an explicit `[repair].target_file` inside `repair.editable`. No target is guessed from an HTTP route. Configurations without a target return `repair.status: unsupported` for that failure.

The existing project runner re-reproduces the failure from tracked source in its sandbox, enforces policy, verifies any candidate, and confirms cleanup. Its requirements still apply: a local loopback project URL template, installed dependencies, a committed Git repository, working namespace/cgroup containment, and a configured Meta provider. Remote targets can be checked but cannot be repaired. Missing prerequisites produce `unavailable`; runner exceptions produce `error`; unsuccessful or incomplete results produce `unresolved`. `verified_candidate` requires outcome `verified`, cleanup `succeeded`, and a proof bundle. Evidence goes to `<project.root>/.faultline/runs`.

`source_applied` is always false. Review the proof and diff separately. The gate remains failed until the live service actually passes a subsequent check. See [the project runner](PROJECT_RUNNER.md) for supported commands, policy, artifacts, and limitations.

## Initializer behavior

Detection covers Next App/Pages routers in root or `src`, Vite React/Vue/Svelte with TypeScript/JavaScript metadata, Express and generic Node scripts/entrypoints, FastAPI/Starlette, Django's `manage.py`, and Flask. It selects declared `dev`/`start` scripts and package managers from `packageManager` or lockfiles. It never invents a test script. TOML strings are escaped, and generated editable globs use the runtime's supported glob syntax (no brace expansion).

Node commands use `env PORT={port}` because the runtime executes arguments without a shell. Next/Vite also receive their supported port/host flags. Review existing scripts that hard-code a different port. pnpm, Yarn, and Bun commands match local manifests, but the sandbox currently mounts Node/npm and uv only: adapt those commands to installed Node entrypoints before repair. Setup commands are metadata; FaultLine does not install dependencies automatically.

Python source discovery recognizes ordinary FastAPI, Starlette, and Flask application assignments and uses their actual module/object names. Requirements-only projects use `.venv/bin/python` after the suggested `uv venv && uv pip install -r requirements.txt`. A framework dependency without a discoverable app produces an explicitly documented conventional `main:app` (ASGI) or `app:app` (Flask) fallback that **must be customized**. No entrypoint and no supported framework produces an error without writing a fake service config. Syntax errors and malformed manifests are reported without creating a partial config.

The default `/` route is a starting invariant, not a claim that every app serves it: replace it with an existing HTTP 200 route. Generated files do not reference a nonexistent schema file and do not claim a guessed repair target. Add an explicit target and reproduction before requesting repair.
