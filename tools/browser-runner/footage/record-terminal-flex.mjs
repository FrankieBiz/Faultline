#!/usr/bin/env node
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { chromium } from "@playwright/test";

const execFileAsync = promisify(execFile);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const OUT_DIR = path.join(ROOT, "data/footage/20261101-193931");
const VIDEO = { width: 1920, height: 1080 };
const FPS = 30;

const TERMINAL_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FaultLine Terminal</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #090a0f;
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
  }
  .window {
    width: 1720px;
    height: 940px;
    background: #0f1117;
    border-radius: 12px;
    box-shadow: 0 24px 80px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.1);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .titlebar {
    height: 44px;
    background: #161922;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    display: flex;
    align-items: center;
    padding: 0 18px;
    user-select: none;
  }
  .buttons { display: flex; gap: 8px; }
  .btn { width: 12px; height: 12px; border-radius: 50%; }
  .btn-close { background: #ff5f56; }
  .btn-min { background: #ffbd2e; }
  .btn-max { background: #27c93f; }
  .title {
    flex: 1;
    text-align: center;
    font-size: 13px;
    color: #8b949e;
    font-weight: 500;
  }
  .content {
    flex: 1;
    padding: 24px 28px;
    font-size: 15px;
    line-height: 1.5;
    color: #c9d1d9;
    overflow: hidden;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .prompt { color: #38bdf8; font-weight: 600; }
  .cmd { color: #f1f5f9; font-weight: 600; }
  .log { color: #94a3b8; }
  .err { color: #f87171; font-weight: bold; }
  .ok { color: #4ade80; }
  .badge-blocked {
    display: inline-block;
    background: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    border: 1px solid rgba(239, 68, 68, 0.4);
    padding: 2px 10px;
    border-radius: 4px;
    font-weight: bold;
    margin: 6px 0;
  }
  .prompt-box {
    background: rgba(30, 41, 59, 0.5);
    border-left: 3px solid #38bdf8;
    padding: 8px 14px;
    margin-top: 8px;
    color: #e2e8f0;
  }
  .cursor {
    display: inline-block;
    width: 9px;
    height: 17px;
    background: #38bdf8;
    vertical-align: middle;
    animation: blink 1s step-end infinite;
  }
  @keyframes blink { 50% { opacity: 0; } }
</style>
</head>
<body>
<div class="window">
  <div class="titlebar">
    <div class="buttons">
      <div class="btn btn-close"></div>
      <div class="btn btn-min"></div>
      <div class="btn btn-max"></div>
    </div>
    <div class="title">frankbiz@linux-workstation: ~/Faultline — faultline gate</div>
  </div>
  <div class="content" id="terminal"></div>
</div>
<script>
const term = document.getElementById("terminal");
const lines = [
  { html: '<span class="prompt">frankbiz@workstation:~/Faultline$</span> <span class="cmd" id="typing"></span><span class="cursor" id="cur"></span>', delay: 400 },
  { typeCmd: "./faultline gate http://127.0.0.1:3000", delay: 1800 },
  { html: '<br><span class="log">[Playwright] Launching Chromium...</span>', delay: 400 },
  { html: '<span class="log">[Playwright] Navigating to http://127.0.0.1:3000/...</span>', delay: 500 },
  { html: '<span class="log">[Playwright] Discovered 9 interactive elements across 1 screen.</span>', delay: 400 },
  { html: '<span class="log">[Playwright] Step 2: Clicking Trail Mug -> <span class="ok">OK</span></span>', delay: 400 },
  { html: '<span class="log">[Playwright] Discovered 17 interactive elements across 2 screens.</span>', delay: 400 },
  { html: '<span class="log">[Playwright] Step 3: Clicking Add to cart -> <span class="ok">OK</span></span>', delay: 400 },
  { html: '<span class="log">[Playwright] Step 4: Clicking Go to checkout -> <span class="ok">OK</span></span>', delay: 400 },
  { html: '<span class="log">[Playwright] Discovered 30 interactive elements across 3 screens.</span>', delay: 400 },
  { html: '<span class="log">[Playwright] Step 5: Filling Name with "Alex Tester" -> <span class="ok">OK</span></span>', delay: 350 },
  { html: '<span class="log">[Playwright] Step 6: Filling Email with "test@example.com" -> <span class="ok">OK</span></span>', delay: 350 },
  { html: '<span class="log">[Playwright] Step 7: Filling Address with "123 Main St" -> <span class="ok">OK</span></span>', delay: 350 },
  { html: '<span class="log">[Playwright] Step 8: Clicking Place order -> <span class="err">💥 HTTP 500 on POST /api/checkout</span></span>', delay: 600 },
  { html: '<br><div class="badge-blocked">🛑 FAILED · DEPLOYMENT_BLOCKED (exit 1)</div>', delay: 500 },
  { html: '<span class="err">Defect intercepted: HTTP 500 on POST /api/checkout after 7 actions across 3 screens.</span>', delay: 400 },
  { html: '<br><span style="color:#e2e8f0;font-weight:600;">Reproduction journey</span>\\n  1. Open http://127.0.0.1:3000/\\n  2. Click link "Trail Mug" on /\\n  3. Click button "Add to cart" on /product/trail-mug\\n  4. Click link "Go to checkout" on /product/trail-mug\\n  5. Fill "Name", "Email", "Address" on /checkout\\n  6. Click button "Place order" on /checkout -> <span class="err">HTTP 500 on POST /api/checkout</span>', delay: 600 },
  { html: '<br><div class="prompt-box"><strong>Agent Remediation Prompt:</strong>\\nFaultLine caught an unhandled HTTP 500 error on POST /api/checkout. Triggered by clicking "Place order" on /checkout.\\nFix the server-side exception handling for POST /api/checkout so it no longer returns HTTP 500 before deploying, then re-run <code>faultline gate http://127.0.0.1:3000/ --json</code> and continue only when it exits 0.</div>', delay: 1000 }
];

async function run() {
  for (const item of lines) {
    if (item.typeCmd) {
      const el = document.getElementById("typing");
      for (let i = 0; i < item.typeCmd.length; i++) {
        el.textContent += item.typeCmd[i];
        await new Promise(r => setTimeout(r, 38));
      }
      document.getElementById("cur").remove();
      await new Promise(r => setTimeout(r, 300));
    } else if (item.html) {
      const d = document.createElement("div");
      d.innerHTML = item.html;
      term.appendChild(d);
      await new Promise(r => setTimeout(r, item.delay));
    }
  }
}
window.runTerminal = run;
</script>
</body>
</html>`;

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const clipsDir = path.join(OUT_DIR, "clips");
  await mkdir(clipsDir, { recursive: true });

  const htmlPath = path.join(OUT_DIR, "terminal-flex.html");
  await writeFile(htmlPath, TERMINAL_HTML, "utf8");

  const rawDir = path.join(OUT_DIR, ".raw-terminal");
  await mkdir(rawDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: VIDEO,
    recordVideo: { dir: rawDir, size: VIDEO }
  });
  const page = await context.newPage();
  await page.goto("file://" + htmlPath, { waitUntil: "load" });
  await page.waitForTimeout(600);

  // Trigger terminal animation
  await page.evaluate(() => window.runTerminal());
  // Wait for the typing, steps, and prompt to display completely + hold for 6 seconds
  await page.waitForTimeout(14500);

  const video = page.video();
  await context.close();

  const webmPath = path.join(OUT_DIR, "05-terminal-gate-flex.webm");
  await video.saveAs(webmPath);
  await browser.close();
  await rm(rawDir, { recursive: true, force: true });

  console.log("Raw terminal flex recorded:", webmPath);

  // Now encode with ffmpeg into clips/05-terminal-gate-flex.mp4 with lower-third caption!
  const mp4Path = path.join(clipsDir, "05-terminal-gate-flex.mp4");
  const captionRegular = "Inter-Medium.otf";
  const captionBold = "Inter-SemiBold.otf";

  // Use ffmpeg to encode to H.264
  const filter = [
    `drawbox=x=80:y=920:w=1760:h=90:color=black@0.85:t=fill`,
    `drawbox=x=80:y=920:w=8:h=90:color=#ef4444:t=fill`,
    `drawtext=text='Pre-Flight Agent Gate (CLI)':fontcolor=white:fontsize=28:x=110:y=935`,
    `drawtext=text='Deterministic Playwright exploration exits 1 (DEPLOYMENT_BLOCKED) and generates exact fix prompt':fontcolor=#94a3b8:fontsize=22:x=110:y=972`
  ].join(",");

  console.log("Encoding 05-terminal-gate-flex.mp4 with lower-third caption...");
  await execFileAsync("ffmpeg", [
    "-y", "-i", webmPath,
    "-vf", filter,
    "-c:v", "libopenh264", "-b:v", "8M",
    "-pix_fmt", "yuv420p", "-r", "30", "-an",
    "-movflags", "+faststart",
    mp4Path
  ]);

  console.log("Created:", mp4Path);
}

main().catch(console.error);
