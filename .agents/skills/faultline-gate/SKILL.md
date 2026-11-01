---
name: faultline-gate
description: Use before declaring a web-app task done, opening or updating a pull request, merging, or deploying - runs `faultline gate <url> --json` against the running local or preview server as a mandatory pre-deployment check, interprets the verdict and exit code, and drives the fix-and-re-gate loop when FaultLine intercepts a defect.
---

# FaultLine Pre-Flight Gate

## Overview

`faultline gate` points headless Chromium at a running site and explores
same-origin screens with deterministic heuristics: it fills forms, clicks
controls, and stops at the first defect: an HTTP 4xx/5xx from the app's own
API, a failed request, an uncaught JavaScript exception, or a `console.error`.
It returns one verdict: `SAFE_TO_DEPLOY` (exit 0) or `DEPLOYMENT_BLOCKED`
(exit 1).

The gate passes only when the crawl found nothing **and** finished exploring
(`stop_reason: "exhausted"`). A crawl that ran out of actions or time, or did
not say why it stopped, is inconclusive and blocks. Even a pass is a bounded
smoke signal for the flows the crawler reached. It does not check business
rules such as prices or totals; keep the project's own tests and assertions.

**Core rule:** a change to a web app is not done until the gate exits 0
against the running app. Unit tests passing is not the same as the clicked
flows working.

## When to run it

Run the gate, and do not skip it, when **all** of these are true:

- The repository serves a web UI or HTTP API you can start locally or reach as a preview.
- Your change touches anything a user can reach: routes, handlers, templates, components, client JS, forms, API contracts, migrations, or config that affects them.
- You are about to do any of the following: report the task as complete, `git commit` the final change, open or update a PR, merge, or deploy.

Skip it only for changes with no runtime surface (docs, comments, CI config
that does not change the app). Say that you skipped it and why.

## How to run it

1. **Start the app** if it is not running (use the project's dev command, e.g.
   `npm run dev`, `uv run uvicorn ...`). Run it in the background and wait
   until the port answers: `curl -s -o /dev/null http://127.0.0.1:<port>`.
2. **Gate it** from the FaultLine checkout (or a `faultline` on `PATH`):

   ```bash
   ./faultline gate http://127.0.0.1:<port> --json
   ```

   - `--json` prints exactly one JSON object on stdout. Parse that object; do not scrape the prose formats.
   - `--format agent` prints the same verdict as labelled plain text, ready to paste into a prompt.
   - `--max-actions N` (1-100, default 25) and `--timeout S` (1-300, default 90) bound the crawl. Raise them for large apps.
3. **Read the exit code first**, then the JSON.

## Exit codes

| Exit | Verdict | What it means | What you do |
| --- | --- | --- | --- |
| `0` | `SAFE_TO_DEPLOY` | Exploration finished and every explored flow was clean. | Proceed. Mention the gate result (elements and screens explored) in your summary or PR body. |
| `1` | `DEPLOYMENT_BLOCKED` with `failure` set | FaultLine intercepted a defect. | Enter the self-healing loop below. Do **not** commit as done, open the PR, or deploy. |
| `1` | `DEPLOYMENT_BLOCKED` with `error.code: "incomplete_crawl"` and `failure: null` | Inconclusive: no defect in what was explored, but the crawl stopped at `stop_reason` (`max_actions`, `timeout`, or none) before exploring everything. | Re-run with higher `--max-actions` and `--timeout` within their limits. If it still cannot finish, report the unfinished flows to the user. This is not a pass. |
| `1` | `DEPLOYMENT_BLOCKED` with another `error` and `failure: null` | The gate could not explore the site (server down, page would not load, browser runner not built). | Fix the environment named in `error.message`, then re-run. This is not a pass. |
| `2` | `DEPLOYMENT_BLOCKED` | Invalid arguments or URL. | Correct the command (absolute `http://` or `https://` URL) and re-run. |

## JSON schema

```jsonc
{
  "gate_status": "PASSED" | "FAILED",
  "verdict": "SAFE_TO_DEPLOY" | "DEPLOYMENT_BLOCKED",
  "exit_code": 0 | 1 | 2,
  "target_url": "http://127.0.0.1:3000/",
  "summary": "Defect intercepted: HTTP 500 on POST /api/checkout after 3 actions across 2 screens.",
  "elements_explored": 20,
  "actions_taken": 3,
  "stop_reason": null,               // "exhausted" | "max_actions" | "timeout" | null; only "exhausted" passes
  "screens_visited": [{"url": "...", "path": "/checkout", "title": "Checkout", "elements": 11, "forms": 1}],
  "failure": {                       // null when the gate passed or could not run
    "kind": "http_error" | "request_failed" | "page_error" | "console_error",
    "method": "POST", "url": "...", "endpoint": "/api/checkout", "status": 500,
    "message": "...", "response_body": "...", "stack": "...", "step": 4,
    "console_errors": ["..."]
  },
  "reproduction_trail": [
    "1. Open http://127.0.0.1:3000/",
    "2. Click link \"Trail Mug\" on / [a:has-text(\"Trail Mug\") >> nth=0]",
    "3. Fill \"Email\" with \"test@example.com\" on /checkout [#email]",
    "4. Click button \"Place order\" on /checkout [button:has-text(\"Place order\")] -> HTTP 500 on POST /api/checkout"
  ],
  "agent_remediation_prompt": "FaultLine caught an unhandled HTTP 500 error on POST /api/checkout. Triggered by clicking ...",
  "error": null                      // {"code": "...", "message": "..."} when the gate could not run or was inconclusive
}
```

`agent_remediation_prompt` is self-contained: the defect, the control that
triggered it, the server response or stack, the full reproduction, and the
required fix. Treat it as your next instruction.

## The self-healing loop

```
gate --json
  exit 0 ──────────────► done: report the verdict, continue to commit / PR / deploy
  exit 2 ──────────────► fix the command, re-run
  exit 1, incomplete ──► raise --max-actions / --timeout within limits, re-run;
                         still incomplete: report the unfinished flows, do not deploy
  exit 1, error set ───► fix the environment (start server, build runner), re-run
  exit 1, failure set ─► 1. read agent_remediation_prompt and failure
                         2. reproduce: follow reproduction_trail; find the handler for
                            failure.method + failure.endpoint (or the script in failure.stack)
                         3. fix the root cause in application code
                         4. run the project's own tests
                         5. restart the server if it does not hot-reload
                         6. gate --json again
```

Rules for the loop:

- **Fix the cause, not the symptom.** Do not catch-and-swallow the exception, return 200 with an empty body, hide the button, or disable the form to make the gate pass. A fix must leave the flow working for a real user.
- **Never weaken the gate.** Do not lower `--max-actions`/`--timeout` to dodge a defect, point it at a different URL, or edit FaultLine.
- **A new defect after a fix is progress, not failure.** The gate stops at the first defect, so a fixed bug can reveal the next one. Keep going.
- **Stop after three gate runs that block on the same `failure.endpoint` and `failure.kind`.** Do not keep guessing. Report the verdict, the reproduction trail, what you tried, and your best root-cause hypothesis to the user, and leave the change unmerged.
- **Never report the task as complete while the last gate run exited non-zero.**

## Reporting

When the gate passes, include one line in your final summary or PR body:

> FaultLine gate: SAFE_TO_DEPLOY (exploration finished), 20 elements across 2 screens explored on http://127.0.0.1:3000. Explored flows only; business rules are covered by the project's tests.

When you hand a blocked gate to the user, paste `summary`, the
`reproduction_trail`, and the `agent_remediation_prompt` verbatim.

## In CI

`.github/workflows/faultline-gate.yml` runs
`faultline gate "$PREVIEW_URL" --markdown >> "$GITHUB_STEP_SUMMARY"` on every
pull request and push to `main` and fails the job on exit 1. If that check is
red on your PR, open the job summary. It holds the same reproduction trail and
fix prompt; run the loop above locally against the same flow.
