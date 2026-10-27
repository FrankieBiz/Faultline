import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test, type Browser } from "@playwright/test";
import { executeCheckoutScenario } from "../../src/oracle.js";

test("a screenshot capture failure is an infrastructure error", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "faultline-missing-screenshot-"));
  // This fake browser isolates the evidence failure without Chromium or an app.
  // The page also has an app assertion failure, which must not mask lost evidence.
  const page = {
    on: () => undefined,
    goto: async () => { throw new Error("test-only application navigation failure"); },
    screenshot: async () => { throw new Error("test-only screenshot capture failure"); },
  };
  const context = {
    tracing: {
      start: async () => undefined,
      stop: async (options: { path: string }) => { await writeFile(options.path, "test-only trace bytes"); },
    },
    newPage: async () => page,
    request: {
      get: async () => ({ status: () => 200, text: async () => '{"orders":[]}' }),
    },
    close: async () => undefined,
  };
  const browser = { newContext: async () => context } as unknown as Browser;
  try {
    const run = await executeCheckoutScenario({
      baseUrl: "http://127.0.0.1:3000", caseId: "test-missing-screenshot", browser, artifactsDir: root,
    });
    expect(run.outcome).toBe("infrastructure_error");
    expect(run.report.verdict).toBe("error");
    expect(run.report.observations).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: "runner_error", data: expect.objectContaining({ step: "capture_screenshot" }) }),
    ]));
    expect(run.manifest.artifacts.some((entry) => entry.role.endsWith("screenshot"))).toBe(false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
