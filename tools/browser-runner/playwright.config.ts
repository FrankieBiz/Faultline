import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright Test configuration for the trusted runner.
 *
 * - `unit` runs the pure oracle logic (assertions, expectations, CLI parsing)
 *   with no browser and no running application.
 * - `chromium-e2e` runs the checkout-flow oracle against a live BuggyShop at
 *   `BUGGYSHOP_BASE_URL` in headless Chromium.
 *
 * SpecV1 §4 requires one worker, zero retries, a JSON reporter, and tracing
 * for every execution. The oracle records its own trace for the case context
 * it creates, so Playwright Test's automatic tracing stays off to avoid two
 * recorders competing for the same context.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 30_000,
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  outputDir: "test-results/output",
  use: {
    headless: true,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "unit",
      testDir: "./tests/unit",
    },
    {
      name: "chromium-e2e",
      testDir: "./tests/e2e",
      use: { ...devices["Desktop Chrome"], headless: true },
    },
  ],
});
