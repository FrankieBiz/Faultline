/**
 * Command-line parsing for the browser runner, kept separate from the
 * entrypoint so it can be unit-tested without launching a browser.
 */

import { randomUUID } from "node:crypto";
import path from "node:path";
import { parseArgs } from "node:util";
import { DEFAULT_CRAWL_TIMEOUT_MS, DEFAULT_MAX_ACTIONS, MAX_CRAWL_ACTIONS, MAX_CRAWL_TIMEOUT_MS } from "./crawler.js";
import { MAX_TIMEOUT_MS, type CheckoutScenarioOptions } from "./oracle.js";

/** Usage text printed for `--help` and argument errors. */
export const USAGE = `Usage: faultline-browser-runner --base-url <url> [options]
       faultline-browser-runner --crawl <url> [--max-actions <n>] [--timeout-ms <ms>] [--ndjson]
                                [--allow-commit-actions]

Runs the trusted checkout scenario once and writes a canonical ExecutionReport.

Required:
  --base-url <url>         BuggyShop frontend origin, e.g. http://127.0.0.1:3000

Options:
  --case-id <id>           Order namespace sent as X-Faultline-Case-Id
                           (default: a fresh "cli-<uuid>")
  --coupon <code>          Coupon to enter at checkout (default: none)
  --output-json <path>     Report destination (default: <artifacts-dir>/report.json)
  --artifacts-dir <path>   Evidence directory, including artifacts.json
                           (default: ./artifacts/<execution-id>)
  --timeout-ms <ms>        Execution budget, at most ${MAX_TIMEOUT_MS} (default: ${MAX_TIMEOUT_MS})
  --execution-id <id>      Execution ID (default: a fresh UUID)
  -h, --help               Show this help

Autonomous crawl:
  --crawl <url>            Click through the site in headless Chromium until a
                           control triggers an HTTP 5xx/400/422, an uncaught
                           error, or console.error; no expectations needed
  --max-actions <n>        Interactions before stopping clean, 1-${MAX_CRAWL_ACTIONS} (default: ${DEFAULT_MAX_ACTIONS})
  --timeout-ms <ms>        Crawl budget, 1000-${MAX_CRAWL_TIMEOUT_MS} (default: ${DEFAULT_CRAWL_TIMEOUT_MS})
  --ndjson                 Print one JSON event per line, ending with {"type":"report"}
  --allow-commit-actions   Also click Place order, Pay, Submit, and similar
                           buttons when the URL is not localhost, loopback, or a
                           private network address. Only use on a disposable
                           environment: on a real site this can place orders.

Exit codes: 0 passed, 1 assertion failed, 2 runner/infrastructure error, 3 timed out.
Crawl exit codes: 0 clean, 1 defect found, 2 runner/infrastructure error.`;

/** Raised for invalid command-line input; the CLI exits with code 2. */
export class CliUsageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CliUsageError";
  }
}

/** Parsed CLI invocation. */
export type CliCommand =
  | { kind: "help" }
  | { kind: "crawl"; url: string; maxActions: number; timeoutMs: number; ndjson: boolean; allowCommitActions: boolean }
  | { kind: "run"; scenario: CheckoutScenarioOptions & { artifactsDir: string; executionId: string }; outputJson: string };

function parseTimeout(raw: string | undefined): number | undefined {
  if (raw === undefined) return undefined;
  if (!/^\d+$/.test(raw)) throw new CliUsageError(`--timeout-ms must be a whole number of milliseconds; received "${raw}".`);
  const value = Number(raw);
  if (value > MAX_TIMEOUT_MS) throw new CliUsageError(`--timeout-ms cannot exceed ${MAX_TIMEOUT_MS}.`);
  return value;
}

function parseBoundedInteger(flag: string, raw: string | undefined, min: number, max: number): number | undefined {
  if (raw === undefined) return undefined;
  if (!/^\d+$/.test(raw)) throw new CliUsageError(`${flag} must be a whole number; received "${raw}".`);
  const value = Number(raw);
  if (value < min || value > max) throw new CliUsageError(`${flag} must be from ${min} to ${max}.`);
  return value;
}

/**
 * Parses argv (without the node and script entries) into a command.
 *
 * @param argv Arguments after the script path.
 * @param cwd Directory that relative paths resolve against.
 */
export function parseCliArgs(argv: readonly string[], cwd: string = process.cwd()): CliCommand {
  let values;
  try {
    ({ values } = parseArgs({
      args: [...argv],
      strict: true,
      allowPositionals: false,
      options: {
        "base-url": { type: "string" },
        "case-id": { type: "string" },
        coupon: { type: "string" },
        "output-json": { type: "string" },
        "artifacts-dir": { type: "string" },
        "timeout-ms": { type: "string" },
        "execution-id": { type: "string" },
        crawl: { type: "string" },
        "max-actions": { type: "string" },
        ndjson: { type: "boolean" },
        "allow-commit-actions": { type: "boolean" },
        help: { type: "boolean", short: "h" },
      },
    }));
  } catch (error) {
    throw new CliUsageError(error instanceof Error ? error.message : String(error));
  }

  if (values.help) return { kind: "help" };

  if (values.crawl !== undefined) {
    const checkoutOnly = ["base-url", "case-id", "coupon", "output-json", "artifacts-dir", "execution-id"] as const;
    const conflict = checkoutOnly.find((name) => values[name] !== undefined);
    if (conflict) throw new CliUsageError(`--${conflict} cannot be combined with --crawl.`);
    return {
      kind: "crawl",
      url: values.crawl,
      maxActions: parseBoundedInteger("--max-actions", values["max-actions"], 1, MAX_CRAWL_ACTIONS) ?? DEFAULT_MAX_ACTIONS,
      timeoutMs: parseBoundedInteger("--timeout-ms", values["timeout-ms"], 1_000, MAX_CRAWL_TIMEOUT_MS) ?? DEFAULT_CRAWL_TIMEOUT_MS,
      ndjson: values.ndjson === true,
      allowCommitActions: values["allow-commit-actions"] === true,
    };
  }
  if (values["max-actions"] !== undefined || values.ndjson || values["allow-commit-actions"]) {
    throw new CliUsageError("--max-actions, --ndjson, and --allow-commit-actions require --crawl.");
  }

  const baseUrl = values["base-url"];
  if (!baseUrl) throw new CliUsageError("--base-url is required.");

  const executionId = values["execution-id"] ?? randomUUID();
  const artifactsDir = path.resolve(cwd, values["artifacts-dir"] ?? path.join("artifacts", executionId));
  const outputJson = path.resolve(cwd, values["output-json"] ?? path.join(artifactsDir, "report.json"));

  return {
    kind: "run",
    outputJson,
    scenario: {
      baseUrl,
      caseId: values["case-id"] ?? `cli-${randomUUID()}`,
      coupon: values.coupon,
      artifactsDir,
      executionId,
      timeoutMs: parseTimeout(values["timeout-ms"]),
    },
  };
}
