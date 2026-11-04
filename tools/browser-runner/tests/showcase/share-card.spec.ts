import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

/**
 * The judge page's share card: the head tags that X, LinkedIn, Discord and Slack read, and the image
 * files they point at (rendered by tools/social/og-card/render.mjs). This keeps the unfurl from
 * silently falling back to a cropped or mislabeled screenshot again.
 */
const DOCS = resolve(fileURLToPath(import.meta.url), "../../../../../docs");
const SITE = "https://frankiebiz.github.io/Faultline/";
const MAX_BYTES = 1_000_000;

interface Head { meta: Record<string, string[]>; canonical: string[] }

/** Reads width and height from a PNG's IHDR chunk. */
function pngSize(file: string): { width: number; height: number } {
  const buf = readFileSync(file);
  expect(buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])), `${file} is a PNG`).toBe(true);
  expect(buf.toString("latin1", 12, 16)).toBe("IHDR");
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

/** Maps an absolute URL on the Pages site to its file under docs/. */
function docsFile(url: string): string {
  expect(url.startsWith(SITE), `${url} is under ${SITE}`).toBe(true);
  const file = resolve(DOCS, "." + decodeURIComponent(new URL(url).pathname.slice(new URL(SITE).pathname.length - 1)));
  expect(file.startsWith(DOCS + sep), `${url} stays inside docs/`).toBe(true);
  return file;
}

test.describe("share card", () => {
  let head: Head = { meta: {}, canonical: [] };

  test.beforeEach(async ({ page }) => {
    const html = readFileSync(resolve(DOCS, "index.html"), "utf8");
    // The browser's own parser reads the head; DOMParser runs no scripts.
    head = await page.evaluate((source) => {
      const doc = new DOMParser().parseFromString(source, "text/html");
      const meta: Record<string, string[]> = {};
      for (const el of doc.head.querySelectorAll("meta[property], meta[name]")) {
        const key = el.getAttribute("property") ?? el.getAttribute("name") ?? "";
        (meta[key] ??= []).push(el.getAttribute("content") ?? "");
      }
      const canonical = [...doc.head.querySelectorAll('link[rel="canonical"]')].map((link) => link.getAttribute("href") ?? "");
      return { meta, canonical };
    }, html);
  });

  /** The content of a tag that must appear exactly once. */
  function one(key: string): string {
    const values = head.meta[key] ?? [];
    expect(values, `exactly one ${key}`).toHaveLength(1);
    return values[0] ?? "";
  }

  test("the head declares one large-image card with the same image for every platform", () => {
    expect(one("twitter:card")).toBe("summary_large_image");
    const image = one("og:image");
    expect(one("twitter:image")).toBe(image);
    expect(image).toMatch(/^https:\/\//);
    expect(image.startsWith(SITE)).toBe(true);
    // X caches card images by URL for about a week: a changed card gets a new -vN name, never an overwrite.
    expect(image).toMatch(/-v\d+\.png$/);
    if (head.meta["og:image:secure_url"]) expect(one("og:image:secure_url")).toBe(image);
    if (head.meta["og:image:type"]) expect(one("og:image:type")).toBe("image/png");
    expect(one("og:image:alt").trim().length).toBeGreaterThan(0);
  });

  test("the canonical URL, og:url and the text limits match what the crawlers accept", () => {
    expect(head.canonical).toHaveLength(1);
    expect(head.canonical[0]).toBe(one("og:url"));
    expect(one("og:url")).toBe(SITE);
    const title = one("twitter:title");
    const description = one("twitter:description");
    const alt = one("twitter:image:alt");
    expect(title.trim().length).toBeGreaterThan(0);
    expect(title.length).toBeLessThanOrEqual(70);
    expect(description.trim().length).toBeGreaterThan(0);
    expect(description.length).toBeLessThanOrEqual(200);
    expect(alt.trim().length).toBeGreaterThan(0);
    expect(alt.length).toBeLessThanOrEqual(420);
  });

  test("the card file exists under docs/, is 1200x630 as declared, and is under 1 MB", () => {
    const file = docsFile(one("og:image"));
    expect(existsSync(file), `${file} exists`).toBe(true);
    expect(statSync(file).size).toBeLessThan(MAX_BYTES);
    const { width, height } = pngSize(file);
    expect({ width, height }).toEqual({ width: 1200, height: 630 });
    expect(Number(one("og:image:width"))).toBe(width);
    expect(Number(one("og:image:height"))).toBe(height);
  });

  test("every rendered share asset is the size its name and platform require", () => {
    const assets: [string, number, number][] = [
      ["faultline-card-v1.png", 1200, 630],
      ["faultline-github-1280x640.png", 1280, 640],
      ["faultline-gallery-1920x1080.png", 1920, 1080],
      ["faultline-201-trap-1080x1350.png", 1080, 1350],
      ["faultline-201-trap-1200x675.png", 1200, 675],
    ];
    for (const [name, width, height] of assets) {
      const file = resolve(DOCS, "assets/og", name);
      expect(existsSync(file), `${name} exists`).toBe(true);
      expect(statSync(file).size, `${name} is under 1 MB`).toBeLessThan(MAX_BYTES);
      expect(pngSize(file), name).toEqual({ width, height });
    }
  });
});
