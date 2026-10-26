/**
 * Trusted checkout oracle for the scripted checkout repair scenario.
 *
 * `runCheckoutScenario` drives BuggyShop as SpecV1 §11.1 describes: catalog →
 * Trail Mug detail → quantity two → add to cart → checkout → shipping details
 * → optional coupon → Place order, in a fresh browser context whose requests
 * carry `X-Faultline-Case-Id`. It records first-party traffic, console output,
 * page errors, a Playwright trace, and a screenshot, judges the evidence with
 * pure business assertions, and returns a canonical {@link ExecutionReport}.
 *
 * The oracle never retries, never repairs, and never schedules other work:
 * it runs the scenario once and reports what it observed.
 */

import { randomUUID } from "node:crypto";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { chromium, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";
import {
  assessCheckout,
  stripAnsi,
  summarize,
  tryParseJson,
  type ApiReadback,
  type CapturedRequest,
  type CapturedResponse,
  type CheckoutEvidence,
  type ConfirmationView,
  type UiOutcome,
} from "./assertions.js";
import {
  verdictFor,
  type ArtifactManifest,
  type AssertionResult,
  type ExecutionReport,
  type Observation,
  type ObservationKind,
  type RunOutcome,
} from "./contracts.js";
import { ArtifactStore, PageEvidenceCollector, truncateUtf8 } from "./evidence.js";
import {
  FIXTURE_CATALOG,
  PRIMARY_PRODUCT_ID,
  PRIMARY_QUANTITY,
  SCENARIO_ID,
  SHIPPING_DETAILS,
  expectCheckout,
  type CheckoutExpectation,
} from "./scenario.js";

export type { ExecutionReport } from "./contracts.js";

/** Header the fixture backend uses to select the case's order namespace. */
export const CASE_ID_HEADER = "X-Faultline-Case-Id";
/** Upper bound on one execution, matching the controller's runner cap. */
export const MAX_TIMEOUT_MS = 20_000;
/** Time held back from the browser flow for readback and evidence capture. */
const EVIDENCE_RESERVE_MS = 4_000;
/** Bound on any single UI wait inside the flow. */
const STEP_TIMEOUT_MS = 7_000;
/** Bound on each direct API readback request. */
const API_TIMEOUT_MS = 3_000;
/** Cap on `raw_logs`; the failure-relevant tail is kept (SpecV1 §11.3). */
const MAX_RAW_LOG_BYTES = 64 * 1024;
const CASE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

/** Options for one checkout execution. */
export interface CheckoutScenarioOptions {
  /** Origin of the BuggyShop frontend, e.g. `http://127.0.0.1:3000`. */
  baseUrl: string;
  /** Order namespace for this case; sent as `X-Faultline-Case-Id`. */
  caseId: string;
  /** Coupon typed into the checkout form. Omit or leave blank for none. */
  coupon?: string;
  /** Directory for screenshots, trace, logs, and `artifacts.json`. Defaults to `./artifacts/<executionId>`. */
  artifactsDir?: string;
  /** Execution identity supplied by the orchestrator; generated when omitted. */
  executionId?: string;
  /** Overall budget in milliseconds, capped at {@link MAX_TIMEOUT_MS}. */
  timeoutMs?: number;
  /**
   * Browser to create the case context in. When omitted, a headless Chromium
   * is launched for this execution and closed afterwards.
   */
  browser?: Browser;
}

/** Everything one execution produced. */
export interface ScenarioRun {
  report: ExecutionReport;
  /** Finer-grained outcome behind the canonical verdict; selects the CLI exit code. */
  outcome: RunOutcome;
  /** Evidence files written beneath `artifactsDir` (also saved as `artifacts.json`). */
  manifest: ArtifactManifest;
  artifactsDir: string;
}

/** Raised for caller errors (bad URL, unsafe case ID) before any work starts. */
export class ScenarioOptionsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ScenarioOptionsError";
  }
}

/** Marks a failure in a named flow step so it can be reported precisely. */
class StepError extends Error {
  constructor(
    readonly step: string,
    cause: unknown,
    readonly infrastructure: boolean,
  ) {
    super(cause instanceof Error ? cause.message : String(cause), { cause });
    this.name = "StepError";
  }
}

class DeadlineExceeded extends Error {
  constructor(readonly step: string) {
    super(`execution budget exhausted during ${step}`);
    this.name = "DeadlineExceeded";
  }
}

/** Monotonic execution budget shared by every step. */
class Deadline {
  private readonly endsAt: number;

  constructor(budgetMs: number) {
    this.endsAt = performance.now() + budgetMs;
  }

  remaining(): number {
    return Math.max(0, Math.floor(this.endsAt - performance.now()));
  }

  /** Timeout for one wait: the step cap or what is left, whichever is smaller. */
  slice(capMs: number): number {
    return Math.max(1, Math.min(capMs, this.remaining()));
  }
}

function validateOptions(options: CheckoutScenarioOptions): { origin: string; timeoutMs: number } {
  let url: URL;
  try {
    url = new URL(options.baseUrl);
  } catch {
    throw new ScenarioOptionsError(`baseUrl must be an absolute URL; received "${options.baseUrl}".`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ScenarioOptionsError(`baseUrl must use http or https; received "${options.baseUrl}".`);
  }
  if (!CASE_ID_PATTERN.test(options.caseId)) {
    throw new ScenarioOptionsError(
      "caseId must be 1-128 characters of letters, digits, '.', '_', ':', or '-', starting with a letter or digit.",
    );
  }
  const requested = options.timeoutMs ?? MAX_TIMEOUT_MS;
  if (!Number.isFinite(requested) || requested < EVIDENCE_RESERVE_MS + 1_000) {
    throw new ScenarioOptionsError(`timeoutMs must be at least ${EVIDENCE_RESERVE_MS + 1_000}.`);
  }
  return { origin: url.origin, timeoutMs: Math.min(Math.floor(requested), MAX_TIMEOUT_MS) };
}

/** Collects values written during the flow so partial evidence survives a failure. */
interface FlowState {
  step: string;
  checkoutRequests: CapturedRequest[];
  checkoutResponse: CapturedResponse | null;
  ui: UiOutcome | null;
}

/** Runs one named step, wrapping any failure as a non-infrastructure StepError. */
async function runStep<T>(state: FlowState, step: string, action: () => Promise<T>): Promise<T> {
  state.step = step;
  try {
    return await action();
  } catch (error) {
    if (error instanceof StepError || error instanceof DeadlineExceeded) throw error;
    throw new StepError(step, error, false);
  }
}

function isConnectionFailure(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /net::ERR_(CONNECTION|NAME_NOT_RESOLVED|ADDRESS|INTERNET_DISCONNECTED|EMPTY_RESPONSE)/.test(message);
}

/** Accessible name of the header cart link for a given item count. */
function cartLinkName(count: number): string {
  return count === 1 ? "Cart, 1 item" : `Cart, ${count} items`;
}

/** Drives the browser through the scenario. Throws StepError on the failing step. */
async function driveCheckout(
  page: Page,
  collector: PageEvidenceCollector,
  state: FlowState,
  coupon: string | undefined,
  deadline: Deadline,
): Promise<void> {
  const product = FIXTURE_CATALOG[PRIMARY_PRODUCT_ID];
  if (!product) throw new Error(`Fixture catalog is missing ${PRIMARY_PRODUCT_ID}.`);

  page.on("request", (request) => {
    if (request.method() === "POST" && collector.isApiRequest(request.url()) && new URL(request.url()).pathname === "/api/checkout") {
      state.checkoutRequests.push({ method: request.method(), url: request.url(), post_data: request.postData() });
    }
  });

  await runStep(state, "open_catalog", async () => {
    try {
      await page.goto("/", { waitUntil: "domcontentloaded", timeout: deadline.slice(STEP_TIMEOUT_MS) });
    } catch (error) {
      // An unreachable fixture is an infrastructure result, not a candidate defect.
      throw new StepError("open_catalog", error, isConnectionFailure(error));
    }
  });

  await runStep(state, "open_product", async () => {
    await page.getByRole("link", { name: product.name, exact: true }).click({ timeout: deadline.slice(STEP_TIMEOUT_MS) });
    await page.waitForURL(`**/product/${product.id}`, { timeout: deadline.slice(STEP_TIMEOUT_MS) });
    await page
      .getByRole("heading", { level: 1, name: product.name, exact: true })
      .waitFor({ state: "visible", timeout: deadline.slice(STEP_TIMEOUT_MS) });
  });

  await runStep(state, "set_quantity", async () => {
    const quantity = page.getByRole("spinbutton", { name: "Quantity", exact: true });
    await quantity.fill(String(PRIMARY_QUANTITY), { timeout: deadline.slice(STEP_TIMEOUT_MS) });
    const value = await quantity.inputValue({ timeout: deadline.slice(STEP_TIMEOUT_MS) });
    if (value !== String(PRIMARY_QUANTITY)) throw new Error(`quantity field shows "${value}"`);
  });

  await runStep(state, "add_to_cart", async () => {
    await page.getByRole("button", { name: "Add to cart", exact: true }).click({ timeout: deadline.slice(STEP_TIMEOUT_MS) });
    await page.getByRole("link", { name: cartLinkName(PRIMARY_QUANTITY), exact: true }).waitFor({ state: "visible", timeout: deadline.slice(STEP_TIMEOUT_MS) });
  });

  await runStep(state, "open_checkout", async () => {
    await page.getByRole("link", { name: "Go to checkout", exact: true }).click({ timeout: deadline.slice(STEP_TIMEOUT_MS) });
    await page.waitForURL("**/checkout", { timeout: deadline.slice(STEP_TIMEOUT_MS) });
    const lineQuantity = page.getByRole("combobox", { name: `Qty for ${product.name}`, exact: true });
    const value = await lineQuantity.inputValue({ timeout: deadline.slice(STEP_TIMEOUT_MS) });
    if (value !== String(PRIMARY_QUANTITY)) throw new Error(`cart shows quantity "${value}" for ${product.name}`);
  });

  await runStep(state, "fill_shipping", async () => {
    await page.getByLabel("Name", { exact: true }).fill(SHIPPING_DETAILS.name, { timeout: deadline.slice(STEP_TIMEOUT_MS) });
    await page.getByLabel("Email", { exact: true }).fill(SHIPPING_DETAILS.email, { timeout: deadline.slice(STEP_TIMEOUT_MS) });
    await page.getByLabel("Address", { exact: true }).fill(SHIPPING_DETAILS.address, { timeout: deadline.slice(STEP_TIMEOUT_MS) });
  });

  if (coupon !== undefined && coupon !== "") {
    await runStep(state, "apply_coupon", async () => {
      await page.getByLabel("Coupon code", { exact: true }).fill(coupon, { timeout: deadline.slice(STEP_TIMEOUT_MS) });
      await page.getByRole("button", { name: "Apply coupon", exact: true }).click({ timeout: deadline.slice(STEP_TIMEOUT_MS) });
    });
  }

  await runStep(state, "submit_order", async () => {
    const placeOrder = page.getByRole("button", { name: "Place order", exact: true });
    // Waiting for the enabled button ensures prices loaded before submission.
    await placeOrder.waitFor({ state: "visible", timeout: deadline.slice(STEP_TIMEOUT_MS) });
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/checkout",
      { timeout: deadline.slice(STEP_TIMEOUT_MS) },
    );
    // Swallow a rejection if the click itself fails; the click error is reported instead.
    responsePromise.catch(() => undefined);
    await placeOrder.click({ timeout: deadline.slice(STEP_TIMEOUT_MS) });
    const response = await responsePromise;
    let bodyText: string | null = null;
    try {
      bodyText = truncateUtf8(await response.text(), 64 * 1024).text;
    } catch {
      bodyText = null;
    }
    state.checkoutResponse = {
      status: response.status(),
      body_text: bodyText,
      request_id: response.headers()["x-request-id"] ?? null,
    };
  });

  await runStep(state, "await_outcome", async () => {
    const main = page.getByRole("main");
    const confirmationHeading = main.getByRole("heading", { level: 1, name: "Order placed", exact: true });
    const failureAlert = main.getByRole("alert").filter({ hasText: "Checkout failed" });
    await confirmationHeading.or(failureAlert).first().waitFor({ state: "visible", timeout: deadline.slice(STEP_TIMEOUT_MS) });

    const confirmationVisible = await confirmationHeading.isVisible();
    const failureVisible = await failureAlert.isVisible();
    state.ui = {
      confirmation_visible: confirmationVisible,
      failure_alert_visible: failureVisible,
      failure_alert_text: failureVisible ? summarize(await failureAlert.first().innerText()) : null,
      confirmation: confirmationVisible ? await readConfirmation(page, deadline) : null,
    };
  });
}

/** Reads the order confirmation through accessible roles and labels. */
async function readConfirmation(page: Page, deadline: Deadline): Promise<ConfirmationView> {
  const region = page.getByRole("region", { name: "Order placed", exact: true });
  const text = async (label: string): Promise<string | null> => {
    const locator = region.getByLabel(label, { exact: true });
    return (await locator.count()) === 1 ? (await locator.textContent({ timeout: deadline.slice(2_000) }))?.trim() ?? null : null;
  };
  const rows = region.getByRole("rowgroup").nth(1).getByRole("row");
  const lines: ConfirmationView["lines"] = [];
  for (const row of await rows.all()) {
    const name = (await row.getByRole("rowheader").first().textContent())?.trim() ?? "";
    const quantity = (await row.getByRole("cell").first().textContent())?.trim() ?? "";
    lines.push({ name, quantity });
  }
  return {
    order_id: await text("Order ID"),
    subtotal: await text("Subtotal"),
    discount: await text("Discount"),
    total: await text("Total"),
    lines,
  };
}

async function readback(request: APIRequestContext, url: string, caseId: string, deadline: Deadline): Promise<ApiReadback> {
  if (deadline.remaining() <= 0) return { status: null, body_text: null, error: "no time left for readback" };
  try {
    const response = await request.get(url, {
      headers: { [CASE_ID_HEADER]: caseId, Accept: "application/json" },
      timeout: deadline.slice(API_TIMEOUT_MS),
      failOnStatusCode: false,
      maxRedirects: 0,
    });
    return { status: response.status(), body_text: truncateUtf8(await response.text(), 64 * 1024).text, error: null };
  } catch (error) {
    return { status: null, body_text: null, error: error instanceof Error ? error.message : String(error) };
  }
}

function extractOrderId(bodyText: string | null | undefined): string | null {
  const body = tryParseJson(bodyText);
  if (typeof body !== "object" || body === null) return null;
  const orderId = (body as { id?: unknown }).id;
  return typeof orderId === "string" && orderId ? orderId : null;
}

function errorDetails(error: unknown): { type: string; message: string; trace: string | null } {
  if (error instanceof Error) {
    return {
      type: error.name || "Error",
      message: stripAnsi(error.message),
      trace: error.stack ? truncateUtf8(stripAnsi(error.stack), 4 * 1024).text : null,
    };
  }
  return { type: "Error", message: stripAnsi(String(error)), trace: null };
}

type FlowFailure = { step: string; error: unknown; kind: Extract<ObservationKind, "assertion" | "transport_error" | "runner_error"> };

/** Builds the observation list: one entry per distinct failure signal. */
function buildObservations(
  assertions: AssertionResult[],
  collector: PageEvidenceCollector,
  flowFailure: FlowFailure | null,
  timedOut: boolean,
  artifactIds: string[],
): Observation[] {
  const observations: Observation[] = [];
  const now = new Date().toISOString();

  for (const entry of collector.network) {
    const pathName = new URL(entry.url).pathname;
    const step = pathName === "/api/checkout" ? "submit_order" : "api_request";
    const request = { url: entry.url, method: entry.method, status: entry.status, request_id: entry.request_id };
    if (entry.status !== null && entry.status >= 500) {
      observations.push({
        id: randomUUID(),
        kind: "http_error",
        source: "network",
        message: summarize(`${entry.method} ${pathName} returned HTTP ${entry.status}${entry.response_body ? `: ${entry.response_body}` : ""}`),
        data: {
          step,
          request,
          response_body: entry.response_body,
          expected: pathName === "/api/checkout" ? "HTTP 201 with a created order" : "successful API response",
          artifact_ids: artifactIds,
        },
        timestamp: entry.finished_at ?? now,
      });
    } else if (entry.status === null && entry.failure) {
      observations.push({
        id: randomUUID(),
        kind: "transport_error",
        source: "network",
        message: summarize(`${entry.method} ${pathName} failed: ${entry.failure}`),
        data: { step, request, transport_error: entry.failure, artifact_ids: artifactIds },
        timestamp: entry.finished_at ?? now,
      });
    }
  }

  for (const pageError of collector.pageErrors) {
    observations.push({
      id: randomUUID(),
      kind: "browser_exception",
      source: "browser",
      message: summarize(`${pageError.name}: ${pageError.message}`),
      data: { exception_type: pageError.name, trace: pageError.stack, artifact_ids: artifactIds },
      timestamp: pageError.at,
    });
  }

  if (flowFailure) {
    const details = errorDetails(flowFailure.error);
    observations.push({
      id: randomUUID(),
      kind: flowFailure.kind,
      source: flowFailure.kind === "runner_error" ? "runner" : "browser",
      message: summarize(`step ${flowFailure.step} failed: ${details.message}`),
      data: {
        step: flowFailure.step,
        reason: timedOut ? "timeout" : flowFailure.kind,
        exception_type: details.type,
        trace: details.trace,
        artifact_ids: artifactIds,
      },
      timestamp: now,
    });
  }

  // Failed checks that saw the same thing (for example every order check after
  // an HTTP 500) are one symptom, so they share a single observation. The flow
  // failure above already covers `checkout.flow_completed`.
  const groups = new Map<string, AssertionResult[]>();
  for (const assertion of assertions) {
    if (assertion.passed) continue;
    if (flowFailure && assertion.id === "checkout.flow_completed") continue;
    const group = groups.get(assertion.observed) ?? [];
    group.push(assertion);
    groups.set(assertion.observed, group);
  }
  for (const [observed, group] of groups) {
    observations.push({
      id: randomUUID(),
      kind: "assertion",
      source: "oracle",
      message: summarize(`${group.map((assertion) => assertion.id).join(", ")}: ${observed}`),
      data: {
        assertion_ids: group.map((assertion) => assertion.id),
        expected: group.map((assertion) => assertion.expected),
        observed,
        artifact_ids: artifactIds,
      },
      timestamp: now,
    });
  }
  return observations;
}

/**
 * Renders network, console, page-error, and runner events as chronological
 * text, keeping the last {@link MAX_RAW_LOG_BYTES} so the failure stays in view.
 */
function buildRawLogs(collector: PageEvidenceCollector, runnerLines: Array<{ at: string; text: string }>): string {
  const lines: Array<{ at: string; text: string }> = [...runnerLines];
  for (const entry of collector.network) {
    const outcome = entry.status !== null ? `HTTP ${entry.status}` : `failed: ${entry.failure ?? "no response"}`;
    const requestId = entry.request_id ? ` request_id=${entry.request_id}` : "";
    lines.push({ at: entry.started_at, text: `network ${entry.method} ${entry.url} -> ${outcome}${requestId}` });
    if (entry.status !== null && entry.status >= 400 && entry.response_body) {
      lines.push({ at: entry.finished_at ?? entry.started_at, text: `network body ${entry.response_body}` });
    }
  }
  for (const message of collector.console) {
    lines.push({ at: message.at, text: `console.${message.type} ${message.text}${message.location ? ` (${message.location})` : ""}` });
  }
  for (const pageError of collector.pageErrors) {
    lines.push({ at: pageError.at, text: `pageerror ${pageError.name}: ${pageError.message}` });
  }
  if (collector.droppedConsoleEntries > 0) {
    lines.push({ at: new Date().toISOString(), text: `console: ${collector.droppedConsoleEntries} further messages dropped` });
  }
  const text = lines
    .sort((left, right) => left.at.localeCompare(right.at))
    .map((line) => `${line.at} ${stripAnsi(line.text).replace(/\r?\n/g, "\\n")}`)
    .join("\n");
  const bytes = Buffer.from(text, "utf8");
  if (bytes.length <= MAX_RAW_LOG_BYTES) return text;
  const tail = bytes.subarray(bytes.length - MAX_RAW_LOG_BYTES).toString("utf8").replace(/^�/, "");
  return `[truncated ${bytes.length - MAX_RAW_LOG_BYTES} earlier bytes]\n${tail}`;
}

/**
 * Runs the scenario once and returns the report together with the run
 * outcome and artifact manifest. Resolves (never rejects) when the browser or
 * fixture cannot be used, reporting an infrastructure error instead; rejects
 * only with {@link ScenarioOptionsError} for invalid options.
 */
export async function executeCheckoutScenario(options: CheckoutScenarioOptions): Promise<ScenarioRun> {
  const { origin, timeoutMs } = validateOptions(options);
  const executionId = options.executionId ?? randomUUID();
  const started = performance.now();
  const deadline = new Deadline(timeoutMs);
  const flowDeadline = new Deadline(timeoutMs - EVIDENCE_RESERVE_MS);
  const expectation: CheckoutExpectation = expectCheckout(options.coupon);
  const artifactsDir = path.resolve(options.artifactsDir ?? path.join("artifacts", executionId));
  const store = new ArtifactStore(artifactsDir);
  const collector = new PageEvidenceCollector(origin);
  const state: FlowState = { step: "launch_browser", checkoutRequests: [], checkoutResponse: null, ui: null };
  const runnerLines: Array<{ at: string; text: string }> = [];
  const log = (text: string): void => {
    runnerLines.push({ at: new Date().toISOString(), text: `runner ${text}` });
  };

  let infrastructureFailure = false;
  let flowFailure: FlowFailure | null = null;
  let timedOut = false;
  let orderReadback: ApiReadback | null = null;
  let namespaceOrders: ApiReadback | null = null;
  let ownedBrowser: Browser | null = null;
  let context: BrowserContext | null = null;

  const collectEvidence = (): CheckoutEvidence => ({
    flow_error: flowFailure ? { step: flowFailure.step, message: errorDetails(flowFailure.error).message } : null,
    checkout_requests: state.checkoutRequests,
    checkout_response: state.checkoutResponse,
    ui: state.ui,
    order_readback: orderReadback,
    namespace_orders: namespaceOrders,
    server_errors: collector.serverErrors(),
    browser_exceptions: collector.pageErrors.map((entry) => ({ name: entry.name, message: entry.message })),
  });

  log(`execution ${executionId} case ${options.caseId} scenario ${SCENARIO_ID} coupon ${JSON.stringify(options.coupon ?? null)}`);
  try {
    await store.init();
    let browser = options.browser;
    if (!browser) {
      ownedBrowser = await chromium.launch({ headless: true });
      browser = ownedBrowser;
    }
    state.step = "create_context";
    context = await browser.newContext({
      baseURL: origin,
      extraHTTPHeaders: { [CASE_ID_HEADER]: options.caseId },
      viewport: { width: 1280, height: 900 },
      locale: "en-US",
      timezoneId: "UTC",
      colorScheme: "light",
      reducedMotion: "reduce",
      serviceWorkers: "block",
    });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
    const page = await context.newPage();
    collector.attach(page);

    // The flow keeps running in the background if the budget expires; its
    // eventual rejection (when the context closes) is expected and ignored.
    const flow = driveCheckout(page, collector, state, options.coupon, flowDeadline);
    flow.catch(() => undefined);
    let flowTimer: NodeJS.Timeout | undefined;
    const flowTimeout = new Promise<never>((_, reject) => {
      flowTimer = setTimeout(() => reject(new DeadlineExceeded(state.step)), flowDeadline.remaining());
    });
    try {
      await Promise.race([flow, flowTimeout]);
    } catch (error) {
      if (error instanceof DeadlineExceeded || (error instanceof StepError && flowDeadline.remaining() === 0)) {
        // A step whose wait was cut short by the exhausted budget is a timeout,
        // not evidence about the application.
        timedOut = true;
        flowFailure = { step: error.step, error: new DeadlineExceeded(error.step), kind: "runner_error" };
      } else if (error instanceof StepError) {
        infrastructureFailure = error.infrastructure;
        flowFailure = { step: error.step, error: error.cause, kind: error.infrastructure ? "transport_error" : "assertion" };
      } else {
        throw error;
      }
    } finally {
      clearTimeout(flowTimer);
    }
    log(flowFailure ? `flow stopped at ${flowFailure.step}` : "flow reached the order outcome");

    // Readback uses the same namespace header so it sees only this case's orders.
    state.step = "readback";
    const orderId = extractOrderId(state.checkoutResponse?.body_text);
    if (!infrastructureFailure) {
      if (orderId) {
        orderReadback = await readback(context.request, `${origin}/api/orders/${encodeURIComponent(orderId)}`, options.caseId, deadline);
      }
      namespaceOrders = await readback(context.request, `${origin}/api/orders`, options.caseId, deadline);
      log(`readback order=${orderReadback?.status ?? "skipped"} namespace=${namespaceOrders.status ?? namespaceOrders.error}`);
    }

    state.step = "capture_evidence";
    await collector.drain();

    // Name the screenshot by what it shows: the final state of a fully passing
    // case, or the failure state otherwise.
    const passing = !timedOut && !infrastructureFailure && assessCheckout(expectation, collectEvidence()).every((result) => result.passed);
    const screenshotPath = `screenshots/${passing ? "final" : "failure"}.png`;
    try {
      await page.screenshot({
        path: store.resolve(screenshotPath),
        fullPage: true,
        timeout: Math.max(1_000, deadline.slice(3_000)),
        animations: "disabled",
      });
      await store.register(passing ? "final_screenshot" : "failure_screenshot", screenshotPath, "image/png");
    } catch (error) {
      log(`screenshot failed: ${errorDetails(error).message}`);
    }

    await context.tracing.stop({ path: store.resolve("trace.zip") });
    await store.register("trace", "trace.zip", "application/zip");
  } catch (error) {
    infrastructureFailure = true;
    flowFailure = { step: state.step, error, kind: "runner_error" };
  } finally {
    await context?.close().catch(() => undefined);
    await ownedBrowser?.close().catch(() => undefined);
  }

  try {
    await store.writeJson("network_log", "network.json", {
      entries: collector.network,
      readbacks: { order: orderReadback, namespace_orders: namespaceOrders },
      body_bytes_captured: collector.bodyBytesCaptured,
      body_capture_exhausted: collector.bodyCaptureExhausted,
    });
    await store.writeJson("console_log", "console.json", {
      messages: collector.console,
      dropped_messages: collector.droppedConsoleEntries,
      page_errors: collector.pageErrors,
    });
  } catch (error) {
    infrastructureFailure = true;
    flowFailure ??= { step: "write_evidence", error, kind: "runner_error" };
  }

  const assertions = assessCheckout(expectation, collectEvidence());
  const outcome: RunOutcome = infrastructureFailure
    ? "infrastructure_error"
    : timedOut
      ? "timed_out"
      : assertions.every((assertion) => assertion.passed)
        ? "passed"
        : "assertion_failed";
  log(`outcome ${outcome}`);

  const artifactIds = store.entries.map((entry) => entry.artifact_id);
  const report: ExecutionReport = {
    execution_id: executionId,
    case_id: options.caseId,
    scenario_id: SCENARIO_ID,
    verdict: verdictFor(outcome),
    duration_ms: Math.round((performance.now() - started) * 1000) / 1000,
    observations: buildObservations(assertions, collector, flowFailure, timedOut, artifactIds),
    assertions,
    raw_logs: buildRawLogs(collector, runnerLines),
  };

  const manifest: ArtifactManifest = { schema_version: "1.0", execution_id: executionId, artifacts: [...store.entries] };
  try {
    await store.writeManifest(manifest);
  } catch (error) {
    // Without a manifest the evidence cannot be registered; report it as an
    // infrastructure failure rather than returning an unverifiable pass.
    const details = errorDetails(error);
    report.verdict = verdictFor("infrastructure_error");
    report.observations.push({
      id: randomUUID(),
      kind: "runner_error",
      source: "runner",
      message: summarize(`artifact manifest could not be written: ${details.message}`),
      data: { step: "write_manifest", exception_type: details.type, trace: details.trace },
      timestamp: new Date().toISOString(),
    });
    return { report, outcome: "infrastructure_error", manifest, artifactsDir };
  }

  return { report, outcome, manifest, artifactsDir };
}

/**
 * Runs the checkout scenario once in a fresh browser context and returns its
 * canonical execution report. See {@link executeCheckoutScenario} for the
 * run outcome and artifact manifest.
 */
export async function runCheckoutScenario(options: CheckoutScenarioOptions): Promise<ExecutionReport> {
  return (await executeCheckoutScenario(options)).report;
}
