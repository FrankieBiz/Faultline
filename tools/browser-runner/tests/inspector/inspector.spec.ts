import { expect, test, type Page } from "@playwright/test";

const id = "00000000-0000-4000-8000-000000000001";
const target = "apps/buggyshop-backend/app/routes/checkout.py";
const fingerprint = "TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'";
const ready = {
  status: "ready", runtime_ready: true, quarantined: false, reason: null,
  model: { available: true, provider: "deterministic", model: "deterministic-checkout-v1", reason: null, prompt_tokens: null, completion_tokens: null },
};
const pack = {
  id: "scripted_checkout_repair", title: "Scripted checkout repair",
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
    repair_note: failing ? "Same route and server fingerprint as Scripted checkout repair. Its sandbox pipeline reproduces the failure again in isolation before any model call." : null,
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
  register?: (body: Record<string, unknown>) => { status: number; json: object };
  apply?: () => { status: number; json: object };
};
async function mock(page: Page, options: Options = {}) {
  const calls = { posts: 0, detail: 0, jobBodies: [] as Record<string, unknown>[], checks: [] as { id: string; body: unknown }[], registered: [] as Record<string, unknown>[], applies: 0, reverts: 0, removes: 0 };
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
  await expect(nav.getByRole("region", { name: "Sandbox repair" }).getByRole("button", { name: /Scripted checkout repair/ })).toHaveAttribute("aria-current", "true");
  await expect(nav.getByRole("region", { name: "faultline.toml" }).getByRole("button")).toHaveCount(3);
  await expect(nav.getByText("POST /api/checkout, 2 requests")).toBeVisible();
  await expect(nav.getByText("POST /api/checkout").nth(1)).toBeVisible();
  await expect(nav.getByText(/rule\[3\] \(broken\) ignored: duplicate id/)).toBeVisible();
  await expect(nav.getByText("Probe any URL with New invariant.")).toBeVisible();
  await expect(page.getByText(/Deterministic fallback/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Scripted checkout repair", level: 1 })).toBeVisible();
  await expect(page.locator(".covering")).toContainText("Checkout without a coupon creates an order");

  await nav.getByRole("button", { name: /Checkout without a coupon creates an order/ }).click();
  await expect(page.getByRole("heading", { name: "Checkout without a coupon creates an order", level: 1 })).toBeVisible();
  await expect(page.locator(".request-line")).toContainText("POST");
  await expect(page.locator(".request-line")).toContainText("http://127.0.0.1:{port}/api/checkout");
  await expect(page.getByText("HTTP status 201; $.discount equals 0; $.total equals $.subtotal")).toBeVisible();
  await expect(page.getByText("Not checked yet.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove probe" })).toHaveCount(0);
});

test("the new invariant dialog probes a URL, reproduces it twice, and starts the bound sandbox repair", async ({ page }) => {
  const calls = await mock(page, { detail: detail("running", null) });
  await page.route("**/api/faultline/jobs", (route) => route.request().method() === "GET" ? route.fulfill({ json: { jobs: [] } }) : route.fallback());
  await page.goto("/");
  await page.getByRole("button", { name: "New invariant" }).click();
  const dialog = page.getByRole("dialog", { name: "New invariant" });
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
  await expect(page.locator(".repair-callout")).toContainText("Repairable in the sandbox: Scripted checkout repair");
  await expect.poll(() => calls.posts).toBe(1);
  expect(calls.jobBodies[0]).toMatchObject({ scenario_id: pack.id, mode: "repair" });
  await expect(page.getByText(/Sandbox run in progress/)).toBeVisible();
  const added = rail(page).getByRole("region", { name: "Added here" }).getByRole("button");
  await expect(added).toHaveAttribute("aria-current", "true");
  await expect(added).toContainText("last check: failing");
});

test("dialog errors stay in the dialog and Escape closes it", async ({ page }) => {
  const calls = await mock(page, {
    register: () => ({ status: 422, json: { error: { code: "invalid_probe", message: "URL must not contain credentials", job_id: null } } }),
  });
  await page.goto("/");
  await page.getByRole("button", { name: "New invariant" }).click();
  const dialog = page.getByRole("dialog", { name: "New invariant" });
  await dialog.getByLabel("URL").fill("not a url");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Enter a full URL, such as https://api.example.com/health.");
  await dialog.getByLabel("Method").selectOption("PUT");
  await dialog.getByLabel("URL").fill("https://user:pw@example.com/");
  await dialog.getByLabel(/JSON body/).fill("{not json");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("The request body must be valid JSON.");
  expect(calls.registered).toHaveLength(0);
  await dialog.getByLabel(/JSON body/).fill("");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("URL must not contain credentials");
  expect(calls.registered).toEqual([{ method: "PUT", url: "https://user:pw@example.com/", expected_status: 200 }]);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  expect(calls.checks).toHaveLength(0);
});

test("a failure no sandbox repair covers is detection only, and probes can be removed", async ({ page }) => {
  const calls = await mock(page, {
    onCheck: (invariantId) => check(invariantId, "detected", {
      url: "https://api.example.com/orders", repair: null,
      repair_note: "Detection only: no registered sandbox repair covers GET /orders. FaultLine repairs only source it can rebuild and verify in isolation.",
    }),
  });
  await page.goto("/");
  await page.getByRole("button", { name: "New invariant" }).click();
  const dialog = page.getByRole("dialog", { name: "New invariant" });
  await dialog.getByLabel("URL").fill("https://api.example.com/orders");
  await dialog.getByRole("button", { name: "Save and check live" }).click();
  await expect(page.getByRole("heading", { name: "Failing", exact: true })).toBeVisible();
  await expect(page.getByText(/Detection only: no registered sandbox repair covers GET \/orders/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Repair in sandbox" })).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(calls.posts).toBe(0);
  await page.getByRole("button", { name: "Remove probe" }).click();
  await expect(notice(page)).toContainText("Removed the probe");
  expect(calls.removes).toBe(1);
  await expect(rail(page).getByText("Probe any URL with New invariant.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Scripted checkout repair", level: 1 })).toBeVisible();
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
  await run.click();
  await expect(page.getByRole("heading", { name: "Passing", exact: true })).toBeVisible();
  await expect(page.getByText("Both fresh sessions met every expectation.")).toBeVisible();
  expect(calls.checks).toEqual([{ id: "service_health", body: { port: 8471 } }, { id: "service_health", body: { port: 8471 } }]);
  await page.getByText("Earlier checks · 1").click();
  await expect(page.locator(".history li").filter({ hasText: "Check did not complete" })).toContainText("ConnectError");
});

test("the store bar applies only an opened verified run, reverts, and checks checkout live", async ({ page }) => {
  const calls = await mock(page, { detail: verifiedDetail(), onCheck: (invariantId) => check(invariantId, "no_failure") });
  await page.goto("/");
  const bar = page.getByRole("region", { name: /Running the seeded checkout defect/ });
  await expect(bar).toContainText(target);
  await expect(bar.getByRole("button", { name: "Apply fix" })).toBeDisabled();
  await expect(bar.getByRole("button", { name: "Revert store" })).toBeDisabled();
  await expect(bar).toContainText("Apply unlocks after a sandbox repair verifies a fix.");
  await inspectPastRun(page);
  await expect(page.getByRole("heading", { name: "Verified repair", exact: true })).toBeVisible();
  await expect(bar).toContainText(`Applies run ${id.slice(0, 8)}'s verified diff to ${target}.`);
  await bar.getByRole("button", { name: "Apply fix" }).click();
  await expect(page.getByRole("heading", { name: `Running the verified fix from run ${id.slice(0, 8)}` })).toBeVisible();
  await expect(notice(page)).toContainText("check it live to confirm");
  expect(calls.applies).toBe(1);
  const patched = page.getByRole("region", { name: /Running the verified fix/ });
  await expect(patched.getByRole("button", { name: "Apply fix" })).toBeDisabled();
  await patched.getByRole("button", { name: "Check checkout live" }).click();
  await expect(page.getByRole("heading", { name: "Passing", exact: true })).toBeVisible();
  expect(calls.checks).toEqual([{ id: "scenario.checkout_api", body: { port: 8000 } }]);
  await patched.getByRole("button", { name: "Revert store" }).click();
  await expect(page.getByRole("heading", { name: "Running the seeded checkout defect" })).toBeVisible();
  expect(calls.reverts).toBe(1);
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
  await expect(page.getByText("Project sandbox scenario")).toBeVisible();
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
  await page.getByRole("button", { name: "New invariant" }).click();
  const box = await page.getByRole("dialog", { name: "New invariant" }).boundingBox();
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
  await expect(page.getByText(/Sandbox run result for Scripted checkout repair/)).toBeVisible();
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
  for (const command of ["faultline init", "faultline doctor", "faultline verify", "faultline run checkout_api --detect",
    "faultline run checkout_api", "faultline listen", "faultline dashboard", "faultline apply", "faultline revert"]) {
    await expect(guide.getByRole("button", { name: `Copy ${command}`, exact: true })).toBeVisible();
  }
  // Only commands the CLI parser defines; live checks of faultline.toml rules are dashboard-only.
  await expect(guide.getByText("faultline check")).toHaveCount(0);
  await expect(guide).toContainText("faultline.toml rules have no CLI equivalent yet");
  await expect(guide.getByRole("listitem").filter({ hasText: "Reproduce and repair" })).toContainText("Run sandbox repair");
  await expect(guide).toContainText("uv run --project services/repair-orchestrator --python 3.13 --locked");

  await guide.getByRole("button", { name: "Copy faultline init", exact: true }).click();
  await expect(guide.getByRole("status")).toHaveText("Copied faultline init");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("faultline init");

  await page.keyboard.press("Escape");
  await expect(guide).toBeHidden();
  await expect(open).toBeFocused();
  await page.locator("body").press("?");
  await expect(guide).toBeVisible();
  await guide.getByRole("button", { name: "Close" }).click();
  await expect(guide).toBeHidden();

  // Typing "?" into a field is text, not a shortcut.
  await page.getByRole("button", { name: "New invariant" }).click();
  await page.getByRole("dialog", { name: "New invariant" }).getByLabel("URL").pressSequentially("https://x.test/?q=1");
  await expect(page.getByRole("dialog", { name: "New invariant" }).getByLabel("URL")).toHaveValue("https://x.test/?q=1");
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

test("the rail shows a live check in flight and each sandbox run's evidence-checked result", async ({ page }) => {
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await mock(page, { detail: verifiedDetail() });
  await page.route("**/api/faultline/invariants/checkout.no_coupon/check", async (route) => { await held; await route.fallback(); });
  await page.goto("/");
  const nav = rail(page);
  await expect(nav.getByRole("region", { name: "Sandbox repair" })).toContainText("sandbox · 1");
  await expect(nav.getByRole("region", { name: "faultline.toml" })).toContainText("http · 3");
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

  const packItem = nav.getByRole("button", { name: /Scripted checkout repair/ });
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
  const packItem = rail(page).getByRole("button", { name: /Scripted checkout repair/ });
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
