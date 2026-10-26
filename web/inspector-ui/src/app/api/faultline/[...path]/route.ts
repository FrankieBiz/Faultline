import { NextRequest, NextResponse } from "next/server";

const ORCHESTRATOR_URL = process.env.FAULTLINE_ORCHESTRATOR_URL || "http://127.0.0.1:9000";
const CONTROL_TOKEN = process.env.FAULTLINE_CONTROL_TOKEN || "dev-control-token";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const targetPath = path.join("/");
  const targetUrl = `${ORCHESTRATOR_URL}/api/faultline/${targetPath}${request.nextUrl.search}`;

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${CONTROL_TOKEN}`);
  headers.set("Accept", request.headers.get("Accept") || "application/json");

  try {
    const response = await fetch(targetUrl, {
      method: "GET",
      headers,
    });

    if (request.headers.get("Accept")?.includes("text/event-stream") || targetPath.endsWith("/events")) {
      return new Response(response.body, {
        status: response.status,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
        },
      });
    }

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { error: "Orchestrator proxy unreachable", detail: message },
      { status: 502 }
    );
  }
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const targetPath = path.join("/");
  const targetUrl = `${ORCHESTRATOR_URL}/api/faultline/${targetPath}`;

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${CONTROL_TOKEN}`);
  headers.set("Content-Type", "application/json");

  try {
    let bodyText = "";
    try {
      bodyText = await request.text();
    } catch {
      bodyText = "";
    }

    const response = await fetch(targetUrl, {
      method: "POST",
      headers,
      body: bodyText ? bodyText : undefined,
    });

    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { error: "Orchestrator proxy unreachable", detail: message },
      { status: 502 }
    );
  }
}
