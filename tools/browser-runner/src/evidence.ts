/**
 * Evidence capture for one browser case: bounded first-party network and
 * console logs, plus an artifact store that writes files beneath the
 * artifacts directory and records their manifest entries (ID, relative path,
 * role, size, SHA-256) as required by SpecV1 §4 and §11.3.
 */

import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Page, Request, Response } from "@playwright/test";
import type { ArtifactManifest, ArtifactManifestEntry, ArtifactRole } from "./contracts.js";

/** File name of the manifest written beside the evidence. */
export const MANIFEST_FILE = "artifacts.json";

/** Per-body and per-execution caps on captured response text (SpecV1 §11.3). */
export const MAX_BODY_BYTES = 2 * 1024;
export const MAX_TOTAL_BODY_BYTES = 16 * 1024;
/** Cap on retained console entries and on each entry's text. */
const MAX_CONSOLE_ENTRIES = 200;
const MAX_CONSOLE_TEXT = 1024;
const MAX_STACK = 4 * 1024;
const MAX_POST_DATA = 2 * 1024;

const TEXTUAL_CONTENT = /^(application\/(json|problem\+json|[\w.+-]*\+json)|text\/)/i;
const SENSITIVE_HEADERS = new Set(["authorization", "cookie", "set-cookie", "proxy-authorization"]);

/** Truncates text to a byte budget, appending an explicit marker when cut. */
export function truncateUtf8(text: string, maxBytes: number): { text: string; truncated: boolean } {
  const bytes = Buffer.from(text, "utf8");
  if (bytes.length <= maxBytes) return { text, truncated: false };
  // Decoding a cut buffer may end in a replacement character; strip it.
  const cut = bytes.subarray(0, maxBytes).toString("utf8").replace(/�$/, "");
  return { text: `${cut}…[truncated ${bytes.length - maxBytes} bytes]`, truncated: true };
}

/** One first-party request/response pair in the network log. */
export interface NetworkEntry {
  method: string;
  url: string;
  resource_type: string;
  request_headers: Record<string, string>;
  post_data: string | null;
  status: number | null;
  response_headers: Record<string, string>;
  request_id: string | null;
  response_body: string | null;
  response_body_truncated: boolean;
  failure: string | null;
  started_at: string;
  finished_at: string | null;
}

/** One browser console message. */
export interface ConsoleEntry {
  type: string;
  text: string;
  location: string | null;
  at: string;
}

/** One uncaught exception thrown in the page. */
export interface PageErrorEntry {
  name: string;
  message: string;
  stack: string | null;
  at: string;
}

function redactHeaders(headers: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers)) {
    result[name] = SENSITIVE_HEADERS.has(name.toLowerCase()) ? "[redacted]" : value;
  }
  return result;
}

/**
 * Listens to a page from before its first navigation and records first-party
 * traffic, console output, and page errors. Response bodies are read
 * asynchronously; call {@link drain} before closing the context so every
 * pending read finishes.
 */
export class PageEvidenceCollector {
  readonly network: NetworkEntry[] = [];
  readonly console: ConsoleEntry[] = [];
  readonly pageErrors: PageErrorEntry[] = [];
  droppedConsoleEntries = 0;
  bodyBytesCaptured = 0;
  bodyCaptureExhausted = false;

  private readonly origin: string;
  private readonly entries = new Map<Request, NetworkEntry>();
  private readonly pending = new Set<Promise<void>>();

  constructor(baseUrl: string) {
    this.origin = new URL(baseUrl).origin;
  }

  /** True when the URL belongs to the application under test. */
  isFirstParty(url: string): boolean {
    try {
      return new URL(url).origin === this.origin;
    } catch {
      return false;
    }
  }

  /** True for first-party requests to the backend proxy path. */
  isApiRequest(url: string): boolean {
    return this.isFirstParty(url) && new URL(url).pathname.startsWith("/api/");
  }

  /** Attaches all listeners. Must be called before `page.goto`. */
  attach(page: Page): void {
    page.on("request", (request) => this.onRequest(request));
    page.on("response", (response) => this.onResponse(response));
    page.on("requestfailed", (request) => this.onRequestFailed(request));
    page.on("console", (message) => {
      if (this.console.length >= MAX_CONSOLE_ENTRIES) {
        this.droppedConsoleEntries += 1;
        return;
      }
      const location = message.location();
      this.console.push({
        type: message.type(),
        text: truncateUtf8(message.text(), MAX_CONSOLE_TEXT).text,
        location: location.url ? `${location.url}:${location.lineNumber}:${location.columnNumber}` : null,
        at: new Date().toISOString(),
      });
    });
    page.on("pageerror", (error) => {
      this.pageErrors.push({
        name: error.name || "Error",
        message: truncateUtf8(error.message, MAX_CONSOLE_TEXT).text,
        stack: error.stack ? truncateUtf8(error.stack, MAX_STACK).text : null,
        at: new Date().toISOString(),
      });
    });
  }

  /** Waits for every in-flight response body read to settle. */
  async drain(): Promise<void> {
    while (this.pending.size > 0) {
      await Promise.allSettled([...this.pending]);
    }
  }

  /** First-party API responses with a 5xx status. */
  serverErrors(): Array<{ method: string; url: string; status: number }> {
    return this.network
      .filter((entry) => entry.status !== null && entry.status >= 500)
      .map((entry) => ({ method: entry.method, url: entry.url, status: entry.status as number }));
  }

  private onRequest(request: Request): void {
    if (!this.isFirstParty(request.url())) return;
    const postData = request.postData();
    const entry: NetworkEntry = {
      method: request.method(),
      url: request.url(),
      resource_type: request.resourceType(),
      request_headers: redactHeaders(request.headers()),
      post_data: postData === null ? null : truncateUtf8(postData, MAX_POST_DATA).text,
      status: null,
      response_headers: {},
      request_id: null,
      response_body: null,
      response_body_truncated: false,
      failure: null,
      started_at: new Date().toISOString(),
      finished_at: null,
    };
    this.entries.set(request, entry);
    // Static assets are kept out of the log; only API traffic is evidence.
    if (this.isApiRequest(request.url())) this.network.push(entry);
  }

  private onResponse(response: Response): void {
    const entry = this.entries.get(response.request());
    if (!entry || !this.isApiRequest(entry.url)) return;
    const headers = response.headers();
    entry.status = response.status();
    entry.response_headers = redactHeaders(headers);
    entry.request_id = headers["x-request-id"] ?? null;
    entry.finished_at = new Date().toISOString();
    if (!TEXTUAL_CONTENT.test(headers["content-type"] ?? "")) return;

    const read = response
      .text()
      .then((body) => {
        const remaining = MAX_TOTAL_BODY_BYTES - this.bodyBytesCaptured;
        if (remaining <= 0) {
          this.bodyCaptureExhausted = true;
          return;
        }
        const clipped = truncateUtf8(body, Math.min(MAX_BODY_BYTES, remaining));
        entry.response_body = clipped.text;
        entry.response_body_truncated = clipped.truncated;
        this.bodyBytesCaptured += Math.min(Buffer.byteLength(body, "utf8"), MAX_BODY_BYTES, remaining);
      })
      .catch((error: unknown) => {
        entry.response_body = null;
        entry.failure = `body unavailable: ${error instanceof Error ? error.message : String(error)}`;
      });
    const tracked = read.finally(() => this.pending.delete(tracked));
    this.pending.add(tracked);
  }

  private onRequestFailed(request: Request): void {
    const entry = this.entries.get(request);
    if (!entry || !this.isApiRequest(entry.url)) return;
    entry.failure = request.failure()?.errorText ?? "request failed";
    entry.finished_at = new Date().toISOString();
  }
}

/**
 * Writes evidence files beneath one artifacts directory and builds the
 * manifest. Relative paths are generated here, never taken from input, so
 * every artifact is contained in the directory.
 */
export class ArtifactStore {
  readonly entries: ArtifactManifestEntry[] = [];

  constructor(readonly root: string) {}

  /** Ensures the artifacts directory exists. */
  async init(): Promise<void> {
    await mkdir(this.root, { recursive: true });
  }

  /** Absolute path for a store-chosen relative path. */
  resolve(relativePath: string): string {
    const resolved = path.resolve(this.root, relativePath);
    const relative = path.relative(this.root, resolved);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
      throw new Error(`Artifact path escapes the artifacts directory: ${relativePath}`);
    }
    return resolved;
  }

  /** Writes bytes and registers them. */
  async write(role: ArtifactRole, relativePath: string, contentType: string, data: string | Uint8Array): Promise<ArtifactManifestEntry> {
    const target = this.resolve(relativePath);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, data);
    return this.register(role, relativePath, contentType);
  }

  /** Writes a JSON document and registers it. */
  async writeJson(role: ArtifactRole, relativePath: string, value: unknown): Promise<ArtifactManifestEntry> {
    return this.write(role, relativePath, "application/json", `${JSON.stringify(value, null, 2)}\n`);
  }

  /** Writes the manifest of every registered artifact. The manifest does not list itself. */
  async writeManifest(manifest: ArtifactManifest): Promise<void> {
    await writeFile(this.resolve(MANIFEST_FILE), `${JSON.stringify(manifest, null, 2)}\n`);
  }

  /** Registers a file another API (screenshot, trace) has already written. */
  async register(role: ArtifactRole, relativePath: string, contentType: string): Promise<ArtifactManifestEntry> {
    const target = this.resolve(relativePath);
    const [bytes, info] = await Promise.all([readFile(target), stat(target)]);
    if (!info.isFile()) throw new Error(`Artifact is not a regular file: ${relativePath}`);
    const entry: ArtifactManifestEntry = {
      artifact_id: randomUUID(),
      role,
      relative_path: relativePath.split(path.sep).join("/"),
      content_type: contentType,
      size_bytes: info.size,
      sha256: createHash("sha256").update(bytes).digest("hex"),
    };
    this.entries.push(entry);
    return entry;
  }
}
