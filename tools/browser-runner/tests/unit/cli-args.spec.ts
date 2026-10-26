import path from "node:path";
import { expect, test } from "@playwright/test";
import { CliUsageError, parseCliArgs } from "../../src/cli-args.js";

test.describe("parseCliArgs", () => {
  test("maps every flag onto scenario options", () => {
    const command = parseCliArgs(
      [
        "--base-url",
        "http://127.0.0.1:3000",
        "--case-id",
        "case-7",
        "--coupon",
        "tenoff",
        "--output-json",
        "out/report.json",
        "--artifacts-dir",
        "out/evidence",
        "--timeout-ms",
        "15000",
        "--execution-id",
        "exec-1",
      ],
      "/work",
    );
    expect(command).toEqual({
      kind: "run",
      outputJson: path.resolve("/work", "out/report.json"),
      scenario: {
        baseUrl: "http://127.0.0.1:3000",
        caseId: "case-7",
        coupon: "tenoff",
        artifactsDir: path.resolve("/work", "out/evidence"),
        executionId: "exec-1",
        timeoutMs: 15000,
      },
    });
  });

  test("defaults the report into the artifacts directory and generates IDs", () => {
    const command = parseCliArgs(["--base-url", "http://127.0.0.1:3000"], "/work");
    if (command.kind !== "run") throw new Error("expected a run command");
    expect(command.scenario.caseId).toMatch(/^cli-[0-9a-f-]{36}$/);
    expect(command.scenario.artifactsDir).toBe(path.resolve("/work", "artifacts", command.scenario.executionId));
    expect(command.outputJson).toBe(path.join(command.scenario.artifactsDir, "report.json"));
    expect(command.scenario.timeoutMs).toBeUndefined();
  });

  test("rejects missing, unknown, and out-of-range input", () => {
    expect(() => parseCliArgs([])).toThrow(CliUsageError);
    expect(() => parseCliArgs(["--base-url", "http://x", "--bogus"])).toThrow(CliUsageError);
    expect(() => parseCliArgs(["--base-url", "http://x", "--timeout-ms", "60000"])).toThrow(CliUsageError);
    expect(() => parseCliArgs(["--base-url", "http://x", "--job-id", "job-1"])).toThrow(CliUsageError);
  });

  test("returns help", () => {
    expect(parseCliArgs(["--help"])).toEqual({ kind: "help" });
  });
});
