// Trusted JSON-lines driver. Assertions stay in the Python controller, outside
// the candidate namespace. Only this loopback origin may receive browser traffic.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(pathToFileURL(process.argv[2]).href);
const origin = process.argv[3];
const output = process.argv[4];
const browser = await chromium.launch({ headless: true, chromiumSandbox: true });
process.once("SIGTERM", async () => { await browser.close(); process.exit(143); });
const context = await browser.newContext({ serviceWorkers: 'block' });
await context.route('**/*', route => {
  const url = new URL(route.request().url());
  return url.origin === origin ? route.continue() : route.abort('blockedbyclient');
});
await context.routeWebSocket('**/*', ws => ws.close());
await context.tracing.start({ screenshots: true, snapshots: true });
const page = await context.newPage();
const requests = [];
page.on('request', req => {
  if (requests.length < 32) requests.push({ method: req.method(), url: req.url().slice(0, 256) });
});
console.log(JSON.stringify({ ready: true }));
try {
  for await (const line of createInterface({ input: process.stdin })) {
    const s = JSON.parse(line);
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
          const bytes = await response.body();
          if (bytes.length > 65536) throw new Error('response_limit');
          let value = bytes.toString('utf8');
          try { value = JSON.parse(value); } catch {}
          result = { value, status: response.status() };
          requests.push({ method: s.method, url: (origin + s.path).slice(0, 256), status: response.status() });
          await response.dispose();
          break;
        }
        case 'capture': {
          if (s.kind === 'screenshot') result = { bytes: (await page.screenshot({ ...options, type: 'png' })).toString('base64') };
          else if (s.kind === 'url') result = { value: page.url() };
          else if (s.kind === 'visible') result = { value: await page.locator(s.selector).isVisible() };
          else if (s.kind === 'value') result = { value: await page.locator(s.selector).inputValue(options) };
          else result = { value: await page.locator(s.selector).innerText(options) };
          break;
        }
        case 'finish': {
          const { writeFile } = await import('node:fs/promises');
          await page.screenshot({ path: output + '/screenshot.png', timeout: 3000 });
          await context.tracing.stop({ path: output + '/trace.zip' });
          await writeFile(output + '/requests.json', JSON.stringify(requests.slice(0, 32)));
          break;
        }
        default: throw new Error('unknown_step');
      }
      const encoded = JSON.stringify({ result });
      if (encoded.length > 1024 * 1024) throw new Error('measurement_limit');
      console.log(encoded);
      if (s.action === 'finish') break;
    } catch {
      console.log(JSON.stringify({ error: 'browser_step_failed' }));
    }
  }
} finally {
  await browser.close();
}
