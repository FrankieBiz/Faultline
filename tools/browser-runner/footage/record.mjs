#!/usr/bin/env node
// Records FaultLine demo footage as separate 1920x1080 clips with Playwright's recordVideo.
//
// It drives services that are already running and never starts or stops them:
//   - the demo stack (./scripts/start-demo.sh) for clips 01 and 04,
//   - a static server of docs/ for clips 02, 03, and 05,
//   - a live repair service (./scripts/start-live-demo.sh) for clip 05, only with --live.
// Each clip is saved as <out>/<name>.webm; <out>/clips.json records the moments the assembler
// trims to and the provenance it captions. See docs/VIDEO_STORYBOARD.md ("Footage").

import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";
import { captureGate, showGateOutput } from "./gate-footage.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const VIDEO = { width: 1920, height: 1080 };
const FPS = 30;
const HEADER_OFFSET = 32; // CSS px. Both redesigned pages use a normal-flow header.
const RECORDED_JOB = "3573b32b-09bd-4f14-897d-cf6dccf9b118";
const GATE_PATCHES = ["zero_all_discounts", "null_coupon_only", "early_return_unsaved"];

const HELP = `Usage: node tools/browser-runner/footage/record.mjs [options]

Records FaultLine demo clips (1920x1080, ${FPS} fps WebM) into data/footage/<timestamp>/.

Options:
  --stack-ports S,I[,A,C]  Demo stack ports: storefront, Inspector, and optionally the
                           API and controller (default 3000,4000,8000,9000).
  --docs-url URL           Static server of docs/ (default http://127.0.0.1:8770/).
  --live URL               Live repair service base URL; enables clip 05.
  --live-defect ID         Bug to plant in clip 05 (default seeded_missing_coupon).
  --only LIST              Comma-separated clips, e.g. 01,03 or 02-recorded-meta-repair.
  --out DIR                Output directory (default data/footage/<timestamp>).
  --zoom N                 CSS zoom applied to every page so text reads larger in the
                           1080p frame; 1 records the page as a 1920x1080 browser shows
                           it (default 1.2).
  --require-deterministic  Refuse an Inspector repair unless readiness names the
                           deterministic fallback. Prevents accidental paid model calls.
  --judge-cut              Shorter reading holds and two corpus examples for a
                           concise judge video. Repair and replay timing stay real.
  --repair-job-id ID       Verified Inspector job for clip 06. Defaults to the job
                           recorded in clip 04, or the latest verified server job.
  -h, --help               Show this help.

Clips:
  01-storefront-crash      Storefront: two Trail Mugs, empty coupon, checkout crash banner.
  02-recorded-meta-repair  Judge page: the recorded Meta repair (job 3573b32b) at real timing.
  03-gates                 Judge page: three candidate patches in the gate explorer.
  04-inspector-run         Inspector: "Run sandbox repair" to the result, then steps, diff, evidence.
  05-live-break-it         Judge page with ?live=URL: plant a bug and wait for the live result.
  07-gate-blocked          Execute the real CLI against the seeded store; require exit 1.
  06-apply-regate-revert   Apply the latest verified Inspector job, confirm HTTP 201,
                           execute a clean CLI gate, then restore the seeded defect.
  08-limits               Judge page: the stated scope and limits, held statically.
`;

const CLIPS = [
  { name: "01-storefront-crash", needs: ["storefront"], run: recordStorefront },
  { name: "02-recorded-meta-repair", needs: ["docs"], run: recordReplay },
  { name: "03-gates", needs: ["docs"], run: recordGates },
  // Capture the broken gate before the sandbox repair and apply, regardless of --only ordering.
  { name: "07-gate-blocked", needs: ["storefront", "inspector"], run: recordBlockedGate },
  { name: "04-inspector-run", needs: ["inspector", "api", "controller"], run: recordInspector },
  { name: "06-apply-regate-revert", needs: ["storefront", "inspector", "api", "controller"], run: recordApplyGateRevert },
  { name: "08-limits", needs: ["docs"], run: recordLimits },
  { name: "05-live-break-it", needs: ["docs", "live"], run: recordLive },
];

// A visible pointer for the recording. Playwright videos have no cursor, so clicks would
// otherwise look like unexplained jumps. The dot is created on the first mouse move (after
// the page has hydrated) and only follows real Playwright mouse events.
const CURSOR_SCRIPT = `(() => {
  if (window !== window.top) return;
  let dot = null;
  const size = (px, fill) => {
    Object.assign(dot.style, { width: px + "px", height: px + "px", margin: -px / 2 + "px 0 0 " + -px / 2 + "px", background: fill });
  };
  const ensure = () => {
    if (dot && dot.isConnected) return dot;
    dot = document.createElement("div");
    dot.setAttribute("aria-hidden", "true");
    Object.assign(dot.style, {
      position: "fixed", left: "0", top: "0", borderRadius: "50%", pointerEvents: "none",
      zIndex: "2147483647", border: "2px solid rgba(15, 17, 20, 0.9)",
      boxShadow: "0 0 0 2px rgba(255, 255, 255, 0.55), 0 2px 10px rgba(0, 0, 0, 0.35)",
      transition: "width 120ms ease-out, height 120ms ease-out, margin 120ms ease-out, background 120ms ease-out"
    });
    size(22, "rgba(255, 255, 255, 0.82)");
    // Undo the page zoom so the dot sits exactly at the event's client coordinates.
    dot.style.zoom = String(1 / (parseFloat(document.documentElement.style.zoom) || 1));
    document.documentElement.appendChild(dot);
    return dot;
  };
  addEventListener("mousemove", (event) => { ensure().style.transform = "translate(" + event.clientX + "px, " + event.clientY + "px)"; }, true);
  addEventListener("mousedown", () => { ensure(); size(16, "rgba(255, 196, 84, 0.95)"); }, true);
  addEventListener("mouseup", () => { ensure(); size(22, "rgba(255, 255, 255, 0.82)"); }, true);
})();`;

// Enlarges the page like CSS zoom does, keeping the 1920x1080 viewport and sharp text.
const zoomScript = (zoom) => `(() => {
  if (window !== window.top) return;
  const apply = () => { document.documentElement.style.zoom = "${zoom}"; };
  if (document.documentElement) apply();
  document.addEventListener("DOMContentLoaded", apply);
})();`;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

function parseOptions(argv) {
  const { values } = parseArgs({
    args: argv,
    options: {
      "stack-ports": { type: "string", default: "3000,4000,8000,9000" },
      "docs-url": { type: "string", default: "http://127.0.0.1:8770/" },
      live: { type: "string" },
      "live-defect": { type: "string", default: "seeded_missing_coupon" },
      only: { type: "string" },
      out: { type: "string" },
      zoom: { type: "string", default: "1.2" },
      "require-deterministic": { type: "boolean", default: false },
      "judge-cut": { type: "boolean", default: false },
      "job-id": { type: "string" },
      "repair-job-id": { type: "string" },
      help: { type: "boolean", short: "h", default: false },
    },
    strict: true,
  });
  if (values.help) {
    process.stdout.write(HELP);
    process.exit(0);
  }
  const ports = values["stack-ports"].split(",").map((item) => item.trim()).filter(Boolean).map(Number);
  if (ports.length < 2 || ports.length > 4 || ports.some((port) => !Number.isInteger(port) || port < 1 || port > 65535)) {
    throw new Error("--stack-ports takes 2 to 4 ports: storefront,inspector[,api,controller].");
  }
  const zoom = Number(values.zoom);
  if (!(zoom >= 1 && zoom <= 2)) throw new Error("--zoom must be between 1 and 2.");
  const docs = new URL(values["docs-url"]);
  if (!docs.pathname.endsWith("/") && !docs.pathname.endsWith(".html")) docs.pathname += "/";
  let live = null;
  if (values.live) {
    const url = new URL(values.live);
    const local = url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname);
    // Mirrors the judge page: it only talks to https or loopback http services.
    if (url.protocol !== "https:" && !local) throw new Error("--live must be https:// or http://127.0.0.1 / http://localhost.");
    live = url.origin;
  }
  const [storefront, inspector, api, controller] = ports;
  const urls = {
    storefront: `http://127.0.0.1:${storefront}`,
    inspector: `http://127.0.0.1:${inspector}`,
    api: api ? `http://127.0.0.1:${api}/healthz` : null,
    controller: controller ? `http://127.0.0.1:${controller}/healthz` : null,
    docs: docs.href,
    live,
  };
  // New shots are opt-in so existing callers keep their original five-clip behavior.
  let selected = CLIPS.filter((clip) => !["06-apply-regate-revert", "07-gate-blocked", "08-limits"].includes(clip.name)
    && (clip.name !== "05-live-break-it" || live));
  if (values.only) {
    const wanted = values.only.split(",").map((item) => item.trim()).filter(Boolean);
    selected = CLIPS.filter((clip) => wanted.some((token) => clip.name === token || clip.name.startsWith(token + "-") || clip.name.slice(3) === token));
    const unknown = wanted.filter((token) => !CLIPS.some((clip) => clip.name === token || clip.name.startsWith(token + "-") || clip.name.slice(3) === token));
    if (unknown.length) throw new Error(`Unknown clip(s): ${unknown.join(", ")}.`);
    if (selected.some((clip) => clip.name === "05-live-break-it") && !live) throw new Error("Clip 05 needs --live <url>.");
  }
  if (!selected.length) throw new Error("No clips selected.");
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
  const out = path.resolve(values.out ?? path.join(ROOT, "data", "footage", stamp));
  if (values["require-deterministic"] && selected.some((clip) => clip.name === "05-live-break-it")) {
    throw new Error("--require-deterministic excludes clip 05, which may call an external model.");
  }
  return { urls, zoom, selected, out, liveDefect: values["live-defect"], requireDeterministic: values["require-deterministic"], judgeCut: values["judge-cut"], jobId: values["repair-job-id"] ?? values["job-id"] ?? null };
}

async function reachable(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(4000), redirect: "manual" });
    await response.arrayBuffer(); // Drain the body; an unread body can trip undici when the server closes.
    return response.status < 500;
  } catch {
    return false;
  }
}

async function preflight(options) {
  const needed = new Set(options.selected.flatMap((clip) => clip.needs));
  const hints = {
    storefront: "the demo stack (./scripts/start-demo.sh), storefront port",
    inspector: "the demo stack (./scripts/start-demo.sh), Inspector port",
    api: "the demo stack (./scripts/start-demo.sh), API port",
    controller: "the demo stack (./scripts/start-demo.sh), controller port",
    docs: "a static server of docs/ (e.g. scripts/record-footage.sh --serve-docs 8770)",
    live: "the live repair service (./scripts/start-live-demo.sh)",
  };
  const missing = [];
  for (const key of needed) {
    let url = options.urls[key];
    if (!url) continue; // API and controller ports are optional checks.
    if (key === "live") url += "/api/live/status";
    if (!(await reachable(url))) missing.push(`  ${key}: ${url} (${hints[key]})`);
  }
  if (missing.length) throw new Error("Not reachable; start these first:\n" + missing.join("\n"));
}

// ---- Pacing helpers: every movement is animated so viewers can follow it. ----

function pointer(page) {
  const viewport = page.viewportSize();
  // Start in the right-hand margin, where the pages used here have no content.
  const state = { x: Math.round(viewport.width * 0.9), y: Math.round(viewport.height * 0.5) };
  return {
    async show() {
      // Creates the dot in the current document at the last position.
      await page.mouse.move(state.x + 1, state.y);
      await page.mouse.move(state.x, state.y);
    },
    async moveTo(x, y) {
      const distance = Math.hypot(x - state.x, y - state.y);
      const steps = Math.round(clamp(distance / 14, 12, 42));
      const fromX = state.x;
      const fromY = state.y;
      for (let i = 1; i <= steps; i += 1) {
        const t = i / steps;
        const eased = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
        await page.mouse.move(fromX + (x - fromX) * eased, fromY + (y - fromY) * eased);
        await sleep(14);
      }
      state.x = x;
      state.y = y;
    },
    async over(locator, { dx = 0.5, dy = 0.5 } = {}) {
      await locator.waitFor({ state: "visible" });
      const box = await locator.boundingBox();
      if (!box) throw new Error("Element has no box to point at.");
      await this.moveTo(Math.round(box.x + box.width * dx), Math.round(box.y + box.height * dy));
      return box;
    },
    async rest() {
      await this.moveTo(Math.round(viewport.width * 0.9), Math.round(viewport.height * 0.5));
    },
    async click(locator, { dx = 0.5, dy = 0.5 } = {}) {
      const box = await this.over(locator, { dx, dy });
      await sleep(220);
      // Click where the pointer already is, so the visible dot does not jump.
      await locator.click({ position: { x: Math.round(state.x - box.x), y: Math.round(state.y - box.y) } });
      await sleep(200);
    },
  };
}

async function glideTo(page, y, ms) {
  await page.evaluate(async ({ y, ms }) => {
    const startY = window.scrollY;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const target = Math.max(0, Math.min(max, y));
    const distance = target - startY;
    if (Math.abs(distance) < 2) return;
    const duration = ms ?? Math.min(2200, Math.max(800, 500 + Math.abs(distance) * 0.9));
    const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
    const start = performance.now();
    await new Promise((resolve) => {
      const frame = (now) => {
        const t = Math.min(1, (now - start) / duration);
        window.scrollTo({ top: startY + distance * ease(t), behavior: "instant" });
        if (t < 1) requestAnimationFrame(frame);
        else resolve();
      };
      requestAnimationFrame(frame);
    });
  }, { y, ms });
}

// Offsets are CSS px; rectangles and scroll positions are in zoomed pixels.
async function scrollTarget(locator, offset) {
  await locator.waitFor({ state: "attached" });
  return locator.evaluate((node, offset) => {
    const zoom = parseFloat(document.documentElement.style.zoom) || 1;
    return node.getBoundingClientRect().top + window.scrollY - offset * zoom;
  }, offset);
}

async function glideToElement(page, locator, { offset = HEADER_OFFSET, ms } = {}) {
  await glideTo(page, await scrollTarget(locator, offset), ms);
}

async function jumpToElement(page, locator, offset = HEADER_OFFSET) {
  const top = await scrollTarget(locator, offset);
  await page.evaluate((top) => window.scrollTo({ top, behavior: "instant" }), top);
}

// Fraction of the visible page height, in CSS px, for offsets that place an element mid-screen.
async function viewportOffset(page, fraction) {
  return page.evaluate((fraction) => Math.round((window.innerHeight * fraction) / (parseFloat(document.documentElement.style.zoom) || 1)), fraction);
}

async function ready(page) {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await sleep(300);
}

async function waitUntil(predicate, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await sleep(250);
  }
  throw new Error(`Timed out after ${Math.round(timeoutMs / 1000)} s waiting for ${what}.`);
}

// ---- Clips ----

async function recordStorefront(page, { urls, mark }) {
  const cursor = pointer(page);
  await page.goto(urls.storefront + "/", { waitUntil: "networkidle" });
  const product = page.getByRole("link", { name: "Trail Mug", exact: true });
  await product.waitFor();
  await ready(page);
  await cursor.show();
  mark("start");
  await sleep(2200);

  await cursor.click(product);
  await page.getByRole("heading", { level: 1, name: "Trail Mug", exact: true }).waitFor();
  await ready(page);
  await sleep(1300);

  const quantity = page.getByRole("spinbutton", { name: "Quantity", exact: true });
  await cursor.click(quantity);
  await page.keyboard.press("ControlOrMeta+A");
  await quantity.pressSequentially("2", { delay: 120 });
  if ((await quantity.inputValue()) !== "2") await quantity.fill("2");
  await sleep(700);
  await cursor.click(page.getByRole("button", { name: "Add to cart", exact: true }));
  await page.getByRole("link", { name: "Cart, 2 items", exact: true }).waitFor();
  await sleep(1400);

  await cursor.click(page.getByRole("link", { name: "Go to checkout", exact: true }));
  await page.waitForURL("**/checkout");
  const placeOrder = page.getByRole("button", { name: "Place order", exact: true });
  await placeOrder.waitFor();
  await ready(page);
  await sleep(1200);

  for (const [label, text] of [["Name", "Avery Trailhead"], ["Email", "avery@example.com"], ["Address", "14 Ridgeline Road\nBoulder, CO 80302"]]) {
    const field = page.getByLabel(label, { exact: true });
    await cursor.click(field);
    await field.pressSequentially(text, { delay: 38 });
    await sleep(250);
  }
  await sleep(500);

  // Show that the coupon field is left empty, then go back up to place the order.
  const coupon = page.getByLabel("Coupon code", { exact: true });
  await glideToElement(page, coupon, { offset: await viewportOffset(page, 0.45) });
  await cursor.over(coupon, { dx: 0.3 });
  mark("coupon_empty");
  await sleep(1800);
  await glideTo(page, 0);
  await sleep(500);

  await cursor.click(placeOrder);
  mark("order_placed");
  const failure = page.getByRole("main").getByRole("alert").filter({ hasText: "Checkout failed" });
  await failure.waitFor({ timeout: 15_000 });
  mark("crash_visible");
  await sleep(600);
  await cursor.over(failure, { dx: 0.78, dy: 0.82 }); // Just past the end of the TypeError line.
  await sleep(3400);
  mark("end");
  return { provenance: "local-fixture", banner: (await failure.innerText()).replace(/\s+/g, " ").trim() };
}

async function recordReplay(page, { urls, mark, judgeCut }) {
  const cursor = pointer(page);
  await page.goto(urls.docs, { waitUntil: "load" });
  await ready(page);
  await cursor.show();
  mark("start");
  await sleep(3200); // The headline and the "Play the recorded Meta repair" call to action.

  await glideToElement(page, page.locator("#repair .player"), { ms: 1600 });
  await sleep(1400);
  const play = page.locator("#play-recorded");
  await cursor.click(play);
  mark("play_start");
  await cursor.rest(); // Keep the running clock and the timeline uncovered.
  await waitUntil(async () => (await play.textContent())?.trim() === "Play again", 30_000, "the recorded playback to finish");
  mark("play_end");
  await sleep(2600);

  await glideToElement(page, page.locator("#repair figure.diff"), { ms: 1500 });
  mark("diff_visible");
  await sleep(judgeCut ? 4000 : 9500); // The one-line patch, the model's explanation, and the recorded facts.
  mark("end");
  return { provenance: "recorded-meta-replay", job: RECORDED_JOB, clock: (await page.locator("#recorded-clock").textContent())?.trim() };
}

async function recordGates(page, { urls, mark, judgeCut }) {
  const cursor = pointer(page);
  await page.goto(urls.docs, { waitUntil: "load" });
  await ready(page);
  await jumpToElement(page, page.locator("#gates"));
  await sleep(400);
  await cursor.show();
  mark("start");
  await sleep(judgeCut ? 2200 : 4200); // The question and the four recorded totals.

  await glideToElement(page, page.locator("#picker"), { ms: 1300 });
  await sleep(1200);
  const patches = judgeCut ? ["early_return_unsaved", "zero_all_discounts"] : GATE_PATCHES;
  for (const id of patches) {
    const option = page.locator(`label[for="patch-${id}"]`);
    await cursor.click(option, { dx: 0.62 }); // Between the patch name and its status.
    await page.locator("#detail").getByText(id, { exact: true }).waitFor();
    mark(`patch_${id}`);
    await sleep(judgeCut ? 3500 : 5000); // Verdicts, failed checks, and the diff.
  }
  mark("end");
  return { provenance: "recorded-evaluation", patches };
}

function classifySource(text) {
  if (/^Deterministic fallback/.test(text)) return "deterministic";
  if (/^Meta Model API/.test(text)) return "meta";
  return "other";
}

async function recordInspector(page, { urls, mark, out, requireDeterministic, judgeCut }) {
  const cursor = pointer(page);
  await page.goto(urls.inspector + "/", { waitUntil: "networkidle" });
  const run = page.getByRole("button", { name: "Run sandbox repair", exact: true });
  await run.waitFor();
  await waitUntil(() => run.isEnabled(), 90_000, "the Inspector to report readiness (Run sandbox repair enabled)");
  await ready(page);
  const readinessSource = (await page.locator(".workspace .source-line").innerText()).replace(/\s+/g, " ").trim();
  if (requireDeterministic && !readinessSource.includes("Deterministic fallback")) {
    throw new Error(`Refusing a model call: Inspector source is ${readinessSource}.`);
  }
  await jumpToElement(page, page.locator(".workspace"));
  await cursor.show();
  mark("start");
  await sleep(judgeCut ? 1600 : 2600);
  // Point at the patch source line from its left margin, leaving its text readable.
  await cursor.over(page.locator(".workspace .source-line"), { dx: -0.03 });
  await sleep(judgeCut ? 1500 : 2200);

  const submitted = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname.endsWith("/api/faultline/jobs"), { timeout: 30_000 });
  await cursor.click(run);
  mark("run_start");
  const submittedJob = await (await submitted).json();
  if (!submittedJob.job_id) throw new Error("Inspector did not return the submitted job id.");
  await cursor.rest(); // The page scrolls to the live result; keep its text uncovered.
  const heading = page.locator("#job-h");
  await heading.waitFor({ timeout: 30_000 });
  // While a run is active the button reads "Repair in progress…"; its name returns when the run ends.
  await waitUntil(async () => (await run.count()) > 0 && (await run.isEnabled()), 300_000, "the run to finish");
  mark("run_end");
  const outcome = (await heading.innerText()).trim();
  if (outcome !== "Verified repair") throw new Error(`Sandbox repair did not verify: ${outcome}.`);
  const sourceLine = page.locator(".result-heading .source-line");
  const jobSource = (await sourceLine.count()) ? (await sourceLine.innerText()).replace(/\s+/g, " ").replace(/^Patch source\s*/, "").trim() : "";
  await jumpToElement(page, page.locator("section.job"));
  await sleep(500);
  await cursor.rest();
  await sleep(judgeCut ? 2500 : 5000); // Result heading, provider line, and the recorded steps.

  const stops = [
    ["seam", page.locator("section.job .seam").first(), 4800],
    ["patch", (await page.locator("section.job .proof").count()) ? page.locator("section.job .proof") : page.locator("#attempts-h"), 6000],
    ["evidence", page.locator("#artifacts-h"), 3800],
  ];
  for (const [key, locator, hold] of stops) {
    if (!(await locator.count())) continue;
    await glideToElement(page, locator);
    mark(key);
    await sleep(judgeCut ? 2500 : hold);
  }
  const details = page.locator("details.technical-details > summary");
  if (await details.count()) {
    await glideToElement(page, details, { offset: await viewportOffset(page, 0.3) });
    await cursor.click(details, { dx: 0.1 });
    await cursor.rest();
    await glideToElement(page, details);
    mark("details");
    await sleep(judgeCut ? 2500 : 4500);
  }
  mark("end");
  const jobId = submittedJob.job_id;
  const jobRecord = await inspectorJson(urls, `jobs/${encodeURIComponent(jobId)}`);
  await writeFile(path.join(out, "04-inspector-job.json"), JSON.stringify(jobRecord, null, 2) + "\n");
  return {
    provenance: classifySource(jobSource || readinessSource) === "meta" ? "local-meta" : "local-" + classifySource(jobSource || readinessSource),
    outcome,
    readiness_source: readinessSource,
    job_source: jobSource,
    job_id: jobId,
    job_record_file: jobId ? "04-inspector-job.json" : null,
  };
}

async function inspectorJson(urls, pathname) {
  const response = await fetch(`${urls.inspector}/api/faultline/${pathname}`, { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error(`Inspector ${pathname} returned HTTP ${response.status}.`);
  return response.json();
}

async function recordLimits(page, { urls, mark }) {
  await page.goto(urls.docs, { waitUntil: "load" });
  await ready(page);
  await jumpToElement(page, page.locator("#limits"));
  mark("start");
  await sleep(6000);
  mark("end");
  return { provenance: "current-project-scope", text: await page.locator("#limits").innerText() };
}

async function recordBlockedGate(page, { urls, out, mark }) {
  const store = await inspectorJson(urls, "store");
  if (store.state !== "seeded") throw new Error(`Blocked gate needs the seeded store; actual state ${store.state}.`);
  // Execute first, then film the captured output. There is no invented progress or simulated terminal.
  const capture = await captureGate({ root: ROOT, out, name: "07-gate-blocked", target: urls.storefront });
  await showGateOutput(page, capture);
  mark("start");
  mark("verdict_visible");
  await sleep(6500);
  await showGateOutput(page, capture, "reproduction");
  mark("reproduction_visible");
  await sleep(8500);
  mark("end");
  if (capture.exit_code !== 1 || capture.report.verdict !== "DEPLOYMENT_BLOCKED" || capture.report.failure?.status !== 500) {
    throw new Error(`Expected a caught HTTP 500 and exit 1; actual ${capture.report.verdict}, exit ${capture.exit_code}. See ${capture.stdout_file}.`);
  }
  return { provenance: "captured-cli-output", capture };
}

async function recordApplyGateRevert(page, { urls, out, mark, jobId }) {
  const cursor = pointer(page);
  await page.goto(urls.inspector + "/", { waitUntil: "networkidle" });
  await ready(page);
  const flow = page.locator("#demo");
  const apply = flow.getByRole("button", { name: "Apply fix", exact: true });
  // Completed jobs are deliberately not reattached on reload. Select the real retained job through history.
  const jobs = await inspectorJson(urls, "jobs?limit=10");
  const sourceJob = jobId ? jobs.jobs?.find((job) => job.id === jobId)
    : jobs.jobs?.find((job) => job.state === "succeeded" && job.outcome === "verified");
  if (!sourceJob || sourceJob.state !== "succeeded" || sourceJob.outcome !== "verified") {
    throw new Error("Clip 06 needs a completed verified job; record clip 04 first or pass --repair-job-id.");
  }
  await page.locator("details.history > summary").click();
  await page.getByRole("button", { name: `Inspect job ${sourceJob.id.slice(0, 8)}`, exact: true }).click();
  await waitUntil(() => apply.isEnabled(), 90_000, "the verified job to unlock Apply fix");
  const before = await inspectorJson(urls, "store");
  if (before.state !== "seeded") throw new Error(`Apply shot needs the seeded store; actual ${before.state}.`);
  await jumpToElement(page, flow);
  await cursor.show();
  mark("start");
  mark("apply_start");
  let capture = null;
  let applied = null;
  let finalStore = null;
  const liveChecks = [];
  const pendingChecks = [];
  const onCheckResponse = (response) => {
    if (response.request().method() === "POST" && /\/api\/faultline\/invariants\/[^/]+\/check$/.test(new URL(response.url()).pathname)) {
      pendingChecks.push(response.json().then((record) => { liveChecks.push(record); }, (error) => { liveChecks.push({ capture_error: error.message }); }));
    }
  };
  page.on("response", onCheckResponse);
  try {
    await sleep(2000);
    await cursor.click(apply);
    mark("apply_clicked");
    const checkoutStatus = flow.locator(".flow-step").nth(2).locator(".flow-status");
    await waitUntil(async () => (await checkoutStatus.innerText()).includes("HTTP 201") && (await checkoutStatus.innerText()).includes("checkout works"), 90_000, "the live checkout check to return HTTP 201");
    applied = await inspectorJson(urls, "store");
    if (applied.state !== "patched") throw new Error(`Apply did not patch the demo store (${applied.state}).`);
    await Promise.all(pendingChecks);
    if (!liveChecks.some((check) => check.outcome === "no_failure" && check.sessions?.length >= 2
      && check.sessions.every((session) => session.status === 201))) {
      throw new Error("No captured live check proves HTTP 201 in both fresh sessions.");
    }
    mark("http_201_visible");
    mark("apply_verified");
    await sleep(4500);
    mark("gate_start");
    capture = await captureGate({ root: ROOT, out, name: "06-gate-clean", target: urls.storefront });
    mark("gate_end");
    await showGateOutput(page, capture);
    mark("clean_gate_visible");
    mark("terminal_start");
    await sleep(6500);
    mark("terminal_end");
    if (capture.exit_code !== 0 || capture.report.verdict !== "SAFE_TO_DEPLOY" || capture.report.stop_reason !== "exhausted") {
      throw new Error(`Clean gate did not finish clean: ${capture.report.verdict}, ${capture.report.stop_reason}, exit ${capture.exit_code}. See ${capture.stdout_file}.`);
    }
  } finally {
    // Return the real demo store to its starting state even if the clean gate fails.
    mark("revert_start");
    await page.goto(urls.inspector + "/", { waitUntil: "networkidle" });
    await ready(page);
    await jumpToElement(page, flow);
    const current = await inspectorJson(urls, "store");
    if (current.state !== "seeded") {
      const revert = flow.getByRole("button", { name: "Revert store", exact: true });
      await waitUntil(() => revert.isEnabled(), 30_000, "Revert store to become available");
      await cursor.click(revert);
      await cursor.click(flow.getByRole("button", { name: "Confirm revert?", exact: true }));
      await waitUntil(async () => (await inspectorJson(urls, "store")).state === "seeded", 30_000, "Revert store to restore the seeded defect");
    }
    finalStore = await inspectorJson(urls, "store");
    await flow.getByRole("heading", { name: "Checkout is broken: the seeded defect is live", exact: true }).waitFor();
    mark("seeded_restored");
    // A retained pre-revert check can still show HTTP 201. Recheck the actual restored source for the closing shot.
    await sleep(1000);
    await cursor.click(flow.getByRole("button", { name: "Check checkout live", exact: true }));
    await waitUntil(async () => (await flow.locator(".flow-step").first().locator(".flow-status").innerText()).includes("HTTP 500"), 30_000, "the reverted store's live check to reproduce HTTP 500");
    mark("reverted_http_500_visible");
    await sleep(3500);
    await writeFile(path.join(out, "06-store-states.json"), JSON.stringify({ before, applied, final: finalStore }, null, 2) + "\n");
    page.off("response", onCheckResponse);
    await Promise.all(pendingChecks);
    await writeFile(path.join(out, "06-live-checks.json"), JSON.stringify(liveChecks, null, 2) + "\n");
    mark("end");
  }
  return { provenance: "local-apply-captured-cli-revert", applied_job_id: applied.applied_job_id, live_checkout_status: 201,
    store_state_file: "06-store-states.json", live_check_file: "06-live-checks.json", final_store_state: finalStore.state, capture };
}

async function liveJson(base, pathname) {
  const response = await fetch(base + pathname, { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error(`${pathname} returned HTTP ${response.status}`);
  return response.json();
}

async function recordLive(page, { urls, mark, liveDefect }) {
  const cursor = pointer(page);
  const url = new URL(urls.docs);
  url.searchParams.set("live", urls.live);
  await page.goto(url.href, { waitUntil: "load" });
  await ready(page);
  const runButton = page.locator("#live-run");
  await jumpToElement(page, page.locator("#live"));
  const status = await liveJson(urls.live, "/api/live/status");
  await waitUntil(() => runButton.isEnabled(), 60_000, `the live service to accept runs (${status.reason ?? "no reason given"})`);
  await cursor.show();
  mark("start");
  await sleep(3600); // The status line names the provider the service is configured with.

  const option = page.locator(`label[for="defect-${liveDefect}"]`);
  if (!(await option.count())) throw new Error(`Unknown --live-defect ${liveDefect}.`);
  await cursor.click(option, { dx: 0.3 });
  await sleep(1200);
  await cursor.click(runButton);
  mark("run_start");
  await cursor.rest(); // Keep the button label and the running clock uncovered.
  const result = page.locator("#live-result .result-head");
  await waitUntil(async () => (await result.count()) > 0, 300_000, "the live run to finish");
  mark("run_end");
  const runId = new URL(page.url()).hash.match(/^#run=([0-9a-f-]+)$/i)?.[1] ?? null;
  await sleep(2400);
  await glideToElement(page, page.locator("#live-result"));
  await sleep(8000);
  mark("end");
  let record = null;
  if (runId) {
    const runRecord = await liveJson(urls.live, `/api/live/runs/${encodeURIComponent(runId)}`);
    record = {
      id: runRecord.id,
      defect_id: runRecord.defect_id,
      outcome: runRecord.outcome,
      provider: runRecord.provider,
      model: runRecord.model,
      classification: runRecord.classification,
      attempts: (runRecord.attempts ?? []).map((attempt) => ({
        attempt_number: attempt.attempt_number,
        outcome: attempt.outcome,
        provider: attempt.provider,
        model: attempt.model,
        generation_ms: attempt.generation_ms,
      })),
    };
  }
  const allMeta = Boolean(record && record.classification === "meta_model" && record.attempts.length && record.attempts.every((attempt) => attempt.provider === "meta"));
  return {
    provenance: allMeta ? "live-meta" : "live-not-meta",
    live_url: urls.live,
    service: { provider: status.provider, model: status.model, classification: status.classification },
    run: record,
    headline: (await result.innerText()).trim(),
  };
}

// ---- Driver ----

async function recordClip(browser, clip, options) {
  const raw = path.join(options.out, ".raw", clip.name);
  const context = await browser.newContext({ viewport: VIDEO, recordVideo: { dir: raw, size: VIDEO, fps: FPS } });
  if (options.zoom !== 1) await context.addInitScript(zoomScript(options.zoom));
  await context.addInitScript(CURSOR_SCRIPT);
  const page = await context.newPage();
  const origin = Date.now(); // The video starts with the page; marks are seconds from here.
  const marks = {};
  const mark = (key) => {
    marks[key] = Number(((Date.now() - origin) / 1000).toFixed(2));
  };
  const started = new Date().toISOString();
  let info = {};
  let error = null;
  try {
    info = await clip.run(page, { ...options, mark });
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught);
    await page.screenshot({ path: path.join(options.out, `${clip.name}.failure.png`) }).catch(() => undefined);
  }
  mark("closed");
  const video = page.video();
  await context.close();
  const file = `${clip.name}.webm`;
  await video.saveAs(path.join(options.out, file));
  await rm(raw, { recursive: true, force: true });
  return { name: clip.name, file, status: error ? "failed" : "ok", error, recorded_at: started, marks, ...info };
}

async function main() {
  const options = parseOptions(process.argv.slice(2));
  await preflight(options);
  await mkdir(options.out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const manifest = {
    created_at: new Date().toISOString(),
    video: { ...VIDEO, fps: FPS, zoom: options.zoom },
    urls: { ...options.urls },
    clips: [],
  };
  const manifestPath = path.join(options.out, "clips.json");
  try {
    for (const clip of options.selected) {
      process.stdout.write(`Recording ${clip.name} ... `);
      const result = await recordClip(browser, clip, options);
      if (clip.name === "04-inspector-run" && result.status === "ok") options.jobId = result.job_id;
      manifest.clips.push(result);
      await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
      const length = result.marks.end != null && result.marks.start != null ? ` (${(result.marks.end - result.marks.start).toFixed(1)} s usable)` : "";
      process.stdout.write(result.status === "ok" ? `ok${length}\n` : `FAILED: ${result.error}\n`);
    }
  } finally {
    await browser.close();
    await rm(path.join(options.out, ".raw"), { recursive: true, force: true });
  }
  process.stdout.write(`\nFootage: ${options.out}\nNext: ./scripts/assemble-footage.sh ${path.relative(ROOT, options.out) || "."}\n`);
  if (manifest.clips.some((clip) => clip.status !== "ok")) process.exitCode = 1;
}

main().catch((error) => {
  process.stderr.write(`record-footage: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(2);
});
