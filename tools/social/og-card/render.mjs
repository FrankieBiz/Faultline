#!/usr/bin/env node
// Render FaultLine's share cards from the HTML templates in this directory.
//
//   node tools/social/og-card/render.mjs [--out DIR] [--only NAME]
//
// Output (default docs/assets/og/): the files listed in ASSETS below, PNG, device scale 1.
// No network: every request goes to a made-up origin that is answered from the repository on disk,
// and anything else is aborted. Fonts come from docs/assets/fonts/, frames and numbers from the
// committed records (docs/replay/3573b32b-.../job.json, docs/evidence/2026-10-28-evaluation-*.json).
//
// Each render is checked before it is written: both web fonts loaded, the template's own record
// checks passed, and every key element sits inside the safe area (48 px from the top and bottom
// edges, inside the canvas, and clear of the bottom-left 320x80 where X overlays the link title).
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const requireFromRunner = createRequire(path.join(ROOT, "tools/browser-runner/package.json"));
let chromium;
try {
  const playwright = await import(pathToFileURL(requireFromRunner.resolve("@playwright/test")).href);
  chromium = playwright.chromium ?? playwright.default.chromium;
} catch {
  console.error("Missing tools/browser-runner dependencies. Run make setup (or npm ci in tools/browser-runner).");
  process.exit(1);
}

// Never bump a shared file in place: X caches card images by URL. Change a card, then add a -v2 name.
export const ASSETS = [
  { file: "faultline-card-v1.png", template: "card.html", query: "layout=og", width: 1200, height: 630 },
  { file: "faultline-github-1280x640.png", template: "card.html", query: "layout=og", width: 1280, height: 640 },
  { file: "faultline-gallery-1920x1080.png", template: "card.html", query: "layout=gallery", width: 1920, height: 1080 },
  { file: "faultline-201-trap-1080x1350.png", template: "trap.html", query: "layout=portrait", width: 1080, height: 1350 },
  { file: "faultline-201-trap-1200x675.png", template: "trap.html", query: "layout=landscape", width: 1200, height: 675 },
];

const args = process.argv.slice(2);
if (args.includes("-h") || args.includes("--help")) {
  console.log("Usage: node tools/social/og-card/render.mjs [--out DIR] [--only FILE] [--force]");
  process.exit(0);
}
const flag = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const OUT = path.resolve(flag("--out") ?? path.join(ROOT, "docs/assets/og"));
const ONLY = flag("--only");
const FORCE = args.includes("--force"); // write layout-check failures too, for previewing a draft
const ORIGIN = "http://og.faultline.test";
const SAFE_Y = 48;
const OVERLAY = { width: 320, height: 80 };
const MAX_BYTES = 1_000_000; // GitHub's social-preview limit, and well under X's and LinkedIn's 5 MB
const TARGET_BYTES = 300_000; // keeps crawler fetches quick (Discord gives an unfurl 10 s in total)
// The only repository paths a template may read: itself, the fonts, and the records it cites.
const READABLE = [
  "tools/social/og-card/",
  "docs/assets/fonts/",
  "docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/",
  "docs/evidence/2026-10-28-evaluation-deterministic.json",
  "docs/evidence/2026-10-28-evaluation-deepseek-v4-pro.json",
  "fixtures/evaluation/adversarial/early_return_unsaved.diff",
];

const browser = await chromium.launch();
const failures = [];
try {
  await mkdir(OUT, { recursive: true });
  for (const asset of ASSETS.filter((a) => !ONLY || a.file === ONLY)) {
    const context = await browser.newContext({
      viewport: { width: asset.width, height: asset.height },
      deviceScaleFactor: 1,
      colorScheme: "dark",
      reducedMotion: "reduce",
      locale: "en-US",
      timezoneId: "UTC",
    });
    await context.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== ORIGIN) return route.abort("blockedbyclient");
      const file = path.resolve(ROOT, "." + decodeURIComponent(url.pathname));
      const rel = path.relative(ROOT, file).split(path.sep).join("/");
      if (rel.startsWith("..") || !READABLE.some((prefix) => rel === prefix || (prefix.endsWith("/") && rel.startsWith(prefix)))) {
        return route.fulfill({ status: 404 });
      }
      try {
        return route.fulfill({ status: 200, body: await readFile(file), contentType: mime(file) });
      } catch {
        return route.fulfill({ status: 404 });
      }
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("requestfailed", (r) => errors.push(`request failed: ${r.url()}`));
    await page.goto(`${ORIGIN}/tools/social/og-card/${asset.template}?${asset.query}`);
    await page.waitForFunction(() => window.__og !== undefined, null, { timeout: 15_000 });
    const state = await page.evaluate(() => window.__og);
    if (!state.ok) errors.push(state.error);

    const problems = await page.evaluate(({ SAFE_Y, OVERLAY }) => {
      const W = innerWidth, H = innerHeight, out = [];
      for (const el of document.querySelectorAll("[data-key]")) {
        const r = el.getBoundingClientRect();
        const name = el.id || el.className || el.tagName;
        if (r.width === 0 || r.height === 0) { out.push(`${name} is empty`); continue; }
        if (r.top < SAFE_Y - 0.5 || r.bottom > H - SAFE_Y + 0.5) out.push(`${name} is within ${SAFE_Y}px of the top or bottom (${Math.round(r.top)}..${Math.round(r.bottom)})`);
        if (r.left < 0 || r.right > W) out.push(`${name} leaves the canvas horizontally`);
        if (r.left < OVERLAY.width && r.bottom > H - OVERLAY.height) out.push(`${name} enters the bottom-left ${OVERLAY.width}x${OVERLAY.height} title overlay`);
      }
      for (const el of document.querySelectorAll("[data-fit]")) {
        if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) out.push(`${el.id || el.className} overflows its box`);
      }
      return out;
    }, { SAFE_Y, OVERLAY });
    errors.push(...problems);

    let png;
    if (state.ok) {
      png = await page.screenshot({ type: "png", clip: { x: 0, y: 0, width: asset.width, height: asset.height }, animations: "disabled", caret: "hide" });
      if (png.length > MAX_BYTES) errors.push(`${png.length} B is over the ${MAX_BYTES} B limit`);
    }
    if (errors.length) failures.push(`${asset.file}:\n  ${errors.join("\n  ")}`);
    if (png && (!errors.length || FORCE)) {
      await writeFile(path.join(OUT, asset.file), png);
      const sha = createHash("sha256").update(png).digest("hex");
      const note = png.length > TARGET_BYTES ? `  (over the ${TARGET_BYTES} B target)` : "";
      console.log(`${asset.file}  ${asset.width}x${asset.height}  ${png.length} B  sha256 ${sha}${note}`);
    }
    await context.close();
  }
} finally {
  await browser.close();
}
if (failures.length) {
  console.error(`\n${FORCE ? "Failed checks (drafts written anyway with --force)" : "Not written"}:\n${failures.join("\n")}`);
  process.exit(1);
}

function mime(file) {
  const ext = path.extname(file).toLowerCase();
  return {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".woff2": "font/woff2",
  }[ext] ?? "application/octet-stream";
}
