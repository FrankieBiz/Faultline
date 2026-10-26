/**
 * Command-line parsing for the browser runner, kept separate from the
 * entrypoint so it can be unit-tested without launching a browser.
 */

import { randomUUID } from "node:crypto";
import path from "node:path";
import { parseArgs } from "node:util";
import { MAX_TIMEOUT_MS, type CheckoutScenarioOptions } from "./oracle.js";

/** Usage text printed for `--help` and argument errors. */
export const USAGE = `Usage: faultline-browser-runner --base-url <url> [options]

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

Exit codes: 0 passed, 1 assertion failed, 2 runner/infrastructure error, 3 timed out.`;

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
  | { kind: "run"; scenario: CheckoutScenarioOptions & { artifactsDir: string; executionId: string }; outputJson: string };

function parseTimeout(raw: string | undefined): number | undefined {
  if (raw === undefined) return undefined;
  if (!/^\d+$/.test(raw)) throw new CliUsageError(`--timeout-ms must be a whole number of milliseconds; received "${raw}".`);
  const value = Number(raw);
  if (value > MAX_TIMEOUT_MS) throw new CliUsageError(`--timeout-ms cannot exceed ${MAX_TIMEOUT_MS}.`);
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
        help: { type: "boolean", short: "h" },
      },
    }));
  } catch (error) {
    throw new CliUsageError(error instanceof Error ? error.message : String(error));
  }

  if (values.help) return { kind: "help" };

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
