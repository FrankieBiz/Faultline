/**
 * Typed client for the BuggyShop backend.
 *
 * The browser only ever calls same-origin `/api/*` paths; `next.config.ts`
 * proxies them to the FastAPI backend. Field names follow the settled backend
 * interface (`apps/buggyshop-backend/README.md`), which supersedes the
 * SpecV1 §2.2 examples for product and order fields. Responses are parsed
 * defensively because this
 * frontend is the observation surface for a deliberately faulty backend: a
 * malformed body must surface as a visible error, never as a fake success.
 */

/** Catalog entry. Prices are integer USD cents supplied by the backend. */
export interface Product {
  id: string;
  name: string;
  price_cents: number;
}

/** One requested line in a checkout submission. */
export interface CheckoutItem {
  product_id: string;
  quantity: number;
}

/**
 * Body of `POST /api/checkout`. The backend rejects unknown fields with 422,
 * so shipping details collected by the form are intentionally not included.
 */
export interface CheckoutRequest {
  items: CheckoutItem[];
  coupon_code: string | null;
}

/** Priced line in a created order. */
export interface OrderLine {
  product_id: string;
  quantity: number;
  unit_price_cents: number;
  line_total_cents: number;
}

/** Order returned by `POST /api/checkout` and `GET /api/orders/{id}`. Amounts are USD cents. */
export interface Order {
  id: string;
  line_items: OrderLine[];
  subtotal: number;
  discount: number;
  total: number;
}

/** Raised when a backend response does not match the documented contract. */
export class ApiContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiContractError";
  }
}

/** Raised when the backend answers with an unexpected HTTP status. */
export class ApiStatusError extends Error {
  readonly status: number;

  constructor(status: number, statusText: string) {
    super(`HTTP ${status} ${describeStatus(status, statusText)}`);
    this.name = "ApiStatusError";
    this.status = status;
  }
}

const STATUS_TEXT: Readonly<Record<number, string>> = {
  400: "Bad Request",
  404: "Not Found",
  409: "Conflict",
  422: "Unprocessable Content",
  429: "Too Many Requests",
  500: "Internal Server Error",
  502: "Bad Gateway",
  503: "Service Unavailable",
  504: "Gateway Timeout",
};

/**
 * Returns a human-readable reason phrase. HTTP/2 responses carry no reason
 * phrase, so well-known codes fall back to their standard wording.
 */
export function describeStatus(status: number, statusText: string): string {
  const trimmed = statusText.trim();
  if (trimmed) return trimmed;
  return STATUS_TEXT[status] ?? "Unexpected status";
}

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCentAmount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function requireString(source: JsonObject, key: string, context: string): string {
  const value = source[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new ApiContractError(`${context}: "${key}" must be a non-empty string.`);
  }
  return value;
}

function requireCents(source: JsonObject, key: string, context: string): number {
  const value = source[key];
  if (!isCentAmount(value)) {
    throw new ApiContractError(`${context}: "${key}" must be a non-negative integer number of cents.`);
  }
  return value;
}

/** Validates one catalog product. */
export function parseProduct(value: unknown): Product {
  if (!isObject(value)) throw new ApiContractError("Product must be a JSON object.");
  return {
    id: requireString(value, "id", "Product"),
    name: requireString(value, "name", "Product"),
    price_cents: requireCents(value, "price_cents", "Product"),
  };
}

/** Validates the catalog, which the backend returns as a JSON array. */
export function parseCatalog(value: unknown): Product[] {
  if (!Array.isArray(value)) throw new ApiContractError("Catalog must be a JSON array of products.");
  return value.map(parseProduct);
}

/** Validates a single order body. */
export function parseOrder(value: unknown): Order {
  if (!isObject(value)) throw new ApiContractError("Order must be a JSON object.");
  if (!Array.isArray(value.line_items) || value.line_items.length === 0) {
    throw new ApiContractError('Order: "line_items" must be a non-empty array.');
  }
  const lineItems = value.line_items.map((raw, index): OrderLine => {
    const context = `Order line ${index + 1}`;
    if (!isObject(raw)) throw new ApiContractError(`${context} must be a JSON object.`);
    const quantity = raw.quantity;
    if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) {
      throw new ApiContractError(`${context}: "quantity" must be a positive integer.`);
    }
    return {
      product_id: requireString(raw, "product_id", context),
      quantity,
      unit_price_cents: requireCents(raw, "unit_price_cents", context),
      line_total_cents: requireCents(raw, "line_total_cents", context),
    };
  });
  return {
    id: requireString(value, "id", "Order"),
    line_items: lineItems,
    subtotal: requireCents(value, "subtotal", "Order"),
    discount: requireCents(value, "discount", "Order"),
    total: requireCents(value, "total", "Order"),
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiContractError("Response body is not valid JSON.");
  }
}

/** Loads the full catalog from `GET /api/products`. */
export async function fetchCatalog(signal: AbortSignal): Promise<Product[]> {
  const response = await fetch("/api/products", {
    signal,
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new ApiStatusError(response.status, response.statusText);
  return parseCatalog(await readJson(response));
}

/**
 * Loads one product from `GET /api/products/{id}`. Resolves to `null` when the
 * backend reports the product does not exist (404).
 */
export async function fetchProduct(productId: string, signal: AbortSignal): Promise<Product | null> {
  const response = await fetch(`/api/products/${encodeURIComponent(productId)}`, {
    signal,
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new ApiStatusError(response.status, response.statusText);
  return parseProduct(await readJson(response));
}

/** Every way a checkout submission can end, as seen from the browser. */
export type CheckoutResult =
  | { kind: "placed"; order: Order }
  | { kind: "failed"; status: number; reason: string; details: string[] }
  | { kind: "unreadable"; status: number; message: string }
  | { kind: "unreachable"; message: string };

const MAX_DETAILS = 4;
const MAX_DETAIL_LENGTH = 200;

function clip(text: string): string {
  const single = text.replace(/\s+/g, " ").trim();
  return single.length > MAX_DETAIL_LENGTH ? `${single.slice(0, MAX_DETAIL_LENGTH - 1)}…` : single;
}

/**
 * Extracts short, displayable reasons from an error body. Understands
 * FastAPI's `{"detail": "..."}` and `{"detail": [{"loc": [...], "msg": "..."}]}`
 * shapes; anything else is shown as bounded plain text.
 */
export function extractErrorDetails(bodyText: string): string[] {
  const text = bodyText.trim();
  if (!text) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return [clip(text)];
  }
  if (isObject(parsed)) {
    const detail = parsed.detail;
    if (typeof detail === "string") return [clip(detail)];
    if (Array.isArray(detail)) {
      return detail.slice(0, MAX_DETAILS).map((entry) => {
        if (!isObject(entry)) return clip(String(entry));
        const message = typeof entry.msg === "string" ? entry.msg : JSON.stringify(entry);
        const location = Array.isArray(entry.loc)
          ? entry.loc.filter((part) => part !== "body").join(".")
          : "";
        return clip(location ? `${location}: ${message}` : message);
      });
    }
    if (isObject(parsed.error) && typeof parsed.error.message === "string") {
      return [clip(parsed.error.message)];
    }
  }
  return [clip(text)];
}

/**
 * Submits the cart to `POST /api/checkout` exactly once. Never retries: the
 * scenario contract requires a single checkout request per submission.
 */
export async function submitCheckout(request: CheckoutRequest): Promise<CheckoutResult> {
  let response: Response;
  try {
    response = await fetch("/api/checkout", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    });
  } catch (error) {
    return {
      kind: "unreachable",
      message: error instanceof Error ? error.message : "The request could not be sent.",
    };
  }

  const reason = describeStatus(response.status, response.statusText);
  if (!response.ok) {
    let bodyText = "";
    try {
      bodyText = await response.text();
    } catch {
      bodyText = "";
    }
    // Plain-text error pages often repeat the reason phrase; don't show it twice.
    const details = extractErrorDetails(bodyText).filter((detail) => detail.toLowerCase() !== reason.toLowerCase());
    return { kind: "failed", status: response.status, reason, details };
  }

  try {
    return { kind: "placed", order: parseOrder(await readJson(response)) };
  } catch (error) {
    return {
      kind: "unreadable",
      status: response.status,
      message: error instanceof Error ? error.message : "The order response could not be read.",
    };
  }
}
