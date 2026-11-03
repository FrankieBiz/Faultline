/**
 * Autonomous crawler: points headless Chromium at a URL and tries to break it.
 *
 * `runAutonomousCrawler` needs no expected statuses or scripted steps. It
 * loads the page, discovers interactive elements, fills required form fields
 * with realistic sample values, and clicks through same-origin controls in a
 * shopping-funnel order (content links and product cards, add-to-cart,
 * checkout, commit buttons), skipping destructive controls such as Remove or
 * Log out. Commit controls are clicked only on disposable origins (localhost,
 * loopback, or a private network address) unless `allowCommitActions` is set.
 * Elsewhere the crawler never clicks a submit control or a button in a POST
 * form, never fills a POST form, and never clicks a control named like a
 * commit (Place order, Pay, Book, Donate, Subscribe, Publish, ...). Those
 * labels are a denylist, so a script-driven control with an unrecognized
 * name can still fire; a crawl that skipped any commit control ends with
 * `skipped_commit_controls` rather than `exhausted`, so the gate does not
 * pass it. When a screen has nothing left to try, it moves on to the most
 * promising same-origin screen it has seen linked but not yet visited (cart
 * and checkout first), up to {@link MAX_SCREENS} screens. After every action
 * it waits for the page to settle and checks for:
 *
 * - HTTP 5xx responses, and 400/422 from fetch/XHR or documents;
 * - uncaught page errors (including unhandled promise rejections);
 * - failed fetch/XHR requests (connection refused, reset);
 * - `console.error` output, such as React error-boundary reports.
 *
 * The first action that triggers any of these halts the crawl with a report
 * naming the failure, the breadcrumb trail that reproduces it, and the same
 * trail as numbered plain-language steps (`reproduction_trail`). Otherwise
 * the crawl stops cleanly after `maxActions`, the time budget, the screen
 * limit, or when no unexplored control is left.
 */

import { performance } from "node:perf_hooks";
import { chromium, type Browser, type BrowserContext, type Page, type Request, type Response } from "@playwright/test";
import { truncateUtf8 } from "./evidence.js";

export const DEFAULT_MAX_ACTIONS = 15;
export const MAX_CRAWL_ACTIONS = 100;
export const DEFAULT_CRAWL_TIMEOUT_MS = 60_000;
export const MAX_CRAWL_TIMEOUT_MS = 300_000;
/** Screens the crawler will jump to from its frontier; bounds sprawling sites. */
export const MAX_SCREENS = 30;
/** Bound on one click or fill. */
const ACTION_TIMEOUT_MS = 3_000;
/** The page counts as settled once no request has been in flight for this long. */
const QUIET_MS = 400;
/** Upper bound on settling after one action. */
const SETTLE_CAP_MS = 5_000;
const MAX_BODY_BYTES = 4 * 1024;
const MAX_LABEL_CHARS = 80;
/** Elements the crawler can click, including script-driven cards (`onclick`, `data-href`, `role=link`). */
const CLICKABLE_CSS =
  'a[href], button, [role="button"], input[type="submit"], input[type="button"], [role="link"], [role="tab"], [role="menuitem"], [data-href], [onclick], summary';
/** Elements the crawler can fill. */
const FIELD_CSS = "input, textarea, select";
/** 4xx statuses that signal a defect when an application request receives them. */
const CLIENT_ERROR_STATUSES = new Set([400, 422]);
const APPLICATION_RESOURCES = new Set(["fetch", "xhr", "document"]);

export type CrawlAction = "navigate" | "click" | "fill" | "select" | "check";

/** One reproducible step; replaying the trail in order reproduces the failure. */
export interface Breadcrumb {
  step: number;
  action: CrawlAction;
  /** Page URL when the action ran (the destination for `navigate`). */
  url: string;
  /** Playwright selector the action targeted. */
  selector?: string;
  /** Human-readable name of the element. */
  label?: string;
  /** Value typed or selected. */
  value?: string;
  /** Kind of element an interaction targeted. */
  element?: ElementKind;
}

export type ElementKind = "button" | "link" | "field";

export type SignalKind = "http_error" | "page_error" | "request_failed" | "console_error";

/** One failure signal observed in the page. */
export interface CrawlSignal {
  kind: SignalKind;
  message: string;
  method?: string;
  url?: string;
  /** Path and query of `url`, e.g. `/api/checkout`. */
  endpoint?: string;
  status?: number;
  response_body?: string;
  stack?: string;
}

/** The defect that halted the crawl. */
export interface CrawlFailure extends CrawlSignal {
  /** Breadcrumb step whose action triggered the failure. */
  step: number;
  /** Every console error seen up to and including the failing step. */
  console_errors: string[];
  /** Other signals the same action produced. */
  related: CrawlSignal[];
}

/**
 * Why a clean crawl stopped. Only `exhausted` means every reachable control
 * and linked screen was explored: `screen_limit` left linked screens unvisited
 * at {@link MAX_SCREENS}, and `skipped_commit_controls` left commit controls
 * unclicked on a non-disposable origin.
 */
export type StopReason = "max_actions" | "timeout" | "exhausted" | "screen_limit" | "skipped_commit_controls";

/** One distinct screen (URL) the crawler explored. */
export interface ScreenVisit {
  url: string;
  /** Path, query, and any hash route, e.g. `/checkout`. */
  path: string;
  title: string;
  /** Interactive elements found the first time the screen was scanned. */
  elements: number;
  forms: number;
  /** Breadcrumb step that reached the screen. */
  first_step: number;
}

interface CrawlSummary {
  target_url: string;
  breadcrumbs: Breadcrumb[];
  /** Distinct interactive elements discovered across all pages. */
  elements_explored: number;
  /** Clicks, fills, selections, and checks performed (navigation excluded). */
  actions_taken: number;
  pages_visited: string[];
  /** Every screen scanned, in the order first reached. */
  screens_visited: ScreenVisit[];
  /** Distinct commit controls left unclicked because commit actions were not allowed. */
  commit_controls_skipped: number;
  duration_ms: number;
}

type ReportBody =
  | (CrawlSummary & { status: "failure"; failure: CrawlFailure })
  | (CrawlSummary & { status: "clean"; stop_reason: StopReason })
  | (CrawlSummary & { status: "error"; error: string });

/** A crawl's outcome; `reproduction_trail` numbers the breadcrumbs as plain-language steps. */
export type CrawlReport = ReportBody & { reproduction_trail: string[] };

/** Progress events for live displays, emitted in order. */
export type CrawlEvent =
  | { type: "launch" }
  | { type: "navigate"; step: number; url: string }
  | {
      type: "discovered";
      url: string;
      title: string;
      /** Interactive elements on this screen. */
      count: number;
      buttons: number;
      links: number;
      forms: number;
      /** Distinct elements discovered so far across every screen. */
      total_elements: number;
      /** Screens scanned so far, this one included. */
      screens: number;
    }
  | {
      type: "action";
      step: number;
      action: Exclude<CrawlAction, "navigate">;
      /** Page the action ran on. */
      url: string;
      element: ElementKind;
      /** True for a button that submits a form. */
      submit: boolean;
      label: string;
      selector: string;
      value?: string;
      ok: boolean;
      failure?: CrawlSignal;
    }
  | { type: "report"; report: CrawlReport };

export interface CrawlOptions {
  url: string;
  /** Interactions before stopping clean (default {@link DEFAULT_MAX_ACTIONS}). */
  maxActions?: number;
  /** Overall budget (default {@link DEFAULT_CRAWL_TIMEOUT_MS}). */
  timeoutMs?: number;
  /** Receives progress events as they happen. */
  onEvent?: (event: CrawlEvent) => void;
  /** Browser to crawl in; a headless Chromium is launched and closed when omitted. */
  browser?: Browser;
  /**
   * Click commit buttons (Place order, Pay, Submit) even when the target is
   * not a disposable origin (see {@link isLocalHost}). Off by default: on a
   * real site those buttons can create orders, payments, or accounts.
   */
  allowCommitActions?: boolean;
}

/** Raised for invalid options before a browser starts. */
export class CrawlOptionsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CrawlOptionsError";
  }
}

/** What the page reports about one clickable element. */
export interface ClickableInfo {
  /** Position among `CLICKABLE_CSS` matches at discovery time. */
  index: number;
  tag: string;
  type: string;
  id: string;
  text: string;
  ariaLabel: string;
  value: string;
  /** Absolute URL for links and `data-href` cards, otherwise empty. */
  href: string;
  /** An anchor with a `download` attribute: it saves a file instead of opening a screen. */
  download: boolean;
  /** ARIA role attribute, e.g. `link` for a clickable product card. */
  role: string;
  disabled: boolean;
  visible: boolean;
  /** Inside header, nav, or footer: global chrome explored after content. */
  inChrome: boolean;
  submit: boolean;
  /** Inside a form whose method is POST. */
  postForm: boolean;
}

/** What the page reports about one form field. */
export interface FieldInfo {
  index: number;
  tag: string;
  type: string;
  id: string;
  name: string;
  label: string;
  placeholder: string;
  autocomplete: string;
  required: boolean;
  empty: boolean;
  checked: boolean;
  disabled: boolean;
  visible: boolean;
  readOnly: boolean;
  min: string;
  max: string;
  /** For selects, the first option with a non-empty value. */
  firstOption: string;
  /** True when the field's form (or, for a field outside any form, its page) declares no required fields; such fields are all filled. */
  formHasNoRequired: boolean;
  /** For radios, whether any radio in the same group is already checked. */
  groupChecked: boolean;
  /** Belongs to a form whose method is POST. */
  postForm: boolean;
}

const DESTRUCTIVE = /\b(log ?out|sign ?out|delete|remove|clear|cancel|reset|unsubscribe|deactivate|empty cart)\b/i;
const COMMIT =
  /\b(place (your )?order|order now|pay|purchase|complete|confirm|submit|buy now|book( now)?|reserve|donate|subscribe|transfer|publish|post|finish|sign up|register|create account|send|save)\b/i;
const CHECKOUT = /\b(check ?out|proceed|continue|next)\b/i;
const ADD = /\b(add to (cart|bag|basket)|add)\b/i;
const CART_PATH = /\/(checkout|cart|basket|bag)\b/i;

/**
 * True for hosts that cannot be a public production site: `localhost`,
 * loopback, `0.0.0.0/8`, RFC 1918 private IPv4, and IPv6 loopback or unique
 * local addresses (including IPv4-mapped forms). Hostnames are not resolved,
 * so a public name that points at a private address still counts as external.
 */
export function isLocalHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[(.*)\]$/, "$1");
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  const v4 = /^(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}$/.exec(host);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return a === 127 || a === 10 || a === 0 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
  }
  if (!host.includes(":")) return false;
  if (host === "::1") return true;
  if (/^f[cd][0-9a-f]{2}:/.test(host)) return true;
  const mapped = /^::ffff:(?:(\d{1,3}(?:\.\d{1,3}){3})|([0-9a-f]{1,4}):([0-9a-f]{1,4}))$/.exec(host);
  if (!mapped) return false;
  const [, dotted, highHex = "0", lowHex = "0"] = mapped;
  if (dotted) return isLocalHost(dotted);
  const [high, low] = [parseInt(highHex, 16), parseInt(lowHex, 16)];
  return isLocalHost(`${high >> 8}.${high & 255}.${low >> 8}.${low & 255}`);
}

/** Files, archives, media, and checksum lists: links to these start a download instead of opening a screen. */
const DOWNLOAD_PATH =
  /(\.(pdf|zip|tar|gz|tgz|bz2|xz|zst|7z|rar|dmg|pkg|exe|msi|deb|rpm|apk|iso|whl|jar|png|jpe?g|gif|svg|webp|avif|ico|mp3|mp4|mov|webm|wav|csv|tsv|xlsx?|docx?|pptx?|txt|log|sig|asc|sha(1|256|512)|md5)|\/((sha(1|256|512)|md5)sums|checksums)(\.\w+)?)$/i;

/** True when a URL path names a downloadable file rather than a page. */
export function isDownloadPath(pathname: string): boolean {
  return DOWNLOAD_PATH.test(pathname);
}

/** True for the error `page.goto` throws when the response is a download (e.g. `Content-Disposition: attachment`). */
export function isDownloadError(error: unknown): boolean {
  return error instanceof Error && /Download is starting/.test(error.message);
}

/** Strips the fragment so in-page anchors do not count as new pages; hash routes (`#/cart`, `#!/cart`) are kept. */
export function normalizeUrl(raw: string): string {
  const url = new URL(raw);
  if (!/^#!?\//.test(url.hash)) url.hash = "";
  return url.toString();
}

/** Same-origin pages are shown by path (`/checkout`); other URLs in full. */
export function displayPath(raw: string, origin: string): string {
  try {
    const url = new URL(raw);
    if (url.origin !== origin) return raw;
    return `${url.pathname}${url.search}${/^#!?\//.test(url.hash) ? url.hash : ""}`;
  } catch {
    return raw;
  }
}

/** Display name for an element: visible words, then accessible name, then value. */
export function labelOf(info: Pick<ClickableInfo, "text" | "ariaLabel" | "value" | "href">): string {
  // Symbol-only text such as "+" says less than the accessible name.
  const text = /[\p{L}\p{N}]/u.test(info.text) ? info.text : "";
  const label = text || info.ariaLabel || info.text || info.value || info.href;
  return label.length > MAX_LABEL_CHARS ? `${label.slice(0, MAX_LABEL_CHARS - 1)}…` : label;
}

/**
 * Ranks one clickable element; higher runs first and `null` means never click.
 *
 * The order walks a shopping funnel: commit buttons (Place order) beat
 * checkout steps, which beat unexplored content links (a product page), which
 * beat add-to-cart, which beats other buttons. Header, nav, and footer
 * elements are demoted so page content is explored before global chrome.
 * Commit controls (see {@link isCommitControl}), links included, are never
 * clicked unless `allowCommit` is true, which defaults to whether `origin` is
 * disposable (see {@link isLocalHost}).
 */
export function scoreClickable(
  info: ClickableInfo,
  context: { origin: string; visited: ReadonlySet<string>; allowCommit?: boolean },
): number | null {
  if (info.disabled || !info.visible) return null;
  const name = `${info.text} ${info.ariaLabel} ${info.value}`.replace(/\s+/g, " ").trim();
  if (DESTRUCTIVE.test(name)) return null;
  // Checked before the link branch so a link labeled "Pay" is held to the same bound as a button.
  const commit = COMMIT.test(name);
  if (isCommitControl(info) && !(context.allowCommit ?? isLocalHost(new URL(context.origin).hostname))) return null;

  let score: number;
  // Anchors and `data-href` cards navigate; judge them by their destination.
  if (info.tag === "a" || info.href) {
    let target: URL;
    try {
      target = new URL(info.href);
    } catch {
      return null;
    }
    if (target.origin !== context.origin) return null;
    if (info.download || isDownloadPath(target.pathname)) return null;
    if (context.visited.has(normalizeUrl(target.toString()))) return null;
    score = CHECKOUT.test(name) || CART_PATH.test(target.pathname) ? 40 : 30;
  } else if (commit) {
    score = 50;
  } else if (CHECKOUT.test(name)) {
    score = 40;
  } else if (ADD.test(name)) {
    score = 25;
  } else if (info.role === "link") {
    // A script-driven product card: explore it like a content link.
    score = 30;
  } else {
    score = info.submit ? 20 : 10;
  }
  return info.inChrome ? score - 35 : score;
}

/**
 * Whether clicking the element can commit something on the server: a submit
 * control (`type=submit`, or a button that submits its form), a button in a
 * POST form, or a control named like a commit (Place order, Pay, Book, ...).
 */
export function isCommitControl(info: Pick<ClickableInfo, "tag" | "type" | "role" | "text" | "ariaLabel" | "value" | "submit" | "postForm">): boolean {
  if (info.submit || info.type === "submit") return true;
  if (info.postForm && (info.tag === "button" || info.tag === "input" || info.role === "button")) return true;
  return COMMIT.test(`${info.text} ${info.ariaLabel} ${info.value}`.replace(/\s+/g, " ").trim());
}

/** Values for standard `autocomplete` tokens, which name a field exactly. */
const AUTOCOMPLETE_VALUES: Readonly<Record<string, string>> = {
  name: "Alex Tester",
  "given-name": "Alex",
  "additional-name": "J",
  "family-name": "Tester",
  nickname: "alex",
  username: "faultline-tester",
  email: "test@example.com",
  tel: "555-010-0199",
  "tel-national": "555-010-0199",
  organization: "FaultLine QA",
  "street-address": "123 Main St",
  "address-line1": "123 Main St",
  "address-line2": "Apt 4",
  "address-level2": "Springfield",
  "address-level1": "IL",
  country: "US",
  "country-name": "United States",
  "postal-code": "62704",
  "cc-name": "Alex Tester",
  "cc-number": "4242 4242 4242 4242",
  "cc-exp": "12/30",
  "cc-exp-month": "12",
  "cc-exp-year": "2030",
  "cc-csc": "123",
  bday: "1990-01-15",
  url: "https://example.com",
};

/** Naming hints, tried in order against the field's words; earlier entries win. */
const NAMED_VALUES: ReadonlyArray<readonly [RegExp, string]> = [
  [/\be ?mail\b/, "test@example.com"],
  [/\b(phone|tel|telephone|mobile|cell)\b/, "555-010-0199"],
  [/\b(zip|postal|post ?code|zip ?code)\b/, "62704"],
  [/\b(city|town|locality)\b/, "Springfield"],
  [/\b(state|province|region|county)\b/, "IL"],
  [/\bcountry\b/, "United States"],
  [/\b(card ?number|cc ?number|card ?no)\b/, "4242 4242 4242 4242"],
  [/\b(cvc|cvv|csc|security ?code)\b/, "123"],
  [/\b(expiry|expiration|expires|exp ?date|cc ?exp)\b/, "12/30"],
  [/\b(address|street|addr|line ?1)\b/, "123 Main St"],
  [/\b(first ?name|given ?name|fname)\b/, "Alex"],
  [/\b(last ?name|family ?name|surname|lname)\b/, "Tester"],
  [/\b(user ?name|login|handle)\b/, "faultline-tester"],
  [/\b(company|organi[sz]ation|business)\b/, "FaultLine QA"],
  [/\bname\b/, "Alex Tester"],
  [/\b(coupon|promo|discount|voucher|gift ?code)\b/, "SAVE10"],
  [/\b(search|query|keyword)\b/, "test"],
  [/\b(qty|quantity|amount|count|units)\b/, "1"],
  [/\bage\b/, "30"],
  [/\b(message|comment|comments|note|notes|feedback|description)\b/, "Testing from FaultLine."],
];

/** Splits names such as `shipping_postalCode` into lower-case words: `shipping postal code`. */
function hintWords(...hints: string[]): string {
  return hints
    .join(" ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[^A-Za-z0-9]+/g, " ")
    .toLowerCase()
    .trim();
}

function clampNumber(value: number, field: Pick<FieldInfo, "min" | "max">): string {
  const min = Number.parseFloat(field.min);
  const max = Number.parseFloat(field.max);
  let result = value;
  if (Number.isFinite(max) && result > max) result = max;
  if (Number.isFinite(min) && result < min) result = min;
  return String(result);
}

/**
 * Realistic sample value for a text-like field, chosen from its type and
 * naming hints. Numbers stay within the field's `min`/`max`.
 */
export function sampleValueFor(field: Pick<FieldInfo, "tag" | "type" | "id" | "name" | "label" | "placeholder" | "autocomplete" | "min" | "max">): string {
  const type = field.type.toLowerCase();
  switch (type) {
    case "email":
      return "test@example.com";
    case "password":
      return "FaultLine-test-123!";
    case "tel":
      return "555-010-0199";
    case "url":
      return "https://example.com";
    case "date":
      return "2026-01-15";
    case "datetime-local":
      return "2026-01-15T10:30";
    case "time":
      return "10:30";
    case "month":
      return "2026-01";
    case "week":
      return "2026-W03";
    case "color":
      return "#3366ff";
  }
  const hints = hintWords(field.name, field.id, field.label, field.placeholder);
  if (type === "number" || type === "range") {
    // A realistic order quantity, otherwise a mid-sized number; both within min/max.
    return clampNumber(/\b(qty|quantity|count|units|items)\b/.test(hints) ? 2 : 10, field);
  }
  // `autocomplete` may hold a section and type prefix: "shipping postal-code".
  const token = field.autocomplete.toLowerCase().trim().split(/\s+/).at(-1) ?? "";
  const exact = AUTOCOMPLETE_VALUES[token];
  if (exact) return exact;
  const words = `${hintWords(field.autocomplete)} ${hints}`;
  for (const [pattern, value] of NAMED_VALUES) {
    if (pattern.test(words)) return value;
  }
  return field.tag === "textarea" ? "Testing from FaultLine." : "test";
}

const UNFILLABLE_TYPES = new Set(["hidden", "submit", "button", "reset", "image", "file"]);

/**
 * Whether the crawler should fill this field before clicking on. Fields of a
 * POST form stay empty unless `allowCommit` is true (see {@link scoreClickable}).
 */
export function shouldFill(field: FieldInfo, allowCommit = true): boolean {
  if (field.disabled || field.readOnly || !field.visible) return false;
  if (field.postForm && !allowCommit) return false;
  if (UNFILLABLE_TYPES.has(field.type)) return false;
  if (field.type === "checkbox") return field.required && !field.checked;
  // One choice per required radio group: the first radio of an unanswered group.
  if (field.type === "radio") return field.required && !field.groupChecked;
  if (!field.empty) return false;
  if (field.tag === "select") return field.required && field.firstOption !== "";
  // Optional fields stay empty: an optional coupon or promo box would otherwise
  // block or change the submission the form is built around.
  return field.required || field.formHasNoRequired;
}

function signalPriority(signal: CrawlSignal): number {
  if (signal.kind === "http_error") return (signal.status ?? 0) >= 500 ? 0 : 2;
  if (signal.kind === "page_error") return 1;
  if (signal.kind === "request_failed") return 3;
  return 4;
}

/** Picks the signal that best explains an action's failure. */
export function primarySignal(signals: readonly CrawlSignal[]): CrawlSignal | undefined {
  return [...signals].sort((a, b) => signalPriority(a) - signalPriority(b))[0];
}

/** Whether a response is a defect signal. */
export function isFailureResponse(status: number, resourceType: string): boolean {
  if (status >= 500) return true;
  return CLIENT_ERROR_STATUSES.has(status) && APPLICATION_RESOURCES.has(resourceType);
}

/** Short description of a signal, e.g. `HTTP 500 on POST /api/checkout`. */
export function describeSignal(signal: CrawlSignal): string {
  switch (signal.kind) {
    case "http_error":
      return `HTTP ${signal.status} on ${signal.method} ${signal.endpoint}`;
    case "request_failed":
      return `${signal.method} ${signal.endpoint} failed: ${signal.message}`;
    case "page_error":
      return `Uncaught ${signal.message}`;
    case "console_error":
      return `console.error: ${signal.message}`;
  }
}

const ACTION_VERBS: Readonly<Record<Exclude<CrawlAction, "navigate">, string>> = {
  click: "Clicking",
  fill: "Filling",
  select: "Selecting in",
  check: "Checking",
};

/** One human-readable progress line for an event, or null for the final report. */
export function formatCrawlEvent(event: CrawlEvent): string | null {
  switch (event.type) {
    case "launch":
      return "[Playwright] Launching Chromium...";
    case "navigate":
      return `[Playwright] Navigating to ${event.url}...`;
    case "discovered":
      return `[Playwright] Discovered ${event.total_elements} interactive elements across ${event.screens} ${event.screens === 1 ? "screen" : "screens"}.`;
    case "action": {
      const value = event.action === "fill" || event.action === "select" ? ` with ${JSON.stringify(event.value)}` : "";
      const result = event.ok || !event.failure ? "OK" : `💥 ${describeSignal(event.failure)}`;
      return `[Playwright] Step ${event.step}: ${ACTION_VERBS[event.action]} ${event.label}${value} -> ${result}`;
    }
    case "report":
      return null;
  }
}

/**
 * The breadcrumbs as numbered plain-language steps a person can follow, with
 * each element's selector in brackets and the failing step naming the defect.
 */
export function formatReproductionTrail(breadcrumbs: readonly Breadcrumb[], origin: string, failure?: CrawlFailure): string[] {
  return breadcrumbs.map((crumb) => {
    const page = displayPath(crumb.url, origin);
    const label = JSON.stringify(crumb.label ?? "");
    const value = JSON.stringify(crumb.value ?? "");
    let line: string;
    switch (crumb.action) {
      case "navigate":
        line = `Open ${crumb.url}`;
        break;
      case "click":
        line = `Click ${crumb.element ?? "element"} ${label} on ${page}`;
        break;
      case "fill":
        line = `Fill ${label} with ${value} on ${page}`;
        break;
      case "select":
        line = `Select ${value} in ${label} on ${page}`;
        break;
      case "check":
        line = `Check ${label} on ${page}`;
        break;
    }
    const target = crumb.selector ? ` [${crumb.selector}]` : "";
    const outcome = failure?.step === crumb.step ? ` -> ${describeSignal(failure)}` : "";
    return `${crumb.step}. ${line}${target}${outcome}`;
  });
}

function endpointOf(raw: string): string {
  try {
    const url = new URL(raw);
    return `${url.pathname}${url.search}`;
  } catch {
    return raw;
  }
}

function clip(text: string, maxChars = 500): string {
  return text.length > maxChars ? `${text.slice(0, maxChars - 1)}…` : text;
}

/** Collects failure signals and tracks in-flight requests for one page. */
class PageMonitor {
  readonly signals: CrawlSignal[] = [];
  readonly consoleErrors: string[] = [];
  private readonly inflight = new Set<Request>();
  private readonly bodies: Promise<void>[] = [];
  private lastActivity = performance.now();

  constructor(page: Page) {
    page.on("request", (request) => {
      this.inflight.add(request);
      this.lastActivity = performance.now();
    });
    page.on("requestfinished", (request) => this.finish(request));
    page.on("requestfailed", (request) => {
      this.finish(request);
      const errorText = request.failure()?.errorText ?? "request failed";
      // Aborts are routine: navigation cancels pending fetches.
      if (errorText.includes("ERR_ABORTED") || !["fetch", "xhr"].includes(request.resourceType())) return;
      this.signals.push({
        kind: "request_failed",
        message: errorText,
        method: request.method(),
        url: request.url(),
        endpoint: endpointOf(request.url()),
      });
    });
    page.on("response", (response) => this.onResponse(response));
    page.on("pageerror", (error) => {
      this.signals.push({
        kind: "page_error",
        message: clip(`${error.name}: ${error.message}`),
        ...(error.stack ? { stack: truncateUtf8(error.stack, MAX_BODY_BYTES).text } : {}),
      });
    });
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = clip(message.text());
      this.consoleErrors.push(text);
      // Chromium logs every failed resource load; the response handler judges
      // those itself, so a 404 favicon does not count as a defect.
      if (text.startsWith("Failed to load resource")) return;
      const location = message.location();
      this.signals.push({
        kind: "console_error",
        message: text,
        ...(location.url ? { url: location.url, stack: `at ${location.url}:${location.lineNumber + 1}:${location.columnNumber + 1}` } : {}),
      });
    });
  }

  private finish(request: Request): void {
    this.inflight.delete(request);
    this.lastActivity = performance.now();
  }

  private onResponse(response: Response): void {
    const request = response.request();
    if (!isFailureResponse(response.status(), request.resourceType())) return;
    const signal: CrawlSignal = {
      kind: "http_error",
      message: `${response.status()} ${response.statusText()}`.trim(),
      method: request.method(),
      url: response.url(),
      endpoint: endpointOf(response.url()),
      status: response.status(),
    };
    this.signals.push(signal);
    this.bodies.push(
      response.text().then(
        (body) => {
          signal.response_body = truncateUtf8(body, MAX_BODY_BYTES).text;
        },
        () => undefined,
      ),
    );
  }

  /** Waits until no request has been in flight for {@link QUIET_MS} since the call, within `capMs`. */
  async settle(page: Page, capMs: number): Promise<void> {
    const endsAt = performance.now() + capMs;
    // Quiet time counts from the action, so deferred errors in a handler that
    // makes no request still land on the step that caused them.
    this.lastActivity = performance.now();
    while (performance.now() < endsAt) {
      if (this.inflight.size === 0 && performance.now() - this.lastActivity >= QUIET_MS) break;
      await page.waitForTimeout(50);
    }
    await Promise.all(this.bodies.splice(0));
  }
}

interface Discovery {
  title: string;
  clickables: ClickableInfo[];
  fields: FieldInfo[];
  forms: number;
}

async function discover(page: Page): Promise<Discovery> {
  const clickables = await page.locator(CLICKABLE_CSS).evaluateAll((elements) =>
    elements.map((element, index) => {
      const el = element as HTMLElement;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      const tag = el.tagName.toLowerCase();
      const input = el as HTMLInputElement;
      const button = el as HTMLButtonElement;
      let href = tag === "a" ? (el as HTMLAnchorElement).href : "";
      const dataHref = el.getAttribute("data-href");
      if (!href && dataHref) {
        try {
          href = new URL(dataHref, location.href).toString();
        } catch {
          href = "";
        }
      }
      return {
        index,
        tag,
        type: (el.getAttribute("type") ?? "").toLowerCase(),
        id: el.id,
        text: (el.innerText ?? "").replace(/\s+/g, " ").trim(),
        ariaLabel: (el.getAttribute("aria-label") ?? "").trim(),
        value: tag === "input" ? input.value : "",
        href,
        download: tag === "a" && el.hasAttribute("download"),
        role: (el.getAttribute("role") ?? "").toLowerCase(),
        disabled: button.disabled === true || el.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none",
        inChrome: el.closest("header, nav, footer") !== null,
        submit:
          (tag === "button" && (button.type === "submit") && button.form !== null) ||
          (tag === "input" && input.type === "submit"),
        postForm: (el.closest("form")?.method ?? "").toLowerCase() === "post",
      };
    }),
  );
  const fields = await page.locator(FIELD_CSS).evaluateAll((elements) =>
    elements.map((element, index) => {
      const el = element as HTMLInputElement & HTMLSelectElement & HTMLTextAreaElement;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      const tag = el.tagName.toLowerCase();
      const labels = el.labels ? Array.from(el.labels).map((label) => label.innerText) : [];
      const form = el.form;
      const firstOption =
        tag === "select" ? (Array.from(el.options).find((option) => option.value !== "")?.value ?? "") : "";
      const radio = tag === "input" && (el.getAttribute("type") ?? "").toLowerCase() === "radio";
      const group =
        radio && el.name
          ? Array.from((form ?? document).querySelectorAll<HTMLInputElement>('input[type="radio"]')).filter((other) => other.name === el.name)
          : [el];
      return {
        index,
        tag,
        type: tag === "input" ? el.type.toLowerCase() : tag,
        id: el.id,
        name: el.name ?? "",
        label: (labels.join(" ") || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim(),
        placeholder: el.getAttribute("placeholder") ?? "",
        autocomplete: el.getAttribute("autocomplete") ?? "",
        // A required radio makes its whole group required.
        required: radio ? group.some((other) => other.required) : el.required === true,
        empty: (el.value ?? "") === "",
        checked: tag === "input" ? el.checked === true : false,
        disabled: el.disabled === true || el.closest("fieldset:disabled") !== null,
        visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none",
        readOnly: el.readOnly === true,
        min: el.getAttribute("min") ?? "",
        max: el.getAttribute("max") ?? "",
        firstOption,
        formHasNoRequired: (form ?? document).querySelector("[required]") === null,
        groupChecked: radio ? group.some((other) => other.checked) : false,
        postForm: (form?.method ?? "").toLowerCase() === "post",
      };
    }),
  );
  return { title: await page.title(), clickables, fields, forms: await page.locator("form").count() };
}

/**
 * A replayable selector for the element at `index` among `baseCss` matches:
 * `#id` when unique, else `tag:has-text("…")` or an attribute match, with a
 * `>> nth=` suffix when the readable form matches several elements.
 */
async function readableSelector(page: Page, baseCss: string, index: number, candidates: string[]): Promise<string> {
  const target = await page.locator(baseCss).nth(index).elementHandle({ timeout: ACTION_TIMEOUT_MS });
  if (!target) throw new Error("element detached");
  try {
    for (const selector of candidates) {
      const matches = await page.locator(selector).elementHandles();
      try {
        const position = await page.evaluate(
          ([element, ...others]) => others.indexOf(element),
          [target, ...matches] as const,
        );
        if (position < 0) continue;
        return matches.length === 1 ? selector : `${selector} >> nth=${position}`;
      } finally {
        await Promise.all(matches.map((match) => match.dispose()));
      }
    }
    return `${baseCss} >> nth=${index}`;
  } finally {
    await target.dispose();
  }
}

const CSS_IDENT = /^[A-Za-z][\w-]*$/;

function clickableSelectors(info: ClickableInfo): string[] {
  const selectors: string[] = [];
  if (info.id && CSS_IDENT.test(info.id)) selectors.push(`#${info.id}`);
  if (info.tag === "input" && info.value) selectors.push(`input[type=${JSON.stringify(info.type)}][value=${JSON.stringify(info.value)}]`);
  if (info.text && info.text.length <= MAX_LABEL_CHARS) selectors.push(`${info.tag}:has-text(${JSON.stringify(info.text)})`);
  if (info.ariaLabel) selectors.push(`${info.tag}[aria-label=${JSON.stringify(info.ariaLabel)}]`);
  if (info.tag === "a" && info.href) selectors.push(`a[href=${JSON.stringify(new URL(info.href).pathname)}]`);
  if (info.tag !== "a" && info.href && info.text) selectors.push(`${info.tag}[data-href]:has-text(${JSON.stringify(info.text.slice(0, MAX_LABEL_CHARS))})`);
  return selectors;
}

function fieldSelectors(field: FieldInfo): string[] {
  const selectors: string[] = [];
  if (field.id && CSS_IDENT.test(field.id)) selectors.push(`#${field.id}`);
  if (field.name) selectors.push(`${field.tag}[name=${JSON.stringify(field.name)}]`);
  if (field.label) selectors.push(`${field.tag}[aria-label=${JSON.stringify(field.label)}]`);
  return selectors;
}

function fieldLabel(field: FieldInfo): string {
  return field.label || field.name || field.placeholder || field.id || field.type;
}

class CrawlTimeout extends Error {}

function firstLine(error: unknown): string {
  return (error instanceof Error ? error.message : String(error)).split("\n")[0] ?? "";
}

/**
 * Crawls `options.url` and returns what it found. Never throws for page
 * behavior: launch and navigation problems come back as `status: "error"`.
 */
export async function runAutonomousCrawler(options: CrawlOptions): Promise<CrawlReport> {
  let start: URL;
  try {
    start = new URL(options.url);
  } catch {
    throw new CrawlOptionsError(`Not an absolute URL: ${JSON.stringify(options.url)}.`);
  }
  if (start.protocol !== "http:" && start.protocol !== "https:") {
    throw new CrawlOptionsError("Only http:// and https:// URLs can be crawled.");
  }
  const maxActions = options.maxActions ?? DEFAULT_MAX_ACTIONS;
  if (!Number.isInteger(maxActions) || maxActions < 1 || maxActions > MAX_CRAWL_ACTIONS) {
    throw new CrawlOptionsError(`maxActions must be a whole number from 1 to ${MAX_CRAWL_ACTIONS}.`);
  }
  const timeoutMs = options.timeoutMs ?? DEFAULT_CRAWL_TIMEOUT_MS;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > MAX_CRAWL_TIMEOUT_MS) {
    throw new CrawlOptionsError(`timeoutMs must be a whole number from 1000 to ${MAX_CRAWL_TIMEOUT_MS}.`);
  }

  const allowCommit = options.allowCommitActions === true || isLocalHost(start.hostname);
  const emit = options.onEvent ?? (() => undefined);
  const startedAt = performance.now();
  const endsAt = startedAt + timeoutMs;
  const remaining = () => endsAt - performance.now();
  const breadcrumbs: Breadcrumb[] = [];
  const visited = new Set<string>();
  const tried = new Set<string>();
  const seenElements = new Set<string>();
  const screens = new Map<string, ScreenVisit>();
  /** Same-origin screens linked from explored ones, by best link score. */
  const frontier = new Map<string, number>();
  /** Frontier URLs that started a download when opened. */
  const downloads = new Set<string>();
  /** Commit controls the guard kept the crawler from clicking, by identity. */
  const skippedCommits = new Set<string>();
  let actionsTaken = 0;

  const summary = (): CrawlSummary => ({
    target_url: start.toString(),
    breadcrumbs,
    elements_explored: seenElements.size,
    actions_taken: actionsTaken,
    pages_visited: [...visited],
    screens_visited: [...screens.values()],
    commit_controls_skipped: skippedCommits.size,
    duration_ms: Math.round(performance.now() - startedAt),
  });
  const finish = (body: ReportBody): CrawlReport => {
    const failure = body.status === "failure" ? body.failure : undefined;
    const report: CrawlReport = { ...body, reproduction_trail: formatReproductionTrail(body.breadcrumbs, start.origin, failure) };
    emit({ type: "report", report });
    return report;
  };

  emit({ type: "launch" });
  let browser = options.browser;
  const ownsBrowser = browser === undefined;
  try {
    browser ??= await chromium.launch({ headless: true });
  } catch (error) {
    return finish({ status: "error", ...summary(), error: `Chromium could not launch: ${firstLine(error)}` });
  }

  let context: BrowserContext | undefined;
  try {
    context = await browser.newContext();
    const page = await context.newPage();
    const monitor = new PageMonitor(page);

    const guard = (): void => {
      if (remaining() <= 0) throw new CrawlTimeout();
    };

    /** Records the signals raised since `before`; returns the failure if any. */
    const failureSince = (before: number, step: number): CrawlFailure | undefined => {
      const raised = monitor.signals.slice(before);
      const primary = primarySignal(raised);
      if (!primary) return undefined;
      return {
        ...primary,
        step,
        console_errors: [...monitor.consoleErrors],
        related: raised.filter((signal) => signal !== primary),
      };
    };

    const navigate = async (url: string): Promise<CrawlFailure | undefined> => {
      guard();
      const step = breadcrumbs.length + 1;
      breadcrumbs.push({ step, action: "navigate", url });
      emit({ type: "navigate", step, url });
      const before = monitor.signals.length;
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: Math.max(1, Math.min(15_000, remaining())) });
      await monitor.settle(page, Math.min(SETTLE_CAP_MS, Math.max(0, remaining())));
      visited.add(normalizeUrl(page.url()));
      return failureSince(before, step);
    };

    const halt = (failure: CrawlFailure) => finish({ status: "failure", ...summary(), failure });

    try {
      let failure: CrawlFailure | undefined;
      try {
        failure = await navigate(start.toString());
      } catch (error) {
        // A slow first page that exhausts the crawl budget is a clean timeout,
        // not an infrastructure error, exactly as the outer catch treats it.
        if (error instanceof CrawlTimeout || remaining() <= 0) throw new CrawlTimeout();
        return finish({ status: "error", ...summary(), error: `Could not load ${start.toString()}: ${firstLine(error)}` });
      }
      if (failure) return halt(failure);

      let announced = "";
      let returnedHome = false;
      let discoveryFailures = 0;
      while (actionsTaken < maxActions) {
        guard();
        if (new URL(page.url()).origin !== start.origin) {
          // A control left the site; resume from the start page.
          failure = await navigate(start.toString());
          if (failure) return halt(failure);
        }
        const pageUrl = normalizeUrl(page.url());
        visited.add(pageUrl);
        let discovery: Discovery;
        try {
          discovery = await discover(page);
          discoveryFailures = 0;
        } catch (error) {
          // A navigation can replace the document mid-scan; rescan once it settles.
          if (++discoveryFailures > 3) throw error;
          await monitor.settle(page, Math.min(SETTLE_CAP_MS, Math.max(0, remaining())));
          continue;
        }
        const { title, clickables, fields, forms } = discovery;
        const identity = (info: ClickableInfo) => `${pageUrl}|click|${info.tag}|${info.text}|${info.ariaLabel}|${info.href}`;
        for (const info of clickables) seenElements.add(identity(info));
        for (const field of fields) seenElements.add(`${pageUrl}|field|${field.tag}|${fieldLabel(field)}`);
        for (const info of clickables) {
          if (!info.href) continue;
          const score = scoreClickable(info, { origin: start.origin, visited, allowCommit });
          if (score === null) continue;
          const target = normalizeUrl(info.href);
          if (downloads.has(target)) continue;
          frontier.set(target, Math.max(score, frontier.get(target) ?? -Infinity));
        }
        if (announced !== pageUrl) {
          announced = pageUrl;
          const links = clickables.filter((info) => info.tag === "a").length;
          const count = clickables.length + fields.length;
          if (!screens.has(pageUrl)) {
            screens.set(pageUrl, { url: pageUrl, path: displayPath(pageUrl, start.origin), title, elements: count, forms, first_step: breadcrumbs.length });
          }
          emit({
            type: "discovered",
            url: pageUrl,
            title,
            count,
            buttons: clickables.length - links,
            links,
            forms,
            total_elements: seenElements.size,
            screens: screens.size,
          });
        }

        const field = fields.find((candidate) => shouldFill(candidate, allowCommit) && !tried.has(`${pageUrl}|field|${candidate.index}|${fieldLabel(candidate)}`));
        if (field) {
          const key = `${pageUrl}|field|${field.index}|${fieldLabel(field)}`;
          tried.add(key);
          let selector: string;
          try {
            selector = await readableSelector(page, FIELD_CSS, field.index, fieldSelectors(field));
          } catch {
            continue;
          }
          const action: "fill" | "select" | "check" = field.type === "checkbox" || field.type === "radio" ? "check" : field.tag === "select" ? "select" : "fill";
          const value = action === "check" ? "checked" : action === "select" ? field.firstOption : sampleValueFor(field);
          const before = monitor.signals.length;
          try {
            const locator = page.locator(selector);
            if (action === "check") await locator.check({ timeout: ACTION_TIMEOUT_MS });
            else if (action === "select") await locator.selectOption(value, { timeout: ACTION_TIMEOUT_MS });
            else await locator.fill(value, { timeout: ACTION_TIMEOUT_MS });
          } catch {
            continue;
          }
          actionsTaken += 1;
          const step = breadcrumbs.length + 1;
          breadcrumbs.push({ step, action, url: pageUrl, selector, label: fieldLabel(field), value, element: "field" });
          await monitor.settle(page, Math.min(SETTLE_CAP_MS, Math.max(0, remaining())));
          failure = failureSince(before, step);
          emit({ type: "action", step, action, url: pageUrl, element: "field", submit: false, label: fieldLabel(field), selector, value, ok: !failure, ...(failure ? { failure } : {}) });
          if (failure) return halt(failure);
          continue;
        }

        const scored = clickables.map((info) => ({ info, key: identity(info), score: scoreClickable(info, { origin: start.origin, visited, allowCommit }) }));
        for (const { info, key, score } of scored) {
          // Explorable but for the commit guard: exploration cannot be called complete.
          if (score === null && !allowCommit && scoreClickable(info, { origin: start.origin, visited, allowCommit: true }) !== null) skippedCommits.add(key);
        }
        const ranked = scored
          .filter((entry): entry is { info: ClickableInfo; key: string; score: number } => entry.score !== null && !tried.has(entry.key))
          .sort((a, b) => b.score - a.score || a.info.index - b.info.index);
        const next = ranked[0];
        if (!next) {
          // Nothing left on this screen: jump to the best unvisited screen linked so far.
          const jump = [...frontier.entries()]
            .filter(([url]) => !visited.has(url))
            .sort((a, b) => b[1] - a[1])[0];
          if (jump && screens.size < MAX_SCREENS) {
            frontier.delete(jump[0]);
            try {
              failure = await navigate(jump[0]);
            } catch (error) {
              if (!isDownloadError(error)) throw error;
              // The link served a file the URL did not reveal; drop its step and keep exploring.
              breadcrumbs.pop();
              downloads.add(jump[0]);
              continue;
            }
            if (failure) return halt(failure);
            continue;
          }
          if (returnedHome || pageUrl === normalizeUrl(start.toString())) {
            // A remaining jump means the screen limit, not exploration, ended the crawl.
            const stop_reason: StopReason = jump ? "screen_limit" : skippedCommits.size > 0 ? "skipped_commit_controls" : "exhausted";
            return finish({ status: "clean", ...summary(), stop_reason });
          }
          // Nothing left here; look for unexplored controls from the start page.
          returnedHome = true;
          failure = await navigate(start.toString());
          if (failure) return halt(failure);
          continue;
        }
        returnedHome = false;
        tried.add(next.key);
        let selector: string;
        try {
          selector = await readableSelector(page, CLICKABLE_CSS, next.info.index, clickableSelectors(next.info));
        } catch {
          continue;
        }
        const label = labelOf(next.info);
        const element: ElementKind = next.info.tag === "a" || next.info.href || next.info.role === "link" ? "link" : "button";
        const before = monitor.signals.length;
        try {
          await page.locator(selector).click({ timeout: Math.max(1, Math.min(ACTION_TIMEOUT_MS, remaining())) });
        } catch {
          continue;
        }
        actionsTaken += 1;
        const step = breadcrumbs.length + 1;
        breadcrumbs.push({ step, action: "click", url: pageUrl, selector, label, element });
        await page.waitForLoadState("domcontentloaded", { timeout: Math.max(1, Math.min(SETTLE_CAP_MS, remaining())) }).catch(() => undefined);
        await monitor.settle(page, Math.min(SETTLE_CAP_MS, Math.max(0, remaining())));
        failure = failureSince(before, step);
        emit({ type: "action", step, action: "click", url: pageUrl, element, submit: next.info.submit, label, selector, ok: !failure, ...(failure ? { failure } : {}) });
        if (failure) return halt(failure);
      }
      return finish({ status: "clean", ...summary(), stop_reason: "max_actions" });
    } catch (error) {
      if (error instanceof CrawlTimeout || remaining() <= 0) {
        return finish({ status: "clean", ...summary(), stop_reason: "timeout" });
      }
      return finish({ status: "error", ...summary(), error: `Crawl stopped unexpectedly: ${firstLine(error)}` });
    }
  } finally {
    await context?.close().catch(() => undefined);
    if (ownsBrowser) await browser.close().catch(() => undefined);
  }
}
