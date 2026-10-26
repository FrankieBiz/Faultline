import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { RunOutcome } from "../../src/contracts.js";
import { executeCheckoutScenario } from "../../src/oracle.js";

/**
 * Live checkout run against a BuggyShop instance.
 *
 * Environment:
 * - `BUGGYSHOP_BASE_URL`: frontend origin (default `http://127.0.0.1:3000`).
 * - `FAULTLINE_COUPON`: optional coupon to enter at checkout.
 * - `FAULTLINE_EXPECTED_OUTCOME`: run outcome this test requires (default
 *   `passed`; use `assertion_failed` to confirm the seeded defect reproduces).
 */
const baseUrl = process.env.BUGGYSHOP_BASE_URL ?? "http://127.0.0.1:3000";
const expectedOutcome = (process.env.FAULTLINE_EXPECTED_OUTCOME ?? "passed") as RunOutcome;

test("checkout scenario produces the expected outcome", async ({ browser }, testInfo) => {
  const { report, outcome } = await executeCheckoutScenario({
    baseUrl,
    caseId: `e2e-${randomUUID()}`,
    coupon: process.env.FAULTLINE_COUPON,
    browser,
    artifactsDir: testInfo.outputPath("evidence"),
  });

  await testInfo.attach("execution-report.json", {
    body: JSON.stringify(report, null, 2),
    contentType: "application/json",
  });

  const failed = report.assertions
    .filter((assertion) => !assertion.passed)
    .map((assertion) => `${assertion.id}: ${assertion.observed}`);
  expect(outcome, failed.join("\n") || "all assertions passed").toBe(expectedOutcome);
});
