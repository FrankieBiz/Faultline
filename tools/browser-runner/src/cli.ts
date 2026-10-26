#!/usr/bin/env node
/**
 * Browser runner entrypoint.
 *
 * Runs the checkout oracle once, writes the canonical ExecutionReport as
 * JSON, and exits with the contract's code for the run outcome. Stdout
 * carries a short human-readable summary only; the report file is the
 * machine channel.
 */

import { mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { CliUsageError, USAGE, parseCliArgs } from "./cli-args.js";
import { EXIT_CODES, type ExecutionReport } from "./contracts.js";
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
