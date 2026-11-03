// Trusted JSON-lines driver. Assertions stay in the Python controller, outside
// the candidate namespace. Only this loopback origin may receive browser traffic.
import { once } from 'node:events';
import { createReadStream } from 'node:fs';
import { stat, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(pathToFileURL(process.argv[2]).href);
const origin = process.argv[3];
const output = process.argv[4];
const streamArtifacts = process.argv[5] === '--stream-artifacts';
const measurementLimit = 65536;
const artifactLimits = { 'screenshot.png': 10 * 1024 * 1024, 'trace.zip': 25 * 1024 * 1024, 'requests.json': 16384 };
const viewport = { width: 1280, height: 720 };

async function send(value) {
  const encoded = JSON.stringify(value) + '\n';
  if (Buffer.byteLength(encoded) > 1024 * 1024) throw new Error('measurement_limit');
  if (!process.stdout.write(encoded)) await once(process.stdout, 'drain');
}

// readline accumulates an entire line before yielding it. Bound the input while
// reading, before JSON.parse/stringify can allocate based on a huge script/body.
async function* commands() {
  let pending = Buffer.alloc(0);
  for await (const chunk of process.stdin) {
    let offset = 0;
    while (offset < chunk.length) {
      const newline = chunk.indexOf(10, offset);
      const end = newline < 0 ? chunk.length : newline;
      if (pending.length + end - offset > measurementLimit) throw new Error('command_limit');
      pending = Buffer.concat([pending, chunk.subarray(offset, end)]);
      if (newline < 0) break;
      yield JSON.parse(pending.toString('utf8'));
      pending = Buffer.alloc(0);
      offset = newline + 1;
    }
  }
  if (pending.length) throw new Error('incomplete_command');
}

async function exportArtifacts() {
  for (const [name, limit] of Object.entries(artifactLimits)) {
    const path = output + '/' + name;
    if ((await stat(path)).size > limit) throw new Error('artifact_limit');
    if (streamArtifacts) {
      let size = 0;
      for await (const chunk of createReadStream(path, { highWaterMark: 48 * 1024 })) {
        size += chunk.length;
        if (size > limit) throw new Error('artifact_limit');
        await send({ artifact: name, data: chunk.toString('base64') });
      }
    }
  }
}

const launchOptions = {
  headless: true,
  chromiumSandbox: true,
  args: [
    '--disable-webrtc',
    '--webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--disable-features=WebRtcHideLocalIpsWithMdns,WebRTC',
    '--js-flags=--max-old-space-size=128',
  ],
};
let browser;
try {
  // Prefer full Chromium: the headless shell may ignore WebRTC preferences.
  browser = await chromium.launch({ ...launchOptions, channel: 'chromium' });
} catch {
  // The default headless shell does not enforce the same network policy.
  // Require full Chromium on fallback too; never retry with weaker isolation.
  try {
    browser = await chromium.launch({ ...launchOptions, executablePath: chromium.executablePath() });
  } catch (cause) {
    throw new Error('sandboxed_browser_isolation_unavailable', { cause });
  }
}
process.once('SIGTERM', async () => { await browser.close(); process.exit(143); });
if (origin === '--preflight') {
  await browser.close();
  await send({ ready: true });
  process.exit(0);
}
const context = await browser.newContext({ serviceWorkers: 'block', viewport, deviceScaleFactor: 1 });
await context.route('**/*', route => {
  const url = new URL(route.request().url());
  return url.origin === origin ? route.continue() : route.abort('blockedbyclient');
});
await context.routeWebSocket('**/*', ws => ws.close());
await context.tracing.start({ screenshots: true, snapshots: true });
const page = await context.newPage();
const requests = [];
function recordRequest(value) { if (requests.length < 32) requests.push(value); }
page.on('request', req => recordRequest({ method: req.method().slice(0, 16), url: req.url().slice(0, 256) }));
async function screenshot(options) {
  // Fixed pixel dimensions bound the encoder allocation even for enormous DOMs.
  const bytes = await page.screenshot({ ...options, type: 'png', fullPage: false,
    scale: 'css', clip: { x: 0, y: 0, ...viewport } });
  if (bytes.length > artifactLimits['screenshot.png']) throw new Error('screenshot_limit');
  return bytes;
}
await send({ ready: true });
try {
  for await (const s of commands()) {
    let result = null;
    try {
      const options = { timeout: s.timeout_ms };
      switch (s.action) {
        case 'navigate': await page.goto(origin + s.path, { ...options, waitUntil: 'domcontentloaded' }); break;
        case 'fill': await page.locator(s.selector).fill(s.value, options); break;
        case 'click': await page.locator(s.selector).click(options); break;
        case 'select': await page.locator(s.selector).selectOption(s.value, options); break;
        case 'wait_for': await page.locator(s.selector).waitFor({ ...options, state: s.state }); break;
        case 'request': {
          const response = await context.request.fetch(origin + s.path, {
            ...options, method: s.method, maxRedirects: 0, failOnStatusCode: false,
            headers: { ...(Object.hasOwn(s, 'body') ? { 'content-type': 'application/json' } : {}), ...s.headers },
            ...(Object.hasOwn(s, 'body') ? { data: JSON.stringify(s.body) } : {}),
          });
          try {
            // The controller's streaming HTTP bridge caps the body before this
            // Playwright buffer is created; keep the independent acceptance cap.
            const bytes = await response.body();
            if (bytes.length > measurementLimit) throw new Error('response_limit');
            let value = bytes.toString('utf8');
            try { value = JSON.parse(value); } catch {}
            result = { value, status: response.status() };
            recordRequest({ method: s.method, url: (origin + s.path).slice(0, 256), status: response.status() });
          } finally { await response.dispose(); }
          break;
        }
        case 'capture': {
          if (s.kind === 'screenshot') {
            const bytes = await screenshot(options);
            if (bytes.length > 512 * 1024) throw new Error('measurement_limit');
            result = { bytes: bytes.toString('base64') };
          } else if (s.kind === 'url') {
            const value = page.url();
            if (value.length > measurementLimit) throw new Error('measurement_limit');
            result = { value };
          } else if (s.kind === 'visible') result = { value: await page.locator(s.selector).isVisible() };
          else {
            // Reject inside the bounded renderer, before Playwright serializes
            // the DOM string into protocol buffers in the host Node process.
            result = { value: await page.locator(s.selector).evaluate((element, { kind, limit }) => {
              const value = kind === 'value' ? element.value : element.innerText;
              if (typeof value !== 'string' || value.length > limit) throw new Error('measurement_limit');
              return value;
            }, { kind: s.kind, limit: measurementLimit }, options) };
          }
          break;
        }
        case 'finish': {
          await screenshot({ path: output + '/screenshot.png', timeout: 3000 });
          await context.tracing.stop({ path: output + '/trace.zip' });
          await writeFile(output + '/requests.json', JSON.stringify(requests));
          await exportArtifacts();
          break;
        }
        default: throw new Error('unknown_step');
      }
      await send({ result });
      if (s.action === 'finish') break;
    } catch {
      await send({ error: 'browser_step_failed' });
    }
  }
} finally {
  await browser.close();
}
