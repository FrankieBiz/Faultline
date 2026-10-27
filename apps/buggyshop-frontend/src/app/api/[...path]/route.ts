import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = path.join("/");
  if (!/^(?:products(?:\/[a-z0-9-]+)?|checkout|orders(?:\/[a-z0-9-]+)?)$/i.test(target)) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  // Runtime selection is essential: each verified candidate has its own server.
  // Next.js rewrites would bake the development backend into the build.
  const base = process.env.BUGGYSHOP_BACKEND_URL || "http://127.0.0.1:8000";
  const headers = new Headers();
  for (const name of ["content-type", "accept", "x-faultline-case-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const response = await fetch(`${base}/api/${target}${request.nextUrl.search}`, {
      method: request.method, headers, cache: "no-store", redirect: "error",
      body: request.method === "POST" ? await request.text() : undefined,
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(10_000)]),
    });
    const resultHeaders = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "x-request-id"]) {
      const value = response.headers.get(name);
      if (value) resultHeaders.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers: resultHeaders });
  } catch {
    return NextResponse.json({ detail: "Checkout service unavailable. Retry when the backend is ready." }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
