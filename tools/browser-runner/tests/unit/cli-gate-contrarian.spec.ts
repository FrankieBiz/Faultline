import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { chromium, expect, test, type Browser } from "@playwright/test";
import { displayPath, normalizeUrl, runAutonomousCrawler, type CrawlEvent } from "../../src/crawler.js";
import { ArtifactStore } from "../../src/evidence.js";

/**
 * Hostile contrarian audit of the Agent Gate CLI and crawler.
 *
 * Three attack surfaces are exercised here:
 *   1. Cross-platform path handling — a Windows-authored `relative_path` must
 *      land in the POSIX-equivalent location and be emitted with forward
 *      slashes, and `resolve` must reject `..` escapes written with either
 *      separator style.
 *   2. An uncaught runtime error thrown on load (step 0, before any click)
 *      must still produce a valid machine-readable JSON gate report and a
 *      CLI exit code of 1.
 *   3. A slow first page that exhausts the crawl budget must be reported as a
 *      clean `timeout`, never an infrastructure `error`.
 */

test.describe("cross-platform path handling", () => {
  test("writes a backslash relative path to its POSIX location and emits POSIX relative_path", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "faultline-paths-"));
    try {
      const store = new ArtifactStore(root);
      await store.init();
      // A Windows-authored path: the backslash is a separator, not a filename byte.
      const entry = await store.write("network_log", "logs\\network.json", "application/json", "{}\n");
      expect(entry.relative_path).toBe("logs/network.json");
      expect(await readFile(path.join(root, "logs", "network.json"), "utf8")).toBe("{}\n");
      // `register` (used by screenshot/trace capture) normalizes the same way.
      await store.write("trace", "screenshots\\failure.png", "application/zip", "zip-bytes");
      const reregistered = await store.register("trace", "screenshots\\failure.png", "application/zip");
      expect(reregistered.relative_path).toBe("screenshots/failure.png");
      expect(await readFile(path.join(root, "screenshots", "failure.png"), "utf8")).toBe("zip-bytes");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("resolve rejects directory escapes in both POSIX and Windows separator styles", () => {
    const root = path.join(tmpdir(), "faultline-root");
    const store = new ArtifactStore(root);
    for (const escape of ["../escape.txt", "..\\escape.txt", "sub/../../escape.txt", "sub\\..\\..\\escape.txt", "a/..\\b/../../x"]) {
      expect(() => store.resolve(escape), JSON.stringify(escape)).toThrow(/escapes/);
    }
    // Contained paths resolve to the same place regardless of separator style.
    expect(store.resolve("screenshots/failure.png")).toBe(path.resolve(root, "screenshots", "failure.png"));
    expect(store.resolve("screenshots\\failure.png")).toBe(path.resolve(root, "screenshots", "failure.png"));
  });

  test("crawler URL helpers fold Windows backslashes into forward-slash paths", () => {
    const origin = "http://shop.test";
    expect(normalizeUrl(`${origin}/checkout\\foo#top`)).toBe(`${origin}/checkout/foo`);
    expect(displayPath(`${origin}/checkout\\foo\\bar`, origin)).toBe("/checkout/foo/bar");
    // Hash routes are preserved while ordinary fragments are dropped.
    expect(normalizeUrl(`${origin}/#/cart`)).toBe(`${origin}/#/cart`);
    expect(normalizeUrl(`${origin}/faq#shipping`)).toBe(`${origin}/faq`);
    // Cross-origin URLs are shown in full, and normalizeUrl still folds their backslashes.
    expect(displayPath("https://example.com/x", origin)).toBe("https://example.com/x");
    expect(normalizeUrl("https://example.com/a\\b")).toBe("https://example.com/a/b");
  });
});

/** A minimal fixture: a page that throws on load, and a page that never arrives in time. */
class ContrarianFixture {
  private server: Server | undefined;
  origin = "";

  private routes(request: IncomingMessage, response: ServerResponse): void {
    const url = new URL(request.url ?? "/", this.origin);
    if (url.pathname === "/boom") {
      response
        .writeHead(200, { "content-type": "text/html" })
        .end(`<!doctype html><html><head><title>Boom</title></head><body><h1>Boom</h1><script>throw new TypeError("boot exploded");</script></body></html>`);
      return;
    }
    if (url.pathname === "/slow") {
      // Respond well after any sane crawl budget; the client aborts first.
      const timer = setTimeout(() => {
        if (!response.destroyed && !response.writableEnded) {
          response.writeHead(200, { "content-type": "text/html" }).end("<title>Slow</title><p>late</p>");
        }
      }, 3_000);
      response.on("close", () => clearTimeout(timer));
      return;
    }
    response.writeHead(404, { "content-type": "text/plain" }).end("not found");
  }

  async start(): Promise<void> {
    this.server = createServer((request, response) => this.routes(request, response));
    await new Promise<void>((resolve) => this.server!.listen(0, "127.0.0.1", resolve));
    this.origin = `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => this.server?.close(() => resolve()));
  }
}

test.describe("agent gate edge cases in Chromium", () => {
  let browser: Browser;
  let fixture: ContrarianFixture;

  test.beforeAll(async () => {
    browser = await chromium.launch({ headless: true });
  });
  test.afterAll(async () => {
    await browser.close();
  });
  test.beforeEach(async () => {
    fixture = new ContrarianFixture();
    await fixture.start();
  });
  test.afterEach(async () => {
    await fixture.stop();
  });

  test("reports an uncaught load-time error at step 0 before any click as a failure", async () => {
    const report = await runAutonomousCrawler({ url: `${fixture.origin}/boom`, browser });
    expect(report.status).toBe("failure");
    if (report.status !== "failure") return;
    expect(report.failure.kind).toBe("page_error");
    expect(report.failure.step).toBe(1);
    expect(report.failure.message).toBe("TypeError: boot exploded");
    // No DOM node was clicked before the defect was caught.
    expect(report.actions_taken).toBe(0);
    expect(report.screens_visited).toEqual([]);
    expect(report.reproduction_trail).toEqual([`1. Open ${fixture.origin}/boom -> Uncaught TypeError: boot exploded`]);
    // The gate report round-trips as valid machine-readable JSON.
    expect(() => JSON.parse(JSON.stringify(report))).not.toThrow();
    expect(JSON.parse(JSON.stringify(report))).toMatchObject({ status: "failure", actions_taken: 0 });
  });

  test("a slow first page that exhausts the budget is a clean timeout, not an error", async () => {
    const report = await runAutonomousCrawler({ url: `${fixture.origin}/slow`, browser, timeoutMs: 1_000 });
    expect(report.status).toBe("clean");
    if (report.status !== "clean") return;
    expect(report.stop_reason).toBe("timeout");
    expect(report.actions_taken).toBe(0);
  });

  test("--crawl emits a valid JSON gate report and exits 1 for a load-time defect", async () => {
    const cli = path.resolve(import.meta.dirname, "../../dist/cli.js");
    const child = spawn(process.execPath, [cli, "--crawl", `${fixture.origin}/boom`, "--ndjson"], { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => (stdout += chunk));
    const code = await new Promise<number | null>((resolve) => child.on("close", resolve));

    const events = stdout.trim().split("\n").map((line) => JSON.parse(line) as CrawlEvent);
    expect(code).toBe(1);
    expect(events[0]).toEqual({ type: "launch" });
    const last = events.at(-1);
    expect(last?.type).toBe("report");
    if (last?.type !== "report") return;
    const gateReport = last.report;
    expect(gateReport).toMatchObject({ status: "failure", actions_taken: 0 });
    if (gateReport.status !== "failure") return;
    expect(gateReport.failure).toMatchObject({ kind: "page_error", step: 1, message: "TypeError: boot exploded" });
  });
});
