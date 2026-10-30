import { test, expect } from "@playwright/test";
import { NextRequest } from "../../../../web/inspector-ui/node_modules/next/server.js";
import { GET, POST } from "../../../../web/inspector-ui/src/app/api/faultline/[...path]/route.js";
import { api } from "../../../../web/inspector-ui/src/lib/faultline-api.js";
import { GET as shopGET } from "../../../../apps/buggyshop-frontend/src/app/api/[...path]/route.js";

const originalFetch = globalThis.fetch;
const previousToken = process.env.FAULTLINE_CONTROL_TOKEN;
const previousBackend = process.env.BUGGYSHOP_BACKEND_URL;
const id = "00000000-0000-4000-8000-000000000001";

test.beforeEach(() => { process.env.FAULTLINE_CONTROL_TOKEN = "test-proxy-credential"; });
test.afterEach(() => {
  globalThis.fetch = originalFetch;
  if (previousToken === undefined) delete process.env.FAULTLINE_CONTROL_TOKEN;
  else process.env.FAULTLINE_CONTROL_TOKEN = previousToken;
  if (previousBackend === undefined) delete process.env.BUGGYSHOP_BACKEND_URL;
  else process.env.BUGGYSHOP_BACKEND_URL = previousBackend;
});

function context(...path) { return { params: Promise.resolve({ path }) }; }

test("artifact proxy preserves binary bytes and inert download headers", async () => {
  const bytes = Uint8Array.from([137, 80, 78, 71, 0, 255, 128]);
  globalThis.fetch = async (_url, init) => {
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer test-proxy-credential");
    return new Response(bytes, { headers: { "content-type": "image/png", "content-disposition": 'attachment; filename="capture"', "content-security-policy": "default-src 'none'" } });
  };
  const response = await GET(new NextRequest(`http://localhost/api/faultline/artifacts/${id}`), context("artifacts", id));
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
  expect(response.headers.get("content-type")).toBe("image/png");
  expect(response.headers.get("content-disposition")).toContain("attachment");
  expect(response.headers.get("x-content-type-options")).toBe("nosniff");
});

test("SSE proxy forwards resume cursor and preserves upstream error type", async () => {
  globalThis.fetch = async (_url, init) => {
    expect(new Headers(init?.headers).get("last-event-id")).toBe("4");
    return Response.json({ error: { message: "missing" } }, { status: 404 });
  };
  const request = new NextRequest(`http://localhost/api/faultline/jobs/${id}/events`, { headers: { "last-event-id": "4", accept: "text/event-stream" } });
  const response = await GET(request, context("jobs", id, "events"));
  expect(response.status).toBe(404);
  expect(response.headers.get("content-type")).toContain("application/json");
});

test("proxy requires configured credentials and rejects cross-origin mutations", async () => {
  globalThis.fetch = async () => { throw new Error("must not contact upstream"); };
  delete process.env.FAULTLINE_CONTROL_TOKEN;
  expect((await GET(new NextRequest("http://localhost/api/faultline/jobs"), context("jobs"))).status).toBe(503);
  const request = new NextRequest("http://localhost/api/faultline/reset", { method: "POST", headers: { origin: "https://attacker.example" } });
  expect((await POST(request, context("reset"))).status).toBe(403);
});

test("storefront proxy reads backend origin at runtime and forwards correlation", async () => {
  process.env.BUGGYSHOP_BACKEND_URL = "http://127.0.0.1:54321";
  globalThis.fetch = async (url, init) => {
    expect(String(url)).toBe("http://127.0.0.1:54321/api/products");
    expect(new Headers(init?.headers).get("x-faultline-case-id")).toBe("test-case");
    return Response.json([], { headers: { "x-request-id": "server-request" } });
  };
  const response = await shopGET(new NextRequest("http://localhost/api/products", { headers: { "x-faultline-case-id": "test-case" } }), context("products"));
  expect(response.headers.get("x-request-id")).toBe("server-request");
  expect(await response.json()).toEqual([]);
});

for (const host of ["127.0.0.1:4101", "localhost:4101"]) {
  test(`proxy accepts browser origin from actual Host ${host}`, async () => {
    globalThis.fetch = async () => Response.json({ status: "ok" });
    // Next may normalize the internal URL to localhost while retaining Host.
    const request = new NextRequest("http://localhost:4101/api/faultline/reset", {
      method: "POST", headers: { host, origin: `http://${host}`, "sec-fetch-site": "same-origin" },
    });
    expect((await POST(request, context("reset"))).status).toBe(200);
  });
}

test("proxy accepts an Orca-forwarded same-origin browser request", async () => {
  globalThis.fetch = async () => Response.json({ status: "ok" });
  // Orca replaces Host with the loopback upstream while retaining the browser origin.
  const request = new NextRequest("http://localhost:4101/api/faultline/reset", {
    method: "POST", headers: {
      host: "127.0.0.1:4101", origin: "http://judge-demo.orca.localhost:41489",
      "sec-fetch-site": "same-origin",
    },
  });
  expect((await POST(request, context("reset"))).status).toBe(200);
});

for (const site of ["same-site", "cross-site", "none", null]) {
  test(`proxy rejects an Orca origin without same-origin fetch metadata (${site})`, async () => {
    globalThis.fetch = async () => { throw new Error("must not contact upstream"); };
    const headers = { host: "127.0.0.1:4101", origin: "http://judge-demo.orca.localhost:41489" };
    if (site !== null) headers["sec-fetch-site"] = site;
    const request = new NextRequest("http://localhost:4101/api/faultline/reset", { method: "POST", headers });
    expect((await POST(request, context("reset"))).status).toBe(403);
  });
}

for (const [origin, site] of [
  ["http://attacker.example:4101", "same-origin"],
  ["http://127.0.0.1:4102", "same-origin"],
  ["https://127.0.0.1:4101", "same-origin"],
  ["http://localhost:4101", "same-site"],
  ["http://127.0.0.1:4101", "cross-site"],
  ["http://judge-demo.orca.localhost.attacker.example:41489", "same-origin"],
  ["https://judge-demo.orca.localhost:41489", "same-origin"],
  ["null", "same-origin"],
]) {
  test(`proxy rejects mismatched browser origin ${origin} (${site})`, async () => {
    globalThis.fetch = async () => { throw new Error("must not contact upstream"); };
    const request = new NextRequest("http://localhost:4101/api/faultline/reset", {
      method: "POST", headers: { host: "127.0.0.1:4101", origin, "sec-fetch-site": site },
    });
    expect((await POST(request, context("reset"))).status).toBe(403);
  });
}

// DNS rebinding: a page on evil.example rebound to 127.0.0.1 is "same-origin" with
// itself, so only the Host allowlist keeps the controller credential out of reach.
for (const host of [
  "evil.example:4101", "127.0.0.1.evil.example:4101", "localhost.evil.example", "orca.localhost.evil.example",
  "127.0.0.1:4101@evil.example", "evil.example",
]) {
  for (const [method, path] of [["GET", ["jobs"]], ["GET", ["artifacts", id]], ["GET", ["jobs", id, "events"]], ["POST", ["reset"]], ["POST", ["jobs"]]]) {
    test(`proxy rejects non-loopback Host ${host} for ${method} ${path.join("/")}`, async () => {
      globalThis.fetch = async () => { throw new Error("must not contact upstream"); };
      const headers = { host, ...(method === "POST" ? { origin: `http://${host}`, "sec-fetch-site": "same-origin" } : {}) };
      const request = new NextRequest(`http://localhost:4101/api/faultline/${path.join("/")}`, { method, headers });
      const response = await (method === "GET" ? GET : POST)(request, context(...path));
      expect(response.status).toBe(403);
    });
  }
}

for (const host of ["127.0.0.1:4101", "localhost:4101", "judge-demo.orca.localhost:41489"]) {
  test(`proxy serves reads for loopback Host ${host}`, async () => {
    globalThis.fetch = async () => Response.json({ jobs: [] });
    const request = new NextRequest("http://localhost:4101/api/faultline/jobs", { headers: { host } });
    expect((await GET(request, context("jobs"))).status).toBe(200);
  });
}

test("client displays actionable message-only proxy errors", async () => {
  globalThis.fetch = async () => Response.json({ error: { message: "Set FAULTLINE_CONTROL_TOKEN on the Inspector server." } }, { status: 503 });
  await expect(api("jobs")).rejects.toThrow("Set FAULTLINE_CONTROL_TOKEN on the Inspector server.");
});
