#!/usr/bin/env node
/**
 * Browser runner entrypoint.
 *
 * Runs the checkout oracle once, writes the canonical ExecutionReport as
 * JSON, and exits with the contract's code for the run outcome. Stdout
 * carries a short human-readable summary only; the report file is the
 * machine channel.
 *
 * `--crawl <url>` instead runs the autonomous crawler and prints its
 * progress and CrawlReport on stdout (one JSON event per line with
 * `--ndjson`).
 */

import { mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { CliUsageError, USAGE, parseCliArgs, type CliCommand } from "./cli-args.js";
import { EXIT_CODES, type ExecutionReport } from "./contracts.js";
import { CrawlOptionsError, describeSignal, formatCrawlEvent, runAutonomousCrawler, type CrawlEvent, type CrawlReport } from "./crawler.js";
import { ScenarioOptionsError, executeCheckoutScenario, type ScenarioRun } from "./oracle.js";

const INFRASTRUCTURE_EXIT = EXIT_CODES.infrastructure_error;

/** Writes the report atomically so a reader never sees a partial file. */
async function writeReport(target: string, report: ExecutionReport): Promise<void> {
  await mkdir(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`, { encoding: "utf8", mode: 0o644 });
  await rename(temporary, target);
}

function printSummary(run: ScenarioRun, outputJson: string): void {
  const { report } = run;
  const lines = [
    `${report.scenario_id} ${run.outcome} (verdict ${report.verdict}, execution ${report.execution_id}, case ${report.case_id})`,
  ];
  for (const assertion of report.assertions) {
    lines.push(`  ${assertion.passed ? "pass" : "FAIL"}  ${assertion.id}: ${assertion.observed}`);
  }
  for (const observation of report.observations.filter((entry) => entry.kind !== "assertion")) {
    lines.push(`  observed ${observation.kind} (${observation.source}): ${observation.message}`);
  }
  lines.push(`  report: ${outputJson}`);
  lines.push(`  evidence: ${run.artifactsDir} (${run.manifest.artifacts.length} files, see artifacts.json)`);
  process.stdout.write(`${lines.join("\n")}\n`);
}

const CRAWL_EXIT_CODES: Readonly<Record<CrawlReport["status"], number>> = { clean: 0, failure: 1, error: INFRASTRUCTURE_EXIT };

/** Runs the autonomous crawler, streaming progress as text or NDJSON on stdout. */
async function crawl(command: Extract<CliCommand, { kind: "crawl" }>): Promise<number> {
  const onEvent = (event: CrawlEvent): void => {
    if (command.ndjson) {
      process.stdout.write(`${JSON.stringify(event)}\n`);
      return;
    }
    const line = formatCrawlEvent(event);
    if (line) process.stdout.write(`${line}\n`);
  };
  let report: CrawlReport;
  try {
    report = await runAutonomousCrawler({ url: command.url, maxActions: command.maxActions, timeoutMs: command.timeoutMs, onEvent });
  } catch (error) {
    if (error instanceof CrawlOptionsError) {
      process.stderr.write(`${error.message}\n`);
      return INFRASTRUCTURE_EXIT;
    }
    throw error;
  }
  if (!command.ndjson) {
    const verdict =
      report.status === "failure"
        ? `Defect intercepted at step ${report.failure.step}: ${describeSignal(report.failure)}`
        : report.status === "clean"
          ? `Clean: no failure after ${report.actions_taken} actions (${report.stop_reason}).`
          : `Crawl error: ${report.error}`;
    process.stdout.write(`${verdict}\n${JSON.stringify(report, null, 2)}\n`);
  }
  return CRAWL_EXIT_CODES[report.status];
}

async function main(): Promise<number> {
  let command;
  try {
    command = parseCliArgs(process.argv.slice(2));
  } catch (error) {
    if (error instanceof CliUsageError) {
      process.stderr.write(`${error.message}\n\n${USAGE}\n`);
      return INFRASTRUCTURE_EXIT;
    }
    throw error;
  }

  if (command.kind === "help") {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }
  if (command.kind === "crawl") return crawl(command);

  let run: ScenarioRun;
  try {
    run = await executeCheckoutScenario(command.scenario);
  } catch (error) {
    if (error instanceof ScenarioOptionsError) {
      process.stderr.write(`${error.message}\n`);
      return INFRASTRUCTURE_EXIT;
    }
    throw error;
  }

  await writeReport(command.outputJson, run.report);
  printSummary(run, command.outputJson);
  return EXIT_CODES[run.outcome];
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error: unknown) => {
    process.stderr.write(`browser runner failed: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`);
    process.exitCode = INFRASTRUCTURE_EXIT;
  },
);
