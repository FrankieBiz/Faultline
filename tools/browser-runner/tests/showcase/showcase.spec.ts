import { resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * The judge page, docs/index.html, driven by keyboard and pointer. Every request to the page's
 * origin is answered from docs/ on disk, so no server runs, and the live repair service is
 * mocked per test. Web Audio is replaced by a recorder whose autoplay behavior each test picks.
 */
const DOCS = resolve(fileURLToPath(import.meta.url), "../../../../../docs");
const LIVE = "http://127.0.0.1:4600";
const INK = "rgb(236, 238, 241)";
const RUN_ID = "5b0e7c1a-2f4d-4c8e-9a61-0d3f2b7e9c44";

type AudioMode = "running" | "autoplay-blocked" | "resume-rejects" | "constructor-throws" | "absent";
interface AudioRecord { contexts: { state: string; resumes: number }[]; oscillators: string[] }

/** Opens the page and returns every uncaught error and console error it raises. */
async function open(page: Page, path = "/"): Promise<string[]> {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.context().route("http://127.0.0.1:4500/**", (route) => {
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    const file = resolve(DOCS, "." + (pathname.endsWith("/") ? pathname + "index.html" : pathname));
    return file.startsWith(DOCS + sep) ? route.fulfill({ path: file }) : route.fulfill({ status: 404 });
  });
  await page.addInitScript(() => {
    // A recording clipboard: what the page wrote, and a switch for a browser that refuses.
    const clip = { writes: [] as string[], refuse: false };
    Object.assign(window, { __clipboard: clip });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text: string) => {
        if (clip.refuse) throw new DOMException("Write permission denied.", "NotAllowedError");
        clip.writes.push(text);
      } },
    });
  });
  await page.goto(path);
  return errors;
}

/**
 * Replaces Web Audio with a recorder. As in a real browser, user activation comes only from a pointer
 * or key event (Playwright's evaluations would otherwise count as gestures), and `mode` decides how
 * the autoplay policy treats a new context.
 */
async function fakeAudio(page: Page, mode: AudioMode, stored?: "on" | "off"): Promise<void> {
  await page.addInitScript(({ mode, stored }) => {
    if (stored) localStorage.setItem("faultline.sound", stored);
    const flags = { active: false };
    for (const type of ["pointerdown", "keydown"]) addEventListener(type, () => { flags.active = true; }, true);
    Object.defineProperty(navigator, "userActivation", {
      configurable: true,
      value: { get hasBeenActive() { return flags.active; }, get isActive() { return flags.active; } },
    });
    const record: AudioRecord = { contexts: [], oscillators: [] };
    Object.assign(window, { __audio: record });
    const scope = window as unknown as Record<string, unknown>;
    if (mode === "absent") {
      delete scope.AudioContext;
      delete scope.webkitAudioContext;
      return;
    }
    const param = () => ({ value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} });
    const connectable = <T extends object>(node: T) => Object.assign(node, { connect: (target: unknown) => target });
    class RecordingAudioContext {
      readonly entry = { state: mode === "running" ? "running" : "suspended", resumes: 0 };
      readonly destination = connectable({});
      readonly currentTime = 0;
      constructor() {
        if (mode === "constructor-throws") throw new DOMException("No audio output device.", "NotSupportedError");
        record.contexts.push(this.entry);
      }
      get state() { return this.entry.state; }
      resume(): Promise<void> {
        this.entry.resumes += 1;
        if (this.entry.state === "closed") return Promise.reject(new DOMException("Closed.", "InvalidStateError"));
        if (mode === "resume-rejects") return Promise.reject(new DOMException("Autoplay is not allowed.", "NotAllowedError"));
        // The autoplay policy holds the context suspended until some later gesture.
        if (mode === "autoplay-blocked") return new Promise<void>(() => {});
        this.entry.state = "running";
        return Promise.resolve();
      }
      close(): Promise<void> {
        this.entry.state = "closed";
        return Promise.resolve();
      }
      createGain() { return connectable({ gain: param() }); }
      createBiquadFilter() { return connectable({ type: "lowpass", Q: param(), frequency: param() }); }
      createOscillator() {
        return connectable({ type: "sine", frequency: param(), start(this: { type: string }) { record.oscillators.push(this.type); }, stop() {} });
      }
    }
    Object.defineProperty(window, "AudioContext", { configurable: true, writable: true, value: RecordingAudioContext });
  }, { mode, stored });
}

const audio = (page: Page) => page.evaluate(() => {
  const record = (window as unknown as { __audio: AudioRecord }).__audio;
  return { contexts: record.contexts.map((c) => c.state), oscillators: record.oscillators.splice(0) };
});
const RESOLVE = ["triangle", "triangle", "triangle", "sine"];
const CATASTROPHE = ["sawtooth", "sawtooth", "square", "sawtooth", "sawtooth", "square"];

/** WCAG relative luminance contrast between two computed `rgb()` colors. */
function contrast(a: string, b: string): number {
  const luminance = (color: string) => {
    const [r = 0, g = 0, bl = 0] = (color.match(/\d+(\.\d+)?/g) ?? []).map(Number).map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** Focuses a control from the keyboard's side and returns the ring drawn on `ringOn` (the control itself by default). */
async function ring(control: Locator, ringOn: Locator = control) {
  await control.focus();
  await expect(control).toBeFocused();
  return ringOn.evaluate((node, owner) => {
    const style = getComputedStyle(node);
    return {
      visible: (owner ? node.querySelector("input") ?? node : node).matches(":focus-visible"),
      style: style.outlineStyle,
      width: style.outlineWidth,
      color: style.outlineColor,
    };
  }, ringOn !== control);
}

test.describe("keyboard focus", () => {
  test("every kind of control draws the same high-contrast ring, including a focused current journey step", async ({ page }) => {
    await fakeAudio(page, "running");
    const errors = await open(page);
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();

    const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const patch = page.getByRole("radio", { name: /^zero_all_discounts/ });
    const controls: [string, Locator, Locator?][] = [
      ["skip link", skip],
      ["section link", page.getByRole("navigation", { name: "Sections" }).getByRole("link", { name: "Meta repair" })],
      ["sound toggle", page.getByRole("button", { name: "Sound cues" })],
      ["hero call to action", page.getByRole("button", { name: "Play the recorded Meta repair" })],
      ["tour step", page.getByRole("link", { name: /Block a broken deploy/ })],
      ["gate run pill", page.getByRole("button", { name: /Test Broken Site/ })],
      ["integration tab", page.getByRole("tab", { name: "Cursor / Claude Code" })],
      ["snippet copy", page.getByRole("button", { name: "Copy Cursor / Claude Code" })],
      ["player button", page.getByRole("button", { name: "Play the recorded run" })],
      ["journey node", page.getByRole("list", { name: /Recorded journey/ }).getByRole("button", { name: "HTTP 500" })],
      ["patch option", patch, page.locator("label.option", { has: patch })],
      ["fallback button", page.getByRole("button", { name: "Play the recorded Meta run instead" })],
      ["command copy", page.getByRole("button", { name: "Copy", exact: true })],
    ];
    for (const [name, control, ringOn] of controls) {
      const drawn = await ring(control, ringOn);
      expect(drawn, name).toEqual({ visible: true, style: "solid", width: "2px", color: INK });
      expect(contrast(drawn.color, background), name).toBeGreaterThanOrEqual(3);
    }

    // Selecting a journey step marks it current with a thin cyan rule; the keyboard ring must still win.
    const node = page.getByRole("list", { name: /Recorded journey/ }).getByRole("button", { name: "HTTP 500" });
    await node.focus();
    await page.keyboard.press("Enter");
    await expect(node).toHaveAttribute("aria-current", "step");
    expect(await ring(node)).toEqual({ visible: true, style: "solid", width: "2px", color: INK });
    expect(errors).toEqual([]);
  });

  test("a focused tour card shows the same cue as hover, and the selected patch keeps a 3:1 rim", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors = await open(page);
    const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const tour = page.getByRole("link", { name: /Block a broken deploy/ });
    const badge = () => tour.evaluate((node) => getComputedStyle(node, "::before").backgroundColor);
    const resting = await badge();
    await tour.focus();
    await expect(tour).toBeFocused();
    expect(await tour.evaluate((node) => node.matches(":focus-visible"))).toBe(true);
    expect(await badge()).not.toBe(resting);
    expect(await badge()).toBe(INK);

    // The checked patch is told apart by a rim, not only by a slightly lighter fill.
    const checked = page.locator("label.option", { has: page.getByRole("radio", { name: /^null_coupon_only/ }) });
    await expect(checked.getByRole("radio")).toBeChecked();
    const rim = await checked.evaluate((node) => getComputedStyle(node).borderTopColor);
    expect(contrast(rim, background)).toBeGreaterThanOrEqual(3);
    const unchecked = page.locator("label.option", { has: page.getByRole("radio", { name: /^silence_type_error/ }) });
    expect(await unchecked.evaluate((node) => getComputedStyle(node).borderTopColor)).not.toBe(rim);
    expect(errors).toEqual([]);
  });

  test("the integration tabs are one tab stop with arrow, Home, and End keys", async ({ page }) => {
    const errors = await open(page);
    const tabs = page.getByRole("tablist", { name: "Integrations" }).getByRole("tab");
    const panel = page.getByRole("tabpanel");
    const copy = page.locator("#gate-copy");
    await expect(tabs).toHaveCount(4);
    const names = await tabs.allTextContents();
    expect(names).toEqual(["Cursor / Claude Code", "GitHub Actions CI/CD", "CLI Pre-Flight", "Agent Skill"]);

    const expectSelected = async (index: number) => {
      for (let i = 0; i < names.length; i += 1) {
        await expect(tabs.nth(i)).toHaveAttribute("aria-selected", String(i === index));
        await expect(tabs.nth(i)).toHaveAttribute("tabindex", i === index ? "0" : "-1");
      }
      await expect(tabs.nth(index)).toBeFocused();
      await expect(panel).toHaveAccessibleName(names[index]!);
      await expect(copy).toHaveAccessibleName(`Copy ${names[index]}`);
    };

    await tabs.first().focus();
    await expectSelected(0);
    await page.keyboard.press("ArrowRight");
    await expectSelected(1);
    await expect(page.locator("#gate-file")).toHaveText(".github/workflows/faultline-gate.yml");
    await page.keyboard.press("End");
    await expectSelected(3);
    await page.keyboard.press("ArrowRight");
    await expectSelected(0);
    await page.keyboard.press("ArrowLeft");
    await expectSelected(3);
    await page.keyboard.press("Home");
    await expectSelected(0);

    // Tab leaves the tablist for the panel's copy button instead of walking every tab.
    await page.keyboard.press("Tab");
    await expect(copy).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(tabs.first()).toBeFocused();
    expect(errors).toEqual([]);
  });

  test("gate runs, the payload format, journey steps, and patches all work from the keyboard", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors = await open(page);
    const clean = page.getByRole("button", { name: /Test Clean Site/ });
    const broken = page.getByRole("button", { name: /Test Broken Site/ });
    await expect(clean).toHaveAttribute("aria-pressed", "false");
    await expect(broken).toHaveAttribute("aria-pressed", "false");

    await broken.focus();
    await page.keyboard.press("Enter");
    await expect(broken).toHaveAttribute("aria-pressed", "true");
    await expect(clean).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("#gate-verdict")).toContainText("Verdict: Deployment blocked");

    const format = page.getByRole("group", { name: "Payload format" });
    const prompt = format.getByRole("button", { name: "Prompt" });
    const json = format.getByRole("button", { name: "JSON" });
    await expect(prompt).toHaveAttribute("aria-pressed", "true");
    await json.focus();
    await page.keyboard.press("Space");
    await expect(json).toHaveAttribute("aria-pressed", "true");
    await expect(prompt).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByRole("button", { name: "Copy the JSON verdict" })).toBeVisible();
    await expect(page.locator(".gate-payload pre")).toContainText('"verdict": "DEPLOYMENT_BLOCKED"');

    await clean.focus();
    await page.keyboard.press("Space");
    await expect(clean).toHaveAttribute("aria-pressed", "true");
    await expect(broken).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("#gate-verdict")).toContainText("Verdict: Safe to deploy");

    const node = page.getByRole("list", { name: /Recorded journey/ }).getByRole("button", { name: "Meta muse-spark-1.3" });
    await node.focus();
    await page.keyboard.press("Enter");
    await expect(node).toHaveAttribute("aria-current", "step");
    await expect(page.locator("#recorded-announce")).toContainText("Meta muse-spark-1.3: The one-line patch");

    // The picker opens on null_coupon_only; arrows move the choice and the detail follows.
    const current = page.getByRole("radio", { name: /^null_coupon_only/ });
    await expect(current).toBeChecked();
    await current.focus();
    await page.keyboard.press("ArrowDown");
    const next = page.getByRole("radio", { name: /^silence_type_error/ });
    await expect(next).toBeFocused();
    await expect(next).toBeChecked();
    await expect(page.locator("#detail h3")).toHaveText("Catch the TypeError and keep a null discount");
    expect(errors).toEqual([]);
  });

  test("the first Tab reveals a skip link that moves focus into main, past the banner", async ({ page }) => {
    const errors = await open(page);
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).not.toBeInViewport();
    await page.keyboard.press("Tab");
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await expect(skip).toHaveAttribute("href", "#main-content");
    await page.keyboard.press("Enter");
    const main = page.getByRole("main");
    await expect(main).toBeFocused();
    await expect(main).toHaveAttribute("id", "main-content");
    expect(new URL(page.url()).hash).toBe("#main-content");
    // The next Tab lands inside main, never back in the banner's section links.
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest("main")))).toBe(true);
    expect(await page.evaluate(() => Boolean(document.activeElement?.closest("header")))).toBe(false);
    expect(errors).toEqual([]);
  });

  test("the recorded journey ribbon takes Tab and Arrow keys, and picking a step keeps focus on it", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors = await open(page);
    const nodes = page.getByRole("list", { name: /Recorded journey/ }).getByRole("button");
    await expect(nodes).toHaveCount(8);
    // Tab walks every node in order.
    await nodes.first().focus();
    for (let i = 1; i < 8; i++) {
      await page.keyboard.press("Tab");
      await expect(nodes.nth(i)).toBeFocused();
    }
    // Arrows move one node at a time and wrap; Home and End jump to the ends.
    await page.keyboard.press("ArrowRight");
    await expect(nodes.first()).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(nodes.last()).toBeFocused();
    await page.keyboard.press("Home");
    await expect(nodes.first()).toBeFocused();
    for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
    const rupture = nodes.nth(4);
    await expect(rupture).toHaveAccessibleName("HTTP 500");
    await expect(rupture).toBeFocused();
    // Enter scrolls the evidence into view but leaves focus on the node.
    await page.keyboard.press("Enter");
    await expect(rupture).toHaveAttribute("aria-current", "step");
    await expect(rupture).toBeFocused();
    await expect(page.locator("#side-before")).toHaveAttribute("data-focus", "");
    await page.keyboard.press("End");
    await expect(nodes.last()).toBeFocused();
    expect(errors).toEqual([]);
  });
});

test.describe("landmarks", () => {
  test("one banner, one main, one contentinfo, with named navigation and a complementary repair core", async ({ page }) => {
    const errors = await open(page);
    await expect(page.getByRole("banner")).toHaveCount(1);
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.getByRole("contentinfo")).toHaveCount(1);
    await expect(page.getByRole("banner").getByRole("navigation", { name: "Sections" })).toBeVisible();
    await expect(page.getByRole("main").getByRole("navigation", { name: "The 3-minute judging tour" })).toBeVisible();
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "README" })).toBeVisible();
    const core = page.getByRole("complementary");
    await expect(core).toHaveCount(1);
    await expect(core).toHaveAccessibleName("Repair core: Meta Model API");
    await expect(page.getByRole("main").getByRole("complementary", { name: "Repair core: Meta Model API" })).toBeVisible();
    // Landmarks sit side by side under body, never nested, and the skip link comes before them all.
    expect(await page.evaluate(() => {
      const pick = (selector: string) => document.querySelector(selector)!;
      const [skip, banner, main, info] = [pick("a.skip"), pick("header[role=banner]"), pick("main"), pick("footer[role=contentinfo]")];
      const before = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
      return [[skip, banner, main, info].every((node) => node.parentElement === document.body),
        document.body.querySelector("a, button, input, [tabindex]") === skip,
        before(skip, banner), before(banner, main), before(main, info)];
    })).toEqual([true, true, true, true, true]);
    // Every in-page link that targets main still resolves after the rename.
    expect(await page.evaluate(() => [...document.querySelectorAll("a[href^='#']")]
      .map((a) => a.getAttribute("href")!.slice(1)).filter((id) => id && !document.getElementById(id)))).toEqual([]);
    expect(errors).toEqual([]);
  });
});

test.describe("pointer and copy feedback", () => {
  test("every kind of control shows a pressed state while held", async ({ page }) => {
    // Reduced motion removes transitions, so the pressed style is read exactly, not mid-animation.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fakeAudio(page, "running");
    const errors = await open(page);
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    const controls: [string, Locator][] = [
      ["call to action", page.getByRole("button", { name: "Play the recorded run" })],
      ["sound toggle", page.getByRole("button", { name: "Sound cues" })],
      // Pressing the clean pill would replace the blocked verdict and its payload controls, so press the pressed one.
      ["gate run pill", page.getByRole("button", { name: /Test Broken Site/ })],
      ["selected integration tab", page.getByRole("tab", { name: "Cursor / Claude Code" })],
      ["integration tab", page.getByRole("tab", { name: "CLI Pre-Flight" })],
      ["payload format", page.getByRole("group", { name: "Payload format" }).getByRole("button", { name: "Prompt" })],
      ["copy", page.getByRole("button", { name: "Copy", exact: true })],
      ["journey node", page.getByRole("list", { name: /Recorded journey/ }).getByRole("button", { name: "Checkout" })],
      ["patch option", page.locator("label.option", { has: page.getByRole("radio", { name: /^round_percentages/ }) })],
      ["tour step", page.getByRole("link", { name: /Try to fool the gates/ })],
    ];
    const look = (control: Locator) => control.evaluate((node) => {
      const style = getComputedStyle(node);
      return [style.transform, style.backgroundColor, style.borderTopColor, style.color].join(" | ");
    });
    for (const [name, control] of controls) {
      await control.scrollIntoViewIfNeeded();
      await control.hover();
      const resting = await look(control);
      await page.mouse.down();
      expect(await look(control), name).not.toBe(resting);
      await page.mouse.up();
    }
    expect(errors).toEqual([]);
  });

  test("a held press draws an ink rim at 3:1 or better on every interactive card, not only a scale", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fakeAudio(page, "running");
    const errors = await open(page);
    const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    const rimmed: [string, Locator][] = [
      ["gate run pill", page.getByRole("button", { name: /Test Broken Site/ })],
      ["journey node", page.getByRole("list", { name: /Recorded journey/ }).getByRole("button", { name: "HTTP 500" })],
      ["patch option", page.locator("label.option", { has: page.getByRole("radio", { name: /^round_percentages/ }) })],
      ["selected patch option", page.locator("label.option", { has: page.getByRole("radio", { name: /^null_coupon_only/ }) })],
      ["screenshot card", page.locator("a.shot").first()],
      ["sound toggle", page.getByRole("button", { name: "Sound cues" })],
      ["integration tab", page.getByRole("tab", { name: "CLI Pre-Flight" })],
      ["trail copy", page.getByRole("button", { name: "Copy the reproduction trail" })],
      ["command copy", page.getByRole("button", { name: "Copy", exact: true })],
    ];
    // Held, then released away from the control, so no press lands as a click.
    const hold = async (control: Locator, read: (node: Element) => string) => {
      await control.scrollIntoViewIfNeeded();
      await control.hover();
      await page.mouse.down();
      const held = await control.evaluate(read);
      await page.mouse.move(1, 1);
      await page.mouse.up();
      return held;
    };
    for (const [name, control] of rimmed) {
      const rim = await hold(control, (node) => getComputedStyle(node).borderTopColor);
      expect(rim, name).toBe(INK);
      expect(contrast(rim, background), name).toBeGreaterThanOrEqual(3);
    }

    // A tour card is a cell of a grid with no border of its own, so its press is an inset ring.
    const ring = await hold(page.getByRole("link", { name: /Try to fool the gates/ }), (node) => getComputedStyle(node).boxShadow);
    const ringColor = ring.match(/rgba?\([^)]+\)/)?.[0] ?? "";
    expect(ring).toContain("inset");
    expect(contrast(ringColor, background)).toBeGreaterThanOrEqual(3);

    // The light primary call to action dims when held and keeps its dark label legible.
    const primary = page.getByRole("button", { name: "Play the recorded run" });
    const [fill, label] = (await hold(primary, (node) => `${getComputedStyle(node).backgroundColor}|${getComputedStyle(node).color}`)).split("|") as [string, string];
    expect(fill).not.toBe(INK);
    expect(contrast(fill, label)).toBeGreaterThanOrEqual(4.5);
    expect(errors).toEqual([]);
  });

  test("copying the reproduction trail is spoken politely, names what was copied, and repeats on a second press", async ({ page }) => {
    const errors = await open(page);
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    const announce = page.locator("#copy-announce");
    await expect(announce).toHaveAttribute("aria-live", "polite");
    await announce.evaluate((node) => {
      const log: string[] = [];
      Object.assign(window, { __live: log });
      new MutationObserver(() => log.push(node.textContent ?? "")).observe(node, { childList: true, characterData: true, subtree: true });
    });
    const writes = () => page.evaluate(() => (window as unknown as { __clipboard: { writes: string[] } }).__clipboard.writes);

    const copy = page.getByRole("button", { name: "Copy the reproduction trail" });
    await copy.focus();
    await page.keyboard.press("Enter");
    await expect(announce).toHaveText("Copied the reproduction trail to the clipboard.");
    await expect(copy).toBeFocused();
    await expect(copy).toHaveText("Copied");
    const [trail] = await writes();
    const lines = trail!.split("\n");
    expect(lines).toHaveLength(8);
    expect(lines[0]).toBe("1. Open http://127.0.0.1:5050/");
    expect(lines[7]).toMatch(/^8\. Click button .+ -> HTTP 500 on POST \/api\/provision-cluster$/);

    await page.keyboard.press("Enter");
    await expect.poll(() => page.evaluate(() => (window as unknown as { __live: string[] }).__live))
      .toEqual(["Copied the reproduction trail to the clipboard.", "", "Copied the reproduction trail to the clipboard."]);
    await expect(copy).toBeFocused();
    expect(await writes()).toHaveLength(2);
    expect(errors).toEqual([]);
  });

  test("copy says what happened, aloud too, and a second press never sticks the label on Copied", async ({ page }) => {
    const errors = await open(page);
    const copy = page.getByRole("button", { name: "Copy", exact: true });
    const announce = page.locator("#copy-announce");
    await expect(announce).toHaveAttribute("aria-live", "polite");
    const writes = () => page.evaluate(() => (window as unknown as { __clipboard: { writes: string[] } }).__clipboard.writes);

    await copy.focus();
    await page.keyboard.press("Enter");
    const copied = page.getByRole("button", { name: "Copied" });
    await expect(copied).toHaveAttribute("data-state", "copied");
    await expect(announce).toHaveText("Copied to the clipboard.");
    expect(await writes()).toEqual([expect.stringContaining("git clone https://github.com/FrankieBiz/Faultline.git && cd Faultline")]);

    // Pressing again while it reads "Copied" used to make "Copied" the label it restored to.
    await page.keyboard.press("Enter");
    await expect(copied).toBeFocused();
    await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeVisible({ timeout: 4000 });
    await expect(page.getByRole("button", { name: "Copy", exact: true })).not.toHaveAttribute("data-state");

    // A labelled copy button keeps its name, so only the live region can say the copy failed.
    await page.evaluate(() => { (window as unknown as { __clipboard: { refuse: boolean } }).__clipboard.refuse = true; });
    const snippet = page.getByRole("button", { name: "Copy Cursor / Claude Code" });
    await snippet.focus();
    await page.keyboard.press("Enter");
    await expect(snippet).toHaveText("Select and copy");
    await expect(snippet).toHaveAttribute("data-state", "failed");
    await expect(announce).toHaveText("Copy was blocked. Select the text and copy it.");
    await expect(snippet).toHaveText("Copy", { timeout: 4000 });
    expect(errors).toEqual([]);
  });
});

test.describe("sound cues", () => {
  test("are off by default, toggle from the keyboard, persist, and close their context when muted", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fakeAudio(page, "running");
    const errors = await open(page);
    const toggle = page.getByRole("button", { name: "Sound cues" });
    await expect(toggle).toHaveAttribute("aria-pressed", "false");

    // Muted: a blocked gate run makes no audio context at all.
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    await expect(page.locator("#gate-verdict")).toContainText("Deployment blocked");
    expect(await audio(page)).toEqual({ contexts: [], oscillators: [] });

    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect.poll(async () => (await audio(page)).oscillators).toEqual(RESOLVE);
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    await expect.poll(async () => (await audio(page)).oscillators).toEqual(CATASTROPHE);
    expect((await audio(page)).contexts).toEqual(["running"]);

    await page.reload();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");

    // Space mutes; the context is closed rather than left holding the audio device.
    await page.getByRole("button", { name: /Test Clean Site/ }).click();
    await expect.poll(async () => (await audio(page)).oscillators).toEqual(RESOLVE);
    await toggle.focus();
    await page.keyboard.press("Space");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect.poll(async () => (await audio(page)).contexts).toEqual(["closed"]);
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    await expect(page.locator("#gate-verdict")).toContainText("Deployment blocked");
    expect(await audio(page)).toEqual({ contexts: ["closed"], oscillators: [] });
    expect(await page.evaluate(() => localStorage.getItem("faultline.sound"))).toBe("off");
    expect(errors).toEqual([]);
  });

  for (const mode of ["autoplay-blocked", "resume-rejects"] as const) {
    test(`a context the browser will not start (${mode}) is closed, never left suspended, and drops its cue`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      await fakeAudio(page, mode);
      const errors = await open(page);
      const toggle = page.getByRole("button", { name: "Sound cues" });
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-pressed", "true");
      await expect.poll(async () => (await audio(page)).contexts, { timeout: 2000 }).toEqual(["closed"]);

      // The next cue tries a fresh context instead of reviving the dead one, and closes that too.
      await page.getByRole("button", { name: /Test Broken Site/ }).click();
      await expect(page.locator("#gate-verdict")).toContainText("Deployment blocked");
      await expect.poll(async () => (await audio(page)).contexts, { timeout: 2000 }).toEqual(["closed", "closed"]);
      await page.waitForTimeout(700);
      expect(await audio(page)).toEqual({ contexts: ["closed", "closed"], oscillators: [] });
      await expect(toggle).toHaveAttribute("aria-pressed", "true");
      expect(errors).toEqual([]);
    });
  }

  test("a browser that cannot open an audio device keeps the toggle working and the page silent", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fakeAudio(page, "constructor-throws");
    const errors = await open(page);
    const toggle = page.getByRole("button", { name: "Sound cues" });
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    await expect(page.locator("#gate-verdict")).toContainText("Deployment blocked");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(await audio(page)).toEqual({ contexts: [], oscillators: [] });
    expect(errors).toEqual([]);
  });

  test("a browser without Web Audio shows no toggle", async ({ page }) => {
    await fakeAudio(page, "absent", "on");
    const errors = await open(page);
    await expect(page.locator("#sound-toggle")).toBeHidden();
    await expect(page.getByRole("button", { name: "Sound cues" })).toHaveCount(0);
    await page.getByRole("button", { name: /Test Broken Site/ }).click();
    await expect(page.locator("#gate-verdict")).toContainText("Deployment blocked", { timeout: 5000 });
    expect(errors).toEqual([]);
  });

  test("a live run that finishes before any gesture stays silent; one watched after a click sounds", async ({ page }) => {
    await fakeAudio(page, "running", "on");
    const runs: Record<string, number> = {};
    const run = (id: string, finished: boolean) => ({
      id, defect_id: "coupon_case_sensitive", state: finished ? "finished" : "running", outcome: finished ? "verified" : null,
      events: [
        { stage: "baseline", status: "running", t_ms: 0 },
        ...(finished ? [{ stage: "done", status: "finished", t_ms: 9000, data: { outcome: "verified" } }] : []),
      ],
      attempts: [],
    });
    // The live service is another origin, so it answers CORS as the real one does.
    const headers = { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET, POST" };
    await page.context().route(`${LIVE}/api/live/**`, (route) => {
      const method = route.request().method();
      const path = new URL(route.request().url()).pathname;
      if (method === "OPTIONS") return route.fulfill({ status: 204, headers });
      if (path === "/api/live/status") {
        return route.fulfill({ headers, json: { available: true, model: "muse-spark-1.3", provider: "meta", classification: "meta_model", limits: { daily_remaining: 5, per_client_per_hour: 3 } } });
      }
      if (path === "/api/live/ledger") return route.fulfill({ headers, json: {} });
      if (path === "/api/live/runs" && method === "POST") return route.fulfill({ status: 202, headers, json: { run_id: RUN_ID.replace("5b0e", "6c1f") } });
      const id = path.split("/").at(-1)!;
      const seen = (runs[id] ?? 0) + 1;
      runs[id] = seen;
      // Each run reports running once, then finished.
      return route.fulfill({ headers, json: run(id, seen > 1) });
    });
    const errors = await open(page, `/?live=${encodeURIComponent(LIVE)}#run=${RUN_ID}`);
    const toggle = page.getByRole("button", { name: "Sound cues" });
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    // The linked run settles while the visitor has not touched the page: no context, no cue.
    await expect(page.locator("#live-result")).toContainText("Verified: the bug is repaired", { timeout: 8000 });
    expect(await audio(page)).toEqual({ contexts: [], oscillators: [] });

    await page.getByRole("button", { name: "Plant this bug and repair it" }).click();
    await expect.poll(async () => (await audio(page)).oscillators, { timeout: 8000 }).toEqual(RESOLVE);
    expect((await audio(page)).contexts).toEqual(["running"]);
    expect(errors).toEqual([]);
  });
});
