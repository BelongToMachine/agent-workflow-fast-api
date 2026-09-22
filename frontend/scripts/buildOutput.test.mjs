import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { brotliDecompressSync } from "node:zlib";

const projectRoot = path.resolve(import.meta.dirname, "..");
const distRoot = path.join(projectRoot, "dist");

function collectFiles(directory, suffix) {
  const files = [];

  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const filePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectFiles(filePath, suffix));
    } else if (entry.name.endsWith(suffix)) {
      files.push(filePath);
    }
  }

  return files;
}

function getEntryAsset() {
  assert.ok(existsSync(path.join(distRoot, "index.html")), "Run `bun run build` before this test");

  const html = readFileSync(path.join(distRoot, "index.html"), "utf8");
  const entryMatch = html.match(/<script[^>]+src="([^"]+\.js)"/);
  assert.ok(entryMatch, "index.html should reference an entry JavaScript asset");

  const assetPath = new URL(entryMatch[1], "https://pages.invalid").pathname;
  const entryPath = path.join(distRoot, assetPath.replace(/^\/+/, ""));
  assert.ok(existsSync(entryPath), `Entry asset does not exist: ${entryMatch[1]}`);
  return entryPath;
}

test("production asset references honor the configured Pages asset base", () => {
  const expectedBase = process.env.EXPECTED_ASSET_BASE_URL;
  if (!expectedBase) {
    return;
  }

  const html = readFileSync(path.join(distRoot, "index.html"), "utf8");
  const assetReferences = [...html.matchAll(/(?:src|href)="([^"]+)"/g)]
    .map((match) => match[1])
    .filter((reference) => reference.includes("/assets/"));

  assert.ok(assetReferences.length > 0, "index.html should reference built assets");
  for (const reference of assetReferences) {
    assert.ok(
      reference.startsWith(expectedBase),
      `Asset reference should start with ${expectedBase}: ${reference}`,
    );
  }
});

test("production asset references use the shared release directory", () => {
  const expectedReleaseId = process.env.EXPECTED_ASSET_RELEASE_ID;
  if (!expectedReleaseId) {
    return;
  }

  const html = readFileSync(path.join(distRoot, "index.html"), "utf8");
  const assetReferences = [...html.matchAll(/(?:src|href)="([^"]+)"/g)]
    .map((match) => match[1])
    .filter((reference) => reference.includes("/assets/"));

  assert.ok(assetReferences.length > 0, "index.html should reference built assets");
  for (const reference of assetReferences) {
    assert.match(
      reference,
      new RegExp(`/assets/${expectedReleaseId}/`),
      `Asset reference should use release directory ${expectedReleaseId}: ${reference}`,
    );
  }
});

test("Pages builds include cross-origin headers for static assets", () => {
  if (!process.env.EXPECTED_ASSET_BASE_URL) {
    return;
  }

  const headersPath = path.join(distRoot, "_headers");
  assert.ok(existsSync(headersPath), "Pages builds should include a _headers file");
  assert.match(
    readFileSync(headersPath, "utf8"),
    /Access-Control-Allow-Origin:\s*\*/,
    "Pages static assets should allow the main site origin",
  );
});

test("production browser code uses the configured FastAPI origin", () => {
  const expectedApiBase = process.env.EXPECTED_API_BASE_URL;
  if (!expectedApiBase) {
    return;
  }

  const assetsDirectory = path.join(distRoot, "assets");
  const javascriptFiles = collectFiles(assetsDirectory, ".js")
    .map((filePath) => readFileSync(filePath, "utf8"));

  assert.ok(
    javascriptFiles.some((source) => source.includes(expectedApiBase)),
    `Built browser code should include the configured FastAPI origin: ${expectedApiBase}`,
  );
});

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

test("Docker production builds pass the Pages asset base to Vite", () => {
  const dockerfile = readFileSync(path.join(projectRoot, "Dockerfile"), "utf8");
  const composeFile = readFileSync(path.join(projectRoot, "compose.production.yaml"), "utf8");
  const deployScript = readFileSync(path.join(projectRoot, "deploy/deploy-frontend.sh"), "utf8");

  assert.match(dockerfile, /ARG VITE_ASSET_BASE_URL/);
  assert.match(dockerfile, /VITE_ASSET_BASE_URL=\$\{VITE_ASSET_BASE_URL\}/);
  assert.match(dockerfile, /ARG VITE_RELEASE_ID=dev/);
  assert.match(dockerfile, /VITE_RELEASE_ID=\$\{VITE_RELEASE_ID\}/);
  assert.match(composeFile, /VITE_ASSET_BASE_URL:\s*\$\{VITE_ASSET_BASE_URL:-\/\}/);
  assert.match(composeFile, /VITE_RELEASE_ID:\s*\$\{VITE_RELEASE_ID:-dev\}/);
  assert.match(deployScript, /export VITE_RELEASE_ID="\$SHA"/);
});

test("production builds send FastAPI requests through the SG Caddy origin", () => {
  const productionEnv = readFileSync(
    path.join(projectRoot, "deploy/frontend.build.production.example"),
    "utf8",
  );

  assert.match(
    productionEnv,
    /^FRONTEND_API_URL=https:\/\/copilot\.asianodeatlas\.com$/m,
    "Production FastAPI requests should use the same-origin Caddy entrypoint",
  );
  assert.match(productionEnv, /^NEXT_PUBLIC_API_MODE=fastapi-direct$/m);
});

test("FastAPI browser configuration has one canonical Vite URL variable", () => {
  const viteConfig = readFileSync(path.join(projectRoot, "vite.config.js"), "utf8");
  const modeConfig = readFileSync(path.join(projectRoot, "src/lib/backend/mode.ts"), "utf8");
  const dockerfile = readFileSync(path.join(projectRoot, "Dockerfile"), "utf8");
  const productionCompose = readFileSync(path.join(projectRoot, "compose.production.yaml"), "utf8");
  const stagingCompose = readFileSync(path.join(projectRoot, "compose.staging.yaml"), "utf8");

  assert.match(viteConfig, /env\.VITE_FASTAPI_URL/);
  assert.match(
    viteConfig,
    /['"]process\.env\.VITE_FASTAPI_URL['"]:\s*JSON\.stringify\(fastApiTarget\)/,
    "The canonical Vite API URL must also be available to legacy process.env consumers",
  );
  assert.match(modeConfig, /import\.meta\.env\.VITE_FASTAPI_URL/);
  for (const source of [viteConfig, modeConfig, dockerfile, productionCompose, stagingCompose]) {
    assert.doesNotMatch(source, /(?:NEXT_PUBLIC_)?FASTAPI_BASE_URL/);
  }
});
