import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type Context = { params: Promise<{ path: string[] }> };
const READ_PATH = /^(?:readiness|scenarios|jobs|jobs\/[\da-f-]+(?:\/events)?|artifacts\/[\da-f-]+)$/i;
const WRITE_PATH = /^(?:jobs|reset|revert|jobs\/[\da-f-]+\/(?:cancel|apply))$/i;

function isLoopbackOrPrivateHost(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname === "127.0.0.1" ||
    hostname.startsWith("127.") ||
    hostname === "[::1]" ||
    hostname === "::1" ||
    hostname === "0.0.0.0" ||
    hostname.endsWith(".local") ||
    hostname.endsWith(".lan") ||
    hostname.startsWith("192.168.") ||
    hostname.startsWith("10.") ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname)
  );
}

async function proxy(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const target = path.join("/");
  if (!(request.method === "GET" ? READ_PATH : WRITE_PATH).test(target)) {
    return NextResponse.json({ error: { message: "Unknown controller route." } }, { status: 404 });
  }
  // The controller credential stays server-side. Cross-site pages cannot use it
  // to submit jobs through this local UI, including form POSTs without CORS.
  if (request.method === "POST") {
    const origin = request.headers.get("origin");
    const secFetchSite = request.headers.get("sec-fetch-site");
    if (origin) {
      let isAllowed = origin === request.nextUrl.origin;
      try {
        const originUrl = new URL(origin);
        const hostHeader = request.headers.get("host");
        const fwdHost = request.headers.get("x-forwarded-host");
        if ((hostHeader && originUrl.host === hostHeader) || (fwdHost && originUrl.host === fwdHost)) {
          isAllowed = true;
        }
        if (isLoopbackOrPrivateHost(originUrl.hostname)) {
          isAllowed = true;
        }
      } catch {
        isAllowed = false;
      }
      if (!isAllowed) {
        return NextResponse.json(
          { error: { code: "forbidden", message: "Same-origin or local network request required." } },
          { status: 403 }
        );
      }
    } else if (secFetchSite === "cross-site") {
      return NextResponse.json(
        { error: { code: "forbidden", message: "Same-origin request required." } },
        { status: 403 }
      );
    }
  }
  const token = process.env.FAULTLINE_CONTROL_TOKEN;
  if (!token) {
    return NextResponse.json({ error: { message: "Set FAULTLINE_CONTROL_TOKEN on the Inspector server." } }, { status: 503 });
  }
  const headers = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of ["accept", "content-type", "last-event-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const base = process.env.FAULTLINE_ORCHESTRATOR_URL || "http://127.0.0.1:9000";
  try {
    const body = request.method === "POST" ? await request.text() : undefined;
    if (body && new TextEncoder().encode(body).length > 4096) {
      return NextResponse.json({ error: { message: "Request is too large." } }, { status: 413 });
    }
    const upstream = await fetch(`${base}/api/faultline/${target}${request.nextUrl.search}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: request.signal,
    });
    const responseHeaders = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of ["content-type", "content-disposition", "content-security-policy", "www-authenticate"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (upstream.headers.get("content-type")?.includes("text/event-stream")) {
      responseHeaders.set("Cache-Control", "no-cache, no-transform");
      responseHeaders.set("X-Accel-Buffering", "no");
    }
    // Stream raw bytes: JSON decoding corrupts PNG/ZIP evidence and SSE errors.
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ error: { message: "Controller unavailable. Start the demo stack and retry." } }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
