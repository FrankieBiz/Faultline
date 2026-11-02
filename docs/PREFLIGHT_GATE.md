# Pre-Flight Agent Gate

Coding agents now write, test, and ship web changes on their own. What they
usually skip is the step a careful engineer does last: open the app and click
through the flow they changed. Unit tests pass, the PR merges, and checkout
returns HTTP 500.

`faultline gate` is that last step as a command. It points headless Chromium
at a running preview, explores discovered same-origin screens, fills forms with
realistic values, clicks in shopping-funnel order, and stops at the first
defect. The result is one verdict an agent or a pipeline can obey:

```bash
faultline gate http://127.0.0.1:3000 --json
```

| Exit | `verdict` | Meaning |
| --- | --- | --- |
| **0** | `SAFE_TO_DEPLOY` | The crawler exhausted its discovered work without finding defects in explored flows. |
| **1** | `DEPLOYMENT_BLOCKED` | A defect was intercepted, exploration was incomplete, or the site could not be explored. |
| **2** | `DEPLOYMENT_BLOCKED` | Invalid arguments or URL. |

A blocked verdict carries the evidence, the numbered steps that reproduce it,
and an instruction a coding agent can act on immediately:

```text
FaultLine caught an unhandled HTTP 500 error on POST /api/checkout. Triggered by clicking "Place order" (#submit-order) on /.
Server response: {"detail":"KeyError: cart_id"}
Reproduce:
  1. Open http://127.0.0.1:5051/
  2. Fill "Email" with "test@example.com" on / [#email]
  3. Click button "Place order" on / [#submit-order] -> HTTP 500 on POST /api/checkout
Fix the server-side exception handling for POST /api/checkout so it no longer returns HTTP 500 before deploying, then re-run `faultline gate http://127.0.0.1:5051/ --json` and continue only when it exits 0.
```

## Platform Compatibility

`faultline gate` is cross-platform and runs natively on **macOS**, **Linux**, and **Windows**:
- Exploration is executed using standard Playwright (headless Chromium) and Python/TypeScript CLI tooling.
- It requires zero Linux Bubblewrap or cgroup v2 privileges.
- Developers, coding agents, and CI pipelines on any operating system can run `faultline gate <url> --json` as an automated pre-deployment check.
*(Note: Only backend candidate repair synthesis and sandboxed candidate execution via `faultline run` requires a Linux host with unprivileged user namespaces and cgroup v2).*

## Architecture

```
           agent / CI / git hook
                    │  faultline gate URL [--json | --markdown | --format agent|ci]
                    ▼
  app/cli.py ── cmd_gate ──► app/cli_crawl.py ── gate_command
                                   │
                                   ├─► crawler_service.run_crawl ──► node tools/browser-runner (Playwright, headless Chromium)
                                   │        NDJSON progress events ◄──┘  final CrawlReport
                                   │
                                   ├─► gate_result: CrawlReport ──► gate JSON contract
                                   │      verdict + exit code, telemetry (elements, screens),
                                   │      reproduction_trail, agent_remediation_prompt
                                   │
                                   └─► renderer: JSON │ Markdown │ agent text │ CI lines │ terminal HUD
```

- **One crawler, many consumers.** The gate reuses the crawler behind
  `faultline crawl`, `faultline scan`, and the Inspector's Live Agent Mission
  HUD, so a defect the gate blocks is the same defect a human sees in the
  dashboard, with the same reproduction trail.
- **One contract, five views.** `gate_result` builds the verdict once; every
  output format renders that object, so `--json`, `--markdown`, and
  `--format agent|ci` cannot disagree.
- **Defects the gate catches:** an HTTP 5xx from the app; a 400/422 on a fetch
  or page load; a request that fails outright; an uncaught JavaScript
  exception; a `console.error`. Destructive controls such as Remove or Log out
  are skipped.
- **It fails closed.** A server that does not answer, a page that will not load, or a
  missing browser runner gives `DEPLOYMENT_BLOCKED` with `error` set, never a
  pass. Only raw `status: "clean"` with `stop_reason: "exhausted"` exits 0.
  Reaching `max_actions`, timing out, hitting the 30-screen limit with linked
  screens unvisited (`screen_limit`), skipping commit controls on a non-local
  origin (`skipped_commit_controls`), or missing a completion reason is
  inconclusive: exit 1, `error.code: "incomplete_crawl"`, and `failure: null`.
  The fix prompt names the next step for each reason; unresolved exploration stays blocked.
  A completed clean crawl finds no defects in explored flows; it does not establish
  business completeness or replace independent assertions and normal project CI.
- **Read-only.** The gate never patches code. Repair stays behind
  `faultline scan` / `faultline run`, where candidates are verified in the
  sandbox before anything is applied.

## Output formats

| Flag | Audience | Stdout | Progress |
| --- | --- | --- | --- |
| *(none)* | People at a terminal | Live HUD, verdict banner, reproduction journey, fix prompt | stdout |
| `--json` | Agents, scripts | Exactly one JSON object | none |
| `--markdown` | PR comments, `$GITHUB_STEP_SUMMARY` | Status badge, facts table, defect, trail, fix prompt | stderr (job log) |
| `--format agent` | LLM prompts | Labelled plain text, no ANSI, ending in `Required action:` | none |
| `--format ci` | CI logs | Terse `key: value` lines; an `::error`/`::notice` annotation under GitHub Actions | stdout |

The output flags are mutually exclusive. `--max-actions` (1-100, default 25)
and `--timeout` seconds (1-300, default 90) bound the crawl.

### JSON contract

```jsonc
{
  "gate_status": "PASSED" | "FAILED",
  "verdict": "SAFE_TO_DEPLOY" | "DEPLOYMENT_BLOCKED",
  "exit_code": 0 | 1 | 2,
  "target_url": "http://127.0.0.1:3000/",
  "summary": "Defect intercepted: HTTP 500 on POST /api/checkout after 3 actions across 2 screens.",
  "elements_explored": 20,
  "actions_taken": 3,
  "stop_reason": "exhausted" | "max_actions" | "timeout" | "screen_limit" | "skipped_commit_controls" | "..." | null,
  "screens_visited": [{"url": "...", "path": "/checkout", "title": "Checkout", "elements": 11, "forms": 1}],
  "failure": {"kind": "http_error", "method": "POST", "endpoint": "/api/checkout", "status": 500, "...": "..."} | null,
  "reproduction_trail": ["1. Open http://127.0.0.1:3000/", "..."],
  "agent_remediation_prompt": "FaultLine caught ..." | null,
  "error": {"code": "invalid_url" | "invalid_request" | "runner_unavailable" | "runner_failed" | "crawl_error" | "incomplete_crawl", "message": "..."} | null
}
```

`error` adds one field to the base contract. It separates "the app is broken"
(`failure` set) from "the gate could not look" (`error` set), so an agent
fixes the right thing. When the gate itself could not run,
`agent_remediation_prompt` explains how to restore the environment.
Both result and error JSON always include integer `actions_taken` and nullable
string `stop_reason`; a crawl that could not start reports `0` and `null`.
Unknown string stop reasons remain visible and cannot pass the gate.

### Scan repair origin binding

`faultline scan` requires both a matching registered method/path and a failing
request origin in the controller readiness response's `repair_origins` list.
For the seeded controller, the list comes from `FAULTLINE_LIVE_STORE_URL`
(backend) and `FAULTLINE_STOREFRONT_URL` (storefront proxy). The storefront defaults
to `http://127.0.0.1:3000`, or the validated `BUGGYSHOP_PORT` when configured.
Origins compare scheme, hostname and effective port; no DNS aliases or arbitrary
ports are inferred. Missing advertisements and foreign origins decline dispatch.
Generic project mode advertises no seeded origins and requires an explicit
project reproduction contract through `faultline run`.

The crawler subprocess receives only browser discovery and basic system
environment variables. Provider keys, controller credentials and Node injection
settings are not forwarded; this does not add a browser resource or network sandbox.

## Integrations

### Coding agents: the `faultline-gate` skill

[`.agents/skills/faultline-gate/SKILL.md`](../.agents/skills/faultline-gate/SKILL.md)
tells any agent that loads skills (Claude Code, Codex, Cursor, Devin) to run
the gate before it reports a task complete, opens a PR, or deploys. It
includes the exit-code table, the JSON schema, and a bounded self-healing
loop:

```
gate --json ─► exit 0: done
            └► exit 1 + failure: read the prompt ─► reproduce ─► fix the root cause
                                  ─► run project tests ─► gate again (stop after 3 identical blocks)
```

The skill forbids gaming the gate: no swallowing exceptions, no hiding
controls, no shrinking the crawl budget. It also forbids claiming completion
while the last run exited non-zero.

### GitHub Actions

[`.github/workflows/faultline-gate.yml`](../.github/workflows/faultline-gate.yml)
runs on every pull request and push to `main`:

```bash
./faultline gate "$PREVIEW_URL" --markdown >> "$GITHUB_STEP_SUMMARY"
```

A blocked verdict fails the job and adds an error annotation. The step summary
shows the badge, the reproduction trail, and the fix prompt for the agent.
Pass the optional `PREVIEW_URL` input through `workflow_dispatch` or
`workflow_call`, set the `PREVIEW_URL` Actions secret (pass it explicitly when
calling the reusable workflow), or set the `FAULTLINE_PREVIEW_URL` repository
variable. Precedence is input, secret, then variable. Give deploy jobs
`needs: gate` and make the check required in branch protection. Without a
preview URL, the workflow tests itself. It
starts a healthy store that must pass, then a store with a broken checkout
that must exit exactly 1 with `POST /api/checkout` in its fix prompt.

### Git pre-push hook

[`.githooks/pre-push`](../.githooks/pre-push) blocks `git push` when the local
dev server fails the gate:

```bash
git config core.hooksPath .githooks
export FAULTLINE_GATE_URL=http://127.0.0.1:3000   # default
```

If the server is not running, the hook warns and lets the push through. Set
`FAULTLINE_GATE_REQUIRED=1` to block instead. `FAULTLINE_GATE_SKIP=1` or
`git push --no-verify` skips the gate for one push.

## What it does not claim

- The gate explores what a crawler can reach within the action budget. A clean
  verdict means "no defect in the explored flows", not "no defects anywhere".
  `elements_explored` and `screens_visited` show exactly what was covered.
- Flows behind authentication or with destructive controls are not exercised.
- On a non-local origin (anything but localhost, loopback, or a private network
  address) the crawler never clicks submit controls, buttons in POST forms, or
  commit-named controls (Place order, Pay, Book, Donate, Subscribe, ...), and
  never fills POST forms. A crawl that skipped any of them ends
  `skipped_commit_controls`, which blocks, so a hosted preview cannot pass.
  To exercise checkout and other commit flows, gate a disposable local preview,
  or pass `--allow-commit-actions` against a preview with test data and payment
  sandboxes.
  The name match is a denylist: a script-driven control outside any form with
  an unrecognized label can still be clicked on a hosted preview.
- Markdown and JSON output include a clipped excerpt (up to 600 characters) of
  the failing response body. A job summary is visible to anyone who can read
  the repository, so gate preview environments that do not return secrets in
  error bodies.

## Verification

`services/repair-orchestrator/tests/test_gate.py` covers parsing, all three
exit codes, the JSON contract, every output format, remediation prompts for each defect
kind, and a real-Chromium run that blocks an HTTP 500. Run it with
`make test` or `make check`.
