/**
 * The Pre-Flight Agent Gate in the Inspector: a TypeScript port of `gate_result`,
 * `gate_error_result`, and `remediation_prompt` in services/repair-orchestrator/app/cli_crawl.py, so a gate run here
 * reports the same verdict, summary, and agent fix prompt as `faultline gate URL --json`.
 * Keep the two in step. docs/index.html carries the same snippets; the "Agent Skill" tab is
 * .agents/skills/faultline-gate/SKILL.md verbatim (tests/test_agent_gate_snippets.py checks both).
 */

import type { CrawlFailure, CrawlTelemetry } from "@/lib/faultline-api";

export const DEFAULT_GATE_URL = "http://localhost:3000";

/** The `faultline gate --json` contract. */
export interface GateResult {
  gate_status: "PASSED" | "FAILED";
  verdict: "SAFE_TO_DEPLOY" | "DEPLOYMENT_BLOCKED";
  exit_code: 0 | 1 | 2;
  target_url: string;
  summary: string;
  elements_explored: number;
  actions_taken: number;
  /** The crawler's stop reason; only "exhausted" (exploration finished) can pass. */
  stop_reason: string | null;
  screens_visited: NonNullable<CrawlTelemetry["screens_visited"]>;
  failure: CrawlFailure | null;
  reproduction_trail: string[];
  agent_remediation_prompt: string | null;
  error: { code: string; message: string } | null;
}

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;
/** Python's `_clip`: at most `limit` characters (code points), ending in an ellipsis when cut. */
const clip = (text: string, limit: number) => {
  const chars = Array.from(text);
  return chars.length <= limit ? text : `${chars.slice(0, limit - 1).join("")}…`;
};
const pathOf = (url: string | undefined) => {
  try {
    return new URL(url ?? "").pathname || "/";
  } catch {
    return "/";
  }
};

export function describeSignal(failure: CrawlFailure): string {
  if (failure.kind === "http_error") return `HTTP ${failure.status} on ${failure.method} ${failure.endpoint}`;
  if (failure.kind === "request_failed") return `${failure.method} ${failure.endpoint} failed: ${failure.message}`;
  if (failure.kind === "page_error") return `Uncaught ${failure.message}`;
  return `console.error: ${failure.message}`;
}

const failureRoute = (failure: CrawlFailure) =>
  failure.kind === "http_error" || failure.kind === "request_failed"
    ? `${(failure.method || "GET").toUpperCase()} ${pathOf(failure.url)}` : null;

const VERBS: Record<string, string> = { click: "clicking", fill: "filling", select: "selecting", check: "checking" };

/** `clicking "Place order" (button:has-text("Place order")) on /checkout`, from the failing action. */
function trigger(telemetry: CrawlTelemetry, failure: CrawlFailure): string | null {
  const action = telemetry.actions?.find((a) => a.step === failure.step);
  if (!action || action.action === "navigate") return null;
  const verb = VERBS[action.action] ?? action.action;
  let target = action.label ? JSON.stringify(action.label) : String(action.selector ?? "None");
  if (action.label && action.selector) target += ` (${action.selector})`;
  return `${verb} ${target} on ${(action.page ?? "/").split("?")[0] || "/"}`;
}

function fixInstruction(failure: CrawlFailure): string {
  const route = failureRoute(failure) ?? "the failing request";
  if (failure.kind === "http_error") {
    const status = failure.status;
    return typeof status === "number" && status >= 500
      ? `Fix the server-side exception handling for ${route} so it no longer returns HTTP ${status}`
      : `Fix the request the page sends to ${route}, or the route handler, so the action no longer gets HTTP ${status}`;
  }
  if (failure.kind === "request_failed") return `Make ${route} answer instead of dropping the connection`;
  if (failure.kind === "page_error") return "Fix the client-side code that throws this exception";
  return "Fix the client-side code that logs this error";
}

function defectPhrase(failure: CrawlFailure): string {
  if (failure.kind === "http_error") {
    const handled = typeof failure.status === "number" && failure.status >= 500 ? "an unhandled " : "an ";
    return `${handled}HTTP ${failure.status} error on ${failureRoute(failure)}`;
  }
  if (failure.kind === "request_failed") return `a failed network request: ${describeSignal(failure)}`;
  if (failure.kind === "page_error") return `an uncaught JavaScript exception: ${failure.message}`;
  return `a console error: ${failure.message}`;
}

/** A self-contained fix instruction an agent can act on without the report. */
export function remediationPrompt(telemetry: CrawlTelemetry, failure: CrawlFailure, url: string): string {
  const sentences = [`FaultLine caught ${defectPhrase(failure)}.`];
  const by = trigger(telemetry, failure);
  if (by) sentences.push(`Triggered by ${by}.`);
  const lines = [sentences.join(" ")];
  if (failure.response_body) lines.push(`Server response: ${clip(String(failure.response_body), 300)}`);
  if (failure.stack) lines.push(`Stack: ${String(failure.stack).split(/\r\n|\r|\n/).slice(0, 4).join(" | ")}`);
  const trail = telemetry.reproduction_trail ?? [];
  if (trail.length) lines.push("Reproduce:", ...trail.map((step) => `  ${step}`));
  lines.push(`${fixInstruction(failure)} before deploying, then re-run \`faultline gate ${url} --json\` and continue only when it exits 0.`);
  return lines.join("\n");
}

/** `stop_reason` as `crawler_service.telemetry` passes it on: a string, or null. */
export const stopReasonOf = (telemetry: CrawlTelemetry | null | undefined): string | null =>
  typeof telemetry?.stop_reason === "string" ? telemetry.stop_reason : null;

/** Whether a crawl may pass the gate: it found nothing and finished exploring (`stop_reason` "exhausted"). */
export const crawlCompleted = (telemetry: CrawlTelemetry | null | undefined) =>
  telemetry?.status === "clean" && stopReasonOf(telemetry) === "exhausted";

/**
 * The verdict for a crawl, in the documented JSON contract. A clean crawl passes only when it
 * finished exploring; one stopped by its action budget or deadline (or that does not say why it
 * stopped) is inconclusive and blocks, with no failure and an `incomplete_crawl` error.
 */
export function gateResult(telemetry: CrawlTelemetry, url: string): GateResult {
  const screens = telemetry.screens_visited ?? [];
  const explored = telemetry.elements_explored ?? 0;
  const actions = telemetry.actions_taken ?? telemetry.actions?.length ?? 0;
  const stopReason = stopReasonOf(telemetry);
  const target = telemetry.target_url || url;
  const trail = telemetry.reproduction_trail ?? [];
  const failure = telemetry.failure ?? null;
  const passed = crawlCompleted(telemetry);
  let summary: string;
  let prompt: string | null = null;
  let error: GateResult["error"] = null;
  if (passed) {
    summary = `No defects found in explored flows: explored ${plural(explored, "element")} across ${plural(screens.length, "screen")} with ${plural(actions, "action")}. This does not establish business completeness.`;
  } else if (telemetry.status === "clean") {
    const message = `Exploration stopped with ${stopReason || "no completion reason"} after ${plural(actions, "action")}; completion was not established.`;
    error = { code: "incomplete_crawl", message };
    summary = `Gate inconclusive: ${message}`;
    prompt = incompletePrompt(message, target);
  } else if (failure) {
    summary = `Defect intercepted: ${describeSignal(failure)} after ${plural(actions, "action")} across ${plural(screens.length, "screen")}.`;
    prompt = remediationPrompt({ ...telemetry, reproduction_trail: trail }, failure, target);
  } else {
    const message = String(telemetry.error || "the crawl ended without a verdict");
    error = { code: "crawl_error", message };
    summary = `Gate could not complete the crawl: ${message}`;
    prompt = gateErrorPrompt(message, target);
  }
  return {
    gate_status: passed ? "PASSED" : "FAILED",
    verdict: passed ? "SAFE_TO_DEPLOY" : "DEPLOYMENT_BLOCKED",
    exit_code: passed ? 0 : 1,
    target_url: target,
    summary,
    elements_explored: explored,
    actions_taken: actions,
    stop_reason: stopReason,
    screens_visited: screens,
    failure,
    reproduction_trail: trail,
    agent_remediation_prompt: prompt,
    error,
  };
}

const incompletePrompt = (message: string, url: string) =>
  `The FaultLine gate is inconclusive for ${url}: ${message} Increase --max-actions and --timeout within their supported limits, then re-run \`faultline gate ${url} --json\`. If exploration still cannot finish, investigate the unfinished flows and retain independent business checks. Do not deploy until the gate exits 0.`;

const gateErrorPrompt = (message: string, url: string) =>
  `The FaultLine gate could not explore ${url} (crawl_error): ${message} Make sure the preview server is running and the browser runner is built, then re-run \`faultline gate ${url} --json\`. Do not deploy until the gate exits 0.`;

/** The verdict when the crawl could not finish (`gate_error_result` for a crawl error): blocked, exit 1. */
export function gateErrorResult(message: string, url: string): GateResult {
  return {
    gate_status: "FAILED", verdict: "DEPLOYMENT_BLOCKED", exit_code: 1, target_url: url,
    summary: `Gate could not run: ${message}`, elements_explored: 0, actions_taken: 0, stop_reason: null, screens_visited: [], failure: null,
    reproduction_trail: [], agent_remediation_prompt: gateErrorPrompt(message, url), error: { code: "crawl_error", message },
  };
}

/** One step of the reproduction trail as the panel lists it. */
export interface TrailStep { kind: string; label: string; page: string | null; text?: string }

/** "Open /", `Click "Start Free"`, or, for a run of fills folded into one step, `Fill "Name", "Email"`. */
export const trailAction = (step: TrailStep, quote: (text: string) => string = (text) => `"${text}"`) =>
  step.kind === "visit" ? `Open ${step.label}`
    : step.kind === "session" ? step.text ?? `Send ${step.label}`
    : step.kind === "fill" ? `Fill ${step.label.split(", ").map(quote).join(", ")}`
    : `Click ${quote(step.label)}`;

export interface AgentSnippet {
  id: string;
  tab: string;
  /** Where the snippet goes. */
  file: string;
  /** One line on what it does. */
  note: string;
  body: string;
}

/** .agents/skills/faultline-gate/SKILL.md, verbatim. */
export const GATE_SKILL = `---
name: faultline-gate
description: Use before declaring a web-app task done, opening or updating a pull request, merging, or deploying - runs \`faultline gate <url> --json\` against the running local or preview server as a mandatory pre-deployment check, interprets the verdict and exit code, and drives the fix-and-re-gate loop when FaultLine intercepts a defect.
---

# FaultLine Pre-Flight Gate

## Overview

\`faultline gate\` points headless Chromium at a running site and explores
same-origin screens with deterministic heuristics: it fills forms, clicks
controls, and stops at the first defect: an HTTP 4xx/5xx from the app's own
API, a failed request, an uncaught JavaScript exception, or a \`console.error\`.
It returns one verdict: \`SAFE_TO_DEPLOY\` (exit 0) or \`DEPLOYMENT_BLOCKED\`
(exit 1).

The gate passes only when the crawl found nothing **and** finished exploring
(\`stop_reason: "exhausted"\`). A crawl that ran out of actions or time, or did
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
- You are about to do any of the following: report the task as complete, \`git commit\` the final change, open or update a PR, merge, or deploy.

Skip it only for changes with no runtime surface (docs, comments, CI config
that does not change the app). Say that you skipped it and why.

## How to run it

1. **Start the app** if it is not running (use the project's dev command, e.g.
   \`npm run dev\`, \`uv run uvicorn ...\`). Run it in the background and wait
   until the port answers: \`curl -s -o /dev/null http://127.0.0.1:<port>\`.
2. **Gate it** from the FaultLine checkout (or a \`faultline\` on \`PATH\`):

   \`\`\`bash
   ./faultline gate http://127.0.0.1:<port> --json
   \`\`\`

   - \`--json\` prints exactly one JSON object on stdout. Parse that object; do not scrape the prose formats.
   - \`--format agent\` prints the same verdict as labelled plain text, ready to paste into a prompt.
   - \`--max-actions N\` (1-100, default 25) and \`--timeout S\` (1-300, default 90) bound the crawl. Raise them for large apps.
3. **Read the exit code first**, then the JSON.

## Exit codes

| Exit | Verdict | What it means | What you do |
| --- | --- | --- | --- |
| \`0\` | \`SAFE_TO_DEPLOY\` | Exploration finished and every explored flow was clean. | Proceed. Mention the gate result (elements and screens explored) in your summary or PR body. |
| \`1\` | \`DEPLOYMENT_BLOCKED\` with \`failure\` set | FaultLine intercepted a defect. | Enter the self-healing loop below. Do **not** commit as done, open the PR, or deploy. |
| \`1\` | \`DEPLOYMENT_BLOCKED\` with \`error.code: "incomplete_crawl"\` and \`failure: null\` | Inconclusive: no defect in what was explored, but the crawl stopped at \`stop_reason\` (\`max_actions\`, \`timeout\`, or none) before exploring everything. | Re-run with higher \`--max-actions\` and \`--timeout\` within their limits. If it still cannot finish, report the unfinished flows to the user. This is not a pass. |
| \`1\` | \`DEPLOYMENT_BLOCKED\` with another \`error\` and \`failure: null\` | The gate could not explore the site (server down, page would not load, browser runner not built). | Fix the environment named in \`error.message\`, then re-run. This is not a pass. |
| \`2\` | \`DEPLOYMENT_BLOCKED\` | Invalid arguments or URL. | Correct the command (absolute \`http://\` or \`https://\` URL) and re-run. |

## JSON schema

\`\`\`jsonc
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
    "2. Click link \\"Trail Mug\\" on / [a:has-text(\\"Trail Mug\\") >> nth=0]",
    "3. Fill \\"Email\\" with \\"test@example.com\\" on /checkout [#email]",
    "4. Click button \\"Place order\\" on /checkout [button:has-text(\\"Place order\\")] -> HTTP 500 on POST /api/checkout"
  ],
  "agent_remediation_prompt": "FaultLine caught an unhandled HTTP 500 error on POST /api/checkout. Triggered by clicking ...",
  "error": null                      // {"code": "...", "message": "..."} when the gate could not run or was inconclusive
}
\`\`\`

\`agent_remediation_prompt\` is self-contained: the defect, the control that
triggered it, the server response or stack, the full reproduction, and the
required fix. Treat it as your next instruction.

## The self-healing loop

\`\`\`
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
\`\`\`

Rules for the loop:

- **Fix the cause, not the symptom.** Do not catch-and-swallow the exception, return 200 with an empty body, hide the button, or disable the form to make the gate pass. A fix must leave the flow working for a real user.
- **Never weaken the gate.** Do not lower \`--max-actions\`/\`--timeout\` to dodge a defect, point it at a different URL, or edit FaultLine.
- **A new defect after a fix is progress, not failure.** The gate stops at the first defect, so a fixed bug can reveal the next one. Keep going.
- **Stop after three gate runs that block on the same \`failure.endpoint\` and \`failure.kind\`.** Do not keep guessing. Report the verdict, the reproduction trail, what you tried, and your best root-cause hypothesis to the user, and leave the change unmerged.
- **Never report the task as complete while the last gate run exited non-zero.**

## Reporting

When the gate passes, include one line in your final summary or PR body:

> FaultLine gate: SAFE_TO_DEPLOY (exploration finished), 20 elements across 2 screens explored on http://127.0.0.1:3000. Explored flows only; business rules are covered by the project's tests.

When you hand a blocked gate to the user, paste \`summary\`, the
\`reproduction_trail\`, and the \`agent_remediation_prompt\` verbatim.

## In CI

\`.github/workflows/faultline-gate.yml\` runs
\`faultline gate "$PREVIEW_URL" --markdown >> "$GITHUB_STEP_SUMMARY"\` on every
pull request and push to \`main\` and fails the job on exit 1. If that check is
red on your PR, open the job summary. It holds the same reproduction trail and
fix prompt; run the loop above locally against the same flow.`;

/**
 * POSIX shell form of `value`, matching Python's `shlex.quote`: safe words pass
 * through, anything else is single-quoted so `&`, `;`, `$`, or spaces in a
 * pasted URL reach `faultline gate` as one argument.
 */
export const shellQuote = (value: string): string =>
  /^[\w@%+=:,./-]+$/.test(value) ? value : `'${value.replace(/'/g, "'\\''")}'`;

export const agentSnippets = (url: string = DEFAULT_GATE_URL): AgentSnippet[] => snippetsFor(shellQuote(url));

/** Copy-ready snippets; `url` is already shell-quoted. */
const snippetsFor = (url: string): AgentSnippet[] => [
  {
    id: "rules",
    tab: "Cursor / Claude Code",
    file: "AGENTS.md · CLAUDE.md · .cursorrules",
    note: "Paste into the agent's rules so it gates itself before every deploy.",
    body: `## Pre-flight gate (FaultLine)
Before you call a web change done, commit it, open or update a pull request, or deploy:
1. Start the preview server and wait until it answers.
2. Run: faultline gate ${url} --json
3. Exit 0 (SAFE_TO_DEPLOY): exploration finished with no defect in the flows it
   reached. Continue, and report the elements and screens explored.
4. Exit 1 (DEPLOYMENT_BLOCKED): a defect, or a crawl that stopped early
   (inconclusive). Treat \`agent_remediation_prompt\` as your next instruction.
   For a defect, follow \`reproduction_trail\`, fix the root cause in source
   (never swallow the error or hide the control), and run the gate again.
5. Exit 2: fix the command. Never deploy or report success until the gate exits 0.`,
  },
  {
    id: "ci",
    tab: "GitHub Actions CI/CD",
    file: ".github/workflows/faultline-gate.yml",
    note: "Fails the pull request on DEPLOYMENT_BLOCKED and writes the trail and fix prompt to the job summary. FaultLine's own copy adds a self-test and annotations.",
    body: `name: FaultLine pre-flight gate
on: [pull_request]
permissions:
  contents: read
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/checkout@v7
        with:
          repository: FrankieBiz/Faultline
          path: .faultline
      - uses: actions/setup-node@v7
        with:
          node-version: '24'
      - uses: astral-sh/setup-uv@v10
      - name: Build the FaultLine crawler
        working-directory: .faultline/tools/browser-runner
        run: npm ci && npx playwright install --with-deps chromium && npm run build
      - name: Start the preview
        run: |
          npm ci && npm run build
          npm start &
          npx --yes wait-on ${url}
      - name: FaultLine pre-flight gate
        run: .faultline/faultline gate ${url} --markdown >> "$GITHUB_STEP_SUMMARY"`,
  },
  {
    id: "cli",
    tab: "CLI Pre-Flight",
    file: "Terminal",
    note: "Run it by hand, from a git hook, or from any script that respects exit codes.",
    body: `./faultline gate ${url}                   # live HUD, verdict, fix prompt
./faultline gate ${url} --json            # one JSON verdict for agents
./faultline gate ${url} --format agent    # plain text for an LLM prompt
./faultline gate ${url} --markdown        # PR comment or job summary
# exit 0 SAFE_TO_DEPLOY (finished, clean) · exit 1 DEPLOYMENT_BLOCKED (defect or incomplete) · exit 2 invalid input`,
  },
  {
    id: "skill",
    tab: "Agent Skill",
    file: ".agents/skills/faultline-gate/SKILL.md",
    note: "Copy the file into your repository's skills folder; agents that load skills pick it up by name.",
    body: GATE_SKILL,
  },
];
