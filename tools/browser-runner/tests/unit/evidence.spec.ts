import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { ArtifactStore, truncateUtf8 } from "../../src/evidence.js";

test.describe("truncateUtf8", () => {
  test("keeps short text and marks truncated text", () => {
    expect(truncateUtf8("short", 10)).toEqual({ text: "short", truncated: false });
    const result = truncateUtf8("x".repeat(30), 10);
    expect(result.truncated).toBe(true);
    expect(result.text).toBe(`${"x".repeat(10)}…[truncated 20 bytes]`);
  });
});

test.describe("ArtifactStore", () => {
  test("hashes written files and refuses paths outside its root", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "faultline-artifacts-"));
    try {
      const store = new ArtifactStore(root);
      await store.init();
      const entry = await store.writeJson("network_log", "network.json", { ok: true });
      const expectedBytes = `${JSON.stringify({ ok: true }, null, 2)}\n`;
      expect(entry.relative_path).toBe("network.json");
      expect(entry.size_bytes).toBe(Buffer.byteLength(expectedBytes));
      expect(entry.sha256).toBe(createHash("sha256").update(expectedBytes).digest("hex"));
      expect(() => store.resolve("../escape.txt")).toThrow(/escapes/);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
