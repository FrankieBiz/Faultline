#!/usr/bin/env node
// Render the 10-slide LinkedIn developer carousel (1080x1350) to PNGs and one PDF.
//
//   node tools/social/generate-linkedin-carousel.mjs [--out DIR]
//
// Output (default data/social/linkedin-carousel/): slide-01.png … slide-10.png, faultline-carousel.pdf,
// and carousel.html (the source the PNGs were rendered from).
//
// Every figure on a slide comes from a committed record, cited in that slide's footer. Re-check the
// cited file before publishing; never add a number here that has no record behind it.
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const requireFromRunner = createRequire(path.join(ROOT, "tools/browser-runner/package.json"));
let chromium;
try {
  const playwright = await import(pathToFileURL(requireFromRunner.resolve("@playwright/test")).href);
  chromium = playwright.chromium ?? playwright.default.chromium;
} catch {
  console.error("Missing tools/browser-runner dependencies. Run make setup (or npm ci in tools/browser-runner).");
  process.exit(1);
}

const args = process.argv.slice(2);
if (args.includes("-h") || args.includes("--help")) {
  console.log("Usage: node tools/social/generate-linkedin-carousel.mjs [--out DIR]");
  process.exit(0);
}
const outIndex = args.indexOf("--out");
const OUT = path.resolve(outIndex >= 0 && args[outIndex + 1] ? args[outIndex + 1] : path.join(ROOT, "data/social/linkedin-carousel"));
const W = 1080;
const H = 1350;

// Seismograph traces, one per evidence state (the same vocabulary as the judge page and Inspector):
// rupture = failure, think = model working, hunt = work in flight, resonance = verified.
const TRACE_W = 1080;
const MID = 60;
function trace(mode) {
  const points = [];
  for (let x = 0; x <= TRACE_W; x += 4) {
    let y = MID;
    if (mode === "rupture") {
      const k = x % 90;
      y += k < 6 ? -48 : k < 12 ? 44 : k < 18 ? -22 : Math.sin(x / 7) * 3;
    } else if (mode === "think") {
      y += Math.sin(x / 60) * 20 * Math.sin(x / 340 + 0.6) + Math.sin(x / 9) * 2;
    } else if (mode === "hunt") {
      const k = x % 180;
      y += k > 80 && k < 92 ? (k < 86 ? -36 : 28) : Math.sin(x / 11) * 2;
    } else if (mode === "resonance") {
      y += Math.sin(x / 34) * 14;
    } else if (mode === "shift") {
      // Rupture on the left resolving into resonance on the right: the whole story in one line.
      const t = x / TRACE_W;
      const k = x % 70;
      const jag = k < 5 ? -46 : k < 10 ? 40 : Math.sin(x / 6) * 4;
      y += jag * Math.max(0, 1 - t * 1.8) + Math.sin(x / 34) * 14 * Math.min(1, Math.max(0, t * 1.8 - 0.6));
    }
    points.push(`${x},${y.toFixed(1)}`);
  }
  return `M${points.join(" L")}`;
}

const COLOR = { rupture: "var(--rose)", think: "var(--amber)", hunt: "var(--cyan)", resonance: "var(--emerald)" };
function seismo(mode) {
  if (mode === "shift") {
    return `<svg class="seis" viewBox="0 0 ${TRACE_W} 120" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="shift" x1="0" x2="1"><stop offset="0.25" stop-color="#ff4d6a"/><stop offset="0.7" stop-color="#3dffa2"/></linearGradient></defs>
      <path d="${trace(mode)}" stroke="url(#shift)"/></svg>`;
  }
  return `<svg class="seis" viewBox="0 0 ${TRACE_W} 120" preserveAspectRatio="none" aria-hidden="true">
    <path d="${trace(mode)}" style="stroke:${COLOR[mode]}"/></svg>`;
}

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const slides = [
  {
    mode: "shift",
    source: "README.md · docs/evidence/2026-10-28-meta-replay-review.md",
    body: `
      <h1 class="hook">We let an AI model patch our code.<span>It only shipped after passing 44 of 44 checks.</span></h1>
      <p class="lede">One seeded checkout crash. One patch from Meta's muse-spark-1.3. Every gate it had to clear before anyone would merge it, in order.</p>
      <div class="diff hook-diff">
        <div class="del">-  discount = cast(int, discounts.get(coupon_code))</div>
        <div class="add">+  discount = cast(int, discounts.get(coupon_code, 0))</div>
      </div>
      <p class="swipe">Swipe for the gates</p>`,
  },
  {
    mode: "rupture",
    source: "fixtures/evaluation/adversarial · docs/evidence/2026-10-28-evaluation-deterministic.md",
    body: `
      <h2>An HTTP 201 doesn't mean the order exists.</h2>
      <p class="lede">The usual check for an agent's fix is "replay the request, expect success." This wrong patch passes it. It returns a convincing 201 with an order ID, and never saves the order.</p>
      <div class="diff">
        <div class="ctx">   if coupon_code and coupon_code not in discounts:</div>
        <div class="ctx">       raise HTTPException(status_code=400)</div>
        <div class="add">+  if not coupon_code:</div>
        <div class="add">+      return {"id": str(uuid4()), "line_items": line_items,</div>
        <div class="add">+              "subtotal": subtotal, "discount": 0, ...}</div>
      </div>
      <div class="split">
        <div><p class="k">The status check sees</p><p class="v amber">201 Created</p></div>
        <div><p class="k">The store has</p><p class="v rose">No order</p></div>
      </div>`,
  },
  {
    mode: "rupture",
    source: "docs/evidence/2026-10-28-evaluation-deterministic.md (authored corpus, one checkout route)",
    body: `
      <h2>Six plausible wrong patches. A status check let five through.</h2>
      <table class="patches">
        <thead><tr><th>Wrong patch</th><th>“Returned 201?”</th><th>FaultLine</th><th class="num">Checks failed</th></tr></thead>
        <tbody>
          ${[
            ["zero_all_discounts", true, 4],
            ["null_coupon_only", true, 2],
            ["silence_type_error", false, 6],
            ["drop_coupon_validation", true, 1],
            ["round_percentages", true, 4],
            ["early_return_unsaved", true, 6],
          ]
            .map(
              ([name, naive, failed]) =>
                `<tr><td><code>${name}</code></td><td class="${naive ? "amber" : "dim"}">${naive ? "Accepted" : "Rejected"}</td><td class="rose">Rejected</td><td class="num">${failed} of 27</td></tr>`,
            )
            .join("")}
        </tbody>
      </table>
      <div class="score"><p><b class="amber">5 of 6</b> accepted by the status check</p><p><b class="emerald">0 of 6</b> accepted by FaultLine</p></div>
      <p class="note">Both correct patches were accepted. All three out-of-policy patches were stopped before they ran.</p>`,
  },
  {
    mode: "rupture",
    source: "docs/evidence/2026-11-01-prefilm-verification.json (storefront_seeded_gate) · docs/PREFLIGHT_GATE.md",
    body: `
      <h2>Catch the 500 before <code class="inline">git push</code>.</h2>
      <p class="lede">An agent runs one command before it deploys. A real browser explores the app on its own: no test script, no expected status.</p>
      <pre class="term"><span class="p">$</span> faultline gate http://127.0.0.1:3000
<span class="d">Discovered 30 interactive elements across 3 screens.</span>
<span class="d">Step 8: Clicking Place order -&gt;</span> <span class="r">HTTP 500 on POST /api/checkout</span>

<span class="badge">FAILED · DEPLOYMENT_BLOCKED (exit 1)</span>
<span class="r">Defect intercepted: HTTP 500 on POST /api/checkout
after 7 actions across 3 screens.</span>

<span class="d">Agent remediation prompt: exact reproduction steps,
the server's TypeError, and "re-run until it exits 0".</span></pre>
      <dl class="exits">
        <div><dt>exit 0</dt><dd>Safe to deploy</dd></div>
        <div><dt>exit 1</dt><dd>Deployment blocked</dd></div>
        <div><dt>exit 2</dt><dd>Invalid URL or arguments</dd></div>
      </dl>`,
  },
  {
    mode: "think",
    source: "docs/evidence/2026-10-28-meta-replay-review.md (job 3573b32b, retained replay)",
    body: `
      <h2>Meta's muse-spark-1.3 wrote a one-line fix in 6.9 s.</h2>
      <p class="lede">The model gets the source, the checkout's business contract, and the failure evidence from the browser. It returns a diff, nothing else. FaultLine treats that diff as untrusted input.</p>
      <div class="diff">
        <div class="hunk">@@ -43,7 +43,7 @@  app/routes/checkout.py</div>
        <div class="del">-  discount = cast(int, discounts.get(coupon_code))</div>
        <div class="add">+  discount = cast(int, discounts.get(coupon_code, 0))</div>
        <div class="ctx">   total = subtotal - discount</div>
      </div>
      <blockquote>“Empty/null coupon produced None discount causing TypeError on subtotal-discount. Default missing coupon lookup to 0.”<cite>The model's explanation, verbatim (excerpt)</cite></blockquote>
      <dl class="facts">
        <div><dt>Generation</dt><dd>6.9 s</dd></div>
        <div><dt>Tokens</dt><dd>3,254</dd></div>
        <div><dt>Attempts</dt><dd>1</dd></div>
        <div><dt>Whole job</dt><dd>13.0 s</dd></div>
      </dl>`,
  },
  {
    mode: "hunt",
    source: "README.md (Hermetic Bubblewrap sandboxing; kernel-enforced cgroup v2 limits; Limits)",
    body: `
      <h2>The patch runs where it can't touch anything.</h2>
      <p class="lede">Every candidate gets a fresh worktree and a Bubblewrap sandbox with private user, PID, IPC, network, UTS, and mount namespaces. Code mounts read-only; the environment is emptied.</p>
      <pre class="term small">bwrap --unshare-all --unshare-user --die-with-parent \\
      --new-session --clearenv --cap-drop ALL …</pre>
      <p class="sub">Before anything runs, the cgroup v2 limits are read back from <code class="inline">/sys/fs/cgroup</code>. If they don't match, the run is refused.</p>
      <dl class="cg">
        <div><dt>memory.max</dt><dd>512 MiB</dd></div>
        <div><dt>memory.swap.max</dt><dd>0</dd></div>
        <div><dt>pids.max</dt><dd>64</dd></div>
        <div><dt>cpu.max</dt><dd>1 CPU</dd></div>
      </dl>
      <p class="note">Namespaces and cgroups on a shared kernel. Not a VM, and there's no seccomp filter yet.</p>`,
  },
  {
    mode: "resonance",
    source: "README.md · docs/evidence/2026-10-28-meta-replay-review.md · fixtures/evaluation",
    body: `
      <h2>The model doesn't decide. 44 checks do.</h2>
      <p class="lede">After the sandbox, a real browser repeats the checkout journey and 27 independent HTTP business assertions run against the candidate. The model never sees them in advance.</p>
      <ul class="asserts">
        ${[
          ["regression.tenoff", "TENOFF takes 10% off, rounded down to the cent"],
          ["regression.fifteen", "FIFTEEN takes 15% off, rounded down to the cent"],
          ["regression.empty_coupon", 'coupon_code "": order stored with zero discount'],
          ["regression.mixed_cart_coupon", "Two products with TENOFF: 10% off the whole subtotal"],
          ["regression.quantity_ten", "Quantity 10: correct line total, order stored"],
        ]
          .map(([id, what]) => `<li><code>${id}</code><span>${esc(what)}</span></li>`)
          .join("")}
      </ul>
      <p class="big-result"><b>44 / 44</b> passed for the Meta patch, then cleanup was confirmed.</p>`,
  },
  {
    mode: "resonance",
    source: "docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118/SHA256SUMS · README.md · tools/verify_bundle.py",
    body: `
      <h2>Don't trust us. Re-check the evidence offline.</h2>
      <p class="lede">Each verified job keeps what happened, not a summary of it: screenshots, Playwright traces, request logs, assertion reports, and a SHA-256 checksum manifest.</p>
      <pre class="term"><span class="p">$</span> cd docs/replay/3573b32b-09bd-4f14-897d-cf6dccf9b118
<span class="p">$</span> sha256sum -c SHA256SUMS
<span class="d">artifacts/0ba43aa4-….json:</span> <span class="g">OK</span>
<span class="d">artifacts/1aa2e17b-….zip:</span>  <span class="g">OK</span>
<span class="d">…</span>
<span class="d">job.json:</span> <span class="g">OK</span>          <span class="g">16 of 16 files OK</span></pre>
      <p class="sub">Any job can be re-checked the same way: <code class="inline">tools/verify_bundle.py</code> runs offline. A job is marked verified only after the controller confirms execution identity, artifact hashes, and resource cleanup.</p>
      <p class="note">The digest is a checksum, not a signature: it proves the files agree with each other, not who produced them.</p>`,
  },
  {
    mode: "resonance",
    source: "docs/evidence/2026-10-31-controller-ledger-meta.md (scripts/trial_ledger.py)",
    body: `
      <h2>Then we ran it three more times, live.</h2>
      <p class="lede">Controller ledger, October 31, 2026. Provider meta, model muse-spark-1.3, one registered scenario.</p>
      <table class="ledger">
        <thead><tr><th>Trial</th><th>Job</th><th>Attempt</th><th>Checks</th><th>Wall time</th></tr></thead>
        <tbody>
          <tr><td>1</td><td><code>165e0b18</code></td><td>1st</td><td class="emerald">44/44</td><td>10.5 s</td></tr>
          <tr><td>2</td><td><code>196cc3b6</code></td><td>1st</td><td class="emerald">44/44</td><td>12.6 s</td></tr>
          <tr><td>3</td><td><code>5fb3c393</code></td><td>1st</td><td class="emerald">44/44</td><td>10.4 s</td></tr>
        </tbody>
      </table>
      <div class="score"><p><b class="emerald">3 of 3</b> verified on the first attempt</p><p><b>10.5 s</b> median, job created to verified</p></div>
      <p class="note">One scenario. This doesn't measure other defects or arbitrary apps, and a verified candidate is not a deployment.</p>`,
  },
  {
    mode: "shift",
    source: "github.com/FrankieBiz/Faultline",
    body: `
      <h2 class="cta">Try to fool the gates yourself.</h2>
      <p class="lede">The judge page replays the Meta repair and lets you pick any of the eleven patches. It runs in any browser; nothing to install.</p>
      <div class="links">
        <p><span>Judge page</span>frankiebiz.github.io/Faultline</p>
        <p><span>Source</span>github.com/FrankieBiz/Faultline</p>
      </div>
      <pre class="term small"><span class="p">$</span> ./faultline gate http://localhost:3000</pre>
      <p class="sub">Tell us which assertion is too weak.</p>
      <p class="note">Built for the Meta AI Developer Hackathon.</p>`,
  },
];

const css = `
  :root {
    --bg: #07080a; --well: #0e1014; --raised: #14171d; --line: #232733;
    --ink: #f2f3f5; --ink-2: #a9aeb8; --ink-3: #6d7380;
    --rose: #ff4d6a; --amber: #f59e0b; --cyan: #2dd4ff; --emerald: #3dffa2; --gold: #f3c969;
    --sans: "Inter", "Inter Variable", "Helvetica Neue", Arial, sans-serif;
    --display: "Inter Display", "Inter", "Helvetica Neue", Arial, sans-serif;
    --mono: "JetBrainsMono Nerd Font Mono", "JetBrains Mono", "Source Code Pro", ui-monospace, monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  @page { size: ${W}px ${H}px; margin: 0; }
  html, body { background: var(--bg); }
  body { font-family: var(--sans); color: var(--ink); -webkit-font-smoothing: antialiased; font-feature-settings: "ss01", "cv11"; }
  .slide {
    position: relative; width: ${W}px; height: ${H}px; overflow: hidden; break-after: page;
    background:
      radial-gradient(circle at 1px 1px, rgba(255,255,255,0.045) 1px, transparent 0) 0 0 / 24px 24px,
      var(--bg);
    display: flex; flex-direction: column;
  }
  .seis { display: block; width: 100%; height: 120px; margin-top: 56px; flex: none; }
  .seis path { fill: none; stroke-width: 3; stroke-linejoin: round; filter: drop-shadow(0 0 8px currentColor); }
  .content { flex: 1; padding: 44px 88px 0; display: flex; flex-direction: column; gap: 34px; }
  footer {
    flex: none; display: flex; justify-content: space-between; align-items: flex-end; gap: 40px;
    padding: 0 88px 64px; color: var(--ink-3); font-size: 19px; line-height: 1.4;
  }
  footer .brand { color: var(--ink); font-weight: 700; font-size: 24px; letter-spacing: -0.01em; display: flex; align-items: center; gap: 12px; white-space: nowrap; }
  footer .brand i { width: 16px; height: 22px; background: linear-gradient(135deg, var(--rose) 50%, var(--emerald) 50%); transform: skewX(-12deg); }
  footer .src { flex: 1; font-family: var(--mono); font-size: 16px; }
  footer .page { font-variant-numeric: tabular-nums; white-space: nowrap; }

  h1, h2 { font-family: var(--display); font-weight: 700; letter-spacing: -0.028em; line-height: 1.04; text-wrap: balance; }
  h1.hook { font-size: 92px; }
  h1.hook span { display: block; margin-top: 26px; color: var(--ink-2); font-size: 62px; font-weight: 600; line-height: 1.1; }
  h2 { font-size: 70px; }
  h2.cta { font-size: 96px; }
  .lede { font-size: 30px; line-height: 1.42; color: var(--ink-2); max-width: 880px; }
  .sub { font-size: 27px; line-height: 1.42; color: var(--ink); max-width: 880px; }
  .note { font-size: 23px; line-height: 1.45; color: var(--ink-3); max-width: 880px; margin-top: auto; padding-bottom: 36px; }
  .swipe { margin-top: auto; padding-bottom: 36px; font-size: 28px; font-weight: 600; color: var(--gold); }
  .nw { white-space: nowrap; }
  code, .inline { font-family: var(--mono); font-size: 0.9em; }
  h2 code.inline { color: var(--cyan); font-size: 0.86em; font-weight: 600; letter-spacing: -0.04em; }
  .amber { color: var(--amber); } .rose { color: var(--rose); } .emerald { color: var(--emerald); } .dim { color: var(--ink-3); }

  .diff { font-family: var(--mono); font-size: 22px; line-height: 1.75; background: var(--well); border: 1px solid var(--line); border-radius: 14px; padding: 18px 0; overflow: hidden; }
  .diff div { padding: 0 26px; white-space: pre; }
  .diff .del { background: rgba(255, 77, 106, 0.12); color: #ff9aac; }
  .diff .add { background: rgba(61, 255, 162, 0.10); color: #9dffd0; }
  .diff .ctx { color: var(--ink-3); }
  .diff .hunk { color: var(--ink-3); padding-bottom: 6px; }
  .hook-diff { font-size: 24px; margin-top: 10px; }

  .split { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--line); }
  .split > div { padding: 26px 0 0; }
  .split > div + div { padding-left: 36px; border-left: 1px solid var(--line); }
  .k { font-size: 24px; color: var(--ink-3); }
  .v { font-family: var(--display); font-size: 64px; font-weight: 700; letter-spacing: -0.03em; margin-top: 6px; }

  table { width: 100%; border-collapse: collapse; font-size: 25px; }
  th { text-align: left; font-weight: 500; color: var(--ink-3); font-size: 21px; padding: 0 0 14px; border-bottom: 1px solid var(--line); }
  td { padding: 12px 0; border-bottom: 1px solid var(--line); vertical-align: baseline; }
  td code { font-size: 23px; color: var(--ink); }
  td span { display: block; font-size: 19px; color: var(--ink-3); margin-top: 3px; }
  .patches td:first-child { width: 44%; }
  .patches .num { text-align: right; color: var(--ink-3); font-variant-numeric: tabular-nums; }
  .ledger td { font-size: 28px; font-variant-numeric: tabular-nums; }
  .ledger td code { font-size: 25px; }

  .score { display: flex; gap: 56px; }
  .score p { font-size: 24px; color: var(--ink-2); line-height: 1.3; max-width: 400px; }
  .score b { display: block; font-family: var(--display); font-size: 76px; letter-spacing: -0.03em; color: var(--ink); line-height: 1.05; }
  .score b.amber { color: var(--amber); } .score b.emerald { color: var(--emerald); }

  .term { font-family: var(--mono); font-size: 22px; line-height: 1.6; background: #0b0d11; border: 1px solid var(--line); border-radius: 14px; padding: 26px 30px; color: var(--ink); white-space: pre; overflow: hidden; }
  .term.small { font-size: 21px; padding: 20px 28px; }
  .term .p { color: var(--cyan); } .term .d { color: var(--ink-3); } .term .r { color: var(--rose); font-weight: 700; } .term .g { color: var(--emerald); }
  .term .badge { display: inline-block; color: var(--rose); font-weight: 700; border: 1px solid rgba(255,77,106,0.5); background: rgba(255,77,106,0.12); border-radius: 6px; padding: 0 12px; }

  dl.exits { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; border-top: 1px solid var(--line); }
  dl.exits div { padding-top: 20px; }
  dl.exits dt { font-family: var(--mono); font-size: 24px; color: var(--ink); }
  dl.exits div:nth-child(1) dt { color: var(--emerald); } dl.exits div:nth-child(2) dt { color: var(--rose); }
  dl.exits dd { font-size: 22px; color: var(--ink-2); margin-top: 6px; }

  blockquote { font-size: 27px; line-height: 1.45; color: var(--ink); border-left: 4px solid var(--amber); padding-left: 26px; max-width: 880px; }
  blockquote cite { display: block; font-style: normal; font-size: 20px; color: var(--ink-3); margin-top: 10px; }
  dl.facts, dl.cg { display: grid; grid-template-columns: repeat(4, 1fr); border-top: 1px solid var(--line); }
  dl.facts div, dl.cg div { padding-top: 20px; }
  dl.facts dt, dl.cg dt { font-size: 21px; color: var(--ink-3); }
  dl.cg dt { font-family: var(--mono); font-size: 19px; }
  dl.facts dd, dl.cg dd { font-family: var(--display); font-weight: 700; font-size: 46px; letter-spacing: -0.02em; margin-top: 4px; }
  dl.cg dd { color: var(--cyan); }

  ul.asserts { list-style: none; border-top: 1px solid var(--line); }
  ul.asserts li { display: grid; grid-template-columns: 390px 1fr; gap: 20px; padding: 11px 0; border-bottom: 1px solid var(--line); align-items: baseline; }
  ul.asserts code { color: var(--emerald); font-size: 20px; }
  ul.asserts span { font-size: 22px; color: var(--ink-2); line-height: 1.35; }
  .big-result { font-size: 28px; color: var(--ink-2); display: flex; align-items: baseline; gap: 24px; }
  .big-result b { font-family: var(--display); font-size: 84px; color: var(--emerald); letter-spacing: -0.03em; flex: none; }

  .links { display: grid; gap: 22px; border-top: 1px solid var(--line); padding-top: 28px; }
  .links p { font-family: var(--mono); font-size: 36px; color: var(--ink); }
  .links span { display: block; font-family: var(--sans); font-size: 22px; color: var(--gold); margin-bottom: 4px; }
`;

const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>FaultLine carousel</title><style>${css}</style></head><body>
${slides
  .map(
    (s, i) => `<section class="slide" id="slide-${i + 1}">
  ${seismo(s.mode)}
  <div class="content">${s.body.replace(/muse-spark-1\.3/g, '<span class="nw">muse-spark-1.3</span>')}</div>
  <footer><span class="brand"><i></i>FaultLine</span><span class="src">Source: ${esc(s.source)}</span><span class="page">${i + 1} / ${slides.length}</span></footer>
</section>`,
  )
  .join("\n")}
</body></html>`;

await mkdir(OUT, { recursive: true });
await writeFile(path.join(OUT, "carousel.html"), html);

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);

  // Fail loudly if any slide's content runs past its frame instead of shipping a clipped slide.
  const overflow = await page.evaluate(() =>
    [...document.querySelectorAll(".slide")].flatMap((slide, i) => {
      const content = slide.querySelector(".content");
      const footer = slide.querySelector("footer").getBoundingClientRect();
      const bottom = Math.max(...[...content.children].map((el) => el.getBoundingClientRect().bottom));
      return bottom > footer.top + 1 || footer.bottom > slide.getBoundingClientRect().bottom + 1 ? [i + 1] : [];
    }),
  );
  if (overflow.length) throw new Error(`Content overflows the footer on slide(s) ${overflow.join(", ")}`);

  for (let i = 0; i < slides.length; i++) {
    const file = path.join(OUT, `slide-${String(i + 1).padStart(2, "0")}.png`);
    await page.locator(`#slide-${i + 1}`).screenshot({ path: file });
    console.log(`  ${path.relative(ROOT, file)}`);
  }
  const pdf = path.join(OUT, "faultline-carousel.pdf");
  await page.pdf({ path: pdf, width: `${W}px`, height: `${H}px`, printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  console.log(`  ${path.relative(ROOT, pdf)} (${slides.length} pages)`);
} finally {
  await browser.close();
}
