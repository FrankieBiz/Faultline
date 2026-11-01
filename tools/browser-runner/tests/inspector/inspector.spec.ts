import { expect, test, type Page } from "@playwright/test";

const id = "00000000-0000-4000-8000-000000000001";
const target = "apps/buggyshop-backend/app/routes/checkout.py";
const fingerprint = "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'";
const ready = {
  status: "ready", runtime_ready: true, quarantined: false, reason: null,
  model: { available: true, provider: "deterministic", model: "deterministic-checkout-v1", reason: null, prompt_tokens: null, completion_tokens: null },
};
const pack = {
  id: "scripted_checkout_repair", title: "E-Commerce Checkout Defect",
  description: "Optional-coupon backend defect causing TypeError during arithmetic when coupon is omitted or empty",
  target_file: target, route: "POST /api/checkout", error_fingerprint: fingerprint,
  expected_assertions: Array.from({ length: 8 }, (_, i) => `checkout.check_${i}`),
};
const checkoutBody = { items: [{ product_id: "trail-mug", quantity: 2 }] };
const rule = {
  id: "checkout.no_coupon", source: "config", title: "Checkout without a coupon creates an order",
  description: "Two Trail Mugs and no coupon: HTTP 201, zero discount, total equal to subtotal.",
  method: "POST", url: "http://127.0.0.1:{port}/api/checkout", expected_status: 201, has_body: true, body: checkoutBody,
  assertions: [{ path: "$.discount", equals: 0 }, { path: "$.total", equals_path: "$.subtotal" }],
  fingerprint: null, created_at: null, needs_port: false, default_port: 8000, latest_check: null,
  repro: null as null | { id: string; steps: object[] }, live_note: null as null | string,
};
/** A faultline.toml [scenarios.checkout_api] entry: a two-request ReproSpec. */
const scenario = {
  ...rule, id: "scenario.checkout_api", source: "scenario", title: "Checkout without a coupon", description: null,
  has_body: false, body: null, expected_status: null, assertions: [],
  repro: { id: "checkout_api", steps: [
    { id: "no_coupon", action: "request", method: "POST", path: "/api/checkout", body: checkoutBody },
    { id: "no_coupon.status", action: "assert", source: "no_coupon", check: { status: 201 } },
    { id: "no_coupon.discount", action: "assert", source: "no_coupon", check: { path: "$.discount", equals: 0 } },
    { id: "unknown", action: "request", method: "POST", path: "/api/checkout", body: { ...checkoutBody, coupon_code: "NOTVALID" } },
    { id: "unknown.status", action: "assert", source: "unknown", check: { status: 400 } },
  ] },
};
const health = {
  ...rule, id: "service_health", title: "Service returns HTTP 200 on health check", description: null,
  method: "GET", url: "http://127.0.0.1:{port}/healthz", expected_status: 200, has_body: false, body: null, assertions: [],
  needs_port: true, default_port: null,
};
const listing = {
  scenarios: [pack], invariants: [scenario, rule, health],
  project: { name: "buggyshop", config_path: "faultline.toml", errors: ["faultline.toml invariants.rule[3] (broken) ignored: duplicate id"] },
};
const seededStore = { state: "seeded", target_file: target, sha256: "abc", url: "http://127.0.0.1:8000", applied_job_id: null, applied_at: null };

function session(status: number | null, passed: boolean, extra: object = {}) {
  return {
    session_id: crypto.randomUUID(), status, duration_ms: 12.4, content_type: "application/json", truncated: false,
    excerpt: status === 500 ? JSON.stringify({ detail: fingerprint }) : "{}", fingerprint: status === 500 ? fingerprint : null, error: null,
    assertions: status === null ? [] : [{ id: "status", label: "HTTP status", passed, expected: "201", observed: String(status) }],
    requests: status === null ? [] : [{ step_id: "request", method: "POST", path: "/api/checkout", status, duration_ms: 12.4 }],
    ...extra,
  };
}
function check(invariantId: string, outcome: "detected" | "no_failure" | "infrastructure_error", extra: object = {}) {
  const failing = outcome === "detected";
  return {
    id: crypto.randomUUID(), invariant_id: invariantId, created_at: "2026-10-30T12:00:00Z", method: "POST",
    url: "http://127.0.0.1:8000/api/checkout", outcome,
    reason: failing ? "same_failure_reproduced_twice" : outcome === "no_failure" ? "failure_not_reproduced_twice" : "execution_or_cleanup_failed",
    sessions: outcome === "infrastructure_error" ? [session(null, false, { error: "ConnectError", excerpt: null })]
      : [session(failing ? 500 : 201, !failing), session(failing ? 500 : 201, !failing)],
    repair: failing ? { scenario_id: pack.id, title: pack.title, target_file: target } : null,
    repair_note: failing ? "Same route and server fingerprint as E-Commerce Checkout Defect. Its sandbox pipeline reproduces the failure again in isolation before any model call." : null,
    ...extra,
  };
}
function job(state = "cancelled", outcome: string | null = state) {
  return {
    id, scenario_id: pack.id, state, stage: state === "running" ? "baseline" : "completed", outcome,
    cleanup_status: "succeeded", created_at: "2026-10-27T12:00:00Z", updated_at: "2026-10-27T12:00:02Z",
    requested_mode: "repair", effective_mode: "repair", repair_block_reason: null, cancel_requested: false, error_details: null,
  };
}
function detail(state = "cancelled", outcome: string | null = state) {
  return { job: job(state, outcome), baseline: null, attempts: [], executions: [], artifacts: [], events: [] };
}
/** A record that satisfies every verification condition: failed isolated baseline, passing candidate, cleanup. */
function verifiedDetail() {
  const attemptId = "00000000-0000-4000-8000-000000000021";
  const diff = `--- a/${target}\n+++ b/${target}\n@@ -40,3 +40,3 @@\n-    discount = cast(int, discounts.get(coupon_code))\n+    discount = cast(int, discounts.get(coupon_code, 0))\n     total = subtotal - discount`;
  const run = (phase: "baseline" | "verification", count: number, failed: number) => ({
    phase, runtime_kind: "isolated-browser", attempt_id: phase === "verification" ? attemptId : null, candidate_snapshot_sha256: "abc123", artifact_ids: [],
    report: { execution_id: phase, verdict: failed ? "failed" : "passed", duration_ms: 1000,
      observations: phase === "baseline" ? [
        { id: "o1", kind: "http_error", source: "POST /api/checkout", message: "POST /api/checkout returned HTTP 500: {}", data: { status: 500 } },
        { id: "o2", kind: "server_exception", source: target, message: fingerprint, data: {} },
      ] : [],
      assertions: Array.from({ length: count }, (_, i) => ({ id: `check-${i}`, passed: i >= failed, expected: "201", observed: i >= failed ? "201" : "500" })) },
  });
  const baseline = run("baseline", 18, 12);
  const verification = run("verification", 44, 0);
  return { ...detail("succeeded", "verified"), baseline, executions: [baseline, verification], artifacts: [],
    attempts: [{ id: attemptId, attempt_number: 1, prompt_tokens: null, completion_tokens: null, raw_patch: null, parsed_diff: diff, outcome: "verified",
      validation_result: { provider: "deterministic", model: "deterministic-checkout-v1", generation_ms: 0, is_valid: true, syntax_valid: true, ast_safe: true, target_file: target } }],
  };
}

/** The wire shape the mock serves; invariants are loose records so tests can add probes. */
type Listing = { scenarios: object[]; invariants: ({ id: string } & Record<string, unknown>)[]; project: object };
type Options = {
  readiness?: object; detail?: object; resetFails?: boolean; listing?: Listing; store?: object;
  checks?: Record<string, object[]>; onCheck?: (invariantId: string, body: unknown) => object;
  register?: (body: Record<string, unknown>) => { status: number; json: object } | undefined;
  apply?: () => { status: number; json: object };
  /** Answers POST crawl; without it the engine has no crawler endpoint (HTTP 404). */
  crawl?: (body: Record<string, unknown>) => { status: number; json?: object; ndjson?: object[] };
};
async function mock(page: Page, options: Options = {}) {
  const calls = { posts: 0, detail: 0, jobBodies: [] as Record<string, unknown>[], checks: [] as { id: string; body: unknown }[], registered: [] as Record<string, unknown>[], applies: 0, reverts: 0, removes: 0, crawls: [] as Record<string, unknown>[] };
  let current: Listing = structuredClone(options.listing ?? listing);
  let store = options.store ?? seededStore;
  await page.route("**/api/faultline/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/faultline/", "");
    const post = request.method() === "POST";
    if (path === "readiness") return route.fulfill({ json: options.readiness ?? ready });
    if (path === "scenarios") return route.fulfill({ json: current });
    if (path === "store") return route.fulfill({ json: store });
    if (path === "jobs" && !post) return route.fulfill({ json: { jobs: options.detail ? [(options.detail as { job: ReturnType<typeof job> }).job] : [] } });
    if (path === "reset") return route.fulfill(options.resetFails ? { status: 503, json: { error: { code: "reset_failed" } } } : { json: { status: "ok" } });
    if (path === "jobs" && post) {
      calls.posts++;
      calls.jobBodies.push(request.postDataJSON());
      return route.fulfill({ status: 202, json: { job_id: id, effective_mode: "repair", repair_block_reason: null } });
    }
    if (path === "invariants" && post) {
      const body = request.postDataJSON() as Record<string, unknown>;
      calls.registered.push(body);
      const response = options.register?.(body);
      if (response) return route.fulfill(response);
      const created = { ...rule, id: "probe-0123456789ab", source: "probe", title: String(body.title ?? `${body.method} ${body.url}`), description: null,
        method: body.method, url: body.url, expected_status: body.expected_status, has_body: "body" in body, body: body.body ?? null,
        assertions: [], needs_port: false, default_port: 8000, created_at: "2026-10-30T12:00:00Z" };
      current = { ...current, invariants: [...current.invariants, created] };
      return route.fulfill({ status: 201, json: created });
    }
    const invariant = path.match(/^invariants\/([^/]+)\/(check|checks|remove)$/);
    if (invariant) {
      const [, invariantId = "", action = ""] = invariant;
      if (action === "checks") return route.fulfill({ json: { checks: options.checks?.[invariantId] ?? [] } });
      if (action === "remove") {
        calls.removes++;
        current = { ...current, invariants: current.invariants.filter((i) => i.id !== invariantId) };
        return route.fulfill({ json: { status: "removed" } });
      }
      const body = request.postData() ? request.postDataJSON() : null;
      calls.checks.push({ id: invariantId, body });
      const record = options.onCheck?.(invariantId, body) ?? check(invariantId, "detected");
      current = { ...current, invariants: current.invariants.map((i) => i.id === invariantId ? { ...i, latest_check: record } : i) };
      return route.fulfill({ json: record });
    }
    if (path === `jobs/${id}/apply`) {
      calls.applies++;
      const response = options.apply?.();
      if (response) return route.fulfill(response);
      store = { ...seededStore, state: "patched", applied_job_id: id, applied_at: "2026-10-30T12:05:00Z" };
      return route.fulfill({ json: { status: "applied", store } });
    }
    if (path === "crawl" && post) {
      const body = request.postDataJSON() as Record<string, unknown>;
      calls.crawls.push(body);
      const response = options.crawl?.(body);
      if (!response) return route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
      if (response.ndjson) {
        return route.fulfill({ status: response.status, contentType: "application/x-ndjson", body: response.ndjson.map((e) => JSON.stringify(e)).join("\n") + "\n" });
      }
      return route.fulfill({ status: response.status, json: response.json ?? {} });
    }
    if (path === "revert") {
      calls.reverts++;
      store = seededStore;
      return route.fulfill({ json: { status: "reverted", store } });
    }
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (path === `jobs/${id}`) { calls.detail++; return route.fulfill({ json: options.detail ?? detail() }); }
    return route.fulfill({ status: 404, json: { error: { code: "not_found" } } });
  });
  return calls;
}

async function inspectPastRun(page: Page) {
  await page.getByText(/Past sandbox runs ·/).click();
  await page.getByRole("button", { name: `Inspect job ${id.slice(0, 8)}` }).first().click();
}
const rail = (page: Page) => page.getByRole("navigation", { name: "Scenarios" });
const runRepair = (page: Page) => page.getByRole("button", { name: "Run sandbox repair" });
// Next.js renders its own empty role="alert" route announcer, so scope to the dashboard notice.
const notice = (page: Page) => page.locator("#workspace > .notice[role=alert]");

test("blocked execution is actionable and never claims a repair", async ({ page }) => {
  await mock(page, { readiness: { ...ready, status: "blocked", runtime_ready: false, reason: "isolated_runtime_unavailable" } });
  await page.goto("/");
  await expect(runRepair(page)).toBeDisabled();
  await expect(page.getByText(/No isolated runtime is configured/)).toBeVisible();
  await expect(page.getByText("No sandbox runs yet.")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toHaveCount(0);
  await page.route("**/api/faultline/readiness", (route) => route.fulfill({ json: ready }));
  await page.getByRole("button", { name: "Check again" }).click();
  await expect(runRepair(page)).toBeEnabled();
  await expect(page.getByRole("button", { name: "Check again" })).toHaveCount(0);
});

test("an unreachable controller says so instead of checking forever", async ({ page }) => {
  await mock(page);
  await page.route("**/api/faultline/readiness", (route) => route.fulfill({ status: 502, json: { error: { message: "Controller unavailable." } } }));
  await page.goto("/");
  await expect(page.getByText("The orchestrator is not reachable through the inspector proxy.")).toBeVisible();
  await expect(page.locator(".workspace .source-line")).toContainText("Unknown until the orchestrator responds");
  await expect(runRepair(page)).toBeDisabled();
  await expect(page.getByRole("button", { name: "Check again" })).toBeVisible();
});

test("the rail lists sandbox repairs, faultline.toml rules, config errors, and added probes", async ({ page }) => {
  await mock(page);
  await page.goto("/");
  const nav = rail(page);
  await expect(nav).toContainText("buggyshop from faultline.toml");
  await expect(nav.getByRole("region", { name: "Repairable defects" }).getByRole("button", { name: /E-Commerce Checkout Defect/ })).toHaveAttribute("aria-current", "true");
  await expect(nav.getByRole("region", { name: "Project checks" }).getByRole("button")).toHaveCount(3);
  await expect(nav.getByText("POST /api/checkout, 2 requests")).toBeVisible();
  await expect(nav.getByText("POST /api/checkout").nth(1)).toBeVisible();
  await expect(nav.getByText(/rule\[3\] \(broken\) ignored: duplicate id/)).toBeVisible();
  await expect(nav.getByText("Test any URL from the bar at the top.")).toBeVisible();
  await expect(page.locator("#workspace").getByText(/Deterministic fallback/)).toBeVisible();
  // The hero names the repair engine exactly as readiness reports it, in amber because it is not Meta.
  await expect(page.locator(".hero-core")).toHaveText("Repair coreDeterministic fallback · deterministic-checkout-v1 · no model call");
  await expect(page.locator(".hero-core")).toHaveAttribute("data-tone", "warn");
  await expect(page.getByRole("heading", { name: "E-Commerce Checkout Defect", level: 1 })).toBeVisible();
  await expect(page.locator(".covering")).toContainText("Checkout without a coupon creates an order");

  await nav.getByRole("button", { name: /Checkout without a coupon creates an order/ }).click();
  await expect(page.getByRole("heading", { name: "Checkout without a coupon creates an order", level: 1 })).toBeVisible();
  await expect(page.locator(".request-line")).toContainText("POST");
  await expect(page.locator(".request-line")).toContainText("http://127.0.0.1:{port}/api/checkout");
  await expect(page.getByText("HTTP status 201; $.discount equals 0; $.total equals $.subtotal")).toBeVisible();
  await expect(page.getByText("Not checked yet.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove this URL" })).toHaveCount(0);
});

test("the new invariant dialog probes a URL, reproduces it twice, and starts the bound sandbox repair", async ({ page }) => {
  const calls = await mock(page, { detail: detail("running", null) });
  await page.route("**/api/faultline/jobs", (route) => route.request().method() === "GET" ? route.fulfill({ json: { jobs: [] } }) : route.fallback());
  await page.goto("/");
  await page.getByRole("button", { name: "Custom URL check" }).click();
  const dialog = page.getByRole("dialog", { name: "Custom URL check" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("URL")).toBeFocused();
  await dialog.getByRole("button", { name: "Fill in the live store checkout" }).click();
  await expect(dialog.getByLabel("Method")).toHaveValue("POST");
  await expect(dialog.getByLabel("URL")).toHaveValue("http://127.0.0.1:8000/api/checkout");
  await expect(dialog.getByLabel("Expected status")).toHaveValue("201");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(dialog).toBeHidden();

  expect(calls.registered).toEqual([{ title: "Checkout without a coupon", method: "POST", url: "http://127.0.0.1:8000/api/checkout", expected_status: 201, body: checkoutBody }]);
  await expect(page.getByRole("heading", { name: "Failing", exact: true })).toBeVisible();
  expect(calls.checks).toEqual([{ id: "probe-0123456789ab", body: {} }]);
  const sessions = page.locator(".session");
  await expect(sessions).toHaveCount(2);
  await expect(sessions.nth(0)).toContainText("500");
  await expect(sessions.nth(1)).toContainText(`Server error: ${fingerprint}`);
  await expect(sessions.nth(0).getByText("expected 201, observed 500")).toBeVisible();
  await expect(page.locator(".repair-callout")).toContainText("Repairable in the sandbox: E-Commerce Checkout Defect");
  await expect.poll(() => calls.posts).toBe(1);
  expect(calls.jobBodies[0]).toMatchObject({ scenario_id: pack.id, mode: "repair" });
  await expect(page.getByText(/Sandbox run in progress/)).toBeVisible();
  const added = rail(page).getByRole("region", { name: "Your custom website" }).getByRole("button");
  await expect(added).toHaveAttribute("aria-current", "true");
  await expect(added).toContainText("last check: failing");
});

test("dialog errors stay in the dialog and Escape closes it", async ({ page }) => {
  const calls = await mock(page, {
    register: () => ({ status: 422, json: { error: { code: "invalid_probe", message: "URL must not contain credentials", job_id: null } } }),
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Custom URL check" }).click();
  const dialog = page.getByRole("dialog", { name: "Custom URL check" });
  await dialog.getByLabel("URL").fill("not a url");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Enter a full URL, such as https://api.example.com/health.");
  // The rejected field is marked, described by the error, and focused so it can be fixed in place.
  await expect(dialog.getByLabel("URL")).toBeFocused();
  await expect(dialog.getByLabel("URL")).toHaveAttribute("aria-invalid", "true");
  await expect(dialog.getByLabel("URL")).toHaveAccessibleDescription("Enter a full URL, such as https://api.example.com/health.");
  await dialog.getByLabel("URL").fill("https://example.com/");
  await dialog.getByLabel("Expected status").fill("42");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Expected status must be a whole number from 100 to 599.");
  await expect(dialog.getByLabel("Expected status")).toBeFocused();
  await expect(dialog.getByLabel("URL")).not.toHaveAttribute("aria-invalid");
  await dialog.getByLabel("Expected status").fill("200");
  await dialog.getByLabel("Method").selectOption("PUT");
  await dialog.getByLabel("URL").fill("https://user:pw@example.com/");
  await dialog.getByLabel(/JSON body/).fill("{not json");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  // The parser's own position is part of the message, so the typo can be found.
  await expect(dialog.getByRole("alert")).toHaveText(/^The request body must be valid JSON: .*position \d+.*\.$/);
  await expect(dialog.getByLabel(/JSON body/)).toBeFocused();
  await expect(dialog.getByLabel(/JSON body/)).toHaveAttribute("aria-invalid", "true");
  expect(calls.registered).toHaveLength(0);
  await dialog.getByLabel(/JSON body/).fill("");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("URL must not contain credentials");
  expect(calls.registered).toEqual([{ method: "PUT", url: "https://user:pw@example.com/", expected_status: 200 }]);
  await expect(dialog.getByLabel(/JSON body/)).not.toHaveAttribute("aria-invalid");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  expect(calls.checks).toHaveLength(0);
  // Reopening keeps the draft but not the last attempt's error.
  await page.getByRole("button", { name: "Custom URL check" }).click();
  await expect(dialog.getByLabel("URL")).toHaveValue("https://user:pw@example.com/");
  await expect(dialog.getByRole("alert")).toHaveCount(0);
});

test("a failure no sandbox repair covers is detection only, and probes can be removed", async ({ page }) => {
  const calls = await mock(page, {
    onCheck: (invariantId) => check(invariantId, "detected", {
      url: "https://api.example.com/orders", repair: null,
      repair_note: "Detection only: no registered sandbox repair covers GET /orders. FaultLine repairs only source it can rebuild and verify in isolation.",
    }),
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Custom URL check" }).click();
  const dialog = page.getByRole("dialog", { name: "Custom URL check" });
  await dialog.getByLabel("URL").fill("https://api.example.com/orders");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(page.getByRole("heading", { name: "Failing", exact: true })).toBeVisible();
  await expect(page.getByText(/Detection only: no registered sandbox repair covers GET \/orders/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Repair in sandbox" })).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(calls.posts).toBe(0);
  await page.getByRole("button", { name: "Remove this URL" }).click();
  await expect(notice(page)).toContainText('Removed "GET https://api.example.com/orders"');
  expect(calls.removes).toBe(1);
  await expect(rail(page).getByText("Test any URL from the bar at the top.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "E-Commerce Checkout Defect", level: 1 })).toBeVisible();
});

test("rules with {port} ask for the port, and outcomes read from the recorded sessions", async ({ page }) => {
  const outcomes = [check("service_health", "infrastructure_error", { url: "http://127.0.0.1:8471/healthz" }), check("service_health", "no_failure", { url: "http://127.0.0.1:8471/healthz" })];
  const calls = await mock(page, { onCheck: () => outcomes.shift()! });
  await page.goto("/");
  await rail(page).getByRole("button", { name: /Service returns HTTP 200/ }).click();
  const run = page.getByRole("button", { name: "Run live check" });
  await expect(run).toBeDisabled();
  await page.getByLabel("Service port").fill("8471");
  await run.click();
  await expect(page.getByRole("heading", { name: "Check did not complete" })).toBeVisible();
  await expect(page.getByText("Nothing answered at http://127.0.0.1:8471. Start the service, then check again.")).toBeVisible();
  await expect(page.getByText("Request failed: ConnectError")).toBeVisible();
  // The engine sends no second session after a transport failure; the result says so rather than leaving a gap.
  await expect(page.locator(".session-skipped")).toContainText("Session 2");
  await expect(page.locator(".session-skipped")).toContainText("Not sent");
  await expect(page.locator(".session-skipped")).toContainText("Session 1 got no response");
  await run.click();
  await expect(page.locator(".session-skipped")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Passing", exact: true })).toBeVisible();
  await expect(page.getByText("Both fresh sessions met every expectation.")).toBeVisible();
  expect(calls.checks).toEqual([{ id: "service_health", body: { port: 8471 } }, { id: "service_health", body: { port: 8471 } }]);
  await page.getByText("Earlier checks · 1").click();
  await expect(page.locator(".history li").filter({ hasText: "Check did not complete" })).toContainText("ConnectError");
});

test("the playground applies only an opened verified run, reverts, and checks checkout live", async ({ page }) => {
  const outcomes = [check("scenario.checkout_api", "no_failure"), check("scenario.checkout_api", "no_failure")];
  const calls = await mock(page, { detail: verifiedDetail(), onCheck: () => outcomes.shift()! });
  await page.goto("/");
  const bar = page.getByRole("region", { name: /Checkout is broken: the seeded defect is live/ });
  await expect(bar).toContainText("Demo Playground · Sample Store");
  await expect(bar).toContainText(target);
  await expect(bar.getByRole("button", { name: "Apply fix" })).toBeDisabled();
  await expect(bar.getByRole("button", { name: "Apply fix" })).toHaveAccessibleDescription(/Unlocks after a verified repair/);
  await expect(bar.getByRole("button", { name: "Revert store" })).toBeDisabled();
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toBeVisible();
  await expect(bar.getByRole("button", { name: "Apply fix" })).toHaveAccessibleDescription(new RegExp(`Writes run ${id.slice(0, 8)}'s verified fix to the store`));
  await bar.getByRole("button", { name: "Apply fix" }).click();
  await expect(page.getByRole("heading", { name: `Checkout is fixed by run ${id.slice(0, 8)}` })).toBeVisible();
  await expect(notice(page)).toContainText("checkout is checked live once it answers");
  expect(calls.applies).toBe(1);
  // Apply waits out the store's hot reload, then confirms checkout live.
  await expect(page.getByRole("heading", { name: "Passing", exact: true })).toBeVisible();
  expect(calls.checks).toEqual([{ id: "scenario.checkout_api", body: { port: 8000 } }]);
  const patched = page.getByRole("region", { name: /Checkout is fixed/ });
  await expect(patched.getByRole("button", { name: "Apply fix" })).toBeDisabled();
  await patched.getByRole("button", { name: "Check checkout live" }).click();
  await expect.poll(() => calls.checks.length).toBe(2);
  await patched.getByRole("button", { name: "Revert store" }).click();
  await expect(page.getByRole("heading", { name: "Checkout is broken: the seeded defect is live" })).toBeVisible();
  expect(calls.reverts).toBe(1);
});

test("the guided demo advances Break it, repair, and Apply fix on recorded evidence", async ({ page }) => {
  const outcomes = [check("scenario.checkout_api", "detected"), check("scenario.checkout_api", "no_failure"), check("scenario.checkout_api", "detected")];
  const calls = await mock(page, { detail: verifiedDetail(), onCheck: () => outcomes.shift()! });
  // Nothing has run yet in this session; the verified record is reached only by step 2.
  await page.route("**/api/faultline/jobs?*", (route) => route.fulfill({ json: { jobs: [] } }));
  await page.goto("/");
  const flow = page.getByRole("list", { name: "Guided demo" });
  const steps = flow.getByRole("listitem");
  await expect(steps).toHaveCount(3);
  await expect(page.locator(".readiness")).toHaveText("Engine Status: Ready");
  await expect(steps.nth(0)).toHaveAttribute("aria-current", "step");
  // A deterministic provider is never called Meta; the step names the fallback instead.
  const repair = flow.getByRole("button", { name: /Auto-repair/ });
  await expect(repair).toContainText("deterministic-checkout-v1");
  await expect(repair).toHaveAccessibleDescription(/not a Meta model trial/);
  await expect(page.getByText("Repair with Meta")).toHaveCount(0);
  await expect(flow.getByRole("button", { name: "Apply fix" })).toBeDisabled();

  // This engine has no crawler endpoint, so the store's checkout check stands in and the HUD says so.
  await expect(flow.getByRole("button", { name: "Break it" })).toHaveAccessibleDescription(/Run Playwright Chaos Crawler/);
  await flow.getByRole("button", { name: "Break it" }).click();
  await expect(page.getByRole("heading", { name: "Failing", exact: true })).toBeVisible();
  expect(calls.crawls).toEqual([{ url: "http://127.0.0.1:3000", max_steps: 25 }]);
  expect(calls.checks).toEqual([{ id: "scenario.checkout_api", body: { port: 8000 } }]);
  const hud = page.getByRole("region", { name: "Live Agent Mission · Direct HTTP check" });
  await expect(hud).toContainText("no Playwright crawler endpoint yet");
  await expect(hud.getByRole("alert")).toContainText("HTTP 500 on POST /api/checkout");
  await expect(hud.getByRole("log", { name: "Agent steps" })).toContainText("[Step 1] Session 1: POST /api/checkout → HTTP 500");
  await expect(steps.nth(0)).toHaveAttribute("data-state", "done");
  await expect(steps.nth(0).locator(".flow-status")).toHaveText("HTTP 500 · checkout crashes");
  await expect(steps.nth(1)).toHaveAttribute("aria-current", "step");

  await repair.click();
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toBeVisible();
  expect(calls.jobBodies).toEqual([expect.objectContaining({ scenario_id: pack.id, mode: "repair" })]);
  await expect(steps.nth(1).locator(".flow-status")).toHaveText("44 of 44 checks passed");
  // Step 2 repaired the defect on the HUD, so the mission follows that run to its verified fix.
  await expect(hud).toContainText("Fix verified: 44/44 assertions passed in the Bubblewrap sandbox");
  await expect(hud.getByRole("button", { name: "Apply Verified Fix to Live Codebase" })).toBeEnabled();
  await expect(steps.nth(1)).toHaveAttribute("data-state", "done");
  await expect(steps.nth(2)).toHaveAttribute("aria-current", "step");

  await flow.getByRole("button", { name: "Apply fix" }).click();
  await expect(steps.nth(2).locator(".flow-status")).toHaveText("HTTP 201 · checkout works");
  expect(calls.applies).toBe(1);
  expect(calls.checks).toHaveLength(2);
  for (const index of [0, 1, 2]) await expect(steps.nth(index)).toHaveAttribute("data-state", "done");
  await expect(flow.locator("[aria-current]")).toHaveCount(0);

  // Breaking a fixed store restores the seed first, then shows checkout failing again.
  await expect(flow.getByRole("button", { name: "Break it" })).toHaveAccessibleDescription(/Reverts the fix, then crawls again/);
  await flow.getByRole("button", { name: "Break it" }).click();
  await expect(page.getByRole("heading", { name: "Checkout is broken: the seeded defect is live" })).toBeVisible();
  await expect(steps.nth(0).locator(".flow-status")).toHaveText("HTTP 500 · checkout crashes");
  expect(calls.reverts).toBe(1);
  expect(calls.checks).toHaveLength(3);
});

test("the repair step says Meta only for the Meta Model API and explains a blocked engine", async ({ page }) => {
  await mock(page, { readiness: { ...ready, model: { ...ready.model, provider: "meta", model: "muse-spark-1.3" } } });
  await page.goto("/");
  const flow = page.getByRole("list", { name: "Guided demo" });
  await expect(flow.getByRole("button", { name: "Repair with Meta" })).toHaveAccessibleDescription(/muse-spark-1\.3 in a Bubblewrap sandbox/);
  await expect(page.locator(".hero-core")).toHaveText("Repair coreMeta Model API · muse-spark-1.3");
  await expect(page.locator(".hero-core")).toHaveAttribute("data-tone", "ok");
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mock(page, { readiness: { ...ready, status: "blocked", runtime_ready: false, reason: "isolated_runtime_unavailable" } });
  await page.reload();
  await expect(page.locator(".readiness")).toHaveText("Engine Status: Needs attention");
  await expect(flow.getByRole("button", { name: /Auto-repair/ })).toBeDisabled();
  await expect(flow.getByRole("button", { name: /Auto-repair/ })).toHaveAccessibleDescription(/Engine needs attention/);
});

test("the header tests any URL without asking for an expected status, reusing its saved check", async ({ page }) => {
  const calls = await mock(page, {
    onCheck: (invariantId) => check(invariantId, "no_failure", { method: "GET", url: "http://localhost:5000/health" }),
    register: (body) => String(body.url).includes("full") ? { status: 409, json: { error: { code: "too_many_probes" } } } : undefined,
  });
  await page.goto("/");
  const quick = page.getByRole("form", { name: "Autonomous bug hunt" });
  const field = page.getByRole("textbox", { name: "Target URL" });
  const ping = quick.getByRole("button", { name: "Quick HTTP Ping" });
  await expect(field).toHaveAttribute("placeholder", "http://localhost:3000/...");
  await expect(page.getByRole("heading", { name: "FaultLine Autonomous Bug Hunter", level: 1 })).toBeVisible();
  await expect(quick.getByRole("button", { name: "Unleash Autonomous Agent" })).toBeVisible();
  // Presets fill the field; nothing runs until the agent is unleashed.
  await quick.getByRole("button", { name: "Storefront (port 3000)" }).click();
  await expect(field).toHaveValue("http://127.0.0.1:3000");
  await quick.getByRole("button", { name: "Backend API (port 8000)" }).click();
  await expect(field).toHaveValue("http://127.0.0.1:8000");
  await expect(quick.getByRole("button", { name: "Backend API (port 8000)" })).toHaveAttribute("aria-pressed", "true");
  await quick.getByRole("button", { name: "AuraScale Cloud (port 5050)" }).click();
  await expect(field).toHaveValue("http://127.0.0.1:5050");
  await quick.getByRole("button", { name: "Custom Localhost" }).click();
  await expect(field).toHaveValue("http://localhost:");
  await expect(field).toBeFocused();
  expect(calls.crawls).toHaveLength(0);
  await expect(quick.getByText(/expected/i)).toHaveCount(0);
  await field.fill("http://");
  await ping.click();
  await expect(quick.getByRole("alert")).toHaveText("Enter a full URL, such as http://localhost:3000/.");
  await expect(field).toHaveAttribute("aria-invalid", "true");
  expect(calls.registered).toHaveLength(0);

  // A bare host and port means http, as in a browser's address bar.
  await field.fill("localhost:5000/health");
  await ping.click();
  await expect(field).toHaveValue("http://localhost:5000/health");
  await expect(page.getByRole("heading", { name: "Passing", exact: true })).toBeVisible();
  await expect(quick.getByRole("alert")).toHaveCount(0);
  expect(calls.registered).toEqual([{ method: "GET", url: "http://localhost:5000/health", expected_status: 200 }]);
  expect(calls.checks).toEqual([{ id: "probe-0123456789ab", body: {} }]);
  expect(calls.crawls).toHaveLength(0);
  await expect(page.getByText("Your custom website", { exact: true }).first()).toBeVisible();
  const saved = rail(page).getByRole("region", { name: "Your custom website" }).getByRole("button");
  await expect(saved).toHaveAttribute("aria-current", "true");
  await expect(saved).toContainText("last check: passing");
  await expect(page.locator("#workspace .check")).toBeInViewport();

  // Testing the same URL again reuses the saved check instead of adding a duplicate.
  await ping.click();
  await expect.poll(() => calls.checks.length).toBe(2);
  expect(calls.registered).toHaveLength(1);
  await expect(saved).toHaveCount(1);

  await expect(ping).toBeEnabled();
  // Enter runs the crawler. With no crawler endpoint, a GET ping stands in and the HUD says so.
  await field.press("Enter");
  const hud = page.getByRole("region", { name: "Live Agent Mission · Direct HTTP check" });
  await expect(hud).toContainText('Sending "GET http://localhost:5000/health" directly');
  await expect(hud.getByRole("status")).toHaveText("Clean");
  await expect(hud).toContainText("Passing: Both fresh sessions met every expectation.");
  await expect(hud).toContainText("✅ Clean. 0 defects found in 2 fresh sessions.");
  expect(calls.crawls).toEqual([{ url: "http://localhost:5000/health", max_steps: 25 }]);
  expect(calls.checks).toHaveLength(3);
  await hud.getByRole("button", { name: "Close the mission" }).click();
  await expect(hud).toHaveCount(0);

  await field.fill("http://localhost:5000/full");
  await ping.click();
  await expect(quick.getByRole("alert")).toHaveText("You have 50 saved URLs. Remove one before adding another.");
  expect(calls.checks).toHaveLength(3);
});

test("the chaos crawler streams its scan and steps, intercepts the defect, and repairs it with Meta", async ({ page }) => {
  let attempts = 0;
  const calls = await mock(page, {
    readiness: { ...ready, model: { ...ready.model, provider: "meta", model: "muse-spark-1.3" } },
    // The first request finds the crawler still starting; the retry streams the crawl.
    crawl: () => ++attempts === 1 ? { status: 503, json: { error: { code: "crawler_starting", message: "starting" } } } : { status: 200, ndjson: [
      { type: "scan", url: "http://127.0.0.1:3000", buttons: 6, forms: 1, links: 3 },
      { type: "step", n: 1, action: "click", target: "Trail Mug", page: "/", ok: true },
      { type: "step", n: 2, action: "click", target: "Add to Cart", page: "/products/trail-mug", ok: true },
      { type: "step", n: 3, action: "submit", target: "Place order", page: "/checkout", ok: false, note: "HTTP 500" },
      { type: "defect", method: "POST", path: "/api/checkout", status: 500, trigger: { kind: "Button", label: "Place order", page: "/checkout" }, fingerprint },
      { type: "done", steps: 3, defect: true },
    ] },
  });
  await page.goto("/");
  const flow = page.getByRole("list", { name: "Guided demo" });
  const steps = flow.getByRole("listitem");
  await flow.getByRole("button", { name: "Break it" }).click();
  const hud = page.getByRole("region", { name: "Live Agent Mission · Playwright" });
  const log = hud.getByRole("log", { name: "Agent steps" });
  await expect(log.getByRole("listitem")).toHaveText([
    "[Scan] Discovered 9 interactive elements (6 buttons, 3 links) and 1 form",
    '[Step 1] Clicked "Trail Mug" (OK) on /',
    '[Step 2] Clicked "Add to Cart" (OK) on /products/trail-mug',
    '[Step 3] Clicked "Place order" on /checkout → 💥 CAUGHT DEFECT: HTTP 500 on POST /api/checkout',
  ]);
  await expect(hud.getByRole("status")).toHaveText("Defect caught");
  const telemetry = hud.locator(".hud-telemetry");
  await expect(telemetry).toContainText("Screens Explored3");
  await expect(telemetry).toContainText("Actions3");
  await expect(telemetry).toContainText("Defects1");
  const banner = hud.getByRole("alert");
  await expect(banner).toContainText("HTTP 500 on POST /api/checkout");
  await expect(banner).toContainText("Triggered by: Button “Place order” on /checkout");
  await expect(banner.getByRole("list", { name: "Click trail" }).getByRole("listitem")).toHaveText(["“Trail Mug”", "“Add to Cart”", "“Place order”"]);
  expect(attempts).toBe(2);
  expect(calls.checks).toHaveLength(0);
  await expect(steps.nth(0)).toHaveAttribute("data-state", "done");
  await expect(steps.nth(0).locator(".flow-status")).toHaveText("Bug caught on /checkout!");
  await expect(steps.nth(1)).toHaveAttribute("aria-current", "step");
  await expect(flow.getByRole("button", { name: "Repair with Meta" })).toBeEnabled();

  await banner.getByRole("button", { name: "Repair with Meta Muse Spark (Sandbox Verified)" }).click();
  await expect.poll(() => calls.jobBodies).toEqual([expect.objectContaining({ scenario_id: pack.id, mode: "repair" })]);
});

test("the mission HUD traces a seismograph, clocks the agent, and maps the journey to the defect", async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await mock(page, { crawl: () => ({ status: 200, ndjson: [
    { type: "scan", url: "http://127.0.0.1:3000", buttons: 6, forms: 1, links: 3 },
    { type: "step", n: 1, action: "click", target: "Trail Mug", page: "/", ok: true },
    { type: "step", n: 2, action: "click", target: "Add to Cart", page: "/products/trail-mug", ok: true },
    { type: "step", n: 3, action: "submit", target: "Place order", page: "/checkout", ok: false, note: "HTTP 500" },
    { type: "defect", method: "POST", path: "/api/checkout", status: 500, trigger: { kind: "Button", label: "Place order", page: "/checkout" }, fingerprint },
    { type: "done", steps: 3, defect: true },
  ] }) });
  // Hold the crawl open so the hunting state can be seen before the stream arrives.
  await page.route("**/api/faultline/crawl", async (route) => { await held; await route.fallback(); });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Target URL" }).fill("http://127.0.0.1:3000");
  await page.getByRole("button", { name: "Unleash Autonomous Agent" }).click();
  const hud = page.getByRole("region", { name: "Live Agent Mission · Playwright" });
  const clock = hud.locator(".hud-telemetry .hud-clock dd");
  await expect(hud).toHaveAttribute("data-seismic", "hunt");
  await expect(clock).toHaveText(/^00:0\d\.\ds$/);
  await expect.poll(() => clock.textContent()).not.toBe("00:00.0s");
  release();

  await expect(hud.getByRole("status")).toHaveText("Defect caught");
  await expect(hud).toHaveAttribute("data-seismic", "rupture");
  // The clock stops once the agent is waiting on a person.
  const stopped = await clock.textContent();
  await page.waitForTimeout(400);
  await expect(clock).toHaveText(stopped!);

  const ribbon = hud.getByRole("alert").getByRole("list", { name: "User journey" });
  await expect(ribbon.getByRole("button")).toHaveText(["🌐/", "🖱️Trail Mug", "🛒Add to Cart", "📋Place order", "💥POST /api/checkout 500"]);
  await expect(hud.getByRole("alert").getByRole("list", { name: "Click trail" }).getByRole("listitem")).toHaveText(["“Trail Mug”", "“Add to Cart”", "“Place order”"]);
  const log = hud.getByRole("log", { name: "Agent steps" }).getByRole("listitem");
  await ribbon.getByRole("button", { name: "Add to Cart" }).click();
  await expect(ribbon.getByRole("button", { name: "Add to Cart" })).toHaveAttribute("aria-current", "step");
  await expect(log.nth(2)).toHaveAttribute("data-focus", "true");
  await expect(hud.locator(".hud-trail li[data-focus]")).toHaveText("“Add to Cart”");
  await ribbon.getByRole("button", { name: "POST /api/checkout 500" }).click();
  await expect(log.nth(3)).toHaveAttribute("data-focus", "true");
  await expect(log.nth(3)).toBeInViewport();
  await expect(hud.locator(".hud-ticker li[data-focus]")).toHaveCount(1);
});

test("a crawl defect no sandbox repair covers is detection only", async ({ page }) => {
  await mock(page, { crawl: () => ({ status: 200, json: { events: [
    { type: "scan", url: "http://localhost:5000/", buttons: 1, forms: 0, links: 0 },
    { type: "step", n: 1, action: "click", target: "Export", page: "/", ok: false, note: "HTTP 500" },
    { type: "defect", method: "GET", path: "/api/export", status: 500, trigger: { kind: "Button", label: "Export", page: "/" } },
    { type: "done", steps: 1, defect: true },
  ] } }) });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Target URL" }).fill("localhost:5000/");
  await page.getByRole("button", { name: "Unleash Autonomous Agent" }).click();
  const banner = page.getByRole("region", { name: "Live Agent Mission · Playwright" }).getByRole("alert");
  await expect(banner).toContainText("HTTP 500 on GET /api/export");
  await expect(banner.getByRole("button", { name: "Auto-repair" })).toBeDisabled();
  await expect(banner.getByRole("button", { name: "Auto-repair" })).toHaveAccessibleDescription("No sandbox repair covers GET /api/export yet, so this failure is detection only.");
});

test("a hunt that finds nothing ends on the clean shield", async ({ page }) => {
  await mock(page, { crawl: () => ({ status: 200, ndjson: [
    { type: "step", n: 1, action: "visit", target: "http://localhost:5000/", page: "/", ok: true },
    { type: "scan", url: "http://localhost:5000/", buttons: 2, forms: 1, links: 1 },
    { type: "step", n: 2, action: "fill", target: "Name", page: "/", ok: true },
    { type: "step", n: 3, action: "fill", target: "Email", page: "/", ok: true },
    { type: "step", n: 4, action: "submit", target: "Subscribe", page: "/", ok: true },
    { type: "done", steps: 4, defect: false, telemetry: { status: "clean", actions_taken: 3, stop_reason: "exhausted" } },
  ] }) });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Target URL" }).fill("localhost:5000/");
  await page.getByRole("textbox", { name: "Target URL" }).press("Enter");
  const hud = page.getByRole("region", { name: "Live Agent Mission · Playwright" });
  await expect(hud.getByRole("log", { name: "Agent steps" }).getByRole("listitem")).toHaveText([
    "[Step 1] Navigating to http://localhost:5000/…",
    "[Scan] Discovered 3 interactive elements (2 buttons, 1 link) and 1 form",
    "[Step 2–3] Filled form fields (Name, Email) (OK) on /",
    '[Step 4] Clicked "Subscribe" (OK) on /',
  ]);
  await expect(hud.getByRole("status")).toHaveText("Clean");
  await expect(hud).toContainText("✅ Exploration finished clean. 0 defects found across 1 screen and 3 actions. A smoke signal for the flows explored, not a business-logic check.");
  await expect(hud.getByRole("alert")).toHaveCount(0);
});

test("a hunt stopped by its budget, or that never says how it ended, is inconclusive and never green", async ({ page }) => {
  const steps = [
    { type: "step", n: 1, action: "visit", target: "http://localhost:5000/", page: "/", ok: true },
    { type: "step", n: 2, action: "fill", target: "Email", page: "/", ok: true },
  ];
  let done: object = { type: "done", steps: 2, defect: false, telemetry: { status: "clean", actions_taken: 1, stop_reason: "max_actions" } };
  await mock(page, { crawl: () => ({ status: 200, ndjson: [...steps, done] }) });
  await page.goto("/");
  const hunt = async () => {
    await page.getByRole("textbox", { name: "Target URL" }).fill("localhost:5000/");
    await page.getByRole("textbox", { name: "Target URL" }).press("Enter");
  };
  await hunt();
  const hud = page.getByRole("region", { name: "Live Agent Mission · Playwright" });
  await expect(hud.getByRole("status")).toHaveText("Inconclusive");
  await expect(hud).toHaveAttribute("data-phase", "incomplete");
  await expect(hud).toContainText("No defect in the flows it explored, but this is inconclusive, not clean. The crawl stopped at its action budget after 1 action, so unexplored flows remain. faultline gate blocks a run like this (incomplete_crawl).");
  await expect(hud.locator(".hud-shield")).toHaveCount(0);
  await expect(hud.locator(".seis")).not.toHaveAttribute("data-mode", "resonance");
  await expect(hud.locator(".hud-telemetry [data-tone=ok]")).toHaveCount(0);

  // An engine that predates stop reasons sends no telemetry: still not clean.
  done = { type: "done", steps: 2, defect: false };
  await hunt();
  await expect(hud.getByRole("status")).toHaveText("Inconclusive");
  await expect(hud).toContainText("The engine did not report how the crawl ended, so unexplored flows remain.");
  await expect(hud.locator(".hud-shield")).toHaveCount(0);
});

// The crawler telemetry of a recorded AuraScale gate run, and the prompt Python's gate_result
// (services/repair-orchestrator/app/cli_crawl.py) returns for it: the Inspector must match it exactly.
const AURASCALE_TELEMETRY = {"status": "failure", "target_url": "http://127.0.0.1:5050/", "elements_explored": 25, "actions_taken": 7, "reproduction_trail": ["1. Open http://127.0.0.1:5050/", "2. Click link \"Explore Pricing\" on / [a:has-text(\"Explore Pricing\")]", "3. Click link \"Start Free\" on /pricing [a:has-text(\"Start Free\")]", "4. Fill \"Full Name\" with \"Alex Tester\" on /signup [#name]", "5. Fill \"Work Email\" with \"test@example.com\" on /signup [#email]", "6. Fill \"Organization Identifier\" with \"FaultLine QA\" on /signup [#org]", "7. Fill \"Cluster Name\" with \"Alex Tester\" on /signup [#cluster_name]", "8. Click button \"🚀 Provision Dedicated Cluster\" on /signup [#btn-activate] -> HTTP 500 on POST /api/provision-cluster"], "screens_visited": [{"url": "http://127.0.0.1:5050/", "path": "/"}, {"url": "http://127.0.0.1:5050/pricing", "path": "/pricing"}, {"url": "http://127.0.0.1:5050/signup", "path": "/signup"}], "actions": [{"step": 2, "action": "click", "label": "Explore Pricing", "selector": "a:has-text(\"Explore Pricing\")", "page": "/", "ok": true}, {"step": 3, "action": "click", "label": "Start Free", "selector": "a:has-text(\"Start Free\")", "page": "/pricing", "ok": true}, {"step": 4, "action": "fill", "label": "Full Name", "selector": "#name", "page": "/signup", "ok": true}, {"step": 5, "action": "fill", "label": "Work Email", "selector": "#email", "page": "/signup", "ok": true}, {"step": 6, "action": "fill", "label": "Organization Identifier", "selector": "#org", "page": "/signup", "ok": true}, {"step": 7, "action": "fill", "label": "Cluster Name", "selector": "#cluster_name", "page": "/signup", "ok": true}, {"step": 8, "action": "click", "label": "🚀 Provision Dedicated Cluster", "selector": "#btn-activate", "page": "/signup", "ok": false}], "failure": {"kind": "http_error", "method": "POST", "url": "http://127.0.0.1:5050/api/provision-cluster", "endpoint": "/api/provision-cluster", "status": 500, "response_body": "{\"status\": 500, \"error\": \"NVMeLeaseAllocationException\", \"message\": \"ResourceExhausted: unable to acquire read/write lock on isolated cgroup enclave #109\", \"code\": \"AURA_RESOURCE_LOCKED\", \"received_payload\": 94}", "step": 8}};
const AURASCALE_PROMPT = "FaultLine caught an unhandled HTTP 500 error on POST /api/provision-cluster. Triggered by clicking \"🚀 Provision Dedicated Cluster\" (#btn-activate) on /signup.\nServer response: {\"status\": 500, \"error\": \"NVMeLeaseAllocationException\", \"message\": \"ResourceExhausted: unable to acquire read/write lock on isolated cgroup enclave #109\", \"code\": \"AURA_RESOURCE_LOCKED\", \"received_payload\": 94}\nReproduce:\n  1. Open http://127.0.0.1:5050/\n  2. Click link \"Explore Pricing\" on / [a:has-text(\"Explore Pricing\")]\n  3. Click link \"Start Free\" on /pricing [a:has-text(\"Start Free\")]\n  4. Fill \"Full Name\" with \"Alex Tester\" on /signup [#name]\n  5. Fill \"Work Email\" with \"test@example.com\" on /signup [#email]\n  6. Fill \"Organization Identifier\" with \"FaultLine QA\" on /signup [#org]\n  7. Fill \"Cluster Name\" with \"Alex Tester\" on /signup [#cluster_name]\n  8. Click button \"🚀 Provision Dedicated Cluster\" on /signup [#btn-activate] -> HTTP 500 on POST /api/provision-cluster\nFix the server-side exception handling for POST /api/provision-cluster so it no longer returns HTTP 500 before deploying, then re-run `faultline gate http://127.0.0.1:5050/ --json` and continue only when it exits 0.";

// `faultline gate --json` key order, and verdicts Python's gate_result returned for the same
// crawler reports (generated from cli_crawl.py with the stop_reason contract, November 1, 2026).
const GATE_KEYS = ["gate_status", "verdict", "exit_code", "target_url", "summary", "elements_explored", "actions_taken", "stop_reason", "screens_visited", "failure", "reproduction_trail", "agent_remediation_prompt", "error"];
const GATE_EXHAUSTED = {"gate_status": "PASSED", "verdict": "SAFE_TO_DEPLOY", "exit_code": 0, "target_url": "http://localhost:4321/", "summary": "No defects found in explored flows: explored 7 elements across 1 screen with 1 action. This does not establish business completeness.", "elements_explored": 7, "actions_taken": 1, "stop_reason": "exhausted", "screens_visited": [{"url": "http://localhost:4321/", "path": "/"}], "failure": null, "reproduction_trail": [], "agent_remediation_prompt": null, "error": null};
const GATE_MAX_ACTIONS = {"gate_status": "FAILED", "verdict": "DEPLOYMENT_BLOCKED", "exit_code": 1, "target_url": "http://localhost:4321/", "summary": "Gate inconclusive: Exploration stopped with max_actions after 1 action; completion was not established.", "elements_explored": 2, "actions_taken": 1, "stop_reason": "max_actions", "screens_visited": [{"url": "http://localhost:4321/", "path": "/"}], "failure": null, "reproduction_trail": [], "agent_remediation_prompt": "The FaultLine gate is inconclusive for http://localhost:4321/: Exploration stopped with max_actions after 1 action; completion was not established. Increase --max-actions and --timeout within their supported limits, then re-run `faultline gate http://localhost:4321/ --json`. If exploration still cannot finish, investigate the unfinished flows and retain independent business checks. Do not deploy until the gate exits 0.", "error": {"code": "incomplete_crawl", "message": "Exploration stopped with max_actions after 1 action; completion was not established."}};
const GATE_NO_REASON = {"gate_status": "FAILED", "verdict": "DEPLOYMENT_BLOCKED", "exit_code": 1, "target_url": "http://localhost:4321/", "summary": "Gate inconclusive: Exploration stopped with no completion reason after 1 action; completion was not established.", "elements_explored": 2, "actions_taken": 1, "stop_reason": null, "screens_visited": [{"url": "http://localhost:4321/", "path": "/"}], "failure": null, "reproduction_trail": [], "agent_remediation_prompt": "The FaultLine gate is inconclusive for http://localhost:4321/: Exploration stopped with no completion reason after 1 action; completion was not established. Increase --max-actions and --timeout within their supported limits, then re-run `faultline gate http://localhost:4321/ --json`. If exploration still cannot finish, investigate the unfinished flows and retain independent business checks. Do not deploy until the gate exits 0.", "error": {"code": "incomplete_crawl", "message": "Exploration stopped with no completion reason after 1 action; completion was not established."}};

test("the pre-flight gate blocks with the CLI's exact fix prompt, clears a clean site, and copies agent snippets", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const calls = await mock(page, { crawl: (body) => body.url === "http://127.0.0.1:5050" ? { status: 200, ndjson: [
    { type: "step", n: 1, action: "visit", target: "http://127.0.0.1:5050/", page: "/", ok: true },
    { type: "scan", url: "http://127.0.0.1:5050/", buttons: 3, forms: 0, links: 6 },
    { type: "step", n: 2, action: "click", target: "Explore Pricing", page: "/", ok: true },
    { type: "step", n: 3, action: "click", target: "Start Free", page: "/pricing", ok: true },
    { type: "step", n: 4, action: "fill", target: "Full Name", page: "/signup", ok: true },
    { type: "step", n: 5, action: "fill", target: "Work Email", page: "/signup", ok: true },
    { type: "step", n: 6, action: "fill", target: "Organization Identifier", page: "/signup", ok: true },
    { type: "step", n: 7, action: "fill", target: "Cluster Name", page: "/signup", ok: true },
    { type: "step", n: 8, action: "click", target: "🚀 Provision Dedicated Cluster", page: "/signup", ok: false, note: "HTTP 500" },
    { type: "defect", method: "POST", path: "/api/provision-cluster", status: 500, trigger: { kind: "Button", label: "🚀 Provision Dedicated Cluster", page: "/signup" } },
    { type: "done", steps: 8, defect: true, telemetry: AURASCALE_TELEMETRY },
  ] } : { status: 200, ndjson: [
    { type: "step", n: 1, action: "visit", target: "http://localhost:4321/", page: "/", ok: true },
    { type: "step", n: 2, action: "click", target: "Docs", page: "/", ok: true },
    { type: "done", steps: 2, defect: false, telemetry: { status: "clean", target_url: "http://localhost:4321/", elements_explored: 7,
      screens_visited: [{ url: "http://localhost:4321/", path: "/" }], actions_taken: 1, stop_reason: "exhausted", failure: null, reproduction_trail: [] } },
  ] } });
  await page.goto("/");
  await page.getByRole("link", { name: "Pre-Flight Gate" }).click();
  const gate = page.getByRole("region", { name: "Nothing ships until the gate clears it." });
  await expect(gate).toHaveAttribute("data-verdict", "idle");
  await expect(gate.getByRole("button", { name: /AuraScale Cloud \(:5050\)/ })).toContainText("Defect → Deployment Blocked!");

  // One click runs the real crawl; the verdict shows in the gate, and the Mission HUD stays closed.
  await gate.getByRole("button", { name: /AuraScale Cloud/ }).click();
  await expect(gate).toHaveAttribute("data-verdict", "blocked");
  expect(calls.crawls).toEqual([{ url: "http://127.0.0.1:5050", max_steps: 25 }]);
  await expect(page.locator(".hud")).toHaveCount(0);
  await expect(gate.locator(".seis")).toHaveAttribute("data-mode", "rupture");
  await expect(gate.locator(".gate-badge")).toHaveText("🛡️ Verdict: Deployment blocked");
  await expect(gate).toContainText("Defect intercepted before going live");
  await expect(gate.getByRole("list", { name: "Reproduction trail" }).getByRole("listitem")).toHaveText([
    "01Open /",
    "02Click “Explore Pricing” on /",
    "03Click “Start Free” on /pricing",
    "04Fill “Full Name”, “Work Email”, “Organization Identifier”, “Cluster Name” on /signup",
    "05Click “🚀 Provision Dedicated Cluster” on /signup → HTTP 500 on POST /api/provision-cluster",
  ]);
  const payload = gate.getByRole("figure");
  await expect(payload.locator("pre")).toHaveText(AURASCALE_PROMPT);
  await payload.getByRole("button", { name: "Copy the agent fix prompt" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(AURASCALE_PROMPT);
  await payload.getByRole("button", { name: "JSON" }).click();
  await payload.getByRole("button", { name: "Copy the JSON verdict" }).click();
  const verdict = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
  expect(verdict).toMatchObject({
    gate_status: "FAILED", verdict: "DEPLOYMENT_BLOCKED", exit_code: 1, target_url: "http://127.0.0.1:5050/",
    summary: "Defect intercepted: HTTP 500 on POST /api/provision-cluster after 7 actions across 3 screens.",
    elements_explored: 25, actions_taken: 7, stop_reason: null, agent_remediation_prompt: AURASCALE_PROMPT, error: null,
  });
  expect(Object.keys(verdict)).toEqual(GATE_KEYS);
  expect(verdict.reproduction_trail).toEqual(AURASCALE_TELEMETRY.reproduction_trail);

  // Handing over opens the Mission HUD with its repair offer and keeps the gate's verdict.
  await gate.getByRole("button", { name: /Open in Mission HUD/ }).click();
  await expect(page.getByRole("region", { name: "Live Agent Mission · Playwright" })).toBeVisible();
  await expect(gate).toHaveAttribute("data-verdict", "blocked");

  // A typed URL runs the same gate; a clean crawl ends on Safe to Deploy with the CLI's summary.
  await gate.getByRole("textbox", { name: "Target preview URL" }).fill("localhost:4321/");
  await gate.getByRole("button", { name: "Run Pre-Flight Gate" }).click();
  await expect(gate).toHaveAttribute("data-verdict", "safe");
  await expect(page.locator(".hud")).toHaveCount(0);
  await expect(gate.locator(".gate-badge")).toHaveText("✅ Verdict: Safe to deploy");
  await expect(gate.locator(".gate-stats")).toContainText("Elements7");
  await expect(gate.locator(".gate-stats")).toContainText("Defects0");
  await expect(gate).toContainText(`${GATE_EXHAUSTED.summary} faultline gate exits 0: a smoke signal for the flows it explored, not proof the business logic is right.`);
  await expect(gate.getByRole("figure")).toHaveCount(0);

  // The snippets follow the gated URL; arrow keys move between the tabs.
  const tabs = gate.getByRole("tab");
  await expect(tabs).toHaveText(["Cursor / Claude Code", "GitHub Actions CI/CD", "CLI Pre-Flight", "Agent Skill"]);
  await tabs.first().focus();
  await page.keyboard.press("ArrowLeft");
  await expect(gate.getByRole("tab", { name: "Agent Skill" })).toHaveAttribute("aria-selected", "true");
  await expect(gate.getByRole("tabpanel")).toContainText("name: faultline-gate");
  await page.keyboard.press("Home");
  await gate.getByRole("button", { name: "Copy Cursor / Claude Code" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("2. Run: faultline gate http://localhost:4321/ --json");
});

test("the gate never clears an unfinished crawl or a direct check, and says so in the CLI's words", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const visit = { type: "step", n: 1, action: "visit", target: "http://localhost:4321/", page: "/", ok: true };
  const fill = { type: "step", n: 2, action: "fill", target: "Email", page: "/", ok: true };
  const report = { status: "clean", target_url: "http://localhost:4321/", elements_explored: 2,
    screens_visited: [{ url: "http://localhost:4321/", path: "/" }], actions_taken: 1, failure: null, reproduction_trail: [] };
  let telemetry: object | null = { ...report, stop_reason: "max_actions" };
  await mock(page, {
    crawl: () => telemetry ? { status: 200, ndjson: [visit, fill, { type: "done", steps: 2, defect: false, telemetry }] }
      : { status: 404, json: { error: { code: "not_found" } } },
    onCheck: (invariantId) => check(invariantId, "no_failure"),
  });
  await page.goto("/");
  const gate = page.getByRole("region", { name: "Nothing ships until the gate clears it." });
  const run = async () => {
    await gate.getByRole("textbox", { name: "Target preview URL" }).fill("localhost:4321/");
    await gate.getByRole("button", { name: "Run Pre-Flight Gate" }).click();
  };
  const copiedJson = async () => {
    await gate.getByRole("figure").getByRole("button", { name: "JSON" }).click();
    await gate.getByRole("figure").getByRole("button", { name: "Copy the JSON verdict" }).click();
    return JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
  };

  // The action budget ran out before exploration finished: blocked, inconclusive, no defect.
  await run();
  await expect(gate).toHaveAttribute("data-verdict", "inconclusive");
  await expect(gate.locator(".gate-badge")).toHaveText("🛡️ Verdict: Inconclusive · deployment blocked");
  await expect(gate.locator(".seis")).toHaveAttribute("data-mode", "still");
  await expect(gate.locator(".gate-stats")).toContainText("Stopped bymax_actions");
  await expect(gate.locator(".gate-stats")).not.toContainText("Defects");
  await expect(gate).toContainText(`No defect in the flows it explored, but exploration did not finish, so this is not a pass. ${GATE_MAX_ACTIONS.summary} faultline gate exits 1 here too.`);
  await expect(gate.getByRole("figure").locator("pre")).toHaveText(GATE_MAX_ACTIONS.agent_remediation_prompt);
  await expect(gate.getByRole("figure")).toContainText("The same agent_remediation_prompt and verdict that faultline gate --json returns for this run.");
  let verdict = await copiedJson();
  expect(verdict).toEqual(GATE_MAX_ACTIONS);
  expect(Object.keys(verdict)).toEqual(GATE_KEYS);

  // A report that does not say why the crawl stopped is not a pass either.
  telemetry = report;
  await run();
  await expect(gate).toHaveAttribute("data-verdict", "inconclusive");
  await expect(gate.getByRole("figure").locator("pre")).toHaveText(GATE_NO_REASON.agent_remediation_prompt);
  verdict = await copiedJson();
  expect(verdict).toEqual(GATE_NO_REASON);

  // Without the crawler, a passing direct HTTP check stands in on the HUD but cannot clear the gate.
  telemetry = null;
  await run();
  await expect(gate).toHaveAttribute("data-verdict", "inconclusive");
  await expect(gate.locator(".gate-badge")).toHaveText("🛡️ Verdict: Inconclusive · deployment blocked");
  await expect(gate).toContainText("The gate could not finish, so it fails closed. The Playwright crawler did not run. A direct HTTP check passed, but one request is not a crawl of the preview. faultline gate exits 1 here too.");
  verdict = await copiedJson();
  expect(verdict).toMatchObject({ verdict: "DEPLOYMENT_BLOCKED", exit_code: 1, failure: null, actions_taken: 0, stop_reason: null, error: { code: "crawl_error" } });
  await expect(gate.getByRole("figure")).toContainText("Built from this run in the faultline gate --json format.");
});

test("the mission HUD repairs, verifies, and applies the fix it caught", async ({ page }) => {
  const calls = await mock(page, {
    detail: verifiedDetail(),
    onCheck: (invariantId) => check(invariantId, "no_failure"),
    crawl: () => ({ status: 200, ndjson: [
      { type: "step", n: 1, action: "visit", target: "http://127.0.0.1:3000", page: "/", ok: true },
      { type: "step", n: 2, action: "submit", target: "Place order", page: "/checkout", ok: false, note: "HTTP 500" },
      { type: "defect", method: "POST", path: "/api/checkout", status: 500, trigger: { kind: "Button", label: "Place order", page: "/checkout" }, fingerprint },
      { type: "done", steps: 2, defect: true },
    ] }),
  });
  // A verified record from an earlier session is not this mission's repair.
  await page.goto("/");
  await page.getByRole("textbox", { name: "Target URL" }).fill("http://127.0.0.1:3000");
  await page.getByRole("button", { name: "Unleash Autonomous Agent" }).click();
  const hud = page.getByRole("region", { name: "Live Agent Mission · Playwright" });
  await expect(hud.getByRole("alert").getByRole("list", { name: "Click trail" }).getByRole("listitem")).toHaveText(["/", "“Place order”"]);
  await expect(hud).not.toContainText("Fix verified");
  await hud.getByRole("button", { name: /Auto-repair \(Sandbox Verified\)/ }).click();
  await expect.poll(() => calls.jobBodies).toEqual([expect.objectContaining({ scenario_id: pack.id, mode: "repair" })]);
  await expect(hud).toContainText("Fix verified: 44/44 assertions passed in the Bubblewrap sandbox");
  await expect(hud.getByRole("status")).toHaveText("Fix verified");
  await expect(hud).toHaveAttribute("data-seismic", "resonance");
  await hud.getByRole("button", { name: "Apply Verified Fix to Live Codebase" }).click();
  await expect(hud).toContainText(`Applied to ${target}.`);
  await expect(hud).toContainText("Live checkout re-checked: HTTP 201 · defect gone.");
  await expect(hud.getByRole("status")).toHaveText("Fix applied");
  expect(calls.applies).toBe(1);
});

test("delivery refusals are explained", async ({ page }) => {
  await mock(page, { detail: verifiedDetail(), apply: () => ({ status: 409, json: { error: { code: "store_not_seeded", message: "store not seeded" } } }) });
  await page.goto("/");
  await inspectPastRun(page);
  await page.getByRole("button", { name: "Apply fix" }).click();
  await expect(notice(page)).toHaveText(/The live store is not on the seeded source/);
});

test("faultline.toml scenarios show every request and judge each one live", async ({ page }) => {
  const twoRequests = (status: number) => ({
    ...session(status, false), assertions: [
      { id: "no_coupon.status", label: "no_coupon.status", passed: false, expected: "201", observed: String(status) },
      { id: "no_coupon.discount", label: "no_coupon.discount", passed: false, expected: "0", observed: "<missing>" },
      { id: "unknown.status", label: "unknown.status", passed: true, expected: "400", observed: "400" },
    ],
    requests: [
      { step_id: "no_coupon", method: "POST", path: "/api/checkout", status, duration_ms: 9 },
      { step_id: "unknown", method: "POST", path: "/api/checkout", status: 400, duration_ms: 4 },
    ],
  });
  const calls = await mock(page, { onCheck: (invariantId) => ({ ...check(invariantId, "detected"), sessions: [twoRequests(500), twoRequests(500)] }) });
  await page.goto("/");
  await rail(page).getByRole("button", { name: /Checkout without a coupon POST/ }).click();
  await expect(page.getByText("Scenario from faultline.toml")).toBeVisible();
  const requests = page.getByRole("list", { name: "Requests in this ReproSpec" }).getByRole("listitem");
  await expect(requests).toHaveCount(2);
  await expect(requests.first()).toContainText("http://127.0.0.1:{port}/api/checkout");
  await expect(page.getByText("3 assertions across 2 requests")).toBeVisible();
  await page.getByText("Expectations · 3").click();
  await expect(page.getByText("$.discount equals 0")).toBeVisible();
  await page.getByRole("button", { name: "Run live check" }).click();
  await expect(page.getByRole("heading", { name: "Failing", exact: true })).toBeVisible();
  expect(calls.checks).toEqual([{ id: "scenario.checkout_api", body: { port: 8000 } }]);
  const rows = page.getByRole("list", { name: "Session 1 requests" }).getByRole("listitem");
  await expect(rows).toHaveCount(2);
  await expect(rows.first().locator("[data-tone=bad]")).toHaveText("500");
  await expect(rows.last().locator("[data-tone=ok]")).toHaveText("400");
});

test("project mode lists the runner's scenario, covers its own entry, and hides store delivery", async ({ page }) => {
  const projectScenario = { ...pack, id: "checkout_api", title: "Checkout without a coupon", description: "", route: "", error_fingerprint: "",
    target_file: "app/routes/checkout.py", executor: "repro", expected_assertions: ["no_coupon.status", "no_coupon.discount", "unknown.status"] };
  const calls = await mock(page, { listing: { ...listing, scenarios: [projectScenario], invariants: [scenario] } });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Checkout without a coupon", level: 1 })).toBeVisible();
  await expect(page.getByText("Your project · sandbox scenario")).toBeVisible();
  await expect(page.getByText("3 ReproSpec assertions, rerun on the baseline twice and on every candidate")).toBeVisible();
  await expect(page.locator(".workspace > .request-line")).toHaveCount(0);
  await expect(rail(page).getByText("ReproSpec, 3 assertions")).toBeVisible();
  await expect(page.locator(".covering")).toContainText("Live check of this scenario");
  await expect(page.getByRole("button", { name: "Apply fix" })).toHaveCount(0);
  await runRepair(page).click();
  await expect.poll(() => calls.posts).toBe(1);
  expect(calls.jobBodies[0]).toMatchObject({ scenario_id: "checkout_api", mode: "repair" });
});

test("scenarios with browser steps explain that they run only in the sandbox", async ({ page }) => {
  const journey = { ...scenario, id: "scenario.journey", title: "Storefront journey",
    live_note: "Browser steps (navigate, fill, click, capture) run only in the sandbox runner.",
    repro: { id: "journey", steps: [{ id: "home", action: "navigate", path: "/" }, { id: "title", action: "capture" }, { id: "title.ok", action: "assert", source: "title", check: { equals: "Shop" } }] } };
  const calls = await mock(page, { listing: { ...listing, invariants: [journey] } });
  await page.goto("/");
  await rail(page).getByRole("button", { name: /Storefront journey/ }).click();
  await expect(page.getByRole("button", { name: "Run live check" })).toBeDisabled();
  await expect(page.getByText(/run only in the sandbox runner\. Run it in the sandbox with faultline run journey/)).toBeVisible();
  expect(calls.checks).toHaveLength(0);
});

for (const state of ["cancelled", "interrupted"]) {
  test(`${state} is terminal and stops polling`, async ({ page }) => {
    const calls = await mock(page, { detail: detail(state) });
    await page.goto("/");
    await inspectPastRun(page);
    await expect(page.getByRole("heading", { name: state === "cancelled" ? "Cancelled" : "Interrupted", exact: true })).toBeVisible();
    await expect(runRepair(page)).toBeEnabled();
    // The terminal state refreshes history once; count only after that settles.
    await page.waitForLoadState("networkidle");
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

test("legacy verified labels are explicitly untrusted and cannot be applied", async ({ page }) => {
  await mock(page, { detail: detail("succeeded", "verified") });
  await page.goto("/");
  await expect(page.getByText("Past sandbox runs · 1 recent run", { exact: true })).toBeVisible();
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Unverified result" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Apply fix" })).toBeDisabled();
});

test("reloading reattaches to an unfinished job and observes its terminal state", async ({ page }) => {
  let completed = false;
  await mock(page, { detail: detail("running", null) });
  await page.route(`**/api/faultline/jobs/${id}`, (route) => route.fulfill({ json: completed ? detail("interrupted") : detail("running", null) }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Running/ }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Stop run" })).toBeVisible();
  completed = true;
  await expect(page.getByRole("heading", { name: "Interrupted", exact: true })).toBeVisible();
});

test("mobile layout fits, keyboard controls have a visible focus, and the dialog fits", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mock(page);
  await page.goto("/");
  await expect(runRepair(page)).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to the selected scenario" })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const missingNames = await page.getByRole("button").evaluateAll((buttons) => buttons.filter((button) => !(button.textContent?.trim() || button.getAttribute("aria-label"))).length);
  expect(missingNames).toBe(0);
  // Flex summaries lose the native disclosure triangle; every summary must draw its own marker.
  const markers = await page.locator("details > summary").evaluateAll((items) => items.map((item) => getComputedStyle(item, "::before").content));
  expect(markers.length).toBeGreaterThan(0);
  expect(markers.filter((content) => content === "none")).toEqual([]);
  await page.getByRole("button", { name: "Custom URL check" }).click();
  const box = await page.getByRole("dialog", { name: "Custom URL check" }).boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
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
  await expect(page.locator(".workspace .source-line")).toContainText("Not a Meta model trial.");
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

test("the store bar links the storefront and runs never claim deployment", async ({ page }) => {
  await mock(page, { detail: detail() });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Open storefront" })).toHaveAttribute("href", `http://127.0.0.1:${process.env.BUGGYSHOP_PORT ?? "3000"}`);
  await expect(page.getByText(/fresh isolated runtime/)).toBeVisible();
  await expect(page.getByText(/nothing is pushed or deployed/)).toBeVisible();
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
  await page.getByText("Past sandbox runs · 2 recent runs", { exact: true }).click();
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
  await expect(page.locator("#artifacts-h ~ details")).not.toHaveAttribute("open");
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

test("the selected scenario's primary action submits that scenario and shows its result", async ({ page }) => {
  const calls = await mock(page, { detail: detail("succeeded", "verified") });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Unverified result" })).toHaveCount(0);
  await expect(runRepair(page)).toBeEnabled();
  await runRepair(page).click();
  await expect(page.getByRole("heading", { name: "Unverified result" })).toBeVisible();
  expect(calls.posts).toBe(1);
  expect(calls.jobBodies[0]).toMatchObject({ scenario_id: pack.id, mode: "repair" });
  await expect(page.getByText(/Sandbox run result for E-Commerce Checkout Defect/)).toBeVisible();
  await expect(runRepair(page)).toBeEnabled();
});

test("a verified run reads failure, patch, gates, checks, and evidence without expanding anything", async ({ page }) => {
  await mock(page, { detail: verifiedDetail() });
  await page.goto("/");
  await inspectPastRun(page);
  const heading = page.getByRole("heading", { name: "Verified repair", exact: true });
  await expect(heading).toBeFocused();
  await expect(heading).toBeInViewport();
  const steps = page.getByRole("list", { name: "What FaultLine did in this run" }).getByRole("listitem");
  await expect(steps).toHaveCount(5);
  await expect(steps.nth(0)).toContainText("Reproduced: POST /api/checkout returned HTTP 500 · TypeError: unsupported operand type(s)");
  await expect(steps.nth(1)).toContainText(`Deterministic fallback · deterministic-checkout-v1 · no model call · +1 −1 lines in ${target}`);
  await expect(steps.nth(2)).toContainText("Scope, syntax, and AST safety policy passed");
  await expect(steps.nth(3)).toContainText("44 of 44 checks passed in the isolated runtime.");
  await expect(steps.nth(4)).toContainText("Cleanup confirmed");
  const source = page.locator(".result-heading .source-line");
  await expect(source).toContainText("Deterministic fallback");
  await expect(source).toContainText("not a Meta model trial");
  await expect(page.getByText("12 of 18 checks failed", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Unified diff from attempt 1")).toBeVisible();
  await expect(page.locator(".technical-details")).not.toHaveAttribute("open");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("live progress follows the newest event before the job record catches up", async ({ page }) => {
  const events = ["baseline", "diagnosing"].map((stage, i) => ({
    sequence: i + 1, timestamp: `2026-10-27T12:00:0${i}Z`, stage, message_code: stage, message: `Entered ${stage}.`,
  }));
  await mock(page, { detail: { ...detail("running", null), events } });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Running: Propose a patch" })).toBeVisible();
  const steps = page.getByRole("list", { name: "What FaultLine did in this run" }).getByRole("listitem");
  await expect(steps.nth(0)).toHaveAttribute("data-state", "done");
  await expect(steps.nth(1)).toHaveAttribute("aria-current", "step");
  for (const index of [2, 3, 4]) await expect(steps.nth(index)).toHaveAttribute("data-state", "pending");
  await expect(page.getByText("Waiting for a patched candidate to test…")).toBeVisible();
  await expect(page.getByText(/No patched candidate was verified/)).toHaveCount(0);
});

test("job submission sends a UUID idempotency key even where crypto.randomUUID is unavailable", async ({ page }) => {
  // randomUUID exists only in secure contexts; plain http on a LAN address lacks it.
  await page.addInitScript(() => Object.defineProperty(Crypto.prototype, "randomUUID", { value: undefined, configurable: true }));
  const keys: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/faultline/jobs") keys.push((request.postDataJSON() as { idempotency_key: string }).idempotency_key);
  });
  await mock(page);
  await page.goto("/");
  expect(await page.evaluate(() => typeof crypto.randomUUID)).toBe("undefined");
  await runRepair(page).click();
  await expect.poll(() => keys.length).toBe(1);
  expect(keys[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test("the CLI guide pairs each real command with its dashboard control, copies commands, and opens with ?", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mock(page);
  await page.goto("/");
  const open = page.getByRole("button", { name: "CLI guide" });
  await expect(open).toHaveAttribute("aria-keyshortcuts", "?");
  await open.click();
  const guide = page.getByRole("dialog", { name: "Developer workflow" });
  await expect(guide).toBeVisible();
  await expect(guide.getByRole("button", { name: "Close" })).toBeFocused();
  for (const command of ["faultline init", "faultline doctor", "faultline check --port 8000", "faultline check --port 8000 --json",
    "faultline verify", "faultline run checkout_api --detect", "faultline run checkout_api", "faultline listen",
    "faultline dashboard", "faultline apply", "faultline revert"]) {
    await expect(guide.getByRole("button", { name: `Copy ${command}`, exact: true })).toBeVisible();
  }
  // faultline check is the terminal twin of Run live check: same rules, same two-session engine, a CI exit code.
  const gate = guide.getByRole("listitem").filter({ hasText: "Gate live invariants" });
  await expect(gate).toContainText("Exit 0 when all pass");
  await expect(gate).toContainText("--repair proposes a sandbox candidate for a reproduced failure without applying it");
  // Flags in prose are code that never wraps mid-flag.
  await expect(gate.locator("code.flag")).toHaveText(["--json", "--repair"]);
  expect(await gate.locator("code.flag").first().evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
  await expect(gate.locator(".guide-dashboard")).toContainText("Run live check sends the same rule through the same engine");
  await expect(guide).not.toContainText("no CLI equivalent");
  const steps = await guide.locator(".guide-step h3").allTextContents();
  expect(steps.indexOf("Gate live invariants")).toBe(steps.indexOf("Check readiness") + 1);
  await expect(guide.getByRole("listitem").filter({ hasText: "Probe the demo store" }).locator(".guide-dashboard")).toHaveText(/Check checkout live/);
  await expect(guide.getByRole("listitem").filter({ hasText: "Reproduce and repair" })).toContainText("Run sandbox repair");
  await expect(guide.locator(".dialog-note")).toContainText("./faultline check --port 8000");
  await expect(guide).not.toContainText("uv run --project");

  await guide.getByRole("button", { name: "Copy faultline init", exact: true }).click();
  await expect(guide.getByRole("status")).toHaveText("Copied faultline init");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("faultline init");
  await guide.getByRole("button", { name: "Copy faultline check --port 8000 --json", exact: true }).click();
  await expect(guide.getByRole("status")).toHaveText("Copied faultline check --port 8000 --json");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("faultline check --port 8000 --json");

  await page.keyboard.press("Escape");
  await expect(guide).toBeHidden();
  await expect(open).toBeFocused();
  await page.locator("body").press("?");
  await expect(guide).toBeVisible();
  await guide.getByRole("button", { name: "Close" }).click();
  await expect(guide).toBeHidden();

  // Typing "?" into a field is text, not a shortcut.
  await page.getByRole("button", { name: "Custom URL check" }).click();
  await page.getByRole("dialog", { name: "Custom URL check" }).getByLabel("URL").pressSequentially("https://x.test/?q=1");
  await expect(page.getByRole("dialog", { name: "Custom URL check" }).getByLabel("URL")).toHaveValue("https://x.test/?q=1");
  await expect(guide).toBeHidden();
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 390, height: 844 });
  await open.click();
  const box = await guide.boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("sound cues are opt-in, persist, and sound an alarm for a reproduced failure and a resolution for a pass", async ({ page }) => {
  // Record every oscillator the cues start; the alarm uses saw and square waves, the resolution triangle and sine.
  await page.addInitScript(() => {
    const started: string[] = [];
    Object.assign(window, { __oscillators: started });
    const Real = window.AudioContext;
    window.AudioContext = class extends Real {
      override createOscillator() {
        const oscillator = super.createOscillator();
        const start = oscillator.start.bind(oscillator);
        oscillator.start = (when?: number) => { started.push(oscillator.type); start(when); };
        return oscillator;
      }
    };
  });
  const started = () => page.evaluate(() => (window as unknown as { __oscillators: string[] }).__oscillators.splice(0));
  const outcomes = [check("checkout.no_coupon", "detected"), check("checkout.no_coupon", "detected"), check("checkout.no_coupon", "no_failure")];
  await mock(page, { onCheck: () => outcomes.shift()! });
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Sound cues" });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await rail(page).getByRole("button", { name: /Checkout without a coupon creates an order/ }).click();
  const run = page.getByRole("button", { name: "Run live check" });
  await run.click();
  await expect(page.getByRole("heading", { name: "Failing", exact: true })).toBeVisible();
  expect(await started()).toEqual([]);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(await started()).toEqual(["triangle", "triangle", "triangle", "sine"]);
  await run.click();
  await expect(run).toHaveText("Run live check");
  expect(new Set(await started())).toEqual(new Set(["sawtooth", "square"]));

  await page.reload();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await rail(page).getByRole("button", { name: /Checkout without a coupon creates an order/ }).click();
  await run.click();
  await expect(page.getByRole("heading", { name: "Passing", exact: true })).toBeVisible();
  expect(await started()).toEqual(["triangle", "triangle", "triangle", "sine"]);
});

test("cues never sound late: none before a user gesture, none from a context that stays suspended", async ({ page }) => {
  // Playwright's own evaluations count as user gestures and its Chromium may autoplay, so model a real
  // browser: activation comes only from a pointer or key event, and a test switch holds the context suspended.
  await page.addInitScript(() => {
    localStorage.setItem("faultline.sound", "on");
    const started: string[] = [];
    const contexts: string[] = [];
    const flags = { active: false, suspend: false };
    Object.assign(window, { __oscillators: started, __contexts: contexts, __audio: flags });
    for (const type of ["pointerdown", "keydown"]) addEventListener(type, () => { flags.active = true; }, true);
    Object.defineProperty(navigator, "userActivation", { value: { get hasBeenActive() { return flags.active; }, isActive: false } });
    const Real = window.AudioContext;
    window.AudioContext = class extends Real {
      constructor(options?: AudioContextOptions) {
        super(options);
        contexts.push(String(options?.latencyHint));
      }
      override get state() { return flags.suspend ? "suspended" : super.state; }
      // A suspended context resumes only at the next gesture, long after the event it would announce.
      override resume() { return flags.suspend ? new Promise<void>((resolve) => setTimeout(resolve, 1500)) : super.resume(); }
      override createOscillator() {
        const oscillator = super.createOscillator();
        const start = oscillator.start.bind(oscillator);
        oscillator.start = (when?: number) => { started.push(oscillator.type); start(when); };
        return oscillator;
      }
    };
  });
  const audio = () => page.evaluate(() => {
    const w = window as unknown as { __oscillators: string[]; __contexts: string[] };
    return { oscillators: w.__oscillators.length, contexts: [...w.__contexts] };
  });
  const suspend = (on: boolean) => page.evaluate((value) => { (window as unknown as { __audio: { suspend: boolean } }).__audio.suspend = value; }, on);
  // Sound was left on; the page reattaches to a run that settles before the operator touches anything.
  let settled = false;
  const outcomes = [check("checkout.no_coupon", "detected"), check("checkout.no_coupon", "detected")];
  await mock(page, { detail: detail("running", null), onCheck: () => outcomes.shift()! });
  await page.route(`**/api/faultline/jobs/${id}`, (route) => route.fulfill({ json: settled ? verifiedDetail() : detail("running", null) }));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sound cues" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Stop run" })).toBeVisible();
  settled = true;
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toBeVisible();
  await page.waitForTimeout(200);
  expect(await audio()).toEqual({ oscillators: 0, contexts: [] });

  // After a gesture, a cue whose context will not resume promptly is dropped rather than held.
  await rail(page).getByRole("button", { name: /Checkout without a coupon creates an order/ }).click();
  await suspend(true);
  const run = page.getByRole("button", { name: "Run live check" });
  await run.click();
  await expect(page.getByRole("heading", { name: "Failing", exact: true })).toBeVisible();
  await page.waitForTimeout(1800);
  expect((await audio()).oscillators).toBe(0);

  // A running context sounds the cue at once, on a context created for interactive latency.
  await suspend(false);
  await run.click();
  await expect(run).toHaveText("Run live check");
  await expect.poll(async () => (await audio()).oscillators).toBe(6);
  expect((await audio()).contexts).toEqual(["interactive"]);
});

test("the rail shows a live check in flight and each sandbox run's evidence-checked result", async ({ page }) => {
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await mock(page, { detail: verifiedDetail() });
  await page.route("**/api/faultline/invariants/checkout.no_coupon/check", async (route) => { await held; await route.fallback(); });
  await page.goto("/");
  const nav = rail(page);
  await expect(nav.getByRole("region", { name: "Repairable defects" })).toContainText("sandbox · 1");
  await expect(nav.getByRole("region", { name: "Project checks" })).toContainText("faultline.toml · 3");
  const ruleItem = nav.getByRole("button", { name: /Checkout without a coupon creates an order/ });
  await expect(ruleItem).toContainText("not checked yet");

  await ruleItem.click();
  await page.getByRole("button", { name: "Run live check" }).click();
  await expect(ruleItem).toContainText("checking live…");
  await expect(ruleItem.locator(".rail-dot")).toHaveAttribute("data-tone", "active");
  await expect(page.getByRole("status").filter({ hasText: "Sending the request from two fresh sessions…" })).toBeVisible();
  release();
  await expect(ruleItem).toContainText("last check: failing");
  await expect(ruleItem.locator(".rail-dot")).toHaveAttribute("data-tone", "bad");
  await expect(page.getByText("Sending the request from two fresh sessions…")).toHaveCount(0);

  const packItem = nav.getByRole("button", { name: /E-Commerce Checkout Defect/ });
  await expect(packItem).toContainText("repairable in the sandbox");
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toBeVisible();
  await expect(packItem).toContainText("last run: verified repair");
  await expect(packItem.locator(".rail-dot")).toHaveAttribute("data-tone", "ok");
});

test("the rail marks a running sandbox job as active and never calls an unproven record verified", async ({ page }) => {
  const events = [{ sequence: 1, timestamp: "2026-10-27T12:00:00Z", stage: "baseline", message_code: "baseline", message: "Entered baseline." }];
  await mock(page, { detail: { ...detail("running", null), events } });
  await page.goto("/");
  const packItem = rail(page).getByRole("button", { name: /E-Commerce Checkout Defect/ });
  await expect(packItem).toContainText("sandbox run in progress…");
  await expect(packItem.locator(".rail-dot")).toHaveAttribute("data-tone", "active");
  await expect(page.locator(".pipeline li[data-state=current]")).toHaveCount(1);
  await expect(page.locator(".readiness")).toHaveAttribute("data-tone", "ok");

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mock(page, { detail: detail("succeeded", "verified") });
  await page.reload();
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Unverified result" })).toBeVisible();
  await expect(packItem).toContainText("last run: unverified result");
  await expect(packItem).not.toContainText("verified repair");
});
