import { expect, test, type Page } from "@playwright/test";

const id = "00000000-0000-4000-8000-000000000001";
const ready = {
  status: "ready", runtime_ready: true, quarantined: false, reason: null,
  model: { available: true, provider: "deterministic", model: "deterministic-checkout-v1", reason: null, prompt_tokens: null, completion_tokens: null },
};
function job(state = "cancelled", outcome: string | null = state) {
  return {
    id, scenario_id: "scripted_checkout_repair", state, stage: state === "running" ? "baseline" : "completed", outcome,
    cleanup_status: "succeeded", created_at: "2026-10-27T12:00:00Z", updated_at: "2026-10-27T12:00:02Z",
    requested_mode: "repair", effective_mode: "repair", repair_block_reason: null, cancel_requested: false, error_details: null,
  };
}
function detail(state = "cancelled", outcome: string | null = state) {
  return { job: job(state, outcome), baseline: null, attempts: [], executions: [], artifacts: [], events: [] };
}
async function mock(page: Page, options: { readiness?: object; detail?: object; resetFails?: boolean } = {}) {
  const calls = { posts: 0, detail: 0 };
  await page.route("**/api/faultline/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/faultline/", "");
    if (path === "readiness") return route.fulfill({ json: options.readiness ?? ready });
    if (path === "jobs" && request.method() === "GET") return route.fulfill({ json: { jobs: options.detail ? [(options.detail as { job: ReturnType<typeof job> }).job] : [] } });
    if (path === "reset") return route.fulfill(options.resetFails ? { status: 503, json: { error: { code: "reset_failed" } } } : { json: { status: "ok" } });
    if (path === "jobs" && request.method() === "POST") {
      calls.posts++;
      return route.fulfill({ status: 202, json: { job_id: id, effective_mode: "repair", repair_block_reason: null } });
    }
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (path === `jobs/${id}`) { calls.detail++; return route.fulfill({ json: options.detail ?? detail() }); }
    return route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });
  return calls;
}

async function inspectPastRun(page: Page) {
  await page.getByText(/Past runs ·/).click();
  await page.getByRole("button", { name: `Inspect job ${id.slice(0, 8)}` }).first().click();
}

test("blocked execution is actionable and never claims a repair", async ({ page }) => {
  await mock(page, { readiness: { ...ready, status: "blocked", runtime_ready: false, reason: "isolated_runtime_unavailable" } });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Run the demo" })).toBeDisabled();
  await expect(page.getByText(/No isolated runtime is configured/)).toBeVisible();
  await expect(page.getByText("No past runs yet.")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toHaveCount(0);
});

test("deterministic mode is visible and authored previews never submit jobs", async ({ page }) => {
  const calls = await mock(page);
  await page.goto("/");
  await expect(page.getByText(/Deterministic fallback/)).toBeVisible();
  const preview = page.locator("details.preview");
  await expect(preview).not.toHaveAttribute("open");
  await preview.locator("summary").click();
  await page.getByRole("button", { name: /Unregistered Coupon/ }).click();
  await expect(page.getByText(/HTTP 400 · Invalid coupon code/)).toBeVisible();
  expect(calls.posts).toBe(0);
});

for (const state of ["cancelled", "interrupted"]) {
  test(`${state} is terminal and stops polling`, async ({ page }) => {
    const calls = await mock(page, { detail: detail(state) });
    await page.goto("/");
    await inspectPastRun(page);
    await expect(page.getByRole("heading", { name: state === "cancelled" ? "Cancelled" : "Interrupted", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run it again" })).toBeEnabled();
    const count = calls.detail;
    await page.waitForTimeout(1700);
    expect(calls.detail).toBe(count);
  });
}

test("reset errors stay visible and do not report success", async ({ page }) => {
  await mock(page, { resetFails: true });
  await page.goto("/");
  await page.getByText("Setup and recovery").click();
  await page.getByRole("button", { name: "Reset environment" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Reset could not reconcile" })).toBeVisible();
  await expect(page.getByText("Environment reset.", { exact: false })).toHaveCount(0);
});

test("legacy verified labels are explicitly untrusted", async ({ page }) => {
  await mock(page, { detail: detail("succeeded", "verified") });
  await page.goto("/");
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Unverified result" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toHaveCount(0);
});

test("reloading reattaches to an unfinished job and observes its terminal state", async ({ page }) => {
  let completed = false;
  await mock(page, { detail: detail("running", null) });
  await page.route(`**/api/faultline/jobs/${id}`, (route) => route.fulfill({ json: completed ? detail("interrupted") : detail("running", null) }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Running/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Stop run" })).toBeVisible();
  completed = true;
  await expect(page.getByRole("heading", { name: "Interrupted", exact: true })).toBeVisible();
});

test("mobile preview fits and keyboard controls have a visible focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mock(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Run the demo" })).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to repair controls" })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const missingNames = await page.getByRole("button").evaluateAll((buttons) => buttons.filter((button) => !(button.textContent?.trim() || button.getAttribute("aria-label"))).length);
  expect(missingNames).toBe(0);
});

test("retries show verifier feedback and non-Meta endpoints are never labeled Meta", async ({ page }) => {
  const attempt = (number: number, extra: object) => ({
    id: `00000000-0000-4000-8000-00000000001${number}`, attempt_number: number,
    prompt_tokens: 900, completion_tokens: 120, raw_patch: null, parsed_diff: null, outcome: "verification_failed",
    validation_result: { provider: "local", model: "qwen2.5-coder:14b", generation_ms: 4200, is_valid: true, syntax_valid: true, ast_safe: true, ...extra },
  });
  const prior = { gate: "verification_failed", policy_error: null, failed_check_count: 2, failed_checks: ["regression.empty_coupon", "regression.whitespace_coupon"], included_rejected_diff: true };
  await mock(page, {
    readiness: {
      ...ready, model: { ...ready.model, provider: "local", model: "qwen2.5-coder:14b" },
      resource_limits: { requested: "required", mode: "cgroup-v2-scope", enforcement_preflight: "passed", reason: null, configured: { memory_max_bytes: 536870912, tasks_max: 64, cpu_quota_percent: 100 } },
    },
    detail: { ...detail("failed", "unresolved"), attempts: [attempt(1, {}), attempt(2, { prior_feedback: prior })] },
  });
  await page.goto("/");
  await expect(page.getByText(/Local model endpoint · qwen2\.5-coder:14b · not a Meta-hosted call/).first()).toBeVisible();
  await expect(page.getByText("Meta Model API")).toHaveCount(0);
  await inspectPastRun(page);
  await page.getByText("Explore the full run details").click();
  const feedback = page.locator(".feedback");
  await expect(feedback).toContainText("Gate feedback from attempt 1");
  await expect(feedback).toContainText("2 failing checks sent back as evidence");
  await expect(feedback.getByText("regression.whitespace_coupon")).toBeVisible();
  await expect(page.getByText("generated in 4.2 s").first()).toBeVisible();
  await page.getByText("Setup and recovery").click();
  await expect(page.getByText("cgroup v2 · 512 MiB · 64 tasks · 100% CPU · enforced")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("judge guidance explains isolated verification and terminal updates", async ({ page }) => {
  await mock(page, { detail: detail() });
  await page.goto("/");
  await page.getByText("Want to try the broken checkout yourself?").click();
  await expect(page.getByRole("link", { name: "Open seeded storefront" })).toHaveAttribute("href", `http://127.0.0.1:${process.env.BUGGYSHOP_PORT ?? "3000"}`);
  await expect(page.getByText(/candidate is tested in isolation/)).toBeVisible();
  await expect(page.getByText(/Nothing is deployed to production/)).toBeVisible();
  await inspectPastRun(page);
  await page.getByText("Explore the full run details").click();
  await expect(page.getByText("Complete · job finished", { exact: true })).toBeVisible();
  await expect(page.getByText("closed", { exact: true })).toHaveCount(0);
});

test("job history exposes provider and outcome and selects earlier evidence", async ({ page }) => {
  const earlierId = "00000000-0000-4000-8000-000000000002";
  const earlier = {
    ...detail("succeeded", "verified"),
    job: { ...job("succeeded", "verified"), id: earlierId },
    attempts: [{ id: "attempt-1", attempt_number: 1, prompt_tokens: 123, completion_tokens: 45,
      raw_patch: null, parsed_diff: null, outcome: "verified",
      validation_result: { provider: "meta", model: "muse-spark-1.3" } }],
  };
  await mock(page, { detail: detail() });
  await page.route("**/api/faultline/jobs?*", (route) => route.fulfill({ json: { jobs: [job(), earlier.job] } }));
  await page.route(`**/api/faultline/jobs/${earlierId}`, (route) => route.fulfill({ json: earlier }));
  await page.goto("/");
  await page.getByText("Past runs · 2 recent runs", { exact: true }).click();
  const row = page.locator(".history li").filter({ hasText: earlierId.slice(0, 8) }).filter({ hasText: "Meta Model API" });
  await expect(row).toContainText("verified");
  await expect(row).toContainText("muse-spark-1.3");
  await page.getByRole("button", { name: `Inspect job ${earlierId.slice(0, 8)}` }).last().click();
  await expect(page.getByRole("heading", { name: "Unverified result" })).toBeVisible();
});


test("large evidence lists are collapsed with counts and direct review downloads", async ({ page }) => {
  const execution = (phase: "baseline" | "verification") => ({
    phase, runtime_kind: "isolated-browser", attempt_id: null, candidate_snapshot_sha256: "abc123", artifact_ids: [],
    report: { execution_id: phase, verdict: phase === "baseline" ? "failed" : "passed", duration_ms: 100,
      observations: [], assertions: Array.from({ length: 44 }, (_, i) => ({ id: `check-${i}`, passed: phase !== "baseline" || i > 0, expected: "201", observed: phase === "baseline" && i === 0 ? "500" : "201" })) },
  });
  const baseline = execution("baseline");
  const verification = execution("verification");
  await mock(page, { detail: { ...detail("succeeded", "verified"), baseline, executions: [baseline, verification],
    artifacts: [{ id: "summary", execution_id: null, attempt_id: null, role: "proof_bundle_md", content_type: "text/markdown", size_bytes: 100, sha256: "abc123" }],
  } });
  await page.goto("/");
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toBeVisible();
  await page.getByText("Explore the full run details").click();
  await expect(page.getByText("Baseline · 43 of 44 passed · 1 failed", { exact: true })).toBeVisible();
  await expect(page.getByText("Verification, attempt ? · 44 of 44 passed", { exact: true })).toBeVisible();
  await expect(page.locator(".asserts").first()).toBeHidden();
  await expect(page.locator(".asserts").last()).toBeHidden();
  await expect(page.getByRole("link", { name: "Download review summary", exact: true })).toBeVisible();
  await expect(page.locator("#artifacts-h + .evidence-actions + details")).not.toHaveAttribute("open");
  await expect(page.locator("#events-h + details")).not.toHaveAttribute("open");
});

test("slow history provider lookup does not delay the latest job", async ({ page }) => {
  const oldId = "10000000-0000-4000-8000-000000000002";
  await mock(page, { detail: detail() });
  await page.route("**/api/faultline/jobs?*", (route) => route.fulfill({ json: { jobs: [job(), { ...job(), id: oldId }] } }));
  await page.route(`**/api/faultline/jobs/${oldId}`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    await route.fulfill({ json: { ...detail(), job: { ...job(), id: oldId } } });
  });
  await page.goto("/");
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Cancelled", exact: true })).toBeVisible({ timeout: 1000 });
});


test("fresh visit gives one clear action and immediately shows its result", async ({ page }) => {
  const calls = await mock(page, { detail: detail("succeeded", "verified") });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Watch FaultLine fix a broken checkout." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Unverified result" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Run the demo" })).toBeEnabled();
  await expect(page.locator(".manual-walkthrough")).not.toHaveAttribute("open");
  await page.getByRole("button", { name: "Run the demo" }).click();
  await expect(page.getByRole("heading", { name: "Unverified result" })).toBeVisible();
  expect(calls.posts).toBe(1);
  await expect(page.getByRole("button", { name: "Run it again" })).toBeEnabled();
});
