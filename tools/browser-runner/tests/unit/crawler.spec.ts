import { spawn } from "node:child_process";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { chromium, expect, test, type Browser } from "@playwright/test";
import {
  CrawlOptionsError,
  formatCrawlEvent,
  isFailureResponse,
  labelOf,
  primarySignal,
  runAutonomousCrawler,
  sampleValueFor,
  scoreClickable,
  shouldFill,
  type ClickableInfo,
  type CrawlEvent,
  type FieldInfo,
} from "../../src/crawler.js";

const ORIGIN = "http://shop.test";

function clickable(overrides: Partial<ClickableInfo>): ClickableInfo {
  return {
    index: 0,
    tag: "button",
    type: "button",
    id: "",
    text: "",
    ariaLabel: "",
    value: "",
    href: "",
    disabled: false,
    visible: true,
    inChrome: false,
    submit: false,
    ...overrides,
  };
}

function field(overrides: Partial<FieldInfo>): FieldInfo {
  return {
    index: 0,
    tag: "input",
    type: "text",
    id: "",
    name: "",
    label: "",
    placeholder: "",
    autocomplete: "",
    required: false,
    empty: true,
    checked: false,
    disabled: false,
    visible: true,
    readOnly: false,
    min: "",
    max: "",
    firstOption: "",
    formHasNoRequired: false,
    ...overrides,
  };
}

test.describe("crawler heuristics", () => {
  const context = { origin: ORIGIN, visited: new Set([`${ORIGIN}/`]) };
  const score = (overrides: Partial<ClickableInfo>) => scoreClickable(clickable(overrides), context);

  test("walks a shopping funnel: commit, checkout, content link, add to cart, other", () => {
    const placeOrder = score({ text: "Place order", type: "submit", submit: true })!;
    const checkout = score({ tag: "a", text: "Go to checkout", href: `${ORIGIN}/checkout` })!;
    const product = score({ tag: "a", text: "Trail Mug", href: `${ORIGIN}/product/trail-mug` })!;
    const add = score({ text: "Add to cart" })!;
    const other = score({ text: "Increase quantity" })!;
    expect(placeOrder).toBeGreaterThan(checkout);
    expect(checkout).toBeGreaterThan(product);
    expect(product).toBeGreaterThan(add);
    expect(add).toBeGreaterThan(other);
  });

  test("demotes header and footer chrome below page content", () => {
    const headerCart = score({ tag: "a", text: "Cart, 0 items", href: `${ORIGIN}/checkout`, inChrome: true })!;
    expect(headerCart).toBeLessThan(score({ text: "Increase quantity" })!);
  });

  test("never clicks destructive, disabled, hidden, external, visited, or download controls", () => {
    expect(score({ text: "Remove Trail Mug" })).toBeNull();
    expect(score({ text: "Log out" })).toBeNull();
    expect(score({ ariaLabel: "Delete account" })).toBeNull();
    expect(score({ text: "Place order", disabled: true })).toBeNull();
    expect(score({ text: "Place order", visible: false })).toBeNull();
    expect(score({ tag: "a", text: "Docs", href: "https://example.com/docs" })).toBeNull();
    expect(score({ tag: "a", text: "Home", href: `${ORIGIN}/#top` })).toBeNull();
    expect(score({ tag: "a", text: "Invoice", href: `${ORIGIN}/invoice.pdf` })).toBeNull();
    expect(score({ tag: "a", text: "Broken", href: "not a url" })).toBeNull();
  });

  test("labels symbol-only controls by their accessible name", () => {
    expect(labelOf({ text: "+", ariaLabel: "Increase quantity", value: "", href: "" })).toBe("Increase quantity");
    expect(labelOf({ text: "Add to cart", ariaLabel: "Add to cart, Trail Mug", value: "", href: "" })).toBe("Add to cart");
    expect(labelOf({ text: "→", ariaLabel: "", value: "", href: "" })).toBe("→");
  });

  test("chooses realistic sample values from type and naming hints", () => {
    expect(sampleValueFor(field({ type: "email" }))).toBe("test@example.com");
    expect(sampleValueFor(field({ id: "address", tag: "textarea", type: "textarea" }))).toBe("123 Main St");
    expect(sampleValueFor(field({ name: "shipping_zip" }))).toBe("62704");
    expect(sampleValueFor(field({ label: "Full name" }))).toBe("Alex Tester");
    expect(sampleValueFor(field({ autocomplete: "tel" }))).toBe("555-010-0199");
    expect(sampleValueFor(field({ type: "number" }))).toBe("10");
    expect(sampleValueFor(field({ type: "number", min: "1", max: "5" }))).toBe("5");
    expect(sampleValueFor(field({ type: "number", min: "20" }))).toBe("20");
    expect(sampleValueFor(field({ tag: "textarea", type: "textarea" }))).toBe("Testing from FaultLine.");
    expect(sampleValueFor(field({}))).toBe("test");
  });

  test("fills required fields and leaves optional ones in a required form empty", () => {
    expect(shouldFill(field({ required: true }))).toBe(true);
    expect(shouldFill(field({ name: "coupon" }))).toBe(false);
    expect(shouldFill(field({ name: "q", formHasNoRequired: true }))).toBe(true);
    expect(shouldFill(field({ required: true, empty: false }))).toBe(false);
    expect(shouldFill(field({ required: true, disabled: true }))).toBe(false);
    expect(shouldFill(field({ required: true, type: "hidden" }))).toBe(false);
    expect(shouldFill(field({ required: true, type: "checkbox" }))).toBe(true);
    expect(shouldFill(field({ required: true, type: "checkbox", checked: true }))).toBe(false);
    expect(shouldFill(field({ required: true, tag: "select", type: "select", firstOption: "us" }))).toBe(true);
    expect(shouldFill(field({ required: true, tag: "select", type: "select" }))).toBe(false);
  });

  test("treats 5xx and application 400/422 as defects, not 404s or asset 4xx", () => {
    expect(isFailureResponse(500, "fetch")).toBe(true);
    expect(isFailureResponse(503, "image")).toBe(true);
    expect(isFailureResponse(422, "xhr")).toBe(true);
    expect(isFailureResponse(400, "document")).toBe(true);
    expect(isFailureResponse(400, "script")).toBe(false);
    expect(isFailureResponse(404, "fetch")).toBe(false);
    expect(isFailureResponse(401, "fetch")).toBe(false);
    expect(isFailureResponse(200, "fetch")).toBe(false);
  });

  test("prefers a server error over the console noise it causes", () => {
    const primary = primarySignal([
      { kind: "console_error", message: "boom" },
      { kind: "http_error", message: "422", status: 422 },
      { kind: "http_error", message: "500", status: 500 },
      { kind: "page_error", message: "TypeError" },
    ]);
    expect(primary?.status).toBe(500);
    expect(primarySignal([{ kind: "console_error", message: "x" }, { kind: "page_error", message: "y" }])?.kind).toBe("page_error");
    expect(primarySignal([])).toBeUndefined();
  });

  test("formats HUD lines", () => {
    expect(formatCrawlEvent({ type: "launch" })).toBe("[Playwright] Launching Chromium...");
    expect(formatCrawlEvent({ type: "discovered", url: ORIGIN, count: 8, buttons: 5, links: 3, forms: 0 })).toBe("[Playwright] Discovered 8 interactive elements.");
    expect(
      formatCrawlEvent({
        type: "action",
        step: 5,
        action: "click",
        url: `${ORIGIN}/checkout`,
        element: "button",
        submit: true,
        label: "Place order",
        selector: 'button:has-text("Place order")',
        ok: false,
        failure: { kind: "http_error", message: "500", status: 500, method: "POST", endpoint: "/api/checkout" },
      }),
    ).toBe("[Playwright] Step 5: Clicking Place order -> 💥 HTTP 500 on POST /api/checkout");
    expect(formatCrawlEvent({ type: "action", step: 3, action: "fill", url: `${ORIGIN}/checkout`, element: "field", submit: false, label: "Email", selector: "#email", value: "test@example.com", ok: true })).toBe(
      '[Playwright] Step 3: Filling Email with "test@example.com" -> OK',
    );
  });

  test("rejects invalid options before launching a browser", async () => {
    await expect(runAutonomousCrawler({ url: "not a url" })).rejects.toBeInstanceOf(CrawlOptionsError);
    await expect(runAutonomousCrawler({ url: "file:///etc/passwd" })).rejects.toBeInstanceOf(CrawlOptionsError);
    await expect(runAutonomousCrawler({ url: ORIGIN, maxActions: 0 })).rejects.toBeInstanceOf(CrawlOptionsError);
    await expect(runAutonomousCrawler({ url: ORIGIN, timeoutMs: 10 })).rejects.toBeInstanceOf(CrawlOptionsError);
  });
});

/** A miniature shop whose checkout fails unless `healthy`, plus booby-trapped controls. */
class FixtureShop {
  healthy = false;
  readonly hits: string[] = [];
  private server: Server | undefined;
  origin = "";

  private page(title: string, body: string): string {
    return `<!doctype html><html><head><title>${title}</title></head><body>
<header><nav><a href="/">Shop</a> <a href="/cart">Cart</a> <button onclick="fetch('/api/logout',{method:'POST'})">Log out</button></nav></header>
<main>${body}</main>
<footer><a href="https://example.com/terms">Terms</a></footer></body></html>`;
  }

  private routes(request: IncomingMessage, response: ServerResponse, body: string): void {
    const url = new URL(request.url ?? "/", this.origin);
    this.hits.push(`${request.method} ${url.pathname}`);
    const html = (status: number, content: string) => {
      response.writeHead(status, { "content-type": "text/html" }).end(content);
    };
    const json = (status: number, value: unknown) => {
      response.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(value));
    };
    switch (`${request.method} ${url.pathname}`) {
      case "GET /":
        return html(200, this.page("Home", `<h1>Shop</h1><a href="/product/widget">Widget</a>`));
      case "GET /product/widget":
        return html(
          200,
          this.page(
            "Widget",
            `<h1>Widget</h1><button id="add" onclick="fetch('/api/cart',{method:'POST'}).then(()=>{document.getElementById('next').hidden=false})">Add to cart</button>
             <p id="next" hidden><a href="/checkout">Proceed to checkout</a></p>`,
          ),
        );
      case "GET /cart":
        return html(200, this.page("Cart", `<p>Your cart</p>`));
      case "GET /checkout":
        return html(
          200,
          this.page(
            "Checkout",
            `<form id="f"><label for="name">Name</label><input id="name" name="name" required>
             <label for="email">Email</label><input id="email" name="email" type="email" required>
             <label for="coupon">Coupon</label><input id="coupon" name="coupon">
             <button type="submit">Place order</button></form><p id="result"></p>
             <script>
               document.getElementById('f').addEventListener('submit', async (event) => {
                 event.preventDefault();
                 const data = Object.fromEntries(new FormData(event.target));
                 const response = await fetch('/api/checkout', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(data)});
                 document.getElementById('result').textContent = response.ok ? 'Thanks!' : 'Something went wrong';
               });
             </script>`,
          ),
        );
      case "POST /api/cart":
        return json(200, { ok: true });
      case "POST /api/logout":
        return json(500, { detail: "logout must never be clicked" });
      case "POST /api/checkout": {
        const order = JSON.parse(body || "{}") as Record<string, string>;
        if (order.coupon) return json(200, { detail: "optional coupon was filled" });
        if (!this.healthy) return json(500, { detail: "TypeError: total - None" });
        return json(201, { order_id: "o-1", email: order.email });
      }
      case "GET /explode":
        return html(200, this.page("Explode", `<button onclick="setTimeout(() => { throw new TypeError('cart is undefined') })">Explode</button>`));
      case "GET /boundary":
        return html(200, this.page("Boundary", `<button onclick="console.error('The above error occurred in <Cart>; error boundary caught it')">Open cart</button>`));
      case "GET /broken":
        return html(500, "<p>Internal Server Error</p>");
      default:
        return html(404, "not found");
    }
  }

  async start(): Promise<void> {
    this.server = createServer((request, response) => {
      const chunks: Buffer[] = [];
      request.on("data", (chunk: Buffer) => chunks.push(chunk));
      request.on("end", () => this.routes(request, response, Buffer.concat(chunks).toString("utf8")));
    });
    await new Promise<void>((resolve) => this.server!.listen(0, "127.0.0.1", resolve));
    this.origin = `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => this.server?.close(() => resolve()));
  }
}

test.describe("runAutonomousCrawler in Chromium", () => {
  let browser: Browser;
  let shop: FixtureShop;

  test.beforeAll(async () => {
    browser = await chromium.launch({ headless: true });
  });
  test.afterAll(async () => {
    await browser.close();
  });
  test.beforeEach(async () => {
    shop = new FixtureShop();
    await shop.start();
  });
  test.afterEach(async () => {
    await shop.stop();
  });

  test("finds the checkout 500 and returns the click trail that reproduces it", async () => {
    const events: CrawlEvent[] = [];
    const report = await runAutonomousCrawler({ url: `${shop.origin}/`, browser, onEvent: (event) => events.push(event) });

    expect(report.status).toBe("failure");
    if (report.status !== "failure") return;
    expect(report.failure).toMatchObject({
      kind: "http_error",
      method: "POST",
      endpoint: "/api/checkout",
      status: 500,
      response_body: JSON.stringify({ detail: "TypeError: total - None" }),
    });
    expect(report.breadcrumbs.map(({ action, label }) => [action, label ?? null])).toEqual([
      ["navigate", null],
      ["click", "Widget"],
      ["click", "Add to cart"],
      ["click", "Proceed to checkout"],
      ["fill", "Name"],
      ["fill", "Email"],
      ["click", "Place order"],
    ]);
    expect(report.breadcrumbs.find((crumb) => crumb.label === "Email")).toMatchObject({ selector: "#email", value: "test@example.com" });
    expect(report.failure.step).toBe(7);
    expect(report.actions_taken).toBe(6);
    expect(report.pages_visited).toEqual([`${shop.origin}/`, `${shop.origin}/product/widget`, `${shop.origin}/checkout`]);
    // Destructive and external controls were never exercised.
    expect(shop.hits).not.toContain("POST /api/logout");
    expect(events[0]).toEqual({ type: "launch" });
    expect(events.at(-1)).toEqual({ type: "report", report });
    expect(events.filter((event) => event.type === "action" && !event.ok)).toHaveLength(1);
    expect(events.find((event) => event.type === "discovered" && event.url.endsWith("/checkout"))).toMatchObject({ forms: 1, buttons: 2, links: 3 });
    expect(events.find((event) => event.type === "action" && event.label === "Place order")).toMatchObject({
      url: `${shop.origin}/checkout`,
      element: "button",
      submit: true,
      ok: false,
    });
  });

  test("replaying the breadcrumbs reproduces the same failure", async () => {
    const report = await runAutonomousCrawler({ url: `${shop.origin}/`, browser });
    expect(report.status).toBe("failure");
    const page = await browser.newPage();
    try {
      const statuses: number[] = [];
      page.on("response", (response) => {
        if (new URL(response.url()).pathname === "/api/checkout") statuses.push(response.status());
      });
      for (const crumb of report.breadcrumbs) {
        if (crumb.action === "navigate") await page.goto(crumb.url);
        else if (crumb.action === "click") await page.locator(crumb.selector!).click();
        else if (crumb.action === "fill") await page.locator(crumb.selector!).fill(crumb.value!);
      }
      await expect.poll(() => statuses).toEqual([500]);
    } finally {
      await page.close();
    }
  });

  test("returns a clean report when nothing breaks", async () => {
    shop.healthy = true;
    const report = await runAutonomousCrawler({ url: `${shop.origin}/`, browser, maxActions: 15 });
    expect(report.status).toBe("clean");
    if (report.status !== "clean") return;
    expect(["exhausted", "max_actions"]).toContain(report.stop_reason);
    expect(report.actions_taken).toBeGreaterThanOrEqual(6);
    expect(report.elements_explored).toBeGreaterThan(5);
    expect(shop.hits).toContain("POST /api/checkout");
    expect(shop.hits).not.toContain("POST /api/logout");
  });

  test("stops clean at maxActions", async () => {
    shop.healthy = true;
    const report = await runAutonomousCrawler({ url: `${shop.origin}/`, browser, maxActions: 2 });
    expect(report).toMatchObject({ status: "clean", stop_reason: "max_actions", actions_taken: 2 });
  });

  test("catches uncaught page errors with their stack", async () => {
    const report = await runAutonomousCrawler({ url: `${shop.origin}/explode`, browser });
    expect(report.status).toBe("failure");
    if (report.status !== "failure") return;
    expect(report.failure.kind).toBe("page_error");
    expect(report.failure.message).toBe("TypeError: cart is undefined");
    expect(report.failure.stack).toContain("cart is undefined");
    expect(report.breadcrumbs.at(-1)).toMatchObject({ action: "click", label: "Explode" });
  });

  test("catches console.error reports such as React error boundaries", async () => {
    const report = await runAutonomousCrawler({ url: `${shop.origin}/boundary`, browser });
    expect(report.status).toBe("failure");
    if (report.status !== "failure") return;
    expect(report.failure.kind).toBe("console_error");
    expect(report.failure.message).toContain("error boundary");
  });

  test("reports a page that fails on load at the navigate step", async () => {
    const report = await runAutonomousCrawler({ url: `${shop.origin}/broken`, browser });
    expect(report.status).toBe("failure");
    if (report.status !== "failure") return;
    expect(report.failure).toMatchObject({ kind: "http_error", status: 500, method: "GET", endpoint: "/broken", step: 1 });
  });

  test("reports an unreachable site as a crawl error", async () => {
    const origin = shop.origin;
    await shop.stop();
    const report = await runAutonomousCrawler({ url: `${origin}/`, browser });
    expect(report.status).toBe("error");
    if (report.status !== "error") return;
    expect(report.error).toContain("Could not load");
    shop = new FixtureShop();
    await shop.start();
  });

  test("--crawl --ndjson streams events and exits 1 with the report last", async () => {
    const cli = path.resolve(import.meta.dirname, "../../dist/cli.js");
    const child = spawn(process.execPath, [cli, "--crawl", `${shop.origin}/`, "--ndjson", "--max-actions", "10"], { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => (stdout += chunk));
    const code = await new Promise<number | null>((resolve) => child.on("close", resolve));
    const events = stdout.trim().split("\n").map((line) => JSON.parse(line) as CrawlEvent);
    expect(code).toBe(1);
    expect(events[0]).toEqual({ type: "launch" });
    const last = events.at(-1);
    expect(last?.type).toBe("report");
    if (last?.type !== "report") return;
    expect(last.report).toMatchObject({ status: "failure", failure: { status: 500, endpoint: "/api/checkout" } });
  });
});
