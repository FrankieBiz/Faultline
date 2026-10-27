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
    if (path === "jobs" && request.method() === "GET") return route.fulfill({ json: { jobs: options.detail ? [job()] : [] } });
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

test("blocked execution is actionable and never claims a repair", async ({ page }) => {
  await mock(page, { readiness: { ...ready, status: "blocked", runtime_ready: false, reason: "isolated_runtime_unavailable" } });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Run live repair" })).toBeDisabled();
  await expect(page.getByText(/No isolated runtime is configured/)).toBeVisible();
  await expect(page.getByText("No jobs recorded yet.", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toHaveCount(0);
});

test("deterministic mode is visible and authored previews never submit jobs", async ({ page }) => {
  const calls = await mock(page);
  await page.goto("/");
  await expect(page.getByText(/Deterministic fallback/)).toBeVisible();
  await page.getByRole("button", { name: /Unregistered Coupon/ }).click();
  await expect(page.getByText(/HTTP 400 · Invalid coupon code/)).toBeVisible();
  expect(calls.posts).toBe(0);
});

for (const state of ["cancelled", "interrupted"]) {
  test(`${state} is terminal and stops polling`, async ({ page }) => {
    const calls = await mock(page, { detail: detail(state) });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: state === "cancelled" ? "Cancelled" : "Interrupted", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run live repair" })).toBeEnabled();
    const count = calls.detail;
    await page.waitForTimeout(1700);
    expect(calls.detail).toBe(count);
  });
}

test("reset errors stay visible and do not report success", async ({ page }) => {
  await mock(page, { resetFails: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Reset environment" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Reset could not reconcile" })).toBeVisible();
  await expect(page.getByText("Environment reset.", { exact: false })).toHaveCount(0);
});

test("legacy verified labels are explicitly untrusted", async ({ page }) => {
  await mock(page, { detail: detail("succeeded", "verified") });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Unverified historical result" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toHaveCount(0);
});

test("reloading reattaches to an unfinished job and observes its terminal state", async ({ page }) => {
  let completed = false;
  await mock(page, { detail: detail("running", null) });
  await page.route(`**/api/faultline/jobs/${id}`, (route) => route.fulfill({ json: completed ? detail("interrupted") : detail("running", null) }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Running/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Cancel job" })).toBeVisible();
  completed = true;
  await expect(page.getByRole("heading", { name: "Interrupted", exact: true })).toBeVisible();
});

test("mobile preview fits and keyboard controls have a visible focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mock(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Run live repair" })).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to repair controls" })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const missingNames = await page.getByRole("button").evaluateAll((buttons) => buttons.filter((button) => !(button.textContent?.trim() || button.getAttribute("aria-label"))).length);
  expect(missingNames).toBe(0);
});
