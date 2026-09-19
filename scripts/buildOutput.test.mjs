import assert from "node:assert/strict";
import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { brotliDecompressSync } from "node:zlib";

const projectRoot = path.resolve(import.meta.dirname, "..");
const distRoot = path.join(projectRoot, "dist");

function getEntryAsset() {
  assert.ok(existsSync(path.join(distRoot, "index.html")), "Run `bun run build` before this test");

  const html = readFileSync(path.join(distRoot, "index.html"), "utf8");
  const entryMatch = html.match(/<script[^>]+src="([^"]+\.js)"/);
  assert.ok(entryMatch, "index.html should reference an entry JavaScript asset");

  const entryPath = path.join(distRoot, entryMatch[1].replace(/^\//, ""));
  assert.ok(existsSync(entryPath), `Entry asset does not exist: ${entryMatch[1]}`);
  return entryPath;
}

test("production entry JavaScript is split and precompressed", () => {
  const entryPath = getEntryAsset();
  const entrySize = statSync(entryPath).size;
  const brotliPath = `${entryPath}.br`;

  assert.ok(entrySize < 1_500_000, `Entry JavaScript is still too large: ${entrySize} bytes`);
  assert.ok(existsSync(brotliPath), `Missing Brotli asset: ${path.relative(distRoot, brotliPath)}`);
  assert.ok(
    statSync(brotliPath).size < entrySize,
    `Brotli asset should be smaller than the source asset: ${statSync(brotliPath).size} >= ${entrySize}`,
  );
  assert.deepEqual(brotliDecompressSync(readFileSync(brotliPath)), readFileSync(entryPath));
});
