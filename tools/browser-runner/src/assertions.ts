/**
 * Business assertions for the scripted checkout repair scenario.
 *
 * The oracle first gathers evidence from the browser and API, then this
 * module judges that evidence against an independently computed
 * expectation. Keeping judgment pure (no browser, no I/O) makes every rule
 * unit-testable and guarantees the same evidence always yields the same
 * verdict.
 */

import { performance } from "node:perf_hooks";
import type { AssertionResult } from "./contracts.js";
import { FIXTURE_CATALOG, normalizeCoupon, type CheckoutExpectation, type ExpectedLine } from "./scenario.js";

/** A `POST /api/checkout` request seen by the browser. */
export interface CapturedRequest {
  method: string;
  url: string;
  post_data: string | null;
}

/** The response to the checkout request. */
export interface CapturedResponse {
  status: number;
  body_text: string | null;
  request_id: string | null;
}

/** Values read from the order confirmation view. */
export interface ConfirmationView {
  order_id: string | null;
  subtotal: string | null;
  discount: string | null;
  total: string | null;
  lines: Array<{ name: string; quantity: string }>;
}

/** What the page showed after the order was submitted. */
export interface UiOutcome {
  confirmation_visible: boolean;
  failure_alert_visible: boolean;
  failure_alert_text: string | null;
  confirmation: ConfirmationView | null;
}

/** Result of a direct API readback made with the case's namespace header. */
export interface ApiReadback {
  status: number | null;
  body_text: string | null;
  error: string | null;
}

/** Everything the oracle observed during one checkout case. */
export interface CheckoutEvidence {
  /** Set when the scripted browser flow could not reach order submission. */
  flow_error: { step: string; message: string } | null;
  checkout_requests: CapturedRequest[];
  checkout_response: CapturedResponse | null;
  ui: UiOutcome | null;
  order_readback: ApiReadback | null;
  namespace_orders: ApiReadback | null;
  server_errors: Array<{ method: string; url: string; status: number }>;
  browser_exceptions: Array<{ name: string; message: string }>;
}

/** Validated order body from the backend. Amounts are USD cents. */
export interface ValidatedOrder {
  id: string;
  line_items: ExpectedLine[];
  subtotal: number;
  discount: number;
  total: number;
}

const MAX_SUMMARY = 480;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ORDER_KEYS = ["id", "line_items", "subtotal", "discount", "total"];
const LINE_KEYS = ["product_id", "quantity", "unit_price_cents", "line_total_cents"];

// Terminal color sequences that Playwright embeds in error call logs.
// eslint-disable-next-line no-control-regex
const ANSI_ESCAPE = /\u001b\[[0-9;]*m/g;

/** Removes terminal color codes so reports contain plain text only. */
export function stripAnsi(text: string): string {
  return text.replace(ANSI_ESCAPE, "");
}

/** Clips a summary to a bounded single line of plain text. */
export function summarize(text: string): string {
  const single = stripAnsi(text).replace(/\s+/g, " ").trim();
  return single.length > MAX_SUMMARY ? `${single.slice(0, MAX_SUMMARY - 1)}…` : single;
}

/** Parses JSON text, returning `undefined` instead of throwing. */
export function tryParseJson(text: string | null | undefined): unknown {
  if (text === null || text === undefined) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

/** True for RFC 9562 UUID strings (any version 1-8, standard variant). */
export function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

/**
 * Converts displayed currency text such as `$39.98` or `−$3.99` to absolute
 * cents. Returns `null` when the text is not a dollar amount.
 */
export function parseDisplayedCents(text: string | null | undefined): number | null {
  if (!text) return null;
  const match = /\$\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)\.([0-9]{2})(?![0-9])/.exec(text);
  if (!match?.[1] || !match[2]) return null;
  return Number(match[1].replace(/,/g, "")) * 100 + Number(match[2]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCents(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): string | null {
  const actual = Object.keys(value).sort();
  const wanted = [...keys].sort();
  if (actual.length === wanted.length && actual.every((key, index) => key === wanted[index])) return null;
  return `keys [${actual.join(", ")}] instead of [${wanted.join(", ")}]`;
}

/**
 * Validates an order body against the order schema: exact keys, integer
 * cents, and well-formed line items.
 */
export function validateOrder(value: unknown): { ok: true; order: ValidatedOrder } | { ok: false; problem: string } {
  if (!isRecord(value)) return { ok: false, problem: "body is not a JSON object" };
  const keyProblem = exactKeys(value, ORDER_KEYS);
  if (keyProblem) return { ok: false, problem: `order has ${keyProblem}` };
  if (typeof value.id !== "string" || !value.id) return { ok: false, problem: "id is not a string" };
  for (const key of ["subtotal", "discount", "total"] as const) {
    if (!isCents(value[key])) return { ok: false, problem: `${key} is not a non-negative integer` };
  }
  if (!Array.isArray(value.line_items) || value.line_items.length === 0) {
    return { ok: false, problem: "line_items is not a non-empty array" };
  }
  const lineItems: ExpectedLine[] = [];
  for (const [index, raw] of value.line_items.entries()) {
    if (!isRecord(raw)) return { ok: false, problem: `line_items[${index}] is not an object` };
    const lineProblem = exactKeys(raw, LINE_KEYS);
    if (lineProblem) return { ok: false, problem: `line_items[${index}] has ${lineProblem}` };
    if (typeof raw.product_id !== "string") return { ok: false, problem: `line_items[${index}].product_id is not a string` };
    if (typeof raw.quantity !== "number" || !Number.isInteger(raw.quantity) || raw.quantity < 1) {
      return { ok: false, problem: `line_items[${index}].quantity is not a positive integer` };
    }
    if (!isCents(raw.unit_price_cents) || !isCents(raw.line_total_cents)) {
      return { ok: false, problem: `line_items[${index}] prices are not non-negative integers` };
    }
    lineItems.push({
      product_id: raw.product_id,
      quantity: raw.quantity,
      unit_price_cents: raw.unit_price_cents,
      line_total_cents: raw.line_total_cents,
    });
  }
  return {
    ok: true,
    order: {
      id: value.id,
      line_items: lineItems,
      subtotal: value.subtotal as number,
      discount: value.discount as number,
      total: value.total as number,
    },
  };
}

type CheckOutcome = { passed: boolean; observed: string };

function check(id: string, expected: string, evaluate: () => CheckOutcome): AssertionResult {
  const started = performance.now();
  let outcome: CheckOutcome;
  try {
    outcome = evaluate();
  } catch (error) {
    outcome = { passed: false, observed: `assertion could not be evaluated: ${String(error)}` };
  }
  return {
    id,
    passed: outcome.passed,
    expected: summarize(expected),
    observed: summarize(outcome.observed),
    duration_ms: Math.max(0, Math.round((performance.now() - started) * 1000) / 1000),
  };
}

function describeLines(lines: readonly ExpectedLine[]): string {
  return lines.map((line) => `${line.product_id}×${line.quantity} @${line.unit_price_cents}=${line.line_total_cents}`).join(", ");
}

function sameLines(actual: readonly ExpectedLine[], expected: readonly ExpectedLine[]): boolean {
  return (
    actual.length === expected.length &&
    expected.every((line) =>
      actual.some(
        (candidate) =>
          candidate.product_id === line.product_id &&
          candidate.quantity === line.quantity &&
          candidate.unit_price_cents === line.unit_price_cents &&
          candidate.line_total_cents === line.line_total_cents,
      ),
    )
  );
}

function sameOrder(left: ValidatedOrder, right: ValidatedOrder): boolean {
  return (
    left.id === right.id &&
    left.subtotal === right.subtotal &&
    left.discount === right.discount &&
    left.total === right.total &&
    sameLines(left.line_items, right.line_items)
  );
}

/** Counts orders in a `GET /api/orders` body (`{"orders": [...]}`). */
export function countNamespaceOrders(readback: ApiReadback | null): number | null {
  if (!readback || readback.status !== 200) return null;
  const body = tryParseJson(readback.body_text);
  return isRecord(body) && Array.isArray(body.orders) ? body.orders.length : null;
}

function describeReadback(readback: ApiReadback | null): string {
  if (!readback) return "no readback was attempted";
  if (readback.error) return `readback failed: ${readback.error}`;
  return `HTTP ${readback.status ?? "none"} ${readback.body_text ?? ""}`;
}

/** Validates the browser's checkout payload against the expected request. */
function assessPayload(request: CapturedRequest | undefined, expectation: CheckoutExpectation): CheckOutcome {
  if (!request) return { passed: false, observed: "no checkout request was sent" };
  const body = tryParseJson(request.post_data);
  if (!isRecord(body)) return { passed: false, observed: `request body is not a JSON object: ${request.post_data ?? "empty"}` };
  const keyProblem = exactKeys(body, ["items", "coupon_code"]);
  if (keyProblem) return { passed: false, observed: `request has ${keyProblem}` };
  if (body.coupon_code !== null && typeof body.coupon_code !== "string") {
    return { passed: false, observed: `coupon_code is ${JSON.stringify(body.coupon_code)}` };
  }
  const items = Array.isArray(body.items) ? body.items : [];
  const itemsOk =
    items.length === 1 &&
    isRecord(items[0]) &&
    exactKeys(items[0], ["product_id", "quantity"]) === null &&
    items[0].product_id === "trail-mug" &&
    items[0].quantity === 2;
  const sentCoupon = normalizeCoupon(body.coupon_code as string | null);
  const couponOk = sentCoupon === expectation.normalized_coupon;
  return {
    passed: itemsOk && couponOk,
    observed: `items ${JSON.stringify(body.items)}; coupon_code ${JSON.stringify(body.coupon_code)} (means ${sentCoupon ?? "no coupon"})`,
  };
}

function nonServerErrorCheck(evidence: CheckoutEvidence): AssertionResult {
  return check("checkout.no_server_errors", "no first-party HTTP 5xx responses", () => ({
    passed: evidence.server_errors.length === 0,
    observed:
      evidence.server_errors.length === 0
        ? "none"
        : evidence.server_errors.map((entry) => `${entry.method} ${entry.url} → ${entry.status}`).join("; "),
  }));
}

function browserExceptionCheck(evidence: CheckoutEvidence): AssertionResult {
  return check("checkout.no_browser_exceptions", "no uncaught browser exceptions", () => ({
    passed: evidence.browser_exceptions.length === 0,
    observed:
      evidence.browser_exceptions.length === 0
        ? "none"
        : evidence.browser_exceptions.map((entry) => `${entry.name}: ${entry.message}`).join("; "),
  }));
}

/**
 * Judges one checkout case. Every assertion is always evaluated so the report
 * lists the full checklist, even when an early step already failed. IDs that
 * appear in the scenario registry's `expected_assertions` keep those names.
 */
export function assessCheckout(expectation: CheckoutExpectation, evidence: CheckoutEvidence): AssertionResult[] {
  const results: AssertionResult[] = [];
  const requests = evidence.checkout_requests;
  const response = evidence.checkout_response;
  const ui = evidence.ui;

  results.push(
    check("checkout.flow_completed", "catalog → product → quantity 2 → cart → checkout → Place order", () =>
      evidence.flow_error
        ? { passed: false, observed: `step ${evidence.flow_error.step} failed: ${evidence.flow_error.message}` }
        : { passed: true, observed: "order submitted through the checkout page" },
    ),
    check("checkout.single_request", "exactly one POST /api/checkout", () => ({
      passed: requests.length === 1,
      observed: `${requests.length} checkout request(s)`,
    })),
    check(
      "checkout.request_payload",
      `items [{"product_id":"trail-mug","quantity":2}] and coupon meaning ${expectation.normalized_coupon ?? "no coupon"}`,
      () => assessPayload(requests[0], expectation),
    ),
    check(`checkout.status_${expectation.status}`, `HTTP ${expectation.status}`, () =>
      response
        ? { passed: response.status === expectation.status, observed: `HTTP ${response.status}` }
        : { passed: false, observed: "no checkout response" },
    ),
  );

  if (expectation.kind === "rejected") {
    results.push(
      check("checkout.failure_ui_visible", "checkout failure alert shown and no confirmation", () =>
        ui
          ? {
              passed: ui.failure_alert_visible && !ui.confirmation_visible,
              observed: ui.confirmation_visible
                ? "order confirmation was shown"
                : ui.failure_alert_visible
                  ? `alert: ${ui.failure_alert_text ?? ""}`
                  : "neither an alert nor a confirmation appeared",
            }
          : { passed: false, observed: "the page outcome was not observed" },
      ),
      check("checkout.no_stored_order", "0 orders in the case namespace", () => {
        const count = countNamespaceOrders(evidence.namespace_orders);
        return { passed: count === 0, observed: count === null ? describeReadback(evidence.namespace_orders) : `${count} order(s)` };
      }),
      nonServerErrorCheck(evidence),
      browserExceptionCheck(evidence),
    );
    return results;
  }

  const parsed = validateOrder(tryParseJson(response?.body_text));
  const order = parsed.ok ? parsed.order : null;
  const noOrder = response ? `no valid order (HTTP ${response.status})` : "no checkout response";
  const product = FIXTURE_CATALOG["trail-mug"];
  const coupon = expectation.normalized_coupon;

  results.push(
    check("checkout.order_schema_valid", "201 body matches the order schema", () =>
      parsed.ok ? { passed: true, observed: "valid order body" } : { passed: false, observed: response ? parsed.problem : noOrder },
    ),
    check("checkout.order_id_is_uuid", "server-generated UUID order id", () =>
      order ? { passed: isUuid(order.id), observed: order.id } : { passed: false, observed: noOrder },
    ),
    check("checkout.line_items_match_cart", describeLines(expectation.line_items), () =>
      order
        ? { passed: sameLines(order.line_items, expectation.line_items), observed: describeLines(order.line_items) }
        : { passed: false, observed: noOrder },
    ),
    check("checkout.subtotal_matches_catalog", `subtotal ${expectation.subtotal}`, () =>
      order ? { passed: order.subtotal === expectation.subtotal, observed: `subtotal ${order.subtotal}` } : { passed: false, observed: noOrder },
    ),
    check(
      coupon === null ? "checkout.no_coupon_discount_is_zero" : "checkout.coupon_discount_applied",
      `discount ${expectation.discount} (${coupon ?? "no coupon"})`,
      () => (order ? { passed: order.discount === expectation.discount, observed: `discount ${order.discount}` } : { passed: false, observed: noOrder }),
    ),
    check(
      coupon === null ? "checkout.total_matches_subtotal" : "checkout.total_matches_subtotal_minus_discount",
      `total ${expectation.total}`,
      () => (order ? { passed: order.total === expectation.total, observed: `total ${order.total}` } : { passed: false, observed: noOrder }),
    ),
    check("checkout.confirmation_shown", "order confirmation shown and no failure alert", () =>
      ui
        ? {
            passed: ui.confirmation_visible && !ui.failure_alert_visible,
            observed: ui.confirmation_visible
              ? "confirmation shown"
              : ui.failure_alert_visible
                ? `failure alert: ${ui.failure_alert_text ?? ""}`
                : "neither a confirmation nor an alert appeared",
          }
        : { passed: false, observed: "the page outcome was not observed" },
    ),
    check("checkout.confirmation_matches_order", "displayed ID, quantity, subtotal, discount, and total equal the order", () => {
      const view = ui?.confirmation;
      if (!view) return { passed: false, observed: "no confirmation view" };
      if (!order) return { passed: false, observed: `confirmation shown without a valid order (${noOrder})` };
      const mismatches: string[] = [];
      if (view.order_id?.trim() !== order.id) mismatches.push(`order ID "${view.order_id ?? ""}"`);
      const pairs: Array<[string, string | null, number]> = [
        ["subtotal", view.subtotal, order.subtotal],
        ["discount", view.discount, order.discount],
        ["total", view.total, order.total],
      ];
      for (const [label, shown, cents] of pairs) {
        if (parseDisplayedCents(shown) !== cents) mismatches.push(`${label} "${shown ?? ""}" vs ${cents}¢`);
      }
      const mugLine = view.lines.find((line) => line.name.trim() === product?.name);
      if (!mugLine || mugLine.quantity.trim() !== String(expectation.line_items[0]?.quantity)) {
        mismatches.push(`line items ${JSON.stringify(view.lines)}`);
      }
      return mismatches.length === 0
        ? { passed: true, observed: "all displayed values match the order" }
        : { passed: false, observed: `mismatched ${mismatches.join("; ")}` };
    }),
    check("checkout.readback_matches_response", "GET /api/orders/{id} returns the same order", () => {
      if (!order) return { passed: false, observed: noOrder };
      const readback = evidence.order_readback;
      if (!readback || readback.status !== 200) return { passed: false, observed: describeReadback(readback) };
      const stored = validateOrder(tryParseJson(readback.body_text));
      if (!stored.ok) return { passed: false, observed: `readback ${stored.problem}` };
      return { passed: sameOrder(stored.order, order), observed: sameOrder(stored.order, order) ? "identical" : "differs from response" };
    }),
    check("checkout.exactly_one_stored_order", "exactly 1 order in the case namespace", () => {
      const count = countNamespaceOrders(evidence.namespace_orders);
      return { passed: count === 1, observed: count === null ? describeReadback(evidence.namespace_orders) : `${count} order(s)` };
    }),
    nonServerErrorCheck(evidence),
    browserExceptionCheck(evidence),
  );
  return results;
}
